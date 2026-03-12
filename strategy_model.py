# strategy_model.py
import qlib
from qlib.data.dataset import DatasetH
from qlib.data.dataset.handler import DataHandlerLP
from pathlib import Path
from qlib.data.dataset.processor import RobustZScoreNorm, Fillna
from qlib.utils import init_instance_by_config
import pandas as pd
import numpy as np
from ruamel.yaml import YAML
import config

class DeepGridStrategy:
    def __init__(self):
        print("-> [Strategy] 正在初始化 Qlib 引擎...")
        qlib.init(provider_uri=config.QLIB_DIR, region="cn")
        
        self.grid_step = 0.015
        self.trend_threshold = 0.02
        self.model = None

    def build_dataset_and_model(self, stock_list, start_date, end_date, yaml_path="lstm_config.yaml"):
        """
        加载 YAML 配置，动态修改时间和股票池，然后实例化
        """
        print(f"-> [Strategy] 正在加载配置文件: {yaml_path}")
        
        # 1. 使用 ruamel.yaml 读取配置 (遵循你上传的官方示例)
        yaml = YAML(typ="safe", pure=True)
        config_file = Path(yaml_path).absolute().resolve()
        task_config = yaml.load(config_file.open(encoding='utf-8'))
        
        # 提取 dataset 和 model 的配置块
        dataset_config = task_config["task"]["dataset"]
        model_config = task_config["task"]["model"]
        
        # 2. 动态覆盖参数 (实盘中时间和股票池是动态变化的，不能写死在 yaml 里)
        print("-> [Strategy] 正在将动态参数注入配置...")
        
        # 修改 Handler 里的时间和股票池
        handler_kwargs = dataset_config["kwargs"]["handler"]["kwargs"]
        handler_kwargs["start_time"] = start_date
        handler_kwargs["end_time"] = end_date
        # 为了保证实盘标准化不出错，fit 时间通常固定在回测训练集的时间段
        handler_kwargs["fit_start_time"] = config.RESEARCH_START_DATE
        handler_kwargs["fit_end_time"] = "2022-12-31" 
        handler_kwargs["instruments"] = stock_list
        
        # 修改 Dataset 里的 segments (实盘推理时，只需要 test segment 有当前时间即可)
        segments = dataset_config["kwargs"]["segments"]
        # 确保 test 段的结束时间包含今天
        segments["test"] = [start_date, end_date] 
        
        # 3. 执行实例化
        print("-> [Strategy] 正在实例化 Dataset 和 Model...")
        dataset = init_instance_by_config(dataset_config)
        self.model = init_instance_by_config(model_config)
        
        # 【实盘注意】：此处仅为首次训练演示。实盘中应该 load 已有的权重文件
        print("-> [Strategy] 开始训练 LSTM 模型...")
        self.model.fit(dataset)
        
        return dataset

    def get_model_prediction(self, dataset):
        print("-> [Strategy] 正在调用 LSTM 模型进行推理...")
        predictions = self.model.predict(dataset, segment="test")
        
        if isinstance(predictions, pd.Series):
            pred_df = predictions.to_frame(name='pred_center_return')
        else:
            pred_df = predictions
            pred_df.columns = ['pred_center_return']
            
        return pred_df
    def generate_actions(self, predictions_df:pd.DataFrame, current_prices, current_positions):
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

def run_strategy(stock_list, today_str, current_prices, current_positions):
    """
    供外部 (xtquant) 调用的主函数接口
    """
    strategy = DeepGridStrategy()
    
    # 往前推取一段数据用于计算特征
    start_date = (pd.to_datetime(today_str) - pd.Timedelta(days=60)).strftime('%Y%m%d')
    
    # 1. 构建数据
    dataset = strategy.build_dataset_and_model(stock_list, start_date, today_str)
    
    # 2. 模型推理
    predictions = strategy.get_model_prediction(dataset)
    
    # 3. 生成动作
    actions = strategy.generate_actions(predictions, current_prices, current_positions)
    print(actions)
    return actions

