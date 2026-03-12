# trader.py
import time
from datetime import datetime
from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant

# 导入你们写好的配置和大脑模块
import config
from strategy_model import run_strategy

# ---------------- 工具函数：代码转换 ----------------
def xt_to_qlib(xt_code):
    """ 000001.SZ -> SZ000001 """
    code, exchange = xt_code.split('.')
    return f"{exchange}{code}"

def qlib_to_xt(qlib_code):
    """ SZ000001 -> 000001.SZ """
    exchange = qlib_code[:2]
    code = qlib_code[2:]
    return f"{code}.{exchange}"
# --------------------------------------------------

class MyTraderCallback(XtQuantTraderCallback):
    def on_stock_order(self, order):
        print(f"[回调] 订单状态更新: {order.stock_code}, 状态: {order.order_status}, 报单数量: {order.order_volume}")

def main_trading_loop():
    print("=== 量化实盘执行系统启动 ===")
    
    # 1. 初始化并连接 QMT 极速版客户端
    # 注意：这里需要填入你们自己的 miniQMT 路径和资金账号
    mini_qmt_path =config.MINI_QMT_PATH
    account_id = config.ACCOUNT_ID
    
    session_id = int(time.time())
    xt_trader = XtQuantTrader(mini_qmt_path, session_id)
    xt_trader.register_callback(MyTraderCallback())
    xt_trader.start()
    
    if xt_trader.connect() != 0:
        print("连接 QMT 失败，请检查客户端是否启动。")
        return
        
    account = StockAccount(account_id)
    xt_trader.subscribe(account)
    print(f"成功连接资金账号: {account_id}")

    # 2. 准备基础数据
    today_str = datetime.now().strftime('%Y%m%d')
    # 假设这是我们之前用 selector.py 选出的活跃股，这里用 Qlib 格式
    qlib_stock_list = ['SZ000001', 'SH600000'] 
    xt_stock_list = [qlib_to_xt(code) for code in qlib_stock_list]

    # 3. 收集策略需要的两大状态：当前价格 (current_prices) 和 当前持仓 (current_positions)
    print("\n-> [Trader] 正在拉取账户状态与实时行情...")
    
    # 获取真实持仓 (转换为 Qlib 格式的字典)
    positions = xt_trader.query_stock_positions(account)
    current_positions = {xt_to_qlib(pos.stock_code): pos.volume for pos in positions if pos.volume > 0}
    
    # 订阅并获取实时行情 (Tick 数据)
    # 对于虚拟盘，这里可以直接取最新价
    current_prices = {}
    for xt_code in xt_stock_list:
        tick = xtdata.get_full_tick([xt_code])
        if xt_code in tick:
            # 取最新成交价
            current_prices[xt_to_qlib(xt_code)] = tick[xt_code]['lastPrice']
        else:
            current_prices[xt_to_qlib(xt_code)] = 0.0

    print(f"当前持仓: {current_positions}")
    
    # ========================================================
    # 4. 召唤策略大脑，执行 run_strategy_pipeline
    # ========================================================
    print("\n-> [Trader] 将状态输入深度学习网格大脑，等待决策...")
    
    actions = run_strategy(
        stock_list=qlib_stock_list,
        today_str=today_str,
        current_prices=current_prices,
        current_positions=current_positions
    )
    
    print("\n-> [Trader] 大脑决策完毕，输出以下交易动作：")
    for stock, info in actions.items():
        print(f"标的: {stock} | 动作: {info['action']} | 目标价: {info['target_price']:.2f} | 理由: {info['reason']}")
        
    # ========================================================
    # 5. 订单路由：将策略输出转化为实际的交易所订单
    # ========================================================
    print("\n-> [Trader] 开始向交易所发送订单...")
    
    # 查询当前可用现金，用于计算买入数量
    asset = xt_trader.query_stock_asset(account)
    available_cash = asset.cash
    
    for qlib_code, action_info in actions.items():
        xt_code = qlib_to_xt(qlib_code)
        action_type = action_info['action']
        target_price = action_info['target_price']
        
        if action_type == "HOLD" or target_price is None:
            continue
            
        if action_type == "BUY":
            # 资金分配：假设每只股票最多分配 10000 元，且不能超过可用现金
            allocate_cash = min(10000, available_cash)
            buy_vol = int(allocate_cash / target_price / 100) * 100 # 向下取整到 100 的整数倍 (A股规则)
            
            if buy_vol >= 100:
                print(f"发送买单: {xt_code}, 价格: {target_price}, 数量: {buy_vol}")
                # 注意：这里我们使用的是“限价单 (FIX_PRICE)”，因为网格策略需要严格在指定价格成交
                xt_trader.order_stock_async(account, xt_code, xtconstant.STOCK_BUY, buy_vol, xtconstant.FIX_PRICE, target_price, 'grid_buy', 'test')
                available_cash -= (buy_vol * target_price) # 扣除预估现金
                
        elif action_type == "SELL":
            # 卖出逻辑：卖出当前账户里该股票的全部/部分持仓
            sell_vol = current_positions.get(qlib_code, 0)
            
            # A股 T+1 规则：如果你需要精准控制可用数量，可以通过 pos.can_use_volume 获取
            if sell_vol >= 100:
                print(f"发送卖单: {xt_code}, 价格: {target_price}, 数量: {sell_vol}")
                xt_trader.order_stock_async(account, xt_code, xtconstant.STOCK_SELL, sell_vol, xtconstant.FIX_PRICE, target_price, 'grid_sell', 'test')

    print("=== 交易循环执行结束 ===")

if __name__ == '__main__':
    main_trading_loop()