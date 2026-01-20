import discord
from discord.ext import commands
import os

intents = discord.Intents.default()
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

@bot.command()
async def countrole(ctx, *, role_name: str):
    role = discord.utils.get(ctx.guild.roles, name=role_name)

    if role is None:
        await ctx.send("❌ Role not found.")
        return

    count = sum(1 for member in ctx.guild.members if role in member.roles)
    await ctx.send(f"✅ **{count}** members have the **{role.name}** role.")

bot.run(os.getenv("TOKEN"))
