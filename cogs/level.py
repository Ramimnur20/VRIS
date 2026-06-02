import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import asyncio
import io
import math
import time
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
from PIL import Image, ImageDraw, ImageFont, ImageOps

logger = logging.getLogger("VOTOX")

class Leveling(commands.Cog):
    """
    Engagement-based XP system with dynamic level cards and role rewards.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        
        # In-memory cooldown tracking: {(guild_id, user_id): last_xp_timestamp}
        self._xp_cooldowns: Dict[Tuple[int, int], float] = {}
        
        # Cache for settings to reduce DB overhead on every message
        self._settings_cache: Dict[int, Dict[str, Any]] = {}

    def _get_db(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initialize database tables for leveling."""
        async with self._get_db() as db:
            # Settings: Enabled status, XP per message, Cooldown
            await db.execute('''
                CREATE TABLE IF NOT EXISTS level_settings (
                    guild_id INTEGER PRIMARY KEY,
                    enabled INTEGER DEFAULT 0,
                    xp_per_message INTEGER DEFAULT 15,
                    cooldown_seconds INTEGER DEFAULT 60
                )
            ''')
            # Users: Individual XP and Level stats
            await db.execute('''
                CREATE TABLE IF NOT EXISTS level_users (
                    guild_id INTEGER,
                    user_id INTEGER,
                    xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id)
                )
            ''')
            # Roles: Mapping levels to role IDs
            await db.execute('''
                CREATE TABLE IF NOT EXISTS level_roles (
                    guild_id INTEGER,
                    level INTEGER,
                    role_id INTEGER,
                    PRIMARY KEY (guild_id, level)
                )
            ''')
            await db.commit()

    # ========================= UTILITIES & CALC =========================

    def _xp_for_next_level(self, level: int) -> int:
        """
        Formula: XP_needed(L) = 100 * L^1.5 + 100
        This returns the total XP required to go from current level to the next.
        """
        return math.floor(100 * (level ** 1.5) + 100)

    async def _get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        """Fetch or default settings for a guild."""
        if guild_id in self._settings_cache:
            return self._settings_cache[guild_id]

        async with self._get_db() as db:
            cursor = await db.execute("SELECT enabled, xp_per_message, cooldown_seconds FROM level_settings WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
            if row:
                data = {"enabled": bool(row[0]), "xp_per_message": row[1], "cooldown_seconds": row[2]}
            else:
                data = {"enabled": False, "xp_per_message": 15, "cooldown_seconds": 60}
            
            self._settings_cache[guild_id] = data
            return data

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
        embed.set_footer(text="VOTOX Leveling Engine", icon_url=self.bot.user.display_avatar.url)
        return embed

    # ========================= IMAGE GENERATION =========================

    def _generate_level_card_sync(self, user_data: Dict[str, Any]) -> io.BytesIO:
        """Synchronous PIL logic for generating the card."""
        # Canvas settings
        width, height = 800, 250
        bg_color = (20, 20, 25, 255) # Dark aesthetic
        accent_color = (88, 101, 242, 255) # Blurple
        
        img = Image.new("RGBA", (width, height), bg_color)
        draw = ImageDraw.Draw(img)
        
        # 1. Handle Avatar
        avatar_raw = Image.open(io.BytesIO(user_data['avatar_bytes'])).convert("RGBA")
        avatar_raw = avatar_raw.resize((170, 170), Image.Resampling.LANCZOS)
        
        # Circular mask
        mask = Image.new("L", (170, 170), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.ellipse((0, 0, 170, 170), fill=255)
        
        avatar = ImageOps.fit(avatar_raw, mask.size, centering=(0.5, 0.5))
        avatar.putalpha(mask)
        img.paste(avatar, (40, 40), avatar)
        
        # 2. Text / Labels
        # Note: In production, you'd provide local paths to fonts like Roboto or Arial
        try:
            font_name = ImageFont.truetype("arial.ttf", 40)
            font_stats = ImageFont.truetype("arial.ttf", 30)
            font_small = ImageFont.truetype("arial.ttf", 22)
        except:
            font_name = ImageFont.load_default()
            font_stats = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # Username
        draw.text((240, 60), user_data['name'], font=font_name, fill=(255, 255, 255))
        
        # Rank & Level
        rank_text = f"RANK #{user_data['rank']}"
        level_text = f"LEVEL {user_data['level']}"
        
        # Calculate level text width for right-alignment
        draw.text((600, 60), level_text, font=font_stats, fill=accent_color)
        draw.text((450, 60), rank_text, font=font_stats, fill=(200, 200, 200))

        # XP Progress text
        xp_text = f"{user_data['current_xp']} / {user_data['needed_xp']} XP"
        draw.text((580, 155), xp_text, font=font_small, fill=(180, 180, 180))

        # 3. Progress Bar
        bar_x, bar_y = 240, 190
        bar_w, bar_h = 500, 30
        
        # Background bar
        draw.rounded_rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], radius=15, fill=(50, 50, 60))
        
        # Foreground bar (percentage)
        percentage = min(1.0, user_data['current_xp'] / user_data['needed_xp'])
        if percentage > 0:
            draw.rounded_rectangle([bar_x, bar_y, bar_x + (bar_w * percentage), bar_y + bar_h], radius=15, fill=accent_color)

        # Save to buffer
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        return buffer

    # ========================= COMMANDS =========================

    @commands.group(name="level", invoke_without_command=True, aliases=["rank"])
    @commands.guild_only()
    async def level_group(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """View your current level and XP progress."""
        target = member or ctx.author
        
        async with self._get_db() as db:
            cursor = await db.execute("SELECT xp, level FROM level_users WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, target.id))
            row = await cursor.fetchone()
            
            if not row:
                return await ctx.send(embed=self._create_embed("No Data", f"{target.display_name} hasn't earned any XP yet.", discord.Color.orange()))

            xp, level = row
            needed = self._xp_for_next_level(level)
            percentage = round((xp / needed) * 100, 1)

            embed = self._create_embed(f"✨ {target.display_name}'s Level")
            embed.set_thumbnail(url=target.display_avatar.url)
            embed.add_field(name="Level", value=f"**{level}**", inline=True)
            embed.add_field(name="Experience", value=f"**{xp}** / {needed} XP", inline=True)
            embed.add_field(name="Progress", value=f"**{percentage}%** to Level {level + 1}", inline=False)
            
            await ctx.send(embed=embed)

    @level_group.command(name="toggle")
    @commands.has_permissions(manage_guild=True)
    async def level_toggle(self, ctx: commands.Context):
        """Enable or disable the leveling system."""
        current = await self._get_guild_settings(ctx.guild.id)
        new_state = not current['enabled']
        
        async with self._get_db() as db:
            await db.execute(
                "INSERT INTO level_settings (guild_id, enabled) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET enabled = ?",
                (ctx.guild.id, int(new_state), int(new_state))
            )
            await db.commit()
        
        # Clear cache
        if ctx.guild.id in self._settings_cache:
            del self._settings_cache[ctx.guild.id]
            
        status = "Enabled" if new_state else "Disabled"
        await ctx.send(embed=self._create_embed("System Updated", f"Leveling system has been **{status}** for this server.", discord.Color.green()))

    @level_group.command(name="threshold")
    @commands.has_permissions(manage_guild=True)
    async def level_threshold(self, ctx: commands.Context, type: str, amount: int):
        """Configure XP reward per message. Syntax: .level threshold permessage 20"""
        if type.lower() != "permessage":
            return await ctx.send("Usage: `.level threshold permessage <amount>`")

        async with self._get_db() as db:
            await db.execute(
                "INSERT INTO level_settings (guild_id, xp_per_message) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET xp_per_message = ?",
                (ctx.guild.id, amount, amount)
            )
            await db.commit()

        if ctx.guild.id in self._settings_cache:
            del self._settings_cache[ctx.guild.id]

        await ctx.send(embed=self._create_embed("Threshold Updated", f"Users will now receive **{amount} XP** per message.", discord.Color.green()))

    @level_group.command(name="leaderboard", aliases=["lb"])
    async def level_leaderboard(self, ctx: commands.Context):
        """View the top 10 most active users in the server."""
        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT user_id, level, xp FROM level_users WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT 10",
                (ctx.guild.id,)
            )
            rows = await cursor.fetchall()

        if not rows:
            return await ctx.send("The leaderboard is currently empty.")

        description = ""
        for i, (user_id, level, xp) in enumerate(rows, 1):
            member = ctx.guild.get_member(user_id)
            name = member.mention if member else f"Unknown User (`{user_id}`)"
            medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"**#{i}**"
            description += f"{medal} {name} • Level **{level}** ({xp} XP)\n"

        embed = self._create_embed(f"🏆 {ctx.guild.name} Leaderboard", description)
        await ctx.send(embed=embed)

    @level_group.command(name="card")
    async def level_card(self, ctx: commands.Context, member: Optional[discord.Member] = None):
        """Generate a high-quality Level Card image."""
        target = member or ctx.author
        await ctx.typing()

        async with self._get_db() as db:
            cursor = await db.execute("SELECT xp, level FROM level_users WHERE guild_id = ? AND user_id = ?", (ctx.guild.id, target.id))
            user_row = await cursor.fetchone()
            
            if not user_row:
                return await ctx.send("No data found for this user.")

            # Get Rank
            cursor = await db.execute(
                "SELECT COUNT(*) FROM level_users WHERE guild_id = ? AND (level > ? OR (level = ? AND xp >= ?))",
                (ctx.guild.id, user_row[1], user_row[1], user_row[0])
            )
            rank = (await cursor.fetchone())[0]

        # Fetch avatar bytes
        avatar_bytes = await target.display_avatar.read()

        # Package data for the thread
        user_data = {
            "name": str(target),
            "level": user_row[1],
            "current_xp": user_row[0],
            "needed_xp": self._xp_for_next_level(user_row[1]),
            "rank": rank,
            "avatar_bytes": avatar_bytes
        }

        # Generate card in thread pool
        buffer = await asyncio.to_thread(self._generate_level_card_sync, user_data)
        
        file = discord.File(fp=buffer, filename=f"level_{target.id}.png")
        await ctx.send(file=file)

    # ========================= ROLE REWARDS =========================

    @level_group.group(name="role", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    async def level_role(self, ctx: commands.Context):
        """Manage level-up role rewards."""
        await ctx.send_help(ctx.command)

    @level_role.command(name="add")
    @commands.has_permissions(manage_guild=True)
    async def level_role_add(self, ctx: commands.Context, level: int, role: discord.Role):
        """Register a role reward for reaching a specific level."""
        async with self._get_db() as db:
            await db.execute(
                "INSERT INTO level_roles (guild_id, level, role_id) VALUES (?, ?, ?) ON CONFLICT(guild_id, level) DO UPDATE SET role_id = ?",
                (ctx.guild.id, level, role.id, role.id)
            )
            await db.commit()
        
        await ctx.send(embed=self._create_embed("Reward Added", f"Members will now receive {role.mention} upon reaching **Level {level}**.", discord.Color.green()))

    @level_role.command(name="remove")
    @commands.has_permissions(manage_guild=True)
    async def level_role_remove(self, ctx: commands.Context, level: int):
        """Remove a role reward from a specific level."""
        async with self._get_db() as db:
            await db.execute("DELETE FROM level_roles WHERE guild_id = ? AND level = ?", (ctx.guild.id, level))
            await db.commit()
            
        await ctx.send(embed=self._create_embed("Reward Removed", f"Removed role reward for **Level {level}**.", discord.Color.red()))

    @level_role.command(name="list")
    async def level_role_list(self, ctx: commands.Context):
        """Display all configured role rewards for the server."""
        async with self._get_db() as db:
            cursor = await db.execute("SELECT level, role_id FROM level_roles WHERE guild_id = ? ORDER BY level ASC", (ctx.guild.id,))
            rows = await cursor.fetchall()

        if not rows:
            return await ctx.send("No role rewards configured.")

        content = ""
        for level, role_id in rows:
            role = ctx.guild.get_role(role_id)
            content += f"Level **{level}**: {role.mention if role else 'Invalid Role'}\n"

        embed = self._create_embed(f"🎁 {ctx.guild.name} Role Rewards", content)
        await ctx.send(embed=embed)

    # ========================= LOGIC HANDLERS =========================

    async def _handle_level_up(self, message: discord.Message, new_level: int):
        """Process role rewards and notify the user on level up."""
        guild = message.guild
        member = message.author

        # 1. Check for role rewards
        async with self._get_db() as db:
            cursor = await db.execute("SELECT role_id FROM level_roles WHERE guild_id = ? AND level = ?", (guild.id, new_level))
            row = await cursor.fetchone()
            
            if row:
                role = guild.get_role(row[0])
                if role:
                    try:
                        await member.add_roles(role, reason=f"Leveling Reward: Reached Level {new_level}")
                    except discord.Forbidden:
                        logger.warning(f"Leveling: Hierarchy error assigning {role.name} to {member.name} in {guild.name}")

        # 2. Level up notification
        embed = self._create_embed(
            "Level Up! 🎊", 
            f"Congratulations {member.mention}! You've reached **Level {new_level}**.",
            discord.Color.gold()
        )
        await message.channel.send(embed=embed, delete_after=15)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """The core XP engine."""
        if message.author.bot or not message.guild:
            return

        settings = await self._get_guild_settings(message.guild.id)
        if not settings['enabled']:
            return

        # --- Cooldown Check ---
        key = (message.guild.id, message.author.id)
        now = time.time()
        last_time = self._xp_cooldowns.get(key, 0)
        
        if now - last_time < settings['cooldown_seconds']:
            return

        self._xp_cooldowns[key] = now

        # --- Process XP ---
        async with self._get_db() as db:
            # Get current stats
            cursor = await db.execute("SELECT xp, level FROM level_users WHERE guild_id = ? AND user_id = ?", (message.guild.id, message.author.id))
            row = await cursor.fetchone()
            
            if not row:
                current_xp, current_lvl = 0, 0
            else:
                current_xp, current_lvl = row

            # Add XP
            xp_to_add = settings['xp_per_message']
            new_xp = current_xp + xp_to_add
            
            # Level up check
            needed_for_next = self._xp_for_next_level(current_lvl)
            
            if new_xp >= needed_for_next:
                # Handle potential multi-level skips (though unlikely with cooldown)
                leveled_up = False
                while new_xp >= self._xp_for_next_level(current_lvl):
                    new_xp -= self._xp_for_next_level(current_lvl)
                    current_lvl += 1
                    leveled_up = True
                
                await db.execute(
                    "INSERT INTO level_users (guild_id, user_id, xp, level) VALUES (?, ?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = ?, level = ?",
                    (message.guild.id, message.author.id, new_xp, current_lvl, new_xp, current_lvl)
                )
                await db.commit()
                
                if leveled_up:
                    await self._handle_level_up(message, current_lvl)
            else:
                # standard increment
                await db.execute(
                    "INSERT INTO level_users (guild_id, user_id, xp, level) VALUES (?, ?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET xp = ?",
                    (message.guild.id, message.author.id, new_xp, current_lvl, new_xp)
                )
                await db.commit()

async def setup(bot: commands.Bot):
    await bot.add_cog(Leveling(bot))