# selector.py
import pandas as pd
from xtquant import xtdata

def get_target_stocks(base_sector: str, end_date: str, top_n: int, lookback_days: int) -> list:
    """
    [TODO: 此处实现选股逻辑]
    
    参数说明:
        base_sector: 基础板块 (如 '中证500')
        end_date: 评估基准日 (如 '20231231')
        top_n: 需要返回的股票数量
        lookback_days: 允许向后查看的天数数据
        
    返回:
        包含股票代码的列表，例如: ['000001.SZ', '600000.SH']
    """
    print(f"-> [Selector] 正在执行选股算法... 基准日: {end_date}")
    
    # 获取基础池
    stock_list = xtdata.get_stock_list_in_sector(base_sector)
    
    
    print("-> [Selector] 当前使用 Dummy 随机选股策略...")
    import random
    if len(stock_list) > top_n:
        final_stock_list = random.sample(stock_list, top_n)
    else:
        final_stock_list = stock_list
    
    print(f"-> [Selector] 选股完成！共选出 {len(final_stock_list)} 只标的。")
    return final_stock_list