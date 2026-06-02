

import discord
from discord.ext import commands
from typing import Optional, Dict, Any, Union
import aiosqlite
from pathlib import Path
import logging

logger = logging.getLogger("VOTOX")

class WelcomeLeave(commands.Cog):
    """
    Handles welcoming new members and tracking departures in a single, robust cog.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"

    def _get_db(self) -> aiosqlite.Connection:
        """Returns an aiosqlite connection context manager."""
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initializes database tables for welcome and leave settings."""
        async with self._get_db() as db:
            # Welcome Settings Table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS welcome_settings (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    message TEXT,
                    embed_enabled INTEGER DEFAULT 0,
                    embed_title TEXT,
                    embed_image TEXT,
                    embed_footer TEXT
                )
            ''')
            # Leave Settings Table
            await db.execute('''
                CREATE TABLE IF NOT EXISTS leave_settings (
                    guild_id INTEGER PRIMARY KEY,
                    channel_id INTEGER,
                    message TEXT,
                    embed_enabled INTEGER DEFAULT 0,
                    embed_title TEXT,
                    embed_image TEXT,
                    embed_footer TEXT
                )
            ''')
            await db.commit()

    # ========================= HELPER METHODS (DRY) =========================

    def _parse_variables(self, text: str, member: discord.Member) -> str:
        """Replaces VOTOX placeholders with dynamic member/guild data."""
        if not text:
            return ""
        
        replacements = {
            "<<user.mention>>": member.mention,
            "<<user>>": member.display_name,
            "<<guild.name>>": member.guild.name,
            "<<guild.count>>": str(member.guild.member_count)
        }
        
        for key, value in replacements.items():
            text = text.replace(key, value)
        return text

    async def _get_config(self, guild_id: int, table: str) -> Dict[str, Any]:
        """Generic helper to fetch configuration from a specific table."""
        async with self._get_db() as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(f"SELECT * FROM {table} WHERE guild_id = ?", (guild_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return dict(row)
                
                # Default values if no entry exists
                return {
                    "guild_id": guild_id,
                    "channel_id": None,
                    "message": "Welcome <<user.mention>> to <<guild.name>>!" if table == "welcome_settings" else "<<user>> has left us.",
                    "embed_enabled": 0,
                    "embed_title": "Welcome!",
                    "embed_image": None,
                    "embed_footer": "VOTOX System"
                }

    async def _update_config(self, guild_id: int, table: str, column: str, value: Any):
        """Generic helper to update a configuration field."""
        async with self._get_db() as db:
            # Ensure entry exists
            await db.execute(f"INSERT OR IGNORE INTO {table} (guild_id) VALUES (?)", (guild_id,))
            # Update value
            await db.execute(f"UPDATE {table} SET {column} = ? WHERE guild_id = ?", (value, guild_id))
            await db.commit()

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        """Standard VOTOX styled embed."""
        embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
        embed.set_footer(text="VOTOX System", icon_url=self.bot.user.display_avatar.url)
        return embed

    async def _dispatch_notification(self, member: discord.Member, mode: str):
        """Unified logic to send join/leave notifications."""
        table = "welcome_settings" if mode == "welcome" else "leave_settings"
        config = await self._get_config(member.guild.id, table)

        if not config["channel_id"]:
            return

        channel = member.guild.get_channel(config["channel_id"])
        if not channel:
            return

        try:
            content = self._parse_variables(config["message"], member)
            
            if config["embed_enabled"]:
                embed = discord.Embed(
                    title=self._parse_variables(config["embed_title"], member),
                    description=content,
                    color=self.bot.embed_color if hasattr(self.bot, 'embed_color') else discord.Color.blurple()
                )
                if config["embed_image"]:
                    embed.set_image(url=config["embed_image"])
                if config["embed_footer"]:
                    embed.set_footer(text=self._parse_variables(config["embed_footer"], member))
                
                await channel.send(embed=embed)
            else:
                await channel.send(content)
        except (discord.Forbidden, discord.HTTPException) as e:
            logger.error(f"Failed to send {mode} message in {member.guild.id}: {e}")

    # ========================= GREET COMMANDS =========================

    @commands.group(name="greet", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def greet(self, ctx: commands.Context):
        """Displays the welcome configuration help menu."""
        embed = self._create_embed("🎉 VOTOX Greet Configuration", "Manage how new members are welcomed.")
        p = ctx.clean_prefix
        embed.add_field(name="Setup Commands", value=(
            f"`{p}greet channel [channel]` - Set destination.\n"
            f"`{p}greet mode [on/off]` - Toggle embed mode.\n"
            f"`{p}greet message [text]` - Set notification text.\n"
            f"`{p}greet variables` - View placeholders."
        ), inline=False)
        embed.add_field(name="Embed Customization", value=(
            f"`{p}greet embed title [text]`\n"
            f"`{p}greet embed image [url]`\n"
            f"`{p}greet embed footer [text]`"
        ), inline=False)
        embed.add_field(name="Utility", value=f"`{p}greet test` - Simulate a join event.", inline=False)
        await ctx.send(embed=embed)

    @greet.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def greet_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Sets the welcome message channel."""
        await self._update_config(ctx.guild.id, "welcome_settings", "channel_id", channel.id)
        await ctx.send(embed=self._create_embed("✅ Channel Set", f"Welcome messages will be sent to {channel.mention}.", discord.Color.green()))

    @greet.command(name="embed")
    @commands.has_permissions(administrator=True)
    async def greet_embed_toggle(self, ctx: commands.Context, status: str):
        """Toggles embed mode for greetings."""
        state = 1 if status.lower() == "on" else 0
        await self._update_config(ctx.guild.id, "welcome_settings", "embed_enabled", state)
        msg = "ENABLED" if state else "DISABLED"
        await ctx.send(embed=self._create_embed("✅ Embed Mode Updated", f"Greeting embeds are now **{msg}**.", discord.Color.green()))

    @greet.command(name="message")
    @commands.has_permissions(administrator=True)
    async def greet_message(self, ctx: commands.Context, *, text: str):
        """Sets the greeting message text."""
        await self._update_config(ctx.guild.id, "welcome_settings", "message", text)
        await ctx.send(embed=self._create_embed("✅ Message Updated", f"New greeting set:\n`{text}`", discord.Color.green()))

    @greet.group(name="embed", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def greet_embed_sub(self, ctx: commands.Context):
        """Manage embed frame details."""
        await ctx.send_help(ctx.command)

    async def _greet_embed_guard(self, ctx: commands.Context) -> bool:
        """Internal check to see if embed mode is enabled before allowing subcommands."""
        config = await self._get_config(ctx.guild.id, "welcome_settings")
        if not config["embed_enabled"]:
            await ctx.send(embed=self._create_embed("❌ Action Locked", "Embed mode is currently **OFF**. Enable it with `.greet embed on` first.", discord.Color.red()))
            return False
        return True

    @greet_embed_sub.command(name="title")
    async def greet_title(self, ctx: commands.Context, *, text: str):
        if await self._greet_embed_guard(ctx):
            await self._update_config(ctx.guild.id, "welcome_settings", "embed_title", text)
            await ctx.send(embed=self._create_embed("✅ Title Updated", f"Embed title set to: `{text}`", discord.Color.green()))

    @greet_embed_sub.command(name="image")
    async def greet_image(self, ctx: commands.Context, url: str):
        if await self._greet_embed_guard(ctx):
            await self._update_config(ctx.guild.id, "welcome_settings", "embed_image", url)
            await ctx.send(embed=self._create_embed("✅ Image Updated", "The welcome embed will now feature a custom image.", discord.Color.green()))

    @greet_embed_sub.command(name="footer")
    async def greet_footer(self, ctx: commands.Context, *, text: str):
        if await self._greet_embed_guard(ctx):
            await self._update_config(ctx.guild.id, "welcome_settings", "embed_footer", text)
            await ctx.send(embed=self._create_embed("✅ Footer Updated", f"Embed footer set to: `{text}`", discord.Color.green()))

    @greet.command(name="variables")
    async def greet_vars(self, ctx: commands.Context):
        """Displays available welcome placeholders."""
        desc = (
            "`<<user.mention>>` - Mentions the user.\n"
            "`<<user>>` - User's display name.\n"
            "`<<guild.name>>` - Server name.\n"
            "`<<guild.count>>` - Total members."
        )
        await ctx.send(embed=self._create_embed("📋 Welcome Placeholders", desc))

    @greet.command(name="test")
    @commands.has_permissions(administrator=True)
    async def greet_test(self, ctx: commands.Context):
        """Simulates a member joining."""
        await ctx.send("⌛ Simulating join event...")
        await self._dispatch_notification(ctx.author, "welcome")

    # ========================= LEAVE COMMANDS =========================

    @commands.group(name="leave", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def leave(self, ctx: commands.Context):
        """Displays the leave configuration help menu."""
        embed = self._create_embed("👋 VOTOX Leave Configuration", "Manage how leaving members are tracked.")
        p = ctx.clean_prefix
        embed.add_field(name="Setup Commands", value=(
            f"`{p}leave channel [channel]` - Set destination.\n"
            f"`{p}leave mode [on/off]` - Toggle embed mode.\n"
            f"`{p}leave message [text]` - Set notification text.\n"
            f"`{p}leave variables` - View placeholders."
        ), inline=False)
        embed.add_field(name="Embed Customization", value=(
            f"`{p}leave embed title [text]`\n"
            f"`{p}leave embed image [url]`\n"
            f"`{p}leave embed footer [text]`"
        ), inline=False)
        embed.add_field(name="Utility", value=f"`{p}leave test` - Simulate a leave event.", inline=False)
        await ctx.send(embed=embed)

    @leave.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def leave_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """Sets the leave message channel."""
        await self._update_config(ctx.guild.id, "leave_settings", "channel_id", channel.id)
        await ctx.send(embed=self._create_embed("✅ Channel Set", f"Leave messages will be sent to {channel.mention}.", discord.Color.green()))

    @leave.command(name="embed")
    @commands.has_permissions(administrator=True)
    async def leave_embed_toggle(self, ctx: commands.Context, status: str):
        """Toggles embed mode for departures."""
        state = 1 if status.lower() == "on" else 0
        await self._update_config(ctx.guild.id, "leave_settings", "embed_enabled", state)
        msg = "ENABLED" if state else "DISABLED"
        await ctx.send(embed=self._create_embed("✅ Embed Mode Updated", f"Leave embeds are now **{msg}**.", discord.Color.green()))

    @leave.command(name="message")
    @commands.has_permissions(administrator=True)
    async def leave_message(self, ctx: commands.Context, *, text: str):
        """Sets the leave message text."""
        await self._update_config(ctx.guild.id, "leave_settings", "message", text)
        await ctx.send(embed=self._create_embed("✅ Message Updated", f"New leave text set:\n`{text}`", discord.Color.green()))

    @leave.group(name="embed", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def leave_embed_sub(self, ctx: commands.Context):
        """Manage embed frame details for departures."""
        await ctx.send_help(ctx.command)

    async def _leave_embed_guard(self, ctx: commands.Context) -> bool:
        """Internal check to see if embed mode is enabled before allowing subcommands."""
        config = await self._get_config(ctx.guild.id, "leave_settings")
        if not config["embed_enabled"]:
            await ctx.send(embed=self._create_embed("❌ Action Locked", "Embed mode is currently **OFF**. Enable it with `.leave embed on` first.", discord.Color.red()))
            return False
        return True

    @leave_embed_sub.command(name="title")
    async def leave_title(self, ctx: commands.Context, *, text: str):
        if await self._leave_embed_guard(ctx):
            await self._update_config(ctx.guild.id, "leave_settings", "embed_title", text)
            await ctx.send(embed=self._create_embed("✅ Title Updated", f"Embed title set to: `{text}`", discord.Color.green()))

    @leave_embed_sub.command(name="image")
    async def leave_image(self, ctx: commands.Context, url: str):
        if await self._leave_embed_guard(ctx):
            await self._update_config(ctx.guild.id, "leave_settings", "embed_image", url)
            await ctx.send(embed=self._create_embed("✅ Image Updated", "The leave embed will now feature a custom image.", discord.Color.green()))

    @leave_embed_sub.command(name="footer")
    async def leave_footer(self, ctx: commands.Context, *, text: str):
        if await self._leave_embed_guard(ctx):
            await self._update_config(ctx.guild.id, "leave_settings", "embed_footer", text)
            await ctx.send(embed=self._create_embed("✅ Footer Updated", f"Embed footer set to: `{text}`", discord.Color.green()))

    @leave.command(name="variables")
    async def leave_vars(self, ctx: commands.Context):
        """Displays available leave placeholders."""
        desc = (
            "`<<user.mention>>` - Mentions the user.\n"
            "`<<user>>` - User's display name.\n"
            "`<<guild.name>>` - Server name.\n"
            "`<<guild.count>>` - Total members."
        )
        await ctx.send(embed=self._create_embed("📋 Leave Placeholders", desc))

    @leave.command(name="test")
    @commands.has_permissions(administrator=True)
    async def leave_test(self, ctx: commands.Context):
        """Simulates a member leaving."""
        await ctx.send("⌛ Simulating leave event...")
        await self._dispatch_notification(ctx.author, "leave")

    # ========================= EVENT LISTENERS =========================

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Fires when a new user joins the guild."""
        await self._dispatch_notification(member, "welcome")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Fires when a user leaves the guild."""
        await self._dispatch_notification(member, "leave")

async def setup(bot: commands.Bot):
    """Loads the WelcomeLeave cog into VOTOX."""
    await bot.add_cog(WelcomeLeave(bot))