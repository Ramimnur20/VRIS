
import discord
from discord.ext import commands
from typing import Optional, Dict, Tuple
import aiosqlite
import json
from pathlib import Path
from datetime import datetime


# ============================================================================
# Confirmation View for Destructive Actions
# ============================================================================

class LoggingDisableView(discord.ui.View):
    """
    Confirmation view for disabling logging and deleting channels.
    
    Provides Confirm (red/danger) and Cancel (secondary) buttons.
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
    
    @discord.ui.button(label="Disable & Delete", style=discord.ButtonStyle.danger)
    async def confirm_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle confirmation."""
        self.confirmed = True
        await interaction.response.defer()
        self.stop()
    
    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Handle cancellation."""
        self.confirmed = False
        await interaction.response.defer()
        self.stop()


# ============================================================================
# Main Logging Cog
# ============================================================================

class Logging(commands.Cog):
    """
    Advanced logging cog for VOTOX.
    
    Handles comprehensive server event logging with color-coded embeds.
    """
    
    def __init__(self, bot: commands.Bot):
        """
        Initialize the Logging cog.
        
        Args:
            bot: The Discord bot instance.
        """
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        self._cache: Dict[int, Dict] = {}
    
    def _get_db(self) -> aiosqlite.Connection:
        """Return database connection."""
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initialize database tables for logging."""
        async with self._get_db() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS logging_config (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 0,
                    channels TEXT,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await db.commit()

    # ========================================================================
    # Helper Methods
    # ========================================================================
    
    async def _get_config(self, guild_id: int) -> Dict:
        """Get configuration from DB."""
        if guild_id in self._cache:
            return self._cache[guild_id]
            
        async with self._get_db() as db:
            cursor = await db.execute("SELECT enabled, channels FROM logging_config WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
            if row:
                config = {"enabled": bool(row[0]), "channels": json.loads(row[1])}
            else:
                config = {"enabled": False, "channels": {}}
                
        self._cache[guild_id] = config
        return config

    async def _save_config(self, guild_id: int, config: Dict) -> None:
        """Save configuration to DB."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO logging_config (guild_id, enabled, channels, updated_at) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (guild_id, 1 if config["enabled"] else 0, json.dumps(config["channels"]))
            )
            await db.commit()
        self._cache[guild_id] = config
    
    async def _is_logging_enabled(self, guild_id: int) -> bool:
        config = await self._get_config(guild_id)
        return config.get("enabled", False)
    
    async def _get_log_channel(self, guild: discord.Guild, channel_type: str) -> Optional[discord.TextChannel]:
        config = await self._get_config(guild.id)
        channel_id = config["channels"].get(channel_type)
        
        if not channel_id:
            return None
        
        return guild.get_channel(channel_id)
    
    # ========================================================================
    # Embed Creation Methods
    # ========================================================================
    
    def _create_success_embed(self, title: str, description: str = "") -> discord.Embed:
        """Create a green success embed."""
        embed = discord.Embed(
            title=f"✅ {title}",
            description=description,
            color=discord.Color.green()
        )
        embed.timestamp = discord.utils.utcnow()
        return embed
    
    def _create_error_embed(self, title: str, description: str = "") -> discord.Embed:
        """Create a red error embed."""
        embed = discord.Embed(
            title=f"❌ {title}",
            description=description,
            color=discord.Color.red()
        )
        embed.timestamp = discord.utils.utcnow()
        return embed
    
    def _create_update_embed(self, title: str, description: str = "") -> discord.Embed:
        """Create an orange update embed."""
        embed = discord.Embed(
            title=f"📝 {title}",
            description=description,
            color=discord.Color.orange()
        )
        embed.timestamp = discord.utils.utcnow()
        return embed
    
    def _create_info_embed(self, title: str, description: str = "") -> discord.Embed:
        """Create a blue info embed."""
        embed = discord.Embed(
            title=f"ℹ️ {title}",
            description=description,
            color=discord.Color.blurple()
        )
        embed.timestamp = discord.utils.utcnow()
        return embed
    
    def _create_warning_embed(self, title: str, description: str = "") -> discord.Embed:
        """Create a yellow warning embed."""
        embed = discord.Embed(
            title=f"⚠️ {title}",
            description=description,
            color=discord.Color.from_rgb(255, 200, 50)
        )
        embed.timestamp = discord.utils.utcnow()
        return embed
    
    # ========================================================================
    # Configuration Commands
    # ========================================================================
    
    @commands.group(name="logging", invoke_without_command=True)
    @commands.has_permissions(administrator=True)
    async def logging_group(self, ctx: commands.Context):
        """
        Main command group for logging configuration.
        
        Displays a comprehensive help menu.
        """
        embed = discord.Embed(
            title="📊 VOTOX Logging System - Help Menu",
            description="Configure comprehensive server event logging.",
            color=discord.Color.blurple()
        )
        
        embed.add_field(
            name=".logging setup",
            value="Automatically create logging channels and enable logging.",
            inline=False
        )
        
        embed.add_field(
            name=".logging enable",
            value="Enable event logging for the server.",
            inline=False
        )
        
        embed.add_field(
            name=".logging disable",
            value="Disable logging and delete all logging channels.",
            inline=False
        )
        
        embed.set_footer(text="VOTOX Logging System")
        
        await ctx.send(embed=embed)
    
    @logging_group.command(name="setup")
    @commands.has_permissions(administrator=True)
    async def logging_setup(self, ctx: commands.Context):
        """
        Automatically set up logging environment.
        
        Creates:
        - A category named "VOTOX LOGS"
        - 5 text channels for different log types
        """
        try:
            # Create category
            category = await ctx.guild.create_category("VOTOX LOGS")
            
            # Create log channels
            message_logs = await ctx.guild.create_text_channel(
                "message-logs",
                category=category,
                topic="Logs for deleted and edited messages"
            )
            
            voice_logs = await ctx.guild.create_text_channel(
                "voice-logs",
                category=category,
                topic="Logs for voice channel activities"
            )
            
            member_logs = await ctx.guild.create_text_channel(
                "member-logs",
                category=category,
                topic="Logs for member join/leave and profile updates"
            )
            
            server_logs = await ctx.guild.create_text_channel(
                "server-logs",
                category=category,
                topic="Logs for server configuration changes"
            )
            
            moderation_logs = await ctx.guild.create_text_channel(
                "moderation-logs",
                category=category,
                topic="Logs for moderation actions (bans, unbans, etc.)"
            )
            
            # Save configuration
            config = await self._get_config(ctx.guild.id)
            config["enabled"] = True
            config["channels"] = {
                "message": message_logs.id,
                "voice": voice_logs.id,
                "member": member_logs.id,
                "server": server_logs.id,
                "moderation": moderation_logs.id
            }
            await self._save_config(ctx.guild.id, config)
            
            # Send confirmation
            embed = self._create_success_embed(
                "Logging Setup Complete",
                f"✅ Created category: **{category.name}**\n"
                f"✅ Created 5 log channels\n"
                f"✅ Logging is now **ENABLED**"
            )
            embed.add_field(name="Channels Created", value=
                f"📄 {message_logs.mention}\n"
                f"🎤 {voice_logs.mention}\n"
                f"👥 {member_logs.mention}\n"
                f"🔧 {server_logs.mention}\n"
                f"⚖️ {moderation_logs.mention}", inline=False)
            
            await ctx.send(embed=embed)
        
        except discord.Forbidden:
            embed = self._create_error_embed(
                "Permission Denied",
                "I lack the necessary permissions to create channels or categories."
            )
            await ctx.send(embed=embed)
        except Exception as e:
            embed = self._create_error_embed(
                "Setup Failed",
                f"An error occurred: {str(e)}"
            )
            await ctx.send(embed=embed)
    
    @logging_group.command(name="enable")
    @commands.has_permissions(administrator=True)
    async def logging_enable(self, ctx: commands.Context):
        """
        Enable event logging for the server.
        """
        config = await self._get_config(ctx.guild.id)
        
        if config["enabled"]:
            embed = self._create_info_embed(
                "Already Enabled",
                "Logging is already enabled for this server."
            )
            await ctx.send(embed=embed)
            return
        
        config["enabled"] = True
        await self._save_config(ctx.guild.id, config)
        
        embed = self._create_success_embed(
            "Logging Enabled",
            "Event logging is now active. All server events will be logged."
        )
        await ctx.send(embed=embed)
    
    @logging_group.command(name="disable")
    @commands.has_permissions(administrator=True)
    async def logging_disable(self, ctx: commands.Context):
        """
        Disable logging and delete all logging channels.
        
        Requires confirmation due to destructive nature.
        """
        config = await self._get_config(ctx.guild.id)
        
        if not config["enabled"]:
            embed = self._create_info_embed(
                "Already Disabled",
                "Logging is already disabled for this server."
            )
            await ctx.send(embed=embed)
            return
        
        # Create confirmation view
        embed = self._create_warning_embed(
            "⚠️ Disable Logging - Confirmation Required",
            "This action will:\n"
            "🗑️ Delete the **VOTOX LOGS** category\n"
            "🗑️ Delete all 5 logging channels\n"
            "🗑️ Disable event logging\n\n"
            "**This action cannot be undone.**"
        )
        
        view = LoggingDisableView(ctx.author.id)
        msg = await ctx.send(embed=embed, view=view)
        
        # Wait for confirmation
        await view.wait()
        
        if not view.confirmed:
            embed = self._create_info_embed("Cancelled", "Logging disable was cancelled.")
            await msg.edit(embed=embed, view=None)
            return
        
        # Disable logging
        config["enabled"] = False
        await self._save_config(ctx.guild.id, config)
        
        # Delete logging channels
        deleted_count = 0
        for channel_type in ["message", "voice", "member", "server", "moderation"]:
            channel_id = config["channels"].get(channel_type)
            if channel_id:
                try:
                    channel = ctx.guild.get_channel(channel_id)
                    if channel:
                        # Delete the channel
                        await channel.delete()
                        deleted_count += 1
                        config["channels"][channel_type] = None
                except discord.Forbidden:
                    pass
        
        # Try to delete the category
        category = None
        for cat in ctx.guild.categories:
            if cat.name == "VOTOX LOGS":
                category = cat
                break
        
        if category:
            try:
                await category.delete()
            except discord.Forbidden:
                pass
        
        embed = self._create_success_embed(
            "Logging Disabled",
            f"✅ Deleted {deleted_count} logging channels\n"
            f"✅ Logging is now **DISABLED**"
        )
        await msg.edit(embed=embed, view=None)
    
    # ========================================================================
    # Message Event Listeners
    # ========================================================================
    
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        """
        Log deleted messages.
        
        Args:
            message: The deleted message.
        """
        if not message.guild or message.author.bot:
            return
        
        if not await self._is_logging_enabled(message.guild.id):
            return
        
        log_channel = await self._get_log_channel(message.guild, "message")
        if not log_channel:
            return
        
        embed = self._create_error_embed(
            "Message Deleted",
            f"**Author:** {message.author.mention}\n"
            f"**Channel:** {message.channel.mention}\n"
            f"**Content:** {message.content or '*[No text content]*'}"
        )
        embed.set_author(name=str(message.author), icon_url=message.author.avatar.url if message.author.avatar else "")
        
        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            pass
    
    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """
        Log edited messages.
        
        Args:
            before: The message before editing.
            after: The message after editing.
        """
        if not before.guild or before.author.bot:
            return
        
        # Ignore if content hasn't changed
        if before.content == after.content:
            return
        
        if not await self._is_logging_enabled(before.guild.id):
            return
        
        log_channel = await self._get_log_channel(before.guild, "message")
        if not log_channel:
            return
        
        embed = self._create_update_embed(
            "Message Edited",
            f"**Author:** {before.author.mention}\n"
            f"**Channel:** {before.channel.mention}\n"
            f"**Before:** {before.content or '*[No text]*'}\n"
            f"**After:** {after.content or '*[No text]*'}"
        )
        embed.set_author(name=str(before.author), icon_url=before.author.avatar.url if before.author.avatar else "")
        
        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            pass
    
    # ========================================================================
    # Voice Event Listeners
    # ========================================================================
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        """
        Log voice channel activities (join, leave, move).
        
        Args:
            member: The member whose voice state changed.
            before: The voice state before the change.
            after: The voice state after the change.
        """
        if member.bot:
            return
        
        if not await self._is_logging_enabled(member.guild.id):
            return
        
        log_channel = await self._get_log_channel(member.guild, "voice")
        if not log_channel:
            return
        
        # Member joined a voice channel
        if before.channel is None and after.channel is not None:
            embed = self._create_success_embed(
                "Voice Channel - Member Joined",
                f"**Member:** {member.mention}\n"
                f"**Channel:** {after.channel.mention}"
            )
            embed.set_author(name=str(member), icon_url=member.avatar.url if member.avatar else "")
        
        # Member left a voice channel
        elif before.channel is not None and after.channel is None:
            embed = self._create_error_embed(
                "Voice Channel - Member Left",
                f"**Member:** {member.mention}\n"
                f"**Channel:** {before.channel.mention}"
            )
            embed.set_author(name=str(member), icon_url=member.avatar.url if member.avatar else "")
        
        # Member moved between voice channels
        elif before.channel != after.channel:
            embed = self._create_update_embed(
                "Voice Channel - Member Moved",
                f"**Member:** {member.mention}\n"
                f"**From:** {before.channel.mention}\n"
                f"**To:** {after.channel.mention}"
            )
            embed.set_author(name=str(member), icon_url=member.avatar.url if member.avatar else "")
        else:
            # Voice state changed but not channel (mute, deafen, etc.)
            return
        
        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            pass
    
    # ========================================================================
    # Member Event Listeners
    # ========================================================================
    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """
        Log member joins.
        
        Args:
            member: The member who joined.
        """
        if not await self._is_logging_enabled(member.guild.id):
            return
        
        log_channel = await self._get_log_channel(member.guild, "member")
        if not log_channel:
            return
        
        embed = self._create_success_embed(
            "Member Joined",
            f"**Member:** {member.mention}\n"
            f"**User ID:** {member.id}\n"
            f"**Account Created:** {member.created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        embed.set_author(name=str(member), icon_url=member.avatar.url if member.avatar else "")
        embed.set_thumbnail(url=member.avatar.url if member.avatar else "")
        
        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            pass
    
    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """
        Log member departures.
        
        Args:
            member: The member who left.
        """
        if not await self._is_logging_enabled(member.guild.id):
            return
        
        log_channel = await self._get_log_channel(member.guild, "member")
        if not log_channel:
            return
        
        embed = self._create_error_embed(
            "Member Left",
            f"**Member:** {member.mention}\n"
            f"**User ID:** {member.id}\n"
            f"**Joined At:** {member.joined_at.strftime('%Y-%m-%d %H:%M:%S') if member.joined_at else 'Unknown'} UTC"
        )
        embed.set_author(name=str(member), icon_url=member.avatar.url if member.avatar else "")
        embed.set_thumbnail(url=member.avatar.url if member.avatar else "")
        
        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            pass
    
    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """
        Log member profile updates.
        
        Args:
            before: The member before the update.
            after: The member after the update.
        """
        if not await self._is_logging_enabled(before.guild.id):
            return
        
        log_channel = await self._get_log_channel(before.guild, "member")
        if not log_channel:
            return
        
        # Check for nickname change
        if before.nick != after.nick:
            embed = self._create_update_embed(
                "Member Update - Nickname Changed",
                f"**Member:** {after.mention}\n"
                f"**Before:** {before.nick or 'No nickname'}\n"
                f"**After:** {after.nick or 'No nickname'}"
            )
            embed.set_author(name=str(after), icon_url=after.avatar.url if after.avatar else "")
            
            try:
                await log_channel.send(embed=embed)
            except discord.Forbidden:
                pass
        
        # Check for avatar change
        if before.avatar != after.avatar:
            embed = self._create_update_embed(
                "Member Update - Avatar Changed",
                f"**Member:** {after.mention}"
            )
            embed.set_author(name=str(after), icon_url=after.avatar.url if after.avatar else "")
            if after.avatar:
                embed.set_image(url=after.avatar.url)
            
            try:
                await log_channel.send(embed=embed)
            except discord.Forbidden:
                pass
        
        # Check for banner change
        if before.banner != after.banner:
            embed = self._create_update_embed(
                "Member Update - Banner Changed",
                f"**Member:** {after.mention}"
            )
            embed.set_author(name=str(after), icon_url=after.avatar.url if after.avatar else "")
            
            try:
                await log_channel.send(embed=embed)
            except discord.Forbidden:
                pass
    
    # ========================================================================
    # Server Event Listeners
    # ========================================================================
    
    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        """
        Log server configuration changes.
        
        Args:
            before: The guild before the update.
            after: The guild after the update.
        """
        if not await self._is_logging_enabled(before.id):
            return
        
        log_channel = await self._get_log_channel(after, "server")
        if not log_channel:
            return
        
        changes = []
        
        if before.name != after.name:
            changes.append(f"**Name:** {before.name} → {after.name}")
        
        if before.verification_level != after.verification_level:
            changes.append(f"**Verification Level:** {before.verification_level} → {after.verification_level}")
        
        if before.icon != after.icon:
            changes.append("**Icon:** Changed")
        
        if before.banner != after.banner:
            changes.append("**Banner:** Changed")
        
        if before.description != after.description:
            changes.append(f"**Description:** {before.description or 'None'} → {after.description or 'None'}")
        
        if before.preferred_locale != after.preferred_locale:
            changes.append(f"**Language:** {before.preferred_locale} → {after.preferred_locale}")
        
        if not changes:
            return
        
        embed = self._create_update_embed(
            "Server Update",
            "\n".join(changes)
        )
        embed.set_thumbnail(url=after.icon.url if after.icon else "")
        
        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            pass
    
    # ========================================================================
    # Moderation Event Listeners
    # ========================================================================
    
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        """
        Log member bans.
        
        Args:
            guild: The guild where the ban occurred.
            user: The user who was banned.
        """
        if not await self._is_logging_enabled(guild.id):
            return
        
        log_channel = await self._get_log_channel(guild, "moderation")
        if not log_channel:
            return
        
        embed = self._create_error_embed(
            "Member Banned",
            f"**User:** {user.mention}\n"
            f"**User ID:** {user.id}"
        )
        embed.set_author(name=str(user), icon_url=user.avatar.url if user.avatar else "")
        embed.set_thumbnail(url=user.avatar.url if user.avatar else "")
        
        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            pass
    
    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        """
        Log member unbans.
        
        Args:
            guild: The guild where the unban occurred.
            user: The user who was unbanned.
        """
        if not await self._is_logging_enabled(guild.id):
            return
        
        log_channel = await self._get_log_channel(guild, "moderation")
        if not log_channel:
            return
        
        embed = self._create_success_embed(
            "Member Unbanned",
            f"**User:** {user.mention}\n"
            f"**User ID:** {user.id}"
        )
        embed.set_author(name=str(user), icon_url=user.avatar.url if user.avatar else "")
        embed.set_thumbnail(url=user.avatar.url if user.avatar else "")
        
        try:
            await log_channel.send(embed=embed)
        except discord.Forbidden:
            pass


# Setup function to load the cog
async def setup(bot: commands.Bot):
    """
    Load the Logging cog into the bot.
    
    Args:
        bot: The Discord bot instance.
    """
    await bot.add_cog(Logging(bot))
