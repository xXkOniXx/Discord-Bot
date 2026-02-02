import discord
from discord.ext import commands, tasks
from discord import app_commands
import json
import os
import random
from typing import Optional
from datetime import datetime
import pytz
from PIL import Image, ImageDraw, ImageFont
# ================== INTENTS ==================
intents = discord.Intents.default()
intents.members = True
intents.messages = True

bot = commands.Bot(command_prefix="/", intents=intents)
tree = bot.tree

# ================== DATA FILES ==================
TRACKED_FILE = "tracked_roles.json"
LEVEL_FILE = "leveling_data.json"
SETTINGS_FILE = "leveling_settings.json"

# ================== LOAD / SAVE FUNCTIONS ==================
def load_json(file_path):
    if not os.path.exists(file_path):
        return {}
    with open(file_path, "r") as f:
        return json.load(f)

def save_json(file_path, data):
    with open(file_path, "w") as f:
        json.dump(data, f, indent=4)

# ================== ROLE TRACKING UTIL ==================
def role_count(role: discord.Role):
    return sum(1 for m in role.guild.members if role in m.roles)

def single_role_embed(role: discord.Role):
    embed = discord.Embed(
        title="📊 Role Count",
        description=f"{role.mention}\n\n👥 **Members:** {role_count(role)}",
        color=role.color if role.color.value else discord.Color.blurple()
    )
    embed.set_footer(text="Auto-updating every 10 minutes • Koni was here")
    return embed

def build_combined_embeds(guild: discord.Guild):
    data = load_json(TRACKED_FILE)
    gid = str(guild.id)
    embeds = []

    if gid not in data:
        embed = discord.Embed(title="No roles tracked", color=discord.Color.blurple())
        embed.set_footer(text="Koni was here")
        embeds.append(embed)
        return embeds

    fields = []
    for role_id in data[gid]:
        if role_id == "combined":
            continue
        role = guild.get_role(int(role_id))
        if not role:
            continue
        fields.append((role.name, f"👥 {role_count(role)}"))

    for i in range(0, len(fields), 25):
        embed = discord.Embed(title="📊 Tracked Roles", color=discord.Color.blurple())
        for name, value in fields[i:i+25]:
            embed.add_field(name=name, value=value, inline=False)
        embed.set_footer(text="Auto-updating every 10 minutes • Koni was here")
        embeds.append(embed)

    return embeds

# ================== READY EVENT ==================
@bot.event
async def on_ready():
    await tree.sync()
    auto_update.start()
    print(f"Bot online as {bot.user}")

# ================== ROLE TRACKING COMMANDS ==================
# /trackrole
@tree.command(name="trackrole", description="Track ONE role with its own embed")
@app_commands.checks.has_permissions(administrator=True)
async def trackrole(interaction: discord.Interaction, role: discord.Role):
    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)
    rid = str(role.id)
    data.setdefault(gid, {})

    # Delete old embed
    if rid in data[gid]:
        try:
            channel = interaction.guild.get_channel(data[gid][rid]["channel_id"])
            msg = await channel.fetch_message(data[gid][rid]["message_id"])
            await msg.delete()
        except:
            pass

    msg = await interaction.channel.send(embed=single_role_embed(role))
    data[gid][rid] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    save_json(TRACKED_FILE, data)
    await interaction.response.send_message(f"✅ Now tracking {role.mention}", ephemeral=True)

# /trackroleall
@tree.command(name="trackroleall", description="Track ALL roles automatically")
@app_commands.checks.has_permissions(administrator=True)
async def trackroleall(interaction: discord.Interaction):
    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)
    data.setdefault(gid, {})

    for role in interaction.guild.roles:
        if role.is_default():
            continue
        data[gid].setdefault(str(role.id), {})

    save_json(TRACKED_FILE, data)
    await interaction.response.send_message("✅ All roles are now being tracked", ephemeral=True)

# /trackroles
@tree.command(name="trackroles", description="Create ONE combined embed for all tracked roles")
@app_commands.checks.has_permissions(administrator=True)
async def trackroles(interaction: discord.Interaction):
    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)
    data.setdefault(gid, {})

    # Delete old combined embed
    if "combined" in data[gid]:
        try:
            channel = interaction.guild.get_channel(data[gid]["combined"]["channel_id"])
            msg = await channel.fetch_message(data[gid]["combined"]["message_id"])
            await msg.delete()
        except:
            pass

    embeds = build_combined_embeds(interaction.guild)
    msg = await interaction.channel.send(embed=embeds[0])
    data[gid]["combined"] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    for extra in embeds[1:]:
        await interaction.channel.send(embed=extra)

    save_json(TRACKED_FILE, data)
    await interaction.response.send_message("✅ Combined role embed created", ephemeral=True)

# /trackselect
@tree.command(name="trackselect", description="Track selected roles (up to 10)")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(
    role1="First role", role2="Second", role3="Third", role4="Fourth",
    role5="Fifth", role6="Sixth", role7="Seventh", role8="Eighth",
    role9="Ninth", role10="Tenth"
)
async def trackselect(interaction: discord.Interaction,
                      role1: Optional[discord.Role] = None,
                      role2: Optional[discord.Role] = None,
                      role3: Optional[discord.Role] = None,
                      role4: Optional[discord.Role] = None,
                      role5: Optional[discord.Role] = None,
                      role6: Optional[discord.Role] = None,
                      role7: Optional[discord.Role] = None,
                      role8: Optional[discord.Role] = None,
                      role9: Optional[discord.Role] = None,
                      role10: Optional[discord.Role] = None):
    roles = [r for r in (role1, role2, role3, role4, role5, role6, role7, role8, role9, role10) if r]
    if not roles:
        await interaction.response.send_message("❌ No roles selected.", ephemeral=True)
        return

    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)
    data.setdefault(gid, {})

    for role in roles:
        rid = str(role.id)
        data[gid].setdefault(rid, {})

    save_json(TRACKED_FILE, data)
    await interaction.response.send_message(f"✅ Tracking {len(roles)} selected roles.", ephemeral=True)

# /untrackrole
@tree.command(name="untrackrole", description="Stop tracking a single role")
@app_commands.checks.has_permissions(administrator=True)
async def untrackrole(interaction: discord.Interaction, role: discord.Role):
    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)

    if gid not in data or str(role.id) not in data[gid]:
        await interaction.response.send_message(f"❌ {role.mention} is not being tracked", ephemeral=True)
        return

    try:
        info = data[gid][str(role.id)]
        channel = interaction.guild.get_channel(info["channel_id"])
        if channel:
            msg = await channel.fetch_message(info["message_id"])
            await msg.delete()
    except:
        pass

    del data[gid][str(role.id)]
    save_json(TRACKED_FILE, data)
    await interaction.response.send_message(f"✅ Stopped tracking {role.mention}", ephemeral=True)

# /untrackall
@tree.command(name="untrackall", description="Stop tracking all roles in this server")
@app_commands.checks.has_permissions(administrator=True)
async def untrackall(interaction: discord.Interaction):
    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)

    if gid not in data or not data[gid]:
        await interaction.response.send_message("❌ No roles are being tracked", ephemeral=True)
        return

    for rid, info in data[gid].items():
        try:
            channel = interaction.guild.get_channel(info["channel_id"])
            if channel:
                msg = await channel.fetch_message(info["message_id"])
                await msg.delete()
        except:
            pass

    data[gid] = {}
    save_json(TRACKED_FILE, data)
    await interaction.response.send_message("✅ All roles have been untracked", ephemeral=True)

# ================== MEMBER TIME ==================
@tree.command(name="membertime", description="Show local time for all members who set their timezone")
async def membertime(interaction: discord.Interaction):
    if not os.path.exists("timezones.json"):
        await interaction.response.send_message("❌ No timezones are set yet.", ephemeral=True)
        return

    with open("timezones.json", "r") as f:
        tz_data = json.load(f)

    embed = discord.Embed(title="🕒 Member Local Times", color=discord.Color.blurple())
    for member_id, tz_name in tz_data.items():
        member = interaction.guild.get_member(int(member_id))
        if not member:
            continue
        tz = pytz.timezone(tz_name)
        now = datetime.now(tz)
        embed.add_field(name=member.display_name, value=now.strftime("%Y-%m-%d %H:%M:%S"), inline=False)

    embed.set_footer(text="Koni was here")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ================== AUTO UPDATE ==================
@tasks.loop(minutes=10)
async def auto_update():
    data = load_json(TRACKED_FILE)
    for guild in bot.guilds:
        gid = str(guild.id)
        if gid not in data:
            continue

        for role_id in data[gid]:
            if role_id == "combined":
                continue
            role = guild.get_role(int(role_id))
            if not role:
                continue
            try:
                channel = guild.get_channel(data[gid][role_id]["channel_id"])
                msg = await channel.fetch_message(data[gid][role_id]["message_id"])
                await msg.edit(embed=single_role_embed(role))
            except:
                pass

        if "combined" in data[gid]:
            try:
                channel = guild.get_channel(data[gid]["combined"]["channel_id"])
                msg = await channel.fetch_message(data[gid]["combined"]["message_id"])
                embeds = build_combined_embeds(guild)
                await msg.edit(embed=embeds[0])
            except:
                pass

# ================== LEVELING SYSTEM ==================
leveling_data = load_json(LEVEL_FILE)
leveling_settings = load_json(SETTINGS_FILE)

def save_leveling():
    save_json(LEVEL_FILE, leveling_data)
    save_json(SETTINGS_FILE, leveling_settings)

async def add_xp(member: discord.Member, guild: discord.Guild, amount: int = None):
    gid, uid = str(guild.id), str(member.id)
    leveling_data.setdefault(gid, {})
    leveling_data[gid].setdefault(uid, {"xp": 0, "level": 0})

    leveling_settings.setdefault(gid, {})
    ignored = leveling_settings[gid].get("ignored_channels", [])

    # Random XP if not specified
    if amount is None:
        amount = random.randint(5, 15)

    leveling_data[gid][uid]["xp"] += amount

    # Level up calculation
    xp = leveling_data[gid][uid]["xp"]
    lvl = leveling_data[gid][uid]["level"]
    required = 100 + (lvl * 50)  # Simple XP curve

    if xp >= required:
        leveling_data[gid][uid]["level"] += 1
        leveling_data[gid][uid]["xp"] -= required

        # Check for role rewards
        role_id = leveling_settings[gid].get("role_rewards", {}).get(str(leveling_data[gid][uid]["level"]))
        if role_id:
            role = guild.get_role(int(role_id))
            if role:
                await member.add_roles(role)

        save_leveling()
        return True, leveling_data[gid][uid]["level"]
    save_leveling()
    return False, leveling_data[gid][uid]["level"]

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    gid = str(message.guild.id)
    ignored = leveling_settings.get(gid, {}).get("ignored_channels", [])
    if str(message.channel.id) in ignored:
        return

    leveled_up, level = await add_xp(message.author, message.guild)
    if leveled_up:
        await message.channel.send(f"🎉 {message.author.mention} reached **level {level}**!")

# ================== LEVELING SETTINGS COMMANDS ==================
# /addrolereward
@tree.command(name="addrolereward", description="Add a role reward for a specific level")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.describe(level="Level to assign role", role="Role to assign")
async def addrolereward(interaction: discord.Interaction, level: int, role: discord.Role):
    gid = str(interaction.guild.id)
    leveling_settings.setdefault(gid, {})
    leveling_settings[gid].setdefault("role_rewards", {})
    leveling_settings[gid]["role_rewards"][str(level)] = str(role.id)
    save_leveling()
    await interaction.response.send_message(f"✅ Role {role.mention} will be assigned at level {level}", ephemeral=True)

# /removerolereward
@tree.command(name="removerolereward", description="Remove a role reward")
@app_commands.checks.has_permissions(administrator=True)
async def removerolereward(interaction: discord.Interaction, level: int):
    gid = str(interaction.guild.id)
    if gid in leveling_settings and "role_rewards" in leveling_settings[gid] and str(level) in leveling_settings[gid]["role_rewards"]:
        del leveling_settings[gid]["role_rewards"][str(level)]
        save_leveling()
        await interaction.response.send_message(f"✅ Removed role reward for level {level}", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ No role reward set for level {level}", ephemeral=True)

# /listrolerewards
@tree.command(name="listrolerewards", description="List all role rewards")
@app_commands.checks.has_permissions(administrator=True)
async def listrolerewards(interaction: discord.Interaction):
    gid = str(interaction.guild.id)
    embed = discord.Embed(title="📜 Level Role Rewards", color=discord.Color.blurple())

    if gid not in leveling_settings or "role_rewards" not in leveling_settings[gid] or not leveling_settings[gid]["role_rewards"]:
        embed.description = "No role rewards set."
    else:
        for lvl, rid in sorted(leveling_settings[gid]["role_rewards"].items(), key=lambda x: int(x[0])):
            role = interaction.guild.get_role(int(rid))
            embed.add_field(name=f"Level {lvl}", value=role.mention if role else f"<Deleted Role ID {rid}>", inline=False)

    embed.set_footer(text="Koni was here")
    await interaction.response.send_message(embed=embed, ephemeral=True)

# /ignorechannel
@tree.command(name="ignorechannel", description="Ignore a channel for XP")
@app_commands.checks.has_permissions(administrator=True)
async def ignorechannel(interaction: discord.Interaction, channel: discord.TextChannel):
    gid = str(interaction.guild.id)
    leveling_settings.setdefault(gid, {})
    leveling_settings[gid].setdefault("ignored_channels", [])

    if str(channel.id) in leveling_settings[gid]["ignored_channels"]:
        await interaction.response.send_message(f"❌ {channel.mention} is already ignored", ephemeral=True)
        return

    leveling_settings[gid]["ignored_channels"].append(str(channel.id))
    save_leveling()
    await interaction.response.send_message(f"✅ {channel.mention} will no longer give XP", ephemeral=True)

# /unignorechannel
@tree.command(name="unignorechannel", description="Unignore a channel for XP")
@app_commands.checks.has_permissions(administrator=True)
async def unignorechannel(interaction: discord.Interaction, channel: discord.TextChannel):
    gid = str(interaction.guild.id)
    if gid in leveling_settings and "ignored_channels" in leveling_settings[gid] and str(channel.id) in leveling_settings[gid]["ignored_channels"]:
        leveling_settings[gid]["ignored_channels"].remove(str(channel.id))
        save_leveling()
        await interaction.response.send_message(f"✅ {channel.mention} will now give XP", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ {channel.mention} was not ignored", ephemeral=True)
from PIL import Image, ImageDraw, ImageFont
import io
import aiohttp

# ================== RANK CARD GENERATOR ==================
def create_rank_card(member: discord.Member, xp: int, level: int, next_level_xp: int):
    # Card settings
    width, height = 800, 200
    bg_color = (54, 57, 63)  # Discord dark gray
    bar_bg_color = (32, 34, 37)
    bar_fill_color = (114, 137, 218)
    font_color = (255, 255, 255)

    # Create image
    card = Image.new("RGB", (width, height), color=bg_color)
    draw = ImageDraw.Draw(card)

    # Fonts (you can use a .ttf file or system font)
    try:
        font_bold = ImageFont.truetype("arialbd.ttf", 40)
        font_regular = ImageFont.truetype("arial.ttf", 30)
    except:
        font_bold = ImageFont.load_default()
        font_regular = ImageFont.load_default()

    # Draw avatar
    size = 150
    avatar = member.display_avatar.with_size(128).with_static_format('png')
    avatar_bytes = io.BytesIO()
    
    async def get_avatar():
        async with aiohttp.ClientSession() as session:
            async with session.get(str(avatar.url)) as resp:
                avatar_bytes.write(await resp.read())
                avatar_bytes.seek(0)
    
    import asyncio
    asyncio.run(get_avatar())
    avatar_img = Image.open(avatar_bytes).convert("RGB").resize((size, size))
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size, size), fill=255)
    card.paste(avatar_img, (25, 25), mask)

    # Draw username
    draw.text((200, 40), str(member), font=font_bold, fill=font_color)

    # Draw level
    draw.text((200, 90), f"Level: {level}", font=font_regular, fill=font_color)

    # Draw XP
    draw.text((200, 130), f"XP: {xp}/{next_level_xp}", font=font_regular, fill=font_color)

    # Draw XP bar
    bar_x, bar_y, bar_width, bar_height = 200, 170, 550, 25
    draw.rectangle([bar_x, bar_y, bar_x + bar_width, bar_y + bar_height], fill=bar_bg_color)
    fill_width = int(bar_width * (xp / next_level_xp))
    draw.rectangle([bar_x, bar_y, bar_x + fill_width, bar_y + bar_height], fill=bar_fill_color)

    # Save to BytesIO
    output_buffer = io.BytesIO()
    card.save(output_buffer, format='PNG')
    output_buffer.seek(0)
    return output_buffer

# ================== /RANK COMMAND ==================
@tree.command(name="rank", description="Show your rank card")
async def rank(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    if member is None:
        member = interaction.user

    gid, uid = str(interaction.guild.id), str(member.id)
    leveling_data.setdefault(gid, {})
    leveling_data[gid].setdefault(uid, {"xp": 0, "level": 0})
    data = leveling_data[gid][uid]

    xp = data["xp"]
    level = data["level"]
    next_level_xp = 100 + (level * 50)

    image_bytes = create_rank_card(member, xp, level, next_level_xp)
    file = discord.File(fp=image_bytes, filename="rank.png")
    await interaction.response.send_message(file=file)
from PIL import Image, ImageDraw, ImageFont
import io
import aiohttp

# ================== LEVEL UP IMAGE GENERATOR ==================
async def create_levelup_image(member: discord.Member, level: int, background_path="levelup_bg.png"):
    """
    Generates a custom level-up image.
    member: discord.Member
    level: int
    background_path: path to a custom background image
    """
    # Load background
    try:
        bg = Image.open(background_path).convert("RGBA")
    except:
        # fallback blank background
        bg = Image.new("RGBA", (800, 200), (54, 57, 63, 255))

    draw = ImageDraw.Draw(bg)

    # Fonts
    try:
        font_bold = ImageFont.truetype("arialbd.ttf", 50)
        font_regular = ImageFont.truetype("arial.ttf", 35)
    except:
        font_bold = ImageFont.load_default()
        font_regular = ImageFont.load_default()

    # Draw "Level Up!" text
    draw.text((250, 30), "🎉 LEVEL UP! 🎉", font=font_bold, fill=(255, 255, 255))

    # Draw username
    draw.text((250, 100), f"{member.display_name}", font=font_bold, fill=(255, 255, 255))

    # Draw new level
    draw.text((250, 150), f"Level {level}", font=font_regular, fill=(255, 255, 0))

    # Draw avatar
    size = 120
    avatar = member.display_avatar.with_size(128).with_static_format('png')
    avatar_bytes = io.BytesIO()
    async with aiohttp.ClientSession() as session:
        async with session.get(str(avatar.url)) as resp:
            avatar_bytes.write(await resp.read())
            avatar_bytes.seek(0)
    avatar_img = Image.open(avatar_bytes).convert("RGBA").resize((size, size))
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size, size), fill=255)
    bg.paste(avatar_img, (50, 40), mask)

    # Save to BytesIO
    output_buffer = io.BytesIO()
    bg.save(output_buffer, format="PNG")
    output_buffer.seek(0)
    return output_buffer
# ================= INTENTS =================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# ================= FILES =================
LEVEL_FILE = "levels.json"
SETTINGS_FILE = "level_settings.json"

# ================= UTIL =================
def load(file, default):
    if not os.path.exists(file):
        return default
    with open(file, "r") as f:
        return json.load(f)

def save(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=4)

# ================= DEFAULT SETTINGS =================
def default_settings():
    return {
        "xp_range": [10, 20],
        "cooldown": 60,
        "disabled_channels": [],
        "role_multipliers": {},
        "level_roles": {}
    }

def xp_needed(level):
    return 100 + (level * 75)

# ================= IMAGE GENERATION =================
def rank_card(member, level, xp, needed):
    img = Image.new("RGB", (900, 250), (25, 27, 32))
    draw = ImageDraw.Draw(img)

    avatar_asset = member.display_avatar.with_size(128)
    buf = io.BytesIO()
    avatar_asset.save(buf)
    avatar = Image.open(buf).convert("RGBA").resize((128, 128))
    img.paste(avatar, (40, 60), avatar)

    try:
        big = ImageFont.truetype("arial.ttf", 36)
        small = ImageFont.truetype("arial.ttf", 22)
    except:
        big = small = ImageFont.load_default()

    draw.text((200, 60), member.display_name, font=big, fill=(255,255,255))
    draw.text((200, 110), f"Level {level}", font=big, fill=(114,137,218))
    draw.text((200, 150), f"{xp}/{needed} XP", font=small, fill=(200,200,200))

    bar_x, bar_y, bar_w = 200, 190, 600
    progress = int(bar_w * (xp / needed))
    draw.rectangle((bar_x, bar_y, bar_x+bar_w, bar_y+20), fill=(50,50,50))
    draw.rectangle((bar_x, bar_y, bar_x+progress, bar_y+20), fill=(114,137,218))

    out = io.BytesIO()
    img.save(out, "PNG")
    out.seek(0)
    return out

# ================= XP SYSTEM =================
@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    settings = load(SETTINGS_FILE, {})
    guild_settings = settings.setdefault(str(message.guild.id), default_settings())

    if message.channel.id in guild_settings["disabled_channels"]:
        return

    levels = load(LEVEL_FILE, {})
    guild = levels.setdefault(str(message.guild.id), {})
    user = guild.setdefault(str(message.author.id), {
        "xp": 0,
        "level": 1,
        "last": 0
    })

    if time.time() - user["last"] < guild_settings["cooldown"]:
        return

    user["last"] = time.time()

    xp = random.randint(*guild_settings["xp_range"])

    for role in message.author.roles:
        mult = guild_settings["role_multipliers"].get(str(role.id))
        if mult:
            xp = int(xp * mult)

    user["xp"] += xp
    needed = xp_needed(user["level"])

if user["xp"] >= needed:
    user["xp"] -= needed
    user["level"] += 1

    reward = guild_settings["level_roles"].get(str(user["level"]))
    if reward:
        role = message.guild.get_role(int(reward))
        if role:
            await message.author.add_roles(role)

    img = rank_card(
        message.author,
        user["level"],
        user["xp"],
        xp_needed(user["level"])
    )

    await message.channel.send(
        f"🎉 **{message.author.mention} reached Level {user['level']}!**",
        file=discord.File(img, "levelup.png")
    )

    save(LEVEL_FILE, levels)
    await bot.process_commands(message)

# ================= COMMANDS =================
@tree.command(name="rank")
async def rank(interaction: discord.Interaction, member: discord.Member = None):
    member = member or interaction.user
    data = load(LEVEL_FILE, {})
    user = data.get(str(interaction.guild.id), {}).get(str(member.id), {"xp": 0, "level": 1})
    img = rank_card(member, user["level"], user["xp"], xp_needed(user["level"]))
    await interaction.response.send_message(file=discord.File(img, "rank.png"))

@tree.command(name="leaderboard")
async def leaderboard(interaction: discord.Interaction):
    data = load(LEVEL_FILE, {}).get(str(interaction.guild.id), {})
    top = sorted(data.items(), key=lambda x: x[1]["level"], reverse=True)[:10]

    embed = discord.Embed(title="🏆 Leaderboard", color=discord.Color.blurple())
    for i, (uid, stats) in enumerate(top, 1):
        member = interaction.guild.get_member(int(uid))
        if member:
            embed.add_field(name=f"{i}. {member.display_name}", value=f"Level {stats['level']}", inline=False)

    await interaction.response.send_message(embed=embed)

@tree.command(name="disablexp")
@app_commands.checks.has_permissions(administrator=True)
async def disablexp(interaction: discord.Interaction, channel: discord.TextChannel):
    settings = load(SETTINGS_FILE, {})
    guild = settings.setdefault(str(interaction.guild.id), default_settings())
    guild["disabled_channels"].append(channel.id)
    save(SETTINGS_FILE, settings)
    await interaction.response.send_message(f"❌ XP disabled in {channel.mention}", ephemeral=True)

@tree.command(name="setxprange")
@app_commands.checks.has_permissions(administrator=True)
async def setxprange(interaction: discord.Interaction, min_xp: int, max_xp: int):
    settings = load(SETTINGS_FILE, {})
    settings.setdefault(str(interaction.guild.id), default_settings())["xp_range"] = [min_xp, max_xp]
    save(SETTINGS_FILE, settings)
    await interaction.response.send_message("✅ XP range updated", ephemeral=True)

@tree.command(name="setrolemultiplier")
@app_commands.checks.has_permissions(administrator=True)
async def setrolemultiplier(interaction: discord.Interaction, role: discord.Role, multiplier: float):
    settings = load(SETTINGS_FILE, {})
    settings.setdefault(str(interaction.guild.id), default_settings())["role_multipliers"][str(role.id)] = multiplier
    save(SETTINGS_FILE, settings)
    await interaction.response.send_message(f"✅ {role.name} XP multiplier set to {multiplier}", ephemeral=True)

@tree.command(name="setlevelrole")
@app_commands.checks.has_permissions(administrator=True)
async def setlevelrole(interaction: discord.Interaction, level: int, role: discord.Role):
    settings = load(SETTINGS_FILE, {})
    settings.setdefault(str(interaction.guild.id), default_settings())["level_roles"][str(level)] = role.id
    save(SETTINGS_FILE, settings)
    await interaction.response.send_message(f"🏆 Level {level} → {role.name}", ephemeral=True)



# ================== RUN ==================
bot.run(os.getenv("DISCORD_TOKEN"))
