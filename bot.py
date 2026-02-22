import discord
from discord.ext import commands, tasks
from discord import app_commands
import os, random, io, time, asyncio
import certifi
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

# ================== INTENTS ==================
intents = discord.Intents.default()
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
tree = bot.tree

# ================== DATABASE ==================
MONGO_URI = os.getenv("MONGO_URI")

TRACKED_STORE = "tracked_roles"
LEVEL_STORE = "leveling_data"
SETTINGS_STORE = "leveling_settings"
ECONOMY_STORE = "economy_data"

mongo_client = None
store_collection = None
mongo_ready = False
store_fallback_cache = {}


def connect_to_mongo():
    global mongo_client, store_collection, mongo_ready

    if not MONGO_URI:
        print("⚠️ MONGO_URI is not set. Running with in-memory fallback storage only.")
        return

    try:
        mongo_client = MongoClient(
            MONGO_URI,
            tls=True,
            tlsCAFile=certifi.where(),
            serverSelectionTimeoutMS=3000,
        )
        db = mongo_client["discord_bot"]
        store_collection = db["stores"]
        mongo_client.admin.command("ping")
        mongo_ready = True
        print("✅ Connected to MongoDB")
    except PyMongoError as e:
        print(f"⚠️ MongoDB connection failed: {e}")
        mongo_ready = False


def load_store(name: str, default=None):
    global mongo_ready
    if default is None:
        default = {}

    if not mongo_ready or store_collection is None:
        return store_fallback_cache.get(name, default)

    try:
        doc = store_collection.find_one({"_id": name})
        if not doc:
            store_collection.insert_one({"_id": name, "data": default})
            return default
        return doc.get("data", default)
    except PyMongoError as e:
        print(f"⚠️ Mongo load failed for {name}: {e}")
        mongo_ready = False
        return store_fallback_cache.get(name, default)


def save_store(name: str, data):
    global mongo_ready
    store_fallback_cache[name] = data

    if not mongo_ready or store_collection is None:
        return

    try:
        store_collection.update_one(
            {"_id": name},
            {"$set": {"data": data}},
            upsert=True,
        )
    except PyMongoError as e:
        print(f"⚠️ Mongo save failed for {name}: {e}")
        mongo_ready = False


# ================== DEFAULT SETTINGS ==================
def default_settings():
    return {
        "xp_range": [30, 60],
        "cooldown": 2,
        "ignored_channels": [],
        "role_rewards": {},
        "levelup_bg": None,
        "rank_backgrounds": {},
        "xp_multiplier": 1.0,
        "level_channel": None,
        "level_notify": {},
        "max_level": 100,
        "voice_bonus_xp": 60,
        "voice_bonus_cooldown": 100,
        "tracked_roles": [],
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
        "married_to": None,
        "active_background": None,
    }


def get_guild_settings(guild_id):
    settings = load_store(SETTINGS_STORE, {})
    return settings.setdefault(str(guild_id), default_settings()), settings


def get_level_data(guild_id):
    levels = load_store(LEVEL_STORE, {})
    return levels.setdefault(str(guild_id), {}), levels


def get_economy_data(guild_id):
    economy = load_store(ECONOMY_STORE, {})
    return economy.setdefault(str(guild_id), {}), economy


def ensure_user_economy(economy_guild, user_id):
    uid = str(user_id)
    if uid not in economy_guild:
        economy_guild[uid] = default_economy_user()
    else:
        # Fill in any missing keys from default
        defaults = default_economy_user()
        for k, v in defaults.items():
            economy_guild[uid].setdefault(k, v)
    return economy_guild[uid]


def update_user_coins(guild_id, user_id, delta):
    economy_guild, economy = get_economy_data(guild_id)
    user = ensure_user_economy(economy_guild, user_id)
    user["coins"] = user.get("coins", 0) + delta
    save_store(ECONOMY_STORE, economy)
    return user["coins"]


def set_user_coins(guild_id, user_id, amount):
    economy_guild, economy = get_economy_data(guild_id)
    user = ensure_user_economy(economy_guild, user_id)
    user["coins"] = max(0, int(amount))
    save_store(ECONOMY_STORE, economy)
    return user["coins"]


def get_user_coins(guild_id, user_id):
    economy_guild, economy = get_economy_data(guild_id)
    user = ensure_user_economy(economy_guild, user_id)
    save_store(ECONOMY_STORE, economy)
    return user.get("coins", 0)


# ================== CONSTANTS ==================
SHOP_BACKGROUNDS = {
    "Galaxy": 500,
    "Neon": 750,
    "Forest": 300
}

EIGHT_BALL_RESPONSES = [
    "It is certain.", "Without a doubt.", "Yes - definitely.",
    "Reply hazy, try again.", "Ask again later.", "Better not tell you now.",
    "My sources say no.", "Very doubtful.", "Absolutely!", "Don't count on it."
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
    {"q": "What planet is known as the Red Planet?", "answers": ["mars", "planet mars"]},
    {"q": "How many continents are there on Earth?", "answers": ["7", "seven"]},
    {"q": "What is the capital of France?", "answers": ["paris"]},
    {"q": "Which ocean is the largest?", "answers": ["pacific", "pacific ocean"]},
    {"q": "What is 5 + 7?", "answers": ["12", "twelve"]},
    {"q": "What gas do plants absorb from the atmosphere?", "answers": ["carbon dioxide", "co2"]},
    {"q": "How many sides does a hexagon have?", "answers": ["6", "six"]},
    {"q": "What is the largest mammal in the world?", "answers": ["blue whale", "whale"]},
    {"q": "What do bees make?", "answers": ["honey"]},
    {"q": "What is the boiling point of water in Celsius?", "answers": ["100", "100c", "100 degrees"]},
    {"q": "Which planet is closest to the sun?", "answers": ["mercury"]},
    {"q": "How many days are in a leap year?", "answers": ["366"]},
    {"q": "What is the hardest natural substance on Earth?", "answers": ["diamond"]},
    {"q": "What is the main language spoken in Brazil?", "answers": ["portuguese"]},
    {"q": "What is the square root of 64?", "answers": ["8", "eight"]},
    {"q": "Which animal is known as the King of the Jungle?", "answers": ["lion"]},
    {"q": "How many letters are in the English alphabet?", "answers": ["26", "twenty six"]},
    {"q": "What is the capital of Japan?", "answers": ["tokyo"]},
    {"q": "Which planet has rings?", "answers": ["saturn"]},
    {"q": "What is 9 x 9?", "answers": ["81", "eighty one"]},
    {"q": "What is the fastest land animal?", "answers": ["cheetah"]},
    {"q": "What color do you get when you mix red and white?", "answers": ["pink"]},
    {"q": "How many hours are in a day?", "answers": ["24", "twenty four"]},
    {"q": "What is the largest continent?", "answers": ["asia"]},
    {"q": "Which instrument has keys, pedals, and strings?", "answers": ["piano"]},
    {"q": "What is the freezing point of water in Celsius?", "answers": ["0", "zero"]},
    {"q": "What is the tallest animal in the world?", "answers": ["giraffe"]},
    {"q": "Which planet is known for its big red spot?", "answers": ["jupiter"]},
    {"q": "How many weeks are in a year?", "answers": ["52", "fifty two"]},
    {"q": "What is 15 divided by 3?", "answers": ["5", "five"]},
    {"q": "What is the capital of the United States?", "answers": ["washington dc", "washington d.c.", "dc"]},
    {"q": "How many minutes are in an hour?", "answers": ["60", "sixty"]},
    {"q": "What shape has three sides?", "answers": ["triangle"]},
    {"q": "What is H2O commonly known as?", "answers": ["water"]},
    {"q": "What is the largest planet in our solar system?", "answers": ["jupiter"]},
    {"q": "What do you call a baby cat?", "answers": ["kitten"]},
    {"q": "What is 10 squared?", "answers": ["100", "one hundred"]},
    {"q": "Which continent is Egypt in?", "answers": ["africa"]},
    {"q": "What is the opposite of hot?", "answers": ["cold"]},
    {"q": "How many months are in a year?", "answers": ["12", "twelve"]},
    {"q": "What is the capital of Canada?", "answers": ["ottawa"]},
    {"q": "Which animal can fly and is a mammal?", "answers": ["bat", "bats"]},
    {"q": "What is the currency used in Japan?", "answers": ["yen"]},
    {"q": "How many legs does a spider have?", "answers": ["8", "eight"]},
    {"q": "What is the tallest mountain in the world?", "answers": ["mount everest", "everest"]},
    {"q": "What is 3 x 4?", "answers": ["12", "twelve"]},
    {"q": "What galaxy do we live in?", "answers": ["milky way", "the milky way"]},
    {"q": "What is the main star of our solar system?", "answers": ["sun", "the sun"]},
    {"q": "How many bones are in the adult human body?", "answers": ["206"]},
    {"q": "What is the capital of Italy?", "answers": ["rome"]},
]

LAUGH_IMAGE_URL = "https://media.giphy.com/media/10JhviFuU2gWD6/giphy.gif"

HELP_COMMANDS = [
    {"name": "daily", "usage": "/daily", "desc": "Claim daily XP and coins."},
    {"name": "rep", "usage": "/rep @user", "desc": "Give a reputation point."},
    {"name": "coinflip", "usage": "/coinflip", "desc": "50/50 gamble for XP."},
    {"name": "8ball", "usage": "/8ball <question>", "desc": "Magic 8-ball response."},
    {"name": "meme", "usage": "/meme", "desc": "Fetch a random meme."},
    {"name": "question", "usage": "/question", "desc": "Conversation starter."},
    {"name": "wouldyourather", "usage": "/wouldyourather", "desc": "Random WYR."},
    {"name": "topic", "usage": "/topic", "desc": "Random debate topic."},
    {"name": "prestige", "usage": "/prestige", "desc": "Prestige at max level."},
    {"name": "levelroles", "usage": "/levelroles", "desc": "Show level role rewards."},
    {"name": "levelnotify", "usage": "/levelnotify", "desc": "Toggle level-up messages."},
    {"name": "backgrounds", "usage": "/backgrounds", "desc": "Show unlocked backgrounds."},
    {"name": "setlevelchannel", "usage": "/setlevelchannel #channel", "desc": "Set level-up channel."},
    {"name": "setxpmultiplier", "usage": "/setxpmultiplier <num>", "desc": "Set XP multiplier."},
    {"name": "blacklistxp", "usage": "/blacklistxp #channel", "desc": "Block XP in channel."},
    {"name": "resetuserxp", "usage": "/resetuserxp @user", "desc": "Reset user XP."},
    {"name": "setlevel", "usage": "/setlevel @user <level> [xp]", "desc": "Admin: set user level/xp."},
    {"name": "balance", "usage": "/balance [@user]", "desc": "Check coin balance."},
    {"name": "givecoins", "usage": "/givecoins @user <amount>", "desc": "Admin: give coins to a user."},
    {"name": "setbalance", "usage": "/setbalance @user <amount>", "desc": "Admin: set a user coin balance."},
    {"name": "work", "usage": "/work", "desc": "Earn coins hourly."},
    {"name": "shop", "usage": "/shop", "desc": "View shop items."},
    {"name": "buybackground", "usage": "/buybackground <name>", "desc": "Buy a background."},
    {"name": "setcolor", "usage": "/setcolor #hex", "desc": "Set rank card color."},
    {"name": "setbadge", "usage": "/setbadge <badge>", "desc": "Set profile badge."},
    {"name": "profile", "usage": "/profile [@user]", "desc": "View user profile."},
    {"name": "voicebonus", "usage": "/voicebonus", "desc": "Toggle voice XP bonus."},
    {"name": "afk", "usage": "/afk [reason]", "desc": "Set AFK status."},
    {"name": "marry", "usage": "/marry @user", "desc": "Marry a user."},
    {"name": "divorce", "usage": "/divorce", "desc": "Divorce for 500 coins."},
    {"name": "gamblerist", "usage": "/gamblerist", "desc": "50/50 ±500 coins."},
    {"name": "koniheist", "usage": "/koniheist", "desc": "Trivia heist for coins."},
    {"name": "roast", "usage": "/roast @user", "desc": "Roast someone."},
    {"name": "rank", "usage": "/rank [@user]", "desc": "Show rank card."},
    {"name": "leaderboard", "usage": "/leaderboard", "desc": "Show leaderboard."},
    {"name": "setxp", "usage": "/setxp <min> <max>", "desc": "Set XP range."},
    {"name": "setcooldown", "usage": "/setcooldown <seconds>", "desc": "Set XP cooldown."},
    {"name": "setrankbackground", "usage": "/setrankbackground <background>", "desc": "Set rank background."},
    {"name": "setlevelupbackground", "usage": "/setlevelupbackground <url>", "desc": "Set level-up background URL."},
    {"name": "setrolereward", "usage": "/setrolereward <level> @role", "desc": "Set role reward."},
    {"name": "removerolereward", "usage": "/removerolereward <level>", "desc": "Remove role reward."},
    {"name": "rolerewards", "usage": "/rolerewards", "desc": "List role rewards."},
    {"name": "trackrole", "usage": "/trackrole @role", "desc": "Restrict XP to a role."},
    {"name": "untrackrole", "usage": "/untrackrole @role", "desc": "Remove XP role restriction."},
    {"name": "trackrolelist", "usage": "/trackrolelist", "desc": "List XP-restricted roles."},
    {"name": "trackroleall", "usage": "/trackroleall", "desc": "Allow XP for all roles."},
]

ROAST_LINES = [
    "If laughs were XP, you'd still be level 1.",
    "You're the human version of a loading screen.",
    "Somewhere out there, a tutorial is missing its beginner.",
    "You bring everyone so much joy... when you leave.",
    "If effort was currency, you'd be broke.",
    "You're the reason the mute button was invented.",
    "You're like a cloud — when you disappear, it's a beautiful day.",
    "Your secrets are always safe with me. I never even listen.",
    "You're proof that even NPCs can glitch.",
    "If there were awards for awkward, you'd place second.",
    "You're the main character... in a very short story.",
    "Your Wi-Fi has more range than your personality.",
    "You're the filler episode of this server.",
    "You're like a broken pencil — pointless.",
    "You have something on your chin... no, the third one down.",
    "You're the reason keyboards have a backspace key.",
    "You're a candle in the wind... unhelpful and flickery.",
    "Your rank should be \"Apprentice Disappointment.\"",
    "You're not stupid; you just have bad luck thinking.",
    "You're the loudest whisper I've ever heard.",
    "You're a DLC nobody asked for.",
    "You make an excellent before photo.",
    "You're the reason coffee needs caffeine.",
    "You're about as useful as a screen door on a submarine.",
    "If charisma were coins, you'd owe the bank.",
    "You're the human equivalent of a typo.",
    "You're not the sharpest sword in the inventory.",
    "You're why the \"skip intro\" button exists.",
    "You're a walking lag spike.",
    "You're a bold move that didn't pay off.",
    "You're the aftertaste of sparkling water.",
    "You're the background noise of life.",
    "You have the energy of a dial-up modem.",
    "You're the tutorial boss of mediocrity.",
    "You're like a phone at 1% — never useful when needed.",
    "You're the reason we need patch notes.",
    "You're a full-time side quest.",
    "You sparkle... like a broken TV.",
    "You're the first draft of a bad idea.",
    "Your vibe is \"insert coin to continue.\"",
    "You're a speed bump in human form.",
    "You're as bright as a burnt-out lightbulb.",
    "Your confidence is louder than your talent.",
    "You have the depth of a puddle on a hot day.",
    "You're the human form of \"buffering.\"",
    "You're a walking \"404: personality not found.\"",
    "You're the cardboard cutout of cool.",
    "You're a broken compass — always wrong and still confident.",
    "You're the type to misspell your own name.",
    "You're a checklist with nothing checked.",
    "You're a meme without the funny.",
]


# ================== HELPERS ==================
def help_embed():
    categories = {
        "🎮 Fun / Social": ["daily", "rep", "coinflip", "8ball", "meme", "roast"],
        "🏆 Leveling": ["rank", "leaderboard", "prestige", "levelroles", "levelnotify", "backgrounds"],
        "💬 Chat Boosters": ["question", "wouldyourather", "topic"],
        "🛠️ Admin": ["setlevelchannel", "setxpmultiplier", "blacklistxp", "resetuserxp", "setlevel", "setxp", "setcooldown"],
        "💰 Economy": ["balance", "givecoins", "setbalance", "work", "shop", "buybackground", "gamblerist", "koniheist", "divorce"],
        "🎨 Cosmetics": ["setcolor", "setbadge", "profile", "voicebonus", "afk", "marry"],
        "📌 Role Tracking": ["trackrole", "untrackrole", "trackrolelist", "trackroleall"],
        "🖼️ Backgrounds": ["setrankbackground", "setlevelupbackground", "setrolereward", "removerolereward", "rolerewards"]
    }
    embed = discord.Embed(
        title="📖 Command Center",
        description="Use the buttons below to run popular commands, or select one from the dropdown for details.",
        color=discord.Color.blurple()
    )
    for title, items in categories.items():
        embed.add_field(name=title, value=", ".join(items), inline=False)
    return embed


def command_lookup(name):
    for cmd in HELP_COMMANDS:
        if cmd["name"] == name:
            return cmd
    return None


async def send_response(interaction, content=None, embed=None, ephemeral=False, file=None):
    payload = {"content": content, "embed": embed, "ephemeral": ephemeral}
    if file is not None:
        payload["file"] = file
    if interaction.response.is_done():
        await interaction.followup.send(**payload)
    else:
        await interaction.response.send_message(**payload)


# ================== HELP UI ==================
class HelpSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(
            placeholder="Select a command for details...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        cmd = command_lookup(self.values[0])
        if not cmd:
            await interaction.response.send_message("Command not found.", ephemeral=True)
            return
        embed = discord.Embed(title=f"/{cmd['name']}", description=cmd["desc"], color=discord.Color.green())
        embed.add_field(name="Usage", value=cmd["usage"], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        options = [discord.SelectOption(label=c["name"], value=c["name"], description=c["desc"][:100]) for c in HELP_COMMANDS]
        first = options[:25]
        second = options[25:]
        if first:
            self.add_item(HelpSelect(first))
        if second:
            self.add_item(HelpSelect(second))

    @discord.ui.button(label="Daily", style=discord.ButtonStyle.primary, emoji="🎁")
    async def daily_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await tree.get_command("daily").callback(interaction)

    @discord.ui.button(label="Coinflip", style=discord.ButtonStyle.secondary, emoji="🪙")
    async def coinflip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await tree.get_command("coinflip").callback(interaction)

    @discord.ui.button(label="Meme", style=discord.ButtonStyle.secondary, emoji="😂")
    async def meme_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await tree.get_command("meme").callback(interaction)

    @discord.ui.button(label="Question", style=discord.ButtonStyle.secondary, emoji="❓")
    async def question_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await tree.get_command("question").callback(interaction)

    @discord.ui.button(label="Would You Rather", style=discord.ButtonStyle.secondary, emoji="🤔")
    async def wyr_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await tree.get_command("wouldyourather").callback(interaction)

    @discord.ui.button(label="Topic", style=discord.ButtonStyle.secondary, emoji="💬")
    async def topic_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await tree.get_command("topic").callback(interaction)

    @discord.ui.button(label="Balance", style=discord.ButtonStyle.secondary, emoji="💰")
    async def balance_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await tree.get_command("balance").callback(interaction)

    @discord.ui.button(label="Work", style=discord.ButtonStyle.secondary, emoji="🛠️")
    async def work_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await tree.get_command("work").callback(interaction)


# ================== LEVEL SYSTEM ==================
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

    draw.text((250, 70), f"{member.display_name} reached Level {level}!", font=font, fill=(255, 255, 255))

    buf.seek(0)
    av = Image.open(buf).convert("RGBA").resize((120, 120))
    mask = av.split()[3]  # extract alpha channel as mask
    bg.paste(av, (50, 40), mask)

    out = io.BytesIO()
    bg.save(out, "PNG")
    out.seek(0)
    return out


async def apply_level_ups(message: discord.Message, user: dict, gset: dict, levels, settings):
    leveled_up = False
    while user["xp"] >= xp_needed(user["level"]):
        user["xp"] -= xp_needed(user["level"])
        user["level"] += 1
        leveled_up = True

        reward = gset["role_rewards"].get(str(user["level"]))
        if reward:
            role = message.guild.get_role(int(reward))
            if role:
                try:
                    await message.author.add_roles(role)
                except discord.HTTPException:
                    pass

        level_notify = gset.get("level_notify", {}).get(str(message.author.id), True)
        if level_notify:
            img = await create_levelup_image(message.author, user["level"], gset.get("levelup_bg"))
            level_channel_id = gset.get("level_channel")
            level_channel = message.guild.get_channel(level_channel_id) if level_channel_id else message.channel
            try:
                await level_channel.send(
                    f"🎉 {message.author.mention} reached Level {user['level']}!",
                    file=discord.File(img, "levelup.png")
                )
            except discord.HTTPException:
                pass

    if leveled_up:
        save_store(LEVEL_STORE, levels)


# ================== EVENTS ==================
@bot.event
async def on_ready():
    connect_to_mongo()

    print("🔄 Syncing commands globally...")
    try:
        synced = await tree.sync()
        print(f"✅ Synced {len(synced)} commands globally")
    except Exception as e:
        print(f"❌ Sync error: {e}")

    if not auto_update_tracked_roles.is_running():
        auto_update_tracked_roles.start()

    print(f"🤖 Logged in as {bot.user}")


@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return

    gset, settings = get_guild_settings(message.guild.id)
    glevels, levels = get_level_data(message.guild.id)
    economy_guild, economy = get_economy_data(message.guild.id)
    econ_user = ensure_user_economy(economy_guild, message.author.id)

    # AFK mention detection
    if message.mentions:
        afk_mentions = []
        for mentioned in message.mentions:
            mentioned_data = ensure_user_economy(economy_guild, mentioned.id)
            if mentioned_data.get("afk"):
                reason = mentioned_data.get("afk_reason") or "No reason provided."
                afk_mentions.append(f"{mentioned.display_name} is AFK: {reason}")
        if afk_mentions:
            try:
                await message.channel.send("\n".join(afk_mentions))
            except discord.HTTPException:
                pass

    # Clear AFK if user sends a message
    if econ_user.get("afk"):
        econ_user["afk"] = False
        econ_user["afk_reason"] = None
        save_store(ECONOMY_STORE, economy)
        try:
            await message.channel.send(f"👋 Welcome back, {message.author.mention}! Your AFK is now off.")
        except discord.HTTPException:
            pass

    # XP logic
    tracked_roles = gset.get("tracked_roles", [])
    if tracked_roles:
        if not any(role.id in tracked_roles for role in message.author.roles):
            await bot.process_commands(message)
            return

    if str(message.channel.id) in gset.get("ignored_channels", []):
        await bot.process_commands(message)
        return

    user = glevels.setdefault(str(message.author.id), {"xp": 0, "level": 1, "last": 0})

    cooldown = gset.get("cooldown", gset.get("xp_cooldown", 2))
    if time.time() - user.get("last", 0) < cooldown:
        await bot.process_commands(message)
        return

    user["last"] = time.time()
    gained_xp = random.randint(*gset["xp_range"])
    gained_xp = int(gained_xp * gset.get("xp_multiplier", 1.0))
    user["xp"] += gained_xp

    await apply_level_ups(message, user, gset, levels, settings)
    save_store(LEVEL_STORE, levels)
    save_store(ECONOMY_STORE, economy)

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

        save_store(LEVEL_STORE, levels)
        save_store(ECONOMY_STORE, economy)


@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        await send_response(interaction, "❌ You do not have permission to use this command.", ephemeral=True)
        return
    if isinstance(error, app_commands.errors.CommandOnCooldown):
        await send_response(interaction, f"⏳ Command is on cooldown. Try again in {error.retry_after:.1f}s.", ephemeral=True)
        return
    if isinstance(error, app_commands.errors.TransformerError):
        await send_response(interaction, "❌ Invalid option or argument. Please check command inputs.", ephemeral=True)
        return
    print(f"❌ App command error: {error}")
    await send_response(interaction, "❌ Something went wrong while running that command.", ephemeral=True)


# ================== BACKGROUND TASKS ==================
@tasks.loop(minutes=5)
async def auto_update_tracked_roles():
    data = load_store(TRACKED_STORE, {})
    for guild in bot.guilds:
        gid = str(guild.id)
        guild_data = data.get(gid, {})
        for rid, info in guild_data.items():
            if not rid.isdigit():
                continue
            role = guild.get_role(int(rid))
            if not role:
                continue
            try:
                ch = guild.get_channel(info["channel"])
                if ch:
                    msg = await ch.fetch_message(info["message"])
                    count = sum(1 for m in guild.members if role in m.roles)
                    embed = discord.Embed(
                        title="📊 Role Count",
                        description=f"{role.mention}\n👥 Members: {count}",
                        color=role.color if role.color.value else discord.Color.blurple()
                    )
                    await msg.edit(embed=embed)
            except Exception:
                pass

        list_info = guild_data.get("_list")
        if list_info:
            role_ids = [int(rid) for rid in guild_data if rid.isdigit()]
            try:
                ch = guild.get_channel(list_info["channel"])
                if ch:
                    msg = await ch.fetch_message(list_info["message"])
                    desc_lines = []
                    for rid in role_ids:
                        role = guild.get_role(rid)
                        if role:
                            count = sum(1 for m in guild.members if role in m.roles)
                            desc_lines.append(f"{role.mention} — {count} members")
                    if not desc_lines:
                        desc_lines = ["No roles are currently tracked."]
                    embed = discord.Embed(
                        title="📌 Tracked Roles",
                        description="\n".join(desc_lines),
                        color=discord.Color.blurple()
                    )
                    await msg.edit(embed=embed)
            except Exception:
                pass


# ================== RANK CARD ==================
def create_animated_rank_card(member, level, xp, required_xp, avatar_path, bg_path=None):
    width, height = 800, 250
    frames = []
    percent = xp / required_xp if required_xp else 0

    avatar = Image.open(avatar_path).resize((180, 180)).convert("RGBA")

    for i in range(15):
        if bg_path and os.path.exists(bg_path):
            base = Image.open(bg_path).convert("RGB").resize((width, height))
        else:
            base = Image.new("RGB", (width, height), (30, 30, 30))

        draw = ImageDraw.Draw(base)
        bar_width = int(500 * percent * (i / 14))

        draw.rectangle((250, 150, 750, 190), fill=(50, 50, 50))
        draw.rectangle((250, 150, 250 + bar_width, 190), fill=(120, 0, 255))
        draw.text((250, 50), member.name, fill="white")
        draw.text((250, 90), f"Level {level}", fill="white")
        draw.text((250, 120), f"{xp}/{required_xp} XP", fill="white")
        base.paste(avatar, (40, 35), avatar)
        frames.append(base)

    path = f"/tmp/rank_{member.id}.gif"
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=60, loop=0)
    return path


# ================== SLASH COMMANDS ==================

@tree.command(name="rank", description="View your animated rank card")
async def rank(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    levels = load_store(LEVEL_STORE, {})
    settings = load_store(SETTINGS_STORE, {})
    gid, uid = str(interaction.guild.id), str(member.id)

    user = levels.get(gid, {}).get(uid)
    if not user:
        await interaction.response.send_message("No level data yet!", ephemeral=True)
        return

    await interaction.response.defer()

    avatar_path = f"/tmp/avatar_{uid}.png"
    await member.display_avatar.save(avatar_path)

    bg_path = settings.get(gid, {}).get("rank_backgrounds", {}).get(uid)
    required = xp_needed(user["level"])
    gif = create_animated_rank_card(member, user["level"], user["xp"], required, avatar_path, bg_path)
    await interaction.followup.send(file=discord.File(gif))


@tree.command(name="leaderboard", description="View top level members")
async def leaderboard(interaction: discord.Interaction):
    glevels, _ = get_level_data(interaction.guild.id)

    if not glevels:
        await interaction.response.send_message("No leaderboard data yet.")
        return

    sorted_users = sorted(
        glevels.items(),
        key=lambda x: (x[1].get("level", 1), x[1].get("xp", 0)),
        reverse=True
    )[:10]

    embed = discord.Embed(title="🏆 Level Leaderboard", color=discord.Color.gold())
    for i, (user_id, data) in enumerate(sorted_users, start=1):
        member = interaction.guild.get_member(int(user_id))
        if member:
            embed.add_field(
                name=f"{i}. {member.display_name}",
                value=f"Level {data.get('level', 1)} | {data.get('xp', 0)} XP",
                inline=False
            )

    await interaction.response.send_message(embed=embed)


@tree.command(name="setxp", description="Set XP range per message")
@app_commands.checks.has_permissions(administrator=True)
async def setxp(interaction: discord.Interaction, min_xp: int, max_xp: int):
    gset, settings = get_guild_settings(interaction.guild.id)
    gset["xp_range"] = [min_xp, max_xp]
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message("✅ XP range updated.", ephemeral=True)


@tree.command(name="setcooldown", description="Set XP message cooldown (seconds)")
@app_commands.checks.has_permissions(administrator=True)
async def setcooldown(interaction: discord.Interaction, seconds: int):
    if seconds < 0:
        await interaction.response.send_message("❌ Cooldown must be 0 or higher.", ephemeral=True)
        return
    gset, settings = get_guild_settings(interaction.guild.id)
    gset["cooldown"] = seconds
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message(f"⏳ Cooldown updated to {seconds}s.", ephemeral=True)


@tree.command(name="setrankbackground", description="Set your active rank background")
async def setrankbackground(interaction: discord.Interaction, background: str):
    background = background.title()
    economy_guild, economy = get_economy_data(interaction.guild.id)
    user = ensure_user_economy(economy_guild, interaction.user.id)

    if background not in user.get("backgrounds", []):
        await interaction.response.send_message("❌ You don't own that background.", ephemeral=True)
        return

    user["active_background"] = background
    save_store(ECONOMY_STORE, economy)
    await interaction.response.send_message(f"🎨 Rank background set to **{background}**.", ephemeral=True)


@tree.command(name="setlevelupbackground", description="Set level-up image background URL (admin)")
@app_commands.checks.has_permissions(administrator=True)
async def setlevelupbackground(interaction: discord.Interaction, image_url: str):
    gset, settings = get_guild_settings(interaction.guild.id)
    gset["levelup_bg"] = image_url
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message("✅ Level-up background updated.", ephemeral=True)


@tree.command(name="setrolereward", description="Give a role when a user reaches a level")
@app_commands.checks.has_permissions(administrator=True)
async def setrolereward(interaction: discord.Interaction, level: int, role: discord.Role):
    gset, settings = get_guild_settings(interaction.guild.id)
    gset["role_rewards"][str(level)] = role.id
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message(f"🎁 {role.mention} will be given at Level {level}.", ephemeral=True)


@tree.command(name="removerolereward", description="Remove a level role reward")
@app_commands.checks.has_permissions(administrator=True)
async def removerolereward(interaction: discord.Interaction, level: int):
    gset, settings = get_guild_settings(interaction.guild.id)
    rewards = gset.get("role_rewards", {})
    if str(level) not in rewards:
        await interaction.response.send_message("❌ No reward set for that level.", ephemeral=True)
        return
    del rewards[str(level)]
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message(f"🗑️ Removed reward for level {level}.", ephemeral=True)


@tree.command(name="rolerewards", description="View configured level role rewards")
async def rolerewards(interaction: discord.Interaction):
    gset, _ = get_guild_settings(interaction.guild.id)
    rewards = gset.get("role_rewards", {})
    if not rewards:
        await interaction.response.send_message("No level rewards configured.")
        return
    embed = discord.Embed(title="🏆 Level Role Rewards", color=discord.Color.green())
    for level, role_id in sorted(rewards.items(), key=lambda x: int(x[0])):
        role = interaction.guild.get_role(int(role_id))
        if role:
            embed.add_field(name=f"Level {level}", value=role.mention, inline=False)
    await interaction.response.send_message(embed=embed)


@tree.command(name="daily", description="Claim daily XP and coins")
async def daily(interaction: discord.Interaction):
    glevels, levels = get_level_data(interaction.guild.id)
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    user = glevels.setdefault(str(interaction.user.id), {"xp": 0, "level": 1, "last": 0})

    now = time.time()
    if now - econ_user["last_daily"] < 86400:
        await send_response(interaction, "⏳ You already claimed your daily. Come back later!", ephemeral=True)
        return

    if now - econ_user["last_daily"] < 172800:
        econ_user["daily_streak"] += 1
    else:
        econ_user["daily_streak"] = 1

    base_coins = 100
    base_xp = 50
    bonus = 50 if econ_user["daily_streak"] % 7 == 0 else 0

    econ_user["coins"] += base_coins + bonus
    user["xp"] += base_xp + bonus
    econ_user["last_daily"] = now

    save_store(LEVEL_STORE, levels)
    save_store(ECONOMY_STORE, economy)
    await send_response(
        interaction,
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
    save_store(ECONOMY_STORE, economy)
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
    save_store(LEVEL_STORE, levels)
    await send_response(interaction, result)


@tree.command(name="8ball", description="Ask the magic 8-ball")
async def eight_ball(interaction: discord.Interaction, question: str):
    await interaction.response.send_message(f"🎱 {random.choice(EIGHT_BALL_RESPONSES)}")


@tree.command(name="meme", description="Grab a random meme")
async def meme(interaction: discord.Interaction):
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get("https://meme-api.com/gimme") as resp:
            if resp.status != 200:
                await send_response(interaction, "❌ Couldn't fetch a meme right now.")
                return
            data = await resp.json()
    embed = discord.Embed(title=data.get("title", "Meme"), color=discord.Color.random())
    embed.set_image(url=data.get("url"))
    await send_response(interaction, embed=embed)


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

    save_store(LEVEL_STORE, levels)
    save_store(ECONOMY_STORE, economy)
    await interaction.response.send_message(f"⭐ Prestige unlocked! You are now {badge}.")


@tree.command(name="levelroles", description="Show level role rewards")
async def levelroles(interaction: discord.Interaction):
    gset, _ = get_guild_settings(interaction.guild.id)
    rewards = gset.get("role_rewards", {})
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
    save_store(SETTINGS_STORE, settings)
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
    await send_response(interaction, random.choice(CONVERSATION_STARTERS))


@tree.command(name="wouldyourather", description="Random would-you-rather question")
async def wouldyourather(interaction: discord.Interaction):
    await send_response(interaction, random.choice(WOULD_YOU_RATHER))


@tree.command(name="topic", description="Random debate topic")
async def topic(interaction: discord.Interaction):
    await send_response(interaction, random.choice(DEBATE_TOPICS))


@tree.command(name="setlevelchannel", description="Set where level-up messages post")
@app_commands.checks.has_permissions(administrator=True)
async def setlevelchannel(interaction: discord.Interaction, channel: discord.TextChannel):
    gset, settings = get_guild_settings(interaction.guild.id)
    gset["level_channel"] = channel.id
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message(f"✅ Level-up channel set to {channel.mention}", ephemeral=True)


@tree.command(name="setxpmultiplier", description="Set XP multiplier")
@app_commands.checks.has_permissions(administrator=True)
async def setxpmultiplier(interaction: discord.Interaction, multiplier: float):
    gset, settings = get_guild_settings(interaction.guild.id)
    gset["xp_multiplier"] = max(0.1, min(multiplier, 5.0))
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message(f"✅ XP multiplier set to {gset['xp_multiplier']}x", ephemeral=True)


@tree.command(name="blacklistxp", description="Block XP farming in a channel")
@app_commands.checks.has_permissions(administrator=True)
async def blacklistxp(interaction: discord.Interaction, channel: discord.TextChannel):
    gset, settings = get_guild_settings(interaction.guild.id)
    if str(channel.id) not in gset["ignored_channels"]:
        gset["ignored_channels"].append(str(channel.id))
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message(f"🚫 XP disabled in {channel.mention}", ephemeral=True)


@tree.command(name="resetuserxp", description="Reset a user's XP and level")
@app_commands.checks.has_permissions(administrator=True)
async def resetuserxp(interaction: discord.Interaction, member: discord.Member):
    glevels, levels = get_level_data(interaction.guild.id)
    glevels[str(member.id)] = {"xp": 0, "level": 1, "last": 0}
    save_store(LEVEL_STORE, levels)
    await interaction.response.send_message(f"♻️ Reset XP for {member.mention}", ephemeral=True)


@tree.command(name="setlevel", description="Admin: Set a user's level and optional XP")
@app_commands.checks.has_permissions(administrator=True)
async def setlevel(interaction: discord.Interaction, member: discord.Member, level: int, xp: int = 0):
    glevels, levels = get_level_data(interaction.guild.id)
    glevels[str(member.id)] = {
        "xp": max(0, int(xp)),
        "level": max(1, int(level)),
        "last": glevels.get(str(member.id), {}).get("last", 0),
    }
    save_store(LEVEL_STORE, levels)
    await interaction.response.send_message(
        f"✅ Set {member.mention} to level {max(1, int(level))} with {max(0, int(xp))} XP.", ephemeral=True
    )


@tree.command(name="balance", description="Check your coin balance")
async def balance(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    coins = get_user_coins(interaction.guild.id, member.id)
    await send_response(interaction, f"💰 {member.display_name} has {coins} coins.")


@tree.command(name="givecoins", description="Admin: Give coins to a user")
@app_commands.checks.has_permissions(administrator=True)
async def givecoins(interaction: discord.Interaction, member: discord.Member, amount: int):
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
        return
    new_balance = update_user_coins(interaction.guild.id, member.id, amount)
    await interaction.response.send_message(f"✅ Gave {amount} coins to {member.mention}. New balance: {new_balance}", ephemeral=True)


@tree.command(name="setbalance", description="Admin: Set a user's coin balance")
@app_commands.checks.has_permissions(administrator=True)
async def setbalance(interaction: discord.Interaction, member: discord.Member, amount: int):
    new_balance = set_user_coins(interaction.guild.id, member.id, amount)
    await interaction.response.send_message(f"✅ Set {member.mention}'s balance to {new_balance} coins.", ephemeral=True)


@tree.command(name="work", description="Earn coins every hour")
async def work(interaction: discord.Interaction):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    now = time.time()
    if now - econ_user["last_work"] < 3600:
        await send_response(interaction, "⏳ You already worked recently. Try later!", ephemeral=True)
        return
    earned = random.randint(50, 150)
    econ_user["coins"] += earned
    econ_user["last_work"] = now
    save_store(ECONOMY_STORE, economy)
    await send_response(interaction, f"🛠️ You earned {earned} coins!")


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
    save_store(ECONOMY_STORE, economy)
    await interaction.response.send_message(f"🎉 You bought the **{background}** background!")


@tree.command(name="setcolor", description="Set your rank card accent color (hex)")
async def setcolor(interaction: discord.Interaction, color_hex: str):
    if not color_hex.startswith("#") or len(color_hex) not in (4, 7):
        await interaction.response.send_message("❌ Provide a hex color like #ff00ff.", ephemeral=True)
        return
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    econ_user["color"] = color_hex
    save_store(ECONOMY_STORE, economy)
    await interaction.response.send_message(f"🎨 Color updated to {color_hex}.", ephemeral=True)


@tree.command(name="setbadge", description="Choose a badge to display")
async def setbadge(interaction: discord.Interaction, badge: str):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    if badge not in econ_user.get("badges", []):
        await interaction.response.send_message("❌ You don't own that badge.", ephemeral=True)
        return
    econ_user["badge"] = badge
    save_store(ECONOMY_STORE, economy)
    await interaction.response.send_message(f"🏅 Badge set to **{badge}**.", ephemeral=True)


@tree.command(name="profile", description="View a user's profile")
async def profile(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    glevels, _ = get_level_data(interaction.guild.id)
    economy_guild, _ = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, member.id)
    user = glevels.get(str(interaction.guild.id), {}).get(str(member.id), {"xp": 0, "level": 1})

    embed = discord.Embed(title=f"{member.display_name}'s Profile", color=discord.Color.blue())
    embed.add_field(name="Level", value=str(user.get("level", 1)))
    embed.add_field(name="XP", value=str(user.get("xp", 0)))
    embed.add_field(name="Coins", value=str(econ_user.get("coins", 0)))
    embed.add_field(name="Rep", value=str(econ_user.get("rep", 0)))
    embed.add_field(name="Prestige", value=str(econ_user.get("prestige", 0)))
    embed.add_field(name="Badge", value=econ_user.get("badge") or "None", inline=True)
    embed.add_field(name="Color", value=econ_user.get("color") or "Default", inline=True)
    embed.add_field(
        name="Married To",
        value=f"<@{econ_user['married_to']}>" if econ_user.get("married_to") else "None",
        inline=True
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="voicebonus", description="Toggle voice bonus XP")
async def voicebonus(interaction: discord.Interaction):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    econ_user["voice_bonus"] = not econ_user.get("voice_bonus", True)
    save_store(ECONOMY_STORE, economy)
    status = "ON" if econ_user["voice_bonus"] else "OFF"
    await interaction.response.send_message(f"🎧 Voice bonus is now {status}.", ephemeral=True)


@tree.command(name="afk", description="Set your AFK status")
async def afk(interaction: discord.Interaction, reason: Optional[str] = None):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    econ_user["afk"] = True
    econ_user["afk_reason"] = reason
    save_store(ECONOMY_STORE, economy)
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
    save_store(ECONOMY_STORE, economy)
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
    save_store(ECONOMY_STORE, economy)
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
        user["coins"] = max(0, user["coins"] - 500)
        result = "🎲 You lost! -500 coins"
    save_store(ECONOMY_STORE, economy)
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
    answers = {answer.strip().lower() for answer in trivia.get("answers", [])}
    await interaction.response.send_message(f"🚨 Koni Heist! Answer in 10s: **{trivia['q']}**\n⏱️ Time left: **10**")
    prompt = await interaction.original_response()

    countdown_stop = asyncio.Event()

    async def countdown_task():
        for remaining in range(9, 0, -1):
            if countdown_stop.is_set():
                return
            await asyncio.sleep(1)
            if countdown_stop.is_set():
                return
            try:
                await prompt.edit(content=f"🚨 Koni Heist! Answer in 10s: **{trivia['q']}**\n⏱️ Time left: **{remaining}**")
            except discord.HTTPException:
                return

    countdown = asyncio.create_task(countdown_task())

    def check(msg):
        return msg.author.id == interaction.user.id and msg.channel.id == interaction.channel.id

    try:
        msg = await bot.wait_for("message", timeout=10.0, check=check)
        countdown_stop.set()
        await countdown
    except asyncio.TimeoutError:
        countdown_stop.set()
        await countdown
        user["last_heist"] = now
        save_store(ECONOMY_STORE, economy)
        new_balance = update_user_coins(interaction.guild.id, interaction.user.id, -300)
        await interaction.followup.send(f"🚔 You got caught by the police! -300 coins. Balance: {new_balance}")
        return

    user["last_heist"] = now
    save_store(ECONOMY_STORE, economy)

    if msg.content.strip().lower() in answers:
        new_balance = update_user_coins(interaction.guild.id, interaction.user.id, 900)
        await interaction.followup.send(f"💰 Heist success! +900 coins. New balance: {new_balance}")
    else:
        new_balance = update_user_coins(interaction.guild.id, interaction.user.id, -300)
        await interaction.followup.send(f"🚔 Wrong answer! -300 coins. New balance: {new_balance}")


@tree.command(name="roast", description="Roast someone creatively")
async def roast(interaction: discord.Interaction, member: discord.Member):
    if member.bot:
        await interaction.response.send_message("🤖 Roasting bots is too easy.", ephemeral=True)
        return
    if member.id == interaction.user.id:
        await interaction.response.send_message("😅 Self-roast? Bold move.", ephemeral=True)
        return
    roast_line = random.choice(ROAST_LINES)
    embed = discord.Embed(description=f"{member.mention} {roast_line}", color=discord.Color.orange())
    embed.set_image(url=LAUGH_IMAGE_URL)
    await interaction.response.send_message(embed=embed)


@tree.command(name="help", description="Show the command center")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(embed=help_embed(), view=HelpView(), ephemeral=True)


@bot.command(name="help")
async def help_prefix(ctx: commands.Context):
    await ctx.send(embed=help_embed(), view=HelpView())


# ================== ROLE TRACKING COMMANDS ==================
@tree.command(name="trackrole", description="Restrict XP gains to users with this role")
@app_commands.checks.has_permissions(administrator=True)
async def trackrole(interaction: discord.Interaction, role: discord.Role):
    gset, settings = get_guild_settings(interaction.guild.id)
    tracked = gset.setdefault("tracked_roles", [])
    if role.id in tracked:
        await interaction.response.send_message("Role already tracked.", ephemeral=True)
        return
    tracked.append(role.id)
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message(f"✅ Now restricting XP to {role.mention}", ephemeral=True)


@tree.command(name="untrackrole", description="Remove XP role restriction")
@app_commands.checks.has_permissions(administrator=True)
async def untrackrole(interaction: discord.Interaction, role: discord.Role):
    gset, settings = get_guild_settings(interaction.guild.id)
    tracked = gset.setdefault("tracked_roles", [])
    if role.id not in tracked:
        await interaction.response.send_message("Role not tracked.", ephemeral=True)
        return
    tracked.remove(role.id)
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message(f"❌ Removed XP restriction for {role.mention}", ephemeral=True)


@tree.command(name="trackroleall", description="Allow XP for all roles (clear restrictions)")
@app_commands.checks.has_permissions(administrator=True)
async def trackroleall(interaction: discord.Interaction):
    gset, settings = get_guild_settings(interaction.guild.id)
    gset["tracked_roles"] = []
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message("✅ XP now works for all roles.", ephemeral=True)


@tree.command(name="trackrolelist", description="Show XP-restricted roles")
async def trackrolelist(interaction: discord.Interaction):
    gset, _ = get_guild_settings(interaction.guild.id)
    tracked = gset.get("tracked_roles", [])
    if not tracked:
        await interaction.response.send_message("XP works for all roles (no restrictions).")
        return
    roles = [interaction.guild.get_role(rid) for rid in tracked]
    mentions = [r.mention for r in roles if r]
    await interaction.response.send_message("Tracked roles:\n" + "\n".join(mentions))


# ================== START BOT ==================
if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))

