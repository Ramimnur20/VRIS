import discord
import re
from typing import Tuple, Optional, Dict, Any, List

class EmbedParserException(Exception):
    """Custom exception for embed parsing errors."""
    pass

def parse_sub_attributes(content: str, separator: str = ':') -> Dict[str, str]:
    attrs = {}
    parts = content.split('&&')
    for p in parts:
        if separator in p:
            key_val = p.split(separator, 1)
            attrs[key_val[0].strip().lower()] = key_val[1].strip()
    return attrs

def _parse_attributes(content: str, separator: str = ':', attr_sep: str = '&&') -> Dict[str, str]:
    """Parses attributes while respecting nested braces."""
    attrs = {}
    parts = []
    start = 0
    bc = 0
    for idx, char in enumerate(content):
        if char == '{': bc += 1
        elif char == '}': bc -= 1
        if bc == 0 and content[idx:idx+len(attr_sep)] == attr_sep:
            parts.append(content[start:idx])
            start = idx + len(attr_sep)
    parts.append(content[start:])
    for p in parts:
        if separator in p:
            k, v = p.split(separator, 1)
            attrs[k.strip().lower()] = v.strip()
    return attrs

def _extract_top_level_tags(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """Scans text for top-level {tag} or {tag: content} blocks, supporting nested braces."""
    tags = []
    cleaned_text = ""
    last_pos = 0
    i = 0
    while i < len(text):
        if text[i] == '{':
            cleaned_text += text[last_pos:i]
            start = i
            brace_count = 1
            i += 1
            while i < len(text) and brace_count > 0:
                if text[i] == '{': brace_count += 1
                elif text[i] == '}': brace_count -= 1
                i += 1
            if brace_count == 0:
                tag_full = text[start+1:i-1].strip()
                if ':' in tag_full:
                    name, val = tag_full.split(':', 1)
                    tags.append((name.strip().lower(), val.strip()))
                else:
                    tags.append((tag_full.lower(), ""))
                last_pos = i
            else:
                i = start + 1
        else:
            i += 1
    cleaned_text += text[last_pos:]
    return cleaned_text.strip(), tags

def parse_embed(text: str) -> Tuple[str, Optional[discord.Embed], Optional[discord.ui.View]]:
    try:
        content_text, tags = _extract_top_level_tags(text)

        # Strictly Classic Mode: requires {embed}
        if not any(t[0] == 'embed' for t in tags):
            return text, None, None

        embed = discord.Embed()
        view = None
        explicit_content = None

        style_map = {
            "primary": discord.ButtonStyle.primary,
            "secondary": discord.ButtonStyle.secondary,
            "success": discord.ButtonStyle.success,
            "danger": discord.ButtonStyle.danger,
            "link": discord.ButtonStyle.link
        }

        for tag, val in tags:
            if tag == "content":
                explicit_content = val
            elif tag == "title":
                embed.title = val
            elif tag == "description":
                embed.description = val
            elif tag == "timestamp":
                embed.timestamp = discord.utils.utcnow()
            elif tag == "color":
                hex_val = val.lstrip('#')
                try:
                    embed.color = discord.Color(int(hex_val, 16))
                except ValueError:
                    try:
                        embed.color = discord.Color(int(val))
                    except:
                        raise EmbedParserException(f"Invalid color format: {val}")
            elif tag == "author":
                attrs = parse_sub_attributes(val)
                if 'name' not in attrs: raise EmbedParserException("Author requires 'name:'")
                embed.set_author(name=attrs['name'], icon_url=attrs.get('icon'), url=attrs.get('url'))
            elif tag == "thumbnail": embed.set_thumbnail(url=val)
            elif tag == "image": embed.set_image(url=val)
            elif tag == "footer":
                attrs = parse_sub_attributes(val)
                if 'text' not in attrs: raise EmbedParserException("Footer requires 'text:'")
                embed.set_footer(text=attrs['text'], icon_url=attrs.get('icon'))
            elif tag == "field":
                attrs = parse_sub_attributes(val)
                if 'name' not in attrs or 'value' not in attrs:
                    raise EmbedParserException("Field requires 'name:' and 'value:'")
                embed.add_field(name=attrs['name'], value=attrs['value'], inline=attrs.get('inline', 'false').lower() == 'true')
            elif tag == "buttons":
                if not view: view = discord.ui.View()
            elif tag == "button":
                if not view: view = discord.ui.View()
                view.add_item(_parse_button(val))
        
        final_content = explicit_content if explicit_content is not None else content_text
        return final_content, embed, view
    except Exception as e:
        if isinstance(e, EmbedParserException): raise e
        raise EmbedParserException(f"Critical parsing error: {e}")

def _parse_button(val: str) -> discord.ui.Button:
    attrs = _parse_attributes(val, separator='=', attr_sep='&&')
    style_map = {
        "primary": discord.ButtonStyle.primary, 
        "secondary": discord.ButtonStyle.secondary, 
        "success": discord.ButtonStyle.success, 
        "danger": discord.ButtonStyle.danger, 
        "link": discord.ButtonStyle.link
    }
    
    style = style_map.get(attrs.get('style', 'secondary').lower(), discord.ButtonStyle.secondary)
    label = attrs.get('label', 'Button')
    url = attrs.get('url') if style == discord.ButtonStyle.link else None
    row = min(max(int(attrs.get('row', 0)), 0), 4)
    action_raw = attrs.get('action')

    btn = discord.ui.Button(style=style, label=label, url=url, row=row)
    if style != discord.ButtonStyle.link:
        if action_raw:
            msg = action_raw.strip('{}').strip()
            async def callback(interaction: discord.Interaction):
                await interaction.response.send_message(msg, ephemeral=True)
            btn.callback = callback
        else:
            async def default_callback(interaction: discord.Interaction):
                await interaction.response.defer()
            btn.callback = default_callback
    return btn

def embed_to_script(message: discord.Message) -> str:
    """Reverse-engineers a discord message into VOTOX script tags."""
    script = "{embed}"
    if message.content:
        script += f"{{content: {message.content}}}"
    
    if message.embeds:
        e = message.embeds[0]
        if e.title: script += f"{{title: {e.title}}}"
        if e.description: script += f"{{description: {e.description}}}"
        if e.color: script += f"{{color: {hex(e.color.value).replace('0x', '#')}}}"
        if e.timestamp: script += "{timestamp}"
        if e.author:
            auth = f"name: {e.author.name}"
            if e.author.icon_url: auth += f" && icon: {e.author.icon_url}"
            if e.author.url: auth += f" && url: {e.author.url}"
            script += f"{{author: {auth}}}"
        if e.thumbnail: script += f"{{thumbnail: {e.thumbnail.url}}}"
        if e.image: script += f"{{image: {e.image.url}}}"
        if e.footer:
            foot = f"text: {e.footer.text}"
            if e.footer.icon_url: foot += f" && icon: {e.footer.icon_url}"
            script += f"{{footer: {foot}}}"
        for f in e.fields:
            script += f"{{field: name: {f.name} && value: {f.value} && inline: {str(f.inline).lower()}}}"
    
    if message.components:
        script += "{buttons}"
        for action_row in message.components:
            for item in action_row.children:
                if isinstance(item, discord.Button):
                    style_name = str(item.style).split('.')[-1]
                    btn = f"label={item.label} && style={style_name}"
                    if item.url: btn += f" && url={item.url}"
                    script += f"{{button: {btn}}}"
    
    return script

def build_script(data: dict) -> str:
    """Compiles local dict data from the UI builder into script format."""
    script = "{embed}"
    if data.get('timestamp'): script += "{timestamp}"
    if data.get('color'): script += f"{{color: {data['color']}}}"
    if data.get('title'): script += f"{{title: {data['title']}}}"
    if data.get('description'): script += f"{{description: {data['description']}}}"
    
    if data.get('author_name'):
        auth = f"name: {data['author_name']}"
        if data.get('author_icon'): auth += f" && icon: {data['author_icon']}"
        if data.get('author_url'): auth += f" && url: {data['author_url']}"
        script += f"{{author: {auth}}}"
    
    if data.get('thumbnail'): script += f"{{thumbnail: {data['thumbnail']}}}"
    if data.get('image'): script += f"{{image: {data['image']}}}"
    
    for f in data.get('fields', []):
        script += f"{{field: name: {f['name']} && value: {f['value']} && inline: {str(f['inline']).lower()}}}"
    
    if data.get('buttons_enabled'):
        script += "{buttons}"
        for b in data.get('buttons_list', []):
            btn_tag = f"label={b['label']} && style={b['style']} && row={b['row']}"
            if b.get('action'): btn_tag += f" && action={{{b['action']}}}"
            script += f"{{button: {btn_tag}}}"
    
    return script