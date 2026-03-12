import pandas as pd
import numpy as np
import time
from datetime import datetime
from sklearn import svm

# 导入 xtquant 核心模块
from xtquant import xtdata
from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
from xtquant.xttype import StockAccount

# ================= 1. 基础配置 =================
STOCK_CODE = '000001.SZ'  # 目标股票：平安银行
ACCOUNT_ID = '86004893'  # 替换为你的 QMT 资金账号
# miniQMT 的 userdata_mini 文件夹路径（必须启动 miniQMT 客户端）
MINI_QMT_PATH = r'D:\国金QMT交易端模拟\userdata_mini' 

class MyTraderCallback(XtQuantTraderCallback):
    """
    回调类：用于接收订单状态、成交回报等异步信息
    """
    def on_stock_order(self, order):
        print(f"订单状态更新: {order.stock_code}, 状态: {order.order_status}, 报单数量: {order.order_volume}")

def train_model():
    """
    离线训练模型阶段 (等同于原代码 days == 0 的部分)
    """
    print("开始下载历史数据并训练 SVM 模型...")
    # 1. 下载并获取历史日线数据 (前复权)
    xtdata.download_history_data2([STOCK_CODE], '1d', '20160101', '20170101')
    data = xtdata.get_market_data(
        field_list=['open', 'high', 'low', 'close', 'volume'],
        stock_list=[STOCK_CODE],
        period='1d',
        start_time='20160101',
        end_time='20170101',
        dividend_type='front'
    )
    
    # xtdata 返回的是以字段为 key 的 dict，需要转换格式
    close_prices = data['close'].loc[STOCK_CODE].values
    open_prices = data['open'].loc[STOCK_CODE].values
    high_prices = data['high'].loc[STOCK_CODE].values
    low_prices = data['low'].loc[STOCK_CODE].values
    volumes = data['volume'].loc[STOCK_CODE].values
    
    x_all, y_all = [], []
    # 构造特征 (与原逻辑一致，此处简化代码结构演示)
    for i in range(14, len(close_prices) - 5):
        window_close = close_prices[i-14 : i+1]
        window_vol = volumes[i-14 : i+1]
        window_high = high_prices[i-14 : i+1]
        window_low = low_prices[i-14 : i+1]
        
        features = [
            window_close[-1] / np.mean(window_close),
            window_vol[-1] / np.mean(window_vol),
            window_high[-1] / np.mean(window_high),
            window_low[-1] / np.mean(window_low),
            window_vol[-1],
            window_close[-1] / window_close[0], # return_now
            np.std(window_close)
        ]
        x_all.append(features)

    # 构造标签：预测 5 天后涨跌
    for i in range(len(close_prices) - 19):
        label = 1 if close_prices[i+19] > close_prices[i+14] else 0
        y_all.append(label)
        
    x_train, y_train = x_all[:-1], y_all[:-1]
    
    # 训练模型
    clf = svm.SVC(C=1.0, kernel='rbf')
    clf.fit(x_train, y_train)
    print("SVM 模型训练完成！")
    return clf

def main():
    # ================= 2. 交易环境初始化 =================
    # 创建交易对象，session_id 用随机数或时间戳避免冲突
    session_id = int(time.time())
    xt_trader = XtQuantTrader(MINI_QMT_PATH, session_id)
    
    # 注册回调并启动交易线程
    xt_trader.register_callback(MyTraderCallback())
    xt_trader.start()
    
    # 连接到 miniQMT 客户端
    connect_result = xt_trader.connect()
    if connect_result != 0:
        print("连接 QMT 失败，请检查路径和客户端是否已启动 (极速版)。")
        return
        
    # 绑定资金账号
    account = StockAccount(ACCOUNT_ID)
    xt_trader.subscribe(account)
    print(f"成功连接账号: {ACCOUNT_ID}")

    # ================= 3. 准备模型 =================
    # 在实际应用中，深度学习模型通常在这里使用 torch.load() 加载权重
    model = train_model()

    # ================= 4. 当日交易逻辑 (每日运行一次) =================
    today_str = datetime.now().strftime('%Y%m%d')
    weekday = datetime.now().isoweekday()
    
    # 获取账户资产和持仓状态
    asset = xt_trader.query_stock_asset(account)
    positions = xt_trader.query_stock_positions(account)
    
    # 检查当前是否持有该股票
    holding_vol = 0
    hold_cost_price = 0
    for pos in positions:
        if pos.stock_code == STOCK_CODE:
            holding_vol = pos.volume
            hold_cost_price = pos.open_price # 简单的持仓成本估算
            break

    # 获取今天的最新切片数据 (用于计算特征和下单参考)
    xtdata.download_history_data2([STOCK_CODE], '1d', '20230101', today_str) # 保证数据够15天
    current_data = xtdata.get_market_data_ex(
        field_list=['open', 'high', 'low', 'close', 'volume'],
        stock_list=[STOCK_CODE],
        period='1d'
    )[STOCK_CODE]
    
    if current_data.empty or len(current_data) < 15:
        print("数据不足以计算特征。")
        return

    today_close = current_data['close'].iloc[-1]
    today_open = current_data['open'].iloc[-1]

    # ------ 卖出逻辑 (每日检查) ------
    if holding_vol > 0:
        if today_close / hold_cost_price >= 1.1:
            print(f"触发止盈！现价: {today_close}, 成本: {hold_cost_price}")
            # 下达市价卖出指令
            xt_trader.order_stock_async(account, STOCK_CODE, xtconstant.STOCK_SELL, holding_vol, xtconstant.LATEST_PRICE, today_close, 'strategy_take_profit', 'test')
            
        elif today_close / hold_cost_price < 0.98 and weekday == 5:
            print(f"触发周末止损！现价: {today_close}, 成本: {hold_cost_price}")
            xt_trader.order_stock_async(account, STOCK_CODE, xtconstant.STOCK_SELL, holding_vol, xtconstant.LATEST_PRICE, today_close, 'strategy_stop_loss', 'test')
            
    # ------ 买入逻辑 (仅限周一且空仓) ------
    elif holding_vol == 0 and weekday == 1:
        # 提取过去15天数据计算特征
        window = current_data.iloc[-15:]
        features = [
            window['close'].iloc[-1] / window['close'].mean(),
            window['volume'].iloc[-1] / window['volume'].mean(),
            window['high'].iloc[-1] / window['high'].mean(),
            window['low'].iloc[-1] / window['low'].mean(),
            window['volume'].iloc[-1],
            window['close'].iloc[-1] / window['close'].iloc[0],
            window['close'].std()
        ]
        features_array = np.array(features).reshape(1, -1)
        
        # 模型预测
        prediction = model.predict(features_array)[0]
        print(f"今日模型预测结果: {prediction}")
        
        if prediction == 1:
            # 计算可用资金的 95% 能买多少股 (向下取整到 100 的倍数)
            available_cash = asset.cash * 0.95
            buy_vol = int(available_cash / today_open / 100) * 100
            
            if buy_vol >= 100:
                print(f"执行买入！预估价格: {today_open}, 数量: {buy_vol}")
                # 下达市价买入指令
                xt_trader.order_stock_async(account, STOCK_CODE, xtconstant.STOCK_BUY, buy_vol, xtconstant.LATEST_PRICE, today_open, 'strategy_buy', 'test')

if __name__ == '__main__':
    # xtquant 需要常量定义
    from xtquant import xtconstant 
    sector_list=xtdata.get_sector_list()
    for sector in sector_list:
        print(f"{sector}:{len(xtdata.get_stock_list_in_sector(sector))}")
    input("pause")
    main()