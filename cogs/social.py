

import discord
from discord.ext import commands, tasks
from discord import app_commands
import aiohttp
import aiosqlite
import io
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple, Set, Union
from datetime import datetime, timedelta
import logging
import re
from urllib.parse import urlparse, parse_qs
import asyncio

logger = logging.getLogger("VOTOX")

class Social(commands.Cog):
   """
   Provides powerful social media utility features for YouTube and SoundCloud.
   """

   def __init__(self, bot: commands.Bot):
       self.bot = bot
       self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
       self.base_api_url = "http://193.122.157.22:4793"
       self.session: Optional[aiohttp.ClientSession] = None

       # Caches for database data to reduce I/O
       self.youtube_feeds_cache: Dict[int, Dict[str, Dict[str, Any]]] = {} # {guild_id: {channel_url: {discord_channel_id, last_video_id}}}
       self.youtube_roles_cache: Dict[int, Dict[str, Set[int]]] = {} # {guild_id: {channel_url: {role_id}}}

   async def cog_load(self):
       """
       Initializes the aiohttp session, database tables, loads cache,
       and starts the background task for YouTube feeds.
       """
       headers = {"User-Agent": "VOTOX/1.0 (Discord Bot)"}
       self.session = aiohttp.ClientSession(headers=headers)
       async with self._get_db() as db:
           await db.execute('''
               CREATE TABLE IF NOT EXISTS youtube_feeds (
                   guild_id INTEGER NOT NULL,
                   youtube_channel_url TEXT NOT NULL,
                   discord_channel_id INTEGER NOT NULL,
                   last_video_id TEXT,
                   PRIMARY KEY (guild_id, youtube_channel_url)
               )
           ''')
           await db.execute('''
               CREATE TABLE IF NOT EXISTS youtube_roles (
                   guild_id INTEGER NOT NULL,
                   youtube_channel_url TEXT NOT NULL,
                   role_id INTEGER NOT NULL,
                   PRIMARY KEY (guild_id, youtube_channel_url, role_id)
               )
           ''')
           await db.commit()
       await self._load_youtube_feed_cache()
       await self._load_youtube_role_cache()
       self.check_youtube_feeds.start()

   async def cog_unload(self):
       """
       Closes the aiohttp session and cancels the background task.
       """
       if self.session:
           await self.session.close()
       self.check_youtube_feeds.cancel()
       logger.info("Social cog unloaded and YouTube feed checker cancelled.")

   def _get_db(self) -> aiosqlite.Connection:
       """Returns an aiosqlite connection to the database."""
       return aiosqlite.connect(self.db_path)

   # ========================= CACHE MANAGEMENT =========================

   async def _load_youtube_feed_cache(self):
       """Loads all YouTube feed configurations into the in-memory cache."""
       self.youtube_feeds_cache.clear()
       async with self._get_db() as db:
           cursor = await db.execute("SELECT guild_id, youtube_channel_url, discord_channel_id, last_video_id FROM youtube_feeds")
           for guild_id, channel_url, discord_channel_id, last_video_id in await cursor.fetchall():
               if guild_id not in self.youtube_feeds_cache:
                   self.youtube_feeds_cache[guild_id] = {}
               self.youtube_feeds_cache[guild_id][channel_url] = {
                   "discord_channel_id": discord_channel_id,
                   "last_video_id": last_video_id
               }
       logger.debug(f"Loaded {sum(len(g) for g in self.youtube_feeds_cache.values())} YouTube feeds into cache.")

   async def _load_youtube_role_cache(self):
       """Loads all YouTube role configurations into the in-memory cache."""
       self.youtube_roles_cache.clear()
       async with self._get_db() as db:
           cursor = await db.execute("SELECT guild_id, youtube_channel_url, role_id FROM youtube_roles")
           for guild_id, channel_url, role_id in await cursor.fetchall():
               if guild_id not in self.youtube_roles_cache:
                   self.youtube_roles_cache[guild_id] = {}
               if channel_url not in self.youtube_roles_cache[guild_id]:
                   self.youtube_roles_cache[guild_id][channel_url] = set()
               self.youtube_roles_cache[guild_id][channel_url].add(role_id)
       logger.debug(f"Loaded {sum(len(c) for g in self.youtube_roles_cache.values() for c in g.values())} YouTube roles into cache.")

   # ========================= HELPER METHODS =========================

   def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
       """Creates a styled Discord embed."""
       embed = discord.Embed(
           title=title,
           description=description,
           color=color,
           timestamp=discord.utils.utcnow()
       )
       embed.set_footer(text="VOTOX Social System", icon_url=self.bot.user.display_avatar.url)
       return embed

   def _create_success_embed(self, title: str, description: str = None) -> discord.Embed:
       return self._create_embed(f"✅ {title}", description, discord.Color.green())

   def _create_error_embed(self, title: str, description: str = None) -> discord.Embed:
       return self._create_embed(f"❌ {title}", description, discord.Color.red())

   def _create_info_embed(self, title: str, description: str = None) -> discord.Embed:
       return self._create_embed(f"ℹ️ {title}", description, discord.Color.blurple())

   async def _fetch_api(self, endpoint: str, params: Optional[Dict[str, Any]] = None, timeout: int = 15) -> Optional[Dict[str, Any]]:
        """
        Makes an asynchronous GET request to the FastAPI backend.
        """
        url = f"{self.base_api_url}{endpoint}"
        if params:
            params = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in params.items()}
            
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                if response.status != 200:
                    logger.error(f"Social API error {response.status} at {url}")
                    return None
                return await response.json()
        except Exception as e:
            logger.error(f"Social API connection failed to {url}: {e}")
            return None

   async def _fetch_api_file(self, endpoint: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> Optional[bytes]:
        """
        Makes an asynchronous GET request to fetch file data.
        """
        url = f"{self.base_api_url}{endpoint}"
        if params:
            params = {k: (str(v).lower() if isinstance(v, bool) else v) for k, v in params.items()}
            
        try:
            async with self.session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout)) as response:
                if response.status != 200:
                    return None
                return await response.read()
        except Exception as e:
            logger.error(f"Social API file connection failed to {url}: {e}")
            return None

   def _extract_youtube_channel_id(self, url: str) -> Optional[str]:
       """Extracts YouTube channel ID from various URL formats."""
       parsed_url = urlparse(url)
       if "youtube.com" in parsed_url.netloc or "youtu.be" in parsed_url.netloc:
           # Handle channel URLs
           if "/channel/" in parsed_url.path:
               return parsed_url.path.split("/channel/")[1].split("/")[0]
           # Handle user URLs (legacy)
           if "/user/" in parsed_url.path:
               # This would require an API call to resolve to channel ID,
               # which is outside the scope of simple URL parsing.
               # For now, we'll return None or handle it as a search query.
               return None
           # Handle video URLs (can sometimes infer channel from video metadata, but not directly from URL)
           if "/watch" in parsed_url.path:
               return None # Cannot reliably get channel ID from video URL alone without API
       return None

   def _extract_youtube_video_id(self, url: str) -> Optional[str]:
       """Extracts YouTube video ID from various URL formats."""
       parsed_url = urlparse(url)
       if parsed_url.netloc in ("www.youtube.com", "youtube.com"):
           if parsed_url.path == "/watch":
               return parse_qs(parsed_url.query).get("v", [None])[0]
           if parsed_url.path.startswith("/embed/"):
               return parsed_url.path.split("/embed/")[1].split("?")[0]
           if parsed_url.path.startswith("/v/"):
               return parsed_url.path.split("/v/")[1].split("?")[0]
       elif parsed_url.netloc in ("youtu.be", "www.youtu.be"):
           return parsed_url.path[1:].split("?")[0]
       return None

   def _get_results(self, data: Any) -> List[Dict[str, Any]]:
       """Safely extract results list from various API response formats."""
       if isinstance(data, list):
           return data
       if isinstance(data, dict):
           return data.get("results", [])
       return []

   # ========================= YOUTUBE COMMANDS =========================

   @commands.hybrid_group(name="youtube", aliases=["yt"], invoke_without_command=True)
   @commands.guild_only()
   async def youtube_group(self, ctx: commands.Context):
       """
       Displays an elegant help menu detailing all available YouTube utilities.
       """
       embed = self._create_info_embed(
           "▶️ VOTOX YouTube Utilities",
           "Explore YouTube content, get video metadata, download media, and set up channel feeds!"
       )
       embed.add_field(name="🔍 Search & Info", value=(
           "`yt search <query>`: Search for videos\n"
           "`yt searchshorts <query>`: Search for YouTube Shorts\n"
           "`yt video <url>`: Get detailed video metadata\n"
           "`yt latest <channel_url_or_query>`: Get a channel's latest upload\n"
           "`yt playlist <url>`: Get playlist info (mock)"
       ), inline=False)
       embed.add_field(name="⬇️ Downloads", value=(
           "`yt download <url>`: Download video (Catbox link)\n"
           "`yt mp3 <url>`: Download audio (Catbox link)\n"
           "`yt screenshot <url> [timestamp]`: Capture video frame"
       ), inline=False)
       embed.add_field(name="🔔 Feeds & Roles", value=(
           "`yt feed add <channel_url> <discord_channel>`: Add channel feed\n"
           "`yt feed remove <channel_url>`: Remove channel feed\n"
           "`yt feed list`: List active feeds\n"
           "`yt feed test <channel_url>`: Test feed notification\n"
           "`yt role add <channel_url> <role>`: Add role to ping\n"
           "`yt role remove <channel_url> <role>`: Remove role from ping\n"
           "`yt role list <channel_url>`: List roles for a feed"
       ), inline=False)
       embed.set_footer(text=f"Use {ctx.clean_prefix}youtube <command> for more details.")
       await ctx.send(embed=embed)

   @youtube_group.command(name="search")
   @app_commands.describe(query="The search query for YouTube videos.")
   async def youtube_search(self, ctx: commands.Context, *, query: str):
       """
       Searches YouTube and returns the top 5 video results.
       """
       await ctx.typing()
       data = await self._fetch_api("/youtube/search", {"q": query, "count": 5})
       
       results = self._get_results(data)

       if data is None:
           await ctx.send(embed=self._create_error_embed("Search Failed", "Could not fetch search results from the API."))
           return
       if not results:
           await ctx.send(embed=self._create_info_embed("No Results", f"No YouTube videos found for '{query}'."))
           return

       embed = self._create_embed(f"🔍 YouTube Search Results for '{query}'", color=discord.Color.red())
       for i, video in enumerate(results[:5]):
           title = video.get("title", "N/A")
           channel = video.get("channel", "N/A")
           url = video.get("url", "#")
           embed.add_field(
               name=f"{i+1}. {title}",
               value=f"Channel: {channel}\n[Watch Here]({url})",
               inline=False
           )
       await ctx.send(embed=embed)

   @youtube_group.command(name="searchshorts")
   @app_commands.describe(query="The search query for YouTube Shorts.")
   async def youtube_searchshorts(self, ctx: commands.Context, *, query: str):
       """
       Searches YouTube specifically for short-form video content.
       """
       await ctx.typing()
       data = await self._fetch_api("/youtube/search", {"q": query, "count": 5, "shorts": True})
       
       results = self._get_results(data)

       if data is None:
           await ctx.send(embed=self._create_error_embed("Search Failed", "Could not fetch search results from the API."))
           return
       if not results:
           await ctx.send(embed=self._create_info_embed("No Results", f"No YouTube Shorts found for '{query}'."))
           return

       embed = self._create_embed(f"🎬 YouTube Shorts Search Results for '{query}'", color=discord.Color.red())
       for i, video in enumerate(results[:5]):
           title = video.get("title", "N/A")
           channel = video.get("channel", "N/A")
           url = video.get("url", "#")
           embed.add_field(
               name=f"{i+1}. {title}",
               value=f"Channel: {channel}\n[Watch Here]({url})",
               inline=False
           )
       await ctx.send(embed=embed)

   @youtube_group.command(name="video")
   @app_commands.describe(url="The URL of the YouTube video.")
   async def youtube_video(self, ctx: commands.Context, url: str):
       """
       Extracts and displays detailed metadata for a specific YouTube video.
       """
       await ctx.typing()
       data = await self._fetch_api("/youtube/video", {"url": url})

       if not data:
           await ctx.send(embed=self._create_error_embed("Metadata Failed", "Could not fetch video metadata from the API. Check the URL."))
           return

       embed = self._create_embed(data.get("title", "N/A"), description=data.get("description_snippet", "No description available."), color=discord.Color.red())
       embed.set_thumbnail(url=data.get("thumbnail", discord.Embed.Empty))
       embed.add_field(name="Channel", value=data.get("channel", "N/A"), inline=True)
       embed.add_field(name="Views", value=f"{int(data['views']):,}" if data.get("views") else "N/A", inline=True)
       embed.add_field(name="Length", value=str(timedelta(seconds=data.get("length_seconds", 0))) if data.get("length_seconds") else "N/A", inline=True)
       embed.add_field(name="Published", value=data.get("publish_date", "N/A"), inline=True)
       embed.add_field(name="URL", value=f"[Watch Video]({url})", inline=False)
       await ctx.send(embed=embed)

   @youtube_group.command(name="download")
   @app_commands.describe(url="The URL of the YouTube video to download.")
   async def youtube_download(self, ctx: commands.Context, url: str):
       """
       Downloads a YouTube video and provides a Catbox mirror URL.
       """
       await ctx.typing()
       data = await self._fetch_api("/youtube/download/video", {"url": url, "catbox": True})

       if not data or not data.get("url"):
           await ctx.send(embed=self._create_error_embed("Download Failed", "Could not generate download link. Check the URL."))
           return

       embed = self._create_success_embed("⬇️ YouTube Video Download", f"Click the button below to download your video from Catbox!")
       embed.add_field(name="Video Title", value=data.get("title", "N/A"), inline=False)
       embed.set_thumbnail(url=data.get("thumbnail", discord.Embed.Empty))

       view = discord.ui.View()
       view.add_item(discord.ui.Button(label="Download Video", url=data["url"], style=discord.ButtonStyle.link))
       await ctx.send(embed=embed, view=view)

   @youtube_group.command(name="mp3")
   @app_commands.describe(url="The URL of the YouTube video to extract audio from.")
   async def youtube_mp3(self, ctx: commands.Context, url: str):
       """
       Downloads only the audio element of a YouTube video to a Catbox link.
       """
       await ctx.typing()
       data = await self._fetch_api("/youtube/download/audio", {"url": url, "catbox": True})

       if not data or not data.get("url"):
           await ctx.send(embed=self._create_error_embed("MP3 Download Failed", "Could not generate MP3 download link. Check the URL."))
           return

       embed = self._create_success_embed("🎵 YouTube MP3 Download", f"Click the button below to download your audio from Catbox!")
       embed.add_field(name="Track Title", value=data.get("title", "N/A"), inline=False)
       embed.set_thumbnail(url=data.get("thumbnail", discord.Embed.Empty))

       view = discord.ui.View()
       view.add_item(discord.ui.Button(label="Download MP3", url=data["url"], style=discord.ButtonStyle.link))
       await ctx.send(embed=embed, view=view)

   @youtube_group.command(name="screenshot")
   @app_commands.describe(url="The URL of the YouTube video.", timestamp="Timestamp in seconds or HH:MM:SS format (e.g., 135 or 00:02:15).")
   async def youtube_screenshot(self, ctx: commands.Context, url: str, timestamp: str):
       """
       Captures a high-quality visual frame at the given timestamp and sends the image.
       """
       await ctx.typing()

       # Convert HH:MM:SS to seconds if needed
       if re.match(r'^\d{2}:\d{2}:\d{2}$', timestamp):
           h, m, s = map(int, timestamp.split(':'))
           timestamp_seconds = h * 3600 + m * 60 + s
       else:
           try:
               timestamp_seconds = int(timestamp)
           except ValueError:
               await ctx.send(embed=self._create_error_embed("Invalid Timestamp", "Timestamp must be in seconds or HH:MM:SS format."))
               return

       image_data = await self._fetch_api_file("/youtube/download/frame", {"url": url, "timestamp": timestamp_seconds, "catbox": True})

       if not image_data:
           await ctx.send(embed=self._create_error_embed("Screenshot Failed", "Could not capture screenshot. Check the URL and timestamp."))
           return

       file = discord.File(io.BytesIO(image_data), filename="screenshot.png")
       embed = self._create_success_embed("📸 YouTube Screenshot", f"Screenshot from `{url}` at `{timestamp}`.")
       embed.set_image(url="attachment://screenshot.png")
       await ctx.send(embed=embed, file=file)

   @youtube_group.command(name="playlist")
   @app_commands.describe(url="The URL of the YouTube playlist.")
   async def youtube_playlist(self, ctx: commands.Context, url: str):
       """
       Displays metadata about a playlist (mock functionality).
       """
       await ctx.typing()
       # As per instructions, mock functionality for playlist as no direct API support.
       embed = self._create_info_embed(
           "▶️ YouTube Playlist (Mock)",
           "Playlist functionality is currently under development or not directly supported by the backend API."
       )
       embed.add_field(name="Provided URL", value=url, inline=False)
       embed.add_field(name="Expected Info", value="This would typically show playlist title, author, video count, and a few video previews.", inline=False)
       embed.set_footer(text="This is a placeholder response.")
       await ctx.send(embed=embed)

   @youtube_group.command(name="latest")
   @app_commands.describe(channel_url_or_query="The YouTube channel URL or a search query for the channel.")
   async def youtube_latest(self, ctx: commands.Context, *, channel_url_or_query: str):
       """
       Grabs the absolute newest upload for a YouTube channel.
       """
       await ctx.typing()
       data = await self._fetch_api("/youtube/search", {"q": channel_url_or_query, "order": "newest", "count": 1})
       
       results = self._get_results(data)

       if data is None or not results:
           await ctx.send(embed=self._create_error_embed("Latest Video Failed", "Could not find the latest video for the given channel/query."))
           return

       video = results[0]
       embed = self._create_embed(f"✨ Latest Upload from {video.get('channel', 'N/A')}", description=video.get("title", "N/A"), color=discord.Color.red())
       embed.set_thumbnail(url=video.get("thumbnail", discord.Embed.Empty))
       embed.add_field(name="Views", value=f"{int(video['views']):,}" if video.get("views") else "N/A", inline=True)
       embed.add_field(name="Length", value=str(timedelta(seconds=video.get("length_seconds", 0))) if video.get("length_seconds") else "N/A", inline=True)
       embed.add_field(name="Published", value=video.get("publish_date", "N/A"), inline=True)
       embed.add_field(name="URL", value=f"[Watch Video]({video.get('url', 'N/A')})", inline=False)
       await ctx.send(embed=embed)

   # ========================= YOUTUBE FEED SUBGROUP =========================

   @youtube_group.group(name="feed")
   @commands.has_permissions(manage_channels=True)
   @commands.guild_only()
   async def youtube_feed_group(self, ctx: commands.Context):
       """
       Manage YouTube channel feed notifications for your server.
       """
       if ctx.invoked_subcommand is None:
           embed = self._create_info_embed(
               "🔔 YouTube Feed Management",
               "Set up and manage notifications for new YouTube uploads."
           )
           embed.add_field(name="Commands", value=(
               "`yt feed add <channel_url> <discord_channel>`: Add a new feed\n"
               "`yt feed remove <channel_url>`: Remove an existing feed\n"
               "`yt feed list`: List all active feeds\n"
               "`yt feed test <channel_url>`: Test a feed notification"
           ), inline=False)
           await ctx.send(embed=embed)

   @youtube_feed_group.command(name="add")
   @commands.has_permissions(manage_guild=True)
   @app_commands.describe(channel_url="The URL of the YouTube channel.", discord_channel="The Discord channel to send notifications to.")
   async def youtube_feed_add(self, ctx: commands.Context, channel_url: str, discord_channel: discord.TextChannel):
       """
       Connects a YouTube channel's upload updates to a specific Discord text channel.
       """
       await ctx.typing()

       # Validate channel_url (basic check)
       if "youtube.com/channel/" not in channel_url and "youtube.com/user/" not in channel_url:
           await ctx.send(embed=self._create_error_embed("Invalid Channel URL", "Please provide a valid YouTube channel URL."))
           return

       # Check if already exists
       if ctx.guild.id in self.youtube_feeds_cache and channel_url in self.youtube_feeds_cache[ctx.guild.id]:
           await ctx.send(embed=self._create_error_embed("Feed Already Exists", "This YouTube channel is already being tracked in this guild."))
           return

       # Get initial latest video ID
       latest_video_data = await self._fetch_api("/youtube/search", {"q": channel_url, "order": "newest", "count": 1})
       initial_results = self._get_results(latest_video_data)
       last_video_id = initial_results[0]["id"] if initial_results else None

       async with self._get_db() as db:
           await db.execute(
               "INSERT INTO youtube_feeds (guild_id, youtube_channel_url, discord_channel_id, last_video_id) VALUES (?, ?, ?, ?)",
               (ctx.guild.id, channel_url, discord_channel.id, last_video_id)
           )
           await db.commit()

       # Update cache
       if ctx.guild.id not in self.youtube_feeds_cache:
           self.youtube_feeds_cache[ctx.guild.id] = {}
       self.youtube_feeds_cache[ctx.guild.id][channel_url] = {
           "discord_channel_id": discord_channel.id,
           "last_video_id": last_video_id
       }

       embed = self._create_success_embed(
           "Feed Added",
           f"YouTube channel `{channel_url}` will now post new videos to {discord_channel.mention}."
       )
       if last_video_id:
           embed.add_field(name="Initial Video", value=f"Tracking from video ID: `{last_video_id}`", inline=False)
       await ctx.send(embed=embed)

   @youtube_feed_group.command(name="remove")
   @commands.has_permissions(manage_guild=True)
   @app_commands.describe(channel_url="The URL of the YouTube channel to stop tracking.")
   async def youtube_feed_remove(self, ctx: commands.Context, channel_url: str):
       """
       Disconnects the YouTube feed for a given channel URL.
       """
       await ctx.typing()

       if ctx.guild.id not in self.youtube_feeds_cache or channel_url not in self.youtube_feeds_cache[ctx.guild.id]:
           await ctx.send(embed=self._create_error_embed("Feed Not Found", "This YouTube channel feed is not active in this guild."))
           return

       async with self._get_db() as db:
           await db.execute(
               "DELETE FROM youtube_feeds WHERE guild_id = ? AND youtube_channel_url = ?",
               (ctx.guild.id, channel_url)
           )
           await db.execute( # Also delete associated roles
               "DELETE FROM youtube_roles WHERE guild_id = ? AND youtube_channel_url = ?",
               (ctx.guild.id, channel_url)
           )
           await db.commit()

       # Update cache
       if ctx.guild.id in self.youtube_feeds_cache and channel_url in self.youtube_feeds_cache[ctx.guild.id]:
           del self.youtube_feeds_cache[ctx.guild.id][channel_url]
       if ctx.guild.id in self.youtube_roles_cache and channel_url in self.youtube_roles_cache[ctx.guild.id]:
           del self.youtube_roles_cache[ctx.guild.id][channel_url]

       embed = self._create_success_embed(
           "Feed Removed",
           f"YouTube channel `{channel_url}` feed has been disconnected."
       )
       await ctx.send(embed=embed)

   @youtube_feed_group.command(name="list")
   @commands.has_permissions(manage_channels=True)
   async def youtube_feed_list(self, ctx: commands.Context):
       """
       Displays a list of all active YouTube update feeds configured for the server.
       """
       await ctx.typing()

       if ctx.guild.id not in self.youtube_feeds_cache or not self.youtube_feeds_cache[ctx.guild.id]:
           await ctx.send(embed=self._create_info_embed("No Active Feeds", "No YouTube channel feeds are configured for this server."))
           return

       embed = self._create_embed("🔔 Active YouTube Feeds", color=discord.Color.red())
       for channel_url, feed_data in self.youtube_feeds_cache[ctx.guild.id].items():
           discord_channel = ctx.guild.get_channel(feed_data["discord_channel_id"])
           roles_to_ping = self.youtube_roles_cache.get(ctx.guild.id, {}).get(channel_url, set())
           role_mentions = ", ".join([ctx.guild.get_role(r_id).mention for r_id in roles_to_ping if ctx.guild.get_role(r_id)]) if roles_to_ping else "None"
           
           embed.add_field(
               name=f"Channel: {channel_url}",
               value=(
                   f"Notifications to: {discord_channel.mention if discord_channel else 'Unknown Channel'}\n"
                   f"Last Video ID: `{feed_data['last_video_id'] or 'N/A'}`\n"
                   f"Roles to Ping: {role_mentions}"
               ),
               inline=False
           )
       await ctx.send(embed=embed)

   @youtube_feed_group.command(name="test")
   @commands.has_permissions(manage_guild=True)
   @app_commands.describe(channel_url="The URL of the YouTube channel to test.")
   async def youtube_feed_test(self, ctx: commands.Context, channel_url: str):
       """
       Triggers a mock upload notification to the designated Discord logging channel to test appearance and permissions.
       """
       await ctx.typing()

       if ctx.guild.id not in self.youtube_feeds_cache or channel_url not in self.youtube_feeds_cache[ctx.guild.id]:
           await ctx.send(embed=self._create_error_embed("Feed Not Found", "This YouTube channel feed is not active in this guild."))
           return

       feed_data = self.youtube_feeds_cache[ctx.guild.id][channel_url]
       discord_channel = ctx.guild.get_channel(feed_data["discord_channel_id"])

       if not discord_channel:
           await ctx.send(embed=self._create_error_embed("Channel Not Found", "The configured Discord channel for this feed no longer exists."))
           return

       # Fetch some video data for the mock
       latest_video_data = await self._fetch_api("/youtube/search", {"q": channel_url, "order": "newest", "count": 1})
       results = self._get_results(latest_video_data)
       if not results:
           video_title = "Mock Video Title"
           video_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ" # Rickroll for fun
           thumbnail_url = "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
       else:
           video_title = results[0]["title"]
           video_url = results[0]["url"]
           thumbnail_url = results[0]["thumbnail"]

       roles_to_ping = self.youtube_roles_cache.get(ctx.guild.id, {}).get(channel_url, set())
       role_mentions = " ".join([ctx.guild.get_role(r_id).mention for r_id in roles_to_ping if ctx.guild.get_role(r_id)])

       notification_embed = self._create_embed(f"🔔 New Video from {channel_url}", description=f"**{video_title}**", color=discord.Color.red())
       notification_embed.set_image(url=thumbnail_url)
       notification_embed.add_field(name="Watch Now", value=f"Click Here", inline=False)

       try:
           await discord_channel.send(content=role_mentions, embed=notification_embed)
           await ctx.send(embed=self._create_success_embed("Test Notification Sent", f"A mock notification was sent to {discord_channel.mention}."))
       except discord.Forbidden:
           await ctx.send(embed=self._create_error_embed("Permission Error", f"I do not have permission to send messages in {discord_channel.mention}."))
       except Exception as e:
           await ctx.send(embed=self._create_error_embed("Test Failed", f"An error occurred: {e}"))

   # ========================= YOUTUBE ROLE SUBGROUP =========================

   @youtube_group.group(name="role")
   @commands.has_permissions(manage_roles=True)
   @commands.guild_only()
   async def youtube_role_group(self, ctx: commands.Context):
       """
       Manage roles to be pinged for YouTube feed notifications.
       """
       if ctx.invoked_subcommand is None:
           embed = self._create_info_embed(
               "🏷️ YouTube Role Management",
               "Configure which roles get pinged for new video notifications."
           )
           embed.add_field(name="Commands", value=(
               "`yt role add <channel_url> <role>`: Add a role to ping\n"
               "`yt role remove <channel_url> <role>`: Remove a role from ping\n"
               "`yt role list <channel_url>`: List roles for a specific feed"
           ), inline=False)
           await ctx.send(embed=embed)

   @youtube_role_group.command(name="add")
   @commands.has_permissions(manage_guild=True)
   @app_commands.describe(channel_url="The URL of the YouTube channel.", role="The role to ping.")
   async def youtube_role_add(self, ctx: commands.Context, channel_url: str, role: discord.Role):
       """
       Adds a role to be pinged when the designated YouTube channel uploads.
       """
       await ctx.typing()

       if ctx.guild.id not in self.youtube_feeds_cache or channel_url not in self.youtube_feeds_cache[ctx.guild.id]:
           await ctx.send(embed=self._create_error_embed("Feed Not Found", "This YouTube channel feed is not active in this guild. Add it first."))
           return

       if ctx.guild.id not in self.youtube_roles_cache:
           self.youtube_roles_cache[ctx.guild.id] = {}
       if channel_url not in self.youtube_roles_cache[ctx.guild.id]:
           self.youtube_roles_cache[ctx.guild.id][channel_url] = set()

       if role.id in self.youtube_roles_cache[ctx.guild.id][channel_url]:
           await ctx.send(embed=self._create_error_embed("Role Already Added", f"{role.mention} is already configured to be pinged for `{channel_url}`."))
           return

       async with self._get_db() as db:
           await db.execute(
               "INSERT INTO youtube_roles (guild_id, youtube_channel_url, role_id) VALUES (?, ?, ?)",
               (ctx.guild.id, channel_url, role.id)
           )
           await db.commit()

       self.youtube_roles_cache[ctx.guild.id][channel_url].add(role.id)

       embed = self._create_success_embed(
           "Role Added",
           f"{role.mention} will now be pinged for new videos from `{channel_url}`."
       )
       await ctx.send(embed=embed)

   @youtube_role_group.command(name="remove")
   @commands.has_permissions(manage_guild=True)
   @app_commands.describe(channel_url="The URL of the YouTube channel.", role="The role to remove.")
   async def youtube_role_remove(self, ctx: commands.Context, channel_url: str, role: discord.Role):
       """
       Removes a role from the feed ping configuration.
       """
       await ctx.typing()

       if ctx.guild.id not in self.youtube_roles_cache or channel_url not in self.youtube_roles_cache[ctx.guild.id] or role.id not in self.youtube_roles_cache[ctx.guild.id][channel_url]:
           await ctx.send(embed=self._create_error_embed("Role Not Found", f"{role.mention} is not configured to be pinged for `{channel_url}`."))
           return

       async with self._get_db() as db:
           await db.execute(
               "DELETE FROM youtube_roles WHERE guild_id = ? AND youtube_channel_url = ? AND role_id = ?",
               (ctx.guild.id, channel_url, role.id)
           )
           await db.commit()

       self.youtube_roles_cache[ctx.guild.id][channel_url].discard(role.id)
       if not self.youtube_roles_cache[ctx.guild.id][channel_url]: # Clean up empty sets
           del self.youtube_roles_cache[ctx.guild.id][channel_url]
           if not self.youtube_roles_cache[ctx.guild.id]:
               del self.youtube_roles_cache[ctx.guild.id]

       embed = self._create_success_embed(
           "Role Removed",
           f"{role.mention} will no longer be pinged for new videos from `{channel_url}`."
       )
       await ctx.send(embed=embed)

   @youtube_role_group.command(name="list")
   @commands.has_permissions(manage_roles=True)
   @app_commands.describe(channel_url="The URL of the YouTube channel.")
   async def youtube_role_list(self, ctx: commands.Context, channel_url: str):
       """
       Displays roles set to ping for a given feed.
       """
       await ctx.typing()

       if ctx.guild.id not in self.youtube_feeds_cache or channel_url not in self.youtube_feeds_cache[ctx.guild.id]:
           await ctx.send(embed=self._create_error_embed("Feed Not Found", "This YouTube channel feed is not active in this guild."))
           return

       roles_to_ping = self.youtube_roles_cache.get(ctx.guild.id, {}).get(channel_url, set())

       if not roles_to_ping:
           await ctx.send(embed=self._create_info_embed("No Roles Configured", f"No roles are configured to be pinged for `{channel_url}`."))
           return

       role_mentions = []
       for r_id in roles_to_ping:
           role = ctx.guild.get_role(r_id)
           if role:
               role_mentions.append(role.mention)
           else:
               role_mentions.append(f"Unknown Role (`{r_id}`)")

       embed = self._create_embed(
           f"🏷️ Roles for `{channel_url}`",
           description="\n".join(role_mentions),
           color=discord.Color.red()
       )
       await ctx.send(embed=embed)

   # ========================= SOUNDCLOUD COMMANDS (OPTIONAL) =========================

   @commands.hybrid_group(name="soundcloud", aliases=["sc"], invoke_without_command=True)
   @commands.guild_only()
   async def soundcloud_group(self, ctx: commands.Context):
       """
       Displays an elegant help menu detailing all available SoundCloud utilities.
       """
       embed = self._create_info_embed(
           "☁️ VOTOX SoundCloud Utilities",
           "Search for tracks and download audio from SoundCloud!"
       )
       embed.add_field(name="🔍 Search", value="`sc search <query>`: Search for SoundCloud tracks", inline=False)
       embed.add_field(name="⬇️ Download", value="`sc download <url>`: Download SoundCloud track (Catbox link)", inline=False)
       embed.set_footer(text=f"Use {ctx.clean_prefix}soundcloud <command> for more details.")
       await ctx.send(embed=embed)

   @soundcloud_group.command(name="search")
   @app_commands.describe(query="The search query for SoundCloud tracks.")
   async def soundcloud_search(self, ctx: commands.Context, *, query: str):
       """
       Searches SoundCloud and returns track results.
       """
       await ctx.typing()
       data = await self._fetch_api("/soundcloud/search", {"q": query})
       
       results = self._get_results(data)

       if data is None:
           await ctx.send(embed=self._create_error_embed("Search Failed", "Could not fetch SoundCloud search results from the API."))
           return
       if not results:
           await ctx.send(embed=self._create_info_embed("No Results", f"No SoundCloud tracks found for '{query}'."))
           return

       embed = self._create_embed(f"🔍 SoundCloud Search Results for '{query}'", color=discord.Color.orange())
       for i, track in enumerate(results[:5]):
           title = track.get("title", "N/A")
           artist = track.get("artist", "N/A")
           url = track.get("url", "#")
           embed.add_field(
               name=f"{i+1}. {title}",
               value=f"Artist: {artist}\nListen Here",
               inline=False
           )
       await ctx.send(embed=embed)

   @soundcloud_group.command(name="download")
   @app_commands.describe(url="The URL of the SoundCloud track to download.")
   async def soundcloud_download(self, ctx: commands.Context, url: str):
       """
       Downloads a SoundCloud track and provides a Catbox mirror URL.
       """
       await ctx.typing()
       data = await self._fetch_api("/soundcloud/download/audio", {"url": url, "catbox": True})

       if not data or not data.get("url"):
           await ctx.send(embed=self._create_error_embed("Download Failed", "Could not generate SoundCloud download link. Check the URL."))
           return

       embed = self._create_success_embed("⬇️ SoundCloud Track Download", f"Click the button below to download your track from Catbox!")
       embed.add_field(name="Track Title", value=data.get("title", "N/A"), inline=False)
       embed.add_field(name="Artist", value=data.get("artist", "N/A"), inline=True)
       embed.add_field(name="Play Count", value=f"{int(data['play_count']):,}" if data.get("play_count") else "N/A", inline=True)
       embed.set_thumbnail(url=data.get("thumbnail", discord.Embed.Empty))

       view = discord.ui.View()
       view.add_item(discord.ui.Button(label="Download Track", url=data["url"], style=discord.ButtonStyle.link))
       await ctx.send(embed=embed, view=view)

   # ========================= BACKGROUND TASKS =========================

   @tasks.loop(minutes=10)
   async def check_youtube_feeds(self):
       """
       Background task to iterate through all registered YouTube channel feeds,
       check for new videos, and broadcast notifications.
       """
       await self.bot.wait_until_ready()
       if not self.youtube_feeds_cache:
           return

       logger.info("Checking YouTube feeds for new videos...")

       for guild_id, feeds_in_guild in list(self.youtube_feeds_cache.items()):
           guild = self.bot.get_guild(guild_id)
           if not guild:
               logger.warning(f"Guild {guild_id} not found, removing its YouTube feeds from cache.")
               del self.youtube_feeds_cache[guild_id]
               async with self._get_db() as db:
                   await db.execute("DELETE FROM youtube_feeds WHERE guild_id = ?", (guild_id,))
                   await db.execute("DELETE FROM youtube_roles WHERE guild_id = ?", (guild_id,))
                   await db.commit()
               continue

           for channel_url, feed_data in list(feeds_in_guild.items()):
               discord_channel_id = feed_data["discord_channel_id"]
               last_video_id = feed_data["last_video_id"]

               discord_channel = guild.get_channel(discord_channel_id)
               if not discord_channel:
                   logger.warning(f"Discord channel {discord_channel_id} not found for feed {channel_url} in guild {guild_id}. Removing feed.")
                   del self.youtube_feeds_cache[guild_id][channel_url]
                   async with self._get_db() as db:
                       await db.execute("DELETE FROM youtube_feeds WHERE guild_id = ? AND youtube_channel_url = ?", (guild_id, channel_url))
                       await db.execute("DELETE FROM youtube_roles WHERE guild_id = ? AND youtube_channel_url = ?", (guild_id, channel_url))
                       await db.commit()
                   continue

               try:
                   latest_video_data = await self._fetch_api("/youtube/search", {"q": channel_url, "order": "newest", "count": 1})
                   results = self._get_results(latest_video_data)

                   if results:
                       new_video = results[0]
                       new_video_id = new_video["id"]

                       if new_video_id and new_video_id != last_video_id:
                           logger.info(f"New video detected for {channel_url}: {new_video['title']} ({new_video_id})")

                           # Update last_video_id in DB and cache
                           async with self._get_db() as db:
                               await db.execute(
                                   "UPDATE youtube_feeds SET last_video_id = ? WHERE guild_id = ? AND youtube_channel_url = ?",
                                   (new_video_id, guild_id, channel_url)
                               )
                               await db.commit()
                           self.youtube_feeds_cache[guild_id][channel_url]["last_video_id"] = new_video_id

                           # Prepare notification
                           notification_embed = self._create_embed(f"🔔 New Video from {new_video.get('channel', 'N/A')}", description=f"**{new_video.get('title', 'N/A')}**", color=discord.Color.red())
                           notification_embed.set_image(url=new_video.get("thumbnail", discord.Embed.Empty))
                           notification_embed.add_field(name="Watch Now", value=f"[Watch Video]({new_video.get('url', 'N/A')})", inline=False)

                           roles_to_ping = self.youtube_roles_cache.get(guild_id, {}).get(channel_url, set())
                           role_mentions = " ".join([guild.get_role(r_id).mention for r_id in roles_to_ping if guild.get_role(r_id)])

                           try:
                               await discord_channel.send(content=role_mentions, embed=notification_embed)
                               logger.info(f"Sent notification for new video {new_video_id} to channel {discord_channel.id} in guild {guild_id}.")
                           except discord.Forbidden:
                               logger.warning(f"Bot lacks permissions to send notification in {discord_channel.name} ({guild.name}).")
                           except Exception as e:
                               logger.error(f"Error sending notification for new video {new_video_id}: {e}")
                       # else:
                           # logger.debug(f"No new video for {channel_url} or last_video_id is the same.")
                   # else:
                       # logger.warning(f"Could not fetch latest video for {channel_url} during feed check.")

               except Exception as e:
                   logger.error(f"Error checking YouTube feed for {channel_url} in guild {guild_id}: {e}")

   @check_youtube_feeds.before_loop
   async def before_check_youtube_feeds(self):
       """Waits until the bot is ready before starting the loop."""
       await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
   """Loads the Social cog into the bot."""
   await bot.add_cog(Social(bot))