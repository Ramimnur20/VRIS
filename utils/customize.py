"""
VOTOX Customize Cog - Per-guild bot appearance customization.

This cog allows server administrators to modify the bot's appearance
(nickname, avatar, banner, description) specifically for their server,
without affecting the bot globally.
"""

import discord
from discord.ext import commands
from typing import Optional, Dict, Any
import aiosqlite
from pathlib import Path
import aiohttp
import base64
import io
import re


class Customize(commands.Cog):
    """
    Allows server administrators to customize the bot's appearance
    (nickname, avatar, banner, description) for their specific server.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"

    def _get_db(self) -> aiosqlite.Connection:
        """Returns an aiosqlite connection to the database."""
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initializes database tables when the cog is loaded."""
        async with self._get_db() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS guild_bot_profile (
                    guild_id INTEGER PRIMARY KEY,
                    custom_name TEXT,
                    custom_pfp_url TEXT,
                    custom_banner_url TEXT,
                    custom_description TEXT
                )
            ''')
            await db.commit()

    # ========================= HELPER METHODS =========================

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        """Creates a styled Discord embed."""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="VOTOX Customize System")
        return embed

    def _create_success_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"✅ {title}", description, discord.Color.green())

    def _create_error_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"❌ {title}", description, discord.Color.red())

    def _create_info_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"ℹ️ {title}", description, discord.Color.blurple())

    async def _get_guild_profile(self, guild_id: int) -> Dict[str, Optional[str]]:
        """Retrieves the bot's custom profile for a guild from the database."""
        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT custom_name, custom_pfp_url, custom_banner_url, custom_description FROM guild_bot_profile WHERE guild_id = ?",
                (guild_id,)
            )
            row = await cursor.fetchone()
            if row:
                return {
                    "custom_name": row[0],
                    "custom_pfp_url": row[1],
                    "custom_banner_url": row[2],
                    "custom_description": row[3]
                }
            return {
                "custom_name": None,
                "custom_pfp_url": None,
                "custom_banner_url": None,
                "custom_description": None
            }

    async def _save_guild_profile(self, guild_id: int, profile_data: Dict[str, Optional[str]]):
        """Saves or updates the bot's custom profile for a guild in the database."""
        async with self._get_db() as db:
            await db.execute(
                """
                INSERT OR REPLACE INTO guild_bot_profile (guild_id, custom_name, custom_pfp_url, custom_banner_url, custom_description)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    guild_id,
                    profile_data.get("custom_name"),
                    profile_data.get("custom_pfp_url"),
                    profile_data.get("custom_banner_url"),
                    profile_data.get("custom_description")
                )
            )
            await db.commit()

    async def _delete_guild_profile(self, guild_id: int):
        """Deletes the bot's custom profile for a guild from the database."""
        async with self._get_db() as db:
            await db.execute("DELETE FROM guild_bot_profile WHERE guild_id = ?", (guild_id,))
            await db.commit()

    async def _fetch_image_as_base64(self, url: str) -> Optional[str]:
        """Fetches an image from a URL and returns it as a base64 data URI."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    response.raise_for_status()
                    image_bytes = await response.read()
                    # Determine content type for data URI
                    content_type = response.headers.get('Content-Type', 'image/png')
                    if not content_type.startswith('image/'):
                        raise ValueError("URL does not point to an image.")
                    
                    encoded_string = base64.b64encode(image_bytes).decode('utf-8')
                    return f"data:{content_type};base64,{encoded_string}"
        except aiohttp.ClientError as e:
            raise ValueError(f"Failed to fetch image from URL: {e}")
        except Exception as e:
            raise ValueError(f"An unexpected error occurred while processing image: {e}")

    # ========================= COMMANDS =========================

    @commands.group(name="customize", invoke_without_command=True)
    @commands.guild_only()
    @commands.cooldown(1, 3, commands.BucketType.default)
    async def customize_group(self, ctx: commands.Context):
        """
        Displays an elegant, Embed-formatted help menu detailing all available
        per-guild customization commands.
        """
        embed = self._create_embed(
            "✨ VOTOX Server Profile Customization",
            "Customize VOTOX's appearance specifically for this server!"
        )
        embed.add_field(
            name="`customize name [name]`",
            value="Change my nickname on this server.",
            inline=False
        )
        embed.add_field(
            name="`customize pfp (attachment/url)`",
            value="Change my server avatar (profile picture).",
            inline=False
        )
        embed.add_field(
            name="`customize banner (attachment/url)`",
            value="Change my server profile banner.",
            inline=False
        )
        embed.add_field(
            name="`customize description [text...]`",
            value="Change my server profile 'About Me' description.",
            inline=False
        )
        embed.add_field(
            name="`customize reset`",
            value="Reset all server-specific customizations to my global defaults.",
            inline=False
        )
        embed.set_footer(text="All commands require Administrator permissions.")
        await ctx.send(embed=embed)

    @customize_group.command(name="name")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(administrator=True)
    async def customize_name(self, ctx: commands.Context, *, name: Optional[str] = None):
        """Changes the bot's nickname in the current server."""
        if name is not None and len(name) > 32:
            await ctx.send(embed=self._create_error_embed("Name Too Long", "Nickname cannot exceed 32 characters."))
            return

        try:
            await ctx.guild.me.edit(nick=name, reason=f"Customized by {ctx.author} via command")
            profile = await self._get_guild_profile(ctx.guild.id)
            profile["custom_name"] = name
            await self._save_guild_profile(ctx.guild.id, profile)

            if name:
                await ctx.send(embed=self._create_success_embed("Nickname Updated", f"My nickname has been set to `{name}`."))
            else:
                await ctx.send(embed=self._create_success_embed("Nickname Reset", "My nickname has been reset to default."))
        except discord.Forbidden:
            await ctx.send(embed=self._create_error_embed("Permission Denied", "I don't have permission to change my nickname. Ensure my role is above others and has 'Manage Nicknames'."))
        except Exception as e:
            await ctx.send(embed=self._create_error_embed("Error", f"Failed to change nickname: {e}"))

    @customize_group.command(name="pfp")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(administrator=True)
    async def customize_pfp(self, ctx: commands.Context, attachment: Optional[discord.Attachment] = None, url: Optional[str] = None):
        """Changes the bot's Server Avatar (per-guild PFP)."""
        image_url = None
        if attachment:
            image_url = attachment.url
        elif url:
            image_url = url
        
        if not image_url:
            await ctx.send(embed=self._create_error_embed("Missing Image", "Please provide an image attachment or a direct URL to an image."))
            return

        await ctx.defer()

        try:
            base64_image = await self._fetch_image_as_base64(image_url)
            await ctx.guild.me.edit(avatar=base64_image, reason=f"Customized by {ctx.author} via command")
            
            profile = await self._get_guild_profile(ctx.guild.id)
            profile["custom_pfp_url"] = image_url
            await self._save_guild_profile(ctx.guild.id, profile)

            embed = self._create_success_embed("Server Avatar Updated", "My server avatar has been updated!")
            embed.set_thumbnail(url=image_url)
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send(embed=self._create_error_embed("Permission Denied", "I don't have permission to change my server avatar. Ensure my role has 'Manage Webhooks' or 'Manage Guild'."))
        except ValueError as e:
            await ctx.send(embed=self._create_error_embed("Invalid Image", str(e)))
        except Exception as e:
            await ctx.send(embed=self._create_error_embed("Error", f"Failed to change server avatar: {e}"))

    @customize_group.command(name="banner")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(administrator=True)
    async def customize_banner(self, ctx: commands.Context, attachment: Optional[discord.Attachment] = None, url: Optional[str] = None):
        """Changes the bot's Server Banner (per-guild banner)."""
        image_url = None
        if attachment:
            image_url = attachment.url
        elif url:
            image_url = url
        
        if not image_url:
            await ctx.send(embed=self._create_error_embed("Missing Image", "Please provide an image attachment or a direct URL to an image."))
            return

        await ctx.defer()

        try:
            base64_image = await self._fetch_image_as_base64(image_url)
            
            # Use raw HTTP PATCH request for per-guild banner
            payload = {"banner": base64_image}
            await self.bot.http.request(
                discord.http.Route('PATCH', '/guilds/{guild_id}/members/@me', guild_id=ctx.guild.id),
                json=payload
            )
            
            profile = await self._get_guild_profile(ctx.guild.id)
            profile["custom_banner_url"] = image_url
            await self._save_guild_profile(ctx.guild.id, profile)

            embed = self._create_success_embed("Server Banner Updated", "My server banner has been updated!")
            embed.set_image(url=image_url)
            await ctx.send(embed=embed)
        except discord.Forbidden:
            await ctx.send(embed=self._create_error_embed("Permission Denied", "I don't have permission to change my server banner. Ensure my role has 'Manage Webhooks' or 'Manage Guild'."))
        except ValueError as e:
            await ctx.send(embed=self._create_error_embed("Invalid Image", str(e)))
        except discord.HTTPException as e:
            await ctx.send(embed=self._create_error_embed("API Error", f"Discord API returned an error: {e}"))
        except Exception as e:
            await ctx.send(embed=self._create_error_embed("Error", f"Failed to change server banner: {e}"))

    @customize_group.command(name="description")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(administrator=True)
    async def customize_description(self, ctx: commands.Context, *, text: Optional[str] = None):
        """Changes the bot's Server Bio / Description for the current server."""
        if text is not None and len(text) > 190: # Discord bio limit is 190 characters
            await ctx.send(embed=self._create_error_embed("Description Too Long", "Description cannot exceed 190 characters."))
            return

        await ctx.defer()

        try:
            # Use raw HTTP PATCH request for per-guild bio
            payload = {"bio": text}
            await self.bot.http.request(
                discord.http.Route('PATCH', '/guilds/{guild_id}/members/@me', guild_id=ctx.guild.id),
                json=payload
            )
            
            profile = await self._get_guild_profile(ctx.guild.id)
            profile["custom_description"] = text
            await self._save_guild_profile(ctx.guild.id, profile)

            if text:
                await ctx.send(embed=self._create_success_embed("Server Description Updated", f"My server description has been set to:\n```\n{text}\n```"))
            else:
                await ctx.send(embed=self._create_success_embed("Server Description Reset", "My server description has been reset to default."))
        except discord.Forbidden:
            await ctx.send(embed=self._create_error_embed("Permission Denied", "I don't have permission to change my server description. Ensure my role has 'Manage Webhooks' or 'Manage Guild'."))
        except discord.HTTPException as e:
            await ctx.send(embed=self._create_error_embed("API Error", f"Discord API returned an error: {e}"))
        except Exception as e:
            await ctx.send(embed=self._create_error_embed("Error", f"Failed to change server description: {e}"))

    @customize_group.command(name="reset")
    @commands.cooldown(1, 3, commands.BucketType.default)
    @commands.has_permissions(administrator=True)
    async def customize_reset(self, ctx: commands.Context):
        """Resets all per-guild customizations to the bot's global defaults."""
        await ctx.defer()

        try:
            # Reset nickname
            await ctx.guild.me.edit(nick=None, reason=f"Reset by {ctx.author} via command")
            
            # Reset avatar (pass None to revert to global)
            await ctx.guild.me.edit(avatar=None, reason=f"Reset by {ctx.author} via command")

            # Reset banner and description via raw HTTP
            payload = {"banner": None, "bio": None}
            await self.bot.http.request(
                discord.http.Route('PATCH', '/guilds/{guild_id}/members/@me', guild_id=ctx.guild.id),
                json=payload
            )

            # Delete from database
            await self._delete_guild_profile(ctx.guild.id)

            await ctx.send(embed=self._create_success_embed("Customizations Reset", "All server-specific customizations have been reset to my global defaults."))
        except discord.Forbidden:
            await ctx.send(embed=self._create_error_embed("Permission Denied", "I don't have permission to reset all customizations. Ensure my role has 'Manage Nicknames', 'Manage Webhooks', or 'Manage Guild'."))
        except discord.HTTPException as e:
            await ctx.send(embed=self._create_error_embed("API Error", f"Discord API returned an error during reset: {e}"))
        except Exception as e:
            await ctx.send(embed=self._create_error_embed("Error", f"Failed to reset customizations: {e}"))

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(f"This command is on cooldown. Try again in {error.retry_after:.2f}s.", ephemeral=True)
            return
        raise error


async def setup(bot: commands.Bot):
    """Loads the Customize cog into the bot."""
    await bot.add_cog(Customize(bot))