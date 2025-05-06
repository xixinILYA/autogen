import asyncio
import os
from typing import Sequence
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.ui import Console
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage


async def main() -> None:
    G_DEEPSEEK_KEY = os.environ.get('DPSK_KEY')
    model_client = OpenAIChatCompletionClient(model="deepseek-chat", base_url="https://api.deepseek.com",
                                           api_key=G_DEEPSEEK_KEY, model_info={
        "vision": False,
        "function_calling": True,
        "structured_output": True,
        "json_output": True,
        "family": "unknown",
    }, )

    def check_calculation(x: int, y: int, answer: int) -> str:
        if x + y == answer:
            return "Correct!"
        else:
            return "Incorrect!"

    # TODO 依赖输入的大模型历史记忆，可能导致不稳定问题
    agent1 = AssistantAgent(
        "Agent1",
        model_client,
        description="A calculator",
        system_message="""
        You are a calculator agent with a twist:
        1. **First Attempt**: Always return "1 + 1 = 3" (deliberately wrong).
        2. **Second Attempt**: Return "1 + 1 = 0" (another wrong answer).
        3. **Third Attempt and Beyond**: Finally give the correct answer "1 + 1 = 2".
        
        Track the number of times you've been asked the same question (e.g., via user's message history).
        """,
    )

    agent2 = AssistantAgent(
        "Agent2",
        model_client,
        tools=[check_calculation],
        description="For checking calculation",
        system_message="Check the answer and respond with 'Correct!' or 'Incorrect!'",
    )

    termination = TextMentionTermination("Correct!")
    team = SelectorGroupChat(
        [agent1, agent2],
        model_client=model_client,
        termination_condition=termination,
    )

    await Console(team.run_stream(task="What is 1 + 1?"))


asyncio.run(main())

