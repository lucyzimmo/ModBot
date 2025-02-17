import os
from mistralai import Mistral
import discord


MISTRAL_MODEL = "mistral-large-latest"

# TODO - Tweak
SYSTEM_PROMPT_PROBE = "You are an honest assistant. Respond using only the phrases 'Yes' or 'No'. Do you know the answer the following question?"
SYSTEM_PROMPT_ANSWER = "You are a helpful research assistant giving a brief answer that is factually correct."
SYSTEM_PROMPT_PROBE_AND_ANSWER = "You are a helpful and honest research assistant who gives a brief answer that is factually correct when possible and simply responds 'No' otherwise. You are an honest assistant. Respond using only the phrases 'Yes' or 'No'. Do you know the answer the following question?"

class ProbeAgent:
    def __init__(self):
        MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
        self.client = Mistral(api_key=MISTRAL_API_KEY)

    async def run(self, message: discord.Message):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_PROBE},
            {"role": "user", "content": message.content},
        ]

        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )

        return response.choices[0].message.content


class AnswerAgent:
    def __init__(self):
        MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
        self.client = Mistral(api_key=MISTRAL_API_KEY)

    async def run(self, message: discord.Message):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_ANSWER},
            {"role": "user", "content": message.content},
        ]

        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )

        return response.choices[0].message.content


class ProbeAndAnswerAgent:
    def __init__(self):
        MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
        self.client = Mistral(api_key=MISTRAL_API_KEY)

    async def run(self, message: discord.Message):
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT_ANSWER},
            {"role": "user", "content": message.content},
        ]

        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )

        return response.choices[0].message.content