import time
import random
from xtquant import xtdata         # 🔴 引入行情模块
from xtquant import xtconstant
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount
import warnings
warnings.filterwarnings("ignore")

# ==========================================
# 1. 初始化交易引擎并连接 (与之前完全一致)
# ==========================================
mini_qmt_path = r'C:\Users\baby liu\Desktop\中信建投\中信建投证券QMT仿真-交易端\userdata_mini'
session_id = int(random.randint(100000, 999999))
xt_trader = XtQuantTrader(mini_qmt_path, session_id)
xt_trader.start()
connect_result = xt_trader.connect()

if connect_result != 0:
    print(f"❌ 连接失败，错误码: {connect_result}")
    exit()

account_id = "34165036" 
acc = StockAccount(account_id)
stock_code = "588000.SH"
buy_volume = 100

print(f"\n>>> 开始拉取 {stock_code} 的实时盘口数据...")

# ==========================================
# 2. 通过 xtdata 获取当前盘口快照 (全档 Tick)
# ==========================================
# get_full_tick 会返回一个字典，里面包含了最新价、买1-买5、卖1-卖5 等所有信息
tick_dict = xtdata.get_full_tick([stock_code])

# 检查是否成功获取到了数据
if stock_code in tick_dict:
    market_data = tick_dict[stock_code]
    
    # askPrice 是一个数组，[0]就是卖一价，[1]是卖二价，以此类推
    ask_price_1 = market_data['askPrice'][0] 
    
    print(f"✅ 成功获取！当前卖一价为: {ask_price_1}")
    
    # 防呆设计：如果卖一价是 0，说明股票可能已经涨停（没有人在卖了），或者停牌
    if ask_price_1 <= 0:
        print("⚠️ 卖一价为 0，标的可能已涨停或无流动性，停止买入。")
        exit()
else:
    print("❌ 未获取到行情数据，请确保 QMT 终端已下载当日行情。")
    exit()

# ==========================================
# 3. 动态组装价格并执行限价下单
# ==========================================
# 💡 量化抢单技巧：为了防止你在下单的这零点几秒内，0.850 的卖一被人抢光了
# 我们可以强行加 1 个 Tick (对于 588000 这种 ETF，最小变动单位是 0.001)
# 根据交易所“价格优先”规则，只要你出价 0.851，依然会以 0.850 的最优价优先撮合成交
target_buy_price = ask_price_1 + 0.001 

print(f">>> 最终决定以 {target_buy_price:.3f} 的限价报单 (卖一价上浮 1 个 Tick)...")

order_id = xt_trader.order_stock(
    account=acc, 
    stock_code=stock_code, 
    order_type=xtconstant.STOCK_BUY,      
    order_volume=buy_volume,              
    price_type=xtconstant.FIX_PRICE,      # 强制使用限价模式
    price=target_buy_price,               # 传入刚刚计算好的动态价格
    strategy_name="Ask1_Tracker",       
    order_remark="追踪卖一价买入"    
)

if order_id > 0:
    print(f"✅ 动态限价单发送成功！订单编号: {order_id}")
else:
    print(f"❌ 下单失败，错误码: {order_id}")