

import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import re
import logging
from pathlib import Path
from typing import Optional, Union, List, Dict, Any, Set, Tuple
import uwuipy

logger = logging.getLogger("VOTOX")

class Uwulock(commands.Cog):
    """
    Enforces uwu-speak on specified users/roles and provides content filtering.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        self.uwu = uwuipy.uwuipy()
        
        # Caches for performance
        self._guild_settings_cache: Dict[int, Dict[str, Any]] = {}
        self._uwulocked_targets_cache: Dict[int, Set[Tuple[int, bool]]] = {} # (target_id, is_role)
        self._global_whitelist_cache: Dict[int, Set[Tuple[int, bool]]] = {}
        self._link_whitelist_cache: Dict[int, Set[Tuple[int, bool]]] = {}
        self._invite_whitelist_cache: Dict[int, Set[Tuple[int, bool]]] = {}
        self._webhooks: Dict[int, discord.Webhook] = {} # {channel_id: webhook_object}

    def _get_db(self) -> aiosqlite.Connection:
        """Returns an aiosqlite connection to the database."""
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initialize database tables and load initial cache data."""
        async with self._get_db() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS uwulocked_targets (
                    guild_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    is_role BOOLEAN NOT NULL,
                    PRIMARY KEY (guild_id, target_id, is_role)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS uwulock_settings (
                    guild_id INTEGER PRIMARY KEY,
                    enabled BOOLEAN DEFAULT 1,
                    link_blocking BOOLEAN DEFAULT 0,
                    invite_blocking BOOLEAN DEFAULT 0
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS uwulock_whitelist (
                    guild_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    is_role BOOLEAN NOT NULL,
                    PRIMARY KEY (guild_id, target_id, is_role)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS uwulock_link_whitelist (
                    guild_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    is_role BOOLEAN NOT NULL,
                    PRIMARY KEY (guild_id, target_id, is_role)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS uwulock_invite_whitelist (
                    guild_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    is_role BOOLEAN NOT NULL,
                    PRIMARY KEY (guild_id, target_id, is_role)
                )
            ''')
            await db.commit()
        await self._load_all_cache_data()

    async def _load_all_cache_data(self):
        """Loads all necessary data into in-memory caches from the database."""
        async with self._get_db() as db:
            # Load uwulock settings
            cursor = await db.execute("SELECT guild_id, enabled, link_blocking, invite_blocking FROM uwulock_settings")
            for guild_id, enabled, link_blocking, invite_blocking in await cursor.fetchall():
                self._guild_settings_cache[guild_id] = {
                    "enabled": bool(enabled),
                    "link_blocking": bool(link_blocking),
                    "invite_blocking": bool(invite_blocking)
                }
            
            # Load uwulocked targets
            cursor = await db.execute("SELECT guild_id, target_id, is_role FROM uwulocked_targets")
            for guild_id, target_id, is_role in await cursor.fetchall():
                if guild_id not in self._uwulocked_targets_cache:
                    self._uwulocked_targets_cache[guild_id] = set()
                self._uwulocked_targets_cache[guild_id].add((target_id, bool(is_role)))
            
            # Load global whitelist
            cursor = await db.execute("SELECT guild_id, target_id, is_role FROM uwulock_whitelist")
            for guild_id, target_id, is_role in await cursor.fetchall():
                if guild_id not in self._global_whitelist_cache:
                    self._global_whitelist_cache[guild_id] = set()
                self._global_whitelist_cache[guild_id].add((target_id, bool(is_role)))
            
            # Load link whitelist
            cursor = await db.execute("SELECT guild_id, target_id, is_role FROM uwulock_link_whitelist")
            for guild_id, target_id, is_role in await cursor.fetchall():
                if guild_id not in self._link_whitelist_cache:
                    self._link_whitelist_cache[guild_id] = set()
                self._link_whitelist_cache[guild_id].add((target_id, bool(is_role)))
            
            # Load invite whitelist
            cursor = await db.execute("SELECT guild_id, target_id, is_role FROM uwulock_invite_whitelist")
            for guild_id, target_id, is_role in await cursor.fetchall():
                if guild_id not in self._invite_whitelist_cache:
                    self._invite_whitelist_cache[guild_id] = set()
                self._invite_whitelist_cache[guild_id].add((target_id, bool(is_role)))

    # ========================= HELPER METHODS =========================

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
        embed.set_footer(text="VOTOX Uwulock System", icon_url=self.bot.user.display_avatar.url)
        return embed

    def _create_success_embed(self, title: str, description: str) -> discord.Embed:
        return self._create_embed(f"✅ {title}", description, discord.Color.green())

    def _create_error_embed(self, title: str, description: str) -> discord.Embed:
        return self._create_embed(f"❌ {title}", description, discord.Color.red())

    def _create_info_embed(self, title: str, description: str) -> discord.Embed:
        return self._create_embed(f"ℹ️ {title}", description, discord.Color.blurple())

    async def _get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """Retrieves guild-specific Uwulock settings from cache or DB."""
        if guild_id in self._guild_settings_cache:
            return self._guild_settings_cache[guild_id]
        
        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT enabled, link_blocking, invite_blocking FROM uwulock_settings WHERE guild_id = ?",
                (guild_id,)
            )
            row = await cursor.fetchone()
            settings = {
                "enabled": bool(row[0]),
                "link_blocking": bool(row[1]),
                "invite_blocking": bool(row[2])
            } if row else {
                "enabled": True, # Default to enabled
                "link_blocking": False,
                "invite_blocking": False
            }
            self._guild_settings_cache[guild_id] = settings
            return settings

    async def _update_guild_setting(self, guild_id: int, column: str, value: Any):
        """Updates a guild-specific Uwulock setting in the database and cache."""
        async with self._get_db() as db:
            await db.execute(
                f"INSERT INTO uwulock_settings (guild_id, {column}) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET {column} = ?",
                (guild_id, value, value)
            )
            await db.commit()
        
        if guild_id not in self._guild_settings_cache:
            self._guild_settings_cache[guild_id] = {}
        self._guild_settings_cache[guild_id][column] = bool(value)

    async def _get_uwulocked_targets(self, guild_id: int) -> Set[Tuple[int, bool]]:
        """Retrieves uwulocked targets from cache or DB."""
        if guild_id in self._uwulocked_targets_cache:
            return self._uwulocked_targets_cache[guild_id]
        
        async with self._get_db() as db:
            cursor = await db.execute("SELECT target_id, is_role FROM uwulocked_targets WHERE guild_id = ?", (guild_id,))
            targets = {(row[0], bool(row[1])) for row in await cursor.fetchall()}
            self._uwulocked_targets_cache[guild_id] = targets
            return targets

    async def _add_uwulocked_target(self, guild_id: int, target_id: int, is_role: bool):
        """Adds a target to the uwulocked list in DB and cache."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO uwulocked_targets (guild_id, target_id, is_role) VALUES (?, ?, ?)",
                (guild_id, target_id, is_role)
            )
            await db.commit()
        if guild_id not in self._uwulocked_targets_cache:
            self._uwulocked_targets_cache[guild_id] = set()
        self._uwulocked_targets_cache[guild_id].add((target_id, is_role))

    async def _remove_uwulocked_target(self, guild_id: int, target_id: int, is_role: bool):
        """Removes a target from the uwulocked list in DB and cache."""
        async with self._get_db() as db:
            await db.execute(
                "DELETE FROM uwulocked_targets WHERE guild_id = ? AND target_id = ? AND is_role = ?",
                (guild_id, target_id, is_role)
            )
            await db.commit()
        if guild_id in self._uwulocked_targets_cache:
            self._uwulocked_targets_cache[guild_id].discard((target_id, is_role))

    async def _get_global_whitelist(self, guild_id: int) -> Set[Tuple[int, bool]]:
        """Retrieves global whitelist targets from cache or DB."""
        if guild_id in self._global_whitelist_cache:
            return self._global_whitelist_cache[guild_id]
        async with self._get_db() as db:
            cursor = await db.execute("SELECT target_id, is_role FROM uwulock_whitelist WHERE guild_id = ?", (guild_id,))
            targets = {(row[0], bool(row[1])) for row in await cursor.fetchall()}
            self._global_whitelist_cache[guild_id] = targets
            return targets

    async def _add_global_whitelist(self, guild_id: int, target_id: int, is_role: bool):
        """Adds a target to the global whitelist in DB and cache."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO uwulock_whitelist (guild_id, target_id, is_role) VALUES (?, ?, ?)",
                (guild_id, target_id, is_role)
            )
            await db.commit()
        if guild_id not in self._global_whitelist_cache:
            self._global_whitelist_cache[guild_id] = set()
        self._global_whitelist_cache[guild_id].add((target_id, is_role))

    async def _remove_global_whitelist(self, guild_id: int, target_id: int, is_role: bool):
        """Removes a target from the global whitelist in DB and cache."""
        async with self._get_db() as db:
            await db.execute(
                "DELETE FROM uwulock_whitelist WHERE guild_id = ? AND target_id = ? AND is_role = ?",
                (guild_id, target_id, is_role)
            )
            await db.commit()
        if guild_id in self._global_whitelist_cache:
            self._global_whitelist_cache[guild_id].discard((target_id, is_role))

    async def _get_link_whitelist(self, guild_id: int) -> Set[Tuple[int, bool]]:
        """Retrieves link whitelist targets from cache or DB."""
        if guild_id in self._link_whitelist_cache:
            return self._link_whitelist_cache[guild_id]
        async with self._get_db() as db:
            cursor = await db.execute("SELECT target_id, is_role FROM uwulock_link_whitelist WHERE guild_id = ?", (guild_id,))
            targets = {(row[0], bool(row[1])) for row in await cursor.fetchall()}
            self._link_whitelist_cache[guild_id] = targets
            return targets

    async def _add_link_whitelist(self, guild_id: int, target_id: int, is_role: bool):
        """Adds a target to the link whitelist in DB and cache."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO uwulock_link_whitelist (guild_id, target_id, is_role) VALUES (?, ?, ?)",
                (guild_id, target_id, is_role)
            )
            await db.commit()
        if guild_id not in self._link_whitelist_cache:
            self._link_whitelist_cache[guild_id] = set()
        self._link_whitelist_cache[guild_id].add((target_id, is_role))

    async def _remove_link_whitelist(self, guild_id: int, target_id: int, is_role: bool):
        """Removes a target from the link whitelist in DB and cache."""
        async with self._get_db() as db:
            await db.execute(
                "DELETE FROM uwulock_link_whitelist WHERE guild_id = ? AND target_id = ? AND is_role = ?",
                (guild_id, target_id, is_role)
            )
            await db.commit()
        if guild_id in self._link_whitelist_cache:
            self._link_whitelist_cache[guild_id].discard((target_id, is_role))

    async def _get_invite_whitelist(self, guild_id: int) -> Set[Tuple[int, bool]]:
        """Retrieves invite whitelist targets from cache or DB."""
        if guild_id in self._invite_whitelist_cache:
            return self._invite_whitelist_cache[guild_id]
        async with self._get_db() as db:
            cursor = await db.execute("SELECT target_id, is_role FROM uwulock_invite_whitelist WHERE guild_id = ?", (guild_id,))
            targets = {(row[0], bool(row[1])) for row in await cursor.fetchall()}
            self._invite_whitelist_cache[guild_id] = targets
            return targets

    async def _add_invite_whitelist(self, guild_id: int, target_id: int, is_role: bool):
        """Adds a target to the invite whitelist in DB and cache."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR IGNORE INTO uwulock_invite_whitelist (guild_id, target_id, is_role) VALUES (?, ?, ?)",
                (guild_id, target_id, is_role)
            )
            await db.commit()
        if guild_id not in self._invite_whitelist_cache:
            self._invite_whitelist_cache[guild_id] = set()
        self._invite_whitelist_cache[guild_id].add((target_id, is_role))

    async def _remove_invite_whitelist(self, guild_id: int, target_id: int, is_role: bool):
        """Removes a target from the invite whitelist in DB and cache."""
        async with self._get_db() as db:
            await db.execute(
                "DELETE FROM uwulock_invite_whitelist WHERE guild_id = ? AND target_id = ? AND is_role = ?",
                (guild_id, target_id, is_role)
            )
            await db.commit()
        if guild_id in self._invite_whitelist_cache:
            self._invite_whitelist_cache[guild_id].discard((target_id, is_role))

    async def _get_webhook(self, channel: discord.TextChannel) -> Optional[discord.Webhook]:
        """Dynamically gets or creates a webhook for the given channel."""
        if channel.id in self._webhooks:
            return self._webhooks[channel.id]
        
        try:
            webhooks = await channel.webhooks()
            webhook = discord.utils.get(webhooks, name="VOTOX-Uwulock")
            if not webhook:
                webhook = await channel.create_webhook(name="VOTOX-Uwulock", reason="Uwulock system webhook")
            self._webhooks[channel.id] = webhook
            return webhook
        except discord.Forbidden:
            logger.warning(f"Uwulock: Missing 'manage_webhooks' permission in {channel.name} ({channel.guild.name}).")
            return None
        except Exception as e:
            logger.error(f"Uwulock: Error getting/creating webhook in {channel.name} ({channel.guild.name}): {e}")
            return None

    async def _is_uwulocked(self, member: discord.Member) -> bool:
        """Checks if a member or any of their roles are uwulocked."""
        uwulocked_targets = await self._get_uwulocked_targets(member.guild.id)
        if (member.id, False) in uwulocked_targets: # Check if user is uwulocked
            return True
        for role in member.roles: # Check if any of their roles are uwulocked
            if (role.id, True) in uwulocked_targets:
                return True
        return False

    async def _is_globally_whitelisted(self, member: discord.Member) -> bool:
        """Checks if a member or any of their roles are globally whitelisted."""
        global_whitelist = await self._get_global_whitelist(member.guild.id)
        if (member.id, False) in global_whitelist:
            return True
        for role in member.roles:
            if (role.id, True) in global_whitelist:
                return True
        return False

    async def _is_link_whitelisted(self, member: discord.Member) -> bool:
        """Checks if a member or any of their roles are whitelisted for links."""
        link_whitelist = await self._get_link_whitelist(member.guild.id)
        if (member.id, False) in link_whitelist:
            return True
        for role in member.roles:
            if (role.id, True) in link_whitelist:
                return True
        return False

    async def _is_invite_whitelisted(self, member: discord.Member) -> bool:
        """Checks if a member or any of their roles are whitelisted for invites."""
        invite_whitelist = await self._get_invite_whitelist(member.guild.id)
        if (member.id, False) in invite_whitelist:
            return True
        for role in member.roles:
            if (role.id, True) in invite_whitelist:
                return True
        return False

    def _check_links(self, text: str) -> bool:
        """Checks if text contains any common URL patterns."""
        url_pattern = r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
        return bool(re.search(url_pattern, text))

    def _check_invites(self, text: str) -> bool:
        """Checks if text contains Discord invite links."""
        invite_pattern = r'(?:discord\.gg/|discordapp\.com/invite/)([a-zA-Z0-9]+)'
        return bool(re.search(invite_pattern, text))

    async def _parse_user_or_role(self, ctx: commands.Context, arg: str) -> Optional[Union[discord.Member, discord.Role]]:
        """Parses a string argument into a Member or Role object."""
        try:
            # Try to get member by ID or mention
            member = await commands.MemberConverter().convert(ctx, arg)
            return member
        except commands.BadArgument:
            try:
                # Try to get role by ID or mention
                role = await commands.RoleConverter().convert(ctx, arg)
                return role
            except commands.BadArgument:
                return None

    # ========================= COMMANDS =========================

    @commands.group(name="uwulock", invoke_without_command=True)
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.guild_only()
    async def uwulock_group(self, ctx: commands.Context):
        """Displays the Uwulock help menu."""
        embed = self._create_info_embed(
            "🌸 Uwulock System Help 🌸",
            "Enforce uwu-speak and content filtering for users/roles."
        )
        embed.add_field(name="Commands", value=(
            "`uwulock add <user/role>`: Add target to uwulock\n"
            "`uwulock remove <user/role>`: Remove target from uwulock\n"
            "`uwulock list`: List uwulocked targets\n"
            "`uwulock enable/disable`: Toggle system globally\n"
            "`uwulock config`: Show current settings\n"
            "`uwulock links <subcommands>`: Manage link blocking\n"
            "`uwulock invites <subcommands>`: Manage invite blocking\n"
            "`uwulock whitelist <subcommands>`: Manage global bypass"
        ), inline=False)
        embed.set_footer(text="Use ',uwulock <command>' for more details on subcommands.")
        await ctx.send(embed=embed)

    @uwulock_group.command(name="add")
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(1, 3, commands.BucketType.default)
    async def uwulock_add(self, ctx: commands.Context, user_or_role: Union[discord.Member, discord.Role]):
        """Adds a user or role to the uwulocked targets list."""
        is_role = isinstance(user_or_role, discord.Role)
        target_id = user_or_role.id
        
        uwulocked_targets = await self._get_uwulocked_targets(ctx.guild.id)
        if (target_id, is_role) in uwulocked_targets:
            return await ctx.send(embed=self._create_error_embed("Already Uwulocked", f"{user_or_role.mention} is already uwulocked."))
        
        await self._add_uwulocked_target(ctx.guild.id, target_id, is_role)
        await ctx.send(embed=self._create_success_embed("Target Uwulocked", f"{user_or_role.mention} has been added to the uwulock list."))

    @uwulock_group.command(name="remove")
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(1, 3, commands.BucketType.default)
    async def uwulock_remove(self, ctx: commands.Context, user_or_role: Union[discord.Member, discord.Role]):
        """Removes a user or role from the uwulocked targets list."""
        is_role = isinstance(user_or_role, discord.Role)
        target_id = user_or_role.id

        uwulocked_targets = await self._get_uwulocked_targets(ctx.guild.id)
        if (target_id, is_role) not in uwulocked_targets:
            return await ctx.send(embed=self._create_error_embed("Not Uwulocked", f"{user_or_role.mention} is not currently uwulocked."))
        
        await self._remove_uwulocked_target(ctx.guild.id, target_id, is_role)
        await ctx.send(embed=self._create_success_embed("Target Unuwulocked", f"{user_or_role.mention} has been removed from the uwulock list."))

    @uwulock_group.command(name="list")
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(1, 3, commands.BucketType.default)
    async def uwulock_list(self, ctx: commands.Context):
        """Displays a list of all currently uwulocked users and roles."""
        uwulocked_targets = await self._get_uwulocked_targets(ctx.guild.id)
        if not uwulocked_targets:
            return await ctx.send(embed=self._create_info_embed("No Uwulocked Targets", "No users or roles are currently uwulocked."))
        
        users = []
        roles = []
        for target_id, is_role in uwulocked_targets:
            if is_role:
                role = ctx.guild.get_role(target_id)
                roles.append(role.mention if role else f"Unknown Role ({target_id})")
            else:
                user = ctx.guild.get_member(target_id)
                users.append(user.mention if user else f"Unknown User ({target_id})")
        
        description = ""
        if users:
            description += "**Users:**\n" + "\n".join(users) + "\n\n"
        if roles:
            description += "**Roles:**\n" + "\n".join(roles)
        
        await ctx.send(embed=self._create_info_embed("Uwulocked Targets", description.strip()))

    @uwulock_group.command(name="enable")
    @commands.has_permissions(manage_guild=True)
    @commands.cooldown(1, 3, commands.BucketType.default)
    async def uwulock_enable(self, ctx: commands.Context):
        """Globally enables the Uwulock system for the guild."""
        await self._update_guild_setting(ctx.guild.id, "enabled", True)
        await ctx.send(embed=self._create_success_embed("Uwulock Enabled", "The Uwulock system is now active."))

    @uwulock_group.command(name="disable")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_guild=True)
    async def uwulock_disable(self, ctx: commands.Context):
        """Globally disables the Uwulock system for the guild."""
        await self._update_guild_setting(ctx.guild.id, "enabled", False)
        await ctx.send(embed=self._create_success_embed("Uwulock Disabled", "The Uwulock system is now inactive."))

    @commands.cooldown(1, 3, commands.BucketType.default)
    @uwulock_group.command(name="config")
    @commands.has_permissions(manage_messages=True)
    async def uwulock_config(self, ctx: commands.Context):
        """Shows a comprehensive dashboard of current Uwulock settings."""
        settings = await self._get_guild_settings(ctx.guild.id)
        uwulocked_targets = await self._get_uwulocked_targets(ctx.guild.id)
        global_whitelist = await self._get_global_whitelist(ctx.guild.id)
        link_whitelist = await self._get_link_whitelist(ctx.guild.id)
        invite_whitelist = await self._get_invite_whitelist(ctx.guild.id)

        embed = self._create_info_embed(f"Uwulock Configuration for {ctx.guild.name}", "")
        embed.add_field(name="System Status", value=(
            f"**Enabled:** {'✅' if settings['enabled'] else '❌'}\n"
            f"**Uwulocked Targets:** {len(uwulocked_targets)}\n"
            f"**Global Whitelist:** {len(global_whitelist)}"
        ), inline=False)
        embed.add_field(name="Content Filtering", value=(
            f"**Link Blocking:** {'✅' if settings['link_blocking'] else '❌'}\n"
            f"**Link Whitelist:** {len(link_whitelist)}\n"
            f"**Invite Blocking:** {'✅' if settings['invite_blocking'] else '❌'}\n"
            f"**Invite Whitelist:** {len(invite_whitelist)}"
        ), inline=False)
        await ctx.send(embed=embed)

    @uwulock_group.group(name="links", invoke_without_command=True)
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_messages=True)
    async def uwulock_links(self, ctx: commands.Context):
        """Manage link blocking for uwulocked targets."""
        embed = self._create_info_embed(
            "🔗 Uwulock Link Blocking 🔗",
            "Configure link blocking for uwulocked users/roles."
        )
        embed.add_field(name="Commands", value=(
            "`uwulock links enable/disable`: Toggle link blocking\n"
            "`uwulock links whitelist <user/role>`: Allow target to send links\n"
            "`uwulock links unwhitelist <user/role>`: Disallow target from sending links"
        ), inline=False)
        await ctx.send(embed=embed)

    @uwulock_links.command(name="enable")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_guild=True)
    async def uwulock_links_enable(self, ctx: commands.Context):
        """Restricts uwulocked targets from sending links."""
        await self._update_guild_setting(ctx.guild.id, "link_blocking", True)
        await ctx.send(embed=self._create_success_embed("Link Blocking Enabled", "Uwulocked targets will now have their links blocked."))

    @commands.cooldown(1, 3, commands.BucketType.default)
    @uwulock_links.command(name="disable")
    @commands.has_permissions(manage_guild=True)
    async def uwulock_links_disable(self, ctx: commands.Context):
        """Allows uwulocked targets to send links freely."""
        await self._update_guild_setting(ctx.guild.id, "link_blocking", False)
        await ctx.send(embed=self._create_success_embed("Link Blocking Disabled", "Uwulocked targets can now send links."))

    @commands.cooldown(1, 3, commands.BucketType.default)
    @uwulock_links.command(name="whitelist")
    @commands.has_permissions(manage_messages=True)
    async def uwulock_links_whitelist(self, ctx: commands.Context, user_or_role: Union[discord.Member, discord.Role]):
        """Whitelists a user or role for sending links while uwulocked."""
        is_role = isinstance(user_or_role, discord.Role)
        target_id = user_or_role.id
        
        link_whitelist = await self._get_link_whitelist(ctx.guild.id)
        if (target_id, is_role) in link_whitelist:
            return await ctx.send(embed=self._create_error_embed("Already Whitelisted", f"{user_or_role.mention} is already link whitelisted."))
        
        await self._add_link_whitelist(ctx.guild.id, target_id, is_role)
        await ctx.send(embed=self._create_success_embed("Link Whitelist Added", f"{user_or_role.mention} can now send links even if blocking is enabled."))

    @commands.cooldown(1, 3, commands.BucketType.default)
    @uwulock_links.command(name="unwhitelist")
    @commands.has_permissions(manage_messages=True)
    async def uwulock_links_unwhitelist(self, ctx: commands.Context, user_or_role: Union[discord.Member, discord.Role]):
        """Removes a target from the link whitelist."""
        is_role = isinstance(user_or_role, discord.Role)
        target_id = user_or_role.id

        link_whitelist = await self._get_link_whitelist(ctx.guild.id)
        if (target_id, is_role) not in link_whitelist:
            return await ctx.send(embed=self._create_error_embed("Not Whitelisted", f"{user_or_role.mention} is not currently link whitelisted."))
        
        await self._remove_link_whitelist(ctx.guild.id, target_id, is_role)
        await ctx.send(embed=self._create_success_embed("Link Whitelist Removed", f"{user_or_role.mention} is no longer link whitelisted."))

    @uwulock_group.group(name="invites", invoke_without_command=True)
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_messages=True)
    async def uwulock_invites(self, ctx: commands.Context):
        """Manage invite blocking for uwulocked targets."""
        embed = self._create_info_embed(
            "🚫 Uwulock Invite Blocking 🚫",
            "Configure invite blocking for uwulocked users/roles."
        )
        embed.add_field(name="Commands", value=(
            "`uwulock invites enable/disable`: Toggle invite blocking\n"
            "`uwulock invites whitelist <user/role>`: Allow target to send invites\n"
            "`uwulock invites unwhitelist <user/role>`: Disallow target from sending invites"
        ), inline=False)
        await ctx.send(embed=embed)

    @uwulock_invites.command(name="enable")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_guild=True)
    async def uwulock_invites_enable(self, ctx: commands.Context):
        """Blocks uwulocked targets from posting Discord server invites."""
        await self._update_guild_setting(ctx.guild.id, "invite_blocking", True)
        await ctx.send(embed=self._create_success_embed("Invite Blocking Enabled", "Uwulocked targets will now have their invites blocked."))

    @commands.cooldown(1, 3, commands.BucketType.default)
    @uwulock_invites.command(name="disable")
    @commands.has_permissions(manage_guild=True)
    async def uwulock_invites_disable(self, ctx: commands.Context):
        """Allows uwulocked targets to send server invites."""
        await self._update_guild_setting(ctx.guild.id, "invite_blocking", False)
        await ctx.send(embed=self._create_success_embed("Invite Blocking Disabled", "Uwulocked targets can now send invites."))

    @commands.cooldown(1, 3, commands.BucketType.default)
    @uwulock_invites.command(name="whitelist")
    @commands.has_permissions(manage_messages=True)
    async def uwulock_invites_whitelist(self, ctx: commands.Context, user_or_role: Union[discord.Member, discord.Role]):
        """Whitelists a user or role for sending invites while uwulocked."""
        is_role = isinstance(user_or_role, discord.Role)
        target_id = user_or_role.id
        
        invite_whitelist = await self._get_invite_whitelist(ctx.guild.id)
        if (target_id, is_role) in invite_whitelist:
            return await ctx.send(embed=self._create_error_embed("Already Whitelisted", f"{user_or_role.mention} is already invite whitelisted."))
        
        await self._add_invite_whitelist(ctx.guild.id, target_id, is_role)
        await ctx.send(embed=self._create_success_embed("Invite Whitelist Added", f"{user_or_role.mention} can now send invites even if blocking is enabled."))

    @commands.cooldown(1, 3, commands.BucketType.default)
    @uwulock_invites.command(name="unwhitelist")
    @commands.has_permissions(manage_messages=True)
    async def uwulock_invites_unwhitelist(self, ctx: commands.Context, user_or_role: Union[discord.Member, discord.Role]):
        """Removes a target from the invite whitelist."""
        is_role = isinstance(user_or_role, discord.Role)
        target_id = user_or_role.id

        invite_whitelist = await self._get_invite_whitelist(ctx.guild.id)
        if (target_id, is_role) not in invite_whitelist:
            return await ctx.send(embed=self._create_error_embed("Not Whitelisted", f"{user_or_role.mention} is not currently invite whitelisted."))
        
        await self._remove_invite_whitelist(ctx.guild.id, target_id, is_role)
        await ctx.send(embed=self._create_success_embed("Invite Whitelist Removed", f"{user_or_role.mention} is no longer invite whitelisted."))

    @uwulock_group.group(name="whitelist", invoke_without_command=True)
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_messages=True)
    async def uwulock_whitelist(self, ctx: commands.Context):
        """Manage global bypass whitelist for Uwulock."""
        embed = self._create_info_embed(
            "✨ Uwulock Global Whitelist ✨",
            "Users/roles on this list will completely bypass the Uwulock system."
        )
        embed.add_field(name="Commands", value=(
            "`uwulock whitelist add <user/role>`: Add target to global whitelist\n"
            "`uwulock whitelist remove <user/role>`: Remove target from global whitelist\n"
            "`uwulock whitelist list`: List globally whitelisted targets"
        ), inline=False)
        await ctx.send(embed=embed)

    @uwulock_whitelist.command(name="add")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_messages=True)
    async def uwulock_whitelist_add(self, ctx: commands.Context, user_or_role: Union[discord.Member, discord.Role]):
        """Completely whitelists a user or role from Uwulock."""
        is_role = isinstance(user_or_role, discord.Role)
        target_id = user_or_role.id
        
        global_whitelist = await self._get_global_whitelist(ctx.guild.id)
        if (target_id, is_role) in global_whitelist:
            return await ctx.send(embed=self._create_error_embed("Already Whitelisted", f"{user_or_role.mention} is already globally whitelisted."))
        
        await self._add_global_whitelist(ctx.guild.id, target_id, is_role)
        await ctx.send(embed=self._create_success_embed("Global Whitelist Added", f"{user_or_role.mention} will now completely bypass Uwulock."))

    @commands.cooldown(1, 3, commands.BucketType.default)
    @uwulock_whitelist.command(name="remove")
    @commands.has_permissions(manage_messages=True)
    async def uwulock_whitelist_remove(self, ctx: commands.Context, user_or_role: Union[discord.Member, discord.Role]):
        """Removes a target from the global bypass whitelist."""
        is_role = isinstance(user_or_role, discord.Role)
        target_id = user_or_role.id

        global_whitelist = await self._get_global_whitelist(ctx.guild.id)
        if (target_id, is_role) not in global_whitelist:
            return await ctx.send(embed=self._create_error_embed("Not Whitelisted", f"{user_or_role.mention} is not currently globally whitelisted."))
        
        await self._remove_global_whitelist(ctx.guild.id, target_id, is_role)
        await ctx.send(embed=self._create_success_embed("Global Whitelist Removed", f"{user_or_role.mention} is no longer globally whitelisted."))

    @uwulock_whitelist.command(name="list")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_messages=True)
    async def uwulock_whitelist_list(self, ctx: commands.Context):
        """Lists all globally whitelisted users/roles."""
        global_whitelist = await self._get_global_whitelist(ctx.guild.id)
        if not global_whitelist:
            return await ctx.send(embed=self._create_info_embed("No Global Whitelist", "No users or roles are currently globally whitelisted."))
        
        users = []
        roles = []
        for target_id, is_role in global_whitelist:
            if is_role:
                role = ctx.guild.get_role(target_id)
                roles.append(role.mention if role else f"Unknown Role ({target_id})")
            else:
                user = ctx.guild.get_member(target_id)
                users.append(user.mention if user else f"Unknown User ({target_id})")
        
        description = ""
        if users:
            description += "**Users:**\n" + "\n".join(users) + "\n\n"
        if roles:
            description += "**Roles:**\n" + "\n".join(roles)
        
        await ctx.send(embed=self._create_info_embed("Global Whitelist Targets", description.strip()))

    # ========================= EVENT LISTENERS =========================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Intercepts messages, applies uwu-speak, and enforces content filtering.
        """
        if message.author.bot or not message.guild or not message.content:
            return

        settings = await self._get_guild_settings(message.guild.id)
        if not settings["enabled"]:
            return

        # Bypass for users with manage_messages or administrator permissions, unless they are explicitly uwulocked
        if message.author.guild_permissions.manage_messages or message.author.guild_permissions.administrator:
            if not await self._is_uwulocked(message.author):
                return

        # Check global whitelist
        if await self._is_globally_whitelisted(message.author):
            return

        # Check if the user/role is uwulocked
        if not await self._is_uwulocked(message.author):
            return

        # --- Content Filtering ---
        violation_found = False
        violation_type = ""
        
        # Link blocking
        if settings["link_blocking"] and self._check_links(message.content):
            if not await self._is_link_whitelisted(message.author):
                violation_found = True
                violation_type = "links"
        
        # Invite blocking
        if not violation_found and settings["invite_blocking"] and self._check_invites(message.content):
            if not await self._is_invite_whitelisted(message.author):
                violation_found = True
                violation_type = "invites"

        if violation_found:
            try:
                await message.delete()
                warning_embed = self._create_error_embed(
                    "🚫 Message Blocked 🚫",
                    f"{message.author.mention}, your message contained {violation_type}, which is not allowed while uwulocked."
                )
                await message.channel.send(embed=warning_embed, delete_after=7)
            except discord.Forbidden:
                logger.warning(f"Uwulock: Could not delete message or send warning in {message.channel.name} ({message.guild.name}). Missing permissions.")
            return

        # --- Uwuification ---
        try:
            uwuified_content = self.uwu.uwuify(message.content)
            
            # Delete original message
            try:
                await message.delete()
            except discord.Forbidden:
                logger.warning(f"Uwulock: Missing 'manage_messages' permission to delete original message in {message.channel.name} ({message.guild.name}).")
                return # Cannot proceed if original message can't be deleted

            # Send via webhook
            webhook = await self._get_webhook(message.channel)
            if webhook:
                try:
                    await webhook.send(
                        content=uwuified_content,
                        username=message.author.display_name,
                        avatar_url=message.author.display_avatar.url,
                        allowed_mentions=discord.AllowedMentions.none()
                    )
                except discord.HTTPException as e:
                    logger.error(f"Uwulock: Failed to send webhook message in {message.channel.name} ({message.guild.name}): {e}")
                    # Fallback to direct reply if webhook fails
                    try:
                        await message.channel.send(
                            f"**{message.author.display_name}**: {uwuified_content}",
                            allowed_mentions=discord.AllowedMentions.none()
                        )
                    except discord.Forbidden:
                        pass # Cannot send message at all
            else:
                # Fallback to direct reply if no webhook could be obtained
                try:
                    await message.channel.send(
                        f"**{message.author.display_name}**: {uwuified_content}",
                        allowed_mentions=discord.AllowedMentions.none()
                    )
                except discord.Forbidden:
                    pass # Cannot send message at all

        except Exception as e:
            logger.error(f"Uwulock: An unexpected error occurred during uwuification or sending: {e}")


    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"This command is on cooldown. Try again in {error.retry_after:.2f}s.", ephemeral=True)
            return
        raise error

async def setup(bot: commands.Bot):
    """Loads the Uwulock cog into the bot."""
    await bot.add_cog(Uwulock(bot))