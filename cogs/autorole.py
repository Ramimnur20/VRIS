

import discord
from discord.ext import commands
from typing import Dict, Optional, Tuple
import logging
import aiosqlite
from pathlib import Path

logger = logging.getLogger("VOTOX")


class Autorole(commands.Cog):
    """
    Automatic role assignment cog for VOTOX.
    
    Manages automatic role assignment for new members (humans and bots) based on
    per-guild configurations. Supports separate roles for humans, bots, and a
    unified role for both member types.
    """
    
    def __init__(self, bot: commands.Bot):
        """
        Initialize the Autorole cog.
        
        Args:
            bot: The Discord bot instance.
        """
        self.bot = bot
        
        # Database configuration
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        self._cache: Dict[int, Dict[str, Optional[int]]] = {}
        
        # In-memory fallback (populated from DB)
        self.autorole_config: Dict[int, Dict[str, Optional[int]]] = {}
    
    def _get_db(self) -> aiosqlite.Connection:
        """Return a connection context manager for the SQLite database."""
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initialize database tables for autorole."""
        async with self._get_db() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS autorole_config (
                    guild_id INTEGER PRIMARY KEY,
                    humans_role_id INTEGER,
                    bots_role_id INTEGER,
                    both_role_id INTEGER,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await db.commit()

    async def _get_guild_config(self, guild_id: int) -> Dict[str, Optional[int]]:
        """Retrieve or initialize the autorole configuration for a guild from the DB."""
        # Check cache first
        if guild_id in self._cache:
            return self._cache[guild_id]
        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT humans_role_id, bots_role_id, both_role_id FROM autorole_config WHERE guild_id = ?",
                (guild_id,)
            )
            row = await cursor.fetchone()
            if row:
                config = {"humans": row[0], "bots": row[1], "both": row[2]}
            else:
                config = {"humans": None, "bots": None, "both": None}
        self._cache[guild_id] = config
        return config

    async def _save_guild_config(self, guild_id: int, config: Dict[str, Optional[int]]) -> None:
        """Persist the autorole configuration for a guild to the DB."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO autorole_config (guild_id, humans_role_id, bots_role_id, both_role_id, updated_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)",
                (guild_id, config.get("humans"), config.get("bots"), config.get("both"))
            )
            await db.commit()
        self._cache[guild_id] = config
    
    def _verify_role_assignable(self, guild: discord.Guild, role: discord.Role) -> Tuple[bool, Optional[str]]:
        """
        Verify that the bot can assign a given role.
        
        Args:
            guild: The Discord guild.
            role: The role to verify.
        
        Returns:
            Tuple of (is_assignable: bool, error_message: Optional[str])
        """
        bot_role = guild.me.top_role
        
        if role >= bot_role:
            return False, f"The role {role.mention} is at or above my highest role {bot_role.mention}. I cannot assign this role."
        
        return True, None
    
    def _create_embed(self, title: str, description: str = "", color: Optional[int] = None) -> discord.Embed:
        """
        Create a styled embed with consistent branding.
        
        Args:
            title: The embed title.
            description: The embed description.
            color: The embed color (defaults to bot's embed color).
        
        Returns:
            A Discord Embed object.
        """
        if color is None:
            color = self.bot.embed_color
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=color
        )
        embed.set_footer(text="VOTOX Autorole System")
        return embed
    
    # ============================================================================
    # COMMAND GROUPS AND SUBCOMMANDS
    # ============================================================================
    
    @commands.group(name="autorole", invoke_without_command=True)
    @commands.guild_only()
    async def autorole(self, ctx: commands.Context):
        """
        Autorole configuration command group.
        
        Displays the help menu when invoked without a subcommand.
        """
        config = await self._get_guild_config(ctx.guild.id)
        
        # Determine current role assignments
        human_role = ctx.guild.get_role(config["humans"]) if config["humans"] else None
        bot_role = ctx.guild.get_role(config["bots"]) if config["bots"] else None
        both_role = ctx.guild.get_role(config["both"]) if config["both"] else None
        
        embed = self._create_embed(
            title="🔧 Autorole Configuration",
            description="Manage automatic role assignment for new members.",
        )
        
        embed.add_field(
            name="👥 Humans Role",
            value=human_role.mention if human_role else "Not configured",
            inline=False
        )
        
        embed.add_field(
            name="🤖 Bots Role",
            value=bot_role.mention if bot_role else "Not configured",
            inline=False
        )
        
        embed.add_field(
            name="👫 Both Role",
            value=both_role.mention if both_role else "Not configured",
            inline=False
        )
        
        embed.add_field(
            name="📋 Available Commands",
            value=(
                "`.autorole humans set <role>` - Set role for humans\n"
                "`.autorole humans remove` - Remove human role\n"
                "`.autorole humans reset` - Reset all human configs\n"
                "`.autorole bot set <role>` - Set role for bots\n"
                "`.autorole bot remove` - Remove bot role\n"
                "`.autorole bot reset` - Reset all bot configs\n"
                "`.autorole both set <role>` - Set role for both\n"
                "`.autorole both remove` - Remove both role\n"
                "`.autorole both reset` - Reset all both configs"
            ),
            inline=False
        )
        
        await ctx.send(embed=embed)
    
    # ============================================================================
    # HUMANS SUBGROUP
    # ============================================================================
    
    @autorole.group(name="humans")
    @commands.guild_only()
    async def humans(self, ctx: commands.Context):
        """Manage autorole configuration for human users."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Please specify a subcommand: `set`, `remove`, or `reset`.")
    
    @humans.command(name="set")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def humans_set(self, ctx: commands.Context, role: discord.Role):
        """
        Set the role to be automatically assigned to human users.
        
        Args:
            role: The role to assign to humans.
        """
        # Verify role hierarchy
        is_assignable, error_msg = self._verify_role_assignable(ctx.guild, role)
        if not is_assignable:
            embed = self._create_embed(
                title="❌ Role Hierarchy Error",
                description=error_msg,
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            return
        
        # Update configuration
        config = await self._get_guild_config(ctx.guild.id)
        config["humans"] = role.id
        await self._save_guild_config(ctx.guild.id, config)
        
        embed = self._create_embed(
            title="✅ Humans Role Updated",
            description=f"Human users will now receive {role.mention} when they join.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
        logger.info(f"Autorole: Guild {ctx.guild.id} - Humans role set to {role.name} ({role.id})")
    
    @humans.command(name="remove")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def humans_remove(self, ctx: commands.Context):
        """
        Remove the autorole assignment for human users.
        """
        config = await self._get_guild_config(ctx.guild.id)
        
        if config["humans"] is None:
            embed = self._create_embed(
                title="⚠️ No Configuration",
                description="No human role is currently configured.",
                color=0xFFFF00
            )
            await ctx.send(embed=embed)
            return
        
        config["humans"] = None
        
        embed = self._create_embed(
            title="✅ Humans Role Removed",
            description="Human users will no longer receive an automatic role.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
        logger.info(f"Autorole: Guild {ctx.guild.id} - Humans role removed")
    
    @humans.command(name="reset")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def humans_reset(self, ctx: commands.Context):
        """
        Reset all human autorole configurations.
        """
        config = await self._get_guild_config(ctx.guild.id)
        config["humans"] = None
        
        embed = self._create_embed(
            title="✅ Humans Configuration Reset",
            description="All human role configurations have been cleared.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
        logger.info(f"Autorole: Guild {ctx.guild.id} - Humans configuration reset")
    
    # ============================================================================
    # BOTS SUBGROUP
    # ============================================================================
    
    @autorole.group(name="bot")
    @commands.guild_only()
    async def bot(self, ctx: commands.Context):
        """Manage autorole configuration for bot accounts."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Please specify a subcommand: `set`, `remove`, or `reset`.")
    
    @bot.command(name="set")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def set(self, ctx: commands.Context, role: discord.Role):
        """
        Set the role to be automatically assigned to bot accounts.
        
        Args:
            role: The role to assign to bots.
        """
        # Verify role hierarchy
        is_assignable, error_msg = self._verify_role_assignable(ctx.guild, role)
        if not is_assignable:
            embed = self._create_embed(
                title="❌ Role Hierarchy Error",
                description=error_msg,
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            return
        
        # Update configuration
        config = await self._get_guild_config(ctx.guild.id)
        config["bots"] = role.id
        
        embed = self._create_embed(
            title="✅ Bots Role Updated",
            description=f"Bot accounts will now receive {role.mention} when they join.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
        logger.info(f"Autorole: Guild {ctx.guild.id} - Bots role set to {role.name} ({role.id})")
    
    @bot.command(name="remove")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def remove(self, ctx: commands.Context):
        """
        Remove the autorole assignment for bot accounts.
        """
        config = await self._get_guild_config(ctx.guild.id)
        
        if config["bots"] is None:
            embed = self._create_embed(
                title="⚠️ No Configuration",
                description="No bot role is currently configured.",
                color=0xFFFF00
            )
            await ctx.send(embed=embed)
            return
        
        config["bots"] = None
        
        embed = self._create_embed(
            title="✅ Bots Role Removed",
            description="Bot accounts will no longer receive an automatic role.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
        logger.info(f"Autorole: Guild {ctx.guild.id} - Bots role removed")
    
    @bot.command(name="reset")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def reset(self, ctx: commands.Context):
        """
        Reset all bot autorole configurations.
        """
        config = await self._get_guild_config(ctx.guild.id)
        config["bots"] = None
        
        embed = self._create_embed(
            title="✅ Bots Configuration Reset",
            description="All bot role configurations have been cleared.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
        logger.info(f"Autorole: Guild {ctx.guild.id} - Bots configuration reset")
    
    # ============================================================================
    # BOTH SUBGROUP
    # ============================================================================
    
    @autorole.group(name="both")
    @commands.guild_only()
    async def both(self, ctx: commands.Context):
        """Manage autorole configuration for all members."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Please specify a subcommand: `set`, `remove`, or `reset`.")
    
    @both.command(name="set")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def both_set(self, ctx: commands.Context, role: discord.Role):
        """
        Set the role to be automatically assigned to all members (humans and bots).
        
        Args:
            role: The role to assign to all members.
        """
        # Verify role hierarchy
        is_assignable, error_msg = self._verify_role_assignable(ctx.guild, role)
        if not is_assignable:
            embed = self._create_embed(
                title="❌ Role Hierarchy Error",
                description=error_msg,
                color=0xFF0000
            )
            await ctx.send(embed=embed)
            return
        
        # Update configuration
        config = await self._get_guild_config(ctx.guild.id)
        config["both"] = role.id
        
        embed = self._create_embed(
            title="✅ Both Role Updated",
            description=f"All members will now receive {role.mention} when they join.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
        logger.info(f"Autorole: Guild {ctx.guild.id} - Both role set to {role.name} ({role.id})")
    
    @both.command(name="remove")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def both_remove(self, ctx: commands.Context):
        """
        Remove the autorole assignment for all members.
        """
        config = await self._get_guild_config(ctx.guild.id)
        
        if config["both"] is None:
            embed = self._create_embed(
                title="⚠️ No Configuration",
                description="No both role is currently configured.",
                color=0xFFFF00
            )
            await ctx.send(embed=embed)
            return
        
        config["both"] = None
        
        embed = self._create_embed(
            title="✅ Both Role Removed",
            description="All members will no longer receive an automatic role via the 'both' setting.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
        logger.info(f"Autorole: Guild {ctx.guild.id} - Both role removed")
    
    @both.command(name="reset")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def both_reset(self, ctx: commands.Context):
        """
        Reset all 'both' autorole configurations.
        """
        config = await self._get_guild_config(ctx.guild.id)
        config["both"] = None
        
        embed = self._create_embed(
            title="✅ Both Configuration Reset",
            description="All 'both' role configurations have been cleared.",
            color=0x00FF00
        )
        await ctx.send(embed=embed)
        logger.info(f"Autorole: Guild {ctx.guild.id} - Both configuration reset")
    
    # ============================================================================
    # EVENT LISTENERS
    # ============================================================================
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """
        Handle member join event - automatically assign configured roles.
        
        Args:
            member: The member that joined.
        """
        guild = member.guild
        config = await self._get_guild_config(guild.id)
        
        # Collect roles to assign
        roles_to_assign = []
        
        # Determine role assignments based on member type
        if member.bot:
            if config["bots"]:
                bot_role = guild.get_role(config["bots"])
                if bot_role:
                    roles_to_assign.append(bot_role)
        else:
            if config["humans"]:
                human_role = guild.get_role(config["humans"])
                if human_role:
                    roles_to_assign.append(human_role)
        
        # Add "both" role if configured
        if config["both"]:
            both_role = guild.get_role(config["both"])
            if both_role:
                roles_to_assign.append(both_role)
        
        # Assign all collected roles
        for role in roles_to_assign:
            try:
                await member.add_roles(role, reason="Autorole: Automatic assignment on join")
                member_type = "bot" if member.bot else "human"
                logger.info(
                    f"Autorole: Assigned {role.name} to {member.name} ({member.id}) - Type: {member_type}"
                )
            except discord.Forbidden:
                logger.warning(
                    f"Autorole: Permission denied assigning {role.name} to {member.name} ({member.id}). "
                    f"Ensure the bot has sufficient permissions and the role is below the bot's hierarchy."
                )
            except discord.HTTPException as e:
                logger.warning(
                    f"Autorole: HTTP error assigning {role.name} to {member.name} ({member.id}): {e}"
                )
            except Exception as e:
                logger.warning(
                    f"Autorole: Unexpected error assigning {role.name} to {member.name} ({member.id}): {e}"
                )


async def setup(bot: commands.Bot):
    """
    Load the autorole cog into the bot.
    
    This function is called automatically during bot startup by the dynamic
    cog loader in bot.py's setup_hook() method.
    
    Args:
        bot: The Discord bot instance.
    """
    await bot.add_cog(Autorole(bot))
