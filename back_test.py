#coding:gbk
"""
基于深度学习预测的网格交易策略（适配 QMT 纯沙盒回测模式）
"""
import pandas as pd
import numpy as np
import time

def init(ContextInfo):
    print("=== 开始初始化 QMT 回测引擎 ===")
    ContextInfo.accountID = 'testS'
    
    # 1. 策略参数设置
    # [ElasticGrid-Step1] 用弹性网格参数替代固定步长 grid_step（原先是 10% 固定间距）
    # [ElasticGrid-Step1] 这里先按“相对 predicted_center(P0) 的比例”硬编码上下限；每日会随 P0 自动缩放
    ContextInfo.G_ul_ratio = 1.3   # [ElasticGrid-Step1] G_ul = P0 * G_ul_ratio（上半区绝对上限）
    ContextInfo.G_ll_ratio = 0.7   # [ElasticGrid-Step1] G_ll = P0 * G_ll_ratio（下半区绝对下限）
    ContextInfo.n_u = 6            # [ElasticGrid-Step1] 上半区网格条数
    ContextInfo.n_l = 6            # [ElasticGrid-Step1] 下半区网格条数

    ContextInfo.trend_threshold = 0.2
    ContextInfo.max_cash_per_stock = 10000  # 单只股票每次买入金额上限
    
    # 2. 核心：加载深度学习预测数据
    print("-> 正在加载深度学习预测数据...")
    csv_path = r"D:\study\python\quant\lstm_predictions_2019_2024.csv" 
    
    try:
        df = pd.read_csv(csv_path)
        # 格式化日期和股票代码
        df['datetime'] = pd.to_datetime(df['datetime']).dt.strftime('%Y%m%d')
        df['instrument'] = df['instrument'].str[2:] + '.' + df['instrument'].str[:2]
        
        # 转化为按日期索引的嵌套字典
        ContextInfo.pred_dict = df.groupby('datetime').apply(
            lambda x: dict(zip(x['instrument'], x['pred_center_return']))
        ).to_dict()
        print(f"-> 预测数据加载完成，共包含 {len(ContextInfo.pred_dict)} 个交易日的数据。")
        
        # 获取所有涉及到的股票作为股票池
        all_stocks = []
        for d in ContextInfo.pred_dict.values():
            all_stocks.extend(list(d.keys()))
        ContextInfo.s = list(set(all_stocks))
    except Exception as e:
        print(f"[-] 加载 CSV 失败: {e}")
        ContextInfo.pred_dict = {}
        ContextInfo.s = ['000001.SZ', '600000.SH'] # 失败后的默认备用池

    # 设置订阅的股票池
    ContextInfo.set_universe(ContextInfo.s)
    
    # ====================================================================
    # 3. 仿照官方示例：手动初始化账户状态（沙盒模式必须自己记账！）
    # ====================================================================
    ContextInfo.holdings = {i: 0 for i in ContextInfo.s} # 记录每只股票的持仓股数
    ContextInfo.buypoint = {}                           # 记录每只股票的买入成本价
    ContextInfo.money = ContextInfo.capital             # 当前可用现金（基于系统设定的初始本金）
    ContextInfo.profit = 0                              # 累计真实利润
    

def handlebar(ContextInfo):
    d = ContextInfo.barpos
    current_date = timetag_to_datetime(ContextInfo.get_bar_timetag(d), '%Y%m%d')
    
    if current_date not in ContextInfo.pred_dict:
        return 
        
    daily_preds = ContextInfo.pred_dict[current_date]
    
    # 获取行情数据 (参照官方示例的 get_history_data 用法)
    data_close = ContextInfo.get_history_data(2, '1d', 'close', 3)
    data_open = ContextInfo.get_history_data(1, '1d', 'open', 3)
    data_high = ContextInfo.get_history_data(1, '1d', 'high', 3)
    data_low = ContextInfo.get_history_data(1, '1d', 'low', 3)
    
    for stock, pred_return in daily_preds.items():
        # 数据完整性校验
        if stock not in data_close or len(data_close[stock]) < 2:
            continue
        if stock not in data_open or len(data_open[stock]) < 1:
            continue
            
        yesterday_close = data_close[stock][-2]
        today_open = data_open[stock][-1]
        today_high = data_high[stock][-1]
        today_low = data_low[stock][-1]
        today_close = data_close[stock][-1]
        
        if np.isnan(today_open) or today_open == 0:
            continue

        # 从手动维护的账本中获取持仓
        holding_vol = ContextInfo.holdings.get(stock, 0)
            
        # 设定网格中枢
        predicted_center = yesterday_close * (1.0 + pred_return)
        buy_grid_line = predicted_center * (1.0 - ContextInfo.grid_step)
        sell_grid_line = predicted_center * (1.0 + ContextInfo.grid_step)
        
        execute_price = 0
        action = 0  # 1 为买入，-1 为卖出
        reason = 0
        # 动作判定逻辑（最高/最低价补偿机制）
        if pred_return > ContextInfo.trend_threshold:
            execute_price = today_open
            action = 1
            reason = 1
        elif pred_return < -ContextInfo.trend_threshold and holding_vol > 0:
            execute_price = today_open
            action = -1
            reason = 1
        elif today_low <= buy_grid_line:
            execute_price = min(today_open, buy_grid_line)
            action = 1
            reason = -1
        elif today_high >= sell_grid_line and holding_vol > 0:
            execute_price = max(today_open, sell_grid_line)
            action = -1
            reason = -1

        # ====================================================================
        # 核心发单与手动记账逻辑 (完全贴合官方示例)
        # ====================================================================
        if action == 1: # 买入逻辑
            # 根据设定的限额和账户剩余现金计算能买多少股
            allocate_cash = min(ContextInfo.max_cash_per_stock, ContextInfo.money)
            buy_vol = int(allocate_cash / execute_price / 100) * 100
            
            if buy_vol >= 100:
                print(f"[{current_date}] ready to buy {stock} at {execute_price:.2f},{'trend' if reason==1 else 'grid'}")
                # 调用沙盒发单接口
                order_shares(stock, buy_vol, 'fix', execute_price, ContextInfo, ContextInfo.accountID)
                
                # 手动记账
                ContextInfo.buypoint[stock] = execute_price
                # 扣除买入本金和手续费(万三)
                fee = buy_vol * execute_price * 0.0003
                ContextInfo.money -= (buy_vol * execute_price)
                ContextInfo.holdings[stock] = holding_vol + buy_vol
                
        elif action == -1: # 卖出逻辑
            sell_vol = holding_vol
            print(f"[{current_date}] ready to sell {stock} at {execute_price:.2f},{'trend' if reason==1 else 'grid'}")
            # 调用沙盒发单接口 (卖出传入负数股数)
            order_shares(stock, -sell_vol, 'fix', execute_price, ContextInfo, ContextInfo.accountID)
            
            # 手动记账
            fee = sell_vol * execute_price * 0.0003
            ContextInfo.money += (sell_vol * execute_price)
            
            buy_cost = ContextInfo.buypoint.get(stock, execute_price)
            # 利润 = (卖出价 - 买入价) * 股数 - 卖出手续费
            ContextInfo.profit += (execute_price - buy_cost) * sell_vol
            ContextInfo.holdings[stock] = 0

    # ====================================================================
    # 界面图表绘制
    # ====================================================================
    profit_ratio = ContextInfo.profit / ContextInfo.capital
    if not ContextInfo.do_back_test:
        # 在主界面画出收益率曲线
        ContextInfo.paint('profit_ratio', profit_ratio, -1, 0)
