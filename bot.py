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
guild_id = 1326353542037901352
rankings_channel_id = 1337904418603008051
questions_channel = None

# List to store previously asked questions
previous_questions = {}  # {tag_id: [(question, thread_id), ...]}

def find_similar_questions(new_question, message, tags=None, threshold=0.6):
    if not tags:
        # logger.info("No previous questions found")
        return []

    # Use first available tag
    current_tag = tags[0] if tags else None
    if not current_tag:
        logger.info("No speaker tag found")
        return []
    
    key = current_tag.id  # Ensure tag.id is used for lookup
    tag_questions = previous_questions.get(key, [])

    # Log previous questions for the current tag
    logger.info(f"Previous questions for tag ID {key} ({current_tag.name}): {tag_questions}")

    if not tag_questions:
        logger.info(f"No previous questions for tag ID: {key} ({current_tag.name})")
        return []

    # Unpack questions and thread_ids
    filtered_questions, filtered_thread_ids = zip(*tag_questions) if tag_questions else ([], [])

    # Create TF-IDF vectors
    vectorizer = TfidfVectorizer()
    all_questions = list(filtered_questions) + [new_question]
    tfidf_matrix = vectorizer.fit_transform(all_questions)

    # Calculate similarity
    similarity_vector = cosine_similarity(tfidf_matrix[-1:], tfidf_matrix[:-1])[0]

    # Get similar questions above threshold
    similar = [
        (q, score, tid) for q, score, tid in zip(filtered_questions, similarity_vector, filtered_thread_ids)
        if score > threshold
    ]
    similar.sort(key=lambda x: x[1], reverse=True)

    # guild_id = message.guild.id if message.guild and hasattr(message, 'guild') else None
    # Return both the question text and the formatted link
    return [(q, f"https://discord.com/channels/{guild_id}/{tid}") for q, score, tid in similar[:5]]

# Move this function outside of post_question_flow
async def get_question_tags(msg: discord.Message):
    forum_channel = questions_channel  # forum_channel = bot.get_channel(response_channel_id)
    if not forum_channel or not isinstance(forum_channel, discord.ForumChannel):
        logger.error(f"Could not find forumn channel not populated from guild when fetching tags")
        await msg.reply("Unable to process question: Could not find forum channel")
        return []

    available_tags = forum_channel.available_tags
    if not available_tags:
        logger.error(f"No tags found in forum channel")
        await msg.reply("Unable to process question: No tags found in forum channel")
        return []

    view = View(timeout=300)
    select = Select(
        placeholder="Choose tags for your question...",
        min_values=1,  # Require at least one tag
        max_values=min(len(available_tags), 5),
        options=[discord.SelectOption(label=tag.name, value=str(tag.id)) for tag in available_tags]
    )
    
    selected_tags = []
    
    async def select_callback(interaction):
        selected_tags.clear()
        # Store the actual tag objects instead of just IDs
        selected_tags.extend([tag for tag in available_tags if str(tag.id) in select.values])
        await interaction.response.defer()
        view.stop()
        # await interaction.response.send_message(
        #     f"Selected tags: {', '.join(tag.name for tag in selected_tags)}",
        #     ephemeral=True
        # )
    
    select.callback = select_callback
    view.add_item(select)
    
    # done_button = Button(label="Done", style=discord.ButtonStyle.green)
    
    # async def done_callback(interaction):
    #     await interaction.response.defer()  # Acknowledge the interaction
    #     view.stop()  # Stop the view to clear outstanding interactions
    #     # await interaction.followup.send(  # Use followup to send the message after stopping the view
    #     #     f"Great! Attributed question with the tags: {', '.join(tag.name for tag in selected_tags)}"
    #     # )

    async def cancel_callback(interaction):
        await interaction.response.send_message("Okay, I won't proceed with your question.")
    
    # done_button.callback = done_callback
    # view.add_item(done_button)
    
    await msg.reply("Please select tags for your question:", view=view)  # , ephemeral=True
    await view.wait()
    
    if len(selected_tags) == 0:
        return []
    return selected_tags

def format_first_message(author: discord.Member, content: str, answer_response: str = None) -> str:
    post_content = f"**by {author.mention}**"  # must be formatted this way alone for later parsing
    if len(content) > 100:
        post_content += f"\n\n**Full question:**\n{content}"
    return post_content


async def post_question_flow(message: discord.Message, answer_response: str = None, tags: list = None):
    async def post_question(tags: list[discord.Object] = None):
        if questions_channel is None:
            return
        
        forum_channel = questions_channel
        # bot.get_channel(response_channel_id)
        if forum_channel and isinstance(forum_channel, discord.ForumChannel):
            thread_title = (message.content[:97] + "...") if len(message.content) > 100 else message.content
            
            try:
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
                # previous_questions.append(message.content)
                # logger.info("Updated previous questions: %s", previous_questions)
            
            except Exception as e:
                logger.error(f"Failed to post question: {e}")
                await message.reply("Error: Something went wrong. We could not post your question.")
            
            # Add to previous questions dictionary
            if tags:
                for tag in tags:
                    if tag.id not in previous_questions:
                        previous_questions[tag.id] = []
                    previous_questions[tag.id].append((thread_title, thread.thread.id))
                    logger.info(f"Added new question to tag {tag.name}: {thread_title}")
        else:
            logger.error(f"Could not find forum channel")
            await message.reply("Error: Could not find forum channel")

    # Use passed tags instead of asking again
    await post_question(tags)

@bot.event
async def on_ready():
    """
    Called when the client is done preparing the data received from Discord.
    Prints message on terminal when bot successfully connects to discord.
    """
    global questions_channel
    logger.info(f"{bot.user} has connected to Discord!")

    # Fetch the response channel
    guild = bot.get_guild(guild_id)
    if not guild:
        logger.error('Guild not found!')
        return
    
    logger.info(f'Connected to guild: {guild.name}')
    response_channel = discord.utils.get(guild.channels, name="questions-for-speakers")
    if not response_channel:
        logger.error("Could not find response channel")
        return
    
    logger.info(f'Found channel: {response_channel.name}')
    questions_channel = response_channel

    # logger.info(f"Channel found: {response_channel.name} (ID: {response_channel.id}, Type: {type(response_channel)})")

    if isinstance(response_channel, discord.ForumChannel):
        # logger.info(f"Fetching threads from forum channel: {response_channel.name}")
        
        # Clear existing dictionary
        previous_questions.clear()
        
        try:
            # Get all threads (both active and archived)
            all_threads = []
            all_threads.extend(response_channel.threads)  # Active threads
            
            # Fetch archived threads
            async for archived_thread in response_channel.archived_threads():
                all_threads.append(archived_thread)
            
            logger.info(f"Found {len(all_threads)} total threads")
            
            # Process all threads
            for thread in all_threads:
                try:
                    # Get the first message in each thread
                    async for message in thread.history(limit=1, oldest_first=True):
                        # if not message.author.bot:  # TODO - QUESTION
                        # Store question for each tag
                        for tag in thread.applied_tags:
                            if tag.id not in previous_questions:
                                previous_questions[tag.id] = []
                            previous_questions[tag.id].append((thread.name, thread.id))
                            # logger.info(f"Added question to tag {tag.name}: {thread.name}")
                        break
                except Exception as thread_error:
                    logger.error(f"Error processing thread {thread.name}: {thread_error}")

            logger.info("Loaded previous questions")
            # Log summary of loaded questions
            # logger.info("Summary of loaded questions:")
            # for tag_id, questions in previous_questions.items():
            #     tag = discord.utils.get(response_channel.available_tags, id=tag_id)
            #     if tag:
            #         logger.info(f"Tag {tag.name}: {len(questions)} questions")
            #         for q, tid in questions:
            #             logger.info(f"  - {q} (Thread ID: {tid})")

        except Exception as e:
            logger.error(f"Error fetching messages from forum channel: {e}")
    else:
        logger.error(f"The 'forumn channel' from guild is not a forum channel. It is of type: {type(response_channel)}.")

@bot.event
async def on_message(message: discord.Message):
    """
    Called when a message is sent in any channel the bot can see.

    https://discordpy.readthedocs.io/en/latest/api.html#discord.on_message
    """
    await bot.process_commands(message)

    def ai_has_answer(answer_response):
        if not answer_response:
            return False
        if answer_response.lower().strip() in ["no", "no.", "no!", "no?", "no..", "no..."]:
            return False
        
        return True

    async def confirm_post_with_ai():
        # Step 3: If there's an answer, display it and ask if they want to post
        # await message.reply(f"Here's what I found online: {answer_response}")
        
        # Ask if they want to post the question
        post_view = View(timeout=300)
        post_button = Button(label="Yes, post the question", style=discord.ButtonStyle.green)
        dont_post_button = Button(label="No, don't post", style=discord.ButtonStyle.red)

        async def post_callback(interaction):
            await interaction.response.defer()
            await post_question_flow(message, answer_response, tags)

        async def dont_post_callback(interaction):
            await interaction.response.send_message("Okay, I won't post your question.") #  ephemeral=True

        post_button.callback = post_callback
        dont_post_button.callback = dont_post_callback
        post_view.add_item(post_button)
        post_view.add_item(dont_post_button)

        await message.reply(f"Here's what I found online: {answer_response}\n\nDo you still want to post your question?", view=post_view)  # ephemeral=True


    # Ignore bot messages and commands
    if message.author.bot or message.content.startswith("!"):
        return
    
    # ignore messages that are not DMs
    if message.guild:
        return
    
    # explicitly ignore messages that are in the response channel
    # if message.channel.id == response_channel_id:
    #     return

    # logger.info("Received message from %s: %s", message.author, message.content)

    # Get tags first
    tags = await get_question_tags(message)
    if not tags:
        return

    # Step 1: Check for similar questions with the selected tags
    similar_questions = find_similar_questions(message.content, message, tags=tags)
    
    if similar_questions:
        view = View(timeout=300)
        continue_button = Button(label="Continue with my question", style=discord.ButtonStyle.primary)
        cancel_button = Button(label="Cancel", style=discord.ButtonStyle.secondary)
        
        async def continue_callback(interaction):
            await interaction.response.defer()
            # Step 2: If user continues, check if agent can answer
            try:
                answer_response = await probe_and_answer_agent.run(message)
            except Exception as e:
                logger.error(f"Error getting answer from agent: {e}")
                await message.reply("Error: Something went wrong. We could not answer your question.")
                return
            
            if ai_has_answer(answer_response):
                confirm_post_with_ai()
            else:
                # If no answer, just proceed with posting
                await post_question_flow(message, answer_response, tags)
        
        async def cancel_callback(interaction):
            await interaction.response.send_message("Okay, I won't proceed with your question.")  #  ephemeral=True
        
        continue_button.callback = continue_callback
        cancel_button.callback = cancel_callback
        view.add_item(continue_button)
        view.add_item(cancel_button)


        
        # Show similar questions and ask if they want to continue
        embed = discord.Embed(color=discord.Color.blue())  # title="I found some similar questions:", 

        for question, thread_url in similar_questions:
            embed.add_field(
                name=f"{question if len(question) < 256 else question[:(256-3)] + "..."}",
                value=f"[View Thread]({thread_url})",
                inline=False
            )

        await message.reply(
            "Here are some similar questions that others have already asked.\nClick 'view thread' to head over and upvote a question.",
            embed=embed,
            view=view
        )
    else:
        # If no similar questions, proceed to check if agent can answer
        answer_response = await probe_and_answer_agent.run(message)
        
        if ai_has_answer(answer_response):
            # If there's an answer, display it and ask if they want to post
            # await message.reply(f"Here's what I found online: {answer_response}")
            
            # Ask if they want to post the question
            post_view = View(timeout=300)
            post_button = Button(label="Yes, post the question", style=discord.ButtonStyle.green)
            dont_post_button = Button(label="No, don't post", style=discord.ButtonStyle.red)

            async def post_callback(interaction):
                await interaction.response.defer()
                await post_question_flow(message, answer_response, tags)

            async def dont_post_callback(interaction):
                await interaction.response.send_message("Okay, I won't post your question.")  # ephemeral=True

            post_button.callback = post_callback
            dont_post_button.callback = dont_post_callback
            post_view.add_item(post_button)
            post_view.add_item(dont_post_button)

            await message.reply(f"Here's what I found online: {answer_response}\n\nDo you still want to post your question?", view=post_view)  # ephemeral=True
            # confirm_post_with_ai()
        else:
            # If no answer, just proceed with posting
            await post_question_flow(message, answer_response, tags)




# Tasks

@tasks.loop(minutes=1)
async def sort_forum_by_reactions(speaker_tag: str = None):
    # logger.info("Starting forum sort task...")
    forum_channel = questions_channel # bot.get_channel(response_channel_id)
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
        
        # logger.info(f"Found {len(all_threads)} total threads")

        # Filter threads by speaker tag if provided
        if speaker_tag:
            filtered_threads = []
            for thread in all_threads:
                # Check if thread has the specified speaker tag
                if any(tag.name == speaker_tag for tag in thread.applied_tags):
                    filtered_threads.append(thread)
            all_threads = filtered_threads
            # logger.info(f"Found {len(all_threads)} threads for speaker tag: {speaker_tag}")
        
        thread_reactions = []

        

        # Process each thread
        for thread in all_threads:
            try:
                # Initialize original_poster mention
                original_poster = None
                first_message = None
                
                # Get the first message (includes citation)
                if hasattr(thread, 'starter_message') and thread.starter_message:
                    first_message = thread.starter_message
                else:
                    # logger.warning(f"Thread '{thread.name}' has no starter message")
                    async for message in thread.history(limit=1, oldest_first=True):
                        first_message = message
                        break
                
                if first_message:
                    try:
                        if first_message.author.id == bot.user.id:  # Access author if sent by ModBot
                            # Split by "**by" and make sure there's a second part
                            original_poster = first_message.content if first_message else None
                            parts = original_poster.split("**by")
                            if len(parts) > 1:
                                # remove everything after **
                                parts[1] = parts[1].split("**")[0]
                                original_poster = parts[1].strip()
                            else:
                                original_poster = None
                        else:
                            original_poster = first_message.author.mention
                    except Exception as parse_error:
                        logger.error(f"Error parsing original poster: {parse_error}")
                        original_poster = None

                reaction_count = 0
                if first_message and first_message.reactions:
                    reaction_count = sum(reaction.count for reaction in first_message.reactions)

                thread_reactions.append((thread, reaction_count, original_poster))
                # logger.info(f"Thread '{thread.name}' by {original_poster if original_poster else 'Unknown'} has {reaction_count} reactions")
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
            # logger.info(f"Added ranking: {thread.name} with {reaction_count} reactions by {original_poster if original_poster else 'Unknown'}")
        
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
            # logger.info(f"Updated rankings message at {current_time}")
        else:
            await rankings_channel.send(rankings)
            # logger.info(f"Created new rankings message at {current_time}")
                
    except Exception as e:
        logger.error(f"Error in sort_forum_by_reactions: {e}")
# Commands


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
