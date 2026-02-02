import discord
from discord.ext import commands, tasks
from discord import app_commands
import json, os, random, io, time
from typing import Optional
from datetime import datetime
import pytz
from PIL import Image, ImageDraw, ImageFont
import aiohttp
GUILD_ID = 1386046923693101076
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
    guild = discord.Object(id=GUILD_ID)

    tree.clear_commands(guild=guild)  # wipes old broken ones
    await tree.sync(guild=guild)      # re-syncs instantly

    print(f"✅ Synced slash commands to {GUILD_ID}")
    print(f"Logged in as {bot.user}")


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
@tree.command(name="setxp", description="Set XP range per message")
@app_commands.checks.has_permissions(administrator=True)
async def setxp(interaction: discord.Interaction, min_xp: int, max_xp: int):
    if min_xp <= 0 or max_xp < min_xp:
        await interaction.response.send_message("❌ Invalid XP range.", ephemeral=True)
        return

    gid = str(interaction.guild.id)
    leveling_settings.setdefault(gid, {})
    leveling_settings[gid]["xp_per_message"] = [min_xp, max_xp]
    save_leveling()

    await interaction.response.send_message(
        f"✅ XP per message set to **{min_xp}–{max_xp}**",
        ephemeral=True
    )
@tree.command(name="leaderboard", description="Show the leveling leaderboard")
async def leaderboard(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    guild_data = leveling_data.get(gid, {})

    if not guild_data:
        await interaction.response.send_message("❌ No leveling data yet.", ephemeral=True)
        return

    sorted_users = sorted(
        guild_data.items(),
        key=lambda x: (x[1]["level"], x[1]["xp"]),
        reverse=True
    )[:10]

    embed = discord.Embed(title="🏆 Level Leaderboard", color=discord.Color.gold())

    for i, (uid, data) in enumerate(sorted_users, start=1):
        member = interaction.guild.get_member(int(uid))
        if member:
            embed.add_field(
                name=f"{i}. {member.display_name}",
                value=f"Level **{data['level']}** • XP **{data['xp']}**",
                inline=False
            )

    embed.set_footer(text="Koni was here")
    await interaction.response.send_message(embed=embed)

@tree.command(name="setrankbackground", description="Upload a custom rank card background")
async def setrankbackground(interaction: discord.Interaction, image: discord.Attachment):
    if not image.content_type or not image.content_type.startswith("image/"):
        await interaction.response.send_message("❌ Please upload an image file.", ephemeral=True)
        return

    gid = str(interaction.guild.id)
    uid = str(interaction.user.id)

    folder = f"rank_backgrounds/{gid}"
    os.makedirs(folder, exist_ok=True)

    path = f"{folder}/{uid}.png"
    await image.save(path)

    leveling_settings.setdefault(gid, {})
    leveling_settings[gid].setdefault("rank_backgrounds", {})
    leveling_settings[gid]["rank_backgrounds"][uid] = path
    save_leveling()

    await interaction.response.send_message("✅ Your custom rank card background has been set!", ephemeral=True)
bg_path = leveling_settings.get(str(member.guild.id), {}).get("rank_backgrounds", {}).get(str(member.id))

if bg_path and os.path.exists(bg_path):
    card = Image.open(bg_path).convert("RGB").resize((width, height))
else:
    card = Image.new("RGB", (width, height), color=bg_color)
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    gid = str(message.guild.id)
    uid = str(message.author.id)

    leveling_settings.setdefault(gid, {})
    leveling_data.setdefault(gid, {})

    settings = leveling_settings[gid]
    user = leveling_data[gid].setdefault(uid, {"xp": 0, "level": 0, "last": 0})

    cooldown = settings.get("cooldown", 60)
    now = datetime.utcnow().timestamp()

    if now - user["last"] < cooldown:
        return

    user["last"] = now

    min_xp, max_xp = settings.get("xp_per_message", [10, 20])
    gained = random.randint(min_xp, max_xp)

    user["xp"] += gained
    required = 100 + (user["level"] * 50)

    if user["xp"] >= required:
        user["xp"] -= required
        user["level"] += 1

        await message.channel.send(
            f"🎉 {message.author.mention} reached **Level {user['level']}!**"
        )

    save_leveling()
    await bot.process_commands(message)
from PIL import Image, ImageDraw, ImageFont, ImageSequence
import imageio
import math

def create_animated_rank_card(member, level, xp, required_xp, avatar_path):
    width, height = 800, 250
    frames = []

    percent = xp / required_xp
    bar_max_width = 500

    avatar = Image.open(avatar_path).resize((180, 180)).convert("RGBA")

    for i in range(15):  # number of frames (smoothness)
        frame = Image.new("RGB", (width, height), (30, 30, 30))
        draw = ImageDraw.Draw(frame)

        # Animated bar fill
        animated_percent = percent * (i / 14)
        bar_width = int(bar_max_width * animated_percent)

        # Background bar
        draw.rectangle((250, 150, 750, 190), fill=(50, 50, 50))

        # XP bar (animated fill)
        draw.rectangle((250, 150, 250 + bar_width, 190), fill=(120, 0, 255))

        # Text
        draw.text((250, 50), f"{member.name}", fill="white")
        draw.text((250, 90), f"Level {level}", fill="white")
        draw.text((250, 120), f"{xp}/{required_xp} XP", fill="white")

        # Avatar
        frame.paste(avatar, (40, 35), avatar)

        frames.append(frame)

    gif_path = f"rank_{member.id}.gif"
    frames[0].save(
        gif_path,
        save_all=True,
        append_images=frames[1:],
        duration=60,
        loop=0
    )

    return gif_path
@tree.command(name="rank", description="View your animated rank card")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    gid = str(interaction.guild.id)
    uid = str(member.id)

    user = leveling_data.get(gid, {}).get(uid)
    if not user:
        await interaction.response.send_message("No level data yet!", ephemeral=True)
        return

    avatar_path = f"avatar_{uid}.png"
    await member.display_avatar.save(avatar_path)

    required = 100 + (user["level"] * 50)

    gif_path = create_animated_rank_card(
        member,
        user["level"],
        user["xp"],
        required,
        avatar_path
    )

    file = discord.File(gif_path, filename="rank.gif")
    await interaction.response.send_message(file=file)

@tree.command(name="setcooldown", description="Set XP cooldown in seconds", guild=discord.Object(id=GUILD_ID))
async def setcooldown(interaction: discord.Interaction, seconds: int):
    xp_settings["cooldown"] = seconds
    await interaction.response.send_message(f"⏳ Cooldown set to {seconds} seconds")

# ================== RUN ==================
bot.run(os.getenv("DISCORD_TOKEN"))

