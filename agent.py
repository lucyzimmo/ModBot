import os
from mistralai import Mistral
import discord


MISTRAL_MODEL = "mistral-large-latest"

# TODO - Tweak
SYSTEM_PROMPT_PROBE = "You are an honest assistant. The question regards the speaker tag, not you. Respond using only the phrases 'Yes' or 'No'. Do you know the answer the following question?"
SYSTEM_PROMPT_ANSWER = "You are a helpful research assistant giving a brief answer that is factually correct about the speaker being asked about."
SYSTEM_PROMPT_PROBE_AND_ANSWER = """Answer 'No' if the question contains the word 'you' or 'your'. You are a helpful research assistant. The questions are about a speaker (the person being asked about), not about you.
If the question is asking for factual information about the speaker's work, research, or professional background, provide a brief factual answer.
If the question is personal (about opinions, feelings, challenges, or experiences) or if you're unsure about the answer, respond with 'No'.
Never answer as if the question is about yourself - the questions are always about the speaker."""

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
            {"role": "system", "content": SYSTEM_PROMPT_PROBE_AND_ANSWER},
            {"role": "user", "content": message.content},
        ]

        response = await self.client.chat.complete_async(
            model=MISTRAL_MODEL,
            messages=messages,
        )

        return response.choices[0].message.content