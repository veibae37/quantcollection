from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount

# 1. 设定客户端路径（精确定位到 bin.x64 目录）
mini_qmt_path = r"D:\dict\DoubleQuant\bin.x64"
session_id = 123456
xt_trader = XtQuantTrader(mini_qmt_path, session_id)

# 2. 启动并连接
xt_trader.start()
connect_result = xt_trader.connect()

if connect_result == 0:
    print("VSCode 成功引入并连接 MiniQMT！")
    
# 3. 尝试订阅一个股票的 L1 实时行情作为验证
xtdata.subscribe_quote(stock_code='603380.SH', period='15m')

import time
from xtquant.xttype import StockAccount

# 假设前面的 connect() 已经成功
account_id = "34165036" 
acc = StockAccount(account_id)

# 1. 订阅账号状态
subscribe_result = xt_trader.subscribe(acc)
if subscribe_result == 0:
    print(f"✅ 账号 {account_id} 状态订阅成功！")
else:
    print("❌ 订阅失败！")

# ----------------- 核心修复在这里 -----------------
print("正在等待券商服务器同步底层数据...")
time.sleep(3)  # 强制暂停 3 秒钟，等待数据回传
# --------------------------------------------------

print(f"\n>>> 开始查询账号 {account_id} 的持仓信息...")

# 2. 再次查询持仓
positions = xt_trader.query_stock_positions(acc)

if positions:
    print(f"✅ 共查询到 {len(positions)} 条持仓记录：\n")
    print(f"{'股票代码':<12} | {'总持仓':<8} | {'可用持仓':<8} | {'建仓均价':<10} | {'当前市值'}")
    print("-" * 60)
    for pos in positions:
        print(f"{pos.stock_code:<12} | "
              f"{pos.volume:<10.0f} | "
              f"{pos.can_use_volume:<10.0f} | "
              f"{pos.open_price:<12.3f} | "
              f"{pos.market_value:.2f}")
else:
    print("⚠️ 等待后依然无持仓，请确认该账号在仿真端确实买入了股票。")