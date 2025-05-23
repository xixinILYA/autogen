import asyncio
import os
import logging
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.tools.mcp import SseServerParams, mcp_server_tools
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_core import CancellationToken

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # 输出到控制台
        logging.FileHandler('mcp_agent.log')  # 输出到文件
    ]
)
logger = logging.getLogger(__name__)

async def get_mcp_tools(server_params: SseServerParams, timeout: float = 30.0) -> list:
    """获取 MCP 工具，处理服务不可用和超时的情况"""
    try:
        # 使用 asyncio.timeout 设置整体超时
        async with asyncio.timeout(timeout):
            tools = await mcp_server_tools(server_params)
            logger.info(f"Successfully retrieved {len(tools)} tools from {server_params.url}")
            return tools
    except asyncio.TimeoutError:
        logger.error(f"Timeout after {timeout}s while retrieving tools from {server_params.url}")
        return []
    except Exception as e:
        logger.error(f"Failed to retrieve tools from {server_params.url}: {str(e)}")
        return []

async def main() -> None:
    # 配置 MCP 服务的 SSE 连接参数
    local_server_params = SseServerParams(
        url="http://192.168.58.14:8400/sse",
        headers={"Content-Type": "application/json"},
        timeout=10,
    )

    server_params = SseServerParams(
        url="http://dev.apigateway.kgidc.cn/b-ai-mcpserver/v1/sse",
        headers={
            "Content-Type": "application/json",
            "opdAppid": "v1-6810a318b7195",
            "opdAppsecret": "4759a8425d265ed5209a709f6b39dd3b"
        },
        timeout=10,
    )

    # 获取 MCP 工具，设置30秒超时
    local_tools = await get_mcp_tools(local_server_params, timeout=10.0)
    tools = await get_mcp_tools(server_params, timeout=10.0)

    # 创建一个 ChatCompletion 客户端（使用 OpenAI 的 GPT 模型）
    G_DEEPSEEK_KEY = os.environ.get('DPSK_KEY')
    if not G_DEEPSEEK_KEY:
        logger.error("DPSK_KEY environment variable not set")
        return

    model_client = OpenAIChatCompletionClient(
        model="deepseek-chat",
        base_url="https://api.deepseek.com",
        api_key=G_DEEPSEEK_KEY,
        model_info={
            "vision": False,
            "function_calling": True,
            "structured_output": True,
            "json_output": True,
            "family": "unknown",
        },
    )

    # 创建 Agent 并注册工具
    mcp_agent = AssistantAgent(
        name="mcp_agent",
        model_client=model_client,
        tools=local_tools + tools,
        system_message=(
            "你是一个智能助手，擅长使用 MCP 工具。你的任务是："
            "1. 分析用户提供的任务或问题；"
            "2. 从可用 MCP 工具列表中选择最适合的工具；"
            "3. 清晰地列出你的思考过程，包括为什么选择该工具以及它如何解决任务；"
            "4. 如果需要，执行选定的 MCP 工具并提供结果。"
            "请以简洁、逻辑清晰的方式回复，确保用户能够理解你的选择依据。"
            "如果没有可用的 MCP 工具，直接说明并提供替代方案。"
        ),
    )

    # 执行任务，让 Agent 使用远程工具
    try:
        async with asyncio.timeout(60.0):  # 设置任务整体超时为60秒
            await Console(
                mcp_agent.run_stream(
                    task="计算 44 + 43 的和是多少",
                    cancellation_token=CancellationToken()
                )
            )
    except asyncio.TimeoutError:
        logger.error("Task execution timed out after 60 seconds")
    except Exception as e:
        logger.error(f"Error during task execution: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
