"""
VRIS Help Cog - Interactive help system with dropdown navigation.

This cog provides a production-ready, aesthetically pleasing help system featuring:
- Beautiful Discord embeds with consistent branding
- Interactive dropdown menus for category navigation
- Dynamic command counting per category
- User-specific access control (prevents hijacking)
- 60-second timeout with graceful degradation
- Three modes: landing page, category lookup, command lookup

The help system is designed to be fully modular and customizable.
"""

import discord
from discord.ext import commands
from typing import Dict, List, Optional
from utils.help import HelpCog


async def setup(bot: commands.Bot):
    """
    Load the help cog into the bot.
    
    This function is called automatically during bot startup by the dynamic
    cog loader in bot.py's setup_hook() method.
    
    Args:
        bot: The Discord bot instance.
    """
    # Disable the default help command
    bot.help_command = None
    
    # Load the help cog
    await bot.add_cog(HelpCog(bot))
