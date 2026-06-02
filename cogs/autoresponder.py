
import discord
from discord.ext import commands
from typing import Optional, Dict, List
import json
import re
import aiosqlite
from pathlib import Path


class Autoresponder(commands.Cog):
    """
    Autoresponder cog for VOTOX.
    
    Handles automated text responses and emoji reactions based on keyword triggers.
    """
    
    def __init__(self, bot: commands.Bot):
        """
        Initialize the Autoresponder cog.
        
        Args:
            bot: The Discord bot instance.
        """
        self.bot = bot
        
        # Database configuration
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        self._cache_responders: Dict[int, Dict[str, str]] = {}
        self._cache_reacts: Dict[int, Dict[str, str]] = {}

    def _get_db(self) -> aiosqlite.Connection:
        """Return a connection context manager."""
        return aiosqlite.connect(self.db_path)
    
    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    def _create_error_embed(self, title: str, description: str) -> discord.Embed:
        """
        Create a styled error embed.
        
        Args:
            title: The embed title.
            description: The embed description.
        
        Returns:
            A formatted Discord embed with error styling.
        """
        embed = discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=discord.Color.red()
        )
        embed.set_footer(text="VOTOX Autoresponder System")
        return embed
    
    def _create_success_embed(self, title: str, description: str) -> discord.Embed:
        """
        Create a styled success embed.
        
        Args:
            title: The embed title.
            description: The embed description.
        
        Returns:
            A formatted Discord embed with success styling.
        """
        embed = discord.Embed(
            title=f"✅ {title}",
            description=description,
            color=discord.Color.green()
        )
        embed.set_footer(text="VOTOX Autoresponder System")
        return embed
    
    def _create_info_embed(self, title: str, description: str) -> discord.Embed:
        """
        Create a styled info embed.
        
        Args:
            title: The embed title.
            description: The embed description.
        
        Returns:
            A formatted Discord embed with info styling.
        """
        embed = discord.Embed(
            title=f"ℹ️ {title}",
            description=description,
            color=discord.Color.blurple()
        )
        embed.set_footer(text="VOTOX Autoresponder System")
        return embed
    
    async def _get_autoresponders(self, guild_id: int) -> Dict[str, str]:
        """Retrieve autoresponders from DB."""
        if guild_id in self._cache_responders:
            return self._cache_responders[guild_id]
            
        async with self._get_db() as db:
            cursor = await db.execute("SELECT triggers FROM autoresponder_config WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
            data = json.loads(row[0]) if row else {}
            
        self._cache_responders[guild_id] = data
        return data

    async def _save_autoresponders(self, guild_id: int, data: Dict[str, str]) -> None:
        """Save autoresponders to DB."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO autoresponder_config (guild_id, triggers, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (guild_id, json.dumps(data))
            )
            await db.commit()
        self._cache_responders[guild_id] = data
    
    async def _get_autoreacts(self, guild_id: int) -> Dict[str, str]:
        """Retrieve autoreacts from DB."""
        if guild_id in self._cache_reacts:
            return self._cache_reacts[guild_id]
            
        async with self._get_db() as db:
            cursor = await db.execute("SELECT triggers FROM autoreact_config WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
            data = json.loads(row[0]) if row else {}
            
        self._cache_reacts[guild_id] = data
        return data

    async def _save_autoreacts(self, guild_id: int, data: Dict[str, str]) -> None:
        """Save autoreacts to DB."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO autoreact_config (guild_id, triggers, updated_at) VALUES (?, ?, CURRENT_TIMESTAMP)",
                (guild_id, json.dumps(data))
            )
            await db.commit()
        self._cache_reacts[guild_id] = data
    
    def _find_trigger_match(self, text: str, triggers: Dict[str, str]) -> Optional[str]:
        """
        Check if any trigger is contained in the text (case-insensitive).
        
        Args:
            text: The message text to check.
            triggers: Dictionary of triggers to search for.
        
        Returns:
            The matched trigger key, or None if no match found.
        """
        text_lower = text.lower()
        
        # Sort by length (longest first) to match more specific triggers first
        sorted_triggers = sorted(triggers.keys(), key=len, reverse=True)
        
        for trigger in sorted_triggers:
            if trigger.lower() in text_lower:
                return trigger
        
        return None
    
    # ========================================================================
    # Autoresponder Commands
    # ========================================================================
    
    @commands.group(name="autoresponder", invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def autoresponder_group(self, ctx: commands.Context):
        """
        Main command group for text autoresponder configuration.
        
        Displays a comprehensive help menu with all available commands.
        """
        embed = discord.Embed(
            title="💬 VOTOX Autoresponder - Help Menu",
            description="Configure automated text responses based on keywords.",
            color=discord.Color.blurple()
        )
        
        embed.add_field(
            name=".autoresponder add [trigger] [message]",
            value="Add a new text autoresponder trigger.",
            inline=False
        )
        
        embed.add_field(
            name=".autoresponder remove [trigger]",
            value="Remove an existing text autoresponder trigger.",
            inline=False
        )
        
        embed.add_field(
            name=".autoresponder list",
            value="Display all configured text autoresponder triggers.",
            inline=False
        )
        
        embed.add_field(
            name=".autoresponder edit [trigger] [new_message]",
            value="Modify the response for an existing trigger.",
            inline=False
        )
        
        embed.set_footer(text="Use .autoresponder <subcommand> for more information")
        
        await ctx.send(embed=embed)
    
    @autoresponder_group.command(name="add")
    @commands.has_permissions(manage_messages=True)
    async def autoresponder_add(self, ctx: commands.Context, trigger: str, *, message: str):
        """
        Add a new text autoresponder trigger.
        
        Args:
            ctx: The command context.
            trigger: The keyword trigger.
            message: The response message.
        """
        responders = await self._get_autoresponders(ctx.guild.id)
        
        if trigger.lower() in [t.lower() for t in responders.keys()]:
            embed = self._create_error_embed(
                "Trigger Already Exists",
                f"A trigger for **{trigger}** already exists.\n"
                f"Use `.autoresponder edit {trigger} [new_message]` to modify it."
            )
            await ctx.send(embed=embed)
            return
        
        responders[trigger] = message
        await self._save_autoresponders(ctx.guild.id, responders)
        
        embed = self._create_success_embed(
            "Autoresponder Added",
            f"**Trigger:** `{trigger}`\n"
            f"**Response:** {message}"
        )
        await ctx.send(embed=embed)
    
    @autoresponder_group.command(name="remove")
    @commands.has_permissions(manage_messages=True)
    async def autoresponder_remove(self, ctx: commands.Context, *, trigger: str):
        """
        Remove an existing text autoresponder trigger.
        
        Args:
            ctx: The command context.
            trigger: The keyword trigger to remove.
        """
        responders = await self._get_autoresponders(ctx.guild.id)
        
        # Find the trigger (case-insensitive)
        matching_trigger = None
        for t in responders.keys():
            if t.lower() == trigger.lower():
                matching_trigger = t
                break
        
        if not matching_trigger:
            embed = self._create_error_embed(
                "Trigger Not Found",
                f"No autoresponder trigger found for **{trigger}**."
            )
            await ctx.send(embed=embed)
            return
        
        removed_response = responders.pop(matching_trigger)
        await self._save_autoresponders(ctx.guild.id, responders)
        
        embed = self._create_success_embed(
            "Autoresponder Removed",
            f"**Trigger:** `{matching_trigger}`\n"
            f"**Removed Response:** {removed_response}"
        )
        await ctx.send(embed=embed)
    
    @autoresponder_group.command(name="list")
    @commands.has_permissions(manage_messages=True)
    async def autoresponder_list(self, ctx: commands.Context):
        """
        Display all configured text autoresponder triggers.
        
        Args:
            ctx: The command context.
        """
        responders = await self._get_autoresponders(ctx.guild.id)
        
        if not responders:
            embed = self._create_info_embed(
                "No Autoresponders",
                "There are no text autoresponder triggers configured.\n"
                "Use `.autoresponder add [trigger] [message]` to create one."
            )
            await ctx.send(embed=embed)
            return
        
        embed = discord.Embed(
            title="💬 Text Autoresponders",
            description=f"Total triggers: {len(responders)}",
            color=discord.Color.blurple()
        )
        
        for trigger, response in responders.items():
            # Truncate long responses
            display_response = response[:100] + "..." if len(response) > 100 else response
            embed.add_field(
                name=f"`{trigger}`",
                value=display_response,
                inline=False
            )
        
        embed.set_footer(text="VOTOX Autoresponder System")
        
        await ctx.send(embed=embed)
    
    @autoresponder_group.command(name="edit")
    @commands.has_permissions(manage_messages=True)
    async def autoresponder_edit(self, ctx: commands.Context, trigger: str, *, new_message: str):
        """
        Modify the response for an existing trigger.
        
        Args:
            ctx: The command context.
            trigger: The keyword trigger to edit.
            new_message: The new response message.
        """
        responders = await self._get_autoresponders(ctx.guild.id)
        
        # Find the trigger (case-insensitive)
        matching_trigger = None
        for t in responders.keys():
            if t.lower() == trigger.lower():
                matching_trigger = t
                break
        
        if not matching_trigger:
            embed = self._create_error_embed(
                "Trigger Not Found",
                f"No autoresponder trigger found for **{trigger}**."
            )
            await ctx.send(embed=embed)
            return
        
        old_response = responders[matching_trigger]
        responders[matching_trigger] = new_message
        await self._save_autoresponders(ctx.guild.id, responders)
        
        embed = self._create_success_embed(
            "Autoresponder Updated",
            f"**Trigger:** `{matching_trigger}`\n"
            f"**Old Response:** {old_response}\n"
            f"**New Response:** {new_message}"
        )
        await ctx.send(embed=embed)
    
    # ========================================================================
    # Autoreact Commands
    # ========================================================================
    
    @commands.group(name="autoreact", invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    async def autoreact_group(self, ctx: commands.Context):
        """
        Main command group for emoji autoreact configuration.
        
        Displays a comprehensive help menu with all available commands.
        """
        embed = discord.Embed(
            title="😊 VOTOX Autoreact - Help Menu",
            description="Configure automated emoji reactions based on keywords.",
            color=discord.Color.blurple()
        )
        
        embed.add_field(
            name=".autoreact add [trigger] [emoji]",
            value="Add a new emoji autoreact trigger.",
            inline=False
        )
        
        embed.add_field(
            name=".autoreact remove [trigger]",
            value="Remove an existing emoji autoreact trigger.",
            inline=False
        )
        
        embed.add_field(
            name=".autoreact list",
            value="Display all configured emoji autoreact triggers.",
            inline=False
        )
        
        embed.add_field(
            name=".autoreact edit [trigger] [new_emoji]",
            value="Modify the emoji reaction for an existing trigger.",
            inline=False
        )
        
        embed.set_footer(text="Use .autoreact <subcommand> for more information")
        
        await ctx.send(embed=embed)
    
    @autoreact_group.command(name="add")
    @commands.has_permissions(manage_messages=True)
    async def autoreact_add(self, ctx: commands.Context, trigger: str, emoji: str):
        """
        Add a new emoji autoreact trigger.
        
        Args:
            ctx: The command context.
            trigger: The keyword trigger.
            emoji: The emoji to react with.
        """
        reacts = await self._get_autoreacts(ctx.guild.id)
        
        if trigger.lower() in [t.lower() for t in reacts.keys()]:
            embed = self._create_error_embed(
                "Trigger Already Exists",
                f"A trigger for **{trigger}** already exists.\n"
                f"Use `.autoreact edit {trigger} [new_emoji]` to modify it."
            )
            await ctx.send(embed=embed)
            return
        
        # Validate emoji by attempting to use it
        try:
            # Try to parse the emoji
            emoji_obj = await commands.EmojiConverter().convert(ctx, emoji)
            emoji_str = str(emoji_obj)
        except commands.BadArgument:
            # If it's not a custom emoji, treat it as a unicode emoji
            emoji_str = emoji
        
        reacts[trigger] = emoji_str
        await self._save_autoreacts(ctx.guild.id, reacts)
        
        embed = self._create_success_embed(
            "Autoreact Added",
            f"**Trigger:** `{trigger}`\n"
            f"**Emoji:** {emoji_str}"
        )
        await ctx.send(embed=embed)
    
    @autoreact_group.command(name="remove")
    @commands.has_permissions(manage_messages=True)
    async def autoreact_remove(self, ctx: commands.Context, *, trigger: str):
        """
        Remove an existing emoji autoreact trigger.
        
        Args:
            ctx: The command context.
            trigger: The keyword trigger to remove.
        """
        reacts = await self._get_autoreacts(ctx.guild.id)
        
        # Find the trigger (case-insensitive)
        matching_trigger = None
        for t in reacts.keys():
            if t.lower() == trigger.lower():
                matching_trigger = t
                break
        
        if not matching_trigger:
            embed = self._create_error_embed(
                "Trigger Not Found",
                f"No autoreact trigger found for **{trigger}**."
            )
            await ctx.send(embed=embed)
            return
        
        removed_emoji = reacts.pop(matching_trigger)
        await self._save_autoreacts(ctx.guild.id, reacts)
        
        embed = self._create_success_embed(
            "Autoreact Removed",
            f"**Trigger:** `{matching_trigger}`\n"
            f"**Removed Emoji:** {removed_emoji}"
        )
        await ctx.send(embed=embed)
    
    @autoreact_group.command(name="list")
    @commands.has_permissions(manage_messages=True)
    async def autoreact_list(self, ctx: commands.Context):
        """
        Display all configured emoji autoreact triggers.
        
        Args:
            ctx: The command context.
        """
        reacts = await self._get_autoreacts(ctx.guild.id)
        
        if not reacts:
            embed = self._create_info_embed(
                "No Autoreacts",
                "There are no emoji autoreact triggers configured.\n"
                "Use `.autoreact add [trigger] [emoji]` to create one."
            )
            await ctx.send(embed=embed)
            return
        
        embed = discord.Embed(
            title="😊 Emoji Autoreacts",
            description=f"Total triggers: {len(reacts)}",
            color=discord.Color.blurple()
        )
        
        for trigger, emoji in reacts.items():
            embed.add_field(
                name=f"`{trigger}`",
                value=emoji,
                inline=False
            )
        
        embed.set_footer(text="VOTOX Autoresponder System")
        
        await ctx.send(embed=embed)
    
    @autoreact_group.command(name="edit")
    @commands.has_permissions(manage_messages=True)
    async def autoreact_edit(self, ctx: commands.Context, trigger: str, new_emoji: str):
        """
        Modify the emoji reaction for an existing trigger.
        
        Args:
            ctx: The command context.
            trigger: The keyword trigger to edit.
            new_emoji: The new emoji to react with.
        """
        reacts = await self._get_autoreacts(ctx.guild.id)
        
        # Find the trigger (case-insensitive)
        matching_trigger = None
        for t in reacts.keys():
            if t.lower() == trigger.lower():
                matching_trigger = t
                break
        
        if not matching_trigger:
            embed = self._create_error_embed(
                "Trigger Not Found",
                f"No autoreact trigger found for **{trigger}**."
            )
            await ctx.send(embed=embed)
            return
        
        # Validate emoji
        try:
            emoji_obj = await commands.EmojiConverter().convert(ctx, new_emoji)
            emoji_str = str(emoji_obj)
        except commands.BadArgument:
            emoji_str = new_emoji
        
        old_emoji = reacts[matching_trigger]
        reacts[matching_trigger] = emoji_str
        await self._save_autoreacts(ctx.guild.id, reacts)
        
        embed = self._create_success_embed(
            "Autoreact Updated",
            f"**Trigger:** `{matching_trigger}`\n"
            f"**Old Emoji:** {old_emoji}\n"
            f"**New Emoji:** {emoji_str}"
        )
        await ctx.send(embed=embed)
    
    # ========================================================================
    # Event Listeners
    # ========================================================================
    
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Handle incoming messages and trigger autoresponders and autoreacts.
        
        Args:
            message: The message that was sent.
        """
        # Ignore bot messages and messages without a guild
        if message.author.bot or not message.guild:
            return
        
        # Check for autoresponder triggers
        responders = await self._get_autoresponders(message.guild.id)
        matched_trigger = self._find_trigger_match(message.content, responders)
        
        if matched_trigger:
            response = responders[matched_trigger]
            try:
                await message.reply(response, mention_author=False)
            except discord.Forbidden:
                # Bot doesn't have permission to send messages
                pass
            except Exception as e:
                print(f"Error sending autoresponder: {e}")
        
        # Check for autoreact triggers
        reacts = await self._get_autoreacts(message.guild.id)
        matched_react_trigger = self._find_trigger_match(message.content, reacts)
        
        if matched_react_trigger:
            emoji = reacts[matched_react_trigger]
            try:
                await message.add_reaction(emoji)
            except discord.Forbidden:
                # Bot doesn't have permission to add reactions
                pass
            except discord.HTTPException:
                # Invalid emoji or emoji not found
                pass
            except Exception as e:
                print(f"Error adding autoreact: {e}")


# Setup function to load the cog
async def setup(bot: commands.Bot):
    """
    Load the Autoresponder cog into the bot.
    
    Args:
        bot: The Discord bot instance.
    """
    await bot.add_cog(Autoresponder(bot))
