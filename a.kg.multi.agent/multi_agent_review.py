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
    level=logging.WARN,
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
    description="解码任意 base64 字符串",
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

# get_host_info_by_ip 工具的 JSON Schema 定义
get_host_info_by_ip_schema = {
    "type": "object",
    "properties": {
        "ip": {"type": "string", "description": "要查询的主机IP地址"}
    },
    "required": ["ip"]
}

# 创建 HttpTool，用于访问获取主机信息的API
get_host_info_by_ip = HttpTool(
    name="get_host_info_by_ip",
    description="根据 IP 地址查询主机的 CPU、内存使用率和硬件配置",
    scheme="http",
    # host="your-api-server",  # 替换为实际API服务器地址
    # port=80,
    host="192.168.58.14",
    port=8001,
    path="/api/hostinfo/{ip}",  # API路径，确保{ip}路径参数被正确处理
    method="GET",
    json_schema=get_host_info_by_ip_schema,
    return_type="json",
)


# get_cost_advice 工具的 JSON Schema 定义
get_cost_advice_schema = {
    "type": "object",
    "properties": {
        "cpu_usg": {"type": "number", "description": "CPU使用率"},
        "mem_usg": {"type": "number", "description": "内存使用率"},
        "cpu_hardware": {"type": "number", "description": "CPU硬件配置"},
        "mem_hardware": {"type": "number", "description": "内存硬件配置"},
        "machine_type": {"type": "string", "description": "机器类型"},
        "machine_class": {"type": "string", "description": "机器规格"}
    },
    "required": ["cpu_usg", "mem_usg", "cpu_hardware", "mem_hardware", "machine_type", "machine_class"]
}


# 创建 HttpTool，用于调用 Dify 工作流 API 获取成本优化建议
get_cost_advice = HttpTool(
    name="get_cost_advice",
    description="根据主机资源使用，主机硬件配置情况，生成成本优化建议（适用于成本分析）",
    scheme="http",
    host="192.168.58.14",
    port=8001,
    path="/v1/workflows/run",
    method="POST",
    json_schema={
        "type": "object",
        "properties": {
            "cpu_usg": {"type": "number", "description": "CPU使用率"},
            "mem_usg": {"type": "number", "description": "内存使用率"},
            "cpu_hardware": {"type": "number", "description": "CPU硬件配置"},
            "mem_hardware": {"type": "number", "description": "内存硬件配置"},
            "machine_type": {"type": "string", "description": "机器类型"},
            "machine_class": {"type": "string", "description": "机器规格"},
            "response_mode": {"type": "string", "default": "blocking"},
            "user": {"type": "string", "default": "pipeline"}
        },
        "required": ["cpu_usg", "mem_usg", "cpu_hardware", "mem_hardware", "machine_type", "machine_class"]
    },
    headers={
        'Authorization': '{{sk.cvmonlinedify}}',
        'Content-Type': 'application/json'
    },
    return_type="json",
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

    # toolkit_agent 代理
    toolkit_agent = AssistantAgent(
        name="toolkit_agent",
        model_client=model_client,
        tools= mcp_tools + [file_read_tool, base64_tool, get_host_info_by_ip, get_cost_advice],  # 使用 FunctionTool 实例
        description="读取本地文件内容, 解码base64, 获取主机信息, 获取成本信息, 包含所有 MCP 工具",
        system_message=(
            "你是多面tools工具助手，能配合专家角色的要求调用最合适的工具。\n"
            "【工作方式】：\n"
            "1. 分析任务对话最后一个专家角色要求的任务；\n"
            "2. 从可用的工具列表中选择最适合该任务的工具；\n"
            "3. 如果没有可用的工具或没有适合的工具，直接返回空消息（暂无工具可用）；\n"
            "4. 清晰地列出你的思考过程，包括为什么选择该工具以及它如何解决任务；\n"
            "5. 执行选定的工具并返回其结果作为答案。\n"
            
            "【约束】：\n"
            "- 所有答案必须来源于实际工具返回的结果，禁止推测或生成；\n"
            "- 如果无法找到合适的工具，简洁说明并终止任务。\n"
            "请以简洁、逻辑清晰的方式回复，确保下一个角色能够理解你回复的内容。\n"
        ),
    )


    # 项目关联信息读取 Agent
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
            "你是一个项目报告生成专家，负责整合来自其他专家的分析内容，输出结构化评估报告。\n\n"
            "【任务目标】：\n"
            "1. 汇总各角色提供的内容（cost_analyst / stability_analyst / security_analyst）；\n"
            "2. 如果部分专家声明无法完成任务，你需要将此作为“信息缺失风险”写入报告；\n"
            "3. 报告结构包括：分析摘要、风险项、建议、结论；\n"
            "4. 使用 Markdown 格式输出，语言简洁专业；\n"
            "5. 最后一行以 'MISSION COMPELET' 结束。"
        )
    )


    # 实现 成本优化、系统稳定评估、安全评估 三个 agent; 注意每个agent都可以调用 toolkit_agent 提供的工具列表来获取、验证自己需要的信息
    cost_agent = AssistantAgent(
        name="cost_analyst",
        model_client=model_client,
        description="分析项目成本并给出优化建议",
        system_message="""
            你负责分析项目的资源、基础设施成本、并给出优化建议。
            你优先通过 toolkit_agent 智能体工具，来获取分析项目成本所需的数据。
        """
        )

    stability_agent = AssistantAgent(
        name="stability_analyst",
        model_client=model_client,
        description="评估项目稳定性并给出处置建议",
        system_message="""
            你负责根据日志、故障记录、重启历史等数据分析系统稳定性。
            必要时通过 toolkit_agent 请求任务所需的数据做分析。
        """
        )

    security_agent = AssistantAgent(
        name="security_analyst",
        model_client=model_client,
        description="评估项目安全性并给出处置建议",
        system_message="""
            你负责根据漏洞扫描、配置安全性、访问控制等角度评估项目的安全。
            你可以请求 toolkit_agent 获取漏洞接口或配置文件。
        """
    )


    mention_termination = TextMentionTermination("MISSION COMPELET")


    # 创建团队
    agents = [
        toolkit_agent,
        cost_agent,
        stability_agent,
        security_agent,
        report_generator_agent
    ]

    team = SelectorGroupChat(
        participants=agents,
        model_client=model_client,
        termination_condition=mention_termination,
        allow_repeated_speaker=True,
        max_turns=15,
        selector_prompt = """
            你正在参与一个软件架构评审任务，团队由多个专家角色组成，每个角色有其明确的职责。

            【角色职责】：
            {roles}

            【任务目标】：
            从成本、稳定性、安全性等多个维度完成分析，最终由报告生成专家（report_generator）汇总形成最终报告。

            【发言规则（按优先级排序）】：
            1. 如果有角色尚未发言，优先选择这些角色继续分析；
            2. 如果某个角色已经发言，但还有进一步分析空间或补充问题，也可再次选择；
            3. 如果某个角色明确声明“无法完成任务”，则不再选择该角色；
            4. 仅当所有分析角色（cost_analyst / stability_analyst / security_analyst）都已完成任务（至少发言一次），且内容没有冲突时，才可选择 report_generator 开始汇总；
            5. 若当前轮次中所有角色都无新信息提供，可提前终止对话；
            6. 每轮只选择一个最合适的角色继续发言，避免重复发言或空转。

            【当前对话历史】：
            {history}

            请根据以上规则，从参与者列表 {participants} 中选择下一个发言角色。
            只返回该角色名，不要输出其他内容。"""
        )

    # 执行任务
    task = """
        你们是一组虚拟专家团队，正在对一个软件开发项目(该项目的ip地址是 10.5.140.9)进行全面评估。
        团队由以下3个角色组成：
        - 成本分析专家（cost_analyst）
        - 系统稳定性顾问（stability_analyst）
        - 安全性专家（security_analyst）

        你们的任务是从各自角度出发，评估该项目在成本、系统稳定性和安全性方面的表现，并在必要时主动向其他专家提问或请求补充信息。

        最终目标是由 report_generator 生成一份结构化的《架构评审综合报告》，内容包括：
        1. 各角色对该项目的专业分析
        2. 各维度存在的风险或优化建议
        3. 一份结论性评估和整体建议

        请开始评估任务。
    """
    try:
        async with asyncio.timeout(300.0):
            await Console(team.run_stream(task=task))
    except asyncio.TimeoutError:
        logger.error("Task execution timed out after 300 seconds")
    except Exception as e:
        logger.error(f"Error during task execution: {str(e)}")

if __name__ == "__main__":
    asyncio.run(main())
