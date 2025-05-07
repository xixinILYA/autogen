import asyncio
import os
import sys
import logging
from typing import Sequence
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.tools.mcp import SseServerParams, mcp_server_tools
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.ui import Console
from autogen_ext.tools.http import HttpTool
from autogen_core.tools import FunctionTool
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

# 创建 ChatCompletion 客户端
G_DEEPSEEK_KEY = os.environ.get('DPSK_KEY')
if not G_DEEPSEEK_KEY:
    logger.error("DPSK_KEY environment variable not set")
    sys.exit(1)

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

async def get_mcp_tools(server_params: SseServerParams, timeout: float = 30.0) -> list:
    """获取 MCP 工具，处理服务不可用和超时的情况"""
    try:
        async with asyncio.timeout(timeout):
            tools = await mcp_server_tools(server_params)
            logger.info(f"Successfully retrieved {len(tools)} tools from {server_params.url}")
            for tool in tools:
                logger.info(f"Tool name: {tool.name}, description: {tool.description}")
            return tools
    except asyncio.TimeoutError:
        logger.error(f"Timeout after {timeout}s while retrieving tools from {server_params.url}")
        return []
    except Exception as e:
        logger.error(f"Failed to retrieve tools from {server_params.url}: {str(e)}")
        return []


# 定义 HttpTool 的 JSON Schema，用于 base64 解码
base64_schema = {
    "type": "object",
    "properties": {
        "value": {"type": "string", "description": "要解码的 base64 值"},
    },
    "required": ["value"],
}

# 创建 HttpTool，用于访问 httpbin.org 的 base64 解码 API
base64_tool = HttpTool(
    name="base64_decode",
    description="解码 base64 值的工具",
    scheme="https",
    host="httpbin.org",
    port=443,
    path="/base64/{value}",
    method="GET",
    json_schema=base64_schema,
    return_type="text",
)


# 创建文件读取工具
def file_read(file_path: str) -> str:
    """读取指定文件的内容"""
    if not file_path:
        return "Error: File path not provided."
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return content
    except FileNotFoundError:
        return f"Error: File '{file_path}' not found."
    except Exception as e:
        return f"Error reading file: {str(e)}"


# 使用 FunctionTool 包装文件读取函数
file_read_tool = FunctionTool(
    func=file_read,
    name="local_file_read",
    description="读取指定本地文件的内容",
)


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
    local_mcp_tools = await get_mcp_tools(local_server_params, timeout=5.0)
    remote_mcp_tools = await get_mcp_tools(server_params, timeout=5.0)
    mcp_tools = local_mcp_tools + remote_mcp_tools

    # 创建 MCP 代理
    mcp_agent = AssistantAgent(
        name="mcp_agent",
        model_client=model_client,
        tools=mcp_tools,
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


    # toolkit_agent 代理
    toolkit_agent = AssistantAgent(
        name="toolkit_agent",
        model_client=model_client,
        tools=[file_read_tool, base64_tool, get_host_info_by_ip, get_cost_advice],  # 使用 FunctionTool 实例
        description="读取本地文件内容, 解码base64",
        system_message=(
            "你是多面tools工具助手，专门根据用户需求调用最合适的工具。你的任务是："
            "1. 分析用户提供的任务或问题；"
            "2. 从可用的工具列表中选择最适合的工具；"
            "3. 清晰地列出你的思考过程，包括为什么选择该工具以及它如何解决任务；"
            "4. 执行选定的工具并返回其结果作为答案；"
            "5. 如果没有可用的工具或没有适合的工具，返回空消息（不提供任何回答）。"
            "约束："
            "- 答案必须严格来自tools工具的返回结果，不得自行生成或推测答案。"
            "- 如果无法找到合适的工具，明确说明原因并返回空消息。"
            "请以简洁、逻辑清晰的方式回复，确保用户能够理解你的选择依据。"
        ),
    )


    # 项目信息读取 Agent
    # project_reader_agent = AssistantAgent(
    #     name="project_reader",
    #     model_client=model_client,
    #     description="汇总信息（通过 file_agent / http_agent / mcp_agent）",
    #     system_message=(
    #         "你是信息收集专家，可以请求 file_agent / http_agent / mcp_agent 来获取数据。"
    #         "你的任务是提供准确的项目信息，而不是分析这些信息。"
    #     )
    # )
    
    report_generator_agent = AssistantAgent(
        name="report_generator",
        model_client=model_client,
        description="聚合所有专家提供的信息，生成项目评估报告。",
        system_message=(
            "你是一个项目报告生成专家，负责整合来自其他专家（如成本、安全、稳定性等）的评估结果。\n"
            "你的目标是撰写一份结构化、专业的综合评估报告，包括：每个维度的分析摘要、主要风险、改进建议和综合结论。\n"
            "请确保内容条理清晰，格式标准（可 Markdown 格式），语言简洁、专业。"
        )
    )


    # 实现 成本优化、系统稳定评估、安全评估 三个 agent; 注意每个agent都可以调用 mcp_agent 提供的工具列表来获取、验证自己需要的信息
    cost_agent = AssistantAgent(
        name="cost_analyst",
        model_client=model_client,
        description="分析项目成本",
        system_message="""
            你负责分析项目的资源、基础设施成本、并给出优化建议。
            你通过 toolkit_agent, mcp_agent 获取任务所需的数据做分析。
        """
        )

    stability_agent = AssistantAgent(
        name="stability_analyst",
        model_client=model_client,
        description="评估项目稳定性",
        system_message="""
            你负责根据日志、故障记录、重启历史等数据分析系统稳定性。
            必要时通过 toolkit_agent, mcp_agent 请求任务所需的数据做分析。
        """
        )

    security_agent = AssistantAgent(
        name="security_analyst",
        model_client=model_client,
        description="评估项目安全性",
        system_message="""
            你负责根据漏洞扫描、配置安全性、访问控制等角度评估项目的安全。
            你可以请求 toolkit_agent, mcp_agent 获取漏洞接口或配置文件。
        """
    )


    # 创建团队
    agents = [
        mcp_agent,
        toolkit_agent,
        cost_agent,
        stability_agent,
        security_agent,
        report_generator_agent
    ]

    team = SelectorGroupChat(
        participants=agents,
        model_client=model_client,
        termination_condition=lambda x: "综合报告" in x.get_last_message().content.lower(),
        max_turns=15,
        selector_prompt="""你正在参与一个软件项目评估任务，每个角色都有明确职责：

            {roles}

            请根据以下对话内容判断下一个应当发言的角色（从 {participants} 中选择）：
            - 哪个角色能有效推动话题深入？
            - 是否需要某角色提供数据、分析或总结？
            - 各角色给出的结论是否可交由 report_generator 输出最终报告？

            {history}

            请选择一个角色继续对话，只返回角色名。
            """
        )

    # 执行任务
    task = """
        你们是一组虚拟专家团队，正在对一个软件开发项目进行全面评估。团队由以下3个角色组成：
        - 成本分析专家（Cost Analyst）
        - 系统稳定性顾问（Stability Specialist）
        - 安全性专家（Security Analyst）

        你们的任务是从各自角度出发，评估该项目在成本、系统稳定性和安全性方面的表现，并在必要时主动向其他专家提问或请求补充信息。

        最终目标是生成一份结构化的《架构评审综合报告》，内容包括：
        1. 各角色对该项目的专业分析
        2. 各维度存在的风险或优化建议
        3. 一份结论性评估和整体建议

        请开始评估任务。
    """
    try:
        async with asyncio.timeout(60.0):
            await Console(team.run_stream(task))
    except asyncio.TimeoutError:
        logger.error("Task execution timed out after 60 seconds")
    except Exception as e:
        logger.error(f"Error during task execution: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
