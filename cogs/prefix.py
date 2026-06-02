

import discord
from discord.ext import commands
import aiosqlite
import logging
from pathlib import Path
from typing import List, Optional, Union

logger = logging.getLogger("VOTOX")
DB_PATH = Path(__file__).parent.parent / "database" / "votox.db"
DEFAULT_PREFIXES = [".", ","]

async def get_prefix(bot: commands.Bot, message: discord.Message) -> List[str]:
    """
    Dynamic prefix hook for VOTOX.
    Queries the database for guild-level, user-level, and noprefix settings.
    """
    prefixes = list(DEFAULT_PREFIXES)

    if not message.guild:
        return prefixes

    try:
        async with aiosqlite.connect(DB_PATH) as db:
            # 1. Fetch Guild Custom Prefixes
            async with db.execute(
                "SELECT prefix FROM guild_prefixes WHERE guild_id = ?", 
                (message.guild.id,)
            ) as cursor:
                guild_rows = await cursor.fetchall()
                for row in guild_rows:
                    prefixes.append(row[0])

            # 2. Fetch User Personal Prefix
            async with db.execute(
                "SELECT prefix FROM user_prefixes WHERE user_id = ?", 
                (message.author.id,)
            ) as cursor:
                user_row = await cursor.fetchone()
                if user_row:
                    prefixes.append(user_row[0])

            # 3. Check No-Prefix Mode
            async with db.execute(
                "SELECT no_prefix_enabled FROM guild_settings WHERE guild_id = ?", 
                (message.guild.id,)
            ) as cursor:
                settings_row = await cursor.fetchone()
                if settings_row and settings_row[0] == 1:
                    # Adding an empty string allows command execution without any prefix
                    prefixes.append("")

    except Exception as e:
        logger.error(f"Error in dynamic prefix hook: {e}")
        # Fallback to defaults on error
        return DEFAULT_PREFIXES

    return commands.when_mentioned_or(*prefixes)(bot, message)


class Prefix(commands.Cog):
    """
    Manage dynamic, customizable prefixes on a guild and user level.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = DB_PATH

    def _get_db(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Automatically initialize prefix tables."""
        async with self._get_db() as db:
            # Guild-specific authorized prefixes
            await db.execute('''
                CREATE TABLE IF NOT EXISTS guild_prefixes (
                    guild_id INTEGER,
                    prefix TEXT,
                    PRIMARY KEY (guild_id, prefix)
                )
            ''')
            # Personal prefixes that work across all shared guilds
            await db.execute('''
                CREATE TABLE IF NOT EXISTS user_prefixes (
                    user_id INTEGER PRIMARY KEY,
                    prefix TEXT
                )
            ''')
            # Guild-wide settings (e.g., No-Prefix mode)
            await db.execute('''
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    no_prefix_enabled INTEGER DEFAULT 0
                )
            ''')
            # Migration: Ensure the no_prefix_enabled column exists if the table was created previously
            try:
                await db.execute("SELECT no_prefix_enabled FROM guild_settings LIMIT 1")
            except aiosqlite.OperationalError:
                await db.execute("ALTER TABLE guild_settings ADD COLUMN no_prefix_enabled INTEGER DEFAULT 0")

            await db.commit()

    # ========================= HELPER METHODS =========================

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
        embed.set_footer(text="VOTOX Prefix Management", icon_url=self.bot.user.display_avatar.url)
        return embed

    def _create_success_embed(self, title: str, description: str) -> discord.Embed:
        return self._create_embed(f"✅ {title}", description, discord.Color.green())

    def _create_error_embed(self, title: str, description: str) -> discord.Embed:
        return self._create_embed(f"❌ {title}", description, discord.Color.red())

    # ========================= COMMANDS =========================

    @commands.group(name="prefixes", aliases=["prefix"], invoke_without_command=True)
    @commands.guild_only()
    async def prefixes_group(self, ctx: commands.Context):
        """Displays the elegant help menu for prefix management."""
        embed = self._create_embed(
            "⌨️ VOTOX Prefix System", 
            "Manage how you and your server interact with VOTOX commands."
        )
        
        prefix = ctx.clean_prefix
        embed.add_field(
            name="Server Commands (Staff Only)", 
            value=(
                f"`{prefix}prefixes add [prefix]` - Add a guild prefix\n"
                f"`{prefix}prefixes remove [prefix]` - Remove a guild prefix\n"
                f"`{prefix}prefixes noprefix [on/off]` - Toggle no-prefix mode"
            ), 
            inline=False
        )
        
        embed.add_field(
            name="Personal Commands", 
            value=(
                f"`{prefix}prefixes self [prefix]` - Set your personal prefix\n"
                f"`{prefix}prefixes list` - Show active prefixes"
            ), 
            inline=False
        )

        embed.add_field(
            name="Default Prefixes",
            value=", ".join([f"`{p}`" for p in DEFAULT_PREFIXES]),
            inline=True
        )

        await ctx.send(embed=embed)

    @prefixes_group.command(name="add")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def prefixes_add(self, ctx: commands.Context, prefix: str):
        """Adds a custom prefix to the server's authorized prefixes list."""
        if len(prefix) > 10:
            return await ctx.send(embed=self._create_error_embed("Invalid Prefix", "Prefixes cannot exceed 10 characters."))

        try:
            async with self._get_db() as db:
                await db.execute(
                    "INSERT INTO guild_prefixes (guild_id, prefix) VALUES (?, ?)", 
                    (ctx.guild.id, prefix)
                )
                await db.commit()
            
            await ctx.send(embed=self._create_success_embed(
                "Prefix Added", 
                f"The prefix `{prefix}` is now authorized for **{ctx.guild.name}**."
            ))
        except aiosqlite.IntegrityError:
            await ctx.send(embed=self._create_error_embed("Duplicate Prefix", f"`{prefix}` is already in the server list."))

    @prefixes_group.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def prefixes_remove(self, ctx: commands.Context, prefix: str):
        """Removes a server-wide prefix from the database."""
        async with self._get_db() as db:
            cursor = await db.execute(
                "DELETE FROM guild_prefixes WHERE guild_id = ? AND prefix = ?", 
                (ctx.guild.id, prefix)
            )
            await db.commit()

            if cursor.rowcount == 0:
                return await ctx.send(embed=self._create_error_embed("Not Found", f"`{prefix}` is not a custom prefix in this server."))
            
            await ctx.send(embed=self._create_success_embed(
                "Prefix Removed", 
                f"Removed `{prefix}` from the authorized server prefixes."
            ))

    @prefixes_group.command(name="self")
    async def prefixes_self(self, ctx: commands.Context, prefix: Optional[str] = None):
        """Sets a personal custom prefix for the command executor."""
        if not prefix:
            async with self._get_db() as db:
                await db.execute("DELETE FROM user_prefixes WHERE user_id = ?", (ctx.author.id,))
                await db.commit()
            return await ctx.send(embed=self._create_success_embed("Personal Prefix Reset", "Your personal prefix has been cleared."))

        if len(prefix) > 10:
            return await ctx.send(embed=self._create_error_embed("Invalid Prefix", "Personal prefixes cannot exceed 10 characters."))

        async with self._get_db() as db:
            await db.execute(
                "INSERT INTO user_prefixes (user_id, prefix) VALUES (?, ?) ON CONFLICT(user_id) DO UPDATE SET prefix = ?", 
                (ctx.author.id, prefix, prefix)
            )
            await db.commit()

        await ctx.send(embed=self._create_success_embed(
            "Personal Prefix Set", 
            f"Your personal prefix is now `{prefix}`. This works in any server we share!"
        ))

    @prefixes_group.command(name="list")
    @commands.guild_only()
    async def prefixes_list(self, ctx: commands.Context):
        """Displays all configured prefixes for the server and the user."""
        guild_prefixes = []
        user_prefix = None
        noprefix_mode = False

        async with self._get_db() as db:
            # Fetch Guild Prefixes
            async with db.execute("SELECT prefix FROM guild_prefixes WHERE guild_id = ?", (ctx.guild.id,)) as cursor:
                guild_prefixes = [row[0] for row in await cursor.fetchall()]
            
            # Fetch User Prefix
            async with db.execute("SELECT prefix FROM user_prefixes WHERE user_id = ?", (ctx.author.id,)) as cursor:
                row = await cursor.fetchone()
                user_prefix = row[0] if row else None
            
            # Fetch Noprefix Setting
            async with db.execute("SELECT no_prefix_enabled FROM guild_settings WHERE guild_id = ?", (ctx.guild.id,)) as cursor:
                row = await cursor.fetchone()
                noprefix_mode = bool(row[0]) if row else False

        embed = self._create_embed(f"📋 Prefix List for {ctx.guild.name}")
        
        # Default Section
        embed.add_field(
            name="Default Prefixes", 
            value=" ".join([f"`{p}`" for p in DEFAULT_PREFIXES]), 
            inline=False
        )

        # Guild Section
        guild_val = " ".join([f"`{p}`" for p in guild_prefixes]) if guild_prefixes else "None configured."
        embed.add_field(name="Server Prefixes", value=guild_val, inline=False)

        # User Section
        user_val = f"`{user_prefix}`" if user_prefix else "None set (using server defaults)."
        embed.add_field(name="Your Personal Prefix", value=user_val, inline=False)

        # Noprefix Section
        status = "✅ Enabled" if noprefix_mode else "❌ Disabled"
        embed.add_field(name="No-Prefix Execution", value=status, inline=True)
        
        # Mention always works
        embed.add_field(name="Direct Mention", value=f"{self.bot.user.mention}", inline=True)

        await ctx.send(embed=embed)

    @prefixes_group.command(name="noprefix")
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def prefixes_noprefix(self, ctx: commands.Context, toggle: str):
        """Toggles 'No-Prefix' mode for the server."""
        toggle = toggle.lower()
        if toggle not in ["on", "off", "enable", "disable"]:
            return await ctx.send(embed=self._create_error_embed("Invalid Argument", "Please use `on` or `off`."))

        state = 1 if toggle in ["on", "enable"] else 0
        
        async with self._get_db() as db:
            await db.execute(
                "INSERT INTO guild_settings (guild_id, no_prefix_enabled) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET no_prefix_enabled = ?", 
                (ctx.guild.id, state, state)
            )
            await db.commit()

        msg = "enabled" if state == 1 else "disabled"
        embed = self._create_success_embed(
            "No-Prefix Mode Updated", 
            f"No-Prefix mode has been **{msg}** for this server."
        )
        if state == 1:
            embed.set_footer(text="Users can now run commands by typing the command name directly.")
            
        await ctx.send(embed=embed)

    # ========================= ERROR HANDLING =========================

    @prefixes_add.error
    @prefixes_remove.error
    @prefixes_noprefix.error
    async def prefix_permissions_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=self._create_error_embed(
                "Access Denied", 
                "You require `Manage Server` permissions to modify guild prefixes."
            ))
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send(embed=self._create_error_embed("Guild Only", "This command can only be used within a server."))

async def setup(bot: commands.Bot):
    """Setup the Prefix cog."""
    await bot.add_cog(Prefix(bot))
