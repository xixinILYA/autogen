import asyncio
import os
import sys
import logging
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
# 生产
else:
    g_dify_workflow_host = "dify.kgidc.cn"
    g_aiops_api_host = "opdproxy.kgidc.cn"
    

# 大模型 LLM 使用deepseek
G_DEEPSEEK_KEY = os.environ.get('DPSK_KEY')
if not G_DEEPSEEK_KEY:
    logger.error("DPSK_KEY environment variable not set")
    sys.exit(1)

model_client = OpenAIChatCompletionClient(
    model="deepseek-chat",
    base_url="https://api.deepseek.com",
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
    description="根据主机资源使用，主机硬件配置情况，生成成本优化建议（适用于成本分析）",
    scheme="http",
    host=g_dify_workflow_host,
    port=80,
    path="/v1/workflows/run",
    method="POST",
    json_schema={
        "type": "object",
        "properties": {
            "cpu_precent": {"type": "number", "description": "CPU使用率"},
            "mem_precent": {"type": "number", "description": "内存使用率"},
            "cpu": {"type": "number", "description": "CPU硬件配置"},
            "mem": {"type": "number", "description": "内存硬件配置"},
            "machine_type": {"type": "string", "description": "机器类型"},
            "machine_class": {"type": "string", "description": "机器规格"}
        },
        "required": ["cpu", "mem", "cpu_precent", "mem_precent", "machine_type", "machine_class"]
    },
    headers={
        'Authorization': 'Bearer app-0E73Ys4ywhawXOM7LmiGgVqa',
        'Content-Type': 'application/json'
    },
    return_type="json",
)

# 稳定性相关的 http 工具
get_stability_info = HttpTool(
    name="get_stability_info",
    description="根据 IP 地址查询主机的稳定性信息，如负载波动、故障率等",
    scheme="http",
    host="192.168.58.14",
    port=8001,
    path="/api/stability/{ip}",
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
        tools=mcp_cost_tools + [get_host_info, get_cost_advice],
        description="分析项目成本并给出优化建议，能够获取项目资源信息、调用成本建议服务",
        system_message="""
            你是负责分析项目资源成本的专家。
            你的职责是：
            - 调用 get_host_info 等工具获取项目相关的 Redis、K8S、Mysql、主机CVM 等资源、硬件配置相关的数据；
            - 分析成本使用情况，调用 get_cost_advice工具 获取优化建议；
            - 仅使用工具返回的数据作为依据，清晰地陈述你的分析过程、数据来源和最终的优化建议。

            注意：
            - 你的回答应专注于“成本分析”这一维度；
            - **请勿整合其他专家的结论试图生成最终的《架构评审综合报告》**；
            - 最终《架构评审综合报告》将由 report_generator 专家整理，请勿重复或越权执行该任务。
        """
        )

    stability_agent = AssistantAgent(
        name="stability_analyst",
        model_client=model_client,
        tools=mcp_stability_tools + [get_stability_info],
        description="评估项目稳定性并给出处置建议",
        system_message="""
            你是负责评估系统稳定性的专家。
            你的职责是：
            - 调用 get_stability_info 等工具获取项目相关的 日志、告警、故障记录等；
            - 分析日志、告警、故障记录等评估系统是否存在不稳定风险；
            - 清晰地陈述你的分析过程、数据来源和最终的优化建议。

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
            你是负责评估系统安全性的专家。
            你的职责是：
            - 调用 get_security_info 等工具获取项目相关的配置文件、访问权限和漏洞等安全信息；
            - 分析配置文件、访问权限和漏洞等安全信息并给出风险提示和加固建议；

            注意：
            - 你的职责仅限于“安全性分析”；
            - **请勿整合其他专家的结论试图生成最终的《架构评审综合报告》**；
            - 最终《架构评审综合报告》将由 report_generator 专家整理，请勿重复或越权执行该任务。
        """
    )

    report_generator = AssistantAgent(
        name="report_generator",
        model_client=model_client,
        description="整理所有专家的结论及建议，生成结构化报告",
        system_message="""
            你是一个项目评估报告专家。
            你的职责是：
            - 整理来自成本分析、安全评估和稳定性分析专家的内容；
            - 如果部分专家声明无法完成任务，你需要将此作为“信息缺失风险”写入报告；
            - 不参与分析，仅组织他们的结论；
            - 报告包括：分析摘要、风险项、建议、结论（Markdown格式）。
            - 最后一行以 'MISSION COMPLETE' 结尾。
        """
        )

    termination = TextMentionTermination("MISSION COMPLETE")
    team = SelectorGroupChat(
        participants=[cost_agent, stability_agent, security_agent, report_generator],
        model_client=model_client,
        termination_condition=termination,
        allow_repeated_speaker=True,
        max_turns=15,
        # selector_prompt = """
        #     你正在参与一个软件架构评审任务，团队由多个专家角色组成，每个角色有其明确的职责。

        #     【角色职责】：
        #     {roles}

        #     【任务目标】：
        #     从成本、稳定性、安全性等多个维度完成分析，最终由报告生成专家（report_generator）汇总形成最终报告。

        #     【发言规则（按优先级排序）】：
        #     1. 如果有角色尚未发言，优先选择这些角色继续分析；
        #     2. 如果当前角色指定征求某个角色的意见，则选择被征求意见的角色发言；
        #     3. 如果某个角色声明'无法完成任务'或者'没其他意见'时，则不再选择该角色；
        #     4. 选择最能有效推动话题深入的角色发言，但要避免重复发言或空转；
        #     5. 仅当所有分析角色（cost_analyst / stability_analyst / security_analyst）都已完成任务（至少发言一次），且内容没有冲突时，才可选择 report_generator 开始汇总；
            

        #     【当前对话历史】：
        #     {history}

        #     请根据【当前对话历史】以及【发言规则（按优先级排序）】，从参与者列表 {participants} 中选择下一个发言角色。
        #     只返回该角色名，不要输出其他内容。"""


        # selector_prompt = """
        # 你是一个智能调度器，负责引导一个软件架构评审多专家团队完成高效讨论并生成最终报告。

        # 【角色说明】
        # {roles}

        # 【任务目标】
        # 围绕“成本、稳定性、安全性”三个维度分析软件架构，最终由 report_generator 整合各专家意见生成完整报告。

        # 【发言选择规则（按优先级）】
        # 1. 有分析专家尚未发言 → 优先从中选择，按顺序 cost → stability → security；
        # 2. 若上一发言者明确 @某角色 → 优先选择该角色；
        # 3. 若角色声明“已完成”或“无其他意见” → 当前阶段不再选择；
        # 4. 若某分析维度未覆盖或存争议 → 选择能补充或澄清的专家；
        # 5. 禁止重复选择刚发言的角色，除非被请求或需澄清；
        # 6. 仅在所有分析专家都已发言并确认完成分析、无冲突时 → 才选择 report_generator 汇总；
        # 7. 若存在冲突（如成本与安全互斥） → 优先选择相关分析专家继续沟通，不得调用 report_generator。

        # 【对话历史】
        # {history}

        # 【参与者列表】
        # {participants}

        # 请只返回下一个发言角色名称（如：cost_agent），不包含其他内容。
        # """

        selector_prompt = """
            你是一个智能调度器，负责在一个软件架构评审的多专家团队中选择下一个发言者。你的目标是高效地引导讨论，确保所有维度都被充分覆盖，并最终生成一份综合报告。

            【团队角色及其专长】：
            {roles}

            【核心任务目标】：
            对提供的软件架构进行全面的多维度（成本、稳定性、安全性）分析。最终，report_generator 将汇总所有专家的分析意见，形成一份结构清晰、内容详实的评审报告。

            【发言选择规则 (严格按以下优先级顺序执行)】：
            1.  **新贡献者优先**: 如果参与者列表中有分析专家（非 report_generator）尚未发言，从中选择一位。如果多位未发言，优先选择其专业领域与当前讨论焦点最相关的角色，或者按照 [cost_agent, stability_agent, security_agent] 的顺序选择。
            2.  **响应直接请求**: 如果上一位发言者明确指名要求特定角色 (例如 "@security_agent, 请你分析一下...") 发言，则选择被指名的角色。
            3.  **避免无效参与**: 如果某个角色明确表示“任务已完成”、“没有其他意见”、“无法提供更多输入”或类似表述，则在当前分析阶段不再选择该角色，除非有新的信息或请求直接指向他们。
            4.  **推动任务进展**:
                * 如果某个分析维度（成本、稳定性、安全性）尚未被充分讨论或存在明显遗漏，选择最能补充该维度的专家。
                * 如果一个角色的发言引入了新的问题或需要其他专家确认/反驳，选择最相关的专家进行回应。
                * 避免选择刚刚发言过的角色，除非他们是直接被请求或需要澄清关键点。目标是促进对话流动，避免讨论停滞或在同一主题上低效循环。
            5.  **报告生成阶段**:
                * **前提条件**: 必须在所有分析专家 (cost_agent, stability_agent, security_agent) 都已至少发言一次，并且他们明确表示对其负责的维度已完成初步分析，或者对话历史显示其核心观点已表达清楚之后，才能选择 report_generator。
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
    task = """
        你们是一个虚拟专家团队，当前任务是对一个软件开发项目进行联合评估。
        【项目关键信息】：该项目的一个核心组件的IP地址是 10.16.6.152。请将此IP作为你们分析的起点和核心关注点。

        【团队角色与核心贡献领域】：
        - 成本分析专家 (cost_analyst): 负责从成本效益角度评估项目，并提供资源和预算相关的分析。
        - 稳定性专家 (stability_analyst): 负责从系统运行的稳定性和可靠性角度评估项目。
        - 安全性专家 (security_analyst): 负责从系统安全配置、潜在风险和漏洞角度评估项目。
        - 报告生成专家 (report_generator): 负责整合所有专家的核心分析意见和关键建议，形成最终的综合评估报告。

        【团队协作指南与最终目标】：
        1.  请各位分析专家（cost_analyst, stability_analyst, security_analyst）围绕项目IP 10.16.6.152，从各自的专业领域出发，进行分析，识别潜在问题或风险，并提出具体的改进建议。
        2.  鼓励你们在评估过程中进行必要的互动，特别是当某个领域的发现或建议可能影响到其他领域时（例如，安全加固措施可能引发成本变动）。
        3.  最终，由 report_generator 专家，根据其他三位专家提供的明确分析结果和核心建议，整合并生成一份结构清晰、重点突出的《架构评审综合报告》。

        请各位专家开始你们的评估工作。
    """

    try:
        async with asyncio.timeout(300.0):
            await Console(team.run_stream(task=task))
    except asyncio.TimeoutError:
        logger.error("Task execution timed out")

if __name__ == "__main__":
    asyncio.run(main())

