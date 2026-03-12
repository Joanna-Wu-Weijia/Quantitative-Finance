# strategy_model.py
import qlib
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP
from qlib.data.dataset.processor import RobustZScoreNorm, Fillna
from qlib.utils import init_instance_by_config
import pandas as pd
import numpy as np

import config

class DeepGridStrategy:
    def __init__(self):
        """
        初始化策略并连接到本地 Qlib 数据库
        """
        print("-> [Strategy] 正在初始化 Qlib 引擎...")
        qlib.init(provider_uri=config.QLIB_DIR, region="cn")
        
        # 网格参数配置
        self.grid_step = 0.015  # 网格间距 (1.5%)
        self.trend_threshold = 0.02 # 判定单边趋势的阈值
        
    def build_dataset(self, stock_list, start_date, end_date):
        """
        利用 Qlib 强大的表达式引擎，实时生成深度学习所需的特征和标签
        """
        print("-> [Strategy] 正在构建时序特征与标签数据集...")
        
        # 1. 定义特征 (Feature Engineering)
        # 这里直接使用 Qlib 的表达式公式，无需手动算 Pandas
        # 例如：计算过去 15 天的各种量价指标
        feature_dict = {
            "close_norm": "$close / Mean($close, 15)",
            "volume_norm": "$volume / Mean($volume, 15)",
            "return_15d": "$close / Ref($close, 15) - 1",
            "volatility": "Std($close, 15)",
            "vwap_ratio": "$vwap / $close"
        }
        
        # 2. 定义预测目标 (Label)
        # 假设深度学习模型要预测未来 3 天的 VWAP 均值，作为网格中枢
        label_dict = {
            "target_vwap": "Mean(Ref($vwap, -1), 3)" 
        }

        # 3. 配置数据处理器 (标准化、去极值、填充缺失值)
        data_handler_config = {
            "start_time": start_date,
            "end_time": end_date,
            "fit_start_time": start_date,
            "fit_end_time": "20221231", # 用于 fit 标准化参数的区间
            "instruments": stock_list,
            "infer_processors": [
                {"class": "RobustZScoreNorm", "kwargs": {"fields_group": "feature", "clip_outlier": True}},
                {"class": "Fillna", "kwargs": {"fields_group": "feature"}}
            ],
            "learn_processors": [
                {"class": "Fillna", "kwargs": {"fields_group": "label"}}
            ]
        }
        
        # 实例化 Handler 和 Dataset
        handler = DataHandlerLP(
            instruments=stock_list,
            start_time=start_date,
            end_time=end_date,
            infer_processors=data_handler_config["infer_processors"],
            learn_processors=data_handler_config["learn_processors"],
            data_loader={
                "class": "QlibDataLoader",
                "kwargs": {
                    "config": {"feature": feature_dict, "label": label_dict}
                }
            }
        )
        # 这里仅作演示，实际训练时会切分 train/valid/test
        dataset = DatasetH(handler=handler, segments={"test": (start_date, end_date)})
        return dataset

    def get_model_prediction(self, dataset):
        """
        调用深度学习模型输出预测值
        """
        print("-> [Strategy] 正在调用深度学习模型进行推理...")
        
        # =========================================================
        # [TODO: 接入你们训练好的深度学习模型]
        # 在实际中，你们可以加载 PyTorch 的 .pth 权重，或者直接使用 Qlib 内置的 pytorch_lstm
        # 这里为了演示流水线闭环，我们 Mock (模拟) 一个输出结果
        # =========================================================
        
        # 获取清洗好的 DataFrame 特征
        df_features = dataset.prepare("test", col_set="feature")
        
        # 模拟模型输出：假设模型预测明天的中枢价格是今天收盘价的 98% 到 102% 之间震荡
        np.random.seed(42)
        mock_predictions = df_features.groupby(level='instrument').apply(
            lambda x: np.random.uniform(-0.02, 0.02, size=len(x))
        ).explode().astype(float)
        
        # 将 Series 还原为 MultiIndex (datetime, instrument) 的 DataFrame
        pred_df = pd.DataFrame(mock_predictions, index=df_features.index, columns=['pred_center_return'])
        return pred_df

    def generate_actions(self, predictions_df, current_prices, current_positions):
        """
        核心网格逻辑：将模型预测转化为具体的交易动作
        """
        print("-> [Strategy] 正在根据网格规则生成交易信号...")
        actions = {}
        
        # 遍历每一只股票的预测结果
        for stock in predictions_df.index.get_level_values('instrument').unique():
            # 获取该股票最新一天的预测收益率
            pred_return = predictions_df.loc[(slice(None), stock), 'pred_center_return'].iloc[-1]
            
            curr_price = current_prices.get(stock, 0)
            holding_vol = current_positions.get(stock, 0)
            
            if curr_price == 0:
                continue
                
            # 计算深度学习预测的未来绝对中枢价格
            predicted_center = curr_price * (1 + pred_return)
            
            # --- 结合之前讨论的导数趋势逻辑进行网格判断 ---
            
            if pred_return > self.trend_threshold:
                # Long Trend (做多趋势): 预测大幅上涨，不设卖出网格，直接做多
                actions[stock] = {"action": "BUY", "target_price": curr_price, "reason": "Long Trend"}
                
            elif pred_return < -self.trend_threshold:
                # Short Trend (做空趋势): 预测大幅下跌，紧急撤单并平仓
                if holding_vol > 0:
                    actions[stock] = {"action": "SELL", "target_price": curr_price, "reason": "Short Trend Panic"}
                    
            else:
                # Null Trend (无趋势/震荡): 开启网格高抛低吸
                buy_grid_line = predicted_center * (1 - self.grid_step)
                sell_grid_line = predicted_center * (1 + self.grid_step)
                
                if curr_price <= buy_grid_line:
                    actions[stock] = {"action": "BUY", "target_price": buy_grid_line, "reason": "Grid Buy"}
                elif curr_price >= sell_grid_line and holding_vol > 0:
                    actions[stock] = {"action": "SELL", "target_price": sell_grid_line, "reason": "Grid Sell"}
                else:
                    actions[stock] = {"action": "HOLD", "target_price": None, "reason": "In Grid Center"}
                    
        return actions

def run_strategy_pipeline(stock_list, today_str, current_prices, current_positions):
    """
    供外部 (xtquant) 调用的主函数接口
    """
    strategy = DeepGridStrategy()
    
    # 往前推取一段数据用于计算特征
    start_date = (pd.to_datetime(today_str) - pd.Timedelta(days=60)).strftime('%Y%m%d')
    
    # 1. 构建数据
    dataset = strategy.build_dataset(stock_list, start_date, today_str)
    
    # 2. 模型推理
    predictions = strategy.get_model_prediction(dataset)
    
    # 3. 生成动作
    actions = strategy.generate_actions(predictions, current_prices, current_positions)
    
    return actions