import asyncio
import os
import logging
from typing import Sequence
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.tools.mcp import SseServerParams, mcp_server_tools
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.ui import Console
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # 输出到控制台
        logging.FileHandler('multi_agent_mcp.log')  # 输出到文件
    ]
)
logger = logging.getLogger(__name__)

async def get_mcp_tools(server_params: SseServerParams, timeout: float = 30.0) -> list:
    """获取 MCP 工具，处理服务不可用和超时的情况"""
    try:
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

    # 获取 MCP 工具
    local_tools = await get_mcp_tools(local_server_params, timeout=5.0)
    tools = await get_mcp_tools(server_params, timeout=5.0)

    # 创建 ChatCompletion 客户端
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

    # 创建 MCP 代理
    mcp_agent = AssistantAgent(
        name="mcp_agent",
        model_client=model_client,
        tools=local_tools + tools,
        description="MCP tools",
        system_message=(
            "你是 MCP 工具助手，专门根据用户需求调用最合适的 MCP 工具。你的任务是："
            "1. 分析用户提供的任务或问题；"
            "2. 从可用 MCP 工具列表中选择最适合的工具；"
            "3. 清晰地列出你的思考过程，包括为什么选择该工具以及它如何解决任务；"
            "4. 执行选定的 MCP 工具并返回其结果作为答案；"
            "5. 如果没有可用的 MCP 工具或没有适合的工具，返回空消息（不提供任何回答）。"
            "约束："
            "- 答案必须严格来自 MCP 工具的返回结果，不得自行生成或推测答案。"
            "- 如果无法找到合适的 MCP 工具，明确说明原因并返回空消息。"
            "- 不要在没有 MCP 工具的情况下尝试回答任务。"
            "请以简洁、逻辑清晰的方式回复，确保用户能够理解你的选择依据。"
        ),
    )

    # 创建检查代理
    def check_calculation(x: int, y: int, answer: int) -> str:
        if x + y == answer:
            return "Correct!"
        else:
            return "Incorrect!"

    checker_agent = AssistantAgent(
        name="checker_agent",
        model_client=model_client,
        tools=[check_calculation],
        description="For checking calculation",
        system_message=(
            "你是检查计算结果的助手，仅当收到明确的计算结果时，调用 check_calculation 工具验证答案，返回 'Correct!' 或 'Incorrect!'。"
            "如果未收到符合格式的计算结果，返回空消息。"
            "约束："
            "- 不得自行推测或回答任务。"
            "- 仅检查任务结果是否正确。"
        ),
    )


    # 创建团队
    termination = TextMentionTermination("Correct!")
    team = SelectorGroupChat(
        participants=[mcp_agent, checker_agent],
        model_client=model_client,
        termination_condition=termination,
        max_turns=5,
        selector_prompt="""You are in a role play game. The following roles are available:
            {roles}.
            Read the following conversation. Then select the next role from {participants} to play. Only return the role.

            {history}

            Read the above conversation. Then select the next role from {participants} to play. Only return the role.
        """
    )

    # 执行任务
    try:
        async with asyncio.timeout(60.0):
            await Console(team.run_stream(task="What is 1 + 1?"))
    except asyncio.TimeoutError:
        logger.error("Task execution timed out after 60 seconds")
    except Exception as e:
        logger.error(f"Error during task execution: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
