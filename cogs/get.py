from discord import (
    Color,
    Colour,
    Interaction,
    Member,
    User,
    Status,
    NotFound,
    PartialEmoji,
    MediaGalleryItem,
    ButtonStyle,
    SeparatorSpacing
)
from discord.ui import (
    LayoutView,
    Container,
    TextDisplay,
    Separator,
    MediaGallery,
    Button,
    ActionRow,
    Thumbnail,
    Section
)
from discord.ext.commands import (
    Cog,
    command,
    hybrid_group,
    cooldown,
    BucketType,
    CommandOnCooldown
)
from discord.app_commands import describe
from typing import Optional, Union
import logging
import time
import psutil


logger = logging.getLogger(__name__)

class Get(Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_command_error(self, ctx, error):
        if isinstance(error, CommandOnCooldown):
            return
        pass

    def format_timestamp(self, timestamp):
        if isinstance(timestamp, str):
            from datetime import datetime
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return f"<t:{int(timestamp.timestamp())}:R>"

    @hybrid_group(
        name="get",
        description="grab user and server info",
        fallback="help",
        extras={'example': ',get profile'}
    )
    async def get_group(self, ctx):
        pass

    @get_group.command(
        name="avatar",
        description="show someone's pfp",
        extras={'example': ',get avatar @user'}
    )
    @describe(user="User whose avatar to show (defaults to yourself)")
    @cooldown(1, 10, BucketType.user)
    async def get_avatar(self, ctx, user: Optional[Member] = None):
        user = user or ctx.author
        server_avatar = getattr(user, 'guild_avatar', None)
        avatar_url = server_avatar.url if server_avatar else (
            user.avatar.url if user.avatar else user.default_avatar.url
        )
        
        media_items = [MediaGalleryItem(media=avatar_url)]
        if user.avatar_decoration:
            media_items.append(MediaGalleryItem(media=user.avatar_decoration.url))

        class AvatarView(LayoutView):
            container = Container(
                TextDisplay(f"**{user.display_name}'s Avatar**"),
                Separator(visible=True, spacing=SeparatorSpacing.small),
                MediaGallery(*media_items),
                Separator(visible=True, spacing=SeparatorSpacing.small),
                TextDisplay(f"Type: {'Custom' if user.avatar else 'Default'}"),
                TextDisplay(
                    f"User: {user.mention} ({user.id})" + (
                        f" | Decoration: [View]({user.avatar_decoration.url})" if user.avatar_decoration else ""
                    )
                ),
                accent_color=user.color if user.color else Colour(0x5865F2)
            )
        
        await ctx.send(view=AvatarView())

    @get_group.command(
        name="banner",
        description="show someone's banner",
        extras={'example': ',get banner @user'}
    )
    @describe(user="User whose banner to show (defaults to yourself)")
    @cooldown(1, 10, BucketType.user)
    async def get_banner(self, ctx, user: Optional[Member] = None):
        user = user or ctx.author
        fetched_user = await self.bot.fetch_user(user.id)
        server_banner = getattr(user, 'guild_banner', None)
        banner_url = server_banner.url if server_banner else (
            fetched_user.banner.url if fetched_user.banner else None
        )

        if not banner_url:
            class NoBannerView(LayoutView):
                container = Container(
                    TextDisplay(f"**{user.display_name}'s Banner**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    TextDisplay("This user has no banner set"),
                    accent_color=Colour(0x808080)
                )
            await ctx.send(view=NoBannerView())
        else:
            class BannerView(LayoutView):
                container = Container(
                    TextDisplay(f"**{user.display_name}'s Banner**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    MediaGallery(MediaGalleryItem(media=banner_url)),
                    accent_color=user.color if user.color else Colour(0x5865F2)
                )
            await ctx.send(view=BannerView())

    @get_group.command(
        name="profile",
        description="see info about a user",
        extras={'example': ',get profile @user'}
    )
    @describe(user="User whose profile to show (defaults to yourself)")
    @cooldown(1, 10, BucketType.user)
    async def get_profile(self, ctx, user: Optional[Member] = None):
        user = user or ctx.author

        key_perms = []
        if user.guild_permissions.administrator:
            key_perms.append("Administrator")
        else:
            perms_to_check = [
                ("manage_guild", "Manage Server"),
                ("manage_roles", "Manage Roles"),
                ("manage_channels", "Manage Channels"),
                ("manage_messages", "Manage Messages"),
                ("kick_members", "Kick Members"),
                ("ban_members", "Ban Members"),
                ("moderate_members", "Timeout Members")
            ]
            for perm, display in perms_to_check:
                if getattr(user.guild_permissions, perm):
                    key_perms.append(display)

        perms_text = ", ".join(key_perms) if key_perms else "None"
        roles_text = " ".join(
            [
                r.mention for r in sorted(
                    user.roles[1:],
                    key=lambda r: r.position,
                    reverse=True
                )[:10]
            ]
        ) if len(user.roles) > 1 else "None"

        class ProfileView(LayoutView):
            container = Container(
                TextDisplay(f"**{user.display_name}'s Profile**"),
                Separator(visible=True, spacing=SeparatorSpacing.small),
                TextDisplay(f"ID: {user.id}"),
                TextDisplay(f"Created: {self.format_timestamp(user.created_at)}"),
                TextDisplay(f"Joined: {self.format_timestamp(user.joined_at) if user.joined_at else 'N/A'}"),
                TextDisplay(f"Status: {str(user.status).replace('Status.', '').title()}"),
                TextDisplay(f"Roles ({len(user.roles)-1}): {roles_text}"),
                TextDisplay(f"Key Permissions: {perms_text}"),
                accent_color=user.color if user.color else Colour(0x5865F2)
            )
        
        await ctx.send(view=ProfileView())

    @get_group.command(
        name="device",
        description="see what device someone's on",
        extras={'example': ',get device @user'}
    )
    @describe(user="User whose device info to show (defaults to yourself)")
    @cooldown(1, 10, BucketType.user)
    async def get_device(self, ctx, user: Optional[Member] = None):
        user = user or ctx.author

        if user.status == Status.offline:
            class OfflineView(LayoutView):
                container = Container(
                    TextDisplay(f"**Device Information**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    TextDisplay(f"User: {user.mention} ({user.display_name})"),
                    TextDisplay(f"Status: Offline"),
                    accent_color=Colour(0x747F8D)
                )
            await ctx.send(view=OfflineView())
            return

        platforms = []
        client_status = user.client_status
        if client_status:
            if client_status.desktop != Status.offline:
                platforms.append("💻 Desktop")
            if client_status.mobile != Status.offline:
                platforms.append("📱 Mobile")
            if client_status.web != Status.offline:
                platforms.append("🌐 Web")
            if hasattr(client_status, "embedded") and client_status.embedded != Status.offline:
                platforms.append("🎮 Console???")

        platforms_text = " | ".join(platforms) if platforms else "Unknown"

        items = [
            TextDisplay(f"**Device Information**"),
            Separator(visible=True, spacing=SeparatorSpacing.small),
            TextDisplay(f"User: {user.mention} ({user.display_name})"),
            TextDisplay(f"Status: {str(user.status).replace('Status.', '').replace('_', ' ').title()}"),
            TextDisplay(f"Platforms: {platforms_text}"),
        ]

        if client_status:
            if client_status.desktop != Status.offline:
                items.append(TextDisplay(f"Desktop: {str(client_status.desktop).replace('Status.', '')}"))
            if client_status.mobile != Status.offline:
                items.append(TextDisplay(f"Mobile: {str(client_status.mobile).replace('Status.', '')}"))
            if client_status.web != Status.offline:
                items.append(TextDisplay(f"Web: {str(client_status.web).replace('Status.', '')}"))
            if hasattr(client_status, "embedded") and client_status.embedded != Status.offline:
                items.append(TextDisplay(f"Console: {str(client_status.embedded).replace('Status.', '')}"))

        class DeviceView(LayoutView):
            container = Container(*items, accent_color=Colour(0x5865F2))
        
        await ctx.send(view=DeviceView())

    @get_group.command(
        name="serverinfo",
        description="see info about this server",
        extras={'example': ',get serverinfo'}
    )
    @cooldown(1, 10, BucketType.user)
    async def get_serverinfo(self, ctx):
        await self.serverinfo_standalone(ctx)

    @get_group.command(
        name="servericon",
        description="show the server icon",
        extras={'example': ',get servericon'}
    )
    @cooldown(1, 10, BucketType.user)
    async def get_servericon(self, ctx):
        guild = ctx.guild

        if not guild.icon:
            class NoIconView(LayoutView):
                container = Container(
                    TextDisplay(f"**{guild.name} Server Icon**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    TextDisplay("This server has no icon set"),
                    accent_color=Colour(0x808080)
                )
            await ctx.send(view=NoIconView())
        else:
            class IconView(LayoutView):
                container = Container(
                    TextDisplay(f"**{guild.name} Server Icon**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    MediaGallery(MediaGalleryItem(media=guild.icon.url)),
                    accent_color=Colour(0x5865F2)
                )
            await ctx.send(view=IconView())

    @get_group.command(
        name="serverbanner",
        description="show the server banner",
        extras={'example': ',get serverbanner'}
    )
    @cooldown(1, 10, BucketType.user)
    async def get_serverbanner(self, ctx):
        guild = ctx.guild

        if not guild.banner:
            class NoBannerView(LayoutView):
                container = Container(
                    TextDisplay(f"**{guild.name} Server Banner**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    TextDisplay("This server has no banner set"),
                    accent_color=Colour(0x808080)
                )
            await ctx.send(view=NoBannerView())
        else:
            class BannerView(LayoutView):
                container = Container(
                    TextDisplay(f"**{guild.name} Server Banner**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    MediaGallery(MediaGalleryItem(media=guild.banner.url)),
                    accent_color=Colour(0x5865F2)
                )
            await ctx.send(view=BannerView())

    @command(
        name="avatar",
        aliases=["pfp", "av"],
        description="show someone's avatar",
        extras={'example': ',avatar @user'}
    )
    @cooldown(1, 10, BucketType.user)
    async def avatar_standalone(self, ctx, user: Optional[Union[Member, User]] = None):
        user = user or ctx.author
        
        if not isinstance(user, Member) and not isinstance(user, User):
            try:
                user = await self.bot.fetch_user(int(user))
            except:
                user = ctx.author

        has_server_avatar = isinstance(user, Member) and user.guild_avatar is not None
        
        def get_view(showing_server: bool):
            is_mem = isinstance(user, Member)
            url = None
            if showing_server and is_mem:
                url = user.guild_avatar.url if user.guild_avatar else user.display_avatar.url
            else:
                url = user.avatar.url if user.avatar else user.default_avatar.url

            title_type = "Server" if showing_server else "User"
            
            btn = Button(
                label=f"Show {'User' if showing_server else 'Server'}",
                style=ButtonStyle.primary,
                emoji=PartialEmoji.from_str('📷')
            )
            
            async def btn_callback(interaction: Interaction):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("This button is not for you!", ephemeral=True)
                    return
                new_view = get_view(not showing_server)
                await interaction.response.edit_message(view=new_view)
            
            btn.callback = btn_callback
            
            media_items = [MediaGalleryItem(media=url)]
            if not showing_server and user.avatar_decoration:
                media_items.append(MediaGalleryItem(media=user.avatar_decoration.url))

            items = [
                TextDisplay(f"**{user.display_name}'s {title_type} Avatar**"),
                Separator(visible=True, spacing=SeparatorSpacing.small),
                MediaGallery(*media_items),
                Separator(visible=True, spacing=SeparatorSpacing.small),
                TextDisplay(
                    f"User: {user.mention} ({user.id})" + (
                        f" | Decoration: [View]({user.avatar_decoration.url})" if not showing_server and user.avatar_decoration else ""
                    )
                ),
            ]
            
            if has_server_avatar:
                items.append(ActionRow(btn))
            
            class View(LayoutView):
                container = Container(*items, accent_color=user.color or Color(0x5865F2))
            
            return View()

        await ctx.send(view=get_view(has_server_avatar))

    @command(
        name="banner",
        aliases=["bnr"],
        description="show someone's banner",
        extras={'example': ',banner @user'}
    )
    @cooldown(1, 10, BucketType.user)
    async def banner_standalone(self, ctx, user: Optional[Union[Member, User]] = None):
        user = user or ctx.author
        
        try:
            fetched_user = await self.bot.fetch_user(user.id)
        except:
            fetched_user = user
        
        server_banner_obj = getattr(user, 'guild_banner', None)
        user_banner = fetched_user.banner.url if fetched_user.banner else None
        server_banner = server_banner_obj.url if server_banner_obj else None
        has_user_banner = user_banner is not None
        has_server_banner = server_banner is not None
        
        if not has_user_banner and not has_server_banner:
            class NoBannerView(LayoutView):
                container = Container(
                    TextDisplay(f"**{user.display_name}'s Banner**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    TextDisplay("This user has no banner set"),
                    accent_color=Colour(0x808080)
                )
            await ctx.send(view=NoBannerView())
            return
            
        def get_view(showing_server: bool):
            url = server_banner if showing_server else user_banner
            title_type = "Server" if showing_server else "User"
            
            btn = Button(
                label=f"Show {'User' if showing_server else 'Server'}",
                style=ButtonStyle.primary,
                emoji=PartialEmoji.from_str('📷')
            )
            
            async def btn_callback(interaction: Interaction):
                if interaction.user.id != ctx.author.id:
                    await interaction.response.send_message("This button is not for you!", ephemeral=True)
                    return
                new_view = get_view(not showing_server)
                await interaction.response.edit_message(view=new_view)
            
            btn.callback = btn_callback
            
            items = [
                TextDisplay(f"**{user.display_name}'s {title_type} Banner**"),
                Separator(visible=True, spacing=SeparatorSpacing.small),
            ]
            
            if url:
                 items.append(MediaGallery(MediaGalleryItem(media=url)))
            else:
                 items.append(TextDisplay(f"No {title_type.lower()} banner set"))

            items.append(Separator(visible=True, spacing=SeparatorSpacing.small))
            
            if has_user_banner and has_server_banner:
                items.append(ActionRow(btn))
            
            class View(LayoutView):
                container = Container(*items, accent_color=user.color or Color(0x5865F2))
            
            return View()

        initial_server = isinstance(user, Member) and has_server_banner
        await ctx.send(view=get_view(initial_server))

    @command(
        name="profile",
        aliases=["whois", "userinfo", "ui"],
        description="see info about a user",
        extras={'example': ',profile @user'}
    )
    @cooldown(1, 10, BucketType.user)
    async def profile_standalone(self, ctx, user: Optional[Union[Member, User]] = None):
        target = user or ctx.author
        is_member = isinstance(target, Member)
        
        fetched_user = target
        if not getattr(target, 'banner', None):
            try:
                fetched_user = await self.bot.fetch_user(target.id)
            except NotFound:
                pass
        
        info_emoji = 'ℹ️'
        member_emoji = '👥'
        time_emoji = '⏱️'
        bot_emoji = '🤖'
        settings_emoji = '⚙️'
        stats_emoji = '📊'
        online_emoji = '🟢'
        offline_emoji = '🔘'
        
        key_perms = []
        if is_member:
            if target.guild_permissions.administrator:
                key_perms.append("Administrator")
            else:
                perms_to_check = [
                    ("manage_guild", "Manage Server"),
                    ("manage_roles", "Manage Roles"),
                    ("manage_channels", "Manage Channels"),
                    ("manage_messages", "Manage Messages"),
                    ("kick_members", "Kick Members"),
                    ("ban_members", "Ban Members"),
                    ("moderate_members", "Timeout Members")
                ]
                for perm, display in perms_to_check:
                    if getattr(target.guild_permissions, perm):
                        key_perms.append(display)

        perms_text = ", ".join(key_perms) if key_perms else "None"
        roles_text = " ".join(
            [
                r.mention for r in sorted(
                    target.roles[1:],
                    key=lambda r: r.position,
                    reverse=True
                )[:10]
            ]
        ) if (is_member and len(target.roles) > 1) else "None"

        server_join = f"<t:{int(target.joined_at.timestamp())}:R>" if is_member and target.joined_at else "N/A"
        discord_join = f"<t:{int(target.created_at.timestamp())}:R>"

        status_text = "Offline"
        if is_member and target.status:
            status_text = str(target.status).title()
        status_icon = online_emoji if status_text != "Offline" else offline_emoji
        
        type_str = f"{bot_emoji} Bot" if target.bot else f"{member_emoji} Human"
        pg = getattr(target, 'primary_guild', None)
        
        container_items = []
        
        if target.display_avatar:
            container_items.append(Section(
                TextDisplay(content=f"{info_emoji} **user info for {target.name}**"),
                TextDisplay(content=(
                    f"> {stats_emoji} **id:** `{target.id}`\n"
                    f"> {time_emoji} **discord join:** {discord_join}\n"
                    f"> {time_emoji} **server join:** {server_join}\n"
                    f"> {status_icon} **status:** {status_text} | {type_str}"
                )),
                accessory=Thumbnail(media=target.display_avatar.url)
            ))
        else:
            container_items.extend([
                TextDisplay(content=f"{info_emoji} **user info for {target.name}**"),
                TextDisplay(content=(
                    f"> {stats_emoji} **id:** `{target.id}`\n"
                    f"> {time_emoji} **discord join:** {discord_join}\n"
                    f"> {time_emoji} **server join:** {server_join}\n"
                    f"> {status_icon} **status:** {status_text} | {type_str}"
                ))
            ])

        roles_content = ""
        if pg and pg.tag:
            badge_emoji = '🏷️'
            roles_content += f"> {badge_emoji} **server tag:** `{pg.tag}`\n"
            
        if target.avatar_decoration:
            deco_emoji = '✨'
            roles_content += f"> {deco_emoji} **decoration:** [View]({target.avatar_decoration.url})\n"

        if is_member and len(target.roles) > 1:
            roles_content += f"\n**{settings_emoji} Roles [{len(target.roles)-1}]**\n> {roles_text}"

        container_items.append(Separator(visible=True, spacing=SeparatorSpacing.small))

        if pg and pg.badge:
            container_items.append(Section(
                TextDisplay(content=roles_content if roles_content else "No additional server info."),
                accessory=Thumbnail(media=pg.badge.url)
            ))
        else:
            container_items.append(
                TextDisplay(content=roles_content if roles_content else "No additional server info.")
            )

        media_items = []
        if target.avatar_decoration:
            media_items.append(MediaGalleryItem(media=target.avatar_decoration.url))

        buttons = [
            Button(url=target.display_avatar.url if target.display_avatar else "https://discord.com", style=ButtonStyle.link, label="user avatar", disabled=not bool(target.display_avatar)),
            Button(url=target.guild_avatar.url if is_member and target.guild_avatar else "https://discord.com", style=ButtonStyle.link, label="server avatar", disabled=not (is_member and target.guild_avatar)),
            Button(url=fetched_user.banner.url if fetched_user.banner else "https://discord.com", style=ButtonStyle.link, label="user banner", disabled=not bool(fetched_user.banner))
        ]

        if target.avatar_decoration:
            buttons.append(Button(url=target.avatar_decoration.url, style=ButtonStyle.link, label="decoration"))
        if pg and pg.badge:
            buttons.append(Button(url=pg.badge.url, style=ButtonStyle.link, label="server tag icon"))
        
        if ctx.guild and ctx.guild.banner:
            buttons.append(Button(url=ctx.guild.banner.url, style=ButtonStyle.link, label="server banner"))
        else:
            buttons.append(Button(url="https://discord.com", style=ButtonStyle.link, label="server banner", disabled=True))

        if media_items:
            container_items.append(Separator(visible=True, spacing=SeparatorSpacing.small))
            container_items.append(MediaGallery(*media_items))

        container_items.extend([
            Separator(visible=True, spacing=SeparatorSpacing.small),
            ActionRow(*buttons[:5]),
        ])
        
        if len(buttons) > 5:
            container_items.append(ActionRow(*buttons[5:]))

        container_items.append(TextDisplay(content=f"**discord perms:** {perms_text}"))

        class ProfileView(LayoutView):
            container = Container(*container_items, accent_color=target.color if is_member and target.color else Colour(0x5865F2))
            
        await ctx.send(view=ProfileView())

    @command(
        name="serverinfo",
        aliases=["si", "guildinfo", "guild"],
        description="see info about this server",
        extras={'example': ',serverinfo'}
    )
    @cooldown(1, 10, BucketType.user)
    async def serverinfo_standalone(self, ctx):
        guild = ctx.guild
        if not guild:
            await ctx.send("This command can only be used in a server.", ephemeral=True)
            return
            
        info_emoji = 'ℹ️'
        member_emoji = '👥'
        channel_emoji = '📺'
        boost_emoji = '🚀'
        stats_emoji = '📊'
        owner_emoji = '👑'
        time_emoji = '⏱️'
        bot_emoji = '🤖'
        role_emoji = '⚙️'
        
        owner_text = guild.owner.mention if guild.owner else 'Unknown'
        created_at = f"<t:{int(guild.created_at.timestamp())}:R>"
        bots = len([m for m in guild.members if m.bot])
        humans = guild.member_count - bots
        
        details_content = (
            f"> {owner_emoji} **owner:** {owner_text}\n"
            f"> {time_emoji} **created:** {created_at}\n"
            f"> {stats_emoji} **id:** `{guild.id}`\n\n"
            f"**{member_emoji} Members [{guild.member_count}]**\n"
            f"> Humans: {humans} | {bot_emoji} Bots: {bots}\n\n"
            f"**{channel_emoji} Channels [{len(guild.channels)}]**\n"
            f"> Text: {len(guild.text_channels)} | Voice: {len(guild.voice_channels)}\n"
            f"> Categories: {len(guild.categories)}\n\n"
            f"**{role_emoji} Server Extras**\n"
            f"> Roles: {len(guild.roles)} | Emojis: {len(guild.emojis)}\n"
            f"> {boost_emoji} **Boosts:** {guild.premium_subscription_count} (Level {guild.premium_tier})"
        )
        
        feats = [f.replace("_", " ").title() for f in guild.features]
        features_text = ", ".join(feats) if feats else "None"

        buttons = [
            Button(url=guild.icon.url if guild.icon else "https://discord.com", style=ButtonStyle.link, label="server avatar", disabled=not bool(guild.icon)),
            Button(url=guild.banner.url if guild.banner else "https://discord.com", style=ButtonStyle.link, label="server banner", disabled=not bool(guild.banner)),
            Button(url=guild.splash.url if guild.splash else "https://discord.com", style=ButtonStyle.link, label="server splash", disabled=not bool(guild.splash))
        ]

        container_items = []
        if guild.icon:
            container_items.append(Section(
                TextDisplay(content=f"{info_emoji} **server info for {guild.name}**"),
                TextDisplay(content=details_content),
                accessory=Thumbnail(media=guild.icon.url)
            ))
        else:
            container_items.extend([
                TextDisplay(content=f"{info_emoji} **server info for {guild.name}**"),
                TextDisplay(content=details_content)
            ])

        container_items.extend([
            Separator(visible=True, spacing=SeparatorSpacing.small),
            ActionRow(*buttons),
            Separator(visible=True, spacing=SeparatorSpacing.small),
            TextDisplay(content=f"**server features:** {features_text}"),
        ])

        class ServerInfoView(LayoutView):
            container = Container(*container_items, accent_color=Colour(0x5865F2))
            
        await ctx.send(view=ServerInfoView())

    @command(
        name="servericon",
        aliases=["sicon", "guildicon", "icon"],
        description="show the server icon",
        extras={'example': ',servericon'}
    )
    @cooldown(1, 10, BucketType.user)
    async def servericon_standalone(self, ctx):
        guild = ctx.guild
        if not guild:
            await ctx.send("...", ephemeral=True)
            return

        if not guild.icon:
            class NoIconView(LayoutView):
                container = Container(
                    TextDisplay(content=f"**{guild.name} Server Icon**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    TextDisplay(content="This server has no icon set"),
                    accent_color=Colour(0x808080)
                )
            await ctx.send(view=NoIconView())
        else:
            class IconView(LayoutView):
                container = Container(
                    TextDisplay(content=f"**{guild.name} Server Icon**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    MediaGallery(MediaGalleryItem(media=guild.icon.url)),
                    accent_color=Colour(0x5865F2)
                )
            await ctx.send(view=IconView())

    @command(
        name="serverbanner",
        aliases=["sbanner", "guildbanner"],
        description="show the server banner",
        extras={'example': ',serverbanner'}
    )
    @cooldown(1, 10, BucketType.user)
    async def serverbanner_standalone(self, ctx):
        guild = ctx.guild
        if not guild:
            await ctx.send("This command can only be used in a server.", ephemeral=True)
            return

        if not guild.banner:
            class NoBannerView(LayoutView):
                container = Container(
                    TextDisplay(content=f"**{guild.name} Server Banner**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    TextDisplay(content="This server has no banner set"),
                    accent_color=Colour(0x808080)
                )
            await ctx.send(view=NoBannerView())
        else:
            class BannerView(LayoutView):
                container = Container(
                    TextDisplay(content=f"**{guild.name} Server Banner**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    MediaGallery(MediaGalleryItem(media=guild.banner.url)),
                    accent_color=Colour(0x5865F2)
                )
            await ctx.send(view=BannerView())

    @command(
        name="serversplash",
        aliases=["ssplash", "guildsplash", "splash"],
        description="show the server splash",
        extras={'example': ',serversplash'}
    )
    @cooldown(1, 10, BucketType.user)
    async def serversplash_standalone(self, ctx):
        guild = ctx.guild
        if not guild:
            await ctx.send("This command can only be used in a server.", ephemeral=True)
            return

        if not guild.splash:
            class NoSplashView(LayoutView):
                container = Container(
                    TextDisplay(content=f"**{guild.name} Server Splash**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    TextDisplay(content="This server has no splash set"),
                    accent_color=Colour(0x808080)
                )
            await ctx.send(view=NoSplashView())
        else:
            class SplashView(LayoutView):
                container = Container(
                    TextDisplay(content=f"**{guild.name} Server Splash**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    MediaGallery(MediaGalleryItem(media=guild.splash.url)),
                    accent_color=Colour(0x5865F2)
                )
            await ctx.send(view=SplashView())
    
    @get_group.command(
        name="servertag",
        description="view someone's server tag name & icon",
        extras={'example': ',get servertag @user'}
    )
    @describe(user="User whose server tag to show (defaults to yourself)")
    @cooldown(1, 10, BucketType.user)
    async def get_servertag(self, ctx, user: Optional[Union[Member, User]] = None):
        if isinstance(user, User) and not isinstance(user, Member):
            try:
                member = await ctx.guild.fetch_member(user.id)
                if member: user = member
            except:
                pass
            
        user = user or ctx.author
        pg = getattr(user, 'primary_guild', None)
        
        if not pg:
            class NoTagView(LayoutView):
                container = Container(
                    TextDisplay(f"**server tag of {user.mention}**"),
                    Separator(visible=True, spacing=SeparatorSpacing.small),
                    TextDisplay("this person doesn't have a server tag enabled"),
                    accent_color=Colour(0x808080)
                )
            await ctx.send(view=NoTagView())
            return

        tag_text = pg.tag if pg.tag else "N/A"
        icon_url = pg.badge.url if pg.badge else None
        
        container_items = []
        header = f"**{user.mention}'s server tag**"
        body = f"Tag: **{tag_text}**"
        if pg.id:
            body += f"\nGuild ID: `{pg.id}`"

        if icon_url:
            container_items.append(Section(
                TextDisplay(header),
                TextDisplay(body),
                accessory=Thumbnail(media=icon_url)
            ))
        else:
            container_items.extend([
                TextDisplay(header),
                Separator(visible=True, spacing=SeparatorSpacing.small),
                TextDisplay(body)
            ])
            
        class TagView(LayoutView):
            container = Container(*container_items, accent_color=Colour(0x5865F2))
        await ctx.send(view=TagView())

    @command(
        name="servertag",
        aliases=["guildtag", "primaryguild"],
        description="view someone's server tag name & icon",
        extras={'example': ',servertag @user'}
    )
    @cooldown(1, 10, BucketType.user)
    async def servertag_standalone(self, ctx, user: Optional[Union[Member, User]] = None):
        await self.get_servertag(ctx, user)

    @command(
        name="botinfo",
        aliases=["bi"],
        description="show bot information",
        extras={'example': ',botinfo'}
    )
    @cooldown(1, 10, BucketType.user)
    async def botinfo(self, ctx):
        usericon = self.bot.user.display_avatar.url if self.bot.user.display_avatar else None
        ram_mb = psutil.virtual_memory().used / (1024 * 1024)
        cpu_percent = psutil.cpu_percent(interval=0.1)
        guild_count = len(self.bot.guilds)
        user_count = len(self.bot.users)
        all_cmd_names = set()
        for cmd in self.bot.commands:
            all_cmd_names.add(cmd.name)
            if hasattr(cmd, 'commands'):
                for subcmd in cmd.commands:
                    all_cmd_names.add(subcmd.name)
        for cmd in self.bot.tree.get_commands():
            all_cmd_names.add(cmd.name)
        total_commands = len(all_cmd_names)

        class Components(LayoutView):
            container = Container(
                Section(
                    TextDisplay(content=f"**votox information**\n\ngeneral information\n> ram: {ram_mb:.2f} mb\n> cpu {cpu_percent}%\n> guilds `{guild_count}`\n> users `{user_count}`\n\ncommands\n> total commands `{total_commands}`\ndeveloped by [voby7](https://discord.com/users/1442735423544627211)\n[support](https://discord.gg/YWG5ryEZGS) | [invite](https://ptb.discord.com/oauth2/authorize?client_id=1447869784937988201) | [top.gg](https://top.gg/bot/1447869784937988201?)"),
                    accessory=Thumbnail(
                        media=usericon,
                    ),
                ),
            )
        await ctx.send(view=Components())

async def setup(bot):
    await bot.add_cog(Get(bot))
