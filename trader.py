# trader.py
import time
from datetime import datetime
import requests
import json

from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount
from xtquant import xtconstant

# 只导入 config，绝对不要导入 strategy_model (因为 Windows 上没有 Qlib)
import config

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

def fetch_signals_from_linux(stock_list, today_str, current_prices, current_positions):
    """
    核心修改：通过 HTTP POST 将状态发送给 Linux，并接收交易指令
    """
    # 构建要发送给 Linux 的状态字典 (Payload)
    payload = {
        "stock_list": stock_list,
        "today_str": today_str,
        "current_prices": current_prices,
        "current_positions": current_positions
    }
    
    print(f"-> [Network] 正在向 Linux 大脑 ({config.API_ENDPOINT}) 发送状态并请求信号...")
    
    try:
        # 发送 POST 请求，timeout 设得稍微长一点，给深度学习模型一点推理时间
        response = requests.post(config.API_ENDPOINT, json=payload, timeout=20)
        
        # 检查 HTTP 状态码
        if response.status_code != 200:
            print(f"-> [Error] 服务器返回异常状态码: {response.status_code}")
            return {}
            
        result = response.json()
        
        if result.get("status") == "success":
            actions = result.get("data", {})
            print("-> [Network] 成功从 Linux 大脑获取今日交易信号！")
            return actions
        else:
            print(f"-> [Error] 服务器大脑内部处理报错: {result.get('message', '未知错误')}")
            return {}
            
    except requests.exceptions.RequestException as e:
        print(f"-> [Error] 远程调用失败，请检查网络或 Linux FastAPI 是否已启动: {e}")
        return {}


def main_trading_loop():
    print("=== 量化实盘执行系统启动 (Windows 节点) ===")
    
    # 1. 初始化并连接 QMT 极速版客户端
    mini_qmt_path = config.MINI_QMT_PATH
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
    # 注意：这里的标的可以写死，但在完善的项目中，最好也是通过读取 CSV 或通过 API 从选股模块获取
    qlib_stock_list = ['SZ000001', 'SH600000'] 
    xt_stock_list = [qlib_to_xt(code) for code in qlib_stock_list]

    # 3. 收集策略需要的两大状态：当前价格 和 当前持仓
    print("\n-> [Trader] 正在拉取账户状态与实时行情...")
    
    positions = xt_trader.query_stock_positions(account)
    current_positions = {xt_to_qlib(pos.stock_code): pos.volume for pos in positions if pos.volume > 0}
    
    current_prices = {}
    for xt_code in xt_stock_list:
        tick = xtdata.get_full_tick([xt_code])
        if xt_code in tick:
            current_prices[xt_to_qlib(xt_code)] = float(tick[xt_code]['lastPrice']) # 转为 float 防 JSON 序列化报错
        else:
            current_prices[xt_to_qlib(xt_code)] = 0.0

    print(f"当前持仓: {current_positions}")
    print(f"当前价格: {current_prices}")
    
    # ========================================================
    # 4. 远程召唤策略大脑
    # ========================================================
    actions = fetch_signals_from_linux(
        stock_list=qlib_stock_list,
        today_str=today_str,
        current_prices=current_prices,
        current_positions=current_positions
    )
    
    if not actions:
        print("\n-> [Trader] 未获取到有效交易信号，今日交易循环结束。")
        return
        
    print("\n-> [Trader] 大脑决策完毕，输出以下交易动作：")
    for stock, info in actions.items():
        print(f"标的: {stock} | 动作: {info['action']} | 目标价: {info['target_price']:.2f} | 理由: {info['reason']}")
    input("pause")
    # ========================================================
    # 5. 订单路由：将策略输出转化为实际的交易所订单
    # ========================================================
    print("\n-> [Trader] 开始向交易所发送订单...")
    
    asset = xt_trader.query_stock_asset(account)
    available_cash = asset.cash
    
    for qlib_code, action_info in actions.items():
        xt_code = qlib_to_xt(qlib_code)
        action_type = action_info['action']
        target_price = action_info['target_price']
        
        if action_type == "HOLD" or target_price is None:
            continue
            
        if action_type == "BUY":
            # 引入 config 中的最大买入金额限制
            allocate_cash = min(config.MAX_CASH_PER_STOCK, available_cash)
            buy_vol = int(allocate_cash / target_price / 100) * 100
            
            if buy_vol >= 100:
                print(f"发送买单: {xt_code}, 价格: {target_price}, 数量: {buy_vol}")
                xt_trader.order_stock_async(account, xt_code, xtconstant.STOCK_BUY, buy_vol, xtconstant.FIX_PRICE, target_price, 'grid_buy', 'test')
                available_cash -= (buy_vol * target_price) 
                
        elif action_type == "SELL":
            sell_vol = current_positions.get(qlib_code, 0)
            if sell_vol >= 100:
                print(f"发送卖单: {xt_code}, 价格: {target_price}, 数量: {sell_vol}")
                xt_trader.order_stock_async(account, xt_code, xtconstant.STOCK_SELL, sell_vol, xtconstant.FIX_PRICE, target_price, 'grid_sell', 'test')

    print("=== 交易循环执行结束 ===")

if __name__ == '__main__':
    main_trading_loop()