# config.py

# --- 数据与选股参数 ---
# BASE_SECTOR = ''      # 基础股票池
TOP_N_STOCKS = 50           # 最终保留的活跃股数量
LOOKBACK_DAYS = 30          # 评估活跃度的回溯天数

# --- 时间范围设定 ---
RESEARCH_START_DATE = '20150101'
RESEARCH_END_DATE = '20231231'

# --- 路径配置 ---
CSV_OUTPUT_DIR = './qlib_source_csvs'