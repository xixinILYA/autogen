import asyncio
import os
import sys
import logging
from typing import Sequence
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.tools.mcp import SseServerParams, mcp_server_tools
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.ui import Console
from autogen_ext.tools.http import HttpTool
from autogen_core.tools import FunctionTool
from pydantic import BaseModel
from typing import Any
from autogen_core import CancellationToken  # 如果你的包没有，再用 autogen_agentchat.conditions 或 cancellation_token 路径


# Logging config
logging.basicConfig(
    level=logging.WARN,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('multi_agent_mcp.log')
    ]
)
logger = logging.getLogger(__name__)

# 环境配置: 
# 测试->生产
if os.getenv("aKl8saxxDh9v7b_Kugou_ML_Namespace_Test") == "breezejiang":
    g_dify_workflow_host = "dify.opd.kugou.net"
    g_aiops_api_host = "machinelearning.opd.kugou.net"
    g_model_base_url = "https://api.lkeap.cloud.tencent.com/v1"
# 生产
else:
    g_dify_workflow_host = "dify.kgidc.cn"
    g_aiops_api_host = "opdproxy.kgidc.cn"
    g_model_base_url = "http://10.5.140.80:8880/v1/chat/completions"
    

# 大模型 LLM 使用deepseek
G_DEEPSEEK_KEY = os.environ.get('DPSK_KEY')
if not G_DEEPSEEK_KEY:
    logger.error("DPSK_KEY environment variable not set")
    sys.exit(1)

# model_client = OpenAIChatCompletionClient(
#     model="deepseek-chat",
#     base_url="https://api.deepseek.com",
#     api_key=G_DEEPSEEK_KEY,
#     model_info={"vision": False, "function_calling": True, "structured_output": True, "json_output": True, "family": "unknown"}
# )

model_client = OpenAIChatCompletionClient(
    model="deepseek-v3",
    base_url=g_model_base_url,
    api_key=G_DEEPSEEK_KEY,
    model_info={"vision": False, "function_calling": True, "structured_output": True, "json_output": True, "family": "unknown"}
)


# 工具列表定义：Tool definitions
async def get_mcp_tools(server_params: SseServerParams, timeout: float = 30.0) -> list:
    """获取 MCP 工具，处理服务不可用和超时的情况"""
    try:
        async with asyncio.timeout(timeout):
            tools = await mcp_server_tools(server_params)
            logger.info(f"Successfully retrieved {len(tools)} tools from {server_params.url}")
            for tool in tools:
                logger.warning(f"Tool name: {tool.name}, description: {tool.description}")
            return tools
    except asyncio.TimeoutError:
        logger.error(f"Timeout after {timeout}s while retrieving tools from {server_params.url}")
        return []
    except Exception as e:
        logger.error(f"Failed to retrieve tools from {server_params.url}: {str(e)}")
        return []


# 创建 HttpTool，用于访问 httpbin.org 的 base64 解码 API
base64_tool = HttpTool(
    name="base64_decode",
    description="解码任意 base64 字符串",
    scheme="https",
    host="httpbin.org",
    port=443,
    path="/base64/{value}",
    method="GET",
    json_schema={
        "type": "object",
        "properties": {
            "value": {"type": "string", "description": "要解码的 base64 值"},
        },
        "required": ["value"],
    },
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


# 创建 HttpTool，用于访问获取主机信息的API
get_host_info = HttpTool(
    name="get_host_info",
    description="根据 ip 地址查询主机的 CPU、内存使用率和硬件型号",
    scheme="http",
    host=g_aiops_api_host,
    port=80,
    path="/b-aiops-ml/v1/GetSshipCpumemInfo",  # API路径，确保{ip}路径参数被正确处理
    method="GET",
    json_schema={
        "type": "object",
        "properties": {
            "sship": {"type": "string", "description": "要查询的主机ip地址"}
        },
        "required": ["sship"]
    },
    return_type="json",
)


# 创建 HttpTool，用于调用 Dify 工作流 API 获取成本优化建议
get_cost_advice = HttpTool(
    name="get_cost_advice",
    description="根据主机资源使用和主机硬件配置情况，生成成本优化建议（适用于成本分析）",
    scheme="http",
    host=g_dify_workflow_host,
    port=80,
    path="/v1/workflows/run",
    method="POST",
    json_schema={
        "type": "object",
        "properties": {
            "inputs": {
                "type": "object",
                "description": "请求的输入参数",
                "properties": {
                    "cpu_precent": {"type": "number", "description": "CPU使用率"},
                    "mem_precent": {"type": "number", "description": "内存使用率"},
                    "cpu": {"type": "number", "description": "CPU硬件配置"},
                    "mem": {"type": "number", "description": "内存硬件配置"},
                    "machine_type": {"type": "string", "description": "机器类型"},
                    "machine_specification": {"type": "string", "description": "机器规格"}
                },
                "required": ["cpu_precent", "mem_precent", "cpu", "mem", "machine_type", "machine_specification"]
            },
            "response_mode": {
                "type": "string",
                "description": "响应模式",
                "enum": ["blocking", "streaming"],
                "default": "blocking"
            },
            "user": {
                "type": "string",
                "description": "请求发起的用户标识",
                "default": "pipeline"
            }
        },
        "required": ["inputs", "response_mode", "user"]
    },
    headers={
        'Authorization': 'Bearer app-0E73Ys4ywhawXOM7LmiGgVqa',
        'Content-Type': 'application/json'
    },
    return_type="json",
)


# 稳定性相关的 http 工具
get_rmsid_info = HttpTool(
    name="get_rmsid_info",
    description="根据 rmsid 查询项目的 资源使用情况",
    scheme="http",
    host=g_aiops_api_host,
    port=80,
    path="/b-aiops-ml/v1/GetRmsidInfo",
    method="GET",
    json_schema={
        "type": "object",
        "properties": {
            "rmsid": {"type": "string", "description": "要查询的rmsid"}
        },
        "required": ["rmsid"]
    },
    return_type="json",
)


get_stability_advice = HttpTool(
    name="get_stability_advice",
    description="根据主机和集群资源使用情况，生成稳定性优化建议（适用于稳定性分析）",
    scheme="http",
    host=g_dify_workflow_host,
    port=80,
    path="/v1/workflows/run",
    method="POST",
    json_schema={
        "type": "object",
        "properties": {
            "inputs": {
                "type": "object",
                "description": "请求的输入参数",
                "properties": {
                    "data_info": {
                        "type": "string",
                        "description": "包含IDC和Kubernetes资源使用情况的JSON字符串"
                    }
                },
                "required": ["data_info"]
            },
            "response_mode": {
                "type": "string",
                "description": "响应模式",
                "enum": ["blocking", "streaming"],
                "default": "blocking"
            },
            "user": {
                "type": "string",
                "description": "请求发起的用户标识",
                "default": "pipeline"
            }
        },
        "required": ["inputs", "response_mode", "user"]
    },
    headers={
        'Authorization': 'Bearer app-EhbX9cVwhoZ7kVrISoYO6c1d',
        'Content-Type': 'application/json'
    },
    return_type="json",
)


# 安全相关的 http 工具
get_security_info = HttpTool(
    name="get_security_info",
    description="根据 IP 地址查询主机的安全信息，如漏洞、入侵检测记录等",
    scheme="http",
    host="192.168.58.14",
    port=8001,
    path="/api/security/{ip}",
    method="GET",
    json_schema={
        "type": "object",
        "properties": {
            "ip": {"type": "string", "description": "目标主机的 IP 地址"}
        },
        "required": ["ip"]
    },
    return_type="json",
)


def is_tool_fail(msg) -> bool:
    # 针对 ToolCallExecutionEvent
    if getattr(msg, "type", None) == "ToolCallExecutionEvent":
        content = getattr(msg, "content", None)
        if isinstance(content, list):
            # 只要有一个 is_error=True
            return any(getattr(x, "is_error", False) for x in content)
        # 如果 content 本身有 is_error
        if hasattr(content, "is_error"):
            return getattr(content, "is_error")
    elif getattr(msg, "type", None) == "ToolCallSummaryMessage":
        content = getattr(msg, "content", None)
        if content in ("", "\n", None, "null"):
            return True
    # 兼容性兜底
    elif  hasattr(msg, "is_error") and getattr(msg, "is_error"):
        return True
    else:
        return False


def selector_func_core(messages: Sequence[BaseAgentEvent | BaseChatMessage], max_failures=2) -> str | None:
    analysis_agents = ["cost_analyst", "stability_analyst", "security_analyst"]
    report_agent = "report_generator"

    latest_reply = {agent: None for agent in analysis_agents + [report_agent]}
    for msg in reversed(messages):
        name = getattr(msg, "source", None)
        if name in latest_reply and latest_reply[name] is None:
            content = msg.to_text() if hasattr(msg, "to_text") else str(getattr(msg, "content", ""))
            latest_reply[name] = content

    # 检查有无 agent 没“完成/终止”
    waiting_agents = [
        agent for agent in analysis_agents
        if not (latest_reply[agent] or "").strip().endswith(("任务完成", "任务终止", "任务完成.", "任务终止.", "任务完成。", "任务终止。"))
    ]
    if not waiting_agents:
        return None

    # 按顺序轮询每个 agent
    for current_agent in waiting_agents:
        # 检查最近消息里是否连续多次工具调用失败
        fail_count = 0
        for msg in reversed(messages):
            if getattr(msg, "source", None) != current_agent:
                continue
            if is_tool_fail(msg):
                logger.warning(f"----------------->>>> {current_agent} fail: {msg}")
                fail_count += 1
            else:
                break   # 一旦遇到不是失败，停止统计
        if fail_count >= max_failures:
            logger.warning(f"{current_agent} fail_count: {fail_count}, skip {current_agent}")
            continue    # 本轮跳过，试下一个 agent
        return current_agent

    # 所有 waiting_agents 都连续失败超过上限，交给大模型选择
    return None


def selector_func(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> str | None:
    try:
        agent = selector_func_core(messages)
        logger.info(f"----------------->>>> Selector function returned: {agent}")
        return agent
    except Exception as e:
        logger.error(f"----------------->>>> Selector function returned: None, use selector_prompt")
        return None


async def main():
    local_server_params = SseServerParams(url="http://192.168.58.14:8400/sse", headers={"Content-Type": "application/json"}, timeout=10)
    server_params = SseServerParams(
        url="http://dev.apigateway.kgidc.cn/b-ai-mcpserver/v1/sse",
        headers={"Content-Type": "application/json", "opdAppid": "v1-6810a318b7195", "opdAppsecret": "4759a8425d265ed5209a709f6b39dd3b"},
        timeout=10
    )
    local_mcp_tools = await get_mcp_tools(local_server_params, timeout=5.0)
    remote_mcp_tools = await get_mcp_tools(server_params, timeout=5.0)

    # 工具功能分类
    mcp_cost_tools = [tool for tool in local_mcp_tools + remote_mcp_tools if "cost" in tool.name or "usage" in tool.name]
    mcp_stability_tools = [tool for tool in local_mcp_tools + remote_mcp_tools if "log" in tool.name or "restart" in tool.name]
    mcp_security_tools = [tool for tool in local_mcp_tools + remote_mcp_tools if "vuln" in tool.name or "config" in tool.name]

    cost_agent = AssistantAgent(
        name="cost_analyst",
        model_client=model_client,
        tools=mcp_cost_tools + [get_rmsid_info, get_host_info, get_cost_advice],
        description="分析项目成本并给出优化建议，能够获取项目资源信息、调用成本分析服务",
        system_message="""
            你是负责分析项目资源成本的专家。你的每次分析回复最后一行必须输出“任务完成”、“任务未完成”、“任务终止”。
            你的职责是：
            - 首先调用 get_rmsid_info 工具获取项目汇总信息；
            - 然后调用 get_host_info 工具(参数来自 get_rmsid_info 响应的 ipList 列表)获取项目相关的 Redis、K8S、Mysql、主机CVM 等资源、硬件配置相关的数据；
            - 最后调用 get_cost_advice 工具(参数来自 get_host_info 响应) 获取优化建议；
            - 仅使用工具返回的数据作为依据，清晰地陈述你的分析过程、数据来源和最终的优化结论；
            - 工具未调用完，最后一行回复 “任务未完成”；
            - 工具调用异常或数据缺失，最后一行回复 “任务终止”；

            注意：
            - 你的回答应专注于“成本分析”这一维度；
            - **请勿整合其他专家的结论试图生成最终的《架构评审综合报告》**；
            - 最终《架构评审综合报告》将由 report_generator 专家整理，请勿重复或越权执行该任务。
        """
        )

    stability_agent = AssistantAgent(
        name="stability_analyst",
        model_client=model_client,
        tools=mcp_stability_tools + [get_rmsid_info, get_stability_advice],
        description="评估项目稳定性并给出处置建议",
        system_message="""
            你是负责评估系统稳定性的专家。你的每次分析回复最后一行必须输出“任务完成”、“任务未完成”、“任务终止”。
            你的职责是：
            - 调用 get_rmsid_info 工具获取项目信息；调用 get_stability_advice 工具 (参数 data_info 是 get_rmsid_info 响应的 data 的 dumps 字符串) 获取项目相关的 日志、告警、故障记录等；
            - 分析日志、告警、故障记录等评估系统是否存在不稳定风险；
            - 清晰地陈述你的分析过程、数据来源和最终的优化建议。
            - 工具未调用完，最后一行回复 “任务未完成”；
            - 工具调用异常或数据缺失，最后一行回复 “任务终止”；

            注意：
            - 你的职责仅限于“稳定性分析”；
            - **请勿整合其他专家的结论试图生成最终的《架构评审综合报告》**；
            - 最终《架构评审综合报告》将由 report_generator 专家整理，请勿重复或越权执行该任务。
        """
    )

    security_agent = AssistantAgent(
        name="security_analyst",
        model_client=model_client,
        tools=mcp_security_tools + [get_security_info],
        description="评估项目安全性并给出处置建议",
        system_message="""
            你是负责评估系统安全性的专家。你的每次分析回复最后一行必须输出“任务完成”、“任务未完成”、“任务终止”。
            你的职责是：
            - 调用 get_security_info 等工具获取项目相关的配置文件、访问权限和漏洞等安全信息；
            - 如果工具返回的信息不足或返回错误，应明确说明“安全信息缺失”或具体错误，最后一行回复 “任务终止”；
            - 仅当调用的工具获取到明确有效的安全信息（如具体漏洞或入侵事件）时，才提供针对性的风险提示和修复建议。

            注意：
            - 你的职责仅限于“安全性分析”；
            - **请勿整合其他专家的结论试图生成最终的《架构评审综合报告》**；
            - 最终《架构评审综合报告》将由 report_generator 专家整理，请勿重复或越权执行该任务。
        """
    )

    report_generator = AssistantAgent(
        name="report_generator",
        model_client=model_client,
        description="整理所有专家的结论，生成结构化报告",
        system_message="""
            你是一个项目评估报告专家。
            你的职责是：
            - 整理来自成本分析、安全评估和稳定性分析专家的内容；
            - 如果部分专家声明无法完成任务，你需要将此作为“信息缺失风险”写入报告；
            - 不参与分析，仅组织他们的结论；
            - 报告包括：项目简介(关联那些资源、比如主机、k8s pod、redis、mysql 等)、分析摘要、风险项(Markdown格式）。
            - 报告中的所有建议必须指明具体的对象，如“主机 IP”、“集群名称”、“Pod 名称”、“myql集群”、“redis集群”等，不能只写‘调整资源’这类泛化建议。
            - 最后一行以 'MISSION COMPLETE' 结尾。
        """
        )

    termination = TextMentionTermination("MISSION COMPLETE")
    team = SelectorGroupChat(
        participants=[cost_agent, stability_agent, security_agent, report_generator],
        model_client=model_client,
        termination_condition=termination,
        selector_func=selector_func,
        allow_repeated_speaker=True,
        max_turns=25,
        selector_prompt = """
            你是一个智能调度器，负责在一个软件架构评审的多专家团队中选择下一个发言者。

            【专家角色及其专长】：
            {roles}

            【核心任务目标】：
            对提供的软件架构进行全面的多维度（成本、稳定性、安全性）分析。

            【发言选择规则 (严格按以下优先级顺序执行)】：
            1.  **未发言者优先**: 如果参与者列表中有专家（非 report_generator）尚未发言，从中选择一位。
            2.  **响应直接请求**: 如果上一位专家指名要求特定角色 (例如 "@security_agent, 请你分析一下...") 发言，则选择被指名的角色。
            3.  **避免无效参与**: 如果某个角色明确表示 “任务已完成”、“任务终止”、“没有其他意见”或类似表述，则在当前分析阶段不再选择该角色。
            4.  **推动任务进展**: 如果某个发言者还没有表示 “任务已完成”、“任务终止”，则继续选择该角色发言。
            5.  **报告生成阶段**:
                * **前提条件**: 仅当所有分析专家（cost_analyst、stability_analyst、security_analyst）最近一次回复的最后一行为“任务已完成”或“任务终止”时，才可以选择 report_generator 进入综合汇总阶段。否则，优先继续选择尚未完成任务的分析专家发言。
                * **冲突解决指示 (重要)**: 如果分析专家之间存在明显未解决的观点冲突 (例如，成本优化建议显著降低了安全性，且未达成共识)，则**不得**选择 report_generator。此时，应优先选择能够调和冲突或对争议点提供进一步澄清的分析专家。
                * 一旦前提条件满足且无明显冲突，选择 report_generator 开始汇总报告。

            【当前对话历史】：
            {history}

            【参与者列表】：
            {participants}

            请严格根据上述【发言选择规则】和【当前对话历史】，从【参与者列表】中选择最合适的下一个发言角色。
            仅返回角色名称 (例如: cost_agent)，不要包含任何解释或额外文本。
            """
        )


    # 执行任务
    rmsid = 10252
    # rmsid = 10272
    task = f"""
        你们是一个虚拟专家团队，当前任务是对一个软件开发项目进行联合评估。
        【项目关键信息】：该项目的 rmsid 是 {rmsid}, 请将此 rmsid 作为你们分析的起点和核心关注点。

        【团队角色与核心贡献领域】：
        - 成本分析专家 (cost_analyst): 负责从成本效益角度评估项目，并提供资源和预算相关的分析。
        - 稳定性专家 (stability_analyst): 负责从系统运行的稳定性和可靠性角度评估项目。
        - 安全性专家 (security_analyst): 负责从系统安全配置、潜在风险和漏洞角度评估项目。
        - 报告生成专家 (report_generator): 负责整合所有专家的核心分析结论，形成最终的综合评估报告。

        【团队协作指南与最终目标】：
        1.  请各位分析专家（cost_analyst, stability_analyst, security_analyst）围绕项目 rmsid 是 {rmsid} 的项目，从各自的专业领域出发，进行分析，识别潜在问题或风险，并提出具体的改进建议。
        2.  鼓励你们在评估过程中进行必要的互动，特别是当某个领域的发现或建议可能影响到其他领域时（例如，安全加固措施可能引发成本变动）。
        3.  最终，由 report_generator 专家，根据其他三位专家提供的明确分析结果，整合并生成一份结构清晰、重点突出的《架构评审综合报告》。

        请各位专家开始你们的评估工作。
    """

    try:
        async with asyncio.timeout(600.0):
            await Console(team.run_stream(task=task))
    except asyncio.TimeoutError:
        logger.error("Task execution timed out")

if __name__ == "__main__":
    asyncio.run(main())

