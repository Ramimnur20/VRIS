

import discord
from discord.ext import commands
from typing import Optional, Dict, Any, Tuple
import aiosqlite
from pathlib import Path
import logging

logger = logging.getLogger("VOTOX")


class Starboard(commands.Cog):
    """
    Manages a starboard system to feature popular messages.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        self._starboard_settings_cache: Dict[int, Dict[str, Any]] = {}

    def _get_db(self) -> aiosqlite.Connection:
        """Returns an aiosqlite connection to the database."""
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initializes database tables and loads settings into cache when the cog is loaded."""
        async with self._get_db() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS starboard_settings (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    emoji TEXT DEFAULT '⭐',
                    threshold INTEGER DEFAULT 3,
                    enabled INTEGER DEFAULT 0
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS starboard_messages (
                    guild_id INTEGER NOT NULL,
                    original_message_id INTEGER PRIMARY KEY,
                    starboard_message_id INTEGER
                )
            ''')
            await db.commit()
        await self._load_settings_cache()

    async def _load_settings_cache(self):
        """Loads all starboard settings into the in-memory cache."""
        self._starboard_settings_cache.clear()
        async with self._get_db() as db:
            cursor = await db.execute("SELECT guild_id, channel_id, emoji, threshold, enabled FROM starboard_settings")
            for guild_id, channel_id, emoji, threshold, enabled in await cursor.fetchall():
                self._starboard_settings_cache[guild_id] = {
                    "channel_id": channel_id,
                    "emoji": emoji,
                    "threshold": threshold,
                    "enabled": bool(enabled)
                }
        logger.debug(f"Loaded {len(self._starboard_settings_cache)} starboard settings into cache.")

    async def _get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """Retrieves starboard settings for a guild, from cache or DB."""
        if guild_id in self._starboard_settings_cache:
            return self._starboard_settings_cache[guild_id]

        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT channel_id, emoji, threshold, enabled FROM starboard_settings WHERE guild_id = ?",
                (guild_id,)
            )
            row = await cursor.fetchone()
            if row:
                settings = {
                    "channel_id": row[0],
                    "emoji": row[1],
                    "threshold": row[2],
                    "enabled": bool(row[3])
                }
                self._starboard_settings_cache[guild_id] = settings
                return settings
            # Default settings if not found
            return {"channel_id": None, "emoji": "⭐", "threshold": 3, "enabled": False}

    async def _update_guild_setting(self, guild_id: int, key: str, value: Any):
        """Updates a specific starboard setting for a guild in the DB and cache."""
        settings = await self._get_guild_settings(guild_id)
        settings[key] = value
        if key == "enabled":
            value = 1 if value else 0
        
        async with self._get_db() as db:
            await db.execute(
                f"INSERT OR REPLACE INTO starboard_settings (guild_id, channel_id, emoji, threshold, enabled) VALUES (?, ?, ?, ?, ?)",
                (guild_id, settings["channel_id"], settings["emoji"], settings["threshold"], settings["enabled"])
            )
            await db.commit()
        self._starboard_settings_cache[guild_id] = settings # Update cache

    # ========================= HELPER METHODS =========================

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.gold()) -> discord.Embed:
        """Creates a styled Discord embed."""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="VOTOX Starboard System", icon_url=self.bot.user.display_avatar.url)
        return embed

    def _create_success_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"✅ {title}", description, discord.Color.green())

    def _create_error_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"❌ {title}", description, discord.Color.red())

    def _create_info_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"ℹ️ {title}", description, discord.Color.blurple())

    async def _get_starboard_message_id(self, guild_id: int, original_message_id: int) -> Optional[int]:
        """Retrieves the starboard message ID for a given original message ID."""
        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT starboard_message_id FROM starboard_messages WHERE guild_id = ? AND original_message_id = ?",
                (guild_id, original_message_id)
            )
            row = await cursor.fetchone()
            return row[0] if row else None

    async def _add_starboard_message(self, guild_id: int, original_message_id: int, starboard_message_id: int):
        """Adds a new entry to the starboard_messages table."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT INTO starboard_messages (guild_id, original_message_id, starboard_message_id) VALUES (?, ?, ?)",
                (guild_id, original_message_id, starboard_message_id)
            )
            await db.commit()

    async def _remove_starboard_message(self, guild_id: int, original_message_id: int):
        """Removes an entry from the starboard_messages table."""
        async with self._get_db() as db:
            await db.execute(
                "DELETE FROM starboard_messages WHERE guild_id = ? AND original_message_id = ?",
                (guild_id, original_message_id)
            )
            await db.commit()

    def _build_starboard_embed(self, message: discord.Message, reaction_count: int, emoji: str) -> discord.Embed:
        """Constructs the embed for the starboard channel."""
        embed = discord.Embed(
            color=discord.Color.gold(),
            description=message.content,
            timestamp=message.created_at
        )
        embed.set_author(name=message.author.display_name, icon_url=message.author.display_avatar.url)
        embed.set_footer(text=f"{emoji} {reaction_count} | ID: {message.id}")

        # Handle attachments
        if message.attachments:
            first_attachment = message.attachments[0]
            if first_attachment.content_type and first_attachment.content_type.startswith('image'):
                embed.set_image(url=first_attachment.url)
            elif first_attachment.content_type and first_attachment.content_type.startswith('video'):
                embed.add_field(name="Video", value=f"[Click to view video]({first_attachment.url})", inline=False)
            else:
                embed.add_field(name="Attachment", value=f"[Click to download {first_attachment.filename}]({first_attachment.url})", inline=False)
        
        # Handle embeds (e.g., from links, if no attachments)
        elif message.embeds:
            first_embed = message.embeds[0]
            if first_embed.image:
                embed.set_image(url=first_embed.image.url)
            elif first_embed.thumbnail:
                embed.set_thumbnail(url=first_embed.thumbnail.url)

        embed.add_field(name="Original Message", value=f"[Jump to Message]({message.jump_url})", inline=False)
        return embed

    # ========================= EVENT LISTENERS =========================

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        """Handles reactions being added to messages."""
        if payload.guild_id is None or payload.member.bot:
            return

        settings = await self._get_guild_settings(payload.guild_id)
        if not settings["enabled"] or settings["channel_id"] is None:
            return

        if str(payload.emoji) != settings["emoji"]:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        starboard_channel = guild.get_channel(settings["channel_id"])
        if not starboard_channel:
            logger.warning(f"Starboard channel not found for guild {guild.id}. Disabling starboard.")
            await self._update_guild_setting(guild.id, "enabled", False)
            return

        try:
            channel = guild.get_channel(payload.channel_id)
            if not channel:
                return
            original_message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            return
        except discord.Forbidden:
            logger.warning(f"Bot lacks permissions to fetch message {payload.message_id} in channel {payload.channel_id} in guild {guild.id}.")
            return

        # Prevent self-starring
        if original_message.author.id == payload.member.id:
            try:
                await original_message.remove_reaction(payload.emoji, payload.member)
            except discord.Forbidden:
                pass # Bot might not have permission to remove reactions
            return

        # Get current reaction count for the specific emoji
        reaction_count = 0
        for reaction in original_message.reactions:
            if str(reaction.emoji) == settings["emoji"]:
                reaction_count = reaction.count
                break

        if reaction_count >= settings["threshold"]:
            starboard_message_id = await self._get_starboard_message_id(guild.id, original_message.id)

            starboard_embed = self._build_starboard_embed(original_message, reaction_count, settings["emoji"])

            if starboard_message_id:
                # Update existing starboard message
                try:
                    starboard_message = await starboard_channel.fetch_message(starboard_message_id)
                    await starboard_message.edit(embed=starboard_embed)
                except discord.NotFound:
                    # Starboard message was deleted, re-post it
                    new_starboard_message = await starboard_channel.send(embed=starboard_embed)
                    await self._add_starboard_message(guild.id, original_message.id, new_starboard_message.id)
                except discord.Forbidden:
                    logger.warning(f"Bot lacks permissions to edit message {starboard_message_id} in starboard channel {starboard_channel.id}.")
            else:
                # Post new starboard message
                try:
                    new_starboard_message = await starboard_channel.send(embed=starboard_embed)
                    await self._add_starboard_message(guild.id, original_message.id, new_starboard_message.id)
                except discord.Forbidden:
                    logger.warning(f"Bot lacks permissions to send messages in starboard channel {starboard_channel.id}.")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        """Handles reactions being removed from messages."""
        if payload.guild_id is None:
            return

        settings = await self._get_guild_settings(payload.guild_id)
        if not settings["enabled"] or settings["channel_id"] is None:
            return

        if str(payload.emoji) != settings["emoji"]:
            return

        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return

        starboard_channel = guild.get_channel(settings["channel_id"])
        if not starboard_channel:
            return

        starboard_message_id = await self._get_starboard_message_id(guild.id, payload.message_id)
        if not starboard_message_id:
            return # Not a starboarded message

        try:
            channel = guild.get_channel(payload.channel_id)
            if not channel:
                return
            original_message = await channel.fetch_message(payload.message_id)
        except discord.NotFound:
            # Original message deleted, remove from starboard
            try:
                starboard_message = await starboard_channel.fetch_message(starboard_message_id)
                await starboard_message.delete()
            except discord.NotFound:
                pass
            await self._remove_starboard_message(guild.id, payload.message_id)
            return
        except discord.Forbidden:
            logger.warning(f"Bot lacks permissions to fetch message {payload.message_id} in channel {payload.channel_id} in guild {guild.id}.")
            return

        reaction_count = 0
        for reaction in original_message.reactions:
            if str(reaction.emoji) == settings["emoji"]:
                reaction_count = reaction.count
                break

        if reaction_count < settings["threshold"]:
            # Remove from starboard if below threshold
            try:
                starboard_message = await starboard_channel.fetch_message(starboard_message_id)
                await starboard_message.delete()
            except discord.NotFound:
                pass # Already deleted
            except discord.Forbidden:
                logger.warning(f"Bot lacks permissions to delete message {starboard_message_id} in starboard channel {starboard_channel.id}.")
            await self._remove_starboard_message(guild.id, original_message.id)
        else:
            # Update count on existing starboard message
            starboard_embed = self._build_starboard_embed(original_message, reaction_count, settings["emoji"])
            try:
                starboard_message = await starboard_channel.fetch_message(starboard_message_id)
                await starboard_message.edit(embed=starboard_embed)
            except discord.NotFound:
                await self._remove_starboard_message(guild.id, original_message.id) # Clean up DB
            except discord.Forbidden:
                logger.warning(f"Bot lacks permissions to edit message {starboard_message_id} in starboard channel {starboard_channel.id}.")

    # ========================= COMMANDS =========================

    @commands.group(name="starboard", invoke_without_command=True)
    @commands.guild_only()
    async def starboard_group(self, ctx: commands.Context):
        """
        Displays an elegant, Embed-formatted help menu showing all starboard setup and configuration options.
        """
        settings = await self._get_guild_settings(ctx.guild.id)
        starboard_channel = ctx.guild.get_channel(settings["channel_id"]) if settings["channel_id"] else "Not Set"

        embed = self._create_info_embed(
            "⭐ VOTOX Starboard System",
            "Feature popular messages in a dedicated channel!"
        )
        embed.add_field(name="Current Configuration", value=(
            f"**Enabled:** {'✅ Yes' if settings['enabled'] else '❌ No'}\n"
            f"**Channel:** {starboard_channel.mention if isinstance(starboard_channel, discord.TextChannel) else starboard_channel}\n"
            f"**Emoji:** {settings['emoji']}\n"
            f"**Threshold:** {settings['threshold']} reactions"
        ), inline=False)
        embed.add_field(name="Commands", value=(
            f"`{ctx.clean_prefix}starboard channel <#channel>`: Set the starboard channel.\n"
            f"`{ctx.clean_prefix}starboard emoji <emoji>`: Set the reaction emoji.\n"
            f"`{ctx.clean_prefix}starboard threshold <amount>`: Set the reaction threshold.\n"
            f"`{ctx.clean_prefix}starboard disable`: Disable the starboard."
        ), inline=False)
        embed.set_footer(text="All commands require 'Manage Guild' permissions.")
        await ctx.send(embed=embed)

    @starboard_group.command(name="channel")
    @commands.has_permissions(manage_guild=True)
    async def starboard_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """
        Designates the text channel where featured starboard messages will be posted.
        Setting a channel automatically enables the starboard.
        """
        try:
            # Check if bot has permissions to send messages in the channel
            if not channel.permissions_for(ctx.guild.me).send_messages:
                await ctx.send(embed=self._create_error_embed(
                    "Permission Denied",
                    f"I do not have permission to send messages in {channel.mention}. Please grant me 'Send Messages' permission."
                ))
                return

            await self._update_guild_setting(ctx.guild.id, "channel_id", channel.id)
            await self._update_guild_setting(ctx.guild.id, "enabled", True)
            await ctx.send(embed=self._create_success_embed(
                "Starboard Channel Set",
                f"Starboard channel set to {channel.mention}. Starboard is now **ENABLED**."
            ))
        except Exception as e:
            await ctx.send(embed=self._create_error_embed("Error", f"Failed to set starboard channel: {e}"))

    @starboard_group.command(name="emoji")
    @commands.has_permissions(manage_guild=True)
    async def starboard_emoji(self, ctx: commands.Context, emoji: str):
        """
        Customizes the reaction emoji needed to feature messages.
        """
        # Validate emoji: try to convert to a discord.Emoji or check if it's a unicode emoji
        try:
            # Attempt to convert to custom emoji
            discord_emoji = await commands.EmojiConverter().convert(ctx, emoji)
            emoji_str = str(discord_emoji)
        except commands.BadArgument:
            # Not a custom emoji, assume it's a unicode emoji
            # Basic check for common unicode emoji patterns
            if not (0x200d <= ord(emoji[0]) <= 0x10ffff): # Simple check for unicode range
                await ctx.send(embed=self._create_error_embed("Invalid Emoji", "Please provide a valid custom emoji or a single unicode emoji."))
                return
            emoji_str = emoji

        await self._update_guild_setting(ctx.guild.id, "emoji", emoji_str)
        await ctx.send(embed=self._create_success_embed(
            "Starboard Emoji Set",
            f"Starboard emoji set to {emoji_str}."
        ))

    @starboard_group.command(name="threshold")
    @commands.has_permissions(manage_guild=True)
    async def starboard_threshold(self, ctx: commands.Context, amount: int):
        """
        Sets the minimum number of reactions required for a message to get posted to the starboard.
        """
        if amount < 1:
            await ctx.send(embed=self._create_error_embed("Invalid Amount", "Threshold amount must be at least 1."))
            return

        await self._update_guild_setting(ctx.guild.id, "threshold", amount)
        await ctx.send(embed=self._create_success_embed(
            "Starboard Threshold Set",
            f"Starboard threshold set to {amount} reactions."
        ))

    @starboard_group.command(name="disable")
    @commands.has_permissions(manage_guild=True)
    async def starboard_disable(self, ctx: commands.Context):
        """
        Disables the starboard system for the current guild.
        """
        settings = await self._get_guild_settings(ctx.guild.id)
        if not settings["enabled"]:
            await ctx.send(embed=self._create_info_embed("Already Disabled", "Starboard is already disabled for this server."))
            return

        await self._update_guild_setting(ctx.guild.id, "enabled", False)
        await ctx.send(embed=self._create_success_embed(
            "Starboard Disabled",
            "Starboard system has been disabled for this server."
        ))


async def setup(bot: commands.Bot):
    """Loads the Starboard cog into the bot."""
    await bot.add_cog(Starboard(bot))