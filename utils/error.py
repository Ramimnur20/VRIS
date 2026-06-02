from discord.ext import commands
import discord


async def handle_error(bot, ctx, error):
    embed = discord.Embed(color=bot.embed_color)
    
    if isinstance(error, commands.CommandNotFound):
        embed.description = "❌ Command not found. Use the help command to see available commands."
    elif isinstance(error, commands.MissingPermissions):
        embed.description = "❌ You don't have the required permissions to use this command."
    elif isinstance(error, commands.MissingRequiredArgument):
        embed.description = f"❌ Missing required argument: `{error.param.name}`"
    elif isinstance(error, commands.CommandOnCooldown):
        embed.description = f"❌ This command is on cooldown. Try again in {error.retry_after:.1f} seconds."
    elif isinstance(error, commands.BadArgument):
        embed.description = f"❌ Invalid argument provided: {error}"
    elif isinstance(error, commands.BadUnionArgument):
        embed.description = f"❌ Could not convert argument: {error}"
    elif isinstance(error, commands.ArgumentParsingError):
        embed.description = "❌ Failed to parse arguments."
    elif isinstance(error, commands.UserInputError):
        embed.description = "❌ Invalid input provided."
    else:
        embed.description = "❌ An unexpected error occurred."
        raise error
    
    await ctx.send(embed=embed)