import os
import discord
import logging

from discord.ext import commands, tasks
from discord.ui import Button, View, Select
from dotenv import load_dotenv
from agent import ProbeAgent, AnswerAgent

PREFIX = "!"

# Setup logging
logger = logging.getLogger("discord")

# Load the environment variables
load_dotenv()

# Create the bot with all intents
# The message content and members intent must be enabled in the Discord Developer Portal for the bot to work.
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Import the agents from the agent.py file
probe_agent = ProbeAgent()
answer_agent = AnswerAgent()


# Get the token from the environment variables
token = os.getenv("DISCORD_TOKEN")
response_channel_id = 1337581994648932363

@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    Prints message on terminal when bot successfully connects to discord.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_ready
    """
    logger.info(f"{bot.user} has connected to Discord!")


@bot.event
async def on_message(question: discord.Message):
    """
    Called when a message is sent in any channel the bot can see.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_message
    """
    # Don't delete this line! It's necessary for the bot to process commands.
    await bot.process_commands(question)

    # Ignore messages from self or other bots to prevent infinite loops.
    if question.author.bot or question.content.startswith("!"):
        return

    # Process the message with the agent you wrote
    # Open up the agent.py file to customize the agent
    logger.info(f"Processing message from {question.author}: {question.content}")

    async def post_question():
        # TODO - Check if questions has already been asked
        newQuestion = True

        # TODO - Conditional logic to determine fate of question
        if not newQuestion:
            # TODO - Conditional logic - like or group?
            pass
        if newQuestion:
            # Send the response to the Q&A channel as a new thread
            forum_channel = bot.get_channel(response_channel_id)
            if forum_channel and isinstance(forum_channel, discord.ForumChannel):
                # Create a thread title from the first 100 characters of the original message
                thread_title = (question.content[:97] + "...") if len(question.content) > 100 else question.content
                
                # Create a new thread in the forum
                thread = await forum_channel.create_thread(
                    name=thread_title,
                    content=f"**Original message from {question.author.mention} in <#{question.channel.id}>:**\n{question.content}"
                )
                await question.reply("Question posted!")
            else:
                logger.error(f"Could not find forum channel with ID {response_channel_id}")
                await question.reply("Error: Could not find forum channel")




    # TODO - Check if question is answerable by Mistral on internet
    probe_response = await probe_agent.run(question)
    if probe_response.lower() == "yes":
        # answer_response = await answer_agent.run(question)
        # answer_response = f"Here's what I found online: {answer_response}"
        # await question.reply(answer_response)  # Send the response back to the DMs
         # Create a view with buttons
        view = View()
        yes_button = Button(label="Yes, search online", style=discord.ButtonStyle.green, custom_id="search_yes")
        no_button = Button(label="No thanks", style=discord.ButtonStyle.red, custom_id="search_no")
        
        async def yes_callback(interaction):
            await interaction.response.defer()  # Acknowledge the interaction
            answer_response = await answer_agent.run(question)
            answer_response = f"Here's what I found online: {answer_response}"
            await question.reply(answer_response)
            
        async def no_callback(interaction):
            await interaction.response.send_message("Okay, I won't search online.", ephemeral=True)
            await post_question()
            
        yes_button.callback = yes_callback
        no_button.callback = no_callback
        view.add_item(yes_button)
        view.add_item(no_button)
        
        # Send message with buttons
        await question.reply("I might be able to help with this. Would you like me to search online?", view=view)
    else:
        await post_question()




# Tasks

""" # TODO - Get this working
@tasks.loop(minutes=0.5)
async def sort_forum_by_reactions():
    # Get the forum channel by ID
    forum_channel = bot.get_channel(response_channel_id)

    # Ensure we are working with a Forum Channel
    if isinstance(forum_channel, discord.ForumChannel):
        print("in is instance, should be sorting")
        # Fetch all the messages from the forum channel (this may take some time for large forums)
        all_messages = []
        async for message in forum_channel.history(limit=None):  # Fetch all messages, no limit
            all_messages.append(message)

        # Create a list of tuples (message, number of reactions)
        message_reactions = []

        for message in all_messages:
            # Count the number of reactions on the message
            num_reactions = sum([reaction.count for reaction in message.reactions])
            message_reactions.append((message, num_reactions))

        # Sort messages by the number of reactions (highest first)
        sorted_messages = sorted(message_reactions, key=lambda x: x[1], reverse=True)

        # Send the top 10 messages with the most reactions (adjust the number as needed)
        response = "Here are the top 10 messages sorted by reactions:\n"
        for i, (message, reactions) in enumerate(sorted_messages[:10], start=1):
            response += f"{i}. {message.content} (Reactions: {reactions})\n"

        # Send the sorted messages to the forum channel or a designated channel
        await forum_channel.send(response)
    else:
        print("The channel is not a forum channel.")
"""


# Commands


# This example command is here to show you how to add commands to the bot.
# Run !ping with any number of arguments to see the command in action.
# Feel free to delete this if your project will not need commands.
@bot.command(name="ping", help="Pings the bot.")
async def ping(ctx, *, arg=None):
    if arg is None:
        await ctx.send("Pong!")
    else:
        await ctx.send(f"Pong! Your argument was {arg}")


# Start the bot, connecting it to the gateway
bot.run(token)
