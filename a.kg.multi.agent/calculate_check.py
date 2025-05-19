import asyncio
import os
import logging
from typing import Sequence
from autogen_agentchat.messages import BaseAgentEvent, BaseChatMessage
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.conditions import TextMentionTermination
from autogen_agentchat.ui import Console



# Logging config
# 获取当前 Python 文件名（不带路径和扩展名）
file_name = os.path.splitext(os.path.basename(__file__))[0]
log_file = f'{file_name}.log'
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(log_file)
    ]
)
logger = logging.getLogger(__name__)


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

    agent1 = AssistantAgent(
        "Agent1",
        model_client,
        description="A faulty calculator that gives wrong answers twice before correcting on the third attempt.",
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

    
    def selector_func(messages: Sequence[BaseAgentEvent | BaseChatMessage]) -> str | None:
        if len(messages) == 1 or messages[-1].to_text() == "Incorrect!":
            return "Agent1"
        if messages[-1].source == "Agent1":
            return "Agent2"
        return None

    termination = TextMentionTermination("Correct!")
    team = SelectorGroupChat(
        [agent1, agent2],
        model_client=model_client,
        selector_func=selector_func,
        termination_condition=termination,
    )

    await Console(team.run_stream(task="What is 1 + 1?"))


asyncio.run(main())