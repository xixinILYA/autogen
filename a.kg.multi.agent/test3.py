import asyncio
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_agentchat.ui import Console
from autogen_ext.models.openai import OpenAIChatCompletionClient
import os, sys
import logging


# # 配置日志
# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.StreamHandler(),  # 输出到控制台
#         logging.FileHandler('multi_agent_mcp.log')  # 输出到文件
#     ]
# )
# logger = logging.getLogger(__name__)


# 创建 ChatCompletion 客户端
G_DEEPSEEK_KEY = os.environ.get('DPSK_KEY')
if not G_DEEPSEEK_KEY:
    # logger.error("DPSK_KEY environment variable not set")
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



async def main() -> None:
    # Create the writer agent
    writer = AssistantAgent(
        "writer",
        model_client=model_client,
        system_message="Draft a short paragraph on climate change.",
    )

    # Create two editor agents
    editor1 = AssistantAgent(
        "editor1", model_client=model_client, system_message="Edit the paragraph for grammar."
    )

    editor2 = AssistantAgent(
        "editor2", model_client=model_client, system_message="Edit the paragraph for style."
    )

    # Create the final reviewer agent
    final_reviewer = AssistantAgent(
        "final_reviewer",
        model_client=model_client,
        system_message="Consolidate the grammar and style edits into a final version.",
    )

    # Build the workflow graph
    builder = DiGraphBuilder()
    builder.add_node(writer).add_node(editor1).add_node(editor2).add_node(
        final_reviewer
    )

    # Fan-out from writer to editor1 and editor2
    builder.add_edge(writer, editor1)
    builder.add_edge(writer, editor2)

    # Fan-in both editors into final reviewer
    builder.add_edge(editor1, final_reviewer)
    builder.add_edge(editor2, final_reviewer)

    # Build and validate the graph
    graph = builder.build()

    # Create the flow
    flow = GraphFlow(
        participants=builder.get_participants(),
        graph=graph,
    )

    # Run the workflow
    await Console(flow.run_stream(task="Write a short biography of Steve Jobs."))

asyncio.run(main())
