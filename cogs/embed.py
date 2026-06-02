import discord
from discord.ext import commands
import aiosqlite
from pathlib import Path
from typing import Optional, Dict, Any
import logging
from utils.embed_parser import parse_embed, build_script, embed_to_script, EmbedParserException

logger = logging.getLogger("VOTOX")

class TitleDescModal(discord.ui.Modal, title="Embed Content"):
    title_input = discord.ui.TextInput(label="Title", required=False, placeholder="Enter embed title...")
    desc_input = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, required=False)
    author_input = discord.ui.TextInput(label="Author Name", required=False)
    author_icon = discord.ui.TextInput(label="Author Icon URL", required=False)
    author_url = discord.ui.TextInput(label="Author Link URL", required=False)

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.title_input.default = view.data.get('title', '')
        self.desc_input.default = view.data.get('description', '')
        self.author_input.default = view.data.get('author_name', '')
        self.author_icon.default = view.data.get('author_icon', '')
        self.author_url.default = view.data.get('author_url', '')

    async def on_submit(self, interaction: discord.Interaction):
        self.view.data['title'] = self.title_input.value
        self.view.data['description'] = self.desc_input.value
        self.view.data['author_name'] = self.author_input.value
        self.view.data['author_icon'] = self.author_icon.value
        self.view.data['author_url'] = self.author_url.value
        await interaction.response.send_message("Updated Title/Description.", ephemeral=True)

class VisualsModal(discord.ui.Modal, title="Visuals & Color"):
    color_input = discord.ui.TextInput(label="Hex Color", placeholder="#ffffff", required=False)
    thumb_input = discord.ui.TextInput(label="Thumbnail URL", required=False)
    image_input = discord.ui.TextInput(label="Image URL", required=False)
    footer_input = discord.ui.TextInput(label="Footer Text", required=False)
    timestamp_input = discord.ui.TextInput(label="Enable Timestamp (true/false)", default="true", required=False)

    def __init__(self, view):
        super().__init__()
        self.view = view
        self.color_input.default = view.data.get('color', '')
        self.thumb_input.default = view.data.get('thumbnail', '')
        self.image_input.default = view.data.get('image', '')
        self.footer_input.default = view.data.get('footer_text', '')
        self.timestamp_input.default = "true" if view.data.get('timestamp') else "false"

    async def on_submit(self, interaction: discord.Interaction):
        self.view.data['color'] = self.color_input.value
        self.view.data['thumbnail'] = self.thumb_input.value
        self.view.data['image'] = self.image_input.value
        self.view.data['footer_text'] = self.footer_input.value
        self.view.data['timestamp'] = self.timestamp_input.value.lower() == 'true'
        await interaction.response.send_message("Updated Visuals.", ephemeral=True)

class FieldModal(discord.ui.Modal, title="Add Field"):
    f_name = discord.ui.TextInput(label="Field Name")
    f_val = discord.ui.TextInput(label="Field Value", style=discord.TextStyle.paragraph)
    f_inline = discord.ui.TextInput(label="Inline (true/false)", default="false")

    def __init__(self, view):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.view.data.setdefault('fields', []).append({
            'name': self.f_name.value,
            'value': self.f_val.value,
            'inline': self.f_inline.value.lower() == 'true'
        })
        await interaction.response.send_message(f"Added field: {self.f_name.value}", ephemeral=True)

# ========================= VIEW =========================

class EmbedBuilderView(discord.ui.View):
    def __init__(self, author_id: int):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.data: Dict[str, Any] = {}

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("You are not the builder.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Title/Description", style=discord.ButtonStyle.secondary)
    async def btn_title(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TitleDescModal(self))

    @discord.ui.button(label="Color/Images", style=discord.ButtonStyle.secondary)
    async def btn_visuals(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(VisualsModal(self))

    @discord.ui.button(label="Add Field", style=discord.ButtonStyle.secondary)
    async def btn_field(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(FieldModal(self))

    @discord.ui.button(label="Get Script", style=discord.ButtonStyle.primary)
    async def btn_script(self, interaction: discord.Interaction, button: discord.ui.Button):
        script = build_script(self.data)
        await interaction.response.send_message(f"**Your Embed Script:**\n```\n{script}\n```", ephemeral=True)

    @discord.ui.button(label="Post Embed", style=discord.ButtonStyle.success)
    async def btn_post(self, interaction: discord.Interaction, button: discord.ui.Button):
        script = build_script(self.data)
        try:
            content, embed, view = parse_embed(script)
            await interaction.channel.send(content=content or None, embed=embed, view=view)
            await interaction.response.send_message("✅ Embed posted!", ephemeral=True)
        except EmbedParserException as e:
            await interaction.response.send_message(f"Error parsing built embed: {e}", ephemeral=True)

class Embed(commands.Cog):
    """
    Advanced dynamic embed management and building system.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"

    def _get_db(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initialize database for saved scripts."""
        async with self._get_db() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS saved_embeds (
                    guild_id INTEGER,
                    script_name TEXT,
                    script_content TEXT,
                    PRIMARY KEY (guild_id, script_name)
                )
            ''')
            await db.commit()

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
        embed.set_footer(text="VOTOX Embed System", icon_url=self.bot.user.display_avatar.url)
        return embed

    def _create_success_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"✅ {title}", description, discord.Color.green())

    def _create_error_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"❌ {title}", description, discord.Color.red())

    def _create_info_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"ℹ️ {title}", description, discord.Color.blurple())

    # ========================= COMMANDS =========================

    @commands.group(name="embed", invoke_without_command=True)
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    async def embed_group(self, ctx: commands.Context):
        """Displays the elegant help menu for embed utilities."""
        prefix = ctx.clean_prefix
        embed = self._create_embed(
            "🖼️ VOTOX Embed Management",
            "Powerful tools to build and broadcast custom Discord embeds."
        )

        embed.add_field(name="Available Commands", value=(
            f"`{prefix}embed send [name/script]` - Post a saved embed or raw code.\n"
            f"`{prefix}embed create` - Launch the interactive UI builder.\n"
            f"`{prefix}embed save [name] [script]` - Store a script for future use.\n"
            f"`{prefix}embed delete [name]` - Remove a saved script.\n"
            f"`{prefix}embed edit [name] [script]` - Update a stored script."
        ), inline=False)

        embed.add_field(name="Tag Guidelines", value=(
            "**Basic:** `{title: text}`, `{description: text}`, `{color: hex}`, `{content: text}`\n"
            "**Author:** `{author: name: x && icon: url && url: url}`\n"
            "**Footer:** `{footer: text: x && icon: url}`\n"
            "**Fields:** `{field: name: x && value: y && inline: true/false}`\n"
            "**Interactive:** `{buttons}`, `{button: label=x && style=success && action={msg}}`"
        ), inline=False)

        embed.add_field(name="Tip", value="Reply to a message and use `.embed copy` to get its script.", inline=False)
        embed.set_footer(text="VOTOX: All scripts MUST contain the {embed} tag.")
        await ctx.send(embed=embed)

    @embed_group.command(name="send")
    @commands.has_permissions(manage_messages=True)
    async def embed_send(self, ctx: commands.Context, *, script_or_name: str):
        """Broadcasts a saved script or parses raw input."""
        content_to_parse = script_or_name

        # 1. DB Lookup
        async with self._get_db() as db:
            cursor = await db.execute(
                "SELECT script_content FROM saved_embeds WHERE guild_id = ? AND script_name = ?",
                (ctx.guild.id, script_or_name)
            )
            row = await cursor.fetchone()
            if row:
                content_to_parse = row[0]

        # 2. Parse and send
        try:
            content, embed, view = parse_embed(content_to_parse)
            if not embed:
                return await ctx.send(embed=self._create_error_embed(
                    "Invalid Script", 
                    "The content does not contain a valid `{embed}` tag."
                ))
            
            await ctx.send(content=content or None, embed=embed, view=view)
            if not ctx.interaction:
                try: await ctx.message.delete() 
                except: pass 

        except EmbedParserException as e:
            await ctx.send(embed=self._create_embed("❌ Parsing Error", str(e), discord.Color.red()))

    @embed_group.command(name="create")
    @commands.has_permissions(manage_messages=True)
    async def embed_create(self, ctx: commands.Context):
        """Launches the premium interactive UI builder."""
        view = EmbedBuilderView(ctx.author.id)
        embed = self._create_embed(
            "🎨 Embed Builder Studio",
            "Use the buttons below to configure your embed elements. Once finished, you can generate the script or post it directly."
        )
        await ctx.send(embed=embed, view=view)

    @embed_group.command(name="save")
    @commands.has_permissions(manage_messages=True)
    async def embed_save(self, ctx: commands.Context, name: str, *, script: str):
        """Registers a custom script to the database."""
        if "{embed}" not in script:
            return await ctx.send(embed=self._create_error_embed("Error", "Script must contain the `{embed}` tag."))

        async with self._get_db() as db:
            try:
                await db.execute(
                    "INSERT INTO saved_embeds (guild_id, script_name, script_content) VALUES (?, ?, ?)",
                    (ctx.guild.id, name.lower(), script)
                )
                await db.commit()
                await ctx.send(embed=self._create_success_embed("Script Saved", f"Stored `{name.lower()}`. Use `{ctx.clean_prefix}embed send {name.lower()}` to post it."))
            except aiosqlite.IntegrityError:
                await ctx.send(embed=self._create_error_embed("Error", "A script with that name already exists. Use `edit` to overwrite."))

    @embed_group.command(name="edit")
    @commands.has_permissions(manage_messages=True)
    async def embed_edit(self, ctx: commands.Context, name: str, *, new_script: str):
        """Overwrites an existing saved script."""
        async with self._get_db() as db:
            cursor = await db.execute(
                "UPDATE saved_embeds SET script_content = ? WHERE guild_id = ? AND script_name = ?",
                (new_script, ctx.guild.id, name.lower())
            )
            await db.commit()
            
            if cursor.rowcount == 0:
                return await ctx.send(embed=self._create_error_embed("Not Found", f"No script named `{name}` exists."))
            
            await ctx.send(embed=self._create_success_embed("Script Updated", f"Updated contents for `{name.lower()}`."))

    @embed_group.command(name="delete")
    @commands.has_permissions(manage_messages=True)
    async def embed_delete(self, ctx: commands.Context, name: str):
        """Deletes a saved script from the guild records."""
        async with self._get_db() as db:
            cursor = await db.execute(
                "DELETE FROM saved_embeds WHERE guild_id = ? AND script_name = ?",
                (ctx.guild.id, name.lower())
            )
            await db.commit()
            
            if cursor.rowcount == 0:
                return await ctx.send(embed=self._create_error_embed("Not Found", f"No script named `{name}` exists."))
            
            await ctx.send(embed=self._create_success_embed("Script Deleted", f"Removed `{name.lower()}` from the database."))

    @embed_group.command(name="list")
    @commands.has_permissions(manage_messages=True)
    async def embed_list(self, ctx: commands.Context):
        """Lists all saved embed scripts for this server."""
        async with self._get_db() as db:
            cursor = await db.execute("SELECT script_name FROM saved_embeds WHERE guild_id = ?", (ctx.guild.id,))
            rows = await cursor.fetchall()

        if not rows:
            return await ctx.send(embed=self._create_embed("📋 Saved Scripts", "No scripts have been saved in this server."))

        names = "\n".join([f"• `{r[0]}`" for r in rows])
        await ctx.send(embed=self._create_embed("📋 Saved Scripts", names))

    @embed_group.command(name="copy")
    @commands.has_permissions(manage_messages=True)
    async def embed_copy(self, ctx: commands.Context):
        """Reverse-engineers a replied-to message into VOTOX script."""
        if not ctx.message.reference:
            return await ctx.send(embed=self._create_embed(
                "⚠️ Copy Error", 
                "You must **reply** to the message containing the embed you want to copy.",
                discord.Color.orange()
            ))

        target_msg = await ctx.channel.fetch_message(ctx.message.reference.message_id)
        if not target_msg.embeds and not target_msg.content:
            return await ctx.send(embed=self._create_error_embed("No Content", "The target message has no content or embeds to copy."))

        script = embed_to_script(target_msg)
        await ctx.send(
            content=f"📝 **Extracted Embed Script:**\n```\n{script}\n```",
            reference=ctx.message
        )

async def setup(bot: commands.Bot):
    """Loads the Embed cog."""
    await bot.add_cog(Embed(bot))