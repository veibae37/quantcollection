import math
import datetime
import numpy as np
import pandas as pd
from datetime import date

# 尝试导入 MiniQMT 库（在 VSC MiniQMT 环境下生效）
try:
    from xtquant import xtdata
    from xtquant.xttrader import XtQuantTrader
    from xtquant.xttype import StockAccount
    from xtquant import xtconstant
except ImportError:
    pass


# ==========================================
# 1. 辅助函数：计算期权到期日与剩余天数
# ==========================================
def get_third_wednesday(year: int, month: int) -> date:
    """计算某年某月的第三个星期三（上交所/深交所期权到期日）"""
    first_day = date(year, month, 1)
    w = first_day.weekday()  # 0: Mon, ..., 2: Wed
    days_to_wed = (2 - w) % 7
    first_wed = 1 + days_to_wed
    third_wed = first_wed + 14
    return date(year, month, third_wed)


def get_days_to_settlement(expire_date_int: int) -> int:
    """
    计算距离到期日的天数
    expire_date_int: YYYYMMDD (如 20260826)
    """
    year = expire_date_int // 10000
    month = (expire_date_int % 10000) // 100
    expire_d = get_third_wednesday(year, month)
    today_d = date.today()
    days = (expire_d - today_d).days
    return max(days, 1)


# ==========================================
# 2. 核心组合计算类：合成期货/组合单对
# ==========================================
class OptionPair:
    """
    用于计算单边合成（Call与Put组合）的最佳成交价格与挂单量
    组合 1 (BCSP / Sell Call + Buy Put): 买入Put(卖价), 卖出Call(买价)
    组合 2 (BPSC / Buy Call + Sell Put): 买入Call(卖价), 卖出Put(买价)
    """

    def __init__(
        self,
        option_type: str,
        code_call: str,
        code_put: str,
        strike: float,
        call_depth: dict,
        put_depth: dict,
        days_to_settlement: int,
        interest_rate: float = 0.03,
    ):
        self.option_type = option_type  # 'BCSP' 或 'BPSC'
        self.code_call = code_call
        self.code_put = code_put
        self.strike = strike
        self.days = days_to_settlement
        self.r = interest_rate

        self.call_depth = call_depth
        self.put_depth = put_depth

    def get_best_price_and_amount(self, desir_mount: int = 1):
        """根据盘口五档计算即时能撮合的套利成本与可用数量"""
        # 折现因子 PV = Strike * exp(-r * T)
        pv_strike = self.strike * math.exp(-self.r * (self.days / 365.0))

        if self.option_type == "BCSP":
            # 买Put(用Put卖一价 ask1) + 卖Call(用Call买一价 bid1)
            call_bid1 = self.call_depth.get("bid1", 0.0)
            call_bid_vol = self.call_depth.get("bid_vol1", 0)
            put_ask1 = self.put_depth.get("ask1", 0.0)
            put_ask_vol = self.put_depth.get("ask_vol1", 0)

            if call_bid1 <= 0 or put_ask1 <= 0:
                return {
                    "price": float("inf"),
                    "amount": 0,
                    "call_price": 0,
                    "put_price": 0,
                }

            # 现金流成本 = Buy_Put - Sell_Call - Discounted_Strike
            net_cost = put_ask1 - call_bid1 - pv_strike
            avail_amount = min(call_bid_vol, put_ask_vol)
            return {
                "price": net_cost,
                "amount": avail_amount,
                "call_price": call_bid1,
                "put_price": put_ask1,
            }

        elif self.option_type == "BPSC":
            # 买Call(用Call卖一价 ask1) + 卖Put(用Put买一价 bid1)
            call_ask1 = self.call_depth.get("ask1", 0.0)
            call_ask_vol = self.call_depth.get("ask_vol1", 0)
            put_bid1 = self.put_depth.get("bid1", 0.0)
            put_bid_vol = self.put_depth.get("bid_vol1", 0)

            if call_ask1 <= 0 or put_bid1 <= 0:
                return {
                    "price": float("inf"),
                    "amount": 0,
                    "call_price": 0,
                    "put_price": 0,
                }

            # 现金流成本 = Buy_Call - Sell_Put + Discounted_Strike
            net_cost = call_ask1 - put_bid1 + pv_strike
            avail_amount = min(call_ask_vol, put_bid_vol)
            return {
                "price": net_cost,
                "amount": avail_amount,
                "call_price": call_ask1,
                "put_price": put_bid1,
            }


# ==========================================
# 3. 主套利策略计算类 (从 fcb2016 移植)
# ==========================================
class BoxArbitrageStrategy:

    def __init__(
        self,
        interest_rate=0.03,
        actionpoint=12,
        desir_mount=1,
        limitordermark=10,
    ):
        """参数配置:

        interest_rate: 无风险利率 (如 0.03 表示 3%) actionpoint: 套利触发门槛（净利润点数）
        desir_mount: 期望下单手数量 limitordermark: 限价单/市价单切换阈值
        """
        self.interest_rate = interest_rate
        self.actionpoint = actionpoint
        self.desir_mount = desir_mount
        self.limitordermark = limitordermark
        self.holdingcostmark = 5.0
        self.liquidcostmark = 0.0

    def calculate_arbitrage(
        self,
        option_hq: pd.DataFrame,
        holding_df: pd.DataFrame,
        olist_df: pd.DataFrame,
    ):
        """盒式套利主计算逻辑

        :param option_hq: 行情数据表，包含 Call/Put 各行及五档行情
        :param holding_df: 当前账户持仓表 [code, side(0买/1卖), amount]
        :param olist_df: 期权合约信息表 [code, expire_date, strike,
        option_type('C'/'P')] :return: (order_list, trade_record)
        """
        # 1. 按行整理与过滤当月合约
        current_month = olist_df["expire_date"].iloc[0]
        cur_olist = olist_df[olist_df["expire_date"] == current_month].copy()

        # 区分 Call 和 Put
        calls = (
            cur_olist[cur_olist["option_type"] == "C"]
            .sort_values("strike")
            .reset_index(drop=True)
        )
        puts = (
            cur_olist[cur_olist["option_type"] == "P"]
            .sort_values("strike")
            .reset_index(drop=True)
        )

        len_div2 = len(calls)
        if len_div2 == 0 or len(calls) != len(puts):
            return None, None

        days_to_settlement = get_days_to_settlement(current_month)

        # 2. 匹配不同行权价进行 Box Spread 对比 (BCSP vs BPSC)
        # 第一组：BCSP (Sell Call + Buy Put at Strike K1)
        bcsp_pairs = []
        for i in range(len_div2):
            c_code = calls.loc[i, "code"]
            p_code = puts.loc[i, "code"]
            strike = calls.loc[i, "strike"]

            c_depth = (
                option_hq.loc[c_code].to_dict()
                if c_code in option_hq.index
                else {}
            )
            p_depth = (
                option_hq.loc[p_code].to_dict()
                if p_code in option_hq.index
                else {}
            )

            pair = OptionPair(
                "BCSP",
                c_code,
                p_code,
                strike,
                c_depth,
                p_depth,
                days_to_settlement,
                self.interest_rate,
            )
            res = pair.get_best_price_and_amount(self.desir_mount)
            # 使用字典结构保存结果，支持字符串 Key 访问
            bcsp_pairs.append({
                "pair": pair,
                "price": res["price"],
                "amount": res["amount"],
                "call_price": res["call_price"],
                "put_price": res["put_price"],
                "idx": i,
            })

        # 第二组：BPSC (Buy Call + Sell Put at Strike K2)
        bpsc_pairs = []
        for i in range(len_div2):
            c_code = calls.loc[i, "code"]
            p_code = puts.loc[i, "code"]
            strike = calls.loc[i, "strike"]

            c_depth = (
                option_hq.loc[c_code].to_dict()
                if c_code in option_hq.index
                else {}
            )
            p_depth = (
                option_hq.loc[p_code].to_dict()
                if p_code in option_hq.index
                else {}
            )

            pair = OptionPair(
                "BPSC",
                c_code,
                p_code,
                strike,
                c_depth,
                p_depth,
                days_to_settlement,
                self.interest_rate,
            )
            res = pair.get_best_price_and_amount(self.desir_mount)
            # 使用字典结构保存结果，支持字符串 Key 访问
            bpsc_pairs.append({
                "pair": pair,
                "price": res["price"],
                "amount": res["amount"],
                "call_price": res["call_price"],
                "put_price": res["put_price"],
                "idx": i,
            })

        # 3. 寻找价格最优组合 (此时元素是字典，支持 x["price"] 访问)
        best_bcsp = min(bcsp_pairs, key=lambda x: x["price"])
        best_bpsc = min(bpsc_pairs, key=lambda x: x["price"])

        tot_cost_bcsp = best_bcsp["price"]
        tot_cost_bpsc = best_bpsc["price"]

        # 4. 计算盒式套利总收益 (Box Profit)
        box_profit = -(tot_cost_bcsp + tot_cost_bpsc)

        # 判断是否触发套利条件
        if box_profit < self.actionpoint:
            return None, None  # 未达到收益门槛

        # 5. 构建 4 腿订单列表
        bcsp_idx = best_bcsp["idx"]
        bpsc_idx = best_bpsc["idx"]

        orders = [
            # Leg 1: Sell Call (BCSP)
            {
                "code": calls.loc[bcsp_idx, "code"],
                "action": 1,
                "side": 2,
                "qty": self.desir_mount,
                "price": best_bcsp["call_price"],
            },
            # Leg 2: Buy Put (BCSP)
            {
                "code": puts.loc[bcsp_idx, "code"],
                "action": 1,
                "side": 1,
                "qty": self.desir_mount,
                "price": best_bcsp["put_price"],
            },
            # Leg 3: Buy Call (BPSC)
            {
                "code": calls.loc[bpsc_idx, "code"],
                "action": 1,
                "side": 1,
                "qty": self.desir_mount,
                "price": best_bpsc["call_price"],
            },
            # Leg 4: Sell Put (BPSC)
            {
                "code": puts.loc[bpsc_idx, "code"],
                "action": 1,
                "side": 2,
                "qty": self.desir_mount,
                "price": best_bpsc["put_price"],
            },
        ]

        # 6. 根据已有持仓逻辑自动调整开平仓状态
        if not holding_df.empty:
            for ord_item in orders:
                matched_hold = holding_df[holding_df["code"] == ord_item["code"]]
                if not matched_hold.empty:
                    hold_side = matched_hold.iloc[0]["side"]
                    if ord_item["side"] != hold_side:
                        ord_item["action"] = 2

        orders_df = pd.DataFrame(orders)

        trade_record = {
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "box_profit": box_profit,
            "orders": orders,
        }

        return orders_df, trade_record


# ==========================================
# 4. MiniQMT 实盘/仿真发单执行对接
# ==========================================
class MiniQMTBoxTrader:

    def __init__(self, account_id: str, session_id: int = 123456):
        self.account_id = account_id
        self.session_id = session_id
        self.account = StockAccount(account_id, "OPTION")  # 期权账户
        self.trader = None

    def connect_qmt(self, qmt_path: str):
        """连接 MiniQMT 终端"""
        self.trader = XtQuantTrader(qmt_path, self.session_id)
        self.trader.start()
        res = self.trader.connect()
        if res == 0:
            print("Successfully connected to MiniQMT!")
            self.trader.subscribe(self.account)
        else:
            print(f"Failed to connect MiniQMT, Error code: {res}")

    def execute_box_orders(self, orders_df: pd.DataFrame):
        """向 MiniQMT 提交 4 腿套利订单"""
        if self.trader is None or orders_df is None or orders_df.empty:
            return

        for idx, row in orders_df.iterrows():
            code = row["code"]
            side = row["side"]  # 1: 买, 2: 卖
            action = row["action"]  # 1: 开仓, 2: 平仓
            qty = int(row["qty"])
            price = float(row["price"])

            # 映射 MiniQMT 的操作类型
            if side == 1 and action == 1:
                order_type = xtconstant.OPTION_BUY_OPEN  # 买入开仓
            elif side == 1 and action == 2:
                order_type = xtconstant.OPTION_BUY_CLOSE  # 买平/买入平仓
            elif side == 2 and action == 1:
                order_type = xtconstant.OPTION_SELL_OPEN  # 卖出开仓
            else:
                order_type = xtconstant.OPTION_SELL_CLOSE  # 卖平/卖出平仓

            # 报单类型: 固定价格/限价单
            price_type = xtconstant.FIX_PRICE

            # 发送订单
            order_id = self.trader.passorder(
                order_type,
                price_type,
                self.account,
                code,
                price_type,
                price,
                qty,
                "Box_Arbitrage_Strategy",
                f"BoxSpread_{code}",
            )
            print(
                f"[Order Sent] Code: {code}, Type: {order_type}, Price:"
                f" {price}, Qty: {qty}, OrderID: {order_id}"
            )


# ==========================================
# 5. 主运行示例 (VSC 直接运行入口)
# ==========================================
def run_demo(
    interest_rate=0.03,
    actionpoint=0.0001,
    desir_mount=1,
    data_mode="demo",
    top_n=20,
    min_volume=1,
):
    """Run the read-only market-wide option scanner used by the web app.

    The scanner covers all discoverable SSE/SZSE ETF options and CFFEX equity
    index options.  It never connects to MiniQMT or submits an order.  The
    historical four-contract fixture was removed from the web path.
    """
    from option_market_scanner import run_option_market_scan

    return run_option_market_scan(
        data_mode=str(data_mode),
        top_n=int(top_n),
        interest_rate=float(interest_rate),
        actionpoint=float(actionpoint),
        desir_mount=int(desir_mount),
        min_volume=int(min_volume),
    )


if __name__ == "__main__":
    import json

    print(json.dumps(run_demo(data_mode="auto"), ensure_ascii=False, indent=2))
