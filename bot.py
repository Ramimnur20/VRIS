import json
import logging
from pathlib import Path
import discord
from discord.ext import commands
from cogs.prefix import get_prefix
import os

# Load configuration
CONFIG_PATH = Path(__file__).parent / "config.json"
with open(CONFIG_PATH, "r", encoding="utf-8") as cfg_file:
    config = json.load(cfg_file)

# Set up logging
log_format = "[%(asctime)s] [ VOTOX ] - [ %(levelname)s ] - %(message)s"
logging.basicConfig(level=logging.INFO, format=log_format)
logger = logging.getLogger("VOTOX")

# Intents
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True


bot = commands.Bot(
    command_prefix=get_prefix,
    intents=intents,
    help_command=None
)

# Attach embed color to bot for easy access
bot.embed_color = int(config.get("embed_color", "0x7289DA"), 16)

# Load error handler
from utils.error import handle_error

# Help command is now handled by the HelpCog (loaded dynamically with other cogs)

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info("VOTOX is online!")

@bot.event
async def on_command_error(ctx, error):
    await handle_error(bot, ctx, error)

# Database setup during startup
@bot.event
async def setup_hook():
    # Initialize database
    from database import init_db
    await init_db()
    # Load cogs dynamically
    cog_path = Path(__file__).parent / "cogs"
    for file in cog_path.glob("*.py"):
        if file.name.startswith("__"):
            continue
        extension = f"cogs.{file.stem}"
        try:
            await bot.load_extension(extension)
            logger.info(f"Loaded cog: {extension}")
        except Exception as e:
            logger.error(f"Failed to load cog {extension}: {e}")

# Run the bot
bot.run(config["token"])