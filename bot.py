import os
import discord
import logging
from datetime import datetime
import pytz  # You might need to install this: pip install pytz

from discord.ext import commands, tasks
from discord.ui import Button, View, Select
from dotenv import load_dotenv
from agent import ProbeAgent, AnswerAgent
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

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

# List to store previously asked questions
previous_questions = []

# Function to check for similar questions
# Function to check for similar questions
def find_similar_questions(new_question, threshold=0.7):
    logger.info("Finding similar questions for: %s", new_question)
    
    # Combine the new question with previous questions
    all_questions = previous_questions + [new_question]
    
    print(previous_questions)

    
    # Create a TF-IDF Vectorizer
    vectorizer = TfidfVectorizer().fit_transform(all_questions)
    vectors = vectorizer.toarray()
    
    # Calculate cosine similarity
    cosine_sim = cosine_similarity(vectors)
    
    # Get the similarity scores for the new question
    similar_indices = cosine_sim[-1][:-1]  # Exclude the last entry (the new question itself)
    
    # Find questions that exceed the threshold
    similar_questions = [
        previous_questions[i] for i in range(len(similar_indices)) 
        if similar_indices[i] > threshold
    ]
    
    logger.info("Similar questions found: %s", similar_questions)
    return similar_questions


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
        # Check for similar questions
        similar_questions = find_similar_questions(question.content)
        
        if similar_questions:
            # Present the user with similar questions
            await question.reply(f"Here are some similar questions you might find helpful:\n" + "\n".join(similar_questions))
        else:
            # Send the response to the Q&A channel as a new thread
            forum_channel = bot.get_channel(response_channel_id)
            if forum_channel and isinstance(forum_channel, discord.ForumChannel):
                # Create a thread title from the first 100 characters of the original message
                thread_title = (question.content[:97] + "...") if len(question.content) > 100 else question.content
                
                # Create a new thread in the forum
                thread = await forum_channel.create_thread(
                    name=thread_title,
                    content=f"**Posted by {question.author.mention}**"
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

    # Check channel types
    if not isinstance(forum_channel, discord.ForumChannel):
        logger.error("The forum channel is not a forum channel.")
        return
    if not isinstance(rankings_channel, discord.TextChannel):
        logger.error("The rankings channel is not a text channel.")
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
                # Initialize original_poster_name
                original_poster_citation = None
                
                # Get the starter message
                logger.info(f"Has starter_message attribute: {hasattr(thread, 'starter_message')}")

                # if hasattr(thread, 'starter_message') and thread.starter_message:
                #     first_message = thread.starter_message
                    
                #     original_poster_citation = first_message.content if first_message else None
                #     logger.info(f"First message content: {original_poster_citation}")
                # else:
                #     async for message in thread.history(limit=1, oldest_first=True):
                #         first_message = message
                #         break
                messages = await thread.history(limit=1).flatten()
                first_message = messages[0]
                
                reaction_count = sum(reaction.count for reaction in first_message.reactions) if first_message.reactions else 0
                thread_reactions.append((thread, reaction_count, original_poster_citation))
                logger.info(f"Thread '{thread.name}' by {original_poster_citation if original_poster_citation else 'Unknown'} has {reaction_count} reactions")
            except Exception as thread_error:
                logger.error(f"Error processing thread '{thread.name}': {thread_error}")

        if not thread_reactions:
            logger.warning("No threads with reactions found")
            return

        # Sort threads by reaction count
        sorted_threads = sorted(thread_reactions, key=lambda x: x[1], reverse=True)
        
        # Create rankings message
        rankings = "# 🏆 Most Popular Questions\n\n"
        for i, (thread, reaction_count, original_poster_citation) in enumerate(sorted_threads[:10], 1):
            author_text = original_poster_citation if original_poster_citation else "by Unkown"
            rankings += f"{i}. [{thread.name}](<{thread.jump_url}>) - {reaction_count} 👍 {author_text}\n"
            logger.info(f"Added ranking: {thread.name} with {reaction_count} reactions by {original_poster_citation if original_poster_citation else 'by Unknown'}")
        
        # Convert UTC to Pacific time
        utc_time = discord.utils.utcnow()
        pacific_tz = pytz.timezone('America/Los_Angeles')
        pacific_time = utc_time.astimezone(pacific_tz)
        current_time = pacific_time.strftime("%Y-%m-%d %I:%M:%S %p PST")
        
        rankings += f"\n*Rankings last updated: {current_time}*"
        rankings += "\n*Updates every 2 minutes*"

        # Update or create rankings message
        existing_message = None
        async for message in rankings_channel.history(limit=10):
            if message.author == bot.user and "Most Popular Questions" in message.content:
                existing_message = message
                break

        if existing_message:
            await existing_message.edit(content=rankings)
            logger.info(f"Updated rankings message at {current_time}")
        else:
            await rankings_channel.send(rankings)
            logger.info(f"Created new rankings message at {current_time}")
                
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

@bot.command(name="startsort", help="Starts sorting forum posts by reactions")
async def start_sorting(ctx):
    try:
        if sort_forum_by_reactions.is_running():
            await ctx.send("Sorting is already running!")
        else:
            sort_forum_by_reactions.start()
            await ctx.send("Started sorting forum posts by reactions. Updates every 2 minutes.")
            logger.info("Forum sorting started by user command")
    except Exception as e:
        error_message = f"Error starting sort: {str(e)}"
        logger.error(error_message)
        await ctx.send(error_message)

@bot.command(name="stopsort", help="Stops sorting forum posts by reactions")
async def stop_sorting(ctx):
    try:
        if sort_forum_by_reactions.is_running():
            sort_forum_by_reactions.cancel()
            await ctx.send("Stopped sorting forum posts.")
            logger.info("Forum sorting stopped by user command")
        else:
            await ctx.send("Sorting was not running!")
    except Exception as e:
        error_message = f"Error stopping sort: {str(e)}"
        logger.error(error_message)
        await ctx.send(error_message)

# Start the bot, connecting it to the gateway
bot.run(token)
