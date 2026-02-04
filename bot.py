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
ECONOMY_FILE = "economy_data.json"

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
        "rank_backgrounds": {},
        "xp_multiplier": 1.0,
        "level_channel": None,
        "level_notify": {},
        "max_level": 100,
        "voice_bonus_xp": 10,
        "voice_bonus_cooldown": 300
    }

def xp_needed(level):
    return 100 + level * 75

def default_economy_user():
    return {
        "coins": 0,
        "rep": 0,
        "rep_last": 0,
        "last_daily": 0,
        "daily_streak": 0,
        "last_work": 0,
        "last_heist": 0,
        "backgrounds": [],
        "color": None,
        "badge": None,
        "badges": [],
        "prestige": 0,
        "voice_bonus": True,
        "last_voice_bonus": 0,
        "afk": False,
        "afk_reason": None,
        "married_to": None
    }

def get_guild_settings(guild_id):
    settings = load_json(SETTINGS_FILE, {})
    return settings.setdefault(str(guild_id), default_settings()), settings

def get_level_data(guild_id):
    levels = load_json(LEVEL_FILE, {})
    return levels.setdefault(str(guild_id), {}), levels

def get_economy_data(guild_id):
    economy = load_json(ECONOMY_FILE, {})
    return economy.setdefault(str(guild_id), {}), economy

def ensure_user_economy(economy_guild, user_id):
    return economy_guild.setdefault(str(user_id), default_economy_user())

SHOP_BACKGROUNDS = {
    "Galaxy": 500,
    "Neon": 750,
    "Forest": 300
}

EIGHT_BALL_RESPONSES = [
    "It is certain.",
    "Without a doubt.",
    "Yes - definitely.",
    "Reply hazy, try again.",
    "Ask again later.",
    "Better not tell you now.",
    "My sources say no.",
    "Very doubtful.",
    "Absolutely!",
    "Don't count on it."
]

CONVERSATION_STARTERS = [
    "Pineapple on pizza — yes or no?",
    "What's a movie you could watch 10 times?",
    "If you could time travel, where would you go?",
    "What's your go-to comfort food?",
    "Cats or dogs — which team are you on?"
]

WOULD_YOU_RATHER = [
    "Would you rather be able to fly or be invisible?",
    "Would you rather never need sleep or never need food?",
    "Would you rather explore space or the deep ocean?",
    "Would you rather have super strength or super speed?",
    "Would you rather live without music or without movies?"
]

DEBATE_TOPICS = [
    "Is social media good or bad for society?",
    "Should homework be banned?",
    "Is it better to be early or right on time?",
    "Are videogames a sport?",
    "Should you separate art from the artist?"
]

HEIST_TRIVIA = [
    {"q": "What planet is known as the Red Planet?", "a": "mars"},
    {"q": "How many continents are there on Earth?", "a": "7"},
    {"q": "What is the capital of France?", "a": "paris"},
    {"q": "Which ocean is the largest?", "a": "pacific"},
    {"q": "What is 5 + 7?", "a": "12"}
]

# ================== READY ==================
@bot.event
async def on_ready():
    print("🔄 Syncing commands globally...")

    try:
        synced = await tree.sync()  # Global sync (no guild wipe)
        print(f"✅ Synced {len(synced)} commands globally")
    except Exception as e:
        print(f"❌ Sync error: {e}")

    auto_update.start()
    auto_update_tracked_list.start()
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

def tracked_role_ids(data, gid):
    return [int(rid) for rid in data.get(gid, {}) if rid.isdigit()]

def tracked_roles_list_embed(guild, role_ids):
    desc_lines = []
    for rid in role_ids:
        role = guild.get_role(rid)
        if role:
            desc_lines.append(f"{role.mention} — {role_count(role)} members")
    if not desc_lines:
        desc_lines = ["No roles are currently tracked."]
    return discord.Embed(
        title="📌 Tracked Roles",
        description="\n".join(desc_lines),
        color=discord.Color.blurple()
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

@tree.command(name="untrackrole")
@app_commands.checks.has_permissions(administrator=True)
async def untrackrole(interaction: discord.Interaction, role: discord.Role):
    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)
    if str(role.id) in data.get(gid, {}):
        del data[gid][str(role.id)]
        save_json(TRACKED_FILE, data)
        await interaction.response.send_message("✅ Role untracked.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ That role isn't tracked.", ephemeral=True)

@tree.command(name="trackrolelist")
@app_commands.checks.has_permissions(administrator=True)
async def trackrolelist(interaction: discord.Interaction):
    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)
    role_ids = tracked_role_ids(data, gid)
    embed = tracked_roles_list_embed(interaction.guild, role_ids)

    msg = await interaction.channel.send(embed=embed)
    data.setdefault(gid, {})["_list"] = {"channel": interaction.channel.id, "message": msg.id}
    save_json(TRACKED_FILE, data)
    await interaction.response.send_message("✅ Tracking list posted and will update every 5 minutes.", ephemeral=True)

@tree.command(name="trackroleall")
@app_commands.checks.has_permissions(administrator=True)
async def trackroleall(interaction: discord.Interaction):
    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)
    data.setdefault(gid, {})
    for role in interaction.guild.roles:
        if role.is_default():
            continue
        msg = await interaction.channel.send(embed=role_embed(role))
        data[gid][str(role.id)] = {"channel": interaction.channel.id, "message": msg.id}
    save_json(TRACKED_FILE, data)
    await interaction.response.send_message("✅ All roles are now tracked.", ephemeral=True)

@tree.command(name="untrackroleall")
@app_commands.checks.has_permissions(administrator=True)
async def untrackroleall(interaction: discord.Interaction):
    data = load_json(TRACKED_FILE)
    gid = str(interaction.guild.id)
    list_info = data.get(gid, {}).get("_list")
    data[gid] = {}
    if list_info:
        data[gid]["_list"] = list_info
    save_json(TRACKED_FILE, data)
    await interaction.response.send_message("✅ All roles untracked.", ephemeral=True)

@tasks.loop(minutes=10)
async def auto_update():
    data = load_json(TRACKED_FILE)
    for guild in bot.guilds:
        gid = str(guild.id)
        for rid, info in data.get(gid, {}).items():
            if not rid.isdigit():
                continue
            role = guild.get_role(int(rid))
            if not role:
                continue
            try:
                ch = guild.get_channel(info["channel"])
                msg = await ch.fetch_message(info["message"])
                await msg.edit(embed=role_embed(role))
            except:
                pass

@tasks.loop(minutes=5)
async def auto_update_tracked_list():
    data = load_json(TRACKED_FILE)
    for guild in bot.guilds:
        gid = str(guild.id)
        list_info = data.get(gid, {}).get("_list")
        if not list_info:
            continue
        role_ids = tracked_role_ids(data, gid)
        try:
            ch = guild.get_channel(list_info["channel"])
            msg = await ch.fetch_message(list_info["message"])
            await msg.edit(embed=tracked_roles_list_embed(guild, role_ids))
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

    gset, settings = get_guild_settings(message.guild.id)
    glevels, levels = get_level_data(message.guild.id)
    economy_guild, economy = get_economy_data(message.guild.id)
    econ_user = ensure_user_economy(economy_guild, message.author.id)
    user = glevels.setdefault(str(message.author.id), {"xp": 0, "level": 1, "last": 0})

    if str(message.channel.id) in gset["ignored_channels"]:
        return

    if time.time() - user["last"] < gset["cooldown"]:
        return

    user["last"] = time.time()
    gained_xp = random.randint(*gset["xp_range"])
    gained_xp = int(gained_xp * gset.get("xp_multiplier", 1.0))
    user["xp"] += gained_xp

    if user["xp"] >= xp_needed(user["level"]):
        user["xp"] -= xp_needed(user["level"])
        user["level"] += 1

        reward = gset["role_rewards"].get(str(user["level"]))
        if reward:
            role = message.guild.get_role(int(reward))
            if role:
                await message.author.add_roles(role)

        level_notify = gset.get("level_notify", {}).get(str(message.author.id), True)
        if level_notify:
            img = await create_levelup_image(message.author, user["level"], gset.get("levelup_bg"))
            level_channel_id = gset.get("level_channel")
            level_channel = message.guild.get_channel(level_channel_id) if level_channel_id else message.channel
            await level_channel.send(
                f"🎉 {message.author.mention} reached Level {user['level']}!",
                file=discord.File(img, "levelup.png")
            )

    save_json(LEVEL_FILE, levels)
    save_json(SETTINGS_FILE, settings)
    save_json(ECONOMY_FILE, economy)

    if econ_user.get("afk"):
        econ_user["afk"] = False
        econ_user["afk_reason"] = None
        save_json(ECONOMY_FILE, economy)
        await message.channel.send(f"👋 Welcome back, {message.author.mention}! Your AFK is now off.")

    if message.mentions:
        afk_mentions = []
        for mentioned in message.mentions:
            mentioned_data = ensure_user_economy(economy_guild, mentioned.id)
            if mentioned_data.get("afk"):
                reason = mentioned_data.get("afk_reason") or "No reason provided."
                afk_mentions.append(f"{mentioned.display_name} is AFK: {reason}")
        if afk_mentions:
            await message.channel.send("\n".join(afk_mentions))
    await bot.process_commands(message)

@bot.event
async def on_voice_state_update(member, before, after):
    if member.bot or not member.guild:
        return

    if before.channel is None and after.channel is not None:
        gset, settings = get_guild_settings(member.guild.id)
        economy_guild, economy = get_economy_data(member.guild.id)
        econ_user = ensure_user_economy(economy_guild, member.id)
        if not econ_user.get("voice_bonus", True):
            return

        now = time.time()
        if now - econ_user.get("last_voice_bonus", 0) < gset.get("voice_bonus_cooldown", 300):
            return

        glevels, levels = get_level_data(member.guild.id)
        user = glevels.setdefault(str(member.id), {"xp": 0, "level": 1, "last": 0})

        bonus_xp = gset.get("voice_bonus_xp", 10)
        bonus_xp = int(bonus_xp * gset.get("xp_multiplier", 1.0))
        user["xp"] += bonus_xp
        econ_user["last_voice_bonus"] = now

        save_json(LEVEL_FILE, levels)
        save_json(ECONOMY_FILE, economy)

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

# ======================================================
# ================== NEW COMMANDS ======================
# ======================================================

@tree.command(name="daily", description="Claim daily XP and coins")
async def daily(interaction: discord.Interaction):
    glevels, levels = get_level_data(interaction.guild.id)
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    user = glevels.setdefault(str(interaction.user.id), {"xp": 0, "level": 1, "last": 0})

    now = time.time()
    if now - econ_user["last_daily"] < 86400:
        await interaction.response.send_message("⏳ You already claimed your daily. Come back later!", ephemeral=True)
        return

    if now - econ_user["last_daily"] < 172800:
        econ_user["daily_streak"] += 1
    else:
        econ_user["daily_streak"] = 1

    base_coins = 100
    base_xp = 50
    bonus = 0
    if econ_user["daily_streak"] % 7 == 0:
        bonus = 50

    econ_user["coins"] += base_coins + bonus
    user["xp"] += base_xp + bonus
    econ_user["last_daily"] = now

    save_json(LEVEL_FILE, levels)
    save_json(ECONOMY_FILE, economy)

    await interaction.response.send_message(
        f"✅ Daily claimed! +{base_coins + bonus} coins, +{base_xp + bonus} XP. 🔥 Streak: {econ_user['daily_streak']}"
    )

@tree.command(name="rep", description="Give a reputation point to someone")
async def rep(interaction: discord.Interaction, member: discord.Member):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("❌ You can't give rep to that user.", ephemeral=True)
        return

    economy_guild, economy = get_economy_data(interaction.guild.id)
    giver = ensure_user_economy(economy_guild, interaction.user.id)
    receiver = ensure_user_economy(economy_guild, member.id)

    now = time.time()
    if now - giver["rep_last"] < 86400:
        await interaction.response.send_message("⏳ You already gave rep today.", ephemeral=True)
        return

    receiver["rep"] += 1
    giver["rep_last"] = now
    save_json(ECONOMY_FILE, economy)
    await interaction.response.send_message(f"👍 {member.mention} received a rep point!")

@tree.command(name="coinflip", description="50/50 gamble for XP")
async def coinflip(interaction: discord.Interaction):
    glevels, levels = get_level_data(interaction.guild.id)
    user = glevels.setdefault(str(interaction.user.id), {"xp": 0, "level": 1, "last": 0})
    win = random.choice([True, False])
    if win:
        user["xp"] += 25
        result = "🎉 You won! +25 XP"
    else:
        result = "😅 You lost! Better luck next time."
    save_json(LEVEL_FILE, levels)
    await interaction.response.send_message(result)

@tree.command(name="8ball", description="Ask the magic 8-ball")
async def eight_ball(interaction: discord.Interaction, question: str):
    response = random.choice(EIGHT_BALL_RESPONSES)
    await interaction.response.send_message(f"🎱 {response}")

@tree.command(name="meme", description="Grab a random meme")
async def meme(interaction: discord.Interaction):
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get("https://meme-api.com/gimme") as resp:
            if resp.status != 200:
                await interaction.response.send_message("❌ Couldn't fetch a meme right now.")
                return
            data = await resp.json()
    embed = discord.Embed(title=data.get("title", "Meme"), color=discord.Color.random())
    embed.set_image(url=data.get("url"))
    await interaction.response.send_message(embed=embed)

@tree.command(name="prestige", description="Prestige when you hit max level")
async def prestige(interaction: discord.Interaction):
    glevels, levels = get_level_data(interaction.guild.id)
    gset, settings = get_guild_settings(interaction.guild.id)
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    user = glevels.setdefault(str(interaction.user.id), {"xp": 0, "level": 1, "last": 0})

    if user["level"] < gset.get("max_level", 100):
        await interaction.response.send_message("❌ You haven't hit max level yet.", ephemeral=True)
        return

    econ_user["prestige"] += 1
    badge = f"Prestige {econ_user['prestige']}"
    if badge not in econ_user["badges"]:
        econ_user["badges"].append(badge)
    user["level"] = 1
    user["xp"] = 0

    save_json(LEVEL_FILE, levels)
    save_json(ECONOMY_FILE, economy)
    save_json(SETTINGS_FILE, settings)
    await interaction.response.send_message(f"⭐ Prestige unlocked! You are now {badge}.")

@tree.command(name="levelroles", description="Show level role rewards")
async def levelroles(interaction: discord.Interaction):
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

    embed = discord.Embed(title="🏆 Level Role Rewards", description=desc, color=discord.Color.blurple())
    await interaction.response.send_message(embed=embed)

@tree.command(name="levelnotify", description="Toggle level-up messages")
async def levelnotify(interaction: discord.Interaction):
    gset, settings = get_guild_settings(interaction.guild.id)
    notify = gset.setdefault("level_notify", {}).get(str(interaction.user.id), True)
    gset["level_notify"][str(interaction.user.id)] = not notify
    save_json(SETTINGS_FILE, settings)
    status = "ON" if gset["level_notify"][str(interaction.user.id)] else "OFF"
    await interaction.response.send_message(f"🔔 Level-up messages are now {status}.", ephemeral=True)

@tree.command(name="backgrounds", description="Show unlocked rank backgrounds")
async def backgrounds(interaction: discord.Interaction):
    economy_guild, _ = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    owned = econ_user.get("backgrounds", [])
    if not owned:
        await interaction.response.send_message("You don't own any backgrounds yet.", ephemeral=True)
        return
    embed = discord.Embed(title="🎨 Your Backgrounds", description="\n".join(owned), color=discord.Color.purple())
    await interaction.response.send_message(embed=embed)

@tree.command(name="question", description="Random conversation starter")
async def question(interaction: discord.Interaction):
    await interaction.response.send_message(random.choice(CONVERSATION_STARTERS))

@tree.command(name="wouldyourather", description="Random would-you-rather question")
async def wouldyourather(interaction: discord.Interaction):
    await interaction.response.send_message(random.choice(WOULD_YOU_RATHER))

@tree.command(name="topic", description="Random debate topic")
async def topic(interaction: discord.Interaction):
    await interaction.response.send_message(random.choice(DEBATE_TOPICS))

@tree.command(name="setlevelchannel", description="Set where level-up messages post")
@app_commands.checks.has_permissions(administrator=True)
async def setlevelchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    gset, settings = get_guild_settings(interaction.guild.id)
    gset["level_channel"] = channel.id
    save_json(SETTINGS_FILE, settings)
    await interaction.response.send_message(f"✅ Level-up channel set to {channel.mention}", ephemeral=True)

@tree.command(name="setxpmultiplier", description="Set XP multiplier")
@app_commands.checks.has_permissions(administrator=True)
async def setxpmultiplier(interaction: discord.Interaction, multiplier: float):
    gset, settings = get_guild_settings(interaction.guild.id)
    gset["xp_multiplier"] = max(0.1, min(multiplier, 5.0))
    save_json(SETTINGS_FILE, settings)
    await interaction.response.send_message(f"✅ XP multiplier set to {gset['xp_multiplier']}x", ephemeral=True)

@tree.command(name="blacklistxp", description="Block XP farming in a channel")
@app_commands.checks.has_permissions(administrator=True)
async def blacklistxp(interaction: discord.Interaction, channel: discord.TextChannel):
    gset, settings = get_guild_settings(interaction.guild.id)
    if str(channel.id) not in gset["ignored_channels"]:
        gset["ignored_channels"].append(str(channel.id))
    save_json(SETTINGS_FILE, settings)
    await interaction.response.send_message(f"🚫 XP disabled in {channel.mention}", ephemeral=True)

@tree.command(name="resetuserxp", description="Reset a user's XP and level")
@app_commands.checks.has_permissions(administrator=True)
async def resetuserxp(interaction: discord.Interaction, member: discord.Member):
    glevels, levels = get_level_data(interaction.guild.id)
    glevels[str(member.id)] = {"xp": 0, "level": 1, "last": 0}
    save_json(LEVEL_FILE, levels)
    await interaction.response.send_message(f"♻️ Reset XP for {member.mention}", ephemeral=True)

@tree.command(name="balance", description="Check your coin balance")
async def balance(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    economy_guild, _ = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, member.id)
    await interaction.response.send_message(f"💰 {member.display_name} has {econ_user['coins']} coins.")

@tree.command(name="work", description="Earn coins every hour")
async def work(interaction: discord.Interaction):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    now = time.time()
    if now - econ_user["last_work"] < 3600:
        await interaction.response.send_message("⏳ You already worked recently. Try later!", ephemeral=True)
        return
    earned = random.randint(50, 150)
    econ_user["coins"] += earned
    econ_user["last_work"] = now
    save_json(ECONOMY_FILE, economy)
    await interaction.response.send_message(f"🛠️ You earned {earned} coins!")

@tree.command(name="shop", description="View the shop")
async def shop(interaction: discord.Interaction):
    lines = [f"**{name}** — {price} coins" for name, price in SHOP_BACKGROUNDS.items()]
    embed = discord.Embed(title="🛒 Background Shop", description="\n".join(lines), color=discord.Color.gold())
    await interaction.response.send_message(embed=embed)

@tree.command(name="buybackground", description="Buy a rank background")
async def buybackground(interaction: discord.Interaction, background: str):
    background = background.title()
    if background not in SHOP_BACKGROUNDS:
        await interaction.response.send_message("❌ That background isn't in the shop.", ephemeral=True)
        return
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    price = SHOP_BACKGROUNDS[background]
    if econ_user["coins"] < price:
        await interaction.response.send_message("❌ You don't have enough coins.", ephemeral=True)
        return
    if background in econ_user["backgrounds"]:
        await interaction.response.send_message("✅ You already own that background.", ephemeral=True)
        return
    econ_user["coins"] -= price
    econ_user["backgrounds"].append(background)
    save_json(ECONOMY_FILE, economy)
    await interaction.response.send_message(f"🎉 You bought the **{background}** background!")

@tree.command(name="setcolor", description="Set your rank card accent color (hex)")
async def setcolor(interaction: discord.Interaction, color_hex: str):
    if not color_hex.startswith("#") or len(color_hex) not in (4, 7):
        await interaction.response.send_message("❌ Provide a hex color like #ff00ff.", ephemeral=True)
        return
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    econ_user["color"] = color_hex
    save_json(ECONOMY_FILE, economy)
    await interaction.response.send_message(f"🎨 Color updated to {color_hex}.", ephemeral=True)

@tree.command(name="setbadge", description="Choose a badge to display")
async def setbadge(interaction: discord.Interaction, badge: str):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    if badge not in econ_user.get("badges", []):
        await interaction.response.send_message("❌ You don't own that badge.", ephemeral=True)
        return
    econ_user["badge"] = badge
    save_json(ECONOMY_FILE, economy)
    await interaction.response.send_message(f"🏅 Badge set to **{badge}**.", ephemeral=True)

@tree.command(name="profile", description="View a user's profile")
async def profile(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    glevels, _ = get_level_data(interaction.guild.id)
    economy_guild, _ = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, member.id)
    user = glevels.get(str(member.id), {"xp": 0, "level": 1})

    embed = discord.Embed(title=f"{member.display_name}'s Profile", color=discord.Color.blue())
    embed.add_field(name="Level", value=str(user.get("level", 1)))
    embed.add_field(name="XP", value=str(user.get("xp", 0)))
    embed.add_field(name="Coins", value=str(econ_user.get("coins", 0)))
    embed.add_field(name="Rep", value=str(econ_user.get("rep", 0)))
    embed.add_field(name="Prestige", value=str(econ_user.get("prestige", 0)))
    embed.add_field(name="Badge", value=econ_user.get("badge") or "None", inline=True)
    embed.add_field(name="Color", value=econ_user.get("color") or "Default", inline=True)
    embed.add_field(name="Married To", value=f"<@{econ_user['married_to']}>" if econ_user.get("married_to") else "None", inline=True)
    await interaction.response.send_message(embed=embed)

@tree.command(name="voicebonus", description="Toggle voice bonus XP")
async def voicebonus(interaction: discord.Interaction):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    econ_user["voice_bonus"] = not econ_user.get("voice_bonus", True)
    save_json(ECONOMY_FILE, economy)
    status = "ON" if econ_user["voice_bonus"] else "OFF"
    await interaction.response.send_message(f"🎧 Voice bonus is now {status}.", ephemeral=True)

@tree.command(name="afk", description="Set your AFK status")
async def afk(interaction: discord.Interaction, reason: Optional[str] = None):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    econ_user["afk"] = True
    econ_user["afk_reason"] = reason
    save_json(ECONOMY_FILE, economy)
    await interaction.response.send_message("😴 You're now AFK.", ephemeral=True)

@tree.command(name="marry", description="Marry another user")
async def marry(interaction: discord.Interaction, member: discord.Member):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("❌ You can't marry that user.", ephemeral=True)
        return
    economy_guild, economy = get_economy_data(interaction.guild.id)
    user = ensure_user_economy(economy_guild, interaction.user.id)
    partner = ensure_user_economy(economy_guild, member.id)
    if user.get("married_to") or partner.get("married_to"):
        await interaction.response.send_message("💔 Someone is already married.", ephemeral=True)
        return
    user["married_to"] = member.id
    partner["married_to"] = interaction.user.id
    save_json(ECONOMY_FILE, economy)
    await interaction.response.send_message(f"💍 {interaction.user.mention} and {member.mention} are now married!")

@tree.command(name="divorce", description="Divorce your partner (costs 500 coins)")
async def divorce(interaction: discord.Interaction):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    user = ensure_user_economy(economy_guild, interaction.user.id)
    if not user.get("married_to"):
        await interaction.response.send_message("❌ You're not married to anyone.", ephemeral=True)
        return
    if user["coins"] < 500:
        await interaction.response.send_message("❌ You need 500 coins to file for divorce.", ephemeral=True)
        return
    partner_id = user["married_to"]
    partner = ensure_user_economy(economy_guild, partner_id)
    user["coins"] -= 500
    user["married_to"] = None
    partner["married_to"] = None
    save_json(ECONOMY_FILE, economy)
    await interaction.response.send_message(
        "💔 How could you! you dirty bastard whyd you cheat?! thats it if i cant have you nobody can! *grabs shotgun*"
    )

@tree.command(name="gamblerist", description="50/50 chance to gain or lose 500 coins")
async def gamblerist(interaction: discord.Interaction):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    user = ensure_user_economy(economy_guild, interaction.user.id)
    win = random.choice([True, False])
    if win:
        user["coins"] += 500
        result = "🎲 You won! +500 coins"
    else:
        user["coins"] -= 500
        result = "🎲 You lost! -500 coins"
    save_json(ECONOMY_FILE, economy)
    await interaction.response.send_message(result)

@tree.command(name="koniheist", description="Answer a trivia question for 900 coins (20 min cooldown)")
async def koniheist(interaction: discord.Interaction):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    user = ensure_user_economy(economy_guild, interaction.user.id)
    now = time.time()
    if now - user.get("last_heist", 0) < 1200:
        await interaction.response.send_message("⏳ The heist is on cooldown. Try again later!", ephemeral=True)
        return

    trivia = random.choice(HEIST_TRIVIA)
    await interaction.response.send_message(f"🚨 Koni Heist! Answer in 10s: **{trivia['q']}**")

    def check(msg):
        return msg.author.id == interaction.user.id and msg.channel.id == interaction.channel.id

    try:
        msg = await bot.wait_for("message", timeout=10.0, check=check)
    except:
        user["coins"] -= 300
        user["last_heist"] = now
        save_json(ECONOMY_FILE, economy)
        await interaction.followup.send("🚔 You got caught by the police! -300 coins.")
        return

    if msg.content.strip().lower() == trivia["a"]:
        user["coins"] += 900
        user["last_heist"] = now
        save_json(ECONOMY_FILE, economy)
        await interaction.followup.send("💰 Heist success! +900 coins.")
    else:
        user["coins"] -= 300
        user["last_heist"] = now
        save_json(ECONOMY_FILE, economy)
        await interaction.followup.send("🚔 Wrong answer! You got caught by the police! -300 coins.")

# ================== RUN ==================
bot.run(os.getenv("DISCORD_TOKEN"))

