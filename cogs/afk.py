import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Optional, Dict, Any, List, Tuple
import aiosqlite
from pathlib import Path
from datetime import datetime, timedelta
import logging
import re

logger = logging.getLogger(__name__)

class AFK(commands.Cog):
    """
    Manages server-wide AFK (Away From Keyboard) statuses, offering customized presets,
    automated logging, and nickname-prefix management.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        self.afk_cache: Dict[int, Dict[int, Any]] = {} # {guild_id: {user_id: afk_data}}
        self.ignored_channels_cache: Dict[int, List[int]] = {} # {guild_id: [channel_id]}
        self.log_channels_cache: Dict[int, int] = {} # {guild_id: channel_id}
        self.guild_settings_cache: Dict[int, Dict[str, Any]] = {} # {guild_id: {setting_name: value}}
        self.afk_timeout_checker.start()

    def _get_db(self) -> aiosqlite.Connection:
        """Returns an aiosqlite connection to the database."""
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initializes database tables and loads initial cache data."""
        async with self._get_db() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS afk_users (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL PRIMARY KEY,
                    reason TEXT,
                    original_nick TEXT,
                    timestamp INTEGER NOT NULL
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS afk_ignored_channels (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, channel_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS afk_log_channels (
                    guild_id INTEGER NOT NULL PRIMARY KEY,
                    channel_id INTEGER NOT NULL
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS afk_presets (
                    user_id INTEGER NOT NULL,
                    preset_name TEXT NOT NULL,
                    preset_status TEXT,
                    PRIMARY KEY (user_id, preset_name)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS afk_settings (
                    guild_id INTEGER NOT NULL PRIMARY KEY,
                    timeout_minutes INTEGER DEFAULT 0
                )
            ''')
            await db.commit()
        await self._load_all_cache_data()

    async def cog_unload(self):
        """Cancels background tasks when the cog is unloaded."""
        self.afk_timeout_checker.cancel()

    async def _load_all_cache_data(self):
        """Loads all necessary data into in-memory caches from the database."""
        async with self._get_db() as db:
            # Load AFK users
            cursor = await db.execute("SELECT guild_id, user_id, reason, original_nick, timestamp FROM afk_users")
            rows = await cursor.fetchall()
            for guild_id, user_id, reason, original_nick, timestamp in rows:
                if guild_id not in self.afk_cache:
                    self.afk_cache[guild_id] = {}
                self.afk_cache[guild_id][user_id] = {
                    "reason": reason,
                    "original_nick": original_nick,
                    "timestamp": datetime.fromtimestamp(timestamp, tz=discord.utils.UTC)
                }

            # Load ignored channels
            cursor = await db.execute("SELECT guild_id, channel_id FROM afk_ignored_channels")
            rows = await cursor.fetchall()
            for guild_id, channel_id in rows:
                if guild_id not in self.ignored_channels_cache:
                    self.ignored_channels_cache[guild_id] = []
                self.ignored_channels_cache[guild_id].append(channel_id)
            
            # Load log channels
            cursor = await db.execute("SELECT guild_id, channel_id FROM afk_log_channels")
            rows = await cursor.fetchall()
            for guild_id, channel_id in rows:
                self.log_channels_cache[guild_id] = channel_id

            # Load guild settings
            cursor = await db.execute("SELECT guild_id, timeout_minutes FROM afk_settings")
            rows = await cursor.fetchall()
            for guild_id, timeout_minutes in rows:
                if guild_id not in self.guild_settings_cache:
                    self.guild_settings_cache[guild_id] = {}
                self.guild_settings_cache[guild_id]["timeout_minutes"] = timeout_minutes

    # ========================= HELPER METHODS =========================

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        """Creates a styled Discord embed."""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="VOTOX AFK System")
        return embed

    def _create_success_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"✅ {title}", description, discord.Color.green())

    def _create_error_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"❌ {title}", description, discord.Color.red())

    def _create_info_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"ℹ️ {title}", description, discord.Color.blurple())

    def _create_warning_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"⚠️ {title}", description, discord.Color.gold())

    def _format_duration(self, seconds: int) -> str:
        """Formats seconds into a human-readable duration string."""
        if seconds <= 0:
            return "0 seconds"
        
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        parts = []
        if days:
            parts.append(f"{days} day{'s' if days != 1 else ''}")
        if hours:
            parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        if minutes:
            parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
        if seconds:
            parts.append(f"{seconds} second{'s' if seconds != 1 else ''}")
        
        return ", ".join(parts)

    async def _get_afk_status(self, user_id: int, guild_id: int) -> Optional[Dict[str, Any]]:
        """Retrieves AFK status for a user from cache or DB."""
        if guild_id in self.afk_cache and user_id in self.afk_cache[guild_id]:
            return self.afk_cache[guild_id][user_id]
        
        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT reason, original_nick, timestamp FROM afk_users WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id)
            )
            row = await cursor.fetchone()
            if row:
                reason, original_nick, timestamp = row
                afk_data = {
                    "reason": reason,
                    "original_nick": original_nick,
                    "timestamp": datetime.fromtimestamp(timestamp, tz=discord.utils.UTC)
                }
                if guild_id not in self.afk_cache:
                    self.afk_cache[guild_id] = {}
                self.afk_cache[guild_id][user_id] = afk_data
                return afk_data
        return None

    async def _set_afk_status(self, member: discord.Member, reason: str):
        """Sets a user's AFK status and updates their nickname."""
        original_nick = member.display_name
        new_nick = f"[AFK] {original_nick}"
        if len(new_nick) > 32:
            new_nick = new_nick[:29] + "..."

        try:
            await member.edit(nick=new_nick, reason="User went AFK")
        except discord.Forbidden:
            logger.warning(f"AFK: Could not change nickname for {member} in {member.guild.name} due to permissions.")
            original_nick = None # Don't try to restore if we couldn't set
        except Exception as e:
            logger.error(f"AFK: Error changing nickname for {member}: {e}")
            original_nick = None

        timestamp = int(discord.utils.utcnow().timestamp())
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO afk_users (guild_id, user_id, reason, original_nick, timestamp) VALUES (?, ?, ?, ?, ?)",
                (member.guild.id, member.id, reason, original_nick, timestamp)
            )
            await db.commit()
        
        if member.guild.id not in self.afk_cache:
            self.afk_cache[member.guild.id] = {}
        self.afk_cache[member.guild.id][member.id] = {
            "reason": reason,
            "original_nick": original_nick,
            "timestamp": datetime.fromtimestamp(timestamp, tz=discord.utils.UTC)
        }

        await self._send_afk_log(
            member.guild,
            self._create_info_embed(
                "AFK Status Set",
                f"{member.mention} is now AFK. Reason: `{reason}`"
            )
        )

    async def _clear_afk_status(self, member: discord.Member, cleared_by: discord.Member = None):
        """Clears a user's AFK status and restores their nickname."""
        afk_data = await self._get_afk_status(member.id, member.guild.id)
        if not afk_data:
            return

        original_nick = afk_data.get("original_nick")
        if original_nick:
            try:
                await member.edit(nick=original_nick, reason="User returned from AFK")
            except discord.Forbidden:
                logger.warning(f"AFK: Could not restore nickname for {member} in {member.guild.name} due to permissions.")
            except Exception as e:
                logger.error(f"AFK: Error restoring nickname for {member}: {e}")
        else:
            # If original_nick was None (meaning we couldn't set it initially), clear any [AFK] prefix
            if member.nick and member.nick.startswith("[AFK]"):
                try:
                    await member.edit(nick=None, reason="User returned from AFK (clearing [AFK] prefix)")
                except discord.Forbidden:
                    logger.warning(f"AFK: Could not clear [AFK] prefix for {member} in {member.guild.name} due to permissions.")
                except Exception as e:
                    logger.error(f"AFK: Error clearing [AFK] prefix for {member}: {e}")

        async with self._get_db() as db:
            await db.execute("DELETE FROM afk_users WHERE guild_id = ? AND user_id = ?", (member.guild.id, member.id))
            await db.commit()
        
        if member.guild.id in self.afk_cache and member.id in self.afk_cache[member.guild.id]:
            del self.afk_cache[member.guild.id][member.id]

        cleared_by_text = f" (Cleared by {cleared_by.mention})" if cleared_by and cleared_by.id != member.id else ""
        await self._send_afk_log(
            member.guild,
            self._create_info_embed(
                "AFK Status Cleared",
                f"{member.mention} is no longer AFK.{cleared_by_text}"
            )
        )

    async def _is_channel_ignored(self, guild_id: int, channel_id: int) -> bool:
        """Checks if a channel is in the ignored list for AFK auto-clear."""
        if guild_id not in self.ignored_channels_cache:
            async with self._get_db() as db:
                cursor = await db.execute("SELECT channel_id FROM afk_ignored_channels WHERE guild_id = ?", (guild_id,))
                self.ignored_channels_cache[guild_id] = [row[0] for row in await cursor.fetchall()]
        return channel_id in self.ignored_channels_cache.get(guild_id, [])

    async def _get_log_channel(self, guild_id: int) -> Optional[discord.TextChannel]:
        """Retrieves the configured AFK log channel."""
        if guild_id in self.log_channels_cache:
            channel_id = self.log_channels_cache[guild_id]
            return self.bot.get_channel(channel_id)
        
        async with self._get_db() as db:
            cursor = await db.execute("SELECT channel_id FROM afk_log_channels WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
            if row:
                self.log_channels_cache[guild_id] = row[0]
                return self.bot.get_channel(row[0])
        return None

    async def _send_afk_log(self, guild: discord.Guild, embed: discord.Embed):
        """Sends an embed to the configured AFK log channel."""
        log_channel = await self._get_log_channel(guild.id)
        if log_channel:
            try:
                await log_channel.send(embed=embed)
            except discord.Forbidden:
                logger.warning(f"AFK: Bot lacks permissions to send logs in {log_channel.name} ({guild.name}).")
            except Exception as e:
                logger.error(f"AFK: Error sending log to {log_channel.name} ({guild.name}): {e}")

    async def _get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """Retrieves guild-specific AFK settings."""
        if guild_id in self.guild_settings_cache:
            return self.guild_settings_cache[guild_id]
        
        async with self._get_db() as db:
            cursor = await db.execute("SELECT timeout_minutes FROM afk_settings WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
            settings = {"timeout_minutes": row[0]} if row else {"timeout_minutes": 0}
            self.guild_settings_cache[guild_id] = settings
            return settings

    async def _update_guild_setting(self, guild_id: int, setting_name: str, value: Any):
        """Updates a guild-specific AFK setting."""
        async with self._get_db() as db:
            if setting_name == "timeout_minutes":
                await db.execute(
                    "INSERT OR REPLACE INTO afk_settings (guild_id, timeout_minutes) VALUES (?, ?)",
                    (guild_id, value)
                )
            await db.commit()
        
        if guild_id not in self.guild_settings_cache:
            self.guild_settings_cache[guild_id] = {}
        self.guild_settings_cache[guild_id][setting_name] = value

    async def _get_user_presets(self, user_id: int) -> Dict[str, str]:
        """Retrieves all AFK presets for a given user."""
        async with self._get_db() as db:
            cursor = await db.execute("SELECT preset_name, preset_status FROM afk_presets WHERE user_id = ?", (user_id,))
            return {row[0]: row[1] for row in await cursor.fetchall()}

    async def _add_user_preset(self, user_id: int, name: str, status: str):
        """Adds or updates an AFK preset for a user."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO afk_presets (user_id, preset_name, preset_status) VALUES (?, ?, ?)",
                (user_id, name, status)
            )
            await db.commit()

    async def _delete_user_preset(self, user_id: int, name: str):
        """Deletes an AFK preset for a user."""
        async with self._get_db() as db:
            await db.execute("DELETE FROM afk_presets WHERE user_id = ? AND preset_name = ?", (user_id, name))
            await db.commit()

    # ========================= BACKGROUND TASKS =========================

    @tasks.loop(minutes=1)
    async def afk_timeout_checker(self):
        """
        Background task to automatically clear AFK statuses if a timeout is set
        and the user has been AFK longer than the timeout.
        """
        now = discord.utils.utcnow()
        users_to_clear = [] # (member, guild_id)

        for guild_id, afk_users_in_guild in list(self.afk_cache.items()): # Iterate a copy to allow modification
            guild = self.bot.get_guild(guild_id)
            if not guild:
                continue

            settings = await self._get_guild_settings(guild_id)
            timeout_minutes = settings.get("timeout_minutes", 0)

            if timeout_minutes <= 0:
                continue

            for user_id, afk_data in list(afk_users_in_guild.items()): # Iterate a copy
                member = guild.get_member(user_id)
                if not member:
                    # User left guild while AFK, clean up DB
                    async with self._get_db() as db:
                        await db.execute("DELETE FROM afk_users WHERE guild_id = ? AND user_id = ?", (guild_id, user_id))
                        await db.commit()
                    del self.afk_cache[guild_id][user_id]
                    continue

                afk_start_time = afk_data["timestamp"]
                if (now - afk_start_time).total_seconds() >= timeout_minutes * 60:
                    users_to_clear.append((member, guild_id))
        
        for member, guild_id in users_to_clear:
            await self._clear_afk_status(member, cleared_by=self.bot.user)
            try:
                await member.send(f"Your AFK status in {member.guild.name} has been automatically cleared after {timeout_minutes} minutes.")
            except discord.Forbidden:
                pass # Cannot DM user

    @afk_timeout_checker.before_loop
    async def before_afk_timeout_checker(self):
        await self.bot.wait_until_ready()

    # ========================= COMMANDS =========================

    @commands.group(name="afk", invoke_without_command=True)
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.default)
    async def afk_group(self, ctx: commands.Context, *, reason: Optional[str] = None):
        """
        Sets your status as AFK with an optional reason.
        If you are already AFK, this will update your reason.
        """
        if reason is None:
            reason = "No reason provided"

        afk_data = await self._get_afk_status(ctx.author.id, ctx.guild.id)
        if afk_data:
            # Already AFK, update reason
            async with self._get_db() as db:
                await db.execute(
                    "UPDATE afk_users SET reason = ? WHERE guild_id = ? AND user_id = ?",
                    (reason, ctx.guild.id, ctx.author.id)
                )
                await db.commit()
            self.afk_cache[ctx.guild.id][ctx.author.id]["reason"] = reason
            embed = self._create_success_embed(
                "AFK Status Updated",
                f"Your AFK reason has been updated to: `{reason}`"
            )
        else:
            # Set new AFK status
            await self._set_afk_status(ctx.author, reason)
            embed = self._create_success_embed(
                "You are now AFK!",
                f"Reason: `{reason}`"
            )
        await ctx.send(embed=embed)

    @afk_group.command(name="set", aliases=["away", "brb"])
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.guild_only()
    async def afk_set(self, ctx: commands.Context, *, status: Optional[str] = None):
        """Identical to the base AFK command; updates or sets yourself as AFK."""
        await self.afk_group(ctx, reason=status)

    @afk_group.command(name="clear", aliases=["back", "return"])
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.guild_only()
    async def afk_clear(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """
        Clears your AFK status. Staff with `manage_nicknames` can clear another member's status.
        """
        target_member = member or ctx.author

        if target_member.id != ctx.author.id and not ctx.author.guild_permissions.manage_nicknames:
            await ctx.send(embed=self._create_error_embed(
                "Permission Denied",
                "You need `Manage Nicknames` permission to clear another member's AFK status."
            ))
            return

        afk_data = await self._get_afk_status(target_member.id, ctx.guild.id)
        if not afk_data:
            await ctx.send(embed=self._create_info_embed(
                "Not AFK",
                f"{target_member.mention} is not currently AFK."
            ))
            return

        await self._clear_afk_status(target_member, cleared_by=ctx.author)
        await ctx.send(embed=self._create_success_embed(
            "AFK Status Cleared",
            f"{target_member.mention}'s AFK status has been cleared."
        ))

    @afk_group.command(name="ignore", aliases=["exempt"])
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def afk_ignore(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """
        Toggles a channel to be ignored for AFK auto-clear.
        If an AFK user sends a message in an ignored channel, their AFK status will not be cleared.
        """
        target_channel = channel or ctx.channel
        
        async with self._get_db() as db:
            if await self._is_channel_ignored(ctx.guild.id, target_channel.id):
                await db.execute(
                    "DELETE FROM afk_ignored_channels WHERE guild_id = ? AND channel_id = ?",
                    (ctx.guild.id, target_channel.id)
                )
                if ctx.guild.id in self.ignored_channels_cache:
                    self.ignored_channels_cache[ctx.guild.id].remove(target_channel.id)
                embed = self._create_success_embed(
                    "Channel No Longer Ignored",
                    f"{target_channel.mention} will no longer ignore AFK messages."
                )
            else:
                await db.execute(
                    "INSERT INTO afk_ignored_channels (guild_id, channel_id) VALUES (?, ?)",
                    (ctx.guild.id, target_channel.id)
                )
                if ctx.guild.id not in self.ignored_channels_cache:
                    self.ignored_channels_cache[ctx.guild.id] = []
                self.ignored_channels_cache[ctx.guild.id].append(target_channel.id)
                embed = self._create_success_embed(
                    "Channel Ignored",
                    f"{target_channel.mention} will now ignore AFK messages (status will not clear)."
                )
            await db.commit()
        await ctx.send(embed=embed)

    @afk_group.command(name="list", aliases=["whoisafk", "afklist"])
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.guild_only()
    async def afk_list(self, ctx: commands.Context, page: int = 1):
        """Displays a paginated list of all currently AFK members in the server."""
        afk_members_data = []
        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT user_id, reason, timestamp FROM afk_users WHERE guild_id = ?",
                (ctx.guild.id,)
            )
            rows = await cursor.fetchall()
            for user_id, reason, timestamp in rows:
                member = ctx.guild.get_member(user_id)
                if member:
                    afk_members_data.append({
                        "member": member,
                        "reason": reason,
                        "timestamp": datetime.fromtimestamp(timestamp, tz=discord.utils.UTC)
                    })
        
        if not afk_members_data:
            await ctx.send(embed=self._create_info_embed(
                "No AFK Members",
                "There are no members currently AFK in this server."
            ))
            return

        afk_members_data.sort(key=lambda x: x["timestamp"]) # Sort by time they went AFK

        items_per_page = 10
        total_pages = (len(afk_members_data) + items_per_page - 1) // items_per_page

        if not (1 <= page <= total_pages):
            await ctx.send(embed=self._create_error_embed(
                "Invalid Page",
                f"Page {page} does not exist. There are {total_pages} page(s)."
            ))
            return

        start_index = (page - 1) * items_per_page
        end_index = start_index + items_per_page
        current_page_data = afk_members_data[start_index:end_index]

        description_parts = []
        for data in current_page_data:
            member = data["member"]
            reason = data["reason"]
            afk_since = discord.utils.utcnow() - data["timestamp"]
            description_parts.append(
                f"**{member.mention}** (`{member.id}`)\n"
                f"Reason: `{reason}`\n"
                f"AFK for: {self._format_duration(int(afk_since.total_seconds()))}\n"
            )
        
        embed = self._create_info_embed(
            f"AFK Members ({len(afk_members_data)})",
            "\n".join(description_parts)
        )
        embed.set_footer(text=f"Page {page}/{total_pages} | VOTOX AFK System")
        await ctx.send(embed=embed)

    @afk_group.command(name="logchannel", aliases=["logset"])
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def afk_logchannel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """
        Registers a log channel for AFK events.
        When someone goes AFK or returns, a formal event embed is sent to this channel.
        """
        if channel is None:
            current_log_channel_id = self.log_channels_cache.get(ctx.guild.id)
            if current_log_channel_id:
                current_channel = ctx.guild.get_channel(current_log_channel_id)
                await ctx.send(embed=self._create_info_embed(
                    "Current AFK Log Channel",
                    f"The current AFK log channel is {current_channel.mention if current_channel else 'Not found (ID: ' + str(current_log_channel_id) + ')'}."
                ))
            else:
                await ctx.send(embed=self._create_info_embed(
                    "No AFK Log Channel Set",
                    "No AFK log channel is currently configured. Use `.afk logchannel <channel>` to set one."
                ))
            return

        async with self._get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO afk_log_channels (guild_id, channel_id) VALUES (?, ?)",
                (ctx.guild.id, channel.id)
            )
            await db.commit()
        self.log_channels_cache[ctx.guild.id] = channel.id
        await ctx.send(embed=self._create_success_embed(
            "AFK Log Channel Set",
            f"AFK events will now be logged in {channel.mention}."
        ))

    @afk_group.command(name="timeout", aliases=["min", "delay"])
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def afk_timeout(self, ctx: commands.Context, minutes: Optional[int] = None):
        """
        Sets an auto-clear timeout for AFK users.
        If configured, active AFK users are automatically cleared after x minutes.
        Set to 0 to disable.
        """
        settings = await self._get_guild_settings(ctx.guild.id)
        current_timeout = settings.get("timeout_minutes", 0)

        if minutes is None:
            status = f"currently set to **{current_timeout} minutes**." if current_timeout > 0 else "**disabled**."
            await ctx.send(embed=self._create_info_embed(
                "AFK Auto-Clear Timeout",
                f"The AFK auto-clear timeout is {status}\n"
                "Use `.afk timeout <minutes>` to change it (0 to disable)."
            ))
            return

        if not (0 <= minutes <= 1440): # Max 24 hours
            await ctx.send(embed=self._create_error_embed(
                "Invalid Timeout",
                "Timeout minutes must be between 0 (disable) and 1440 (24 hours)."
            ))
            return
        
        await self._update_guild_setting(ctx.guild.id, "timeout_minutes", minutes)
        if minutes > 0:
            embed = self._create_success_embed(
                "AFK Auto-Clear Timeout Set",
                f"AFK users will now be automatically cleared after **{minutes} minutes**."
            )
        else:
            embed = self._create_success_embed(
                "AFK Auto-Clear Timeout Disabled",
                "AFK auto-clear timeout has been disabled."
            )
        await ctx.send(embed=embed)

    @afk_group.group(name="preset", invoke_without_command=True)
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.guild_only()
    async def afk_preset_group(self, ctx: commands.Context):
        """Displays a menu explaining the AFK preset commands."""
        embed = self._create_info_embed(
            "AFK Presets",
            "Manage your custom AFK status messages.\n\n"
            "**Commands:**\n"
            "`.afk preset add <name> <status>`: Save a customized status message.\n"
            "`.afk preset delete <name>`: Delete a saved preset.\n"
            "`.afk preset list`: List all your saved presets.\n"
            "`.afk preset use <name>`: Immediately trigger AFK status utilizing the preset."
        )
        await ctx.send(embed=embed)

    @afk_preset_group.command(name="add", aliases=["save", "create"])
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.guild_only()
    async def afk_preset_add(self, ctx: commands.Context, name: str, *, status: str):
        """Saves a customized AFK status message."""
        if len(name) > 50:
            await ctx.send(embed=self._create_error_embed("Name Too Long", "Preset name cannot exceed 50 characters."))
            return
        if len(status) > 200:
            await ctx.send(embed=self._create_error_embed("Status Too Long", "Preset status cannot exceed 200 characters."))
            return

        await self._add_user_preset(ctx.author.id, name, status)
        await ctx.send(embed=self._create_success_embed(
            "Preset Saved",
            f"Preset `{name}` saved with status: `{status}`"
        ))

    @commands.cooldown(1, 3, commands.BucketType.default)
    @afk_preset_group.command(name="delete", aliases=["delpreset", "removepreset"])
    @commands.guild_only()
    async def afk_preset_delete(self, ctx: commands.Context, name: str):
        """Deletes a saved AFK preset."""
        presets = await self._get_user_presets(ctx.author.id)
        if name not in presets:
            await ctx.send(embed=self._create_error_embed("Preset Not Found", f"Preset `{name}` does not exist."))
            return
        
        await self._delete_user_preset(ctx.author.id, name)
        await ctx.send(embed=self._create_success_embed(
            "Preset Deleted",
            f"Preset `{name}` has been deleted."
        ))

    @commands.cooldown(1, 3, commands.BucketType.default)
    @afk_preset_group.command(name="list")
    @commands.guild_only()
    async def afk_preset_list(self, ctx: commands.Context):
        """Lists all presets currently configured by the executing user."""
        presets = await self._get_user_presets(ctx.author.id)
        if not presets:
            await ctx.send(embed=self._create_info_embed(
                "No Presets",
                "You have no saved AFK presets. Use `.afk preset add <name> <status>` to create one."
            ))
            return
        
        description_parts = []
        for name, status in presets.items():
            description_parts.append(f"**`{name}`**: `{status}`")
        
        embed = self._create_info_embed(
            f"Your AFK Presets ({len(presets)})",
            "\n".join(description_parts)
        )
        await ctx.send(embed=embed)

    @commands.cooldown(1, 3, commands.BucketType.default)
    @afk_preset_group.command(name="use", aliases=["quickafk", "usepreset"])
    @commands.guild_only()
    async def afk_preset_use(self, ctx: commands.Context, name: str):
        """Immediately triggers AFK status utilizing the status text of the targeted preset."""
        presets = await self._get_user_presets(ctx.author.id)
        if name not in presets:
            await ctx.send(embed=self._create_error_embed("Preset Not Found", f"Preset `{name}` does not exist."))
            return
        
        status = presets[name]
        await self.afk_group(ctx, reason=status)

    # ========================= EVENT HANDLING =========================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Handles incoming messages for AFK auto-clear and mention alerts.
        """
        if message.author.bot or not message.guild:
            return

        # --- Self-Recovery (Return Check) ---
        afk_data = await self._get_afk_status(message.author.id, message.guild.id)
        if afk_data:
            if not await self._is_channel_ignored(message.guild.id, message.channel.id):
                await self._clear_afk_status(message.author)
                await message.channel.send(
                    f"Welcome back, {message.author.mention}! Your AFK status has been cleared.",
                    delete_after=10
                )
            return # Don't process mentions if user just returned from AFK

        # --- Ping / Mention Alert ---
        for mentioned_user in message.mentions:
            if mentioned_user.bot:
                continue
            
            mentioned_afk_data = await self._get_afk_status(mentioned_user.id, message.guild.id)
            if mentioned_afk_data:
                afk_since = discord.utils.utcnow() - mentioned_afk_data["timestamp"]
                embed = self._create_warning_embed(
                    f"{mentioned_user.display_name} is AFK!",
                    f"**Reason:** `{mentioned_afk_data['reason']}`\n"
                    f"**AFK for:** {self._format_duration(int(afk_since.total_seconds()))}"
                )
                embed.set_thumbnail(url=mentioned_user.avatar.url if mentioned_user.avatar else discord.Embed.Empty)
                try:
                    await message.reply(embed=embed, mention_author=False)
                except discord.Forbidden:
                    pass # Cannot reply to message
                except Exception as e:
                    logger.error(f"AFK: Error sending mention alert: {e}")

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"This command is on cooldown. Try again in {error.retry_after:.2f}s.", ephemeral=True)
            return
        raise error


async def setup(bot: commands.Bot):
    """Loads the AFK cog into the bot."""
    await bot.add_cog(AFK(bot))