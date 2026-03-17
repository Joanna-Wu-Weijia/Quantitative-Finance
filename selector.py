import pandas as pd
import numpy as np
from xtquant import xtdata

def get_target_stocks(sector_list: list, end_date: str, top_n: int, lookback_days: int) -> list:
    """
    执行多因子选股逻辑 (适配 get_market_data_ex 格式与强健的去空值逻辑)
    """
    print(f"-> [Selector] 正在执行多因子选股算法... 评估基准日: {end_date}")
    
    # ==========================================
    # 第一步：获取基础股票池
    # ==========================================
    stock_pool = []
    for base_sector in sector_list:
        stocks = xtdata.get_stock_list_in_sector(base_sector)
        stock_pool.extend(stocks)
        
    stock_pool = list(set(stock_pool))
    print(f"-> [Selector] 去重后总备选池: {len(stock_pool)} 只")

    # 获取批量数据 (使用 ex 函数)
    market_data = xtdata.get_market_data_ex(
        field_list=['close', 'volume'],
        stock_list=stock_pool,
        period='1d',
        end_time=end_date,
        count=lookback_days
    )
    
    # ==========================================
    # 核心修改 1：解析 ex 函数的嵌套字典格式
    # ==========================================
    close_dict = {}
    vol_dict = {}
    
    for stock, df in market_data.items():
        # 确保 df 不是空的，并且包含我们需要的数据列
        if not df.empty and 'close' in df.columns and 'volume' in df.columns:
            close_dict[stock] = df['close']
            vol_dict[stock] = df['volume']
            
    if not close_dict:
        print("[-] 未获取到任何有效的行情数据，请检查数据是否已下载。")
        return []

    # 瞬间拼接成截面 DataFrame (行：日期，列：股票代码)
    df_close = pd.DataFrame(close_dict)
    df_vol = pd.DataFrame(vol_dict)
    
    # ==========================================
    # 核心修改 2：针对截图脏数据的强力清洗
    # ==========================================
    # 剔除那些像 '134775.SZ' 一样，在考察期内全是 NaN 或全为 0 的标的
    df_close.dropna(axis=1, how='all', inplace=True)
    df_vol.dropna(axis=1, how='all', inplace=True)
    
    # 对齐列 (确保 close 和 vol 的股票池完全一致)
    valid_stocks = df_close.columns.intersection(df_vol.columns)
    df_close = df_close[valid_stocks]
    df_vol = df_vol[valid_stocks]

    # ==========================================
    # 第二步：计算选股因子 (特征工程)
    # ==========================================
    factors_df = pd.DataFrame(index=df_close.columns)
    
    # 因子 1: 动量因子 (Momentum)
    # 【鲁棒性优化】：用 ffill 和 bfill 找到区间内真实的“第一个”和“最后一个”有效价格，防止首尾恰好停牌报错
    first_valid_price = df_close.bfill().iloc[0]
    last_valid_price = df_close.ffill().iloc[-1]
    factors_df['momentum'] = (last_valid_price - first_valid_price) / first_valid_price
    
    # 因子 2: 波动率因子 (Volatility)
    daily_returns = df_close.pct_change()
    factors_df['volatility'] = daily_returns.std()
    
    # 因子 3: 流动性因子 (Liquidity)
    factors_df['liquidity'] = df_vol.mean()
    
    # ==========================================
    # 第三步：剔除无法计算的异常标的
    # ==========================================
    # 将可能出现的除以0产生的无穷大替换为空值
    factors_df.replace([np.inf, -np.inf], np.nan, inplace=True)
    factors_df.dropna(inplace=True)
    # 剔除日均成交量为0的绝对死水股
    factors_df = factors_df[factors_df['liquidity'] > 0] 

    if factors_df.empty:
        print("[-] 经过清洗后，没有股票符合要求。")
        return []

    # ==========================================
    # 第四步：因子去极值与标准化
    # ==========================================
    def process_factor(series):
        lower_bound = series.quantile(0.01)
        upper_bound = series.quantile(0.99)
        series_clipped = series.clip(lower=lower_bound, upper=upper_bound)
        series_norm = (series_clipped - series_clipped.mean()) / series_clipped.std()
        return series_norm

    factors_df['mom_norm'] = process_factor(factors_df['momentum'])
    factors_df['liq_norm'] = process_factor(factors_df['liquidity'])
    factors_df['vol_norm'] = process_factor(factors_df['volatility']) * -1 

    # ==========================================
    # 第五步：打分与排名
    # ==========================================
    factors_df['total_score'] = factors_df['mom_norm'] + factors_df['vol_norm'] + factors_df['liq_norm']
    factors_df.sort_values(by='total_score', ascending=False, inplace=True)
    
    final_stock_list = factors_df.head(top_n).index.tolist()

    print(f"-> [Selector] 选股完成！共选出 {len(final_stock_list)} 只标的。")
    return final_stock_list