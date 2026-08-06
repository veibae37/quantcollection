# -*- coding: utf-8 -*-
import time
import pandas as pd
from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant import xtconstant
from xtquant.xttype import StockAccount
import datetime


MINI_QMT_PATH = r'C:\Users\baby liu\Desktop\中信建投\中信建投证券QMT仿真-交易端\userdata_mini' 
ACCOUNT_ID = '34165036'                      
ACTION_POINT = 12.0                                 # 触发套利的利润阈值 
FEE_ESTIMATE = 6.0                                  # 预估的4条腿总交易成本/滑点折损 (元)
POLL_INTERVAL = 0.5                                 # 盘口轮询间隔 (秒)

# 定义要监控的盒式套利合约组 (示例为上证50ETF期权)
# K1: 低行权价, K2: 高行权价
BOX_CONFIG = {
    'K1': 1600,
    'K2': 1700,
    'call_k1': '10011031.SH',  # K1 认购
    'put_k1':  '10011040.SH',  # K1 认沽
    'call_k2': '10011028.SH',  # K2 认购
    'put_k2':  '10011034.SH',  # K2 认沽
    'multiplier': 10000        # 合约乘数
}

# 需要订阅的合约列表
CONTRACT_LIST = [
    BOX_CONFIG['call_k1'], BOX_CONFIG['put_k1'], 
    BOX_CONFIG['call_k2'], BOX_CONFIG['put_k2']
]

# ==========================================
# 1. 交易回调类 (接收成交回报)
# ==========================================
class MyXtQuantCallback(XtQuantTraderCallback):
    def on_disconnected(self):
        print("[-] MiniQMT 交易终端连接断开")

    def on_stock_order(self, order):
        print(f"[委托回报] 合约: {order.stock_code}, 状态: {order.order_status}, 报单价: {order.price}")

    def on_stock_trade(self, trade):
        print(f"[成交回报] 合约: {trade.stock_code}, 成交价: {trade.traded_price}, 数量: {trade.traded_volume}")

    def on_stock_error(self, error):
        print(f"[交易错误] {error.error_msg}")

# ==========================================
# 2. 策略核心逻辑 (基于实时盘口)
# ==========================================
def check_box_arbitrage():
    """
    拉取五档行情并计算盒式套利空间
    返回: orders (订单列表), profit (净利润)
    """
    # 拉取最新快照
    tick_dict = xtdata.get_full_tick(CONTRACT_LIST)
    
    # 确保4个合约都有数据返回
    if len(tick_dict) < 4:
        return [], 0
        
    try:
        # 获取盘口买一/卖一价 (对价交易，保证立刻成交)
        # 盘口买价(Bid)是用来卖出的，盘口卖价(Ask)是用来买入的
        ask1_c1 = tick_dict[BOX_CONFIG['call_k1']]['askPrice'][0]  # 买入 Call K1 付出的价格
        bid1_p1 = tick_dict[BOX_CONFIG['put_k1']]['bidPrice'][0]   # 卖出 Put K1 收到的价格
        bid1_c2 = tick_dict[BOX_CONFIG['call_k2']]['bidPrice'][0]  # 卖出 Call K2 收到的价格
        ask1_p2 = tick_dict[BOX_CONFIG['put_k2']]['askPrice'][0]   # 买入 Put K2 付出的价格
        
        # 排除盘口为空 (价格为0) 的情况，防止跌停/涨停导致计算异常
        if ask1_c1 == 0 or bid1_p1 == 0 or bid1_c2 == 0 or ask1_p2 == 0:
            return [], 0

        # 计算每份合约的建仓总成本
        cost_per_unit = ask1_c1 - bid1_p1 - bid1_c2 + ask1_p2
        
        # 盒式套利到期理论收益
        payoff_per_unit = BOX_CONFIG['K2'] - BOX_CONFIG['K1']
        
        # 计算单张合约的净利润 (乘以乘数，扣除摩擦成本)
        profit = (payoff_per_unit - cost_per_unit) * BOX_CONFIG['multiplier'] - FEE_ESTIMATE
        
        if profit >= ACTION_POINT:
            # 构造订单队列
            orders = [
                # 动作 1: 买入开仓 Call K1
                {'code': BOX_CONFIG['call_k1'], 'type': xtconstant.OPT_BUY_OPEN,  'price': ask1_c1},
                # 动作 2: 卖出开仓 Put K1
                {'code': BOX_CONFIG['put_k1'],  'type': xtconstant.OPT_SELL_OPEN, 'price': bid1_p1},
                # 动作 3: 卖出开仓 Call K2
                {'code': BOX_CONFIG['call_k2'], 'type': xtconstant.OPT_SELL_OPEN, 'price': bid1_c2},
                # 动作 4: 买入开仓 Put K2
                {'code': BOX_CONFIG['put_k2'],  'type': xtconstant.OPT_BUY_OPEN,  'price': ask1_p2}
            ]
            return orders, profit
            
    except Exception as e:
        print(f"数据解析异常: {e}")
        
    return [], 0

# ==========================================
# 3. 订单执行引擎
# ==========================================
def execute_box_orders(orders, trader, account):
    """
    并发向 QMT 发送 4 条腿的订单
    """
    for order in orders:
        seq = trader.order_stock_async(
            account=account,
            stock_code=order['code'],
            order_type=order['type'],
            order_volume=1,  # 默认每次下单 1 张
            price_type=xtconstant.FIX_PRICE,
            price=order['price'],
            strategy_name="Box_Arbitrage_Live",
            order_remark="盒式套利发单"
        )
        print(f"[+] 发送指令 | 流水号: {seq} | 合约: {order['code']} | 价格: {order['price']}")

# ==========================================
# 主程序入口
# ==========================================
if __name__ == '__main__':
    print("="*40)
    print("启动 MiniQMT 期权盒式套利系统...")
    print("="*40)
    
    # 1. 初始化交易终端
    session_id = int(time.time())
    xt_trader = XtQuantTrader(MINI_QMT_PATH, session_id)
    
    # 2. 注册回调并启动后台线程
    xt_trader.register_callback(MyXtQuantCallback())
    xt_trader.start()
    
    # 3. 建立连接
    print(f"[*] 正在连接 QMT 终端, 路径: {MINI_QMT_PATH}")
    connect_result = xt_trader.connect()
    
    if connect_result == 0:
        print("[+] 连接成功！")
    else:
        print(f"[-] 连接失败，错误码: {connect_result}")
        print("请检查：1. QMT是否已启动并登录; 2. 是否开启极简模式; 3. 路径和账号是否正确。")
        import sys; sys.exit()
        
    # 4. 订阅账号
    account = StockAccount(ACCOUNT_ID, 'STOCK')
    xt_trader.subscribe(account)
    
    # 5. 订阅行情数据 (持续接收 Tick)
    print(f"[*] 正在订阅行情: {CONTRACT_LIST}")
    for code in CONTRACT_LIST:
        xtdata.subscribe_quote(code, period='tick', count=-1)
        
    # 给 QMT 几秒钟时间缓冲行情初始数据
    time.sleep(3) 

    # 6. 进入实盘高频轮询主循环
    print("[*] 进入监控模式，等待套利空间出现...")
    try:
        while True:
            # 检查信号
            orders, profit = check_box_arbitrage()
            
            if orders:
                print("\n" + "="*40)
                print(f"!!! 发现套利机会 !!!")
                print(f"当前无风险利润: {profit:.2f} 元 (阈值: {ACTION_POINT})")
                print("="*40)
                
                # 执行下单
                execute_box_orders(orders, xt_trader, account)
                
                # 下单后休眠一段时间，防止因未成交导致的重复疯狂发单
                # 实盘中这里通常需要加入订单状态检查逻辑 (未成交则撤单)
                print("[*] 发单完毕，休眠 10 秒防重发...")
                time.sleep(10) 
                
            # 控制轮询频率，降低 CPU 占用
            time.sleep(POLL_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n[*] 接收到停止指令，正在退出系统...")
        xt_trader.stop()