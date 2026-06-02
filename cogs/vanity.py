"""
VOTOX Vanity Cog - Presence-based reward system.

This cog tracks users' custom statuses and grants reward roles to members 
who feature a specific keyword in their profile.

CRITICAL REQUIREMENTS:
The bot MUST have the following intents enabled in the main bot configuration:
- discord.Intents.members = True
- discord.Intents.presences = True

Features:
- Async database persistence via aiosqlite.
- Deep presence interception (on_presence_update).
- Role reward automation with hierarchy safety.
- Multi-layer blacklisting (User, Role, Text pattern).
- Dynamic notification variable engine.
- Sleek Embed-based administration UI.
"""

import discord
from discord.ext import commands
import aiosqlite
from pathlib import Path
from typing import Optional, Dict, Any, List, Union
import logging
import asyncio

logger = logging.getLogger("VOTOX")


class Vanity(commands.Cog):
    """
    Manages vanity keyword rewards in user statuses.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"

    def _get_db(self) -> aiosqlite.Connection:
        """Returns an aiosqlite connection to the database."""
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initializes database tables for vanity tracking."""
        async with self._get_db() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vanity_settings (
                    guild_id INTEGER PRIMARY KEY,
                    keyword TEXT,
                    message_template TEXT
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vanity_roles (
                    guild_id INTEGER,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, role_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vanity_channels (
                    guild_id INTEGER,
                    channel_id INTEGER,
                    PRIMARY KEY (guild_id, channel_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vanity_blacklist_users (
                    guild_id INTEGER,
                    user_id INTEGER,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vanity_blacklist_roles (
                    guild_id INTEGER,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, role_id)
                )
            ''')
            await db.execute('''
                CREATE TABLE IF NOT EXISTS vanity_blacklist_text (
                    guild_id INTEGER,
                    blocked_text TEXT,
                    PRIMARY KEY (guild_id, blocked_text)
                )
            ''')
            await db.commit()

    # ========================= HELPER METHODS =========================

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        """Standard VOTOX styling for vanity embeds."""
        embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
        embed.set_footer(text="VOTOX Vanity System", icon_url=self.bot.user.display_avatar.url)
        return embed

    def _create_success_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"✅ {title}", description, discord.Color.green())

    def _create_error_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"❌ {title}", description, discord.Color.red())

    def _create_info_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"ℹ️ {title}", description, discord.Color.blurple())

    def _parse_variables(self, text: str, member: discord.Member, status_text: str) -> str:
        """Replaces placeholders in the reward message."""
        if not text:
            return ""
        replacements = {
            "<<user.mention>>": member.mention,
            "<<user>>": member.display_name,
            "<<guild.name>>": member.guild.name,
            "<<status>>": status_text
        }
        for key, val in replacements.items():
            text = text.replace(key, val)
        return text

    async def _get_vanity_settings(self, guild_id: int) -> Dict[str, Any]:
        async with self._get_db() as db:
            cursor = await db.execute("SELECT keyword, message_template FROM vanity_settings WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
            if row:
                return {"keyword": row[0], "message_template": row[1]}
            return {"keyword": None, "message_template": None}

    async def _get_vanity_roles(self, guild_id: int) -> List[int]:
        async with self._get_db() as db:
            cursor = await db.execute("SELECT role_id FROM vanity_roles WHERE guild_id = ?", (guild_id,))
            return [r[0] for r in await cursor.fetchall()]

    async def _is_blacklisted(self, member: discord.Member, status_text: str) -> bool:
        guild_id = member.guild.id
        async with self._get_db() as db:
            # User blacklist check
            cursor = await db.execute("SELECT 1 FROM vanity_blacklist_users WHERE guild_id = ? AND user_id = ?", (guild_id, member.id))
            if await cursor.fetchone():
                return True

            # Role blacklist check
            role_ids = [r.id for r in member.roles]
            if role_ids:
                placeholders = ', '.join(['?'] * len(role_ids))
                cursor = await db.execute(f"SELECT 1 FROM vanity_blacklist_roles WHERE guild_id = ? AND role_id IN ({placeholders})", (guild_id, *role_ids))
                if await cursor.fetchone():
                    return True

            # Text blacklist check
            cursor = await db.execute("SELECT blocked_text FROM vanity_blacklist_text WHERE guild_id = ?", (guild_id,))
            blocked_patterns = [r[0] for r in await cursor.fetchall()]
            for pattern in blocked_patterns:
                if pattern.lower() in status_text.lower():
                    return True
        return False

    async def _update_member_vanity(self, member: discord.Member, after_status: Optional[str]):
        """Internal logic to process status change and assign/remove roles."""
        settings = await self._get_vanity_settings(member.guild.id)
        keyword = settings.get("keyword")
        if not keyword:
            return

        reward_role_ids = await self._get_vanity_roles(member.guild.id)
        if not reward_role_ids:
            return

        roles_to_handle = []
        for rid in reward_role_ids:
            role = member.guild.get_role(rid)
            if role:
                roles_to_handle.append(role)

        if not roles_to_handle:
            return

        has_keyword = keyword.lower() in after_status.lower() if after_status else False
        is_bl = await self._is_blacklisted(member, after_status or "") if has_keyword else False

        should_have = has_keyword and not is_bl
        currently_has = any(r in member.roles for r in roles_to_handle)

        if should_have and not currently_has:
            # Assign reward roles
            try:
                await member.add_roles(*roles_to_handle, reason="Vanity keyword detected in status.")
                
                # Notification Logic
                async with self._get_db() as db:
                    cursor = await db.execute("SELECT channel_id FROM vanity_channels WHERE guild_id = ?", (member.guild.id,))
                    channel_ids = [r[0] for r in await cursor.fetchall()]

                if settings["message_template"]:
                    msg_content = self._parse_variables(settings["message_template"], member, after_status)
                    embed = self._create_success_embed("Vanity Reward", msg_content)
                    for cid in channel_ids:
                        chan = member.guild.get_channel(cid)
                        if chan:
                            try:
                                await chan.send(embed=embed)
                            except:
                                pass
            except discord.Forbidden:
                logger.warning(f"Vanity: Hierarchy error in {member.guild.name} for {member.name}")
            except Exception as e:
                logger.error(f"Vanity: Error adding roles: {e}")

        elif not should_have and currently_has:
            # Remove roles
            try:
                roles_present = [r for r in roles_to_handle if r in member.roles]
                if roles_present:
                    await member.remove_roles(*roles_present, reason="Vanity keyword removed/blacklisted.")
            except discord.Forbidden:
                pass
            except Exception as e:
                logger.error(f"Vanity: Error removing roles: {e}")

    # ========================= EVENT LISTENERS =========================

    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        """Intercepts custom status changes."""
        if after.bot:
            return

        def get_custom_status(member: discord.Member) -> Optional[str]:
            for activity in member.activities:
                if isinstance(activity, discord.CustomActivity):
                    return activity.state
            return None

        before_status = get_custom_status(before)
        after_status = get_custom_status(after)

        if before_status == after_status:
            return

        await self._update_member_vanity(after, after_status)

    # ========================= COMMANDS =========================

    @commands.group(name="vanity", invoke_without_command=True)
    @commands.guild_only()
    async def vanity_group(self, ctx: commands.Context):
        """Displays the vanity configuration help menu."""
        embed = self._create_embed("✨ VOTOX Vanity System", "Reward users for supporting your server in their status!")
        p = ctx.clean_prefix
        embed.add_field(name="General Commands", value=(
            f"`{p}vanity set [keyword]` - Set the status keyword.\n"
            f"`{p}vanity sync` - Force update all server members.\n"
            f"`{p}vanity variables` - View available placeholders."
        ), inline=False)
        embed.add_field(name="Subgroups", value=(
            f"`{p}vanity role ...` - Manage reward roles.\n"
            f"`{p}vanity channels ...` - Manage notification channels.\n"
            f"`{p}vanity message ...` - Manage notification templates.\n"
            f"`{p}vanity blacklist ...` - Manage exclusions."
        ), inline=False)
        await ctx.send(embed=embed)

    @vanity_group.command(name="set")
    @commands.has_permissions(administrator=True)
    async def vanity_set(self, ctx: commands.Context, *, keyword: str):
        """Sets the keyword required for vanity roles."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT INTO vanity_settings (guild_id, keyword) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET keyword = ?",
                (ctx.guild.id, keyword, keyword)
            )
            await db.commit()
        await ctx.send(embed=self._create_success_embed("Keyword Updated", f"Keyword set to: `{keyword}`"))

    @vanity_group.command(name="sync")
    @commands.has_permissions(administrator=True)
    async def vanity_sync(self, ctx: commands.Context):
        """Manually syncs vanity roles for all members."""
        msg = await ctx.send(embed=self._create_info_embed("Vanity Sync", "Starting server-wide presence sync..."))

        def get_custom_status(member: discord.Member) -> Optional[str]:
            for activity in member.activities:
                if isinstance(activity, discord.CustomActivity):
                    return activity.state
            return None

        count = 0
        for member in ctx.guild.members:
            if member.bot:
                continue
            await self._update_member_vanity(member, get_custom_status(member))
            count += 1

        await msg.edit(embed=self._create_success_embed("Sync Complete", f"Processed **{count}** members."))

    # --- Role Management ---
    @vanity_group.group(name="role", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def vanity_role(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @vanity_role.command(name="add")
    @commands.has_permissions(administrator=True)
    async def vanity_role_add(self, ctx: commands.Context, role: discord.Role):
        async with self._get_db() as db:
            try:
                await db.execute("INSERT INTO vanity_roles (guild_id, role_id) VALUES (?, ?)", (ctx.guild.id, role.id))
                await db.commit()
                await ctx.send(embed=self._create_success_embed("Role Added", f"{role.mention} is now a reward role."))
            except aiosqlite.IntegrityError:
                await ctx.send(embed=self._create_error_embed("Duplicate", "This role is already configured."))

    @vanity_role.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def vanity_role_remove(self, ctx: commands.Context, role: discord.Role):
        async with self._get_db() as db:
            await db.execute("DELETE FROM vanity_roles WHERE guild_id = ? AND role_id = ?", (ctx.guild.id, role.id))
            await db.commit()
        await ctx.send(embed=self._create_success_embed("Role Removed", f"Removed {role.mention} from rewards."))

    @vanity_role.command(name="list")
    @commands.has_permissions(administrator=True)
    async def vanity_role_list(self, ctx: commands.Context):
        r_ids = await self._get_vanity_roles(ctx.guild.id)
        mentions = [ctx.guild.get_role(rid).mention for rid in r_ids if ctx.guild.get_role(rid)]
        await ctx.send(embed=self._create_info_embed("Vanity Reward Roles", "\n".join(mentions) or "None configured."))

    # --- Channel Management ---
    @vanity_group.group(name="channels", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def vanity_channels_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @vanity_channels_group.command(name="add")
    @commands.has_permissions(administrator=True)
    async def vanity_channels_add(self, ctx: commands.Context, channel: discord.TextChannel):
        async with self._get_db() as db:
            await db.execute("INSERT OR IGNORE INTO vanity_channels (guild_id, channel_id) VALUES (?, ?)", (ctx.guild.id, channel.id))
            await db.commit()
        await ctx.send(embed=self._create_success_embed("Channel Added", f"Vanity logs will be sent to {channel.mention}."))

    @vanity_channels_group.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def vanity_channels_remove(self, ctx: commands.Context, channel: discord.TextChannel):
        async with self._get_db() as db:
            await db.execute("DELETE FROM vanity_channels WHERE guild_id = ? AND channel_id = ?", (ctx.guild.id, channel.id))
            await db.commit()
        await ctx.send(embed=self._create_success_embed("Channel Removed", f"Removed {channel.mention} from logs."))

    @vanity_channels_group.command(name="view")
    @commands.has_permissions(administrator=True)
    async def vanity_channels_view(self, ctx: commands.Context):
        async with self._get_db() as db:
            cursor = await db.execute("SELECT channel_id FROM vanity_channels WHERE guild_id = ?", (ctx.guild.id,))
            c_ids = [r[0] for r in await cursor.fetchall()]
        mentions = [f"<#{cid}>" for cid in c_ids if ctx.guild.get_channel(cid)]
        await ctx.send(embed=self._create_info_embed("Vanity Notification Channels", "\n".join(mentions) or "None configured."))

    # --- Blacklist Management ---
    @vanity_group.group(name="blacklist", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def vanity_blacklist_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @vanity_blacklist_group.command(name="user")
    @commands.has_permissions(administrator=True)
    async def vanity_bl_user(self, ctx: commands.Context, user: Union[discord.Member, discord.User]):
        async with self._get_db() as db:
            await db.execute("INSERT OR IGNORE INTO vanity_blacklist_users (guild_id, user_id) VALUES (?, ?)", (ctx.guild.id, user.id))
            await db.commit()
        await ctx.send(embed=self._create_success_embed("Blacklisted User", f"Blocked {user.mention} from vanity."))

    @vanity_blacklist_group.command(name="role")
    @commands.has_permissions(administrator=True)
    async def vanity_bl_role(self, ctx: commands.Context, role: discord.Role):
        async with self._get_db() as db:
            await db.execute("INSERT OR IGNORE INTO vanity_blacklist_roles (guild_id, role_id) VALUES (?, ?)", (ctx.guild.id, role.id))
            await db.commit()
        await ctx.send(embed=self._create_success_embed("Blacklisted Role", f"Role {role.mention} is now excluded."))

    @vanity_blacklist_group.command(name="text")
    @commands.has_permissions(administrator=True)
    async def vanity_bl_text(self, ctx: commands.Context, *, text: str):
        async with self._get_db() as db:
            await db.execute("INSERT OR IGNORE INTO vanity_blacklist_text (guild_id, blocked_text) VALUES (?, ?)", (ctx.guild.id, text))
            await db.commit()
        await ctx.send(embed=self._create_success_embed("Blacklisted Text", f"Statuses containing `{text}` will be ignored."))

    @vanity_blacklist_group.command(name="list")
    @commands.has_permissions(administrator=True)
    async def vanity_bl_list(self, ctx: commands.Context):
        async with self._get_db() as db:
            cursor = await db.execute("SELECT user_id FROM vanity_blacklist_users WHERE guild_id = ?", (ctx.guild.id,))
            u_ids = [r[0] for r in await cursor.fetchall()]
            cursor = await db.execute("SELECT role_id FROM vanity_blacklist_roles WHERE guild_id = ?", (ctx.guild.id,))
            r_ids = [r[0] for r in await cursor.fetchall()]
            cursor = await db.execute("SELECT blocked_text FROM vanity_blacklist_text WHERE guild_id = ?", (ctx.guild.id,))
            txts = [r[0] for r in await cursor.fetchall()]

        embed = self._create_info_embed("Vanity Blacklist", "Current exclusions for this server.")
        embed.add_field(name="Users", value=", ".join([f"<@{uid}>" for uid in u_ids]) or "None", inline=False)
        embed.add_field(name="Roles", value=", ".join([f"<@&{rid}>" for rid in r_ids]) or "None", inline=False)
        embed.add_field(name="Text Patterns", value=", ".join([f"`{t}`" for t in txts]) or "None", inline=False)
        await ctx.send(embed=embed)

    # --- Unblacklist Subgroup ---
    @vanity_group.group(name="unblacklist", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def vanity_unblacklist_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @vanity_unblacklist_group.command(name="user")
    async def vanity_ub_user(self, ctx: commands.Context, user: discord.User):
        async with self._get_db() as db:
            await db.execute("DELETE FROM vanity_blacklist_users WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, user.id))
            await db.commit()
        await ctx.send(embed=self._create_success_embed("Unblacklisted", f"Removed {user.mention} from blacklist."))

    # --- Message Management ---
    @vanity_group.group(name="message", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def vanity_message_group(self, ctx: commands.Context):
        await ctx.send_help(ctx.command)

    @vanity_message_group.command(name="set")
    async def vanity_msg_set(self, ctx: commands.Context, *, text: str):
        async with self._get_db() as db:
            await db.execute("UPDATE vanity_settings SET message_template = ? WHERE guild_id = ?", (text, ctx.guild.id))
            await db.commit()
        await ctx.send(embed=self._create_success_embed("Template Updated", f"New notification set:\n{text}"))

    @vanity_message_group.command(name="view")
    async def vanity_msg_view(self, ctx: commands.Context):
        settings = await self._get_vanity_settings(ctx.guild.id)
        await ctx.send(embed=self._create_info_embed("Vanity Message", f"```{settings['message_template'] or 'None'}```"))

    @vanity_message_group.command(name="preview")
    async def vanity_msg_preview(self, ctx: commands.Context):
        settings = await self._get_vanity_settings(ctx.guild.id)
        if not settings["message_template"]:
            return await ctx.send(embed=self._create_error_embed("No Template", "Please set a message template first."))
        preview = self._parse_variables(settings["message_template"], ctx.author, "I love VOTOX!")
        await ctx.send(embed=self._create_success_embed("Message Preview", preview))

    @vanity_group.command(name="variables", aliases=["vars"])
    async def vanity_variables(self, ctx: commands.Context):
        """Displays placeholders for the vanity message."""
        desc = (
            "Use these placeholders in your `,vanity message set` text:\n\n"
            "`<<user.mention>>` - Mentions the user.\n"
            "`<<user>>` - User's display name.\n"
            "`<<guild.name>>` - Server name.\n"
            "`<<status>>` - User's exact custom status."
        )
        await ctx.send(embed=self._create_info_embed("Available Placeholders", desc))


async def setup(bot: commands.Bot):
    """Loads the Vanity cog into VOTOX."""
    await bot.add_cog(Vanity(bot))