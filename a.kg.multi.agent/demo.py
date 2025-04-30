import asyncio
import os
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.ui import Console

G_DEEPSEEK_KEY = os.environ.get('DPSK_KEY')

async def main():
    # 初始化模型客户端（需替换为您的 API 密钥或配置）
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
        description="你是一位经验丰富、条理清晰的项目经理，擅长组织多方专家进行系统性评审。"
        "你的职责是协调各个领域专家的工作，整合他们的专业意见，形成结构严谨、内容详实的综合评审报告。"
        "你了解项目架构评审的重要性，能够确保评审报告全面、准确且具备可操作性。",
        system_message="负责协调成本评审员、效率评审员、稳定性评审员、安全评审员四位专家的评审工作，"
        "收集他们各自的评审结果，分析并综合这些结果，最终形成一份完整的项目架构评审报告。"
        "报告需包含：1) 成本分析；2) 效率分析；3) 稳定性分析；4) 安全性分析；"
        "并在每一部分给出总结性意见和改进建议。"
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
    flight_agent = AssistantAgent(
        name="association_query_assistant",
        model_client=model_client,
        tools=[lookup_flight],
        description="专注于根据已有信息，通过工具查询关联信息",
        system_message="专注于根据已有信息，通过tools工具查询关联信息"
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
    task = "对企业某个资源做架构评审，资源可以是某个云主机CVM，可以是某个项目ID；首先需要根据项目ID找到关联的 K8S 或者 CVM，然后继续根据" \
    "该项目的关联信息，从 成本角度，稳定性角度，资源利用率角度，安全角度 评估该项目，最终输出一份综合评估建议报告"
    await Console(team.run_stream(task=task))

# 运行异步主函数
if __name__ == "__main__":
    asyncio.run(main())
