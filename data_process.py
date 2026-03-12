# data_builder.py
import os
import pandas as pd
import numpy as np
from xtquant import xtdata

# 导入配置和选股接口
import config
from selector import get_target_stocks

def convert_to_qlib_csv(stock_list, start_date, end_date, output_dir):

    os.makedirs(output_dir, exist_ok=True)
    
    print(f"-> [DataBuilder] 开始下载 {len(stock_list)} 只股票的长期历史数据...")
    xtdata.download_history_data2(stock_list, period='1d', start_time=start_date, end_time=end_date)
    
    print("-> [DataBuilder] 读取数据并格式化为 Qlib 格式...")
    market_data = xtdata.get_market_data_ex(
        field_list=['open', 'high', 'low', 'close', 'volume', 'amount'],
        stock_list=stock_list,
        period='1d',
        start_time=start_date,
        end_time=end_date,
        dividend_type='front'
    )
    
    success_count = 0
    for stock in stock_list:
        df = market_data.get(stock)
        if df is None or df.empty:
            continue
            
        df = df.copy()
        df.index = pd.to_datetime(df.index)
        df.index.name = 'date'
        
        df['vwap'] = np.where(df['volume'] > 0, df['amount'] / df['volume'], df['close'])
        df['factor'] = 1.0 
        
        code, exchange = stock.split('.')
        qlib_symbol = f"{exchange}{code}"
        
        df = df[['open', 'high', 'low', 'close', 'volume', 'amount', 'vwap', 'factor']]
        
        csv_path = os.path.join(output_dir, f"{qlib_symbol}.csv")
        df.to_csv(csv_path)
        success_count += 1
        
    print(f"-> [DataBuilder] 处理完毕！共生成 {success_count} 个 Qlib CSV 文件。")


def main():

    # sector_list=xtdata.get_sector_list()
    sector_list=["深证B股"]
    for base_sector in sector_list:
        print(f"{base_sector}:{len(xtdata.get_stock_list_in_sector(base_sector))}")

        target_stocks = get_target_stocks(
            base_sector=base_sector,
            end_date=config.RESEARCH_END_DATE,
            top_n=config.TOP_N_STOCKS,
            lookback_days=config.LOOKBACK_DAYS
        )
        
        convert_to_qlib_csv(
            stock_list=target_stocks,
            start_date=config.RESEARCH_START_DATE,
            end_date=config.RESEARCH_END_DATE,
            output_dir=config.CSV_OUTPUT_DIR
        )

if __name__ == '__main__':
    main()