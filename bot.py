import discord
from discord.ext import commands, tasks
from discord import app_commands
import json, os, random, io, time
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

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

# ================== JSON UTILS ==================
def load_json(path, default=None):
    if not os.path.exists(path):
        return default if default is not None else {}
    with open(path, "r") as f:
        return json.load(f)

def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=4)

# ================== DEFAULT SETTINGS ==================
def default_settings():
    return {
        "xp_range": [10, 20],
        "cooldown": 60,
        "ignored_channels": [],
        "role_rewards": {},
        "levelup_bg": None,
        "rank_backgrounds": {}
    }

def xp_needed(level):
    return 100 + level * 75

# ================== READY ==================
@bot.event
async def on_ready():
    guild = discord.Object(id=GUILD_ID)
    print("🔄 Syncing commands...")
    tree.clear_commands(guild=guild)
    await tree.sync(guild=guild)

    if not auto_update.is_running():
        auto_update.start()

    print(f"✅ Synced slash commands to guild {GUILD_ID}")
    print(f"🤖 Logged in as {bot.user}")

# ======================================================
# ================== ROLE TRACKING =====================
# ======================================================
def role_count(role):
    return sum(1 for m in role.guild.members if role in m.roles)

def role_embed(role):
    return discord.Embed(
        title="📊 Role Count",
        description=f"{role.mention}\n👥 Members: {role_count(role)}",
        color=role.color if role.color.value else discord.Color.blurple()
    )

@tree.command(name="trackrole")
@app_commands.checks.has_permissions(administrator=True)
async def trackrole(interaction: discord.Interaction, role: discord.Role):
    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)
    data.setdefault(gid, {})

    msg = await interaction.channel.send(embed=role_embed(role))
    data[gid][str(role.id)] = {"channel": interaction.channel.id, "message": msg.id}

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
async def create_levelup_image(member, level, bg_path):
    if bg_path and os.path.exists(bg_path):
        bg = Image.open(bg_path).convert("RGBA")
    else:
        bg = Image.new("RGBA", (800, 200), (54, 57, 63, 255))

    draw = ImageDraw.Draw(bg)

    try:
        font = ImageFont.truetype("arialbd.ttf", 48)
    except:
        font = ImageFont.load_default()

    draw.text((250, 70), f"{member.display_name} reached Level {level}!", font=font, fill=(255,255,255))

    avatar = member.display_avatar.with_size(128)
    buf = io.BytesIO()
    await avatar.save(buf)
    buf.seek(0)
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
    user = glevels.setdefault(str(message.author.id), {"xp": 0, "level": 1, "last": 0})

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

        img = await create_levelup_image(message.author, user["level"], gset.get("levelup_bg"))

        await message.channel.send(
            f"🎉 {message.author.mention} reached Level {user['level']}!",
            file=discord.File(img, "levelup.png")
        )

    save_json(LEVEL_FILE, levels)
    save_json(SETTINGS_FILE, settings)
    await bot.process_commands(message)

# ======================================================
# ================== RANK CARD =========================
# ======================================================
def create_animated_rank_card(member, level, xp, required_xp, avatar_path, bg_path=None):
    width, height = 800, 250
    frames = []
    percent = xp / required_xp if required_xp else 0

    avatar = Image.open(avatar_path).resize((180, 180)).convert("RGBA")

    for i in range(15):
        if bg_path and os.path.exists(bg_path):
            base = Image.open(bg_path).convert("RGB").resize((width,height))
        else:
            base = Image.new("RGB",(width,height),(30,30,30))

        draw = ImageDraw.Draw(base)
        bar_width = int(500 * percent * (i/14))

        draw.rectangle((250,150,750,190), fill=(50,50,50))
        draw.rectangle((250,150,250+bar_width,190), fill=(120,0,255))

        draw.text((250,50), member.name, fill="white")
        draw.text((250,90), f"Level {level}", fill="white")
        draw.text((250,120), f"{xp}/{required_xp} XP", fill="white")

        base.paste(avatar,(40,35),avatar)
        frames.append(base)

    path = f"rank_{member.id}.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=60, loop=0)
    return path

# ======================================================
# ================== COMMANDS ==========================
# ======================================================

@tree.command(name="rank", description="View your animated rank card")
async def rank(interaction: discord.Interaction, member: Optional[discord.Member]=None):
    member = member or interaction.user
    levels = load_json(LEVEL_FILE, {})
    settings = load_json(SETTINGS_FILE, {})
    gid, uid = str(interaction.guild.id), str(member.id)

    user = levels.get(gid, {}).get(uid)
    if not user:
        await interaction.response.send_message("No level data yet!", ephemeral=True)
        return

    avatar_path = f"avatar_{uid}.png"
    await member.display_avatar.save(avatar_path)

    bg_path = settings.get(gid, {}).get("rank_backgrounds", {}).get(uid)
    required = xp_needed(user["level"])

    gif = create_animated_rank_card(member, user["level"], user["xp"], required, avatar_path, bg_path)
    await interaction.response.send_message(file=discord.File(gif))

@tree.command(name="leaderboard")
async def leaderboard(interaction: discord.Interaction):
    levels = load_json(LEVEL_FILE,{})
    gid = str(interaction.guild.id)
    top = sorted(levels.get(gid,{}).items(), key=lambda x:(x[1]["level"],x[1]["xp"]), reverse=True)[:10]

    embed = discord.Embed(title="🏆 Leaderboard", color=discord.Color.gold())
    for i,(uid,data) in enumerate(top,1):
        member = interaction.guild.get_member(int(uid))
        if member:
            embed.add_field(name=f"{i}. {member.display_name}", value=f"Level {data['level']} • XP {data['xp']}", inline=False)

    await interaction.response.send_message(embed=embed)

@tree.command(name="setxp")
@app_commands.checks.has_permissions(administrator=True)
async def setxp(interaction: discord.Interaction, min_xp:int, max_xp:int):
    settings = load_json(SETTINGS_FILE,{})
    gid = str(interaction.guild.id)
    settings.setdefault(gid, default_settings())["xp_range"] = [min_xp,max_xp]
    save_json(SETTINGS_FILE, settings)
    await interaction.response.send_message("✅ XP updated", ephemeral=True)

@tree.command(name="setcooldown")
@app_commands.checks.has_permissions(administrator=True)
async def setcooldown(interaction: discord.Interaction, seconds:int):
    settings = load_json(SETTINGS_FILE,{})
    gid = str(interaction.guild.id)
    settings.setdefault(gid, default_settings())["cooldown"] = seconds
    save_json(SETTINGS_FILE, settings)
    await interaction.response.send_message("⏳ Cooldown updated", ephemeral=True)

@tree.command(name="setrankbackground")
async def setrankbackground(interaction: discord.Interaction, image: discord.Attachment):
    settings = load_json(SETTINGS_FILE,{})
    gid, uid = str(interaction.guild.id), str(interaction.user.id)
    os.makedirs(f"rank_backgrounds/{gid}", exist_ok=True)
    path = f"rank_backgrounds/{gid}/{uid}.png"
    await image.save(path)
    settings.setdefault(gid, default_settings())["rank_backgrounds"][uid] = path
    save_json(SETTINGS_FILE, settings)
    await interaction.response.send_message("✅ Rank background set!", ephemeral=True)

@tree.command(name="setlevelupbackground")
@app_commands.checks.has_permissions(administrator=True)
async def setlevelupbackground(interaction: discord.Interaction, image: discord.Attachment):
    if not image.content_type or not image.content_type.startswith("image/"):
        await interaction.response.send_message("❌ Upload an image file.", ephemeral=True)
        return

    settings = load_json(SETTINGS_FILE, {})
    gid = str(interaction.guild.id)

    os.makedirs("levelup_backgrounds", exist_ok=True)
    path = f"levelup_backgrounds/{gid}.png"
    await image.save(path)

    settings.setdefault(gid, default_settings())["levelup_bg"] = path
    save_json(SETTINGS_FILE, settings)
    await interaction.response.send_message("✅ Level-up background updated!", ephemeral=True)

@tree.command(name="setrolereward")
@app_commands.checks.has_permissions(administrator=True)
async def setrolereward(interaction: discord.Interaction, level: int, role: discord.Role):
    settings = load_json(SETTINGS_FILE, {})
    gid = str(interaction.guild.id)
    settings.setdefault(gid, default_settings())["role_rewards"][str(level)] = role.id
    save_json(SETTINGS_FILE, settings)
    await interaction.response.send_message(f"🎁 {role.mention} will be given at Level {level}", ephemeral=True)

@tree.command(name="removerolereward")
@app_commands.checks.has_permissions(administrator=True)
async def removerolereward(interaction: discord.Interaction, level: int):
    settings = load_json(SETTINGS_FILE, {})
    gid = str(interaction.guild.id)
    rewards = settings.setdefault(gid, default_settings())["role_rewards"]

    if str(level) in rewards:
        del rewards[str(level)]
        save_json(SETTINGS_FILE, settings)
        await interaction.response.send_message("🗑️ Reward removed.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ No reward set for that level.", ephemeral=True)

@tree.command(name="rolerewards")
async def rolerewards(interaction: discord.Interaction):
    settings = load_json(SETTINGS_FILE, {})
    gid = str(interaction.guild.id)
    rewards = settings.get(gid, {}).get("role_rewards", {})

    if not rewards:
        await interaction.response.send_message("No level rewards set yet.", ephemeral=True)
        return

    desc = ""
    for level, role_id in sorted(rewards.items(), key=lambda x: int(x[0])):
        role = interaction.guild.get_role(int(role_id))
        if role:
            desc += f"Level {level} → {role.mention}\n"

    embed = discord.Embed(title="🎖️ Level Role Rewards", description=desc, color=discord.Color.green())
    await interaction.response.send_message(embed=embed)

# ================== RUN ==================
bot.run(os.getenv("DISCORD_TOKEN"))


