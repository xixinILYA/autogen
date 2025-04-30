import asyncio
import os
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.ui import Console

async def main():
    # 初始化模型客户端（需替换为您的 API 密钥或配置）
    G_DEEPSEEK_KEY = os.environ.get('DPSK_KEY')
    model_client = OpenAIChatCompletionClient(model="deepseek-chat", base_url="https://api.deepseek.com",
                                           api_key=G_DEEPSEEK_KEY, model_info={
        "vision": False,
        "function_calling": True,
        "structured_output": True,
        "json_output": True,
        "family": "unknown",
    }, )

    # 定义智能体的工具函数
    async def lookup_hotel(location: str) -> str:
        return f"{location} 的酒店推荐：上海外滩华尔道夫酒店、浦东丽思卡尔顿酒店、四季酒店。"

    async def lookup_flight(origin: str, destination: str) -> str:
        return f"从 {origin} 到 {destination} 的航班：东方航空、南方航空、春秋航空。"

    async def book_trip() -> str:
        return "您的行程已成功预订！"

    # 创建智能体，分配角色和工具
    travel_advisor = AssistantAgent(
        name="travel_advisor",
        model_client=model_client,
        tools=[book_trip],
        description="协助用户规划旅行。",
        system_message="您是旅行顾问，负责协调其他智能体并帮助规划旅行。"
    )
    hotel_agent = AssistantAgent(
        name="hotel_booking_agent",
        model_client=model_client,
        tools=[lookup_hotel],
        description="专注于查找和预订酒店。",
        system_message="您是酒店预订智能体，根据请求提供酒店推荐。"
    )
    flight_agent = AssistantAgent(
        name="flight_booking_agent",
        model_client=model_client,
        tools=[lookup_flight],
        description="专注于查找和预订航班。",
        system_message="您是航班预订智能体，根据请求提供航班推荐。"
    )

    # 定义终止条件
    termination = TextMentionTermination("TERMINATE")

    # 创建 SelectorGroupChat 团队
    team = SelectorGroupChat(
        participants=[travel_advisor, hotel_agent, flight_agent],
        model_client=model_client,
        termination_condition=termination,
        max_turns=10,  # 限制最大轮次为 10
        allow_repeated_speaker=False  # 禁止连续选择同一发言者
    )

    # 执行任务
    task = "规划一次为期 3 天的上海旅行，包括航班和酒店。"
    await Console(team.run_stream(task=task))

# 运行异步主函数
if __name__ == "__main__":
    asyncio.run(main())
