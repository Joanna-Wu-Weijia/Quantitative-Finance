import qlib
from qlib.data import D

# 初始化 Qlib，指向你刚刚编译好的本地数据库
qlib.init(provider_uri='./qlib_data/my_custom_cn_data', region='cn')

# 极速拉取数据测试 (此时不再需要任何 csv 和 xtdata)
df_test = D.features(['SZ000001'], ['$close', '$vwap', '($close - $open) / $open'], start_time='2023-01-01', end_time='2023-12-31')
print(df_test)