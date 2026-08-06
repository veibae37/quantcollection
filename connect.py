# 因为 xtquant 文件夹就在旁边，Python 能直接 import 成功
from xtquant.xttrader import XtQuantTrader
from xtquant.xttype import StockAccount
import random

# 1. 填入你刚才找到的极简模式数据路径 (注意前面的 r 不能少)
mini_qmt_path = r'C:\Users\baby liu\Desktop\中信建投\中信建投证券QMT仿真-交易端\userdata_mini'

# 2. 生成随机 Session ID 并初始化交易对象
session_id = int(random.randint(100000, 999999))
xt_trader = XtQuantTrader(mini_qmt_path, session_id)

# 3. 启动后台线程并连接
xt_trader.start()
connect_result = xt_trader.connect()

if connect_result == 0:
    print("✅ 成功连接到 QMT 极简终端！API 通道已打通。")
    
    # 连接成功后，你可以顺便测试一下能否读取账号资产
    # 填入你的资金账号 (比如仿真账号数字)
    account_id = "34165036" 
    acc = StockAccount(account_id)
    
    # 订阅该账号的交易状态
    subscribe_result = xt_trader.subscribe(acc)
    if subscribe_result == 0:
        print(f"✅ 账号 {account_id} 状态订阅成功！")
else:
    print(f"❌ 连接失败，错误码: {connect_result}")