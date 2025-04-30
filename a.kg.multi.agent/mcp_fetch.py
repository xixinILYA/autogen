import asyncio
import os
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_ext.tools.mcp import SseServerParams, mcp_server_tools
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.ui import Console
from autogen_core import CancellationToken


async def main() -> None:
    # 配置 MCP 服务的 SSE 连接参数
    local_server_params = SseServerParams(
        url="http://192.168.58.14:8400/sse",
        headers={"Content-Type": "application/json"},  # 根据服务要求调整
        timeout=10,
    )

    # 获取远程 MCP 服务提供的所有工具
    local_tools = await mcp_server_tools(local_server_params)

    server_params = SseServerParams(
        url="http://dev.apigateway.kgidc.cn/b-ai-mcpserver/v1/sse",
        headers={
            "Content-Type": "application/json",
            "opdAppid": "v1-6810a318b7195",
            "opdAppsecret": "4759a8425d265ed5209a709f6b39dd3b"
        },  # 根据服务要求调整
        timeout=10,
    )

    # 获取远程 MCP 服务提供的所有工具
    tools = await mcp_server_tools(server_params)

    # 创建一个 ChatCompletion 客户端（使用 OpenAI 的 GPT 模型）
    G_DEEPSEEK_KEY = os.environ.get('DPSK_KEY')
    model_client = OpenAIChatCompletionClient(model="deepseek-chat", base_url="https://api.deepseek.com",
                                           api_key=G_DEEPSEEK_KEY, model_info={
        "vision": False,
        "function_calling": True,
        "structured_output": True,
        "json_output": True,
        "family": "unknown",
    }, )

    # 创建 Agent 并注册工具
    agent1 = AssistantAgent(
        name="mcp_agent1",
        model_client=model_client,
        tools=local_tools+tools,
        system_message="你是一个能使用 MCP 工具的智能助手。",
    )

    # 执行任务，让 Agent 使用远程工具
    await Console(
        agent1.run_stream(
            task="计算 44 + 43 的和是多少",
            cancellation_token=CancellationToken()
        )
    )

if __name__ == "__main__":
    asyncio.run(main())


# import asyncio
# import os
# from autogen_ext.models.openai import OpenAIChatCompletionClient
# from autogen_ext.tools.mcp import SseServerParams, mcp_server_tools
# from autogen_agentchat.agents import AssistantAgent
# from autogen_agentchat.teams import SelectorGroupChat
# from autogen_agentchat.ui import Console
# from autogen_core import CancellationToken


# async def main():
#     # MCP 服务连接参数
#     local_params = SseServerParams(url="http://192.168.58.14:8400/sse", headers={"Content-Type": "application/json"}, timeout=10)
#     remote_params = SseServerParams(url="http://dev.apigateway.kgidc.cn/b-ai-mcpserver/v1/sse", headers={
#         "Content-Type": "application/json",
#         "opdAppid": "v1-6810a318b7195",
#         "opdAppsecret": "4759a8425d265ed5209a709f6b39dd3b"
#     }, timeout=10)

#     # 获取 MCP 工具列表
#     local_tools = await mcp_server_tools(local_params)
#     remote_tools = await mcp_server_tools(remote_params)

#     # OpenAI ChatCompletion 客户端
#     G_DEEPSEEK_KEY = os.environ.get('DPSK_KEY')
#     model_client = OpenAIChatCompletionClient(
#         model="deepseek-chat",
#         base_url="https://api.deepseek.com",
#         api_key=G_DEEPSEEK_KEY,
#         model_info={
#             "vision": False,
#             "function_calling": True,
#             "structured_output": True,
#             "json_output": True,
#             "family": "unknown",
#         },
#     )

#     # 两个不同工具源的 Agent
#     agent_local = AssistantAgent(name="local_mcp_agent", model_client=model_client, tools=local_tools,
#                                  system_message="你连接的是本地 MCP 工具服务。")
#     agent_remote = AssistantAgent(name="remote_mcp_agent", model_client=model_client, tools=remote_tools,
#                                   system_message="你连接的是远程 MCP 工具服务。")

#     # 发起任务：列出 MCP 所有可用工具
#     team = SelectorGroupChat(
#         [agent_local, agent_remote],
#         model_client=model_client
#     )

#     await team.run(task="列出所有的 MCP 工具列表")


# asyncio.run(main())

