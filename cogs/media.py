
import aiosqlite
from pathlib import Path
from discord.ext import commands
import re
from typing import Optional, Set, Dict, List
from datetime import datetime
import discord

class MediaChannel(commands.Cog):
    """
    A sophisticated media-only channel enforcement system with embed-based UI,
    bypass lists, and flexible link handling.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        self._cache: Dict[int, Dict] = {}

    def _get_db(self) -> aiosqlite.Connection:
        """Return a connection context manager for the SQLite database."""
        return aiosqlite.connect(self.db_path)

    # ========================= HELPER METHODS =========================

    async def _get_guild_config(self, guild_id: int) -> Dict:
        """Retrieve guild configuration from the database, initializing defaults if needed."""
        # Check cache first
        if guild_id in self._cache:
            return self._cache[guild_id]
        async with self._get_db() as db:
            # Get allowlink flag
            cursor = await db.execute("SELECT allow_links FROM media_channel_config WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
            allowlink = True if row is None else bool(row[0])
            # Get media channels
            cursor = await db.execute("SELECT channel_id FROM media_channels WHERE guild_id = ?", (guild_id,))
            channels = {r[0] for r in await cursor.fetchall()}
            # Get bypass users
            cursor = await db.execute("SELECT user_id FROM media_bypass_users WHERE guild_id = ?", (guild_id,))
            bypass = {r[0] for r in await cursor.fetchall()}
        config = {"media_channels": channels, "allowlink": allowlink, "bypass_users": bypass}
        self._cache[guild_id] = config
        return config

    async def _save_guild_config(self, guild_id: int, config: Dict) -> None:
        """Persist the media channel configuration for a guild to the DB."""
        async with self._get_db() as db:
            # Save allow_links flag
            await db.execute(
                "INSERT OR REPLACE INTO media_channel_config (guild_id, allow_links) VALUES (?, ?)",
                (guild_id, 1 if config["allowlink"] else 0)
            )
            # Sync media channels
            await db.execute("DELETE FROM media_channels WHERE guild_id = ?", (guild_id,))
            for ch_id in config["media_channels"]:
                await db.execute("INSERT INTO media_channels (guild_id, channel_id) VALUES (?, ?)", (guild_id, ch_id))
            # Sync bypass users
            await db.execute("DELETE FROM media_bypass_users WHERE guild_id = ?", (guild_id,))
            for u_id in config["bypass_users"]:
                await db.execute("INSERT INTO media_bypass_users (guild_id, user_id) VALUES (?, ?)", (guild_id, u_id))
            await db.commit()
        self._cache[guild_id] = config

    async def _is_media_channel(self, channel_id: int, guild_id: int) -> bool:
        """Check if a channel is configured as media‑only."""
        config = await self._get_guild_config(guild_id)
        return channel_id in config["media_channels"]

    async def _is_bypassed(self, user_id: int, guild_id: int) -> bool:
        """Check if a user is on the bypass list."""
        config = await self._get_guild_config(guild_id)
        return user_id in config["bypass_users"]

    def _contains_url(self, text: str) -> bool:
        """Check if text contains URLs (http/https links)."""
        url_pattern = r'https?://(?:www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b(?:[-a-zA-Z0-9()@:%_\+.~#?&/=]*)'
        return bool(re.search(url_pattern, text))

    def _create_embed_header(self, title: str, description: str, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        """Create a consistently styled embed header."""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        return embed

    def _create_success_embed(self, title: str, description: str) -> discord.Embed:
        """Create a success-styled embed."""
        return self._create_embed_header(title, description, discord.Color.green())

    def _create_error_embed(self, title: str, description: str) -> discord.Embed:
        """Create an error-styled embed."""
        return self._create_embed_header(title, description, discord.Color.red())

    def _create_warning_embed(self, title: str, description: str) -> discord.Embed:
        """Create a warning-styled embed."""
        return self._create_embed_header(title, description, discord.Color.gold())

    # ========================= COMMAND GROUPS =========================

    @commands.group(name="media", invoke_without_command=True)
    @commands.guild_only()
    async def media(self, ctx: commands.Context):
        """
        Display the help menu for media channel configuration.
        """
        embed = discord.Embed(
            title="🎬 Media Channel Manager",
            description="Manage media-only channels and bypass lists for your server.",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )

        embed.add_field(
            name="📋 Channel Commands",
            value="`media channel set <channel>` - Designate a channel as media-only\n"
                  "`media channel remove <channel>` - Remove media-only restriction\n"
                  "`media channel allowlink <on/off>` - Toggle link allowance (default: on)",
            inline=False
        )

        embed.add_field(
            name="👤 Bypass Commands",
            value="`media bypass add <user>` - Add user to bypass list\n"
                  "`media bypass remove <user>` - Remove user from bypass list\n"
                  "`media bypass list` - View all bypassed users",
            inline=False
        )

        embed.add_field(
            name="ℹ️ Information",
            value="Media channels only allow **attachments** (images, videos, etc.) and optionally **links**.\n"
                  "Plain text-only messages will be automatically deleted.\n"
                  "Bypassed users can send any content in media channels.",
            inline=False
        )

        embed.set_footer(text="Use 'media <command>' for more details")
        await ctx.send(embed=embed)

    # ========================= CHANNEL SUBCOMMANDS =========================

    @media.group(name="channel", invoke_without_command=True)
    @commands.guild_only()
    async def media_channel(self, ctx: commands.Context):
        """Manage media-only channels."""
        embed = self._create_error_embed(
            "⚠️ Missing Subcommand",
            "Use `media channel set`, `media channel remove`, or `media channel allowlink`"
        )
        await ctx.send(embed=embed)

    @media_channel.command(name="set")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def media_channel_set(self, ctx: commands.Context, channel: discord.TextChannel):
        """Designate a text channel as media-only."""
        config = await self._get_guild_config(ctx.guild.id)

        if channel.id in config["media_channels"]:
            embed = self._create_error_embed(
                "⚠️ Already Media Channel",
                f"{channel.mention} is already a media-only channel."
            )
            await ctx.send(embed=embed)
            return

        config["media_channels"].add(channel.id)
        await self._save_guild_config(ctx.guild.id, config)

        embed = self._create_success_embed(
            "✅ Channel Updated",
            f"{channel.mention} has been set as a **media-only channel**.\n\n"
            f"📌 Only attachments and media are allowed here."
        )
        embed.add_field(
            name="Current Settings",
            value=f"**Allow Links:** {'✅ Yes' if config['allowlink'] else '❌ No'}",
            inline=False
        )
        await ctx.send(embed=embed)

    @media_channel.command(name="remove")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def media_channel_remove(self, ctx: commands.Context, channel: discord.TextChannel):
        """Remove the media-only restriction from a channel."""
        config = await self._get_guild_config(ctx.guild.id)

        if channel.id not in config["media_channels"]:
            embed = self._create_error_embed(
                "⚠️ Not a Media Channel",
                f"{channel.mention} is not currently a media-only channel."
            )
            await ctx.send(embed=embed)
            return

        config["media_channels"].discard(channel.id)
        await self._save_guild_config(ctx.guild.id, config)

        embed = self._create_success_embed(
            "✅ Channel Unrestricted",
            f"{channel.mention} is no longer a media-only channel.\n\n"
            f"💬 All message types are now allowed."
        )
        await ctx.send(embed=embed)

    @media_channel.command(name="allowlink")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def media_channel_allowlink(self, ctx: commands.Context, toggle: str):
        """Toggle whether links/URLs are allowed in media channels."""
        toggle_lower = toggle.lower()

        if toggle_lower not in ("on", "off", "true", "false", "yes", "no", "1", "0"):
            embed = self._create_error_embed(
                "⚠️ Invalid Toggle",
                "Please use: `on`, `off`, `yes`, `no`, `true`, or `false`"
            )
            await ctx.send(embed=embed)
            return

        config = await self._get_guild_config(ctx.guild.id)
        new_state = toggle_lower in ("on", "true", "yes", "1")
        config["allowlink"] = new_state
        await self._save_guild_config(ctx.guild.id, config)

        status = "✅ **Enabled**" if new_state else "❌ **Disabled**"
        embed = self._create_success_embed(
            "🔗 Link Settings Updated",
            f"URLs in media channels are now {status}\n\n"
            f"Media channels will {'accept links' if new_state else 'reject links'} as valid content."
        )
        await ctx.send(embed=embed)

    # ========================= BYPASS SUBCOMMANDS =========================

    @media.group(name="bypass", invoke_without_command=True)
    @commands.guild_only()
    async def media_bypass(self, ctx: commands.Context):
        """Manage the media channel bypass list."""
        embed = self._create_error_embed(
            "⚠️ Missing Subcommand",
            "Use `media bypass add`, `media bypass remove`, or `media bypass list`"
        )
        await ctx.send(embed=embed)

    @media_bypass.command(name="add")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def media_bypass_add(self, ctx: commands.Context, user: discord.User):
        """Add a user to the media channel bypass list."""
        config = await self._get_guild_config(ctx.guild.id)

        if user.id in config["bypass_users"]:
            embed = self._create_error_embed(
                "⚠️ Already Bypassed",
                f"{user.mention} is already on the bypass list."
            )
            await ctx.send(embed=embed)
            return

        config["bypass_users"].add(user.id)
        await self._save_guild_config(ctx.guild.id, config)

        embed = self._create_success_embed(
            "✅ User Bypassed",
            f"{user.mention} has been added to the bypass list.\n\n"
            f"They can now send any content in media channels."
        )
        await ctx.send(embed=embed)

    @media_bypass.command(name="remove")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def media_bypass_remove(self, ctx: commands.Context, user: discord.User):
        """Remove a user from the media channel bypass list."""
        config = await self._get_guild_config(ctx.guild.id)

        if user.id not in config["bypass_users"]:
            embed = self._create_error_embed(
                "⚠️ Not Bypassed",
                f"{user.mention} is not on the bypass list."
            )
            await ctx.send(embed=embed)
            return

        config["bypass_users"].discard(user.id)
        await self._save_guild_config(ctx.guild.id, config)

        embed = self._create_success_embed(
            "✅ Bypass Removed",
            f"{user.mention} has been removed from the bypass list.\n\n"
            f"They must now follow media-only channel restrictions."
        )
        await ctx.send(embed=embed)

    @media_bypass.command(name="list")
    @commands.guild_only()
    async def media_bypass_list(self, ctx: commands.Context):
        """Display all users on the media channel bypass list."""
        config = await self._get_guild_config(ctx.guild.id)

        if not config["bypass_users"]:
            embed = self._create_embed_header(
                "📋 Bypass List",
                "No users are currently on the media channel bypass list.",
                discord.Color.greyple()
            )
            await ctx.send(embed=embed)
            return

        # Fetch user objects
        bypass_list = []
        for user_id in config["bypass_users"]:
            try:
                user = await self.bot.fetch_user(user_id)
                bypass_list.append(f"• {user.mention} (`{user.id}`)")
            except discord.NotFound:
                bypass_list.append(f"• Unknown User (`{user_id}`)")

        embed = self._create_embed_header(
            "📋 Media Channel Bypass List",
            f"**Total Bypassed Users:** {len(bypass_list)}",
            discord.Color.blurple()
        )

        # Add users in chunks to avoid field limits
        user_text = "\n".join(bypass_list)
        if len(user_text) > 1024:
            # Split into multiple fields if needed
            current_chunk = []
            for user_line in bypass_list:
                test_text = "\n".join(current_chunk + [user_line])
                if len(test_text) > 1024:
                    embed.add_field(name="Bypassed Users", value="\n".join(current_chunk), inline=False)
                    current_chunk = [user_line]
                else:
                    current_chunk.append(user_line)
            if current_chunk:
                embed.add_field(name="Bypassed Users", value="\n".join(current_chunk), inline=False)
        else:
            embed.add_field(name="Bypassed Users", value=user_text, inline=False)

        await ctx.send(embed=embed)

    # ========================= EVENT HANDLERS =========================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """
        Monitor messages in media channels and enforce media-only restrictions.
        """
        # Ignore bot messages
        if message.author.bot:
            return

        # Ignore DMs
        if not message.guild:
            return

        # Check if this is a media channel
        if not await self._is_media_channel(message.channel.id, message.guild.id):
            return

        # Check if author is bypassed
        if await self._is_bypassed(message.author.id, message.guild.id):
            return

        config = await self._get_guild_config(message.guild.id)

        # Check if message has attachments (always allowed)
        if message.attachments:
            return

        # Check if links are allowed and message contains links
        if config["allowlink"] and self._contains_url(message.content):
            return

        # If we reach here, the message violates media-only rules
        try:
            # Delete the violating message
            await message.delete()

            # Create and send warning embed
            warning_embed = self._create_warning_embed(
                "🚫 Media-Only Channel",
                f"Plain text is not allowed here, {message.author.mention}.\n\n"
                f"Please share **images, videos, or other media**."
            )

            if config["allowlink"]:
                warning_embed.add_field(
                    name="💡 Tip",
                    value="Links and attachments are also welcome!",
                    inline=False
                )

            # Send the warning and delete it after 5 seconds
            try:
                warning_msg = await message.channel.send(embed=warning_embed, delete_after=5.0)
            except discord.Forbidden:
                # If bot can't send in channel, try DM
                try:
                    await message.author.send(embed=warning_embed)
                except discord.Forbidden:
                    pass

        except discord.Forbidden:
            # Bot lacks permission to delete messages
            pass


async def setup(bot):
    """Load the MediaChannel cog."""
    await bot.add_cog(MediaChannel(bot))
