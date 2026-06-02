import discord
from discord.ext import commands, tasks
from typing import Optional, Dict, Any, Set, List
import asyncio
import re
from datetime import datetime, timedelta
import random
import aiosqlite
import json
from pathlib import Path

def parse_duration(duration_str: str) -> Optional[int]:
    """
    Parse duration string to seconds.
    
    Supports: 1d (days), 4h (hours), 30m (minutes), 10s (seconds)
    Example: "1d 4h 30m 10s" -> 100810 seconds
    
    Args:
        duration_str: Duration string
    
    Returns:
        Total seconds or None if invalid
    """
    if not duration_str:
        return None
    
    duration_str = duration_str.lower().strip()
    total_seconds = 0
    
    # Pattern to match number + unit
    pattern = r'(\d+)\s*([dhms])'
    matches = re.findall(pattern, duration_str)
    
    if not matches:
        return None
    
    unit_multipliers = {
        'd': 86400,   # days
        'h': 3600,    # hours
        'm': 60,      # minutes
        's': 1,       # seconds
    }
    
    for value, unit in matches:
        total_seconds += int(value) * unit_multipliers[unit]
    
    return total_seconds if total_seconds > 0 else None


def format_duration(seconds: int) -> str:
    """
    Format seconds to human-readable duration.
    
    Example: 3661 -> "1h 1m 1s"
    
    Args:
        seconds: Total seconds
    
    Returns:
        Human-readable duration string
    """
    if seconds <= 0:
        return "0s"
    
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0:
        parts.append(f"{secs}s")
    
    return " ".join(parts) if parts else "0s"


def format_remaining_time(end_time: datetime) -> str:
    """
    Format remaining time until end_time.
    
    Args:
        end_time: Target datetime
    
    Returns:
        Human-readable remaining time
    """
    remaining = (end_time - discord.utils.utcnow()).total_seconds()
    if remaining <= 0:
        return "ENDED"
    return format_duration(int(remaining))


class Giveaway(commands.Cog):
    """
    Giveaway management cog for VOTOX.
    
    Provides commands to host, customize, end, and reroll giveaways with beautiful embeds.
    """
    
    def __init__(self, bot: commands.Bot):
        """
        Initialize the Giveaway cog.
        
        Args:
            bot: The Discord bot instance
        """
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        self.giveaway_checker.start()
    
    def _get_db(self) -> aiosqlite.Connection:
        """Get database connection."""
        return aiosqlite.connect(self.db_path)

    def cog_unload(self):
        """Clean up when the cog is unloaded."""
        self.giveaway_checker.cancel()
    
    async def _get_active_giveaways(self) -> List[Dict]:
        """Fetch all active giveaways from the database."""
        async with self._get_db() as db:
            cursor = await db.execute("SELECT * FROM giveaways WHERE status = 'active'")
            rows = await cursor.fetchall()
            giveaways = []
            for r in rows:
                giveaways.append({
                    "guild_id": r[0],
                    "channel_id": r[1],
                    "message_id": r[2],
                    "prize": r[3],
                    "winners": r[4],
                    "end_time": datetime.fromisoformat(r[5]).replace(tzinfo=discord.utils.UTC),
                    "host_id": r[6]
                })
            return giveaways

    async def _get_customization(self, guild_id: int) -> Dict[str, Any]:
        """Retrieve guild-specific giveaway customization."""
        async with self._get_db() as db:
            cursor = await db.execute("SELECT config FROM giveaway_config WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
            return json.loads(row[0]) if row else {}

    @tasks.loop(seconds=5)
    async def giveaway_checker(self):
        """
        Background task to check and automatically end expired giveaways.
        Runs every 5 seconds.
        """
        active_giveaways = await self._get_active_giveaways()
        for giveaway in active_giveaways:
            if discord.utils.utcnow() >= giveaway["end_time"]:
                channel = self.bot.get_channel(giveaway["channel_id"])
                if channel:
                    try:
                        await self._end_giveaway_internal(
                            channel,
                            giveaway,
                            auto_end=True
                        )
                    except Exception as e:
                        print(f"Error auto-ending giveaway: {e}")
    
    @giveaway_checker.before_loop
    async def before_giveaway_checker(self):
        """Wait for bot to be ready before starting the checker."""
        await self.bot.wait_until_ready()
    
    async def _build_giveaway_embed(
        self,
        prize: str,
        host: discord.Member,
        end_time: datetime,
        winners_count: int,
        message_id: int = None,
        guild: discord.Guild = None
    ) -> discord.Embed:
        """
        Build a giveaway embed with custom overrides or default template.
        
        Args:
            prize: The giveaway prize
            host: Host member object
            end_time: When giveaway ends
            winners_count: Number of winners
            message_id: Optional message ID for tracking
            guild: Guild object for customization lookup
        
        Returns:
            Discord Embed object
        """
        customization = await self._get_customization(guild.id) if guild else {}
        
        # Variable replacements
        variables = {
            "{prize}": prize,
            "{duration}": format_remaining_time(end_time),
            "{winners_count}": str(winners_count),
            "{host}": host.mention,
        }
        
        # Get or use defaults
        title = customization.get("title") or "🎉 **GIVEAWAY** 🎉"
        description = customization.get("description") or (
            f"**Prize:** {prize}\n"
            f"**Host:** {host.mention}\n"
            f"**Winners:** {winners_count}\n"
            f"**Time Remaining:** {format_remaining_time(end_time)}\n\n"
            f"React with 🎉 to enter!"
        )
        image_url = customization.get("image")
        footer_text = customization.get("footer") or "VOTOX Giveaway System"
        
        # Apply variable replacements
        for var, value in variables.items():
            title = title.replace(var, value)
            description = description.replace(var, value)
            footer_text = footer_text.replace(var, value)
        
        embed = discord.Embed(
            title=title,
            description=description,
            color=self.bot.embed_color,
            timestamp=end_time
        )
        
        if image_url:
            embed.set_image(url=image_url)
        
        embed.set_footer(text=footer_text)
        embed.add_field(
            name="Entries",
            value="0",
            inline=False
        )
        
        return embed
    
    async def _get_giveaway_entries(self, message: discord.Message) -> Set[int]:
        """
        Get all unique users who reacted to the giveaway message.
        Filters out bots.
        
        Args:
            message: The giveaway message
        
        Returns:
            Set of user IDs
        """
        users = set()
        
        # Get all reactions on the message
        for reaction in message.reactions:
            async for user in reaction.users():
                if not user.bot:
                    users.add(user.id)
        
        return users
    
    async def _end_giveaway_internal(
        self,
        channel: discord.TextChannel,
        giveaway: Dict[str, Any],
        auto_end: bool = False
    ) -> None:
        """
        Internal method to end a giveaway and select winners.
        
        Args:
            channel: Channel where giveaway was hosted
            giveaway: Giveaway data dictionary
            auto_end: Whether this was automatically ended
        """
        try:
            # Get the giveaway message
            message = await channel.fetch_message(giveaway["message_id"])
        except discord.NotFound:
            return
        
        # Get all entries
        entries = await self._get_giveaway_entries(message)
        
        # Select winners
        winners_count = giveaway["winners"]
        winners = []
        
        if entries:
            # Select unique random winners
            winners_count = min(winners_count, len(entries))
            winner_ids = random.sample(list(entries), winners_count)
            
            for winner_id in winner_ids:
                user = await self.bot.fetch_user(winner_id)
                winners.append(user)
        
        # Update giveaway status in DB
        async with self._get_db() as db:
            await db.execute("UPDATE giveaways SET status = 'ended' WHERE message_id = ?", (giveaway["message_id"],))
            await db.commit()
        
        # Build results embed
        if winners:
            winners_mention = " ".join([w.mention for w in winners])
            embed = discord.Embed(
                title="🎉 Giveaway Ended!",
                description=(
                    f"**Prize:** {giveaway['prize']}\n"
                    f"**Winner(s):** {winners_mention}\n"
                    f"**Total Entries:** {len(entries)}"
                ),
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="VOTOX Giveaway System")
        else:
            embed = discord.Embed(
                title="❌ Giveaway Ended - No Winners",
                description=(
                    f"**Prize:** {giveaway['prize']}\n"
                    f"**Reason:** No entries received"
                ),
                color=discord.Color.red(),
                timestamp=discord.utils.utcnow()
            )
            embed.set_footer(text="VOTOX Giveaway System")
        
        # Send results
        await channel.send(embed=embed)
        
        # Try to add checkmark reaction to original message
        try:
            await message.add_reaction("✅")
        except discord.Forbidden:
            pass
    
    @commands.group(name="giveaway", invoke_without_command=True)
    @commands.guild_only()
    async def giveaway(self, ctx: commands.Context):
        """
        🎉 Giveaway Management System
        
        Use `.giveaway <subcommand>` to manage giveaways.
        """
        # If no subcommand provided, show help
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🎉 VOTOX Giveaway System",
                description="Comprehensive giveaway hosting and management",
                color=self.bot.embed_color,
            )
            
            embed.add_field(
                name="📋 Core Commands",
                value=(
                    "`.giveaway start <prize> <duration> [winners]` - Start a giveaway\n"
                    "`.giveaway end` - End current giveaway\n"
                    "`.giveaway reroll` - Reroll a winner"
                ),
                inline=False
            )
            
            embed.add_field(
                name="🎨 Customization Commands",
                value=(
                    "`.giveaway embed title <text>` - Set custom title\n"
                    "`.giveaway embed description <text>` - Set custom description\n"
                    "`.giveaway embed image <url>` - Set custom image\n"
                    "`.giveaway embed footer <text>` - Set custom footer"
                ),
                inline=False
            )
            
            embed.add_field(
                name="⏱️ Duration Format",
                value=(
                    "Use: `1d`, `4h`, `30m`, `10s`\n"
                    "Examples: `1d 2h 30m`, `2h 15m`, `45m`"
                ),
                inline=False
            )
            
            embed.add_field(
                name="💡 Variable Support",
                value=(
                    "{prize} - Current giveaway prize\n"
                    "{duration} - Remaining time\n"
                    "{winners_count} - Number of winners\n"
                    "{host} - Giveaway host mention"
                ),
                inline=False
            )
            
            embed.set_footer(text="Staff only • React 🎉 to enter giveaways")
            
            await ctx.send(embed=embed)
    
    @giveaway.command(name="start")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def giveaway_start(
        self,
        ctx: commands.Context,
        *,
        args: str
    ):
        """
        Start a giveaway.
        
        Syntax: .giveaway start <prize> <duration> [winners]
        Example: .giveaway start "Steam Gift Card" 1d 2h 1
        """
        # Parse arguments
        # Format: "prize" duration [winners]
        parts = args.strip().split()
        
        if len(parts) < 2:
            embed = discord.Embed(
                title="❌ Invalid Syntax",
                description="`.giveaway start <prize> <duration> [winners]`",
                color=discord.Color.red(),
            )
            embed.add_field(
                name="Example",
                value="`.giveaway start \"Steam Card\" 1d 2h 2`"
            )
            await ctx.send(embed=embed)
            return
        
        # Extract components - find quoted prize or first word
        if args.startswith('"'):
            # Quoted prize
            end_quote = args.find('"', 1)
            if end_quote == -1:
                await ctx.send("❌ Unclosed quote in prize name")
                return
            prize = args[1:end_quote]
            remaining = args[end_quote + 1:].strip().split()
        else:
            # Non-quoted prize (single word)
            prize = parts[0]
            remaining = parts[1:]
        
        if not remaining:
            await ctx.send("❌ Duration is required")
            return
        
        # Parse duration (can be multiple parts like "1d 2h")
        duration_parts = []
        winners = 1
        
        for part in remaining:
            if re.match(r'\d+[dhms]', part):
                duration_parts.append(part)
            else:
                # Try to parse as winners count
                try:
                    winners = int(part)
                except ValueError:
                    pass
        
        if not duration_parts:
            await ctx.send("❌ Invalid duration format. Use: 1d, 4h, 30m, 10s")
            return
        
        duration_str = " ".join(duration_parts)
        duration_seconds = parse_duration(duration_str)
        
        if not duration_seconds or duration_seconds < 1:
            await ctx.send("❌ Invalid duration format. Use: 1d, 4h, 30m, 10s")
            return
        
        if winners < 1:
            await ctx.send("❌ Winners count must be at least 1")
            return
        
        # Check if there's already an active giveaway
        active = await self._get_active_giveaways()
        if any(g['channel_id'] == ctx.channel.id for g in active):
            embed = discord.Embed(
                title="❌ Giveaway Already Active",
                description="There is already an active giveaway in this channel",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return
        
        # Calculate end time
        end_time = discord.utils.utcnow() + timedelta(seconds=duration_seconds)
        
        # Build and send giveaway embed
        embed = await self._build_giveaway_embed(
            prize=prize,
            host=ctx.author,
            end_time=end_time,
            winners_count=winners,
            guild=ctx.guild
        )
        
        giveaway_message = await ctx.send(embed=embed)
        
        # Add entry reaction
        try:
            await giveaway_message.add_reaction("🎉")
        except discord.Forbidden:
            await ctx.send("⚠️ Missing permission to add reactions")
            return
        
        async with self._get_db() as db:
            await db.execute(
                "INSERT INTO giveaways (guild_id, channel_id, message_id, prize, winners, end_time, host_id, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (ctx.guild.id, ctx.channel.id, giveaway_message.id, prize, winners, end_time.isoformat(), ctx.author.id, 'active')
            )
            await db.commit()
        
        # Confirmation
        embed = discord.Embed(
            title="✅ Giveaway Started!",
            description=(
                f"**Prize:** {prize}\n"
                f"**Duration:** {format_duration(duration_seconds)}\n"
                f"**Winners:** {winners}\n"
                f"**Ends:** <t:{int(end_time.timestamp())}:R>"
            ),
            color=discord.Color.green(),
        )
        embed.set_footer(text="React with 🎉 to enter")
        
        await ctx.send(embed=embed, delete_after=30)
    
    @giveaway.command(name="end")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def giveaway_end(self, ctx: commands.Context):
        """Force-end the active giveaway in this channel immediately."""
        active_giveaways = await self._get_active_giveaways()
        giveaway = next((g for g in active_giveaways if g['channel_id'] == ctx.channel.id), None)
        if not giveaway:
            embed = discord.Embed(
                title="❌ No Active Giveaway",
                description="There is no active giveaway in this channel",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return
        
        # End the giveaway
        await self._end_giveaway_internal(ctx.channel, giveaway, auto_end=False)
        
        # Confirmation
        embed = discord.Embed(
            title="✅ Giveaway Ended",
            description="The giveaway has been forcefully ended and winners have been selected.",
            color=discord.Color.green(),
        )
        await ctx.send(embed=embed, delete_after=30)
    
    @giveaway.command(name="reroll")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def giveaway_reroll(self, ctx: commands.Context):
        """Reroll a new winner from the most recently ended giveaway."""
        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT * FROM giveaways WHERE channel_id = ? AND status = 'ended' ORDER BY end_time DESC LIMIT 1",
                (ctx.channel.id,)
            )
            r = await cursor.fetchone()
            if not r:
                giveaway = None
            else:
                giveaway = {
                    "guild_id": r[0],
                    "channel_id": r[1],
                    "message_id": r[2],
                    "prize": r[3],
                    "winners": r[4]
                }
        
        if not giveaway:
            embed = discord.Embed(
                title="❌ No Previous Giveaway",
                description="There is no previous giveaway to reroll in this channel",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return
        
        # Get the original message
        try:
            message = await ctx.channel.fetch_message(giveaway["message_id"])
        except discord.NotFound:
            embed = discord.Embed(
                title="❌ Original Message Not Found",
                description="Could not fetch the original giveaway message",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return
        
        # Get entries
        entries = await self._get_giveaway_entries(message)
        
        if not entries:
            embed = discord.Embed(
                title="❌ No Entries",
                description="There are no entries to reroll from",
                color=discord.Color.red(),
            )
            await ctx.send(embed=embed)
            return
        
        # Select new winner
        winner_id = random.choice(list(entries))
        winner = await self.bot.fetch_user(winner_id)
        
        embed = discord.Embed(
            title="🎉 Reroll Complete!",
            description=(
                f"**Prize:** {giveaway['prize']}\n"
                f"**New Winner:** {winner.mention}\n"
                f"**Total Entries:** {len(entries)}"
            ),
            color=discord.Color.green(),
                timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="VOTOX Giveaway System")
        
        await ctx.send(embed=embed)
    
    @giveaway.group(name="embed")
    @commands.guild_only()
    @commands.has_permissions(manage_guild=True)
    async def giveaway_embed(self, ctx: commands.Context):
        """Customize giveaway embed appearance."""
        if ctx.invoked_subcommand is None:
            embed = discord.Embed(
                title="🎨 Giveaway Embed Customization",
                description="Customize how giveaway embeds appear",
                color=self.bot.embed_color,
            )
            
            embed.add_field(
                name="Available Commands",
                value=(
                    "`.giveaway embed title <text>` - Set embed title\n"
                    "`.giveaway embed description <text>` - Set embed description\n"
                    "`.giveaway embed image <url>` - Set embed image\n"
                    "`.giveaway embed footer <text>` - Set embed footer"
                ),
                inline=False
            )
            
            embed.add_field(
                name="Variable Support",
                value=(
                    "{prize} - Current giveaway prize\n"
                    "{duration} - Remaining time\n"
                    "{winners_count} - Number of winners\n"
                    "{host} - Giveaway host mention"
                ),
                inline=False
            )
            
            embed.set_footer(text="All customizations are guild-specific")
            
            await ctx.send(embed=embed)
    
    @giveaway_embed.command(name="title")
    async def embed_title(self, ctx: commands.Context, *, text: str):
        """Set custom embed title."""
        if not text or len(text) > 256:
            await ctx.send("❌ Title must be between 1 and 256 characters")
            return
        
        config = await self._get_customization(ctx.guild.id)
        config["title"] = text
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO giveaway_config (guild_id, config) VALUES (?, ?)",
                (ctx.guild.id, json.dumps(config))
            )
            await db.commit()
        
        embed = discord.Embed(
            title="✅ Title Updated",
            description=f"**New Title:** {text}",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Variable Support",
            value="{prize}, {duration}, {winners_count}, {host}"
        )
        
        await ctx.send(embed=embed, delete_after=30)
    
    @giveaway_embed.command(name="description")
    async def embed_description(self, ctx: commands.Context, *, text: str):
        """Set custom embed description."""
        if not text or len(text) > 4096:
            await ctx.send("❌ Description must be between 1 and 4096 characters")
            return
        
        config = await self._get_customization(ctx.guild.id)
        config["description"] = text
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO giveaway_config (guild_id, config) VALUES (?, ?)",
                (ctx.guild.id, json.dumps(config))
            )
            await db.commit()
        
        embed = discord.Embed(
            title="✅ Description Updated",
            description=f"**New Description:**\n{text}",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Variable Support",
            value="{prize}, {duration}, {winners_count}, {host}"
        )
        
        await ctx.send(embed=embed, delete_after=30)
    
    @giveaway_embed.command(name="image")
    async def embed_image(self, ctx: commands.Context, url: str):
        """Set custom embed image URL."""
        # Basic URL validation
        if not url.startswith(("http://", "https://")):
            await ctx.send("❌ Invalid URL. Must start with http:// or https://")
            return
        
        config = await self._get_customization(ctx.guild.id)
        config["image"] = url
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO giveaway_config (guild_id, config) VALUES (?, ?)",
                (ctx.guild.id, json.dumps(config))
            )
            await db.commit()
        
        embed = discord.Embed(
            title="✅ Image URL Updated",
            description=f"**New Image URL:**\n{url}",
            color=discord.Color.green(),
        )
        
        await ctx.send(embed=embed, delete_after=30)
    
    @giveaway_embed.command(name="footer")
    async def embed_footer(self, ctx: commands.Context, *, text: str):
        """Set custom embed footer text."""
        if not text or len(text) > 2048:
            await ctx.send("❌ Footer must be between 1 and 2048 characters")
            return
        
        config = await self._get_customization(ctx.guild.id)
        config["footer"] = text
        async with self._get_db() as db:
            await db.execute(
                "INSERT OR REPLACE INTO giveaway_config (guild_id, config) VALUES (?, ?)",
                (ctx.guild.id, json.dumps(config))
            )
            await db.commit()
        
        embed = discord.Embed(
            title="✅ Footer Updated",
            description=f"**New Footer:**\n{text}",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="Variable Support",
            value="{prize}, {duration}, {winners_count}, {host}"
        )
        
        await ctx.send(embed=embed, delete_after=30)


async def setup(bot: commands.Bot) -> None:
    """Load the Giveaway cog into the bot."""
    await bot.add_cog(Giveaway(bot))
