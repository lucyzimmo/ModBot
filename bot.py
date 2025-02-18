import os
import discord
import logging
from datetime import datetime
import pytz  # You might need to install this: pip install pytz

from discord.ext import commands, tasks
from discord.ui import Button, View, Select
from dotenv import load_dotenv
from agent import ProbeAndAnswerAgent
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
probe_and_answer_agent = ProbeAndAnswerAgent()

# At the top with other constants
response_channel_id = 1337581994648932363
rankings_channel_id = 1337904418603008051

# List to store previously asked questions
previous_questions = []

def find_similar_questions(new_question, threshold=0.7):
    if not previous_questions:  # If no previous questions, return empty list
        logger.info("No previous questions found")
        return []
    
    # Create TF-IDF vectors
    vectorizer = TfidfVectorizer()
    all_questions = previous_questions + [new_question]
    tfidf_matrix = vectorizer.fit_transform(all_questions)
    
    # Calculate similarity with the new question
    similarity_vector = cosine_similarity(tfidf_matrix[-1:], tfidf_matrix[:-1])[0]
    
    # Get similar questions above threshold
    similar = [(q, score) for q, score in zip(previous_questions, similarity_vector) if score > threshold]
    similar.sort(key=lambda x: x[1], reverse=True)
    
    return [q for q, _ in similar[:3]]  # Return top 3 similar questions

def format_first_message(author: discord.Member, content: str, answer_response: str = None) -> str:
    post_content = f"**by {author.mention}**"  # must be formatted this way alone for later parsing
    if len(content) > 100:
        post_content += f"\n\n**Full question:**\n{content}"
    if answer_response and answer_response.lower() != "no":
        post_content += f"\n\n**AI-Generated Answer:**\n{answer_response}"
    return post_content

async def post_question_flow(message: discord.Message, answer_response: str = None):
    async def post_question(tags: list[discord.Object] = None):
        forum_channel = bot.get_channel(response_channel_id)
        if forum_channel and isinstance(forum_channel, discord.ForumChannel):
            thread_title = (message.content[:97] + "...") if len(message.content) > 100 else message.content
            
            # Create initial post content
            post_content = format_first_message(message.author, message.content, answer_response)
            
            # Create the forum post with initial message
            thread = await forum_channel.create_thread(
                name=thread_title,
                content=post_content,
                applied_tags=tags
            )
            await message.reply("Question posted!")
            
            # Add to previous questions list
            previous_questions.append(message.content)
            logger.info("Updated previous questions: %s", previous_questions)
        else:
            logger.error(f"Could not find forum channel with ID {response_channel_id}")
            await message.reply("Error: Could not find forum channel")

    async def get_question_tags():
        forum_channel = bot.get_channel(response_channel_id)
        if not forum_channel or not isinstance(forum_channel, discord.ForumChannel):
            logger.error(f"Could not find forum channel with ID {response_channel_id}")
            return []

        available_tags = forum_channel.available_tags
        if not available_tags:
            logger.info(f"No tags found in forum channel with ID {response_channel_id}")
            return []  # Simply return empty list without showing tag selection UI

        view = View(timeout=300)  # 5 minute timeout
        select = Select(
            placeholder="Choose tags for your question...",
            min_values=0,
            max_values=min(len(available_tags), 5),
            options=[discord.SelectOption(label=tag.name, value=str(tag.id)) for tag in available_tags]
        )
        
        selected_tags = []
        
        async def select_callback(interaction):
            selected_tags.clear()
            selected_tags.extend([discord.Object(id=int(tag_id)) for tag_id in select.values])
            await interaction.response.send_message(
                f"Selected tags: {', '.join(tag.name for tag in available_tags if str(tag.id) in select.values)}",
                ephemeral=True
            )
        
        select.callback = select_callback
        view.add_item(select)
        
        done_button = Button(label="Done", style=discord.ButtonStyle.green)
        
        async def done_callback(interaction):
            view.stop()
            await interaction.response.defer()
        
        done_button.callback = done_callback
        view.add_item(done_button)
        
        await message.reply("Please select tags for your question:", view=view)
        await view.wait()
        
        return selected_tags

    # Get tags and post the question
    tags = await get_question_tags()
    await post_question(tags)

@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    Prints message on terminal when bot successfully connects to discord.
    """
    logger.info(f"{bot.user} has connected to Discord!")

    # Fetch the response channel
    response_channel = bot.get_channel(response_channel_id)
    
    if response_channel is None:
        logger.error(f"Could not find response channel with ID {response_channel_id}")
        return

    logger.info(f"Channel found: {response_channel.name} (ID: {response_channel.id}, Type: {type(response_channel)})")

    if isinstance(response_channel, discord.ForumChannel):
        logger.info(f"Fetching threads from forum channel: {response_channel.name}")
        
        # Fetch all active threads in the forum channel
        try:
            # Fetch active threads
            for thread in response_channel.threads:
                async for message in thread.history(limit=None):  # Fetch all messages in the thread
                    if not message.author.bot:  # Ignore messages from bots
                        previous_questions.append(message.content)  # Add the question to the list
                        logger.info("Added to previous questions: %s", message.content)  # Debugging line

            # Fetch archived threads
            async for thread in response_channel.archived_threads():  # Iterate over the async generator
                async for message in thread.history(limit=None):  # Fetch all messages in the thread
                    if not message.author.bot:  # Ignore messages from bots
                        previous_questions.append(message.content)  # Add the question to the list
                        logger.info("Added to previous questions: %s", message.content)  # Debugging line

        except Exception as e:
            logger.error(f"Error fetching messages from forum channel: {e}")
    else:
        logger.error(f"The channel with ID {response_channel_id} is not a forum channel. It is of type: {type(response_channel)}.")


@bot.event
async def on_message(message: discord.Message):
    """
    Called when a message is sent in any channel the bot can see.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_message
    """
    await bot.process_commands(message)

    # Ignore bot messages and commands
    if message.author.bot or message.content.startswith("!"):
        return

    logger.info("Received message from %s: %s", message.author, message.content)

    # Step 1: Check for similar questions first
    similar_questions = find_similar_questions(message.content)
    
    if similar_questions:
        view = View(timeout=300)
        continue_button = Button(label="Continue with my question", style=discord.ButtonStyle.primary)
        cancel_button = Button(label="Cancel", style=discord.ButtonStyle.secondary)
        
        async def continue_callback(interaction):
            await interaction.response.defer()
            # Step 2: If user continues, check if agent can answer
            answer_response = await probe_and_answer_agent.run(message)
            
            if answer_response.lower() != "no":
                # Step 3: If there's an answer, display it and ask if they want to post
                await message.reply(f"Here's what I found: {answer_response}")
                
                # Ask if they want to post the question
                post_view = View(timeout=300)
                post_button = Button(label="Yes, post the question", style=discord.ButtonStyle.green)
                dont_post_button = Button(label="No, don't post", style=discord.ButtonStyle.red)

                async def post_callback(interaction):
                    await interaction.response.defer()
                    await post_question_flow(message, answer_response)

                async def dont_post_callback(interaction):
                    await interaction.response.send_message("Okay, I won't post your question.", ephemeral=True)

                post_button.callback = post_callback
                dont_post_button.callback = dont_post_callback
                post_view.add_item(post_button)
                post_view.add_item(dont_post_button)

                await message.reply("Do you still want to post your question?", view=post_view)
            else:
                # If no answer, just proceed with posting
                await post_question_flow(message)
        
        async def cancel_callback(interaction):
            await interaction.response.send_message("Okay, I won't proceed with your question.", ephemeral=True)
        
        continue_button.callback = continue_callback
        cancel_button.callback = cancel_callback
        view.add_item(continue_button)
        view.add_item(cancel_button)
        
        # Show similar questions and ask if they want to continue
        similar_questions_text = "\n".join([f"• {q}" for q in similar_questions])
        await message.reply(
            f"I found some similar questions:\n{similar_questions_text}\n\nWould you like to continue with your question?",
            view=view
        )
    else:
        # If no similar questions, proceed to check if agent can answer
        answer_response = await probe_and_answer_agent.run(message)
        
        if answer_response.lower() != "no":
            # If there's an answer, display it and ask if they want to post
            await message.reply(f"Here's what I found: {answer_response}")
            
            # Ask if they want to post the question
            post_view = View(timeout=300)
            post_button = Button(label="Yes, post the question", style=discord.ButtonStyle.green)
            dont_post_button = Button(label="No, don't post", style=discord.ButtonStyle.red)

            async def post_callback(interaction):
                await interaction.response.defer()
                await post_question_flow(message, answer_response)

            async def dont_post_callback(interaction):
                await interaction.response.send_message("Okay, I won't post your question.", ephemeral=True)

            post_button.callback = post_callback
            dont_post_button.callback = dont_post_callback
            post_view.add_item(post_button)
            post_view.add_item(dont_post_button)

            await message.reply("Do you want to post your question?", view=post_view)
        else:
            # If no answer, just proceed with posting
            await post_question_flow(message)




# Tasks

@tasks.loop(minutes=1)
async def sort_forum_by_reactions(speaker_tag: str = None):
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
        
        logger.info(f"Found {len(all_threads)} total threads")

        # Filter threads by speaker tag if provided
        if speaker_tag:
            filtered_threads = []
            for thread in all_threads:
                # Check if thread has the specified speaker tag
                if any(tag.name == speaker_tag for tag in thread.applied_tags):
                    filtered_threads.append(thread)
            all_threads = filtered_threads
            logger.info(f"Found {len(all_threads)} threads for speaker tag: {speaker_tag}")
        
        thread_reactions = []

        

        # Process each thread
        for thread in all_threads:
            try:
                # Initialize original_poster mention
                original_poster = None
                
                # Get the first message (includes citation)
                if hasattr(thread, 'starter_message') and thread.starter_message:
                    first_message = thread.starter_message
                    
                    original_poster = first_message.content if first_message else None
                else:
                    logger.warning(f"Thread '{thread.name}' has no starter message")
                    async for message in thread.history(limit=1, oldest_first=True):
                        first_message = message
                        original_poster = first_message.content if first_message else None
                        break
                
                if original_poster:
                    try:
                        # Split by "**by" and make sure there's a second part
                        parts = original_poster.split("**by")
                        if len(parts) > 1:
                            # remove everything after **
                            parts[1] = parts[1].split("**")[0]
                            original_poster = parts[1].strip()
                        else:
                            original_poster = "Unknown"
                    except Exception as parse_error:
                        logger.error(f"Error parsing original poster: {parse_error}")
                        original_poster = "Unknown"

                logger.info(f"First message content: {first_message.content}")
                
                reaction_count = sum(reaction.count for reaction in first_message.reactions) if first_message.reactions else 0
                thread_reactions.append((thread, reaction_count, original_poster))
                logger.info(f"Thread '{thread.name}' by {original_poster if original_poster else 'Unknown'} has {reaction_count} reactions")
            except Exception as thread_error:
                logger.error(f"Error processing thread '{thread.name}': {thread_error}")

        if not thread_reactions:
            logger.warning("No threads with reactions found")
            return

        # Sort threads by reaction count
        sorted_threads = sorted(thread_reactions, key=lambda x: x[1], reverse=True)
        
        # Create rankings message
        rankings = "# 🏆 Most Popular Questions" + (f" for {speaker_tag}" if speaker_tag else " of all time") + "\n\n"
        for i, (thread, reaction_count, original_poster) in enumerate(sorted_threads[:10], 1):
            author_mention = original_poster if original_poster else "Unknown"
            rankings += f"{i}. [{thread.name}](<{thread.jump_url}>)\n"
            rankings += f"    👍 {reaction_count} reactions | by {author_mention}\n"  # NOTE: for some reason, discord isn't handling these newlines correctly
            logger.info(f"Added ranking: {thread.name} with {reaction_count} reactions by {original_poster if original_poster else 'Unknown'}")
        
        # Convert UTC to Pacific time
        utc_time = discord.utils.utcnow()
        pacific_tz = pytz.timezone('America/Los_Angeles')
        pacific_time = utc_time.astimezone(pacific_tz)
        current_time = pacific_time.strftime("%Y-%m-%d %I:%M:%S %p PST")
        
        rankings += f"\n*Rankings last updated: {current_time}*"
        rankings += "\n*Updates every 1 minute*"

        # Limit the rankings message to 2000 characters due to discord character limits
        if len(rankings) > 2000:
            rankings = rankings[:(2000-3)] + "..."

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

@bot.command(name="startsort", help="Starts sorting forum posts by reactions. Usage: !startsort [speaker_tag]")
async def start_sorting(ctx, speaker_tag: str = None):
    try:
        if sort_forum_by_reactions.is_running():
            await ctx.send(f"Sorting is already running. To stop, use !stopsort.")
        else:
            sort_forum_by_reactions.start(speaker_tag)
            if speaker_tag:
                await ctx.send(f"Started sorting forum posts by reactions for speaker tag '{speaker_tag}'. Updates every 1 minute.")
            else:
                await ctx.send("Started sorting all forum posts by reactions. Updates every 1 minute.\n" +
                             "Tip: To sort by a specific speaker, use !startsort <speaker_tag>")
            logger.info(f"Forum sorting started by user command{' for speaker tag: ' + speaker_tag if speaker_tag else ' for all posts'}")
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
