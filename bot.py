import discord
from discord.ext import commands, tasks
from discord import app_commands
import json, os, random, io, time
from typing import Optional
from datetime import datetime
import pytz
from PIL import Image, ImageDraw, ImageFont
import aiohttp

# ================== INTENTS ==================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ================== FILES ==================
TRACKED_FILE = "tracked_roles.json"
LEVEL_FILE = "leveling_data.json"
SETTINGS_FILE = "leveling_settings.json"
TIMEZONE_FILE = "timezones.json"

# ================== JSON UTILS ==================
def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# ================== READY ==================
@bot.event
async def on_ready():
    await tree.sync()
    auto_update.start()
    print(f"✅ Online as {bot.user}")

# ======================================================
# ================== ROLE TRACKING =====================
# ======================================================
def role_count(role):
    return sum(1 for m in role.guild.members if role in m.roles)

def role_embed(role):
    return discord.Embed(
        title="📊 Role Count",
        description=f"{role.mention}\n👥 **Members:** {role_count(role)}",
        color=role.color if role.color.value else discord.Color.blurple()
    )

@tree.command(name="trackrole")
@app_commands.checks.has_permissions(administrator=True)
async def trackrole(interaction: discord.Interaction, role: discord.Role):
    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)
    data.setdefault(gid, {})

    msg = await interaction.channel.send(embed=role_embed(role))
    data[gid][str(role.id)] = {
        "channel": interaction.channel.id,
        "message": msg.id
    }

    save_json(TRACKED_FILE, data)
    await interaction.response.send_message("✅ Role tracked", ephemeral=True)

@tasks.loop(minutes=10)
async def auto_update():
    data = load_json(TRACKED_FILE)
    for guild in bot.guilds:
        gid = str(guild.id)
        for rid, info in data.get(gid, {}).items():
            role = guild.get_role(int(rid))
            if not role:
                continue
            try:
                ch = guild.get_channel(info["channel"])
                msg = await ch.fetch_message(info["message"])
                await msg.edit(embed=role_embed(role))
            except:
                pass

# ======================================================
# ================== LEVEL SYSTEM ======================
# ======================================================
def xp_needed(level):
    return 100 + level * 75

def default_settings():
    return {
        "xp_range": [10, 20],
        "cooldown": 60,
        "ignored_channels": [],
        "role_rewards": {},
        "levelup_bg": None
    }

async def create_levelup_image(member, level, bg_path):
    bg = Image.open(bg_path).convert("RGBA") if bg_path and os.path.exists(bg_path) else Image.new("RGBA",(800,200),(54,57,63,255))
    draw = ImageDraw.Draw(bg)

    try:
        font = ImageFont.truetype("arialbd.ttf", 48)
    except:
        font = ImageFont.load_default()

    draw.text((250, 70), f"{member.display_name} reached Level {level}!", font=font, fill=(255,255,255))

    avatar = member.display_avatar.with_size(128)
    buf = io.BytesIO()
    await avatar.save(buf)
    av = Image.open(buf).resize((120,120))
    bg.paste(av,(50,40),av)

    out = io.BytesIO()
    bg.save(out,"PNG")
    out.seek(0)
    return out

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    settings = load_json(SETTINGS_FILE, {})
    levels = load_json(LEVEL_FILE, {})

    gset = settings.setdefault(str(message.guild.id), default_settings())
    glevels = levels.setdefault(str(message.guild.id), {})
    user = glevels.setdefault(str(message.author.id), {"xp":0,"level":1,"last":0})

    if str(message.channel.id) in gset["ignored_channels"]:
        return
    if time.time() - user["last"] < gset["cooldown"]:
        return

    user["last"] = time.time()
    user["xp"] += random.randint(*gset["xp_range"])

    if user["xp"] >= xp_needed(user["level"]):
        user["xp"] -= xp_needed(user["level"])
        user["level"] += 1

        reward = gset["role_rewards"].get(str(user["level"]))
        if reward:
            role = message.guild.get_role(int(reward))
            if role:
                await message.author.add_roles(role)

        img = await create_levelup_image(message.author, user["level"], gset["levelup_bg"])
        await message.channel.send(
            f"🎉 {message.author.mention} leveled up!",
            file=discord.File(img,"levelup.png")
        )

    save_json(LEVEL_FILE, levels)
    save_json(SETTINGS_FILE, settings)
    await bot.process_commands(message)

# ======================================================
# ================== COMMANDS ==========================
# ======================================================
@tree.command(name="rank")
async def rank(interaction: discord.Interaction, member: Optional[discord.Member]=None):
    member = member or interaction.user
    data = load_json(LEVEL_FILE, {})
    user = data.get(str(interaction.guild.id), {}).get(str(member.id), {"xp":0,"level":1})
    await interaction.response.send_message(f"📈 {member.mention} — Level {user['level']} | XP {user['xp']}")

@tree.command(name="setlevelupbackground")
@app_commands.checks.has_permissions(administrator=True)
async def setbg(interaction: discord.Interaction, image: discord.Attachment):
    path = f"levelup_{interaction.guild.id}.png"
    await image.save(path)
    settings = load_json(SETTINGS_FILE, {})
    settings.setdefault(str(interaction.guild.id), default_settings())["levelup_bg"] = path
    save_json(SETTINGS_FILE, settings)
    await interaction.response.send_message("✅ Level-up background set!", ephemeral=True)

# ================== RUN ==================
bot.run(os.getenv("DISCORD_TOKEN"))

