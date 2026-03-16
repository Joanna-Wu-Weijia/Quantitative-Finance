# server_api.py (运行在 Linux 服务器上)
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Dict
import traceback

# 导入你们写好的策略入口函数
from strategy_model import run_strategy

# ==========================================
# 1. 定义数据接收模型 (Pydantic Schema)
# 这必须与 Windows 端 trader.py 发送的 payload 格式严格一致
# ==========================================
class StrategyRequest(BaseModel):
    stock_list: List[str]             # 例如: ["SZ000001", "SH600000"]
    today_str: str                    # 例如: "20231025"
    current_prices: Dict[str, float]  # 例如: {"SZ000001": 10.5, "SH600000": 8.2}
    current_positions: Dict[str, int] # 例如: {"SZ000001": 1000}

# ==========================================
# 2. 初始化 FastAPI 服务
# ==========================================
app = FastAPI(title="Quant Signal Server", description="深度学习网格策略推理服务")

@app.on_event("startup")
async def startup_event():
    print("-> [Server] AI 推理服务已启动，等待接收 Windows 节点数据...")
    # 如果你们的模型很大，建议在这里提前加载 PyTorch 模型权重到内存中
    # 避免每次收到请求时都重新加载模型

# ==========================================
# 3. 定义 POST 路由处理函数
# ==========================================
@app.post("/get_target_actions")
async def get_actions(request_data: StrategyRequest):
    """
    接收来自 Windows 的账户状态，进行模型推理并返回交易指令
    """
    print(f"\n-> [Server] 收到 Windows 节点请求，计算日期: {request_data.today_str}")
    print(f"-> [Server] 收到的标的池: {request_data.stock_list}")
    
    try:
        # 解包 Pydantic 模型数据，喂给你们的 Qlib 策略大脑
        actions = run_strategy(
            stock_list=request_data.stock_list,
            today_str=request_data.today_str,
            current_prices=request_data.current_prices,
            current_positions=request_data.current_positions
        )
        
        print("-> [Server] 推理完成，已生成交易动作！")
        
        # 组装成功响应，发回给 Windows
        return {
            "status": "success",
            "message": "推理成功",
            "data": actions
        }
        
    except Exception as e:
        # 捕获推理过程中的任何错误，并把错误信息打印在 Linux 端，同时返回给 Windows 端
        error_msg = f"策略执行失败: {str(e)}"
        print(f"-> [Error] {error_msg}")
        traceback.print_exc() # 在 Linux 控制台打印完整错误栈
        
        # 返回友好的错误 JSON 给 Windows
        return {
            "status": "error",
            "message": error_msg,
            "data": {}
        }

if __name__ == "__main__":
    # 在 Linux 上启动服务，0.0.0.0 允许局域网/公网访问
    # 端口保持与 config.py 中的 LINUX_SERVER_PORT 一致
    uvicorn.run(app, host="0.0.0.0", port=1214)