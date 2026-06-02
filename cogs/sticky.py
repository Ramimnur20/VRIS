import discord
from discord.ext import commands
import aiosqlite
import asyncio
from pathlib import Path
from typing import Optional, Dict
import logging
from collections import defaultdict

logger = logging.getLogger("VOTOX")

class Sticky(commands.Cog):
    """
    Manages 'sticky' messages that are automatically re-posted to stay at the bottom of the chat.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        # Dictionary to store a Lock for each channel to prevent race conditions
        self._locks: Dict[int, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _get_db(self) -> aiosqlite.Connection:
        """Returns an aiosqlite connection to the database."""
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initializes the sticky_messages table."""
        async with self._get_db() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS sticky_messages (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER PRIMARY KEY,
                    message_content TEXT NOT NULL,
                    last_message_id INTEGER
                )
            ''')
            await db.commit()

    # ========================= HELPER METHODS =========================

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        """Standard VOTOX styling for configuration embeds."""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="VOTOX Sticky System", icon_url=self.bot.user.display_avatar.url)
        return embed

    async def _delete_message_safe(self, channel: discord.TextChannel, message_id: int):
        """Attempts to delete a message while handling common Discord errors."""
        if not message_id:
            return
        try:
            msg = await channel.fetch_message(message_id)
            await msg.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            # Message already gone, or we can't delete it
            pass

    # ========================= EVENT LISTENERS =========================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Logic to re-post the sticky message when a new message is sent."""
        # 1. Ignore bots and DMs
        if message.author.bot or not message.guild:
            return

        # 2. Check if the channel has a sticky configuration
        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT message_content, last_message_id FROM sticky_messages WHERE channel_id = ?",
                (message.channel.id,)
            )
            row = await cursor.fetchone()

        if not row:
            return

        content, last_id = row

        # 3. Use a lock for this channel to prevent race conditions from multiple users typing at once
        async with self._locks[message.channel.id]:
            # Attempt to delete the previous sticky
            await self._delete_message_safe(message.channel, last_id)

            # Send the new sticky
            try:
                new_sticky = await message.channel.send(content)
                
                # Update database with the new message ID
                async with self._get_db() as db:
                    await db.execute(
                        "UPDATE sticky_messages SET last_message_id = ? WHERE channel_id = ?",
                        (new_sticky.id, message.channel.id)
                    )
                    await db.commit()
            except discord.Forbidden:
                # Permissions were likely revoked mid-operation
                pass

    # ========================= COMMANDS =========================

    @commands.group(name="sticky", invoke_without_command=True)
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_messages=True)
    async def sticky_group(self, ctx: commands.Context):
        """Displays the VOTOX Sticky help menu."""
        embed = self._create_embed(
            "📌 Sticky Message Management",
            "Sticky messages stay at the bottom of the channel and are re-posted whenever someone chats."
        )
        
        prefix = ctx.clean_prefix
        embed.add_field(
            name="Available Commands",
            value=(
                f"`{prefix}sticky add (channel) [message]` - Setup a sticky message.\n"
                f"`{prefix}sticky edit (channel) [new_message]` - Edit sticky content.\n"
                f"`{prefix}sticky remove (channel)` - Delete the sticky config.\n"
                f"`{prefix}sticky list` - View all stickies in this server."
            ),
            inline=False
        )
        await ctx.send(embed=embed)

    @sticky_group.command(name="add")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_messages=True)
    async def sticky_add(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None, *, message: str):
        """Registers a new sticky message for a channel."""
        target_channel = channel or ctx.channel

        async with self._get_db() as db:
            # Check if one already exists
            cursor = await db.execute("SELECT 1 FROM sticky_messages WHERE channel_id = ?", (target_channel.id,))
            if await cursor.fetchone():
                return await ctx.send(embed=self._create_embed(
                    "❌ Error", 
                    f"A sticky message already exists for {target_channel.mention}. Use `edit` instead.",
                    discord.Color.red()
                ))

        # Send the initial sticky message
        try:
            initial_msg = await target_channel.send(message)
        except discord.Forbidden:
            return await ctx.send(embed=self._create_embed(
                "❌ Permission Denied",
                f"I don't have permission to send messages in {target_channel.mention}.",
                discord.Color.red()
            ))

        # Save to database
        async with self._get_db() as db:
            await db.execute(
                "INSERT INTO sticky_messages (guild_id, channel_id, message_content, last_message_id) VALUES (?, ?, ?, ?)",
                (ctx.guild.id, target_channel.id, message, initial_msg.id)
            )
            await db.commit()

        await ctx.send(embed=self._create_embed(
            "✅ Sticky Added",
            f"Sticky message successfully configured for {target_channel.mention}.",
            discord.Color.green()
        ))

    @sticky_group.command(name="edit")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_messages=True)
    async def sticky_edit(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None, *, new_message: str):
        """Modifies the content of an existing sticky message."""
        target_channel = channel or ctx.channel

        async with self._get_db() as db:
            cursor = await db.execute("SELECT 1 FROM sticky_messages WHERE channel_id = ?", (target_channel.id,))
            if not await cursor.fetchone():
                return await ctx.send(embed=self._create_embed(
                    "❌ Not Found",
                    f"There is no sticky message configured for {target_channel.mention}.",
                    discord.Color.red()
                ))

            await db.execute(
                "UPDATE sticky_messages SET message_content = ? WHERE channel_id = ?",
                (new_message, target_channel.id)
            )
            await db.commit()

        await ctx.send(embed=self._create_embed(
            "✅ Sticky Updated",
            f"The content for {target_channel.mention} has been updated. It will update on the next message sent.",
            discord.Color.green()
        ))

    @sticky_group.command(name="remove", aliases=["delete", "del"])
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_messages=True)
    async def sticky_remove(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Deletes the sticky configuration for a channel."""
        target_channel = channel or ctx.channel

        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT last_message_id FROM sticky_messages WHERE channel_id = ?",
                (target_channel.id,)
            )
            row = await cursor.fetchone()

            if not row:
                return await ctx.send(embed=self._create_embed(
                    "❌ Not Found",
                    f"No sticky message is active in {target_channel.mention}.",
                    discord.Color.red()
                ))

            last_id = row[0]
            await db.execute("DELETE FROM sticky_messages WHERE channel_id = ?", (target_channel.id,))
            await db.commit()

        # Clean up the last message
        await self._delete_message_safe(target_channel, last_id)

        await ctx.send(embed=self._create_embed(
            "✅ Sticky Removed",
            f"The sticky message for {target_channel.mention} has been disabled and deleted.",
            discord.Color.green()
        ))

    @sticky_group.command(name="list")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(manage_messages=True)
    async def sticky_list(self, ctx: commands.Context):
        """Lists all active sticky messages in the current server."""
        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT channel_id, message_content FROM sticky_messages WHERE guild_id = ?",
                (ctx.guild.id,)
            )
            rows = await cursor.fetchall()

        if not rows:
            return await ctx.send(embed=self._create_embed(
                "📋 Active Stickies",
                "There are no sticky messages configured in this server.",
                discord.Color.blurple()
            ))

        embed = self._create_embed("📋 Active Server Stickies", color=discord.Color.blurple())
        
        for channel_id, content in rows:
            channel = ctx.guild.get_channel(channel_id)
            channel_name = channel.mention if channel else f"Deleted Channel (`{channel_id}`)"
            
            # Truncate content preview for the embed
            preview = content[:100] + "..." if len(content) > 100 else content
            embed.add_field(
                name=f"Channel: {channel.name if channel else 'Unknown'}",
                value=f"**Location:** {channel_name}\n**Content:** {preview}",
                inline=False
            )

        await ctx.send(embed=embed)

    # ========================= ERROR HANDLING =========================

    @sticky_add.error
    @sticky_edit.error
    @sticky_remove.error
    @sticky_list.error
    async def sticky_permissions_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(embed=self._create_embed(
                "❌ Permission Denied",
                "You require `Manage Messages` permissions to modify sticky configurations.",
                discord.Color.red()
            ))
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send(embed=self._create_embed(
                "❌ Guild Only",
                "This command can only be used within a server.",
                discord.Color.red()
            ))
        elif isinstance(error, commands.ChannelNotFound):
             await ctx.send(embed=self._create_embed(
                "❌ Error",
                "The specified channel was not found.",
                discord.Color.red()
            ))

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"This command is on cooldown. Try again in {error.retry_after:.2f}s.", ephemeral=True)
            return
        raise error

async def setup(bot: commands.Bot):
    """Loads the Sticky cog into the bot."""
    await bot.add_cog(Sticky(bot))