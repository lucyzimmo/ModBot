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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

# Load the environment variables
load_dotenv()
token = os.getenv('DISCORD_TOKEN')

if token is None:
    logger.error("No token found! Make sure DISCORD_TOKEN is set in your .env file")
    exit(1)

# Create the bot with all intents
# The message content and members intent must be enabled in the Discord Developer Portal for the bot to work.
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=PREFIX, intents=intents)

# Import the agents from the agent.py file
probe_agent = ProbeAgent()
answer_agent = AnswerAgent()

# At the top with other constants
response_channel_id = 1337581994648932363
rankings_channel_id = 1337904418603008051  

@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    Prints message on terminal when bot successfully connects to discord.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_ready
    """
    logger.info(f"{bot.user} has connected to Discord!")
    sort_forum_by_reactions.start()  # Start the sorting task


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

@tasks.loop(minutes=2)
async def sort_forum_by_reactions():
    logger.info("Starting forum sort task...")
    forum_channel = bot.get_channel(response_channel_id)
    rankings_channel = bot.get_channel(rankings_channel_id)

    if not isinstance(forum_channel, discord.ForumChannel):
        logger.error("The channel is not a forum channel.")
        return

    try:
        # Get and fetch all threads (both active and archived)
        archived_threads = []
        async for thread in forum_channel.archived_threads():
            archived_threads.append(thread)
            
        active_threads = forum_channel.threads
        all_threads = list(active_threads) + archived_threads
        
        logger.info(f"Found {len(all_threads)} threads")
        thread_reactions = []

        # Process each thread
        for thread in all_threads:
            try:
                if hasattr(thread, 'starter_message') and thread.starter_message:
                    # Use the starter message if available
                    first_message = thread.starter_message
                else:
                    # Otherwise fetch the first message
                    async for message in thread.history(limit=1, oldest_first=True):
                        first_message = message
                        break
                
                reaction_count = sum(reaction.count for reaction in first_message.reactions) if first_message.reactions else 0
                thread_reactions.append((thread, reaction_count))
                logger.info(f"Thread '{thread.name}' (ID: {thread.id}) has {reaction_count} reactions")
            except Exception as thread_error:
                logger.error(f"Error processing thread '{thread.name}': {thread_error}")

        if not thread_reactions:
            logger.warning("No threads with reactions found")
            return

        # Sort threads by reaction count
        sorted_threads = sorted(thread_reactions, key=lambda x: x[1], reverse=True)
        
        # Create rankings message
        rankings = "# 🏆 Most Popular Questions\n\n"
        for i, (thread, reaction_count) in enumerate(sorted_threads[:10], 1):
            rankings += f"{i}. [{thread.name}](<{thread.jump_url}>) - {reaction_count} 👍\n"
        
        rankings += "\n*Rankings update every 2 minutes*"

        # Find existing rankings message
        existing_message = None
        async for message in rankings_channel.history(limit=10):
            if message.author == bot.user and "Most Popular Questions" in message.content:
                existing_message = message
                break

        # Update or create rankings message
        if existing_message:
            await existing_message.edit(content=rankings)
            logger.info("Updated rankings message")
        else:
            await rankings_channel.send(rankings)
            logger.info("Created new rankings message")
                
    except Exception as e:
        logger.error(f"Error in sort_forum_by_reactions: {e}")


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
