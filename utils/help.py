"""
VOTOX Interactive Help System - Aesthetic dropdown-based command help.

This module provides a production-ready, interactive help system featuring:
- Beautiful Discord embeds with consistent branding
- Interactive dropdown menus for category navigation
- Dynamic command counting per category
- User-specific access control (prevents hijacking)
- 60-second timeout with graceful degradation
- Three modes: landing page, category lookup, command lookup
- Customizable emoji mapping for categories
- Comprehensive command metadata extraction
"""

import discord
from discord.ext import commands
from typing import Dict, List, Optional, Tuple, Any
import asyncio

# ============================================================================
# EMOJI MAPPING - Customize Here
# ============================================================================
# Map cog names to emojis for visual identification in dropdowns.
# Add your custom server emojis here: "CogName": "<:emoji_name:emoji_id>"

CATEGORY_EMOJIS = {
    "Moderation": "⚖️",
    "Giveaway": "🎁",
    "Logging": "📝",
    "Welcomer": "👋",
    "Leave": "👋",
    "Autoresponder": "💬",
    "Greet": "👋",
    # Add more categories as needed
}


# ============================================================================
# Command Metadata Extractor
# ============================================================================

class CommandMetadata:
    """Extract and manage command metadata."""
    
    @staticmethod
    def get_command_description(command: commands.Command) -> str:
        """
        Extract command description from docstring or help text.
        
        Args:
            command: The discord.py Command object.
        
        Returns:
            Command description string.
        """
        if command.help:
            return command.help.split("\n")[0]  # First line of help text
        if command.description:
            return command.description
        return "No description available."
    
    @staticmethod
    def get_command_syntax(command: commands.Command, prefix: str) -> str:
        """
        Generate command syntax with argument breakdown.
        
        Syntax conventions:
        - [arg] = Required argument
        - (arg) = Optional argument
        - <alias1/alias2> = Aliases
        
        Args:
            command: The discord.py Command object.
            prefix: The bot's prefix.
        
        Returns:
            Formatted syntax string.
        """
        syntax = f"{prefix}{command.name}"
        
        if command.signature:
            syntax += f" {command.signature}"
        
        return f"```{syntax}```"
    
    @staticmethod
    def get_command_aliases(command: commands.Command) -> str:
        """
        Format command aliases.
        
        Args:
            command: The discord.py Command object.
        
        Returns:
            Formatted aliases string, or "None" if no aliases.
        """
        if not command.aliases:
            return "None"
        
        return ", ".join(f"`{alias}`" for alias in command.aliases)


# ============================================================================
# Category Select Dropdown View
# ============================================================================

class CategorySelect(discord.ui.Select):
    """
    Interactive dropdown menu for selecting command categories.
    
    Features:
    - Dynamic category loading from active cogs
    - Command counting per category
    - Author-only access
    - Graceful timeout handling
    """
    
    def __init__(self, bot: commands.Bot, ctx: commands.Context, cog_data: Dict[str, List[commands.Command]]):
        """
        Initialize the category select dropdown.
        
        Args:
            bot: The Discord bot instance.
            ctx: The command context.
            cog_data: Dictionary mapping cog names to their commands.
        """
        self.bot = bot
        self.ctx = ctx
        
        # Build select options from cog data
        options = []
        for cog_name, commands_list in cog_data.items():
            visible_commands = [cmd for cmd in commands_list if not cmd.hidden]
            if visible_commands:  # Only show cogs with visible commands
                emoji = CATEGORY_EMOJIS.get(cog_name, "📚")
                option = discord.SelectOption(
                    label=f"{cog_name}",
                    value=cog_name,
                    description=f"{len(visible_commands)} command{'s' if len(visible_commands) != 1 else ''}",
                    emoji=emoji
                )
                options.append(option)
        
        super().__init__(
            placeholder="Select a category to view commands...",
            min_values=1,
            max_values=1,
            options=options
        )
    
    async def callback(self, interaction: discord.Interaction):
        """Handle category selection."""
        # Verify the interaction is from the original command author
        if interaction.user.id != self.ctx.author.id:
            await interaction.response.send_message(
                "❌ Only the user who triggered this help menu can use it.",
                ephemeral=True
            )
            return
        
        selected_cog = self.values[0]
        embed = await self._build_category_embed(selected_cog)
        await interaction.response.edit_message(embed=embed)
    
    async def _build_category_embed(self, cog_name: str) -> discord.Embed:
        """
        Build embed displaying all commands in a category (including subcommands).
        
        Args:
            cog_name: The name of the cog/category.
        
        Returns:
            Formatted Discord Embed.
        """
        cog = self.bot.get_cog(cog_name)
        if not cog:
            return discord.Embed(
                title="❌ Category Not Found",
                description=f"The category '{cog_name}' could not be loaded.",
                color=discord.Color.red()
            )
        
        # Get the HelpCog instance to use its helper methods
        help_cog = self.bot.get_cog("HelpCog")
        if not help_cog:
            return discord.Embed(
                title="❌ Error",
                description="Help system not loaded properly.",
                color=discord.Color.red()
            )
        
        # Get all commands (top-level and subcommands) from cog
        cog_commands = help_cog._get_all_commands_in_cog(cog)
        
        if not cog_commands:
            return discord.Embed(
                title=f"{cog_name} Commands",
                description="No commands available in this category.",
                color=self.bot.embed_color
            )
        
        embed = discord.Embed(
            title=f"{CATEGORY_EMOJIS.get(cog_name, '📚')} {cog_name} Commands",
            description=cog.__doc__ or "Command category.",
            color=self.bot.embed_color
        )
        
        command_list = []
        for cmd_path, cmd in sorted(cog_commands, key=lambda x: x[0]):
            description = CommandMetadata.get_command_description(cmd)
            command_list.append(f"**`{self.ctx.clean_prefix}{cmd_path}`** - {description}")
        
        embed.description = (cog.__doc__ or "Command category.") + "\n\n" + "\n".join(command_list)
        
        embed.set_footer(
            text=f"Use '{self.ctx.clean_prefix}help <command>' for detailed command info • Category {cog_name}"
        )
        
        return embed
    
    def _get_subcommand_paths(self, parent_cmd: commands.Command, prefix: str = "") -> List[Tuple[str, commands.Command]]:
        """
        Recursively get subcommand paths.
        
        Args:
            parent_cmd: The parent command group.
            prefix: The prefix accumulated so far.
        
        Returns:
            List of (full_path, command) tuples.
        """
        results = []
        
        if isinstance(parent_cmd, commands.Group):
            new_prefix = f"{prefix}{parent_cmd.name} " if prefix else f"{parent_cmd.name} "
            
            for cmd in parent_cmd.commands:
                if not cmd.hidden:
                    results.append((new_prefix + cmd.name, cmd))
                    # Recurse for nested groups
                    if isinstance(cmd, commands.Group):
                        results.extend(self._get_subcommand_paths(cmd, new_prefix + cmd.name + " "))
        
        return results


# ============================================================================
# Help View with Dropdown
# ============================================================================

class HelpView(discord.ui.View):
    """
    Main view containing the category dropdown menu.
    
    Features:
    - 60-second timeout with automatic disabling
    - Author-only access control
    - Graceful placeholder update on timeout
    """
    
    def __init__(self, bot: commands.Bot, ctx: commands.Context, cog_data: Dict[str, List[commands.Command]]):
        """
        Initialize the help view.
        
        Args:
            bot: The Discord bot instance.
            ctx: The command context.
            cog_data: Dictionary mapping cog names to their commands.
        """
        super().__init__(timeout=60.0)
        self.bot = bot
        self.ctx = ctx
        
        # Add the category select dropdown
        select = CategorySelect(bot, ctx, cog_data)
        self.add_item(select)
    
    async def on_timeout(self):
        """Called when the view times out after 60 seconds."""
        # Update the select menu to be disabled
        for item in self.children:
            if isinstance(item, discord.ui.Select):
                item.disabled = True
                item.placeholder = "⏰ This menu has expired. Use the command again to get a new menu."


# ============================================================================
# Help Command Cog
# ============================================================================

class HelpCog(commands.Cog):
    """
    Interactive help system for VOTOX bot.
    
    Provides an aesthetic, dropdown-based help menu with comprehensive
    command information and category navigation.
    """
    
    def __init__(self, bot: commands.Bot):
        """
        Initialize the Help cog.
        
        Args:
            bot: The Discord bot instance.
        """
        self.bot = bot
    
    def _get_subcommand_paths(self, parent_cmd: commands.Command, prefix: str = "") -> List[Tuple[str, commands.Command]]:
        """
        Recursively get subcommand paths.
        
        Args:
            parent_cmd: The parent command group.
            prefix: The prefix accumulated so far.
        
        Returns:
            List of (full_path, command) tuples.
        """
        results = []
        
        if isinstance(parent_cmd, commands.Group):
            new_prefix = f"{prefix}{parent_cmd.name} " if prefix else f"{parent_cmd.name} "
            
            for cmd in parent_cmd.commands:
                if not cmd.hidden:
                    results.append((new_prefix + cmd.name, cmd))
                    # Recurse for nested groups
                    if isinstance(cmd, commands.Group):
                        results.extend(self._get_subcommand_paths(cmd, new_prefix + cmd.name + " "))
        
        return results
    
    def _get_all_commands_in_cog(self, cog: commands.Cog) -> List[Tuple[str, commands.Command]]:
        """
        Get all commands (top-level and subcommands) in a specific cog.
        
        Args:
            cog: The cog to get commands from.
        
        Returns:
            List of (full_path, command) tuples.
        """
        commands_list = []
        
        # Top-level commands
        for cmd in self.bot.commands:
            if cmd.cog == cog and not cmd.hidden:
                commands_list.append((cmd.name, cmd))
                # Get subcommands
                if isinstance(cmd, commands.Group):
                    commands_list.extend(self._get_subcommand_paths(cmd))
        
        return commands_list
    
    def _get_all_cogs_data(self) -> Dict[str, List[commands.Command]]:
        """
        Retrieve all loaded cogs and their associated commands (including subcommands).
        
        Returns:
            Dictionary mapping cog names to lists of commands (all levels).
        """
        cog_data = {}
        
        for cog_name, cog in self.bot.cogs.items():
            if cog_name == "HelpCog":
                continue
                
            commands_list = self._get_all_commands_in_cog(cog)
            # Extract just the commands (not the paths) for backward compatibility
            if commands_list:
                cog_data[cog_name] = [cmd for _, cmd in commands_list]
        
        return cog_data
    
    def _get_all_commands_count(self) -> int:
        """
        Get the total count of all visible commands (including subcommands).
        
        Returns:
            Total number of non-hidden commands at all levels.
        """
        count = 0
        
        for cmd in self.bot.commands:
            if not cmd.hidden:
                count += 1
                # Count subcommands in groups
                if isinstance(cmd, commands.Group):
                    count += self._count_subcommands(cmd)
        
        return count
    
    def _count_subcommands(self, group: commands.Group) -> int:
        """
        Recursively count all subcommands in a group.
        
        Args:
            group: The command group to count subcommands in.
        
        Returns:
            Total count of non-hidden subcommands.
        """
        count = 0
        
        for cmd in group.commands:
            if not cmd.hidden:
                count += 1
                # Recurse if it's a nested group
                if isinstance(cmd, commands.Group):
                    count += self._count_subcommands(cmd)
        
        return count
    
    def _get_cog_count(self) -> int:
        """
        Get the total count of cogs with visible commands.
        
        Returns:
            Total number of active cogs.
        """
        return len(self._get_all_cogs_data())
    
    async def _build_landing_embed(self, ctx: commands.Context) -> discord.Embed:
        """
        Build the landing page embed with bot stats.
        
        Args:
            ctx: The command context.
        
        Returns:
            Formatted landing page embed.
        """
        total_cogs = self._get_cog_count()
        total_commands = self._get_all_commands_count()
        
        embed = discord.Embed(
            title="🎉 Welcome to VOTOX Help",
            description="Select a command category below to explore available commands.",
            color=self.bot.embed_color
        )
        
        # Bot stats
        embed.add_field(
            name="📊 Bot Statistics",
            value=f"**Categories:** {total_cogs}\n**Total Commands:** {total_commands}",
            inline=False
        )
        
        embed.add_field(
            name="⚡ Quick Links",
            value=f"Use `{ctx.clean_prefix}help <command>` for detailed command information.",
            inline=False
        )
        
        embed.set_footer(
            text="Dropdown expires in 60 seconds • React only as the command invoker"
        )
        embed.set_thumbnail(url=self.bot.user.avatar.url if self.bot.user.avatar else "")
        
        return embed
    
    async def _find_command(self, ctx: commands.Context, search_term: str) -> Optional[commands.Command]:
        """
        Search for a command by name or alias (including subcommands).
        
        Args:
            ctx: The command context.
            search_term: The command name or alias to search for.
        
        Returns:
            The Command object if found, None otherwise.
        """
        search_term_lower = search_term.lower()
        
        # Search all commands (top-level and subcommands)
        def search_in_commands(commands_list: List[commands.Command]) -> Optional[commands.Command]:
            """Recursively search through commands and subcommands."""
            for command in commands_list:
                # Check command name
                if command.name.lower() == search_term_lower and not command.hidden:
                    return command
                
                # Check aliases
                if search_term_lower in [alias.lower() for alias in command.aliases]:
                    return command
                
                # If it's a group, search its subcommands
                if isinstance(command, commands.Group):
                    result = search_in_commands(command.commands)
                    if result:
                        return result
            
            return None
        
        return search_in_commands(self.bot.commands)
    
    async def _build_command_detail_embed(self, ctx: commands.Context, command: commands.Command) -> discord.Embed:
        """
        Build a detailed embed for a specific command.
        
        Args:
            ctx: The command context.
            command: The command to detail.
        
        Returns:
            Formatted command detail embed.
        """
        embed = discord.Embed(
            title=f"Command: {ctx.clean_prefix}{command.name}",
            description=CommandMetadata.get_command_description(command),
            color=self.bot.embed_color
        )
        
        # Full help text
        if command.help and len(command.help) > len(CommandMetadata.get_command_description(command)):
            embed.add_field(
                name="📖 Details",
                value=command.help,
                inline=False
            )
        
        # Syntax
        embed.add_field(
            name="💻 Syntax",
            value=CommandMetadata.get_command_syntax(command, ctx.clean_prefix),
            inline=False
        )
        
        # Aliases
        aliases = CommandMetadata.get_command_aliases(command)
        embed.add_field(name="🔗 Aliases", value=aliases, inline=True)
        
        # Cog/Category
        cog_name = command.cog.qualified_name if command.cog else "General"
        embed.add_field(name="📚 Category", value=cog_name, inline=True)
        
        embed.set_footer(text=f"Command • {command.cog.qualified_name if command.cog else 'General'}")
        
        return embed
    
    @commands.command(name="help", brief="Display help information")
    async def help_command(
        self,
        ctx: commands.Context,
        *,
        search_term: Optional[str] = None
    ):
        """
        Display help information with interactive category dropdown.
        
        Three modes of operation:
        
        1. Landing Page (No Arguments):
            .help
            Shows bot statistics and interactive category dropdown.
        
        2. Category Lookup (Cog Name):
            .help moderation
            Directly shows all commands in the Moderation category.
        
        3. Command Lookup (Command Name or Alias):
            .help ban
            Shows detailed information about a specific command.
        
        Args:
            ctx: The command context.
            search_term: Optional search term (category or command name).
        """
        
        # =====================================================================
        # Mode 1: Landing Page (No Arguments)
        # =====================================================================
        if not search_term:
            cog_data = self._get_all_cogs_data()
            embed = await self._build_landing_embed(ctx)
            view = HelpView(self.bot, ctx, cog_data)
            
            await ctx.send(embed=embed, view=view)
            return
        
        search_term = search_term.lower()
        
        # =====================================================================
        # Mode 2: Category Lookup
        # =====================================================================
        found_cog = None
        for cog_name in self.bot.cogs.keys():
            if cog_name.lower() == search_term:
                found_cog = cog_name
                break
        
        if found_cog:
            cog = self.bot.get_cog(found_cog)
            cog_commands = self._get_all_commands_in_cog(cog)
            
            if not cog_commands:
                embed = discord.Embed(
                    title="❌ No Commands",
                    description=f"The category '{found_cog}' has no visible commands.",
                    color=discord.Color.red()
                )
                await ctx.send(embed=embed)
                return
            
            embed = discord.Embed(
                title=f"{CATEGORY_EMOJIS.get(found_cog, '📚')} {found_cog} Commands",
                description=cog.__doc__ or "Command category.",
                color=self.bot.embed_color
            )
            
            command_list = []
            for cmd_path, cmd in sorted(cog_commands, key=lambda x: x[0]):
                description = CommandMetadata.get_command_description(cmd)
                command_list.append(f"**`{ctx.clean_prefix}{cmd_path}`** - {description}")
            
            embed.description = (cog.__doc__ or "Command category.") + "\n\n" + "\n".join(command_list)
            
            embed.set_footer(
                text=f"Use '{ctx.clean_prefix}help <command>' for detailed info"
            )
            await ctx.send(embed=embed)
            return
        
        # =====================================================================
        # Mode 3: Command Lookup
        # =====================================================================
        command = await self._find_command(ctx, search_term)
        
        if not command:
            embed = discord.Embed(
                title="❌ Command Not Found",
                description=f"Could not find a command or category matching `{search_term}`.",
                color=discord.Color.red()
            )
            embed.set_footer(text=f"Use '{ctx.clean_prefix}help' to see all categories")
            await ctx.send(embed=embed)
            return
        
        embed = await self._build_command_detail_embed(ctx, command)
        await ctx.send(embed=embed)


# ============================================================================
# Legacy Help Command Class (Optional Fallback)
# ============================================================================

class CustomHelpCommand(commands.HelpCommand):
    """
    Legacy help command class for backward compatibility.
    
    This is kept for fallback purposes but the HelpCog is the primary system.
    """
    
    async def send_bot_help(self, mapping):
        """Send bot help (not used with new HelpCog)."""
        embed = discord.Embed(
            title="VOTOX Bot Commands",
            description="Use `.help <command>` for more information on a specific command.",
            color=self.bot.embed_color
        )
        
        for cog_name, cog_commands in mapping.items():
            if cog_commands and cog_name is not None:
                command_list = []
                for cmd in cog_commands:
                    if not cmd.hidden:
                        command_list.append(f"`{cmd.name}`")
                
                if command_list:
                    embed.add_field(
                        name=cog_name.qualified_name,
                        value=" ".join(command_list),
                        inline=False
                    )
        
        await self.get_destination().send(embed=embed)
    
    async def send_command_help(self, command):
        """Send command help (not used with new HelpCog)."""
        embed = discord.Embed(
            title=f"`{self.context.clean_prefix}{command.name}`",
            description=command.description or "No description available.",
            color=self.bot.embed_color
        )
        
        if command.help:
            embed.add_field(name="Description", value=command.help, inline=False)
        
        if command.aliases:
            embed.add_field(
                name="Aliases",
                value=", ".join(f"`{alias}`" for alias in command.aliases),
                inline=False
            )
        
        if command.signature:
            embed.add_field(
                name="Usage",
                value=f"```{self.context.clean_prefix}{command.name} {command.signature}```",
                inline=False
            )
        
        await self.get_destination().send(embed=embed)


# ============================================================================
# Setup Function
# ============================================================================

async def setup(bot: commands.Bot):
    """
    Load the help cog into the bot.
    
    Args:
        bot: The Discord bot instance.
    """
    await bot.add_cog(HelpCog(bot))
    # Disable the default help command
    bot.help_command = None