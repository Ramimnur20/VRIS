
import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, Dict, List, Tuple, Any, Set
from datetime import datetime, timedelta
from collections import deque
import re
import io
from urllib.parse import urlparse
import aiosqlite
from pathlib import Path


# ============================================================================
# Confirmation Views for Destructive Actions
# ============================================================================

class ConfirmationView(discord.ui.View):
    """
    Interactive confirmation view for destructive moderation actions.
    
    Provides Confirm (green) and Cancel (red) buttons.
    """
    
    def __init__(self, author_id: int, timeout: float = 60.0):
        """
        Initialize the confirmation view.
        
        Args:
            author_id: The ID of the user who triggered the action.
            timeout: How long the view remains active.
        """
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.confirmed = False
    
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        """Ensure only the command author can use the buttons."""
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "You are not authorized to use this button.",
                ephemeral=True
            )
            return False
        return True
    
    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle confirmation."""
        self.confirmed = True
        await interaction.response.defer()
        self.stop()
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.danger)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle cancellation."""
        self.confirmed = False
        await interaction.response.defer()
        self.stop()


# ============================================================================
# Duration Parsing Utilities
# ============================================================================

def parse_duration(duration_str: str) -> Optional[timedelta]:
    """
    Parse a duration string into a timedelta object.
    
    Supported formats:
    - "7d" -> 7 days
    - "24h" -> 24 hours
    - "30m" -> 30 minutes
    - "45s" -> 45 seconds
    
    Args:
        duration_str: String representation of duration.
    
    Returns:
        timedelta object, or None if parsing fails.
    """
    if not duration_str:
        return None
    
    duration_str = duration_str.strip().lower()
    
    # Regex to match number + unit
    match = re.match(r'(\d+)([smhdw])', duration_str)
    if not match:
        return None
    
    amount = int(match.group(1))
    unit = match.group(2)
    
    if unit == 's':
        return timedelta(seconds=amount)
    elif unit == 'm':
        return timedelta(minutes=amount)
    elif unit == 'h':
        return timedelta(hours=amount)
    elif unit == 'd':
        return timedelta(days=amount)
    elif unit == 'w':
        return timedelta(weeks=amount)
    
    return None


def format_duration(td: timedelta) -> str:
    """
    Format a timedelta into a readable string.
    
    Args:
        td: The timedelta to format.
    
    Returns:
        Human-readable duration string.
    """
    total_seconds = int(td.total_seconds())
    
    weeks = total_seconds // (7 * 24 * 3600)
    total_seconds %= 7 * 24 * 3600
    
    days = total_seconds // (24 * 3600)
    total_seconds %= 24 * 3600
    
    hours = total_seconds // 3600
    total_seconds %= 3600
    
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    
    parts = []
    if weeks > 0:
        parts.append(f"{weeks}w")
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0:
        parts.append(f"{seconds}s")
    
    return " ".join(parts) if parts else "0s"


# ============================================================================
# Main Moderation Cog
# ============================================================================

class Moderation(commands.Cog):
    """
    Advanced moderation cog for VOTOX.
    
    Handles bans, kicks, timeouts, purges, warnings, and lockdowns.
    """
    
    def __init__(self, bot: commands.Bot):
        """
        Initialize the Moderation cog.
        
        Args:
            bot: The Discord bot instance.
        """
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        
        # In-memory caches for snipe functionality (per channel)
        # Stores the most recent event for each type per channel
        self._sniped_cache: Dict[int, Dict[str, Any]] = {} # {channel_id: {message_data}}
        self._edited_cache: Dict[int, Dict[str, Any]] = {} # {channel_id: {before_data, after_data}}
        self._reaction_cache: Dict[int, Dict[str, Any]] = {} # {channel_id: {reaction_data}}
        
        self._protected_cache: Dict[int, Dict[str, Set[int]]] = {} # {guild_id: {"channels": {channel_id}, "users": {user_id}}}
    
    def _get_db(self) -> aiosqlite.Connection:
        """
        Get a database connection.
        
        Returns:
            aiosqlite connection object.
        """
        return aiosqlite.connect(self.db_path)
    
    @commands.Cog.listener()
    async def on_ready(self):
        """Refresh the protection cache when the bot is ready."""
        for guild in self.bot.guilds:
            await self._refresh_protection_cache(guild.id)

    async def _refresh_protection_cache(self, guild_id: int) -> None:
        """Refresh the in-memory cache for protected channels and users for a given guild."""
        async with self._get_db() as db:
            cursor = await db.execute("SELECT channel_id FROM snipe_protected_channels WHERE guild_id = ?", (guild_id,))
            protected_channels = {row[0] for row in await cursor.fetchall()}
            
            cursor = await db.execute("SELECT user_id FROM snipe_protected_users WHERE guild_id = ?", (guild_id,))
            protected_users = {row[0] for row in await cursor.fetchall()}
            
        self._protected_cache[guild_id] = {"channels": protected_channels, "users": protected_users}

    def _is_protected_channel(self, guild_id: int, channel_id: int) -> bool:
        return channel_id in self._protected_cache.get(guild_id, {}).get("channels", set())

    def _is_protected_user(self, guild_id: int, user_id: int) -> bool:
        return user_id in self._protected_cache.get(guild_id, {}).get("users", set())
    
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
        embed.set_footer(text="VOTOX Moderation System")
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
        embed.set_footer(text="VOTOX Moderation System")
        return embed
    
    def _create_warning_embed(self, title: str, description: str) -> discord.Embed:
        """
        Create a styled warning embed.
        
        Args:
            title: The embed title.
            description: The embed description.
        
        Returns:
            A formatted Discord embed with warning styling.
        """
        embed = discord.Embed(
            title=f"⚠️ {title}",
            description=description,
            color=discord.Color.orange()
        )
        embed.set_footer(text="VOTOX Moderation System")
        return embed
    
    def _create_info_embed(self, title: str, description: str) -> discord.Embed:
        """
        Create a styled information embed.
        
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
        embed.set_footer(text="VOTOX Moderation System")
        return embed
    
    async def _check_hierarchy(self, moderator: discord.Member, target: discord.Member) -> Tuple[bool, str]:
        """
        Check if moderator can act on target based on role hierarchy.
        
        Args:
            moderator: The moderator attempting the action.
            target: The target of the action.
        
        Returns:
            Tuple of (is_valid, error_message).
        """
        if moderator.id == target.id:
            return False, "You cannot perform actions on yourself."
        
        if target.id == self.bot.user.id:
            return False, "You cannot perform actions on me."
        
        if moderator.top_role <= target.top_role and moderator.id != moderator.guild.owner_id:
            return False, f"You cannot perform actions on {target.mention} (insufficient role hierarchy)."
        
        if moderator.guild.me.top_role <= target.top_role:
            return False, f"I cannot perform actions on {target.mention} (my role is too low)."
        
        return True, ""
    
    # ========================================================================
    # Ban Command
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="ban", aliases=["yeet"])
    @commands.has_permissions(ban_members=True)
    async def ban(self, ctx: commands.Context, user: discord.User, *, args: str = ""):
        """
        Ban a member from the server with optional duration.
        
        Syntax: .ban [user] (reason) (duration)
        
        Args:
            ctx: The command context.
            user: The user to ban.
            args: Optional reason and duration.
        """
        try:
            member = await ctx.guild.fetch_member(user.id)
        except discord.NotFound:
            # If member is not in the guild, allow direct ban by user ID
            member = None
        
        if member:
            valid, error = await self._check_hierarchy(ctx.author, member)
            if not valid:
                embed = self._create_error_embed("Hierarchy Error", error)
                await ctx.send(embed=embed)
                return
        
        # Parse reason and duration
        reason = "No reason provided"
        duration = None
        
        if args:
            parts = args.split()
            # Try to parse last part as duration
            if parts and re.match(r'\d+[smhdw]', parts[-1]):
                duration = parse_duration(parts[-1])
                reason = " ".join(parts[:-1]) if len(parts) > 1 else "No reason provided"
            else:
                reason = args
        
        # Create confirmation embed
        duration_str = format_duration(duration) if duration else "Permanent"
        embed = self._create_warning_embed(
            "Ban Confirmation",
            f"**User:** {user.mention}\n"
            f"**Reason:** {reason}\n"
            f"**Duration:** {duration_str}\n\n"
            f"Click **Confirm** to proceed or **Cancel** to abort."
        )
        
        view = ConfirmationView(ctx.author.id)
        msg = await ctx.send(embed=embed, view=view)
        
        # Wait for confirmation
        await view.wait()
        
        if not view.confirmed:
            embed = self._create_error_embed("Ban Cancelled", "The ban action was cancelled.")
            await msg.edit(embed=embed, view=None)
            return
        
        # Perform the ban
        try:
            if duration:
                # Discord doesn't support timed bans natively; note this in the reason
                await ctx.guild.ban(user, reason=f"[{format_duration(duration)}] {reason}")
            else:
                await ctx.guild.ban(user, reason=reason)
            
            embed = self._create_success_embed(
                "Ban Executed",
                f"**User:** {user.mention}\n"
                f"**Reason:** {reason}\n"
                f"**Duration:** {duration_str}"
            )
            await msg.edit(embed=embed, view=None)
        
        except discord.Forbidden:
            embed = self._create_error_embed(
                "Permission Error",
                "I lack the necessary permissions to ban this user."
            )
            await msg.edit(embed=embed, view=None)
        except Exception as e:
            embed = self._create_error_embed(
                "Ban Failed",
                f"An error occurred: {str(e)}"
            )
            await msg.edit(embed=embed, view=None)
    
    # ========================================================================
    # Kick Command
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="kick")
    @commands.has_permissions(kick_members=True)
    async def kick(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        """
        Kick a member from the server.
        
        Syntax: .kick [user] (reason)
        
        Args:
            ctx: The command context.
            member: The member to kick.
            reason: The reason for the kick.
        """
        valid, error = await self._check_hierarchy(ctx.author, member)
        if not valid:
            embed = self._create_error_embed("Hierarchy Error", error)
            await ctx.send(embed=embed)
            return
        
        # Create confirmation embed
        embed = self._create_warning_embed(
            "Kick Confirmation",
            f"**User:** {member.mention}\n"
            f"**Reason:** {reason}\n\n"
            f"Click **Confirm** to proceed or **Cancel** to abort."
        )
        
        view = ConfirmationView(ctx.author.id)
        msg = await ctx.send(embed=embed, view=view)
        
        # Wait for confirmation
        await view.wait()
        
        if not view.confirmed:
            embed = self._create_error_embed("Kick Cancelled", "The kick action was cancelled.")
            await msg.edit(embed=embed, view=None)
            return
        
        # Perform the kick
        try:
            await member.kick(reason=reason)
            
            embed = self._create_success_embed(
                "Kick Executed",
                f"**User:** {member.mention}\n**Reason:** {reason}"
            )
            await msg.edit(embed=embed, view=None)
        
        except discord.Forbidden:
            embed = self._create_error_embed(
                "Permission Error",
                "I lack the necessary permissions to kick this user."
            )
            await msg.edit(embed=embed, view=None)
        except Exception as e:
            embed = self._create_error_embed(
                "Kick Failed",
                f"An error occurred: {str(e)}"
            )
            await msg.edit(embed=embed, view=None)
    
    # ========================================================================
    # Timeout Command
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="timeout", aliases=["mute"])
    @commands.has_permissions(moderate_members=True)
    async def timeout(self, ctx: commands.Context, member: discord.Member, duration: str = "1h", *, reason: str = "No reason provided"):
        """
        Time out a member for a specified duration.
        
        Syntax: .timeout [user] (duration) (reason)
        
        Args:
            ctx: The command context.
            member: The member to timeout.
            duration: The duration (e.g., "1h", "30m").
            reason: The reason for the timeout.
        """
        valid, error = await self._check_hierarchy(ctx.author, member)
        if not valid:
            embed = self._create_error_embed("Hierarchy Error", error)
            await ctx.send(embed=embed)
            return
        
        # Parse duration
        td = parse_duration(duration)
        if not td:
            embed = self._create_error_embed(
                "Invalid Duration",
                "Please use a valid duration format (e.g., '1h', '30m', '7d')."
            )
            await ctx.send(embed=embed)
            return
        
        # Cap at 28 days (Discord's limit)
        if td.days > 28:
            td = timedelta(days=28)
        
        try:
            await member.timeout(td, reason=reason)
            
            embed = self._create_success_embed(
                "Timeout Executed",
                f"**User:** {member.mention}\n"
                f"**Duration:** {format_duration(td)}\n"
                f"**Reason:** {reason}"
            )
            await ctx.send(embed=embed)
        
        except discord.Forbidden:
            embed = self._create_error_embed(
                "Permission Error",
                "I lack the necessary permissions to timeout this user."
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = self._create_error_embed(
                "Timeout Failed",
                f"An error occurred: {str(e)}"
            )
            await ctx.send(embed=embed)
    
    # ========================================================================
    # Purge Command
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="purge", aliases=["prune"])
    @commands.has_permissions(manage_messages=True)
    async def purge(self, ctx: commands.Context, target: str = "all", amount: int = 10):
        """
        Bulk delete messages from the channel.
        
        Syntax: 
        - .purge [amount] -> Delete all messages
        - .purge humans [amount] -> Delete only human messages
        - .purge bots [amount] -> Delete only bot messages
        
        Args:
            ctx: The command context.
            target: Type of messages to delete (all, humans, bots).
            amount: Number of messages to delete.
        """
        # Handle different argument patterns
        if isinstance(target, int):
            # Called as .purge [amount]
            amount = target
            target = "all"
        elif target.lower() not in ["all", "humans", "bots"]:
            try:
                amount = int(target)
                target = "all"
            except ValueError:
                embed = self._create_error_embed(
                    "Invalid Arguments",
                    "Usage: `.purge [amount]`, `.purge humans [amount]`, or `.purge bots [amount]`"
                )
                await ctx.send(embed=embed)
                return
        
        # Validate amount
        if amount < 1 or amount > 1000:
            embed = self._create_error_embed(
                "Invalid Amount",
                "Please specify a number between 1 and 1000."
            )
            await ctx.send(embed=embed)
            return
        
        # Define filter function
        def check(msg: discord.Message) -> bool:
            if target.lower() == "humans":
                return not msg.author.bot
            elif target.lower() == "bots":
                return msg.author.bot
            return True
        
        try:
            deleted = await ctx.channel.purge(limit=amount, check=check)
            
            embed = self._create_success_embed(
                "Messages Purged",
                f"**Deleted:** {len(deleted)} message(s)\n**Type:** {target.capitalize()}"
            )
            await ctx.send(embed=embed, delete_after=5)
        
        except discord.Forbidden:
            embed = self._create_error_embed(
                "Permission Error",
                "I lack the necessary permissions to purge messages."
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = self._create_error_embed(
                "Purge Failed",
                f"An error occurred: {str(e)}"
            )
            await ctx.send(embed=embed)
    
    # ========================================================================
    # Add Emoji Command
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="addemoji")
    @commands.has_permissions(manage_emojis=True)
    async def addemoji(self, ctx: commands.Context, url: str = None):
        """
        Add a custom emoji to the server.
        
        Syntax: .addemoji (attachment/url)
        
        Args:
            ctx: The command context.
            url: Optional image URL.
        """
        image_data = None
        
        # Check for attachment
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            try:
                image_data = await attachment.read()
            except Exception as e:
                embed = self._create_error_embed(
                    "Attachment Error",
                    f"Failed to read attachment: {str(e)}"
                )
                await ctx.send(embed=embed)
                return
        
        # Check for URL
        elif url:
            try:
                async with self.bot.session.get(url) as resp:
                    if resp.status != 200:
                        raise ValueError(f"HTTP {resp.status}")
                    image_data = await resp.read()
            except Exception as e:
                embed = self._create_error_embed(
                    "URL Error",
                    f"Failed to fetch image from URL: {str(e)}"
                )
                await ctx.send(embed=embed)
                return
        
        else:
            embed = self._create_error_embed(
                "Missing Image",
                "Please provide an image attachment or URL."
            )
            await ctx.send(embed=embed)
            return
        
        # Attempt to add emoji
        try:
            # Extract emoji name from URL or default
            if url:
                emoji_name = urlparse(url).path.split('/')[-1].split('.')[0]
            else:
                emoji_name = ctx.message.attachments[0].filename.split('.')[0]
            
            emoji_name = emoji_name[:32]  # Discord limit
            
            emoji = await ctx.guild.create_custom_emoji(name=emoji_name, image=image_data)
            
            embed = self._create_success_embed(
                "Emoji Added",
                f"Added emoji: {emoji}"
            )
            await ctx.send(embed=embed)
        
        except discord.Forbidden:
            embed = self._create_error_embed(
                "Permission Error",
                "I lack the necessary permissions to add emojis."
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = self._create_error_embed(
                "Emoji Creation Failed",
                f"An error occurred: {str(e)}"
            )
            await ctx.send(embed=embed)
    
    # ========================================================================
    # Add Sticker Command
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="addsticker")
    @commands.has_permissions(manage_emojis_and_stickers=True)
    async def addsticker(self, ctx: commands.Context, url: str = None):
        """
        Add a custom sticker to the server.
        
        Syntax: .addsticker (attachment/url)
        
        Args:
            ctx: The command context.
            url: Optional image URL.
        """
        image_data = None
        
        # Check for attachment
        if ctx.message.attachments:
            attachment = ctx.message.attachments[0]
            try:
                image_data = await attachment.read()
            except Exception as e:
                embed = self._create_error_embed(
                    "Attachment Error",
                    f"Failed to read attachment: {str(e)}"
                )
                await ctx.send(embed=embed)
                return
        
        # Check for URL
        elif url:
            try:
                async with self.bot.session.get(url) as resp:
                    if resp.status != 200:
                        raise ValueError(f"HTTP {resp.status}")
                    image_data = await resp.read()
            except Exception as e:
                embed = self._create_error_embed(
                    "URL Error",
                    f"Failed to fetch image from URL: {str(e)}"
                )
                await ctx.send(embed=embed)
                return
        
        else:
            embed = self._create_error_embed(
                "Missing Image",
                "Please provide an image attachment or URL."
            )
            await ctx.send(embed=embed)
            return
        
        # Attempt to add sticker
        try:
            # Extract sticker name from URL or default
            if url:
                sticker_name = urlparse(url).path.split('/')[-1].split('.')[0]
            else:
                sticker_name = ctx.message.attachments[0].filename.split('.')[0]
            
            sticker_name = sticker_name[:32]  # Discord limit
            
            sticker = await ctx.guild.create_sticker(
                name=sticker_name,
                description=f"Added by {ctx.author}",
                emoji="🎨",
                file=discord.File(io.BytesIO(image_data), filename="sticker.png")
            )
            
            embed = self._create_success_embed(
                "Sticker Added",
                f"Added sticker: {sticker.name}"
            )
            await ctx.send(embed=embed)
        
        except discord.Forbidden:
            embed = self._create_error_embed(
                "Permission Error",
                "I lack the necessary permissions to add stickers."
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = self._create_error_embed(
                "Sticker Creation Failed",
                f"An error occurred: {str(e)}"
            )
            await ctx.send(embed=embed)
    
    # ========================================================================
    # Unban Command
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="unban")
    @commands.has_permissions(ban_members=True)
    async def unban(self, ctx: commands.Context, user: discord.User, *, reason: str = "No reason provided"):
        """
        Revoke a ban on a user.
        
        Syntax: .unban [user] (reason)
        
        Args:
            ctx: The command context.
            user: The user to unban.
            reason: The reason for unbanning.
        """
        try:
            await ctx.guild.unban(user, reason=reason)
            
            embed = self._create_success_embed(
                "Unban Executed",
                f"**User:** {user.mention}\n**Reason:** {reason}"
            )
            await ctx.send(embed=embed)
        
        except discord.NotFound:
            embed = self._create_error_embed(
                "User Not Banned",
                f"{user.mention} is not currently banned."
            )
            await ctx.send(embed=embed)
        except discord.Forbidden:
            embed = self._create_error_embed(
                "Permission Error",
                "I lack the necessary permissions to unban this user."
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = self._create_error_embed(
                "Unban Failed",
                f"An error occurred: {str(e)}"
            )
            await ctx.send(embed=embed)
    
    # ========================================================================
    # Unmute Command
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="unmute", aliases=["untimeout"])
    @commands.has_permissions(moderate_members=True)
    async def unmute(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        """
        Remove an active timeout from a member.
        
        Syntax: .unmute [user] (reason)
        
        Args:
            ctx: The command context.
            member: The member to unmute.
            reason: The reason for removing the timeout.
        """
        if member.timed_out_until is None or member.timed_out_until < discord.utils.utcnow():
            embed = self._create_error_embed(
                "Not Timed Out",
                f"{member.mention} is not currently timed out."
            )
            await ctx.send(embed=embed)
            return
        
        try:
            await member.timeout(None, reason=reason)
            
            embed = self._create_success_embed(
                "Timeout Removed",
                f"**User:** {member.mention}\n**Reason:** {reason}"
            )
            await ctx.send(embed=embed)
        
        except discord.Forbidden:
            embed = self._create_error_embed(
                "Permission Error",
                "I lack the necessary permissions to remove the timeout."
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = self._create_error_embed(
                "Unmute Failed",
                f"An error occurred: {str(e)}"
            )
            await ctx.send(embed=embed)
    
    # ========================================================================
    # Warning System
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="warn")
    @commands.has_permissions(moderate_members=True)
    async def warn(self, ctx: commands.Context, member: discord.Member, *, reason: str = "No reason provided"):
        """
        Log a warning against a member.
        
        Syntax: .warn [user] (reason)
        
        Args:
            ctx: The command context.
            member: The member to warn.
            reason: The reason for the warning.
        """
        async with self._get_db() as db:
            await db.execute(
                """
                INSERT INTO warnings (guild_id, user_id, moderator_id, reason, created_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (ctx.guild.id, member.id, ctx.author.id, reason)
            )
            await db.commit()
            
            # Get total warning count
            cursor = await db.execute(
                "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, member.id)
            )
            warn_count = (await cursor.fetchone())[0]
        
        embed = self._create_success_embed(
            "Warning Logged",
            f"**User:** {member.mention}\n"
            f"**Reason:** {reason}\n"
            f"**Total Warnings:** {warn_count}"
        )
        await ctx.send(embed=embed)
    
    @commands.command(name="unwarn")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(moderate_members=True)
    async def unwarn(self, ctx: commands.Context, member: discord.Member, warn_index: int = 0):
        """
        Remove a warning from a member.
        
        Syntax: .unwarn [user] (warn_index)
        
        Args:
            ctx: The command context.
            member: The member to remove a warning from.
            warn_index: Index of warning to remove (0 = most recent).
        """
        async with self._get_db() as db:
            # Get all warnings for this user
            cursor = await db.execute(
                """SELECT warning_id, reason FROM warnings 
                   WHERE guild_id = ? AND user_id = ? 
                   ORDER BY created_at DESC""",
                (ctx.guild.id, member.id)
            )
            warnings = await cursor.fetchall()
            
            if not warnings:
                embed = self._create_error_embed(
                    "No Warnings",
                    f"{member.mention} has no warnings."
                )
                await ctx.send(embed=embed)
                return
            
            # Check if index is valid
            if warn_index >= len(warnings):
                embed = self._create_error_embed(
                    "Invalid Index",
                    f"Warning index out of range. {member.mention} has {len(warnings)} warning(s)."
                )
                await ctx.send(embed=embed)
                return
            
            # Get the warning to remove
            warning_id, removed_reason = warnings[warn_index]
            
            # Delete the warning
            await db.execute(
                "DELETE FROM warnings WHERE warning_id = ?",
                (warning_id,)
            )
            await db.commit()
            
            # Get remaining count
            cursor = await db.execute(
                "SELECT COUNT(*) FROM warnings WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, member.id)
            )
            remaining = (await cursor.fetchone())[0]
        
        embed = self._create_success_embed(
            "Warning Removed",
            f"**User:** {member.mention}\n"
            f"**Removed Reason:** {removed_reason}\n"
            f"**Remaining Warnings:** {remaining}"
        )
        await ctx.send(embed=embed)
    
    # ========================================================================
    # Lock/Unlock Commands
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="lock")
    @commands.has_permissions(manage_channels=True)
    async def lock(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """
        Lock a channel by disabling @everyone send_messages permission.
        
        Syntax: .lock (channel)
        
        Args:
            ctx: The command context.
            channel: The channel to lock (defaults to current channel).
        """
        channel = channel or ctx.channel
        
        try:
            await channel.set_permissions(
                ctx.guild.default_role,
                send_messages=False
            )
            
            embed = self._create_success_embed(
                "Channel Locked",
                f"**Channel:** {channel.mention}"
            )
            await ctx.send(embed=embed)
        
        except discord.Forbidden:
            embed = self._create_error_embed(
                "Permission Error",
                "I lack the necessary permissions to lock this channel."
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = self._create_error_embed(
                "Lock Failed",
                f"An error occurred: {str(e)}"
            )
            await ctx.send(embed=embed)
    
    @commands.command(name="unlock")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_channels=True)
    async def unlock(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """
        Unlock a channel by restoring @everyone send_messages permission.
        
        Syntax: .unlock (channel)
        
        Args:
            ctx: The command context.
            channel: The channel to unlock (defaults to current channel).
        """
        channel = channel or ctx.channel
        
        try:
            await channel.set_permissions(
                ctx.guild.default_role,
                send_messages=True
            )
            
            embed = self._create_success_embed(
                "Channel Unlocked",
                f"**Channel:** {channel.mention}"
            )
            await ctx.send(embed=embed)
        
        except discord.Forbidden:
            embed = self._create_error_embed(
                "Permission Error",
                "I lack the necessary permissions to unlock this channel."
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = self._create_error_embed(
                "Unlock Failed",
                f"An error occurred: {str(e)}"
            )
            await ctx.send(embed=embed)
    
    # ========================================================================
    # Lockdown Commands
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="lockdown", aliases=["lockall"])
    @commands.has_permissions(manage_channels=True)
    async def lockdown(self, ctx: commands.Context):
        """
        Lock down all text channels in the server.
        
        Syntax: .lockdown
        
        Args:
            ctx: The command context.
        """
        # Create confirmation embed
        embed = self._create_warning_embed(
            "Server Lockdown Confirmation",
            "⚠️ This action will **disable messaging in all text channels**.\n\n"
            "Click **Confirm** to proceed or **Cancel** to abort."
        )
        
        view = ConfirmationView(ctx.author.id)
        msg = await ctx.send(embed=embed, view=view)
        
        # Wait for confirmation
        await view.wait()
        
        if not view.confirmed:
            embed = self._create_error_embed("Lockdown Cancelled", "The lockdown was cancelled.")
            await msg.edit(embed=embed, view=None)
            return
        
        # Perform lockdown
        locked_channels = []
        failed_channels = []
        
        for channel in ctx.guild.text_channels:
            try:
                await channel.set_permissions(
                    ctx.guild.default_role,
                    send_messages=False
                )
                locked_channels.append(channel.id)
            except Exception:
                failed_channels.append(channel.name)
        
        # Persist locked channels to DB
        async with self._get_db() as db:
            for ch_id in locked_channels:
                await db.execute(
                    "INSERT OR IGNORE INTO lockdown_channels (guild_id, channel_id) VALUES (?, ?)",
                    (ctx.guild.id, ch_id)
                )
            await db.commit()
        
        description = f"**Locked Channels:** {len(locked_channels)}"
        if failed_channels:
            description += f"\n**Failed:** {', '.join(failed_channels)}"
        
        embed = self._create_success_embed(
            "Server Locked Down",
            description
        )
        await msg.edit(embed=embed, view=None)
    
    @commands.command(name="unlockdown", aliases=["unlockall"])
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_channels=True)
    async def unlockdown(self, ctx: commands.Context):
        """
        Restore normal messaging permissions to all channels locked by lockdown.
        
        Syntax: .unlockdown
        
        Args:
            ctx: The command context.
        """
        async with self._get_db() as db:
            cursor = await db.execute("SELECT channel_id FROM lockdown_channels WHERE guild_id = ?", (ctx.guild.id,))
            rows = await cursor.fetchall()
            locked_channels = [r[0] for r in rows]
            
            if not locked_channels:
                embed = self._create_error_embed(
                    "No Lockdown Active",
                    "There is no active lockdown to reverse."
                )
                await ctx.send(embed=embed)
                return

        unlocked = []
        failed = []
        
        for channel_id in locked_channels:
            channel = ctx.guild.get_channel(channel_id)
            if not channel:
                continue
            
            try:
                await channel.set_permissions(
                    ctx.guild.default_role,
                    send_messages=True
                )
                unlocked.append(channel.name)
            except Exception:
                failed.append(channel.name)
        
        # Clear lockdown tracking in DB
        async with self._get_db() as db:
            await db.execute("DELETE FROM lockdown_channels WHERE guild_id = ?", (ctx.guild.id,))
            await db.commit()
        
        description = f"**Unlocked Channels:** {len(unlocked)}"
        if failed:
            description += f"\n**Failed:** {', '.join(failed)}"
        
        embed = self._create_success_embed(
            "Lockdown Lifted",
            description
        )
        await ctx.send(embed=embed)
    
    # ========================================================================
    # Snipe Commands (New Advanced Suite)
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.group(name="snipe", invoke_without_command=True)
    @commands.guild_only()
    async def snipe_group(self, ctx: commands.Context):
        """
        Advanced snipe utility for deleted messages, edited messages, and removed reactions.
        
        Use `.snipe <subcommand>` for more options.
        """
        if ctx.invoked_subcommand is None:
            # Default to showing deleted message if no subcommand
            await self.snipe_deleted(ctx)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @snipe_group.command(name="deleted")
    async def snipe_deleted(self, ctx: commands.Context):
        """
        Displays the most recently deleted message in the current channel.
        """
        if self._is_protected_channel(ctx.guild.id, ctx.channel.id):
            embed = self._create_error_embed(
                "Channel Protected",
                "This channel is protected from sniping."
            )
            await ctx.send(embed=embed)
            return

        sniped_message = self._sniped_cache.get(ctx.channel.id)
        
        if not sniped_message:
            embed = self._create_info_embed(
                "No Deleted Messages",
                "No messages have been deleted recently in this channel."
            )
            await ctx.send(embed=embed)
            return
        
        if self._is_protected_user(ctx.guild.id, sniped_message["author_id"]):
            embed = self._create_error_embed(
                "User Protected",
                "The author of the last deleted message is protected from sniping."
            )
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="🔍 Sniped Message",
            description=sniped_message["content"] or "*[No content]*",
            color=discord.Color.blurple(),
            timestamp=sniped_message["deleted_at"]
        )
        embed.set_author(
            name=sniped_message["author_name"],
            icon_url=sniped_message["author_avatar"] or discord.Embed.Empty
        )
        embed.set_footer(text=f"Message ID: {sniped_message['message_id']}")
        
        await ctx.send(embed=embed)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @snipe_group.command(name="edited", aliases=["se"])
    async def snipe_edited(self, ctx: commands.Context):
        """
        Displays the most recently edited message in the current channel.
        """
        if self._is_protected_channel(ctx.guild.id, ctx.channel.id):
            embed = self._create_error_embed(
                "Channel Protected",
                "This channel is protected from sniping."
            )
            await ctx.send(embed=embed)
            return

        edited_message = self._edited_cache.get(ctx.channel.id)
        
        if not edited_message:
            embed = self._create_info_embed(
                "No Edited Messages",
                "No messages have been edited recently in this channel."
            )
            await ctx.send(embed=embed)
            return
        
        if self._is_protected_user(ctx.guild.id, edited_message["author_id"]):
            embed = self._create_error_embed(
                "User Protected",
                "The author of the last edited message is protected from sniping."
            )
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="📝 Sniped Edited Message",
            color=discord.Color.orange(),
            timestamp=edited_message["edited_at"]
        )
        embed.set_author(
            name=edited_message["author_name"],
            icon_url=edited_message["author_avatar"] or discord.Embed.Empty
        )
        embed.add_field(name="Before", value=edited_message["before_content"] or "*[No content]*", inline=False)
        embed.add_field(name="After", value=edited_message["after_content"] or "*[No content]*", inline=False)
        embed.set_footer(text=f"Message ID: {edited_message['message_id']}")
        
        await ctx.send(embed=embed)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @snipe_group.command(name="reaction", aliases=["sr"])
    async def snipe_reaction(self, ctx: commands.Context):
        """
        Displays the most recently removed reaction in the current channel.
        """
        if self._is_protected_channel(ctx.guild.id, ctx.channel.id):
            embed = self._create_error_embed(
                "Channel Protected",
                "This channel is protected from sniping."
            )
            await ctx.send(embed=embed)
            return

        removed_reaction = self._reaction_cache.get(ctx.channel.id)
        
        if not removed_reaction:
            embed = self._create_info_embed(
                "No Removed Reactions",
                "No reactions have been removed recently in this channel."
            )
            await ctx.send(embed=embed)
            return
        
        if self._is_protected_user(ctx.guild.id, removed_reaction["user_id"]):
            embed = self._create_error_embed(
                "User Protected",
                "The user who removed the last reaction is protected from sniping."
            )
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="💔 Sniped Reaction",
            description=(
                f"**Emoji:** {removed_reaction['emoji']}\n"
                f"**Removed by:** {removed_reaction['user_name']}\n"
                f"**Message:** [Jump to Message]({removed_reaction['message_jump_url']})"
            ),
            color=discord.Color.red(),
            timestamp=removed_reaction["removed_at"]
        )
        embed.set_author(
            name=removed_reaction["user_name"],
            icon_url=removed_reaction["user_avatar"] or discord.Embed.Empty
        )
        embed.set_footer(text=f"Message ID: {removed_reaction['message_id']}")
        
        await ctx.send(embed=embed)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @snipe_group.group(name="channels")
    @commands.has_permissions(manage_messages=True)
    async def snipe_channels(self, ctx: commands.Context):
        """Manage channels protected from snipe."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @snipe_channels.command(name="protect")
    @commands.has_permissions(manage_messages=True)
    async def snipe_channels_protect(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Add a channel to the snipe protection list."""
        channel = channel or ctx.channel
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO snipe_protected_channels (guild_id, channel_id) VALUES (?, ?)",
                (ctx.guild.id, channel.id)
            )
            await db.commit()
        await self._refresh_protection_cache(ctx.guild.id)
        embed = self._create_success_embed("Channel Protected", f"{channel.mention} is now protected from sniping.")
        await ctx.send(embed=embed)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @snipe_channels.command(name="unprotect")
    @commands.has_permissions(manage_messages=True)
    async def snipe_channels_unprotect(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Remove a channel from the snipe protection list."""
        channel = channel or ctx.channel
        async with self._get_db() as db:
            await db.execute(
                "DELETE FROM snipe_protected_channels WHERE guild_id = ? AND channel_id = ?",
                (ctx.guild.id, channel.id)
            )
            await db.commit()
        await self._refresh_protection_cache(ctx.guild.id)
        embed = self._create_success_embed("Channel Unprotected", f"{channel.mention} is no longer protected from sniping.")
        await ctx.send(embed=embed)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @snipe_channels.command(name="list")
    async def snipe_channels_list(self, ctx: commands.Context):
        """List all channels protected from sniping."""
        protected_channels = self._protected_cache.get(ctx.guild.id, {}).get("channels", set())
        if not protected_channels:
            embed = self._create_info_embed("No Protected Channels", "No channels are currently protected from sniping.")
            await ctx.send(embed=embed)
            return
        
        channel_mentions = [ctx.guild.get_channel(ch_id).mention for ch_id in protected_channels if ctx.guild.get_channel(ch_id)]
        embed = self._create_info_embed(
            "Protected Channels",
            "\n".join(channel_mentions) or "No valid channels found."
        )
        await ctx.send(embed=embed)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @snipe_group.group(name="user")
    @commands.has_permissions(manage_messages=True)
    async def snipe_user(self, ctx: commands.Context):
        """Manage users protected from snipe."""
        if ctx.invoked_subcommand is None:
            await ctx.send_help(ctx.command)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @snipe_user.command(name="protect")
    @commands.has_permissions(manage_messages=True)
    async def snipe_user_protect(self, ctx: commands.Context, user: discord.User):
        """Add a user to the snipe protection list."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO snipe_protected_users (guild_id, user_id) VALUES (?, ?)",
                (ctx.guild.id, user.id)
            )
            await db.commit()
        await self._refresh_protection_cache(ctx.guild.id)
        embed = self._create_success_embed("User Protected", f"{user.mention} is now protected from sniping.")
        await ctx.send(embed=embed)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @snipe_user.command(name="unprotect")
    @commands.has_permissions(manage_messages=True)
    async def snipe_user_unprotect(self, ctx: commands.Context, user: discord.User):
        """Remove a user from the snipe protection list."""
        async with self._get_db() as db:
            await db.execute(
                "DELETE FROM snipe_protected_users WHERE guild_id = ? AND user_id = ?",
                (ctx.guild.id, user.id)
            )
            await db.commit()
        await self._refresh_protection_cache(ctx.guild.id)
        embed = self._create_success_embed("User Unprotected", f"{user.mention} is no longer protected from sniping.")
        await ctx.send(embed=embed)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @snipe_user.command(name="list")
    async def snipe_user_list(self, ctx: commands.Context):
        """List all users protected from sniping."""
        protected_users = self._protected_cache.get(ctx.guild.id, {}).get("users", set())
        if not protected_users:
            embed = self._create_info_embed("No Protected Users", "No users are currently protected from sniping.")
            await ctx.send(embed=embed)
            return
        
        user_mentions = []
        for user_id in protected_users:
            user = self.bot.get_user(user_id) or await self.bot.fetch_user(user_id)
            user_mentions.append(user.mention if user else f"Unknown User ({user_id})")

        embed = self._create_info_embed(
            "Protected Users",
            "\n".join(user_mentions) or "No valid users found."
        )
        await ctx.send(embed=embed)

    # ========================================================================
    # Clear Snipe Command
    # ========================================================================
    
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.command(name="clearsnipe", aliases=["cs"])
    async def clearsnipe(self, ctx: commands.Context):
        """
        Clear the in-memory snipe caches for the current channel.
        
        Syntax: .clearsnipe
        
        Args:
            ctx: The command context.
        """
        cleared_count = 0
        if ctx.channel.id in self._sniped_cache:
            del self._sniped_cache[ctx.channel.id]
            cleared_count += 1
        if ctx.channel.id in self._edited_cache:
            del self._edited_cache[ctx.channel.id]
            cleared_count += 1
        if ctx.channel.id in self._reaction_cache:
            del self._reaction_cache[ctx.channel.id]
            cleared_count += 1

        if cleared_count > 0:
            embed = self._create_success_embed(
                "Snipe Cache Cleared",
                f"Cleared {cleared_count} snipe cache(s) for {ctx.channel.mention}."
            )
        else:
            embed = self._create_info_embed(
                "No Cache",
                f"There is no snipe cache data for {ctx.channel.mention}."
            )
        await ctx.send(embed=embed)

    # ========================================================================
    # Event Listeners for Snipe Caching
    # ========================================================================

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """Initialize protection cache when joining a new guild."""
        await self._refresh_protection_cache(guild.id)
    
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """
        Cache deleted messages for the .snipe command, respecting protection.
        """
        if not message.guild or message.author.bot:
            return
        
        if self._is_protected_channel(message.guild.id, message.channel.id) or \
           self._is_protected_user(message.guild.id, message.author.id):
            return
        
        self._sniped_cache[message.channel.id] = {
            "message_id": message.id,
            "content": message.content,
            "author_id": message.author.id,
            "author_name": str(message.author),
            "author_avatar": message.author.avatar.url if message.author.avatar else None,
            "deleted_at": discord.utils.utcnow()
        }

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """
        Cache edited messages for the .snipe edited command, respecting protection.
        """
        if before.author.bot or not before.guild or before.content == after.content:
            return
        
        if self._is_protected_channel(before.guild.id, before.channel.id) or \
           self._is_protected_user(before.guild.id, before.author.id):
            return
        
        self._edited_cache[before.channel.id] = {
            "message_id": before.id,
            "before_content": before.content,
            "after_content": after.content,
            "author_id": before.author.id,
            "author_name": str(before.author),
            "author_avatar": before.author.avatar.url if before.author.avatar else None,
            "edited_at": discord.utils.utcnow()
        }

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """
        Cache removed reactions for the .snipe reaction command, respecting protection.
        """
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        
        channel = guild.get_channel(payload.channel_id)
        if not channel:
            return
        
        user = guild.get_member(payload.user_id) or await self.bot.fetch_user(payload.user_id)
        if not user or user.bot:
            return
        
        if self._is_protected_channel(guild.id, channel.id) or \
           self._is_protected_user(guild.id, user.id):
            return
        
        # Fetch the message to get its jump_url
        try:
            message = await channel.fetch_message(payload.message_id)
            jump_url = message.jump_url
        except discord.NotFound:
            jump_url = "Message not found"
        
        self._reaction_cache[payload.channel_id] = {
            "message_id": payload.message_id,
            "emoji": str(payload.emoji),
            "user_id": user.id,
            "user_name": str(user),
            "user_avatar": user.avatar.url if user.avatar else None,
            "removed_at": discord.utils.utcnow(),
            "message_jump_url": jump_url
        }

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"This command is on cooldown. Try again in {error.retry_after:.2f}s.", ephemeral=True)
            return
        raise error

# ============================================================================
# Setup Function
# ============================================================================

async def setup(bot: commands.Bot):
    """
    Load the Moderation cog into the bot.
    
    Args:
        bot: The Discord bot instance.
    """
    await bot.add_cog(Moderation(bot))
