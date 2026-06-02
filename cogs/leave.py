import discord
from discord.ext import commands
from discord import app_commands
from typing import Optional, Dict, Any
import re
import aiosqlite
from pathlib import Path


class Leaver(commands.Cog):
    """
    Leave message management cog for VOTOX.
    
    Handles member departure notifications with text and embed support.
    """
    
    def __init__(self, bot: commands.Bot):
        """
        Initialize the Leaver cog.
        
        Args:
            bot: The Discord bot instance.
        """
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
    
    def _get_db(self) -> aiosqlite.Connection:
        """
        Get a database connection context manager.
        
        Returns:
            aiosqlite connection object.
        """
        return aiosqlite.connect(self.db_path)
    
    async def _get_guild_config(self, guild_id: int) -> Dict[str, Any]:
        """
        Retrieve or initialize guild leave configuration from database.
        
        Args:
            guild_id: The ID of the guild.
        
        Returns:
            Dictionary containing the guild's leave configuration.
        """
        async with self._get_db() as db:
            cursor = await db.execute(
                """
                SELECT channel_id, message, embed_enabled, embed_title, embed_image, embed_footer
                FROM leave_config WHERE guild_id = ?
                """,
                (guild_id,)
            )
            row = await cursor.fetchone()
            
            if row:
                return {
                    "guild_id": guild_id,
                    "channel_id": row[0],
                    "message": row[1],
                    "embed_enabled": bool(row[2]),
                    "embed_title": row[3],
                    "embed_image": row[4],
                    "embed_footer": row[5]
                }
            
            # Return default config
            return {
                "guild_id": guild_id,
                "channel_id": None,
                "message": "<<user>> has left the server. Goodbye!",
                "embed_enabled": False,
                "embed_title": "Member Left",
                "embed_image": None,
                "embed_footer": "We hope to see you again!"
            }
    
    async def _save_guild_config(self, guild_id: int, config: Dict[str, Any]) -> None:
        """
        Save guild configuration to database.
        
        Args:
            guild_id: The ID of the guild.
            config: The configuration dictionary to save.
        """
        async with self._get_db() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO leave_config 
                (guild_id, channel_id, message, embed_enabled, embed_title, embed_image, embed_footer, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    guild_id,
                    config.get("channel_id"),
                    config.get("message"),
                    int(config.get("embed_enabled", False)),
                    config.get("embed_title"),
                    config.get("embed_image"),
                    config.get("embed_footer")
                )
            )
            await db.commit()
    
    def _parse_variables(self, text: str, member: discord.Member, guild: discord.Guild) -> str:
        """
        Replace placeholder variables in text with actual values.
        
        Supported placeholders:
        - <<user.mention>>: Mentions the member
        - <<user>>: Displays the member's display name
        - <<guild.name>>: The server's name
        - <<guild.count>>: The server's total member count (after departure)
        
        Args:
            text: The text containing placeholders.
            member: The Discord member object.
            guild: The Discord guild object.
        
        Returns:
            Text with all placeholders replaced.
        """
        if not text:
            return text
        
        text = text.replace("<<user.mention>>", member.mention)
        text = text.replace("<<user>>", member.display_name)
        text = text.replace("<<guild.name>>", guild.name)
        text = text.replace("<<guild.count>>", str(guild.member_count))
        
        return text
    
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
            title=title,
            description=description,
            color=discord.Color.red()
        )
        embed.set_footer(text="VOTOX Leave System")
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
            title=title,
            description=description,
            color=discord.Color.green()
        )
        embed.set_footer(text="VOTOX Leave System")
        return embed
    
    @commands.group(name="leave", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def leave_group(self, ctx: commands.Context):
        """
        Main command group for leave message configuration.
        
        Displays a comprehensive help menu with all available subcommands.
        """
        embed = discord.Embed(
            title="👋 VOTOX Leave System - Help Menu",
            description="Configure leave messages for your server using the commands below.",
            color=discord.Color.blurple()
        )
        
        embed.add_field(
            name=".leave channel [channel]",
            value="Set the channel where leave messages will be sent.",
            inline=False
        )
        
        embed.add_field(
            name=".leave embed [on/off]",
            value="Toggle embed mode for leave messages.",
            inline=False
        )
        
        embed.add_field(
            name=".leave message [text...]",
            value="Set the text leave message (supports variables).",
            inline=False
        )
        
        embed.add_field(
            name=".leave test",
            value="Send a test leave message to the configured channel.",
            inline=False
        )
        
        embed.add_field(
            name=".leave embed title [text...]",
            value="Set the embed title (only works if embed mode is ON).",
            inline=False
        )
        
        embed.add_field(
            name=".leave embed image [url]",
            value="Set the embed image URL (only works if embed mode is ON).",
            inline=False
        )
        
        embed.add_field(
            name=".leave embed footer [text...]",
            value="Set the embed footer text (only works if embed mode is ON).",
            inline=False
        )
        
        embed.add_field(
            name=".leave variables",
            value="Display all available placeholder variables.",
            inline=False
        )
        
        embed.set_footer(text="Use .leave <subcommand> for more information")
        
        await ctx.send(embed=embed)
    
    @leave_group.command(name="channel")
    @commands.has_permissions(administrator=True)
    async def leave_channel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """
        Set the leave message channel.
        
        Args:
            ctx: The command context.
            channel: The text channel where leave messages will be sent.
        """
        config = await self._get_guild_config(ctx.guild.id)
        
        if channel is None:
            if config["channel_id"] is None:
                embed = self._create_error_embed(
                    "No Channel Set",
                    "No leave channel is currently configured. Please specify a channel."
                )
            else:
                current_channel = ctx.guild.get_channel(config["channel_id"])
                channel_mention = current_channel.mention if current_channel else f"<#{config['channel_id']}>"
                embed = discord.Embed(
                    title="Leave Channel",
                    description=f"Current leave channel: {channel_mention}",
                    color=discord.Color.blurple()
                )
            await ctx.send(embed=embed)
            return
        
        config["channel_id"] = channel.id
        await self._save_guild_config(ctx.guild.id, config)
        
        embed = self._create_success_embed(
            "Channel Updated",
            f"Leave messages will now be sent to {channel.mention}"
        )
        await ctx.send(embed=embed)
    
    @leave_group.command(name="mode")
    @commands.has_permissions(administrator=True)
    async def leave_mode(self, ctx: commands.Context, toggle: Optional[str] = None):
        """
        Toggle embed mode for leave messages.
        
        Args:
            ctx: The command context.
            toggle: 'on' to enable embeds, 'off' to disable them, or None to check status.
        """
        config = await self._get_guild_config(ctx.guild.id)
        
        if toggle is None:
            status = "**Enabled** ✅" if config["embed_enabled"] else "**Disabled** ❌"
            embed = discord.Embed(
                title="Embed Mode Status",
                description=f"Embed mode is currently {status}",
                color=discord.Color.blurple()
            )
            await ctx.send(embed=embed)
            return
        
        toggle_lower = toggle.lower()
        
        if toggle_lower == "on":
            config["embed_enabled"] = True
            embed = self._create_success_embed(
                "Embed Mode Enabled",
                "Leave messages will now be sent as embeds."
            )
        elif toggle_lower == "off":
            config["embed_enabled"] = False
            embed = self._create_success_embed(
                "Embed Mode Disabled",
                "Leave messages will now be sent as text messages."
            )
        else:
            embed = self._create_error_embed(
                "Invalid Option",
                "Use `.leave mode on` or `.leave mode off`"
            )
        
        await self._save_guild_config(ctx.guild.id, config)
        await ctx.send(embed=embed)
    
    @leave_group.command(name="message")
    @commands.has_permissions(administrator=True)
    async def leave_message(self, ctx: commands.Context, *, message: str = None):
        """
        Set the text leave message.
        
        Args:
            ctx: The command context.
            message: The leave message text (supports variables).
        """
        config = await self._get_guild_config(ctx.guild.id)
        
        if message is None:
            embed = discord.Embed(
                title="Current Leave Message",
                description=f"```\n{config['message']}\n```",
                color=discord.Color.blurple()
            )
            await ctx.send(embed=embed)
            return
        
        config["message"] = message
        await self._save_guild_config(ctx.guild.id, config)
        
        embed = self._create_success_embed(
            "Message Updated",
            f"Leave message set to:\n```\n{message}\n```"
        )
        await ctx.send(embed=embed)
    
    @leave_group.command(name="test")
    @commands.has_permissions(administrator=True)
    async def leave_test(self, ctx: commands.Context):
        """
        Send a test leave message to the configured channel.
        
        Uses the command executor as the mock member.
        """
        config = await self._get_guild_config(ctx.guild.id)
        
        if config["channel_id"] is None:
            embed = self._create_error_embed(
                "No Channel Configured",
                "Please set a leave channel using `.leave channel [channel]`"
            )
            await ctx.send(embed=embed)
            return
        
        leave_channel = ctx.guild.get_channel(config["channel_id"])
        if leave_channel is None:
            embed = self._create_error_embed(
                "Channel Not Found",
                f"The configured channel (ID: {config['channel_id']}) no longer exists."
            )
            await ctx.send(embed=embed)
            return
        
        # Parse variables using the command executor as the mock member
        if config["embed_enabled"]:
            # Send as embed
            embed_title = self._parse_variables(config["embed_title"], ctx.author, ctx.guild)
            embed_footer = self._parse_variables(config["embed_footer"], ctx.author, ctx.guild)
            message_text = self._parse_variables(config["message"], ctx.author, ctx.guild)
            
            leave_embed = discord.Embed(
                title=embed_title,
                description=message_text,
                color=discord.Color.blurple()
            )
            
            if config["embed_image"]:
                leave_embed.set_image(url=config["embed_image"])
            
            leave_embed.set_footer(text=embed_footer)
            
            try:
                await leave_channel.send(embed=leave_embed)
            except discord.Forbidden:
                embed = self._create_error_embed(
                    "Permission Denied",
                    f"I don't have permission to send messages in {leave_channel.mention}"
                )
                await ctx.send(embed=embed)
                return
        else:
            # Send as text message
            message_text = self._parse_variables(config["message"], ctx.author, ctx.guild)
            try:
                await leave_channel.send(message_text)
            except discord.Forbidden:
                embed = self._create_error_embed(
                    "Permission Denied",
                    f"I don't have permission to send messages in {leave_channel.mention}"
                )
                await ctx.send(embed=embed)
                return
        
        embed = self._create_success_embed(
            "Test Message Sent",
            f"Leave message preview sent to {leave_channel.mention}"
        )
        await ctx.send(embed=embed)
    
    @leave_group.group(name="embed")
    @commands.has_permissions(administrator=True)
    async def leave_embed_group(self, ctx: commands.Context):
        """
        Group for embed-specific configuration commands.
        
        Note: This allows .leave embed title, .leave embed image, etc.
        """
        if ctx.invoked_subcommand is None:
            await self.leave_mode(ctx)
    
    @leave_embed_group.command(name="title")
    @commands.has_permissions(administrator=True)
    async def leave_embed_title(self, ctx: commands.Context, *, title: str = None):
        """
        Set the embed title for leave messages.
        
        Args:
            ctx: The command context.
            title: The embed title text (supports variables).
        """
        config = await self._get_guild_config(ctx.guild.id)
        
        if not config["embed_enabled"]:
            embed = self._create_error_embed(
                "Embed Mode Disabled",
                "Embed title configuration is not available when embed mode is OFF.\n"
                "Enable embed mode using `.leave mode on`"
            )
            await ctx.send(embed=embed)
            return
        
        if title is None:
            embed = discord.Embed(
                title="Current Embed Title",
                description=f"```\n{config['embed_title']}\n```",
                color=discord.Color.blurple()
            )
            await ctx.send(embed=embed)
            return
        
        config["embed_title"] = title
        await self._save_guild_config(ctx.guild.id, config)
        
        embed = self._create_success_embed(
            "Embed Title Updated",
            f"Embed title set to:\n```\n{title}\n```"
        )
        await ctx.send(embed=embed)
    
    @leave_embed_group.command(name="image")
    @commands.has_permissions(administrator=True)
    async def leave_embed_image(self, ctx: commands.Context, *, url: str = None):
        """
        Set the embed image URL for leave messages.
        
        Args:
            ctx: The command context.
            url: The image URL to display in the embed.
        """
        config = await self._get_guild_config(ctx.guild.id)
        
        if not config["embed_enabled"]:
            embed = self._create_error_embed(
                "Embed Mode Disabled",
                "Embed image configuration is not available when embed mode is OFF.\n"
                "Enable embed mode using `.leave mode on`"
            )
            await ctx.send(embed=embed)
            return
        
        if url is None:
            current_url = config["embed_image"] if config["embed_image"] else "Not set"
            embed = discord.Embed(
                title="Current Embed Image",
                description=f"```\n{current_url}\n```",
                color=discord.Color.blurple()
            )
            await ctx.send(embed=embed)
            return
        
        config["embed_image"] = url
        await self._save_guild_config(ctx.guild.id, config)
        
        embed = self._create_success_embed(
            "Embed Image Updated",
            f"Embed image URL set to:\n```\n{url}\n```"
        )
        await ctx.send(embed=embed)
    
    @leave_embed_group.command(name="footer")
    @commands.has_permissions(administrator=True)
    async def leave_embed_footer(self, ctx: commands.Context, *, footer: str = None):
        """
        Set the embed footer text for leave messages.
        
        Args:
            ctx: The command context.
            footer: The embed footer text (supports variables).
        """
        config = await self._get_guild_config(ctx.guild.id)
        
        if not config["embed_enabled"]:
            embed = self._create_error_embed(
                "Embed Mode Disabled",
                "Embed configuration is not available when embed mode is OFF.\n"
                "Enable embed mode using `.leave embed on`"
            )
            await ctx.send(embed=embed)
            return
        
        if footer is None:
            embed = discord.Embed(
                title="Current Embed Footer",
                description=f"```\n{config['embed_footer']}\n```",
                color=discord.Color.blurple()
            )
            await ctx.send(embed=embed)
            return
        
        config["embed_footer"] = footer
        await self._save_guild_config(ctx.guild.id, config)
        
        embed = self._create_success_embed(
            "Embed Footer Updated",
            f"Embed footer set to:\n```\n{footer}\n```"
        )
        await ctx.send(embed=embed)
    
    @leave_group.command(name="variables")
    async def leave_variables(self, ctx: commands.Context):
        """
        Display all available placeholder variables for leave messages.
        """
        embed = discord.Embed(
            title="📋 Available Placeholder Variables",
            description="Use these placeholders in your leave messages to display dynamic information.",
            color=discord.Color.blurple()
        )
        
        embed.add_field(
            name="<<user.mention>>",
            value="Mentions the member (e.g., <@userid>)",
            inline=False
        )
        
        embed.add_field(
            name="<<user>>",
            value="Displays the member's display name",
            inline=False
        )
        
        embed.add_field(
            name="<<guild.name>>",
            value="The server's name",
            inline=False
        )
        
        embed.add_field(
            name="<<guild.count>>",
            value="The server's total member count (after departure)",
            inline=False
        )
        
        embed.set_footer(text="VOTOX Leave System | Use these in .leave message and .leave embed title commands")
        
        await ctx.send(embed=embed)
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """
        Handle the member removal event and send the configured leave message.
        
        Args:
            member: The member that left the guild.
        """
        config = await self._get_guild_config(member.guild.id)
        
        # Check if a channel is configured
        if config["channel_id"] is None:
            return
        
        leave_channel = member.guild.get_channel(config["channel_id"])
        if leave_channel is None:
            return
        
        try:
            # Check if embed mode is enabled
            if config["embed_enabled"]:
                # Send as embed
                embed_title = self._parse_variables(config["embed_title"], member, member.guild)
                embed_footer = self._parse_variables(config["embed_footer"], member, member.guild)
                message_text = self._parse_variables(config["message"], member, member.guild)
                
                leave_embed = discord.Embed(
                    title=embed_title,
                    description=message_text,
                    color=discord.Color.blurple()
                )
                
                if config["embed_image"]:
                    leave_embed.set_image(url=config["embed_image"])
                
                leave_embed.set_footer(text=embed_footer)
                
                await leave_channel.send(embed=leave_embed)
            else:
                # Send as text message
                message_text = self._parse_variables(config["message"], member, member.guild)
                await leave_channel.send(message_text)
        
        except discord.Forbidden:
            # Bot doesn't have permission to send messages
            pass
        except Exception as e:
            # Log any other errors
            print(f"Error sending leave message for {member}: {e}")


# Setup function to load the cog
async def setup(bot: commands.Bot):
    """
    Load the Leaver cog into the bot.
    
    Args:
        bot: The Discord bot instance.
    """
    await bot.add_cog(Leaver(bot))
