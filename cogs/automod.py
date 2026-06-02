

import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import re
import logging
from pathlib import Path
from typing import Optional, Union, List, Dict, Any

logger = logging.getLogger("VOTOX")

class AutoMod(commands.Cog):
    """
    High-performance Auto-Moderation system using Native Discord API and Custom Checks.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db_path = Path(__file__).parent.parent / "database" / "votox.db"
        
        # Rule Name Constants
        self.RULE_WORDS = "VOTOX: Keywords"
        self.RULE_LINKS = "VOTOX: Link Protection"
        self.RULE_SPAM = "VOTOX: Anti-Spam"
        self.RULE_MENTIONS = "VOTOX: Mention Protection"

    def _get_db(self) -> aiosqlite.Connection:
        return aiosqlite.connect(self.db_path)

    async def cog_load(self):
        """Initialize database tables for custom checks."""
        async with self._get_db() as db:
            await db.execute('''
                CREATE TABLE IF NOT EXISTS automod_settings (
                    guild_id INTEGER PRIMARY KEY,
                    emoji_limit INTEGER DEFAULT 0,
                    line_limit INTEGER DEFAULT 0,
                    log_channel_id INTEGER DEFAULT NULL
                )
            ''')
            await db.commit()

    # ========================= HELPER METHODS =========================

    def _create_embed(self, title: str, description: str = None, color: discord.Color = discord.Color.blurple()) -> discord.Embed:
        embed = discord.Embed(title=title, description=description, color=color, timestamp=discord.utils.utcnow())
        embed.set_footer(text="VOTOX AutoMod Enforcement", icon_url=self.bot.user.display_avatar.url)
        return embed

    async def _get_native_rule(self, guild: discord.Guild, name: str) -> Optional[discord.AutoModRule]:
        """Fetch a native AutoMod rule by name."""
        try:
            rules = await guild.fetch_automod_rules()
            return discord.utils.get(rules, name=name)
        except discord.Forbidden:
            return None

    async def _get_custom_settings(self, guild_id: int) -> Dict[str, Any]:
        """Fetch custom settings from the database."""
        async with self._get_db() as db:
            cursor = await db.execute("SELECT emoji_limit, line_limit, log_channel_id FROM automod_settings WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
            if row:
                return {"emoji_limit": row[0], "line_limit": row[1], "log_channel_id": row[2]}
            return {"emoji_limit": 0, "line_limit": 0, "log_channel_id": None}

    async def _update_custom_setting(self, guild_id: int, column: str, value: Any):
        """Update a custom setting in the database."""
        async with self._get_db() as db:
            await db.execute(f"INSERT INTO automod_settings (guild_id, {column}) VALUES (?, ?) ON CONFLICT(guild_id) DO UPDATE SET {column} = ?", (guild_id, value, value))
            await db.commit()

    # ========================= COMMANDS =========================

    @commands.group(name="automod", invoke_without_command=True)
    @commands.has_permissions(manage_guild=True)
    @commands.guild_only()
    async def automod(self, ctx: commands.Context):
        """Displays the AutoMod dashboard status for the server."""
        rules = await ctx.guild.fetch_automod_rules()
        custom = await self._get_custom_settings(ctx.guild.id)

        def check_native(name):
            rule = discord.utils.get(rules, name=name)
            return "✅ Enabled" if rule and rule.enabled else "❌ Disabled"

        embed = self._create_embed("🛡️ AutoMod Dashboard", f"Status of VOTOX moderation engines for **{ctx.guild.name}**.")
        
        embed.add_field(name="Native Filters (Discord API)", value=(
            f"**Keywords:** {check_native(self.RULE_WORDS)}\n"
            f"**Links:** {check_native(self.RULE_LINKS)}\n"
            f"**Spam Engine:** {check_native(self.RULE_SPAM)}\n"
            f"**Mass Mentions:** {check_native(self.RULE_MENTIONS)}"
        ), inline=False)

        embed.add_field(name="Custom Filters (VOTOX Engine)", value=(
            f"**Emoji Spam:** {'✅ Limit: ' + str(custom['emoji_limit']) if custom['emoji_limit'] > 0 else '❌ Disabled'}\n"
            f"**Wall of Text:** {'✅ Limit: ' + str(custom['line_limit']) + ' lines' if custom['line_limit'] > 0 else '❌ Disabled'}"
        ), inline=False)

        await ctx.send(embed=embed)

    @automod.command(name="words")
    @commands.has_permissions(manage_guild=True)
    async def automod_words(self, ctx: commands.Context, action: str, *, word: Optional[str] = None):
        """Manage the native keyword filter. [add/remove/list]"""
        action = action.lower()
        rule = await self._get_native_rule(ctx.guild, self.RULE_WORDS)

        if action == "list":
            keywords = rule.trigger.keyword_filter if rule else []
            return await ctx.send(embed=self._create_embed("📝 Blocked Keywords", ", ".join([f"`{w}`" for w in keywords]) or "No keywords blocked."))

        if not word:
            return await ctx.send(embed=self._create_embed("❌ Error", "Please provide a word to add or remove.", discord.Color.red()))

        try:
            if action == "add":
                if not rule:
                    await ctx.guild.create_automod_rule(
                        name=self.RULE_WORDS,
                        event_type=discord.AutoModRuleEventType.message_send,
                        trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.keyword, keyword_filter=[word]),
                        actions=[discord.AutoModRuleAction(type=discord.AutoModRuleActionType.block_message)],
                        enabled=True,
                        reason="VOTOX AutoMod Initialization"
                    )
                else:
                    current_filters = list(rule.trigger.keyword_filter)
                    if word not in current_filters:
                        current_filters.append(word)
                        await rule.edit(trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.keyword, keyword_filter=current_filters))
                
                await ctx.send(embed=self._create_embed("✅ Success", f"Added `{word}` to blocked keywords."))

            elif action == "remove":
                if not rule or word not in rule.trigger.keyword_filter:
                    return await ctx.send(embed=self._create_embed("❌ Error", "That word is not in the blocklist.", discord.Color.red()))
                
                current_filters = list(rule.trigger.keyword_filter)
                current_filters.remove(word)
                await rule.edit(trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.keyword, keyword_filter=current_filters))
                await ctx.send(embed=self._create_embed("✅ Success", f"Removed `{word}` from blocked keywords."))

        except discord.Forbidden:
            await ctx.send(embed=self._create_embed("❌ Permission Error", "I lack permissions to manage AutoMod rules.", discord.Color.red()))

    @automod.command(name="antispam")
    @commands.has_permissions(manage_guild=True)
    async def automod_antispam(self, ctx: commands.Context, toggle: str):
        """Toggles Discord's native spam trigger. [on/off]"""
        toggle = toggle.lower()
        rule = await self._get_native_rule(ctx.guild, self.RULE_SPAM)

        try:
            if toggle == "on":
                if not rule:
                    await ctx.guild.create_automod_rule(
                        name=self.RULE_SPAM,
                        event_type=discord.AutoModRuleEventType.message_send,
                        trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.spam),
                        actions=[discord.AutoModRuleAction(type=discord.AutoModRuleActionType.block_message)],
                        enabled=True
                    )
                else:
                    await rule.edit(enabled=True)
                await ctx.send(embed=self._create_success_embed("Anti-Spam Enabled", "Native spam protection is now active."))
            else:
                if rule:
                    await rule.edit(enabled=False)
                await ctx.send(embed=self._create_success_embed("Anti-Spam Disabled", "Native spam protection has been deactivated."))
        except discord.Forbidden:
            await ctx.send(embed=self._create_error_embed("Permission Denied", "Ensure I have Manage Server permissions."))

    @automod.command(name="link")
    @commands.has_permissions(manage_guild=True)
    async def automod_link(self, ctx: commands.Context, toggle: str):
        """Toggles blocking of all hyperlinks using native wildcards. [on/off]"""
        toggle = toggle.lower()
        rule = await self._get_native_rule(ctx.guild, self.RULE_LINKS)
        link_patterns = ["*http://*", "*https://*"]

        try:
            if toggle == "on":
                if not rule:
                    await ctx.guild.create_automod_rule(
                        name=self.RULE_LINKS,
                        event_type=discord.AutoModRuleEventType.message_send,
                        trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.keyword, keyword_filter=link_patterns),
                        actions=[discord.AutoModRuleAction(type=discord.AutoModRuleActionType.block_message)],
                        enabled=True
                    )
                else:
                    await rule.edit(enabled=True)
                await ctx.send(embed=self._create_success_embed("Link Protection Enabled", "All hyperlinks are now blocked via native AutoMod."))
            else:
                if rule:
                    await rule.edit(enabled=False)
                await ctx.send(embed=self._create_success_embed("Link Protection Disabled", "Links are now allowed."))
        except discord.Forbidden:
            await ctx.send(embed=self._create_error_embed("Permission Denied", "I need Manage Server permissions to configure native AutoMod."))

    @automod.command(name="emojispam")
    @commands.has_permissions(manage_guild=True)
    async def automod_emojispam(self, ctx: commands.Context, limit: str):
        """Sets the max allowed emojis in a message. [limit/off]"""
        if limit.lower() == "off":
            await self._update_custom_setting(ctx.guild.id, "emoji_limit", 0)
            return await ctx.send(embed=self._create_success_embed("Emoji Protection Disabled", "No limit on emojis will be enforced."))

        if not limit.isdigit():
            return await ctx.send(embed=self._create_error_embed("Invalid Input", "Please provide a valid number for the limit."))

        val = int(limit)
        await self._update_custom_setting(ctx.guild.id, "emoji_limit", val)
        await ctx.send(embed=self._create_success_embed("Emoji Protection Updated", f"Messages with more than **{val}** emojis will be deleted."))

    @automod.command(name="walloftext")
    @commands.has_permissions(manage_guild=True)
    async def automod_walloftext(self, ctx: commands.Context, lines: str):
        """Sets the max allowed line breaks in a message. [lines/off]"""
        if lines.lower() == "off":
            await self._update_custom_setting(ctx.guild.id, "line_limit", 0)
            return await ctx.send(embed=self._create_success_embed("Wall of Text Protection Disabled", "No limit on line breaks will be enforced."))

        if not lines.isdigit():
            return await ctx.send(embed=self._create_error_embed("Invalid Input", "Please provide a valid number for the lines limit."))

        val = int(lines)
        await self._update_custom_setting(ctx.guild.id, "line_limit", val)
        await ctx.send(embed=self._create_success_embed("Wall of Text Updated", f"Messages exceeding **{val}** lines will be removed."))

    @automod.command(name="massmention")
    @commands.has_permissions(manage_guild=True)
    async def automod_massmention(self, ctx: commands.Context, limit: str):
        """Configures native mass mention protection. [limit/off]"""
        rule = await self._get_native_rule(ctx.guild, self.RULE_MENTIONS)
        
        if limit.lower() == "off":
            if rule:
                await rule.edit(enabled=False)
            return await ctx.send(embed=self._create_success_embed("Mention Protection Disabled", "Mass mentions are no longer being filtered natively."))

        if not limit.isdigit():
            return await ctx.send(embed=self._create_error_embed("Invalid Input", "Provide a numeric limit (e.g., 5)."))

        val = int(limit)
        if val < 3 or val > 50:
            return await ctx.send(embed=self._create_error_embed("Range Error", "Mention limit must be between 3 and 50."))

        try:
            if not rule:
                await ctx.guild.create_automod_rule(
                    name=self.RULE_MENTIONS,
                    event_type=discord.AutoModRuleEventType.message_send,
                    trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.mention_spam, mention_total_limit=val),
                    actions=[discord.AutoModRuleAction(type=discord.AutoModRuleActionType.block_message)],
                    enabled=True
                )
            else:
                await rule.edit(trigger=discord.AutoModTrigger(type=discord.AutoModRuleTriggerType.mention_spam, mention_total_limit=val), enabled=True)
            
            await ctx.send(embed=self._create_success_embed("Mention Protection Active", f"Native AutoMod will block messages with more than **{val}** mentions."))
        except discord.Forbidden:
            await ctx.send(embed=self._create_error_embed("Permission Denied", "Missing Manage Server permissions."))

    # ========================= CUSTOM LOGGING HELPERS =========================

    def _create_success_embed(self, title: str, description: str) -> discord.Embed:
        return self._create_embed(f"✅ {title}", description, discord.Color.green())

    def _create_error_embed(self, title: str, description: str) -> discord.Embed:
        return self._create_embed(f"❌ {title}", description, discord.Color.red())

    async def _log_violation(self, message: discord.Message, trigger: str, details: str):
        """Log custom violations to the designated log channel if configured."""
        settings = await self._get_custom_settings(message.guild.id)
        log_id = settings.get("log_channel_id")
        
        if not log_id:
            return

        channel = message.guild.get_channel(log_id)
        if not channel:
            return

        embed = self._create_embed(f"🛡️ AutoMod Violation: {trigger}", color=discord.Color.orange())
        embed.add_field(name="User", value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
        embed.add_field(name="Channel", value=message.channel.mention, inline=True)
        embed.add_field(name="Trigger Info", value=details, inline=False)
        
        content_preview = message.content[:500] + "..." if len(message.content) > 500 else message.content
        embed.add_field(name="Content Preview", value=f"```\n{content_preview}\n```", inline=False)

        try:
            await channel.send(embed=embed)
        except:
            pass

    # ========================= EVENT LISTENERS =========================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """Custom checks for Emoji Spam and Wall of Text."""
        if message.author.bot or not message.guild:
            return

        # Bypass for staff
        if message.author.guild_permissions.manage_messages or message.author.guild_permissions.administrator:
            return

        settings = await self._get_custom_settings(message.guild.id)
        
        # 1. Check Emoji Spam
        if settings["emoji_limit"] > 0:
            # Regex to match Unicode, custom, and animated emojis
            unicode_emoji_regex = r'[\U00010000-\U0010ffff]'
            custom_emoji_regex = r'<a?:\w+:\d+>'
            
            unicode_emojis = re.findall(unicode_emoji_regex, message.content)
            custom_emojis = re.findall(custom_emoji_regex, message.content)
            total_emojis = len(unicode_emojis) + len(custom_emojis)

            if total_emojis > settings["emoji_limit"]:
                try:
                    await message.delete()
                    alert = await message.channel.send(
                        embed=self._create_embed(
                            "🚫 Message Removed", 
                            f"{message.author.mention}, your message contained too many emojis (**{total_emojis}**). Limit: **{settings['emoji_limit']}**.", 
                            discord.Color.red()
                        ), 
                        delete_after=5.0
                    )
                    await self._log_violation(message, "Emoji Spam", f"Emojis: {total_emojis} (Limit: {settings['emoji_limit']})")
                    return # Stop further checks if deleted
                except discord.Forbidden:
                    pass

        # 2. Check Wall of Text (Newlines)
        if settings["line_limit"] > 0:
            lines = message.content.count('\n') + 1
            if lines > settings["line_limit"]:
                try:
                    await message.delete()
                    await message.channel.send(
                        embed=self._create_embed(
                            "🚫 Message Removed", 
                            f"{message.author.mention}, your message is too long (**{lines}** lines). Max allowed: **{settings['line_limit']}** lines.", 
                            discord.Color.red()
                        ), 
                        delete_after=5.0
                    )
                    await self._log_violation(message, "Wall of Text", f"Lines: {lines} (Limit: {settings['line_limit']})")
                except discord.Forbidden:
                    pass

async def setup(bot: commands.Bot):
    await bot.add_cog(AutoMod(bot))