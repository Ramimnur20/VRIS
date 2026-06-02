import discord
from discord import app_commands
from discord.ext import commands
import random
import aiohttp
import aiosqlite
from pathlib import Path
try:
    import orjson
    class json:
        @staticmethod
        def dumps(obj, **kwargs):
            return orjson.dumps(obj).decode('utf-8')
        @staticmethod
        def loads(s, **kwargs):
            return orjson.loads(s)
except ImportError:
    import json
from typing import Optional
import io
import base64
import hashlib
import asyncio
import os
import tempfile
import re
from urllib.parse import quote, unquote
import urllib.request
import logging
logger = logging.getLogger(__name__)

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageOps
from ddgs import DDGS

class Fun(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        self.eightball_responses = [
            "it is certain",
            "it is decidedly so",
            "without a doubt",
            "yes definitely",
            "you may rely on it",
            "as i see it, yes",
            "most likely",
            "outlook good",
            "yes",
            "signs point to yes",
            "reply hazy, try again",
            "ask again later",
            "better not tell you now",
            "cannot predict now",
            "concentrate and ask again",
            "don't count on it",
            "my reply is no",
            "my sources say no",
            "outlook not so good",
            "very doubtful"
        ]

    def _get_db(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.db_path)

    def _create_embed(self, title: str, description: str = None, color: discord.Color = None):
        embed = discord.Embed(
            title=title,
            description=description,
            color=color or self.bot.embed_color
        )
        embed.set_footer(text="VOTOX Fun System")
        return embed

    async def send_error(self, ctx, message: str, ephemeral: bool = True):
        embed = discord.Embed(title="❌ Error", description=message, color=discord.Color.red())
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message(embed=embed, ephemeral=ephemeral)
        else:
            await ctx.send(embed=embed, delete_after=10 if ephemeral else None)

    async def send_success(self, ctx, message: str, ephemeral: bool = True):
        embed = discord.Embed(title="✅ Success", description=message, color=discord.Color.green())
        if isinstance(ctx, discord.Interaction):
            await ctx.response.send_message(embed=embed, ephemeral=ephemeral)
        else:
            await ctx.send(embed=embed, delete_after=10 if ephemeral else None)

    def get_emoji_codepoint(self, emoji: str) -> str:
        codepoints = []
        for char in emoji:
            code = ord(char)
            if code in (0xFE0F, 0x200D):
                continue
            codepoints.append(f'{code:x}')
        return '-'.join(codepoints)

    def fetch_twemoji(self, emoji: str) -> Image.Image | None:
        try:
            codepoint = self.get_emoji_codepoint(emoji)
            url = f"https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/72x72/{codepoint}.png"

            with urllib.request.urlopen(url, timeout=5) as response:
                emoji_data = response.read()

            img = Image.open(io.BytesIO(emoji_data))
            if img.mode != 'RGBA':
                img = img.convert('RGBA')
            return img
        except Exception as e:
            logger.debug(f"Failed to fetch Twemoji for {emoji}: {e}")
            return None

    def render_text_with_emojis(self, text: str, font, emoji_size: int, max_width: int) -> Image.Image:
        import re

        emoji_pattern = re.compile(
            r'[\U0001F600-\U0001F64F]|'
            r'[\U0001F300-\U0001F5FF]|'
            r'[\U0001F680-\U0001F6FF]|'
            r'[\U0001F1E0-\U0001F1FF]|'
            r'[\U00002600-\U000027BF]|'
            r'[\U0001F900-\U0001F9FF]|'
            r'[\U0001FA00-\U0001FA6F]|'
            r'[\U0001FA70-\U0001FAFF]|'
            r'[\U00002702-\U000027B0]'
        )

        segments = []
        last_end = 0
        for match in emoji_pattern.finditer(text):
            if match.start() > last_end:
                segments.append(('text', text[last_end:match.start()]))
            segments.append(('emoji', match.group()))
            last_end = match.end()
        if last_end < len(text):
            segments.append(('text', text[last_end:]))

        temp_img = Image.new('RGBA', (1, 1))
        temp_draw = ImageDraw.Draw(temp_img)

        x_offset = 0
        max_height = emoji_size

        for seg_type, content in segments:
            if seg_type == 'text':
                bbox = temp_draw.textbbox((0, 0), content, font=font)
                x_offset += bbox[2] - bbox[0]
                max_height = max(max_height, bbox[3] - bbox[1])
            else:
                x_offset += emoji_size + 2

        final_img = Image.new('RGBA', (min(x_offset + 20, max_width), max_height + 20), (255, 255, 255, 0))
        draw = ImageDraw.Draw(final_img)

        x_pos = 10
        y_pos = 10

        for seg_type, content in segments:
            if seg_type == 'text':
                draw.text((x_pos, y_pos), content, font=font, fill=(0, 0, 0, 255))
                bbox = draw.textbbox((x_pos, y_pos), content, font=font)
                x_pos += bbox[2] - bbox[0]
            else:
                emoji_img = self.fetch_twemoji(content)
                if emoji_img:
                    emoji_img = emoji_img.resize((emoji_size, emoji_size), Image.Resampling.LANCZOS)
                    final_img.paste(emoji_img, (x_pos, y_pos), emoji_img)
                x_pos += emoji_size + 2

        return final_img

    async def cog_load(self):
        async with self._get_db() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS image_search_cache (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    query TEXT NOT NULL,
                    image_data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            await conn.execute('''
                CREATE INDEX IF NOT EXISTS idx_image_search_user_query 
                ON image_search_cache(user_id, query)
            ''')
            await conn.commit()

    async def question_autocomplete(self, interaction: discord.Interaction, current: str):
        choices = [
            app_commands.Choice(name="Will it rain today?", value="Will it rain today?"),
            app_commands.Choice(name="Should I eat pizza?", value="Should I eat pizza?"),
            app_commands.Choice(name="Will I pass my test?", value="Will I pass my test?"),
            app_commands.Choice(name="Is today a good day?", value="Is today a good day?"),
            app_commands.Choice(name="Will I be successful?", value="Will I be successful?"),
            app_commands.Choice(name="Should I go out tonight?", value="Should I go out tonight?"),
            app_commands.Choice(name="Is it worth the risk?", value="Is it worth the risk?"),
            app_commands.Choice(name="Will my team win?", value="Will my team win?")
        ]

        if current:
            filtered_choices = [choice for choice in choices if current.lower() in choice.name.lower() or current.lower() in choice.value.lower()]
            return filtered_choices[:25]
        return choices[:25]

    async def dice_sides_autocomplete(self, interaction: discord.Interaction, current: str):
        choices = [
            app_commands.Choice(name="6 sided (standard)", value=6),
            app_commands.Choice(name="20 sided (D&D)", value=20),
            app_commands.Choice(name="12 sided", value=12),
            app_commands.Choice(name="10 sided", value=10),
            app_commands.Choice(name="8 sided", value=8),
            app_commands.Choice(name="4 sided", value=4),
            app_commands.Choice(name="100 sided", value=100),
            app_commands.Choice(name="3 sided", value=3),
            app_commands.Choice(name="2 sided (coin)", value=2)
        ]

        if current:
            filtered_choices = []
            for choice in choices:
                if current.lower() in choice.name.lower():
                    filtered_choices.append(choice)
                elif current.isdigit() and str(choice.value).startswith(current):
                    filtered_choices.append(choice)
            return filtered_choices[:25]
        return choices[:25]

    async def dice_count_autocomplete(self, interaction: discord.Interaction, current: str):
        choices = [
            app_commands.Choice(name="1 die", value=1),
            app_commands.Choice(name="2 dice", value=2),
            app_commands.Choice(name="3 dice", value=3),
            app_commands.Choice(name="4 dice", value=4),
            app_commands.Choice(name="5 dice", value=5),
            app_commands.Choice(name="6 dice", value=6),
            app_commands.Choice(name="7 dice", value=7),
            app_commands.Choice(name="8 dice", value=8),
            app_commands.Choice(name="9 dice", value=9),
            app_commands.Choice(name="10 dice", value=10)
        ]

        if current:
            filtered_choices = []
            for choice in choices:
                if current.lower() in choice.name.lower():
                    filtered_choices.append(choice)
                elif current.isdigit() and str(choice.value).startswith(current):
                    filtered_choices.append(choice)
            return filtered_choices[:25]
        return choices[:25]

    async def rps_choice_autocomplete(self, interaction: discord.Interaction, current: str):
        choices = [
            app_commands.Choice(name="🪨 rock", value="rock"),
            app_commands.Choice(name="📄 paper", value="paper"),
            app_commands.Choice(name="✂️ scissors", value="scissors")
        ]

        if current:
            filtered_choices = [choice for choice in choices if current.lower() in choice.name.lower() or current.lower() in choice.value.lower()]
            return filtered_choices[:25]
        return choices[:25]

    async def generate_roast(self, target_name: str) -> str:
        try:
            api_key = self.bot.config.get("groq_api_key")

            if not api_key:
                return "ERROR:ai is not configured"

            prompt = f"""Generate a packgod-style roast similar to this example but with different words and references:

"SHUT YO SKIN TONE CHICKEN BONE GOOGLE CHROME NO HOME FLIP PHONE DISOWNED ICE CREAM CONE GARDEN GNOME EXTRA CHROMOSOME METRONOME DIMMADOME GENOME FULL BLOWN MONOCHROME STUDENT LOAN INDIANA JONES OVERGROWN FLINTSTONE X AND Y HORMONE FRIEND ZONE SYLVESTER STALLONE SIERRA LEONE AUTOZONE PROFESSIONALLY SEEN SILVER PATRONE"

Create a similar roast with:
- ALL CAPS format
- Same rapid-fire style
- Random object/reference combinations
- Rhyming words when possible
- Keep it silly and creative, not actually offensive
- Start with "SHUT YO"
- Use creative ending
- Make it about the same length
- Include 💀 and 🔥 emojis where appropriate or other emojis!

Generate ONE unique variation in ALL CAPS:"""

            from groq import Groq
            client = Groq(api_key=api_key)

            completion = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a creative roast generator that creates funny, silly roasts in the exact style of packgod. Generate variations that follow the same pattern and rhythm but use different words and references. Keep them silly and creative, not actually offensive. - generate the roast ONLY ; no additional text"
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=1,
                max_completion_tokens=200,
                top_p=1,
                stream=False,
                stop=None
            )

            if hasattr(completion, 'choices') and completion.choices:
                roast = completion.choices[0].message.content.strip() if completion.choices[0].message.content else ""
            else:
                return "ERROR:ai returned an invalid response"

            if not roast:
                return "ERROR:ai returned an empty response"

            roast = roast.replace('"', '').strip()

            if len(roast) < 10:
                return "ERROR:ai returned a very short response"

            return roast

        except Exception as e:
            error_msg = str(e)
            if 'api_key' in error_msg.lower():
                return "ERROR:invalid api key configuration"
            elif 'rate limit' in error_msg.lower():
                return "ERROR:api rate limit exceeded. please try again later."
            elif 'connection' in error_msg.lower():
                return "ERROR:connection to api failed. the service may be down."
            return f"ERROR:roast generation failed: {error_msg[:50]}"

    async def generate_8ball_response(self, question: str) -> str:
        try:
            api_key = self.bot.config.get("groq_api_key")

            if not api_key:
                return random.choice(self.eightball_responses)

            from groq import Groq
            client = Groq(api_key=api_key)

            prompt = f"""You are a mystical magic 8ball. Someone asked: "{question}"

Respond with a short, mystical answer (10 words or less) in the style of a magic 8ball. Be creative, slightly mysterious, and vary between positive, negative, and neutral responses. Don't just say yes/no - be more interesting!

Examples of good responses:
- "the stars align in your favor"
- "outlook cloudy, try again later"
- "absolutely, without a shadow of doubt"
- "the spirits say no"
- "perhaps, if the moon wills it"

Generate ONE creative magic 8ball response:"""

            completion = client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {
                        "role": "system",
                        "content": "You are a mystical magic 8ball oracle. Provide short, creative, and varied responses. Be mysterious and fun. Response ONLY with the answer, no quotes or extra text."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=1.2,
                max_completion_tokens=50,
                top_p=1,
                stream=False,
                stop=None
            )

            if hasattr(completion, 'choices') and completion.choices:
                response = completion.choices[0].message.content.strip() if completion.choices[0].message.content else ""
            else:
                return random.choice(self.eightball_responses)

            if not response or len(response) < 3:
                return random.choice(self.eightball_responses)

            response = response.replace('"', '').replace("'", '').strip()

            if len(response) > 100:
                response = response[:97] + "..."

            return response

        except Exception as e:
            return random.choice(self.eightball_responses)

    @commands.hybrid_group(name="fun", description="play games like magic 8ball, dice, and coin flip", invoke_without_command=True)
    async def fun_group(self, ctx):
        await ctx.send_help(ctx.command)

    @fun_group.command(name="8ball", description="ask the magic 8ball a question")
    @app_commands.describe(question="Your yes/no question for the magic 8ball")
    @app_commands.autocomplete(question=question_autocomplete)
    async def fun_8ball(self, ctx, question: Optional[str] = None):
        if not question:
            return await self.send_error(ctx, "You must provide a question.")

        if len(question) > 200:
            await self.send_error(ctx, "Question too long (max 200 characters)")
            return

        async with ctx.typing():
            response = await self.generate_8ball_response(question)

        view = discord.ui.LayoutView()
        view.add_item(discord.ui.Container(
            discord.ui.TextDisplay(content="**✨ ai magic 8ball**"),
            discord.ui.TextDisplay(content=f"**question:** {question}"),
            discord.ui.TextDisplay(content=f"**answer:** 🎱 {response}"),
            discord.ui.TextDisplay(content=f"**asked by:** {ctx.author.name}"),
            accent_color=discord.Color(0x7B68EE)
        ))
        await ctx.send(view=view)

    @commands.hybrid_command(name="8ball", description="ask the magic 8ball a question", aliases=["8b", "magic8ball", "eightball", "ball", "magic"])
    async def eightball(self, ctx, *, question: Optional[str] = None):
        if not question:
            return await self.send_error(ctx, "You must provide a question.")

        if len(question) > 200:
            await self.send_error(ctx, "Question too long (max 200 characters)")
            return

        async with ctx.typing():
            response = await self.generate_8ball_response(question)

        view = discord.ui.LayoutView()
        view.add_item(discord.ui.Container(
            discord.ui.TextDisplay(content="**✨ ai magic 8ball**"),
            discord.ui.TextDisplay(content=f"**question:** {question}"),
            discord.ui.TextDisplay(content=f"**answer:** 🎱 {response}"),
            discord.ui.TextDisplay(content=f"**asked by:** {ctx.author.name}"),
            accent_color=discord.Color(0x7B68EE)
        ))
        await ctx.send(view=view)

    @fun_group.command(name="dice", description="roll one or multiple dice with customizable number of sides")
    @app_commands.describe(
        sides="Number of sides on the dice (2-100)",
        count="Number of dice to roll (1-10)"
    )
    @app_commands.autocomplete(sides=dice_sides_autocomplete, count=dice_count_autocomplete)
    async def fun_dice(self, ctx, sides: int = 6, count: int = 1):
        if sides < 2 or sides > 100:
            await self.send_error(ctx, "Dice must have between 2 and 100 sides")
            return

        if count < 1 or count > 10:
            await self.send_error(ctx, "Can only roll between 1 and 10 dice")
            return

        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)

        if count == 1:
            roll_line = f"🎲 rolled a **d{sides}**: {rolls[0]}"
        else:
            rolls_str = " + ".join(str(roll) for roll in rolls)
            roll_line = f"🎲 rolled **{count}d{sides}**: {rolls_str}\ntotal: **{total}**"
        username = ctx.author.name
        content = f"# dice roll\n{roll_line}\nrolled by {username}\n-# VOTOX"
        class Dice(discord.ui.LayoutView):    
            container1 = discord.ui.Container(
                discord.ui.TextDisplay(content=content),
            )
        await ctx.send(view=Dice())

    @commands.hybrid_command(name="dice", description="roll one or more dice", aliases=["roll", "diceroll", "rolldie", "die"])
    async def dice(self, ctx, sides: int = 6, count: int = 1):
        if sides < 2 or sides > 100:
            await self.send_error(ctx, "Dice must have between 2 and 100 sides")
            return

        if count < 1 or count > 10:
            await self.send_error(ctx, "Can only roll between 1 and 10 dice")
            return

        rolls = [random.randint(1, sides) for _ in range(count)]
        total = sum(rolls)

        if count == 1:
            roll_line = f"🎲 rolled a **d{sides}**: {rolls[0]}"
        else:
            rolls_str = " + ".join(str(roll) for roll in rolls)
            roll_line = f"🎲 rolled **{count}d{sides}**: {rolls_str}\ntotal: **{total}**"
        username = ctx.author.name
        content = f"# dice roll\n{roll_line}\nrolled by {username}\n-# VOTOX"
        class Dice(discord.ui.LayoutView):    
            container1 = discord.ui.Container(
                discord.ui.TextDisplay(content=content),
            )
        await ctx.send(view=Dice())

    @fun_group.command(name="coinflip", description="flip a virtual coin to get heads or tails")
    async def fun_coinflip(self, ctx):
        result = random.choice(["heads", "tails"])
        emoji = "🪙" if result == "heads" else "🥉"

        view = discord.ui.LayoutView()
        view.add_item(discord.ui.Container(
            discord.ui.TextDisplay(content="**coin flip**"),
            discord.ui.TextDisplay(content=f"{emoji} **{result}**"),
            discord.ui.TextDisplay(content=f"**flipped by:** {ctx.author.name}"),
            accent_color=discord.Color(0xFFD700)
        ))
        await ctx.send(view=view)

    @commands.hybrid_command(name="coinflip", description="flip a coin to get heads or tails", aliases=["flip", "coin", "cf", "heads", "tails", "flipcoin"])
    async def coinflip(self, ctx):
        result = random.choice(["heads", "tails"])
        emoji = "🪙" if result == "heads" else "🥉"

        view = discord.ui.LayoutView()
        view.add_item(discord.ui.Container(
            discord.ui.TextDisplay(content="**coin flip**"),
            discord.ui.TextDisplay(content=f"{emoji} **{result}**"),
            discord.ui.TextDisplay(content=f"**flipped by:** {ctx.author.name}"),
            accent_color=discord.Color(0xFFD700)
        ))
        await ctx.send(view=view)

    @fun_group.command(name="dih", description="check dih size")
    @app_commands.describe(user="User to check (defaults to yourself)")
    async def fun_pp(self, ctx, user: Optional[discord.Member] = None):
        target_user = user if user is not None else ctx.author

        size = random.randint(0, 15)

        pp_visual = "8" + "=" * size + "D"

        embed = self._create_embed(title="dih size checker🥀🥀", color=discord.Color.from_rgb(255, 105, 180))
        embed.add_field(name=f"{target_user.name}'s pp", value=f"`{pp_visual}`", inline=False)
        embed.add_field(name="size", value=f"{size} inches", inline=False)
        embed.add_field(name="checked by", value=ctx.author.name, inline=False)

        await ctx.send(embed=embed)

    @fun_group.command(name="choose", description="let me choose from your options")
    @app_commands.describe(options="Options separated by commas (e.g., pizza, burger, tacos)")
    async def fun_choose(self, ctx, *, options: str):
        choice_list = [choice.strip() for choice in options.split(',')]

        if len(choice_list) < 2:
            await self.send_error(ctx, "Need at least 2 options separated by commas")
            return

        if len(choice_list) > 20:
            await self.send_error(ctx, "Too many options (max 20)")
            return

        chosen = random.choice(choice_list)

        embed = self._create_embed(title="choice made", description=f"i choose: **{chosen}**", color=discord.Color.green())
        embed.add_field(name="options", value=", ".join(choice_list), inline=False)
        embed.add_field(name="chosen for", value=ctx.author.name, inline=False)

        await ctx.send(embed=embed)

    @fun_group.command(name="rps", description="play rock paper scissors with the bot")
    @app_commands.describe(choice="Your choice: rock, paper, or scissors")
    @app_commands.autocomplete(choice=rps_choice_autocomplete)
    async def fun_rps(self, ctx, choice: str):
        choice = choice.lower().strip()
        valid_choices = ['rock', 'paper', 'scissors']

        if choice not in valid_choices:
            await self.send_error(ctx, "Choose rock, paper, or scissors")
            return

        bot_choice = random.choice(valid_choices)

        if choice == bot_choice:
            result = "tie"
            color = 0xFFFF00
        elif (choice == 'rock' and bot_choice == 'scissors') or \
             (choice == 'paper' and bot_choice == 'rock') or \
             (choice == 'scissors' and bot_choice == 'paper'):
            result = "you win"
            color = 0x00FF00
        else:
            result = "you lose"
            color = 0xFF0000

        emojis = {'rock': '🪨', 'paper': '📄', 'scissors': '✂️'}

        embed = self._create_embed(title="rock paper scissors", color=discord.Color(int(color)))
        embed.add_field(name="your choice", value=f"{emojis[choice]} {choice}", inline=True)
        embed.add_field(name="my choice", value=f"{emojis[bot_choice]} {bot_choice}", inline=True)
        embed.add_field(name="result", value=f"**{result}**", inline=False)
        embed.add_field(name="played by", value=ctx.author.name, inline=False)

        await ctx.send(embed=embed)

    @fun_group.command(name="humble", description="generate AI-powered packgod style roasts")
    @app_commands.describe(user="User to humble with an epic roast")
    async def fun_humble(self, ctx, user: Optional[discord.Member] = None):

        if ctx.message.reference and ctx.message.reference.message_id:
            try:
                replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                target_user = replied_message.author
            except:
                target_user = None
        else:
            target_user = user

        if not target_user:
            await self.send_error(ctx, "Provide a user or reply to a message.")
            return

        if target_user.bot:
            await self.send_error(ctx, "I don't humble bots, they have no feelings")
            return

        if target_user.id == ctx.author.id:
            await self.send_error(ctx, "You can't humble yourself, that's just sad")
            return

        async with ctx.typing():

            roast_text = await self.generate_roast(target_user.display_name)

        if roast_text.startswith("ERROR:"):
            error_message = roast_text.replace("ERROR:", "").strip()
            await self.send_error(ctx, f"Roast generation failed: {error_message}")
            return

        embed = self._create_embed(title="HUMBLED BY VOTOX!", color=discord.Color.from_rgb(255, 69, 0))
        embed.add_field(name="TARGET", value=target_user.mention, inline=False)
        embed.add_field(name="HUMBLE", value=roast_text, inline=False)
        embed.add_field(name="HUMBLED BY", value=ctx.author.name, inline=False)

        await ctx.send(embed=embed)

    @fun_group.command(name="caption", description="add caption text to images")
    @app_commands.describe(
        text="Caption text to add to the image",
        attachment="Image file to caption (or attach to message)"
    )
    async def fun_caption(self, ctx, text: str, attachment: Optional[discord.Attachment] = None):
        if not text:
            await self.send_error(ctx, "Text is required.")
            return

        if len(text) > 200:
            await self.send_error(ctx, "Caption text too long (max 200 characters)")
            return

        image_url = None

        if attachment and attachment.content_type and attachment.content_type.startswith('image/'):
            if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                image_url = attachment.url
            else:
                await self.send_error(ctx, "File must be a PNG/JPG/JPEG image")
                return
        elif ctx.message and ctx.message.attachments:
            for attachment in ctx.message.attachments:
                if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                    image_url = attachment.url
                    break

        if not image_url and ctx.message and ctx.message.reference and ctx.message.reference.message_id:
            try:
                replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if replied_message.attachments:
                    for attachment in replied_message.attachments:
                        if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):
                            image_url = attachment.url
                            break
                elif replied_message.embeds:
                    for embed in replied_message.embeds:
                        if embed.image:
                            image_url = embed.image.url
                            break
            except:
                pass

        if not image_url:
            await self.send_error(ctx, "Please attach an image or reply to a message with an image")
            return

        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(image_url) as response:
                        if response.status != 200:
                            await self.send_error(ctx, "Failed to download image")
                            return
                        image_data = await response.read()

                # Use external caption API (URL based)
                api_url = "http://193.122.157.22:4793/fun/caption"
                async with aiohttp.ClientSession() as session:
                    payload = {"url": image_url, "text": text}
                    async with session.post(api_url, json=payload) as resp:
                        if resp.status != 200:
                            await self.send_error(ctx, "Caption API failed")
                            return
                        data = await resp.json()
                        result_url = data.get("url")
                        if not result_url:
                            await send_error_view(ctx, "caption API returned no url", ephemeral=True)
                            await self.send_error(ctx, "caption API returned no url")
                            return

                        async with session.get(result_url) as img_resp:
                            if img_resp.status != 200:
                                await self.send_error(ctx, "Failed to download result image")
                                return
                            output_data = await img_resp.read()

                        ext = 'png'
                        if result_url.lower().endswith('.gif'):
                            ext = 'gif'
                        output_buffer = io.BytesIO(output_data)
                        output_buffer.seek(0)
                        filename = f"captioned.{ext}"
                        file = discord.File(output_buffer, filename=filename, spoiler=False)
                        embed = self._create_embed(title="image captioned", description=f"added caption: **{text}**", color=discord.Color.green())
                        embed.set_image(url=f"attachment://{filename}")
                        embed.add_field(name="captioned by", value=ctx.author.name, inline=False)
                        await ctx.send(embed=embed, file=file)
                        return
                    original_image = Image.open(io.BytesIO(image_data))
                    frames = []

                    try:
                        while True:
                            frame = original_image.copy()
                            if frame.mode != 'RGBA':
                                frame = frame.convert('RGBA')

                            font_size = max(16, min(48, frame.width // 20))
                            try:
                                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                            except:
                                font = ImageFont.load_default()

                            caption_img = self.render_text_with_emojis(text, font, font_size, frame.width)
                            caption_height = caption_img.height + 20
                            new_height = frame.height + caption_height

                            captioned_frame = Image.new('RGBA', (frame.width, int(new_height)), (255, 255, 255, 255))
                            captioned_frame.paste(caption_img, ((frame.width - caption_img.width) // 2, 10), caption_img)
                            captioned_frame.paste(frame, (0, int(caption_height)), frame if frame.mode == 'RGBA' else None)

                            frames.append(captioned_frame.convert('RGB'))
                            original_image.seek(original_image.tell() + 1)
                    except EOFError:
                        pass

                    output_buffer = io.BytesIO()
                    duration = original_image.info.get('duration', 100)
                    frames[0].save(output_buffer, format='GIF', save_all=True, append_images=frames[1:], duration=duration, loop=0)
                    output_buffer.seek(0)
                    filename = "captioned.gif"

                    try:
                        original_image.close()
                        del original_image
                        import gc
                        gc.collect()
                    except Exception:
                        pass

            except Exception as e:
                await self.send_error(ctx, f"Failed to add caption: {str(e)}")

    @fun_group.command(name="base64", description="encode or decode base64 text")
    @app_commands.describe(
        action="Choose 'encode' or 'decode'",
        text="Text to encode/decode"
    )
    async def fun_base64(self, ctx, action: str, text: str):

        if not action or action.lower() not in ["encode", "decode", "e", "d"]:
            await self.send_error(ctx, "Action must be 'encode' or 'decode'")
            return

        if not text:
            await self.send_error(ctx, "Please provide text to encode or decode")
            return

        action = action.lower()

        result = ""
        action_name = ""
        color = 0x00FF00

        try:
            if action in ["encode", "e"]:

                encoded_bytes = base64.b64encode(text.encode('utf-8'))
                result = encoded_bytes.decode('utf-8')
                action_name = "encoded"
                color = 0x00FF00

            elif action in ["decode", "d"]:

                try:
                    decoded_bytes = base64.b64decode(text)
                    result = decoded_bytes.decode('utf-8')
                    action_name = "decoded"
                    color = 0x0099FF
                except Exception:
                    await self.send_error(ctx, "Invalid base64 input - cannot decode")
                    return

            input_display = text[:100] + "..." if len(text) > 100 else text
            result_display = result
            username = ctx.author.name
            if len(result) > 1900:
                header = f"## Base64 {action_name.title()}!"
                body = f"result is too long to display ({len(result)} characters)\n**input length**: `{len(text)}`\n**output length**: `{len(result)}`"
            else:
                header = f"## Base64 {action_name.title()}!"
                body = f"**input**: `{input_display}`\n**result**: `{result_display}`"
            by_line = f"{action_name} by {username}"
            class Base64(discord.ui.LayoutView):    
                container1 = discord.ui.Container(
                    discord.ui.TextDisplay(content=f"{header}\n{body}\n{by_line}\n-# FishR"),
                    discord.ui.TextDisplay(content=f"{header}\n{body}\n{by_line}\n-# VOTOX"),
                )
            await ctx.send(view=Base64())
            if len(result) > 1900:
                return

        except Exception as e:
            await self.send_error(ctx, f"Failed to {action} text: {str(e)}")

    @fun_group.command(name="sha256", description="generate SHA256 hash of text")
    @app_commands.describe(text="Text to generate SHA256 hash for")
    async def fun_sha256(self, ctx, *, text: Optional[str] = None):

        if not text:
            await self.send_error(ctx, "Text is required.")
            return

        try:

            hash_object = hashlib.sha256(text.encode('utf-8'))
            hash_hex = hash_object.hexdigest()

            embed = self._create_embed(title="SHA-256 hash generated", color=discord.Color.from_rgb(255, 107, 107))
            input_display = text[:100] + "..." if len(text) > 100 else text
            embed.add_field(name="input", value=f"```{input_display}```", inline=False)

            embed.add_field(name="SHA-256 hash", value=f"```{hash_hex}```", inline=False)

            embed.add_field(name="input length", value=f"{len(text)} characters", inline=True)
            embed.add_field(name="hash length", value="64 characters", inline=True)
            embed.add_field(name="hashed by", value=ctx.author.name, inline=False)

            await ctx.send(embed=embed)

        except Exception as e:
            await self.send_error(ctx, f"Failed to generate hash: {str(e)}")

    async def check_automod_words(self, guild_id, message):
        import re

        try:
            async with self._get_db() as conn:
                async with conn.execute(
                    "SELECT blocked_words, word_filter FROM automod_settings WHERE guild_id = ?",
                    (guild_id,)
                ) as cursor:
                    result = await cursor.fetchone()

                if not result or not result[1]:
                    return False

                blocked_words = result[0]
                if not blocked_words:
                    return False

                words_list = [word.strip() for word in blocked_words.split(',') if word.strip()]

                message_lower = message.lower()

                for word in words_list:
                    if not word:
                        continue

                    if word.startswith('/') and word.endswith('/'):
                        pattern = word[1:-1]
                        try:
                            if re.search(pattern, message_lower, re.IGNORECASE):
                                return True
                        except re.error:
                            continue
                    else:

                        if word.lower() in message_lower:
                            return True

                return False
        except Exception:
            return False

    @fun_group.command(name="steal", description="steal emojis and stickers from messages")
    @app_commands.describe(
        message_id="ID of message containing emojis/stickers to steal",
        name="Custom name for the stolen emoji/sticker"
    )
    @commands.has_permissions(manage_expressions=True)
    async def fun_steal(self, ctx, message_id: Optional[str] = None, *, name: Optional[str] = None):

        target_message = None

        if ctx.message.reference and ctx.message.reference.message_id:
            try:
                target_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            except:
                pass
        elif message_id:
            try:
                target_message = await ctx.channel.fetch_message(int(message_id))
            except:
                await self.send_error(ctx, "Invalid message ID or message not found")
                return

        if not target_message:
            await self.send_error(ctx, "Provide a message ID or reply to a message.")
            return

        import re
        custom_emojis = []
        stickers = []

        emoji_pattern = r'<(a?):([^:]+):(\d+)>'
        emoji_matches = re.findall(emoji_pattern, target_message.content)

        for animated, emoji_name, emoji_id in emoji_matches:
            custom_emojis.append({
                'name': emoji_name,
                'id': int(emoji_id),
                'animated': bool(animated),
                'url': f"https://cdn.discordapp.com/emojis/{emoji_id}.{'gif' if animated else 'png'}"
            })

        if target_message.stickers:
            for sticker in target_message.stickers:
                if sticker.format != discord.StickerFormatType.lottie:
                    stickers.append({
                        'name': sticker.name,
                        'id': sticker.id,
                        'url': sticker.url,
                        'format': sticker.format
                    })

        if not custom_emojis and not stickers:
            await self.send_error(ctx, "No custom emojis or stickers found in that message")
            return

        view = StealView(ctx, custom_emojis, stickers, name, self.bot)

        embed = self._create_embed(title="emoji & sticker stealer", description=f"found {len(custom_emojis)} custom emoji{'s' if len(custom_emojis) != 1 else ''} and {len(stickers)} sticker{'s' if len(stickers) != 1 else ''}", color=discord.Color.from_rgb(255, 105, 180))

        if custom_emojis:
            emoji_list = []
            for emoji in custom_emojis[:5]:
                emoji_list.append(f"<{'a' if emoji['animated'] else ''}:{emoji['name']}:{emoji['id']}> `{emoji['name']}`")
            embed.add_field(name="custom emojis", value="\n".join(emoji_list), inline=False)
            if len(custom_emojis) > 5:
                embed.add_field(name="note", value=f"showing 5 of {len(custom_emojis)} emojis", inline=False)

        if stickers:
            sticker_list = []
            for sticker in stickers[:3]:
                format_name = "png" if sticker['format'] == discord.StickerFormatType.png else "apng"
                sticker_list.append(f"`{sticker['name']}` ({format_name})")
            embed.add_field(name="stickers", value="\n".join(sticker_list), inline=False)
            if len(stickers) > 3:
                embed.add_field(name="note", value=f"showing 3 of {len(stickers)} stickers", inline=False)

        await ctx.send(embed=embed, view=view)

    @fun_group.command(name="translate", description="translate text between languages")
    @app_commands.describe(
        target_language="Language to translate to (e.g., Spanish, French, Japanese)",
        text="Text to translate (or reply to a message)"
    )
    async def fun_translate(self, ctx, target_language: str, *, text: Optional[str] = None):

        if not text and ctx.message.reference:
            try:
                replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                text = replied_message.content
                if not text:
                    await self.send_error(ctx, "The replied message has no text to translate")
                    return
            except discord.NotFound:
                await self.send_error(ctx, "Couldn't find the replied message")
                return
        elif not text:
            return await self.send_error(ctx, "Text is required for translation.")

        if len(text) > 2000:
            await self.send_error(ctx, "Text too long (max 2000 characters)")
            return

        api_key = self.bot.config.get("groq_api_key")

        if not api_key:
            await self.send_error(ctx, "Translation service is not available (API key not configured)")
            return

        async with ctx.typing():
            try:
                from groq import Groq
                client = Groq(api_key=api_key)

                prompt = f"""Translate the following text to {target_language}. Only provide the translation, no additional text.

Text to translate: {text}

Translation:"""

                chat_completion = client.chat.completions.create(
                    model="llama-3.1-8b-instant",
                    messages=[
                        {
                            'role': 'system',
                            'content': f'You are a professional translator. Translate text accurately to {target_language}. Only return the translation without any additional commentary.'
                        },
                        {
                            'role': 'user',
                            'content': prompt
                        }
                    ],
                    max_tokens=1000,
                    temperature=0.1,
                    stream=False
                )

                translation = chat_completion.choices[0].message.content.strip() if chat_completion.choices[0].message.content else ""

                translation = translation.replace('"', '').replace('\n', ' ').strip()

                embed = self._create_embed(title="🌐 translation", color=discord.Color.blue())
                embed.add_field(name="original text", value=text[:1000] + ("..." if len(text) > 1000 else ""), inline=False)
                embed.add_field(name=f"translated to {target_language}", value=translation[:1000] + ("..." if len(translation) > 1000 else ""), inline=False)
                embed.add_field(name="translated by", value=ctx.author.name, inline=False)

                await ctx.send(embed=embed)

            except Exception as e:
                await self.send_error(ctx, f"Translation error: {str(e)}")

    @commands.hybrid_command(name="pp", description="check pp size", aliases=["dih"])
    async def pp(self, ctx, user: Optional[discord.Member] = None):
        await self.fun_pp(ctx, user)

    @commands.hybrid_command(name="dihr", description="fixed 67 inch result", aliases=["ppr"])
    async def dihr(self, ctx, user: Optional[discord.Member] = None):
        target_user = user if user is not None else ctx.author

        size = 67
        pp_visual = "8" + "=" * size + "D"

        embed = self._create_embed(title="dih size checker🥀🥀 (REAL)", color=discord.Color.from_rgb(255, 105, 180))
        embed.add_field(name=f"{target_user.name}'s pp", value=f"`{pp_visual}`", inline=False)
        embed.add_field(name="size", value=f"{size} inches (REAL)", inline=False)
        embed.add_field(name="checked by", value=ctx.author.name, inline=False)

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="choose", description="let me choose from your options", aliases=["pick", "select", "choice", "decide", "random"])
    async def choose(self, ctx, *, options: str):
        await self.fun_choose(ctx, options=options)

    @commands.hybrid_command(name="rps", description="play rock paper scissors with the bot", aliases=["rockpaperscissors", "rock", "paper", "scissors", "game"])
    async def rockpaperscissors(self, ctx, choice: str):
        await self.fun_rps(ctx, choice)

    @commands.hybrid_command(name="humble", description="get ai powered roasts and burns", aliases=["roast", "burn", "flame"])
    async def humble(self, ctx, user: Optional[discord.Member] = None):
        await self.fun_humble(ctx, user)

    @commands.hybrid_command(name="caption", description="add caption text to images", aliases=["cap", "addcaption"])
    async def caption(self, ctx, *, text: Optional[str] = None):
        await self.fun_caption(ctx, text if text else "", attachment=None)

    @commands.hybrid_command(name="base64", description="encode or decode base64 text", aliases=["b64", "encode", "decode"])
    async def base64_converter(self, ctx, action: Optional[str] = None, *, text: Optional[str] = None):
        await self.fun_base64(ctx, action, text=text)

    @commands.hybrid_command(name="aiclear", description="clear ai conversation memory for a user")
    async def ai_clear(self, ctx, user: Optional[discord.Member] = None):
        await self.fun_aiclear(ctx, user)
        await self.send_success(ctx, f"Conversation memory for {user or ctx.author} has been cleared.")

    @commands.hybrid_command(name="sha256", aliases=["hash", "sha", "checksum"], description="creates a special code from text to keep it safe")
    async def sha256_hash(self, ctx, *, text: Optional[str] = None):
        await self.fun_sha256(ctx, text=text)

    @commands.hybrid_command(name="translate", aliases=["trans", "tr", "translation"], description="changes text from one language to another language")
    async def translate(self, ctx, target_language: str, *, text: Optional[str] = None):
        await self.fun_translate(ctx, target_language, text=text)

    @fun_group.command(name="tts", description="convert text to speech and send as voice message")
    @app_commands.describe(text="Text to convert to speech")
    async def fun_tts(self, ctx, *, text: str = None):
        if not text:
            await self.send_error(ctx, "Provide text for TTS.")
            return

        if len(text) > 500:
            await self.send_error(ctx, "Text must be 500 characters or less")
            return

        await ctx.defer()

        try:
            api_key = self.bot.config.get("groq_api_key")

            if not api_key:
                await self.send_error(ctx, "AI is not configured")
                return

            import tempfile
            import aiohttp
            import os
            from pathlib import Path
            from groq import Groq

            client = Groq(api_key=api_key)

            ogg_file = tempfile.NamedTemporaryFile(delete=False, suffix='.ogg')
            ogg_file.close()
            speech_file_path = Path(ogg_file.name)

            response = await asyncio.to_thread(
                client.audio.speech.create,
                model="playai-tts",
                voice="Thunder-PlayAI",
                response_format="ogg",
                input=text
            )

            with open(speech_file_path, 'wb') as f:
                f.write(response.read())

            try:
                import base64

                upload_url = f"https://discord.com/api/v10/channels/{ctx.channel.id}/attachments"
                upload_headers = {
                    'Authorization': f'Bot {self.bot.http.token}',
                    'Content-Type': 'application/json'
                }

                upload_payload = {
                    "files": [{
                        "filename": "voice-message.ogg",
                        "file_size": os.path.getsize(ogg_file.name),
                        "id": "0"
                    }]
                }

                async with aiohttp.ClientSession() as discord_session:
                    async with discord_session.post(upload_url, headers=upload_headers, json=upload_payload) as upload_response:
                        if upload_response.status != 200:
                            raise Exception(f"upload url generation failed: {upload_response.status}")
                        upload_data = await upload_response.json()

                    attachment_upload_url = upload_data['attachments'][0]['upload_url']
                    uploaded_filename = upload_data['attachments'][0]['upload_filename']

                    with open(ogg_file.name, 'rb') as audio_file:
                        async with discord_session.put(attachment_upload_url, data=audio_file.read()) as put_response:
                            if put_response.status not in [200, 201]:
                                raise Exception(f"file upload failed: {put_response.status}")

                    waveform_data = base64.b64encode(b'\x00' * 64).decode('utf-8')

                    message_url = f"https://discord.com/api/v10/channels/{ctx.channel.id}/messages"
                    message_headers = {
                        'Authorization': f'Bot {self.bot.http.token}',
                        'Content-Type': 'application/json'
                    }
                    message_payload = {
                        "flags": 8192,
                        "attachments": [{
                            "id": "0",
                            "filename": "voice-message.ogg",
                            "uploaded_filename": uploaded_filename,
                            "duration_secs": 5.0,
                            "waveform": waveform_data
                        }]
                    }

                    async with discord_session.post(message_url, headers=message_headers, json=message_payload) as message_response:
                        if message_response.status not in [200, 201]:
                            response_text = await message_response.text()
                            raise Exception(f"message send failed: {message_response.status} - {response_text[:100]}")

                        voice_message_data = await message_response.json()
                        voice_message_id = voice_message_data.get('id')

                    if voice_message_id:
                        try:
                            voice_message = await ctx.channel.fetch_message(voice_message_id)

                            prompt_embed = self._create_embed(title="TTS PROMPT", description=text, color=discord.Color.blurple())
                            await voice_message.reply(embed=prompt_embed, mention_author=False)
                        except Exception as e:
                            pass

            finally:
                try:
                    os.unlink(ogg_file.name)
                except:
                    pass

        except Exception as e:
            await self.send_error(ctx, f"TTS failed: {str(e)}")

    @commands.hybrid_command(name="tts", description="convert text to speech", aliases=["texttospeech", "speak", "say"])
    async def tts_standalone(self, ctx, *, text: str = None):
        await self.fun_tts(ctx, text=text)

    @fun_group.command(name="urban", description="look up a term on Urban Dictionary")
    @app_commands.describe(term="Term to search on Urban Dictionary")
    async def fun_urban(self, ctx, *, term: str = None):
        if not term:
            await self.send_error(ctx, "Provide a term to search.")
            return

        if len(term) > 100:
            await self.send_error(ctx, "Search term too long (max 100 characters)")
            return

        async with ctx.typing():
            try:
                async with aiohttp.ClientSession() as session:
                    url = f"http://api.urbandictionary.com/v0/define?term={term}"
                    async with session.get(url) as response:
                        if response.status != 200:
                            await self.send_error(ctx, "Failed to fetch definition from Urban Dictionary")
                            return

                        data = await response.json()

                if not data.get('list'):
                    await self.send_error(ctx, f"No definition found for **{term}**")
                    return

                definitions = data['list']

                embed = create_urban_embed(definitions, 0, self.bot.embed_color)
                view = UrbanDictionaryView(definitions, ctx.author.id, self.bot)
                await ctx.send(embed=embed, view=view)

            except Exception as e:
                await self.send_error(ctx, f"Error looking up term: {str(e)}")

    @commands.hybrid_command(name="urban", aliases=["ud", "define", "dictionary"], description="look up a term on Urban Dictionary")
    async def urban_standalone(self, ctx, *, term: str = None):
        await self.fun_urban(ctx, term=term)

    @fun_group.command(name="image", description="search for images using DuckDuckGo (completely free)")
    @app_commands.describe(
        query="What to search for"
    )
    async def fun_image(self, ctx, query: str = None):
        if not query:
            await self.send_error(ctx, "Provide a search query.")
            return

        if len(query) > 100:
            await self.send_error(ctx, "Search query too long (max 100 characters)")
            return

        safesearch = "moderate"

        async with ctx.typing():
            try:
                import time
                start_time = time.time()

                async with self._get_db() as conn:
                    async with conn.execute(
                        'SELECT image_data FROM image_search_cache WHERE user_id = ? AND query = ? ORDER BY created_at DESC LIMIT 1',
                        (ctx.author.id, query)
                    ) as cursor:
                        cached = await cursor.fetchone()

                if cached:
                    results = json.loads(cached[0])
                else:
                    results = []
                    ddgs_instance = DDGS()
                    raw_results = list(ddgs_instance.images(
                        query=query,
                        max_results=100,
                        safesearch=safesearch
                    ))

                    results = [
                        r for r in raw_results
                        if (r.get('image') or r.get('thumbnail')) and
                        (r.get('image', '').startswith(('http://', 'https://')) or
                         r.get('thumbnail', '').startswith(('http://', 'https://'))) and
                        len(r.get('image', '')) < 512 and
                        len(r.get('thumbnail', '')) < 512
                    ]

                    if not results:
                        await self.send_error(ctx, f"No images found for **{query}**")
                        return

                    async with self._get_db() as conn:
                        await conn.execute(
                            'INSERT INTO image_search_cache (user_id, query, image_data) VALUES (?, ?, ?)',
                            (ctx.author.id, query, json.dumps(results))
                        )
                        await conn.commit()

                search_time_ms = int((time.time() - start_time) * 1000)

                if not hasattr(self.bot, '_image_search_data'):
                    self.bot._image_search_data = {}

                cache_key = f"{ctx.author.id}_{query}"
                self.bot._image_search_data[cache_key] = {
                    'results': results,
                    'user_name': ctx.author.display_name,
                    'search_time': search_time_ms
                }

                layout = create_image_layout(results, query, 0, ctx.author.display_name, search_time_ms, ctx.author.id, len(results))

                await ctx.send(view=layout)

            except Exception as e:
                await self.send_error(ctx, f"Image search failed: {str(e)}")

    @commands.hybrid_command(name="image", description="search for images", aliases=["img", "search", "photo"])
    async def image_standalone(self, ctx, *, query: str = None):
        await self.fun_image(ctx, query=query)

    @fun_group.command(name="img2gif", description="convert PNG images to GIF")
    @app_commands.describe(file="Image to convert to GIF (PNG/JPG/JPEG)")
    async def fun_img2gif(self, ctx, file: Optional[discord.Attachment] = None):
        image_url = None

        if file:
            if file.content_type and file.content_type.startswith('image/'):
                if file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    image_url = file.url
                else:
                    await self.send_error(ctx, "File must be a PNG/JPG/JPEG image")
                    return
            else:
                await self.send_error(ctx, "File must be an image (PNG/JPG/JPEG)")
                return

        elif ctx.message and ctx.message.attachments:
            for attachment in ctx.message.attachments:
                if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                    image_url = attachment.url
                    break

        elif ctx.message and ctx.message.reference and ctx.message.reference.message_id:
            try:
                replied_message = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                if replied_message.attachments:
                    for attachment in replied_message.attachments:
                        if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                            image_url = attachment.url
                            break
            except:
                pass

        if not image_url:
            await self.send_error(ctx, "Attach an image or reply to one.")
            return

        async with ctx.typing():
            try:
                api_url = "http://193.122.157.22:4793/fun/img2gif"
                async with aiohttp.ClientSession() as session:
                    payload = {"url": image_url}
                    async with session.post(api_url, json=payload) as resp:
                        if resp.status != 200:
                            await self.send_error(ctx, "img2gif API failed")
                            return

                        content_type = resp.headers.get('content-type', '')
                        if 'image' in content_type:
                            # Direct image response
                            output_data = await resp.read()
                        else:
                            # JSON response with url
                            data = await resp.json()
                            result_url = data.get("url")
                            if not result_url:
                                await self.send_error(ctx, "img2gif API returned no URL")
                                return
                            async with session.get(result_url) as img_resp:
                                if img_resp.status != 200:
                                    await self.send_error(ctx, "Failed to download result image")
                                    return
                                output_data = await img_resp.read()

                output_buffer = io.BytesIO(output_data)
                output_buffer.seek(0)
                output_file = discord.File(output_buffer, filename="converted.gif")
                embed = self._create_embed(title="image converted to GIF", description="your image has been converted to GIF format", color=discord.Color.green())
                embed.set_image(url="attachment://converted.gif")
                await ctx.send(embed=embed, file=output_file)

            except Exception as e:
                await self.send_error(ctx, f"Conversion failed: {str(e)}")

    @commands.hybrid_command(name="img2gif", description="turns a picture into a moving gif animation")
    async def img2gif(self, ctx):
        await self.fun_img2gif(ctx)

class UrbanDictionaryView(discord.ui.View):
    def __init__(self, definitions, user_id, bot):
        super().__init__(timeout=300)
        self.definitions = definitions
        self.user_id = user_id
        self.bot = bot
        self.current_page = 0
        self.max_pages = len(definitions)

        self.update_buttons()

    def create_embed(self):
        return create_urban_embed(self.definitions, self.current_page, self.bot.embed_color)

    def update_buttons(self):
        for item in self.children[:]:
            if isinstance(item, discord.ui.Button):
                self.remove_item(item)

        if self.current_page > 0:
            prev_button = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary)
            prev_button.callback = self.previous_page
            self.add_item(prev_button)

        if self.current_page < self.max_pages - 1:
            next_button = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary)
            next_button.callback = self.next_page
            self.add_item(next_button)

    async def previous_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return False
        return True

class StealView(discord.ui.View):
    def __init__(self, ctx, emojis, stickers, custom_name, bot):
        super().__init__(timeout=300)
        self.ctx = ctx
        self.emojis = emojis
        self.stickers = stickers
        self.custom_name = custom_name
        self.bot = bot
        self.current_emoji_index = 0
        self.current_sticker_index = 0
        self.user_id = ctx.author.id

        if emojis:
            self.add_emoji_button.disabled = False
            if len(emojis) > 1:
                self.add_all_emojis_button.disabled = False
        if stickers:
            self.add_sticker_button.disabled = False

    @discord.ui.button(label="Add Emoji", style=discord.ButtonStyle.primary, disabled=True)
    async def add_emoji_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        if not self.emojis:
            await interaction.response.send_message("no emojis to add", ephemeral=True)
            return

        emoji = self.emojis[self.current_emoji_index]

        try:

            async with aiohttp.ClientSession() as session:
                async with session.get(emoji['url']) as response:
                    if response.status == 200:
                        emoji_data = await response.read()
                    else:
                        await interaction.response.send_message("failed to download emoji", ephemeral=True)
                        return

            final_name = self.custom_name or emoji['name']

            if not interaction.guild:
                await interaction.response.send_message("this command can only be used in a server", ephemeral=True)
                return

            new_emoji = await interaction.guild.create_custom_emoji(
                name=final_name,
                image=emoji_data,
                reason=f"stolen by {interaction.user}"
            )

            embed = discord.Embed(title="✅ Success", description=f"added emoji {new_emoji} as `{final_name}`", color=discord.Color.green())
            await interaction.response.send_message(embed=embed, ephemeral=True)

            if self.current_emoji_index < len(self.emojis) - 1:
                self.current_emoji_index += 1
            else:
                button.disabled = True
                await interaction.edit_original_response(view=self)

        except discord.Forbidden:
            await interaction.response.send_message("i don't have permission to manage emojis", ephemeral=True)
        except discord.HTTPException as e:
            if e.code == 30008:
                await interaction.response.send_message("emoji limit reached for this server", ephemeral=True)
            else:
                await interaction.response.send_message(f"failed to add emoji: {str(e)}", ephemeral=True)

    @discord.ui.button(label="Add All Emojis", style=discord.ButtonStyle.success, disabled=True, row=1)
    async def add_all_emojis_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        if not self.emojis:
            await interaction.response.send_message("no emojis to add", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        added_count = 0
        failed_count = 0
        import aiohttp

        for emoji in self.emojis:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(emoji['url']) as response:
                        if response.status == 200:
                            emoji_data = await response.read()
                        else:
                            failed_count += 1
                            continue

                final_name = self.custom_name or emoji['name']

                if not interaction.guild:
                    await interaction.followup.send("this command can only be used in a server", ephemeral=True)
                    return

                await interaction.guild.create_custom_emoji(
                    name=final_name,
                    image=emoji_data,
                    reason=f"stolen by {interaction.user}"
                )
                added_count += 1

            except discord.Forbidden:
                failed_count += 1
                break
            except discord.HTTPException as e:
                if e.code == 30008:
                    failed_count += len(self.emojis) - added_count
                    break
                else:
                    failed_count += 1

        result_text = f"added {added_count} emoji{'s' if added_count != 1 else ''}"
        if failed_count > 0:
            result_text += f", {failed_count} failed"

        embed = discord.Embed(title="✅ Success", description=result_text, color=discord.Color.green())
        await interaction.followup.send(embed=embed, ephemeral=True)

        button.disabled = True
        self.add_emoji_button.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Add Sticker", style=discord.ButtonStyle.secondary, disabled=True)
    async def add_sticker_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        if not self.stickers:
            await interaction.response.send_message("no stickers to add", ephemeral=True)
            return

        sticker = self.stickers[self.current_sticker_index]

        try:

            async with aiohttp.ClientSession() as session:
                async with session.get(sticker['url']) as response:
                    if response.status == 200:
                        sticker_data = await response.read()
                    else:
                        await interaction.response.send_message("failed to download sticker", ephemeral=True)
                        return

            final_name = self.custom_name or sticker['name']

            if not interaction.guild:
                await interaction.response.send_message("this command can only be used in a server", ephemeral=True)
                return

            new_sticker = await interaction.guild.create_sticker(
                name=final_name,
                description=f"stolen by {interaction.user}",
                emoji="⭐",
                file=discord.File(io.BytesIO(sticker_data), filename=f"{final_name}.{'png' if sticker['format'] == discord.StickerFormatType.png else 'png'}"),
                reason=f"stolen by {interaction.user}"
            )

            embed = discord.Embed(title="✅ Success", description=f"added sticker `{final_name}`", color=discord.Color.green())
            await interaction.response.send_message(embed=embed, ephemeral=True)

            if self.current_sticker_index < len(self.stickers) - 1:
                self.current_sticker_index += 1
            else:
                button.disabled = True
                await interaction.edit_original_response(view=self)

        except discord.Forbidden:
            await interaction.response.send_message("i don't have permission to manage stickers", ephemeral=True)
        except discord.HTTPException as e:
            if e.code == 30039:
                await interaction.response.send_message("sticker limit reached for this server", ephemeral=True)
            else:
                await interaction.response.send_message(f"failed to add sticker: {str(e)}", ephemeral=True)

class ImageSearchView(discord.ui.View):
    def __init__(self, results, query, user_id, bot):
        super().__init__(timeout=300)
        self.results = results
        self.query = query
        self.user_id = user_id
        self.bot = bot
        self.current_page = 0
        self.max_pages = len(results)

        self.update_buttons()

    def create_embed(self):
        image_info = self.results[self.current_page]

        embed = discord.Embed(title=f"🖼️ Image Search: {self.query}", color=discord.Color.from_rgb(135, 206, 235))
        embed.add_field(name="Title", value=image_info.get('title', 'N/A'), inline=False)
        embed.add_field(name="Image URL", value=f"[{image_info.get('content', 'N/A')}]({image_info.get('content', '#')})", inline=False)
        embed.add_field(name="Source", value=f"[{image_info.get('domain', 'N/A')}]({image_info.get('url', '#')})", inline=False)
        embed.set_image(url=image_info.get('image', '#'))

        embed.set_footer(text=f"Image {self.current_page + 1}/{self.max_pages}")
        return embed

    def update_buttons(self):
        for item in self.children[:]:
            if isinstance(item, discord.ui.Button):
                self.remove_item(item)

        if self.current_page > 0:
            prev_button = discord.ui.Button(label="◀ Previous", style=discord.ButtonStyle.secondary)
            prev_button.callback = self.previous_page
            self.add_item(prev_button)

        if self.current_page < self.max_pages - 1:
            next_button = discord.ui.Button(label="Next ▶", style=discord.ButtonStyle.secondary)
            next_button.callback = self.next_page
            self.add_item(next_button)

    async def previous_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def next_page(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        if self.current_page < self.max_pages - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return False
        return True

class UrbanPrevButton(discord.ui.DynamicItem[discord.ui.Button], template=r'urban_prev:(?P<term>[^:]+):(?P<page>[0-9]+):(?P<user_id>[0-9]+)'):
    def __init__(self, term: str, page: int, user_id: int):
        super().__init__(
            discord.ui.Button(
                label="◀ Previous",
                style=discord.ButtonStyle.secondary,
                custom_id=f'urban_prev:{quote(term)}:{page}:{user_id}',
            )
        )
        self.term = term
        self.page = page
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        term = unquote(match['term'])
        page = int(match['page'])
        user_id = int(match['user_id'])
        return cls(term, page, user_id)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        new_page = self.page - 1
        if new_page < 0:
            return

        await refetch_urban(interaction, self.term, new_page, self.user_id)

class UrbanNextButton(discord.ui.DynamicItem[discord.ui.Button], template=r'urban_next:(?P<term>[^:]+):(?P<page>[0-9]+):(?P<user_id>[0-9]+)'):
    def __init__(self, term: str, page: int, user_id: int):
        super().__init__(
            discord.ui.Button(
                label="Next ▶",
                style=discord.ButtonStyle.secondary,
                custom_id=f'urban_next:{quote(term)}:{page}:{user_id}',
            )
        )
        self.term = term
        self.page = page
        self.user_id = user_id

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        term = unquote(match['term'])
        page = int(match['page'])
        user_id = int(match['user_id'])
        return cls(term, page, user_id)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        new_page = self.page + 1
        await refetch_urban(interaction, self.term, new_page, self.user_id)

class UrbanJumpButton(discord.ui.DynamicItem[discord.ui.Button], template=r'urban_jump:(?P<term>[^:]+):(?P<page>[0-9]+):(?P<user_id>[0-9]+):(?P<max_pages>[0-9]+)'):
    def __init__(self, term: str, page: int, user_id: int, max_pages: int):
        super().__init__(
            discord.ui.Button(
                emoji='🔍',
                style=discord.ButtonStyle.primary,
                custom_id=f'urban_jump:{quote(term)}:{page}:{user_id}:{max_pages}',
            )
        )
        self.term = term
        self.page = page
        self.user_id = user_id
        self.max_pages = max_pages

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        term = unquote(match['term'])
        page = int(match['page'])
        user_id = int(match['user_id'])
        max_pages = int(match['max_pages'])
        return cls(term, page, user_id, max_pages)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        modal = UrbanPageJumpModal(self.term, self.user_id, self.max_pages)
        await interaction.response.send_modal(modal)

class ImagePrevButton(discord.ui.DynamicItem[discord.ui.Button], template=r'img_prev:(?P<query_hash>[a-f0-9]+):(?P<page>[0-9]+):(?P<user_id>[0-9]+)'):
    def __init__(self, query_hash: str, page: int, user_id: int, preloaded_embeds: list = None):
        super().__init__(
            discord.ui.Button(
                label='◀ Previous',
                style=discord.ButtonStyle.secondary,
                custom_id=f'img_prev:{query_hash}:{page}:{user_id}',
            )
        )
        self.query_hash = query_hash
        self.page = page
        self.user_id = user_id
        self.preloaded_embeds = preloaded_embeds or []

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        query_hash = match['query_hash']
        page = int(match['page'])
        user_id = int(match['user_id'])

        if not hasattr(interaction.client, '_image_embed_cache'):
            interaction.client._image_embed_cache = {}

        query = None
        for key in interaction.client._image_embed_cache.keys():
            if hashlib.md5(key.split('_', 1)[1].encode()).hexdigest()[:16] == query_hash:
                query = key.split('_', 1)[1]
                break

        preloaded_embeds = []

        return cls(query_hash, page, user_id, preloaded_embeds)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        new_page = self.page - 1
        if new_page < 0:
            return

        query = None
        if hasattr(interaction.client, '_image_search_data'):
            for key in interaction.client._image_search_data.keys():
                if hashlib.md5(key.split('_', 1)[1].encode()).hexdigest()[:16] == self.query_hash:
                    query = key.split('_', 1)[1]
                    break

        if not query:
            await interaction.response.send_message("search expired, please search again", ephemeral=True)
            return

        await refetch_images(interaction, query, new_page, self.user_id, self.preloaded_embeds)

class ImageNextButton(discord.ui.DynamicItem[discord.ui.Button], template=r'img_next:(?P<query_hash>[a-f0-9]+):(?P<page>[0-9]+):(?P<user_id>[0-9]+)'):
    def __init__(self, query_hash: str, page: int, user_id: int, preloaded_embeds: list = None):
        super().__init__(
            discord.ui.Button(
                label='Next ▶',
                style=discord.ButtonStyle.secondary,
                custom_id=f'img_next:{query_hash}:{page}:{user_id}',
            )
        )
        self.query_hash = query_hash
        self.page = page
        self.user_id = user_id
        self.preloaded_embeds = preloaded_embeds or []

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        query_hash = match['query_hash']
        page = int(match['page'])
        user_id = int(match['user_id'])

        return cls(query_hash, page, user_id, [])

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        query = None
        if hasattr(interaction.client, '_image_search_data'):
            for key in interaction.client._image_search_data.keys():
                if hashlib.md5(key.split('_', 1)[1].encode()).hexdigest()[:16] == self.query_hash:
                    query = key.split('_', 1)[1]
                    break

        if not query:
            await interaction.response.send_message("search expired, please search again", ephemeral=True)
            return

        new_page = self.page + 1
        await refetch_images(interaction, query, new_page, self.user_id, self.preloaded_embeds)

class ImageJumpButton(discord.ui.DynamicItem[discord.ui.Button], template=r'img_jump:(?P<query_hash>[a-f0-9]+):(?P<page>[0-9]+):(?P<user_id>[0-9]+):(?P<max_pages>[0-9]+)'):
    def __init__(self, query_hash: str, page: int, user_id: int, max_pages: int, preloaded_embeds: list = None):
        super().__init__(
            discord.ui.Button(
                emoji='🔍',
                style=discord.ButtonStyle.primary,
                custom_id=f'img_jump:{query_hash}:{page}:{user_id}:{max_pages}',
            )
        )
        self.query_hash = query_hash
        self.page = page
        self.user_id = user_id
        self.max_pages = max_pages
        self.preloaded_embeds = preloaded_embeds or []

    @classmethod
    async def from_custom_id(cls, interaction: discord.Interaction, item: discord.ui.Button, match: re.Match[str], /):
        query_hash = match['query_hash']
        page = int(match['page'])
        user_id = int(match['user_id'])
        max_pages = int(match['max_pages'])

        return cls(query_hash, page, user_id, max_pages, [])

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("you cannot use these buttons", ephemeral=True)
            return

        query = None
        if hasattr(interaction.client, '_image_search_data'):
            for key in interaction.client._image_search_data.keys():
                if hashlib.md5(key.split('_', 1)[1].encode()).hexdigest()[:16] == self.query_hash:
                    query = key.split('_', 1)[1]
                    break

        if not query:
            await interaction.response.send_message("search expired, please search again", ephemeral=True)
            return

        modal = ImagePageJumpModal(query, self.user_id, self.max_pages, self.preloaded_embeds)
        await interaction.response.send_modal(modal)

class UrbanPageJumpModal(discord.ui.Modal, title='Jump to Page'):
    page_number = discord.ui.TextInput(label='Page Number', placeholder='Enter page number...', min_length=1, max_length=3, required=True)

    def __init__(self, term: str, user_id: int, max_pages: int):
        super().__init__()
        self.term = term
        self.user_id = user_id
        self.max_pages = max_pages
        self.page_number.placeholder = f'1-{max_pages}'

    async def on_submit(self, interaction: discord.Interaction):
        try:
            page_num = int(self.page_number.value)
            if page_num < 1 or page_num > self.max_pages:
                await interaction.response.send_message(f"please enter a number between 1 and {self.max_pages}", ephemeral=True)
                return

            new_page = page_num - 1
            await refetch_urban(interaction, self.term, new_page, self.user_id)
        except ValueError:
            await interaction.response.send_message("please enter a valid number", ephemeral=True)

class ImagePageJumpModal(discord.ui.Modal, title='Jump to Page'):
    page_number = discord.ui.TextInput(label='Page Number', placeholder='Enter page number...', min_length=1, max_length=3, required=True)

    def __init__(self, query: str, user_id: int, max_pages: int, preloaded_embeds: list = None):
        super().__init__()
        self.query = query
        self.user_id = user_id
        self.max_pages = max_pages
        self.preloaded_embeds = preloaded_embeds or []
        self.page_number.placeholder = f'1-{max_pages}'

    async def on_submit(self, interaction: discord.Interaction):
        try:
            page_num = int(self.page_number.value)
            if page_num < 1 or page_num > self.max_pages:
                await interaction.response.send_message(f"please enter a number between 1 and {self.max_pages}", ephemeral=True)
                return

            new_page = page_num - 1
            await refetch_images(interaction, self.query, new_page, self.user_id, self.preloaded_embeds)
        except ValueError:
            await interaction.response.send_message("please enter a valid number", ephemeral=True)

async def refetch_urban(interaction: discord.Interaction, term: str, page: int, user_id: int):
    async with aiohttp.ClientSession() as session:
        url = f"http://api.urbandictionary.com/v0/define?term={term}"
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                results = data.get('list', [])[:100]

                if results and page < len(results):
                    bot = interaction.client
                    embed = create_urban_embed(results, page, bot.embed_color)
                    view = UrbanDictionaryView(results, user_id, bot)
                    await interaction.response.edit_message(embed=embed, view=view)
                else:
                    await interaction.response.send_message("page not found", ephemeral=True)
            else:
                await interaction.response.send_message("failed to fetch results", ephemeral=True)

async def refetch_images(interaction: discord.Interaction, query: str, page: int, user_id: int, preloaded_embeds: list):
    try:
        cache_key = f"{user_id}_{query}"
        db_path = Path(__file__).parent.parent / "database" / "votox.db"

        if not hasattr(interaction.client, '_image_search_data') or cache_key not in interaction.client._image_search_data:
            async with aiosqlite.connect(db_path) as conn:
                async with conn.execute(
                    'SELECT image_data FROM image_search_cache WHERE user_id = ? AND query = ? ORDER BY created_at DESC LIMIT 1',
                    (user_id, query)
                ) as cursor:
                    cached = await cursor.fetchone()

            if cached:
                results = json.loads(cached[0])
                if not hasattr(interaction.client, '_image_search_data'):
                    interaction.client._image_search_data = {}
                interaction.client._image_search_data[cache_key] = {
                    'results': results,
                    'user_name': interaction.user.display_name,
                    'search_time': 0
                }
            else:
                if not interaction.response.is_done():
                    await interaction.response.send_message("no cached images found. please search again", ephemeral=True)
                else:
                    await interaction.followup.send("no cached images found. please search again", ephemeral=True)
                return

        search_data = interaction.client._image_search_data[cache_key]
        results = search_data['results']

        if page < len(results):
            layout = create_image_layout(
                results, query, page,
                search_data['user_name'], search_data['search_time'],
                user_id, len(results)
            )

            if not interaction.response.is_done():
                await interaction.response.defer()
            await interaction.edit_original_response(view=layout)
        else:
            if not interaction.response.is_done():
                await interaction.response.send_message("page not found", ephemeral=True)
            else:
                await interaction.followup.send("page not found", ephemeral=True)
    except Exception as e:
        try:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"failed to navigate: {str(e)}", ephemeral=True)
            else:
                await interaction.followup.send(f"failed to navigate: {str(e)}", ephemeral=True)
        except:
            pass

def create_urban_embed(results, current_page, color):
    definition = results[current_page]

    definition_text = definition['definition'].replace('[', '').replace(']', '')
    example_text = definition.get('example', 'No example available').replace('[', '').replace(']', '')

    if len(definition_text) > 1024:
        definition_text = definition_text[:1021] + "..."
    if len(example_text) > 1024:
        example_text = example_text[:1021] + "..."

    embed = discord.Embed(title=f"📚 Urban Dictionary: {definition['word']}", color=color)

    embed.add_field(name="Definition", value=definition_text, inline=False)
    embed.add_field(name="Example", value=example_text, inline=False)
    embed.add_field(name="👍", value=str(definition.get('thumbs_up', 0)), inline=True)
    embed.add_field(name="👎", value=str(definition.get('thumbs_down', 0)), inline=True)
    embed.add_field(name="Author", value=definition.get('author', 'Unknown'), inline=True)

    if definition.get('permalink'):
        embed.add_field(name="Link", value=f"[View on Urban Dictionary]({definition['permalink']})", inline=False)

    embed.set_footer(text=f"Definition {current_page + 1}/{len(results)}")

    return embed

def create_image_layout(results, query, current_page, user_name, search_time_ms, user_id, max_pages):
    image_info = results[current_page]

    title = image_info.get('title', 'N/A')
    if len(title) > 100:
        title = title[:97] + "..."

    image_url = image_info.get('image') or image_info.get('thumbnail')
    source_url = image_info.get('url', '#')

    search_time = f"{search_time_ms}ms" if search_time_ms < 1000 else f"{search_time_ms/1000:.1f}s"

    query_hash = hashlib.md5(query.encode()).hexdigest()[:16]

    class ImageLayout(discord.ui.LayoutView):
        container1 = discord.ui.Container(
            discord.ui.TextDisplay(content=f"# query: {query}"),
            discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            discord.ui.MediaGallery(
                discord.MediaGalleryItem(
                    media=image_url if image_url else "https://via.placeholder.com/300x200?text=Image+Not+Available",
                ),
            ) if image_url else discord.ui.TextDisplay(content="*Image not available*"),
            discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
            discord.ui.ActionRow(
                discord.ui.Button(
                    style=discord.ButtonStyle.secondary,
                    label="<",
                    custom_id=f'img_prev:{query_hash}:{current_page}:{user_id}',
                    disabled=current_page == 0
                ),
                discord.ui.Button(
                    style=discord.ButtonStyle.secondary,
                    label="Jump",
                    custom_id=f'img_jump:{query_hash}:{current_page}:{user_id}:{max_pages}',
                ),
                discord.ui.Button(
                    style=discord.ButtonStyle.secondary,
                    label=">",
                    custom_id=f'img_next:{query_hash}:{current_page}:{user_id}',
                    disabled=current_page >= max_pages - 1
                ),
            ),
            discord.ui.ActionRow(
                discord.ui.Button(
                    url=source_url,
                    style=discord.ButtonStyle.link,
                    label="image source",
                ),
                discord.ui.Button(
                    url=image_url if image_url else "https://discord.com",
                    style=discord.ButtonStyle.link,
                    label="image link",
                ),
            ),
            accent_colour=discord.Colour(0x87CEEB),
        )

    return ImageLayout()

def create_image_view(query: str, current_page: int, max_pages: int, user_id: int):
    view = discord.ui.View(timeout=None)

    if current_page > 0:
        view.add_item(ImagePrevButton(query, current_page, user_id).item)

    view.add_item(ImageJumpButton(query, current_page, user_id, max_pages).item)

    if current_page < max_pages - 1:
        view.add_item(ImageNextButton(query, current_page, user_id).item)

    return view

async def setup(bot):
    await bot.add_cog(Fun(bot))