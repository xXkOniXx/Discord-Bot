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
ROLE_TRACKER_STORE = "role_tracker"
PROPERTY_STORE = "property_data"

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
        mongo_client = MongoClient(MONGO_URI, tls=True, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=3000)
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
        store_collection.update_one({"_id": name}, {"$set": {"data": data}}, upsert=True)
    except PyMongoError as e:
        print(f"⚠️ Mongo save failed for {name}: {e}")
        mongo_ready = False


# ================== DEFAULT SETTINGS ==================
def default_settings():
    return {
        "xp_range": [30, 60], "cooldown": 2, "ignored_channels": [],
        "role_rewards": {}, "levelup_bg": None, "rank_backgrounds": {},
        "xp_multiplier": 1.0, "level_channel": None, "level_notify": {},
        "max_level": 100, "voice_bonus_xp": 60, "voice_bonus_cooldown": 100,
        "tracked_roles": [],
    }


def xp_needed(level):
    return 100 + level * 75


def default_economy_user():
    return {
        "coins": 0, "bank": 0, "rep": 0, "rep_last": 0, "rep_given_to": None,
        "last_daily": 0, "daily_streak": 0, "last_work": 0, "last_heist": 0,
        "backgrounds": [], "color": None, "badge": None, "badges": [],
        "prestige": 0, "voice_bonus": True, "last_voice_bonus": 0,
        "afk": False, "afk_reason": None, "married_to": None,
        "active_background": None, "jail": False, "jail_until": 0,
        "bail_amount": 0, "divorced_count": 0, "socials": {}, "job_counts": {},
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
        for k, v in default_economy_user().items():
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


def is_in_jail(econ_user):
    if not econ_user.get("jail", False):
        return False
    if time.time() >= econ_user.get("jail_until", 0):
        econ_user["jail"] = False
        econ_user["jail_until"] = 0
        econ_user["bail_amount"] = 0
        return False
    return True


def get_tracker_data(guild_id):
    data = load_store(ROLE_TRACKER_STORE, {})
    return data.setdefault(str(guild_id), {"tracked": {}, "list_message": None}), data


def get_property_data(guild_id):
    data = load_store(PROPERTY_STORE, {})
    return data.setdefault(str(guild_id), {}), data


def ensure_user_properties(prop_guild, user_id):
    return prop_guild.setdefault(str(user_id), [])


async def send_response(interaction, content=None, embed=None, ephemeral=False, file=None):
    payload = {"content": content, "embed": embed, "ephemeral": ephemeral}
    if file is not None:
        payload["file"] = file
    if interaction.response.is_done():
        await interaction.followup.send(**payload)
    else:
        await interaction.response.send_message(**payload)


# ================== CONSTANTS ==================
SHOP_BACKGROUNDS = {"Galaxy": 500, "Neon": 750, "Forest": 300}

EIGHT_BALL_RESPONSES = [
    "It is certain.", "Without a doubt.", "Yes - definitely.",
    "Reply hazy, try again.", "Ask again later.", "Better not tell you now.",
    "My sources say no.", "Very doubtful.", "Absolutely!", "Don't count on it."
]

CONVERSATION_STARTERS = [
    "Pineapple on pizza — yes or no?", "What's a movie you could watch 10 times?",
    "If you could time travel, where would you go?", "What's your go-to comfort food?",
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
    "Is social media good or bad for society?", "Should homework be banned?",
    "Is it better to be early or right on time?", "Are videogames a sport?",
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
GRIND_COOLDOWNS = {}

GRIND_QUESTIONS = {
    "Disney Movies": [
        {"emojis": "🦁👑", "answer": ["lion king", "the lion king"]},
        {"emojis": "🧊❄️👸", "answer": ["frozen"]},
        {"emojis": "🐟🔵💙", "answer": ["finding nemo"]},
        {"emojis": "🍎👸🐦", "answer": ["snow white"]},
        {"emojis": "🧞‍♂️🪔✨", "answer": ["aladdin"]},
        {"emojis": "🥀🕰️👗", "answer": ["beauty and the beast"]},
        {"emojis": "🐠🐙🌊", "answer": ["finding dory"]},
        {"emojis": "🐘🎪🎩", "answer": ["dumbo"]},
        {"emojis": "🧵🪡👗🎃", "answer": ["the nightmare before christmas", "nightmare before christmas"]},
        {"emojis": "🐜🍃🌿", "answer": ["a bugs life", "bugs life"]},
        {"emojis": "🐻🍯🌳", "answer": ["winnie the pooh"]},
        {"emojis": "🧜‍♀️🌊🐚", "answer": ["the little mermaid", "little mermaid"]},
        {"emojis": "🚀👨‍🚀🤠", "answer": ["toy story"]},
        {"emojis": "👠🎃🕛", "answer": ["cinderella"]},
        {"emojis": "💤👸🌹", "answer": ["sleeping beauty"]},
        {"emojis": "🌺💃🏝️", "answer": ["moana"]},
        {"emojis": "🍄🔴⭐", "answer": ["mario"]},
        {"emojis": "🦌❄️🌲", "answer": ["bambi"]},
        {"emojis": "🎵🌄🦁🌍", "answer": ["lion king", "the lion king"]},
        {"emojis": "🌹🕯️🏰", "answer": ["beauty and the beast"]},
    ],
    "Brands": [
        {"emojis": "🍎💻📱", "answer": ["apple"]},
        {"emojis": "✔️👟", "answer": ["nike"]},
        {"emojis": "🐊👕", "answer": ["lacoste"]},
        {"emojis": "🦅📦", "answer": ["american eagle"]},
        {"emojis": "📘👍", "answer": ["facebook"]},
        {"emojis": "🐦🔵", "answer": ["twitter"]},
        {"emojis": "📸❤️", "answer": ["instagram"]},
        {"emojis": "🟢🎵🎧", "answer": ["spotify"]},
        {"emojis": "🛒🟡📦", "answer": ["amazon"]},
        {"emojis": "🔵🛒🏪", "answer": ["walmart"]},
        {"emojis": "☕🟢🧜‍♀️", "answer": ["starbucks"]},
        {"emojis": "🏎️🐴🇮🇹", "answer": ["ferrari"]},
        {"emojis": "🍩☕🇺🇸", "answer": ["dunkin", "dunkin donuts"]},
        {"emojis": "🐊💚", "answer": ["crocs"]},
        {"emojis": "🟥🎮", "answer": ["youtube"]},
        {"emojis": "🔴▶️🎵", "answer": ["youtube music"]},
        {"emojis": "⭐🍺🐴", "answer": ["budweiser"]},
        {"emojis": "💎💍👜", "answer": ["tiffany"]},
        {"emojis": "⭐🔵🚗", "answer": ["subaru"]},
        {"emojis": "🎬📺🔴", "answer": ["netflix"]},
    ],
    "TV Shows": [
        {"emojis": "🧪🔬💀", "answer": ["breaking bad"]},
        {"emojis": "🐉⚔️👑❄️", "answer": ["game of thrones"]},
        {"emojis": "🏝️✈️💥", "answer": ["lost"]},
        {"emojis": "🧟‍♂️🪓🌍", "answer": ["the walking dead", "walking dead"]},
        {"emojis": "🕵️‍♂️🔍🇬🇧", "answer": ["sherlock"]},
        {"emojis": "👨‍👩‍👧‍👦🛋️☕", "answer": ["friends"]},
        {"emojis": "🍕🗽👫", "answer": ["how i met your mother"]},
        {"emojis": "🏥🩺❤️", "answer": ["greys anatomy", "grey's anatomy"]},
        {"emojis": "🌌🚀👽", "answer": ["the x files", "x files"]},
        {"emojis": "🧠🔬🤯", "answer": ["stranger things"]},
        {"emojis": "🕶️🐝🐛", "answer": ["black mirror"]},
        {"emojis": "🎸🎤🏫", "answer": ["glee"]},
        {"emojis": "🏄‍♂️🌊🍍", "answer": ["spongebob", "spongebob squarepants"]},
        {"emojis": "🔴🔵💊", "answer": ["the matrix", "matrix"]},
        {"emojis": "🏰👻🕯️", "answer": ["haunting of hill house"]},
        {"emojis": "🧛‍♂️🌲🏫", "answer": ["twilight"]},
        {"emojis": "🤵🔫🍸", "answer": ["james bond"]},
        {"emojis": "🌀🦸‍♂️🕷️", "answer": ["spiderman", "spider-man"]},
        {"emojis": "🎭🃏🤡", "answer": ["joker"]},
        {"emojis": "🏫👨‍🏫🔬", "answer": ["breaking bad"]},
    ],
    "Fast Food": [
        {"emojis": "🍔👑", "answer": ["burger king"]},
        {"emojis": "🍟🤡🍔", "answer": ["mcdonalds", "mcdonald's"]},
        {"emojis": "🔔🌮", "answer": ["taco bell"]},
        {"emojis": "🍗🤴", "answer": ["popeyes"]},
        {"emojis": "🐔⭐", "answer": ["chick fil a", "chick-fil-a"]},
        {"emojis": "🥖🥗🥪", "answer": ["subway"]},
        {"emojis": "🏠🍕", "answer": ["dominos", "domino's"]},
        {"emojis": "🍕🍕🍕", "answer": ["pizza hut"]},
        {"emojis": "🦐🍤🦞", "answer": ["red lobster"]},
        {"emojis": "🥩🔥🏪", "answer": ["arbys", "arby's"]},
        {"emojis": "🍦🍨🍧", "answer": ["dairy queen", "dq"]},
        {"emojis": "🧇🥞☕", "answer": ["ihop"]},
        {"emojis": "🥚🧀🍳", "answer": ["waffle house"]},
        {"emojis": "🐔🥤🍟", "answer": ["kfc", "kentucky fried chicken"]},
        {"emojis": "🥩🧅🍞", "answer": ["shake shack"]},
        {"emojis": "⭐🍔🌟", "answer": ["carls jr", "carl's jr", "hardees", "hardee's"]},
        {"emojis": "🟠🍗", "answer": ["popeyes"]},
        {"emojis": "🐟🍟", "answer": ["long john silvers", "long john silver's"]},
        {"emojis": "🌊🦞🥧", "answer": ["red lobster"]},
        {"emojis": "🍕🛵📱", "answer": ["doordash"]},
    ],
    "Characters": [
        {"emojis": "🕷️🔴🕸️", "answer": ["spider-man", "spiderman"]},
        {"emojis": "🦇🌑🦸", "answer": ["batman"]},
        {"emojis": "🔴🔵⭐🛡️", "answer": ["captain america"]},
        {"emojis": "🟢💪😡", "answer": ["hulk"]},
        {"emojis": "⚡🔨🪨", "answer": ["thor"]},
        {"emojis": "🧙‍♂️⚡📚", "answer": ["harry potter"]},
        {"emojis": "🐭🧀🏃", "answer": ["jerry", "jerry mouse"]},
        {"emojis": "🐱🏃🧀", "answer": ["tom", "tom cat"]},
        {"emojis": "🟡😊🧽", "answer": ["spongebob", "spongebob squarepants"]},
        {"emojis": "🌊🐙🦑", "answer": ["squidward"]},
        {"emojis": "⭐🌟🌊", "answer": ["patrick", "patrick star"]},
        {"emojis": "🤖🔴👁️", "answer": ["terminator"]},
        {"emojis": "🧊❄️💙", "answer": ["elsa"]},
        {"emojis": "🌺💃🏝️", "answer": ["moana"]},
        {"emojis": "🦁👑🌍", "answer": ["simba"]},
        {"emojis": "🐘🌊🎪", "answer": ["dumbo"]},
        {"emojis": "🤠🐍👢", "answer": ["woody"]},
        {"emojis": "🚀👨‍🚀💚", "answer": ["buzz lightyear", "buzz"]},
        {"emojis": "🍄🔴⭐", "answer": ["mario"]},
        {"emojis": "🦁🧙‍♂️🪄", "answer": ["gandalf"]},
    ],
    "Logos": [
        {"emojis": "🍎⌨️💻", "answer": ["apple"]},
        {"emojis": "🔵😊👍", "answer": ["facebook"]},
        {"emojis": "🐦💬🔵", "answer": ["twitter"]},
        {"emojis": "▶️🔴📺", "answer": ["youtube"]},
        {"emojis": "🔍🌐🟦", "answer": ["google"]},
        {"emojis": "🛒📦🔶", "answer": ["amazon"]},
        {"emojis": "🎵🟢🎧", "answer": ["spotify"]},
        {"emojis": "🎬📺🔴", "answer": ["netflix"]},
        {"emojis": "🚗🗺️📍", "answer": ["uber"]},
        {"emojis": "🟣📸✨", "answer": ["instagram"]},
        {"emojis": "💼🔵👔", "answer": ["linkedin"]},
        {"emojis": "🎮🟩", "answer": ["xbox"]},
        {"emojis": "🎮🔵", "answer": ["playstation"]},
        {"emojis": "🃏🎮🔴", "answer": ["nintendo"]},
        {"emojis": "🐱💻", "answer": ["github"]},
        {"emojis": "💬🟣", "answer": ["twitch"]},
        {"emojis": "🎵📱🍎", "answer": ["apple music"]},
        {"emojis": "🔵💬✈️", "answer": ["telegram"]},
        {"emojis": "📘✈️🏨", "answer": ["airbnb"]},
        {"emojis": "🟣💬", "answer": ["twitch"]},
    ],
}

GRIND_GENRE_CHOICES = [
    app_commands.Choice(name="🎬 Disney Movies", value="Disney Movies"),
    app_commands.Choice(name="🏷️ Brands", value="Brands"),
    app_commands.Choice(name="📺 TV Shows", value="TV Shows"),
    app_commands.Choice(name="🍔 Fast Food", value="Fast Food"),
    app_commands.Choice(name="🎭 Characters", value="Characters"),
    app_commands.Choice(name="🔷 Logos", value="Logos"),
]

HEART_COLORS = [
    ("❤️", "red"), ("💙", "blue"), ("💚", "green"),
    ("💛", "yellow"), ("💜", "purple"), ("🩷", "pink"),
]
CONVEYOR_ITEMS = ["📦", "📮", "🎁", "📫", "🧸", "📬"]
TRASH_ITEM = "📄"
FOOD_ITEMS = ["🍔", "🍕", "🌮", "🍟", "🥤", "🌯", "🍗", "🥪"]
NON_FOOD_ITEM = "🧹"

BODY_PARTS = [
    {"name": "skull", "display": "🦴  ← broken!\n💪  🫁  💪\n🦵      🦵", "answers": ["skull", "head"]},
    {"name": "left arm", "display": "🧠\n🦴  🫁  💪  ← broken!\n🦵      🦵", "answers": ["left arm", "arm"]},
    {"name": "right arm", "display": "🧠\n💪  🫁  🦴  ← broken!\n🦵      🦵", "answers": ["right arm", "arm"]},
    {"name": "left leg", "display": "🧠\n💪  🫁  💪\n🦴      🦵  ← broken!", "answers": ["left leg", "leg"]},
    {"name": "right leg", "display": "🧠\n💪  🫁  💪\n🦵      🦴  ← broken!", "answers": ["right leg", "leg"]},
    {"name": "ribs", "display": "🧠\n💪  🦴  💪  ← broken!\n🦵      🦵", "answers": ["ribs", "rib", "chest"]},
]

PINHEAD_ITEMS = [
    ("🪨", "rock"), ("🍦", "ice cream"), ("🧁", "cupcake"), ("🕳️", "black hole"),
    ("💎", "diamond"), ("❄️", "snow"), ("🪡", "needle"), ("🩲", "underwear"),
]

HIDING_SPOTS_LIST = [
    ("🚗", "Behind a parked car"), ("🗑️", "Inside a dumpster"), ("🌳", "Behind a large tree"),
    ("📦", "Inside a cardboard box"), ("🏠", "On someone's porch"), ("🚌", "Under a bus"),
    ("🌿", "In the bushes"), ("🪣", "Behind a fence post"), ("🛒", "In an abandoned shopping cart"),
]

JOB_DESCRIPTIONS = {
    "Streamer":          ("📺", "Match heart colors live on stream. Earns **600 coins**."),
    "Garbage Collector": ("🗑️", "Spot trash on the conveyor belt. Earns **500 coins**."),
    "Fast Food Worker":  ("🍔", "Remove non-food from the counter. Earns **550 coins**."),
    "Doctor":            ("👨‍⚕️", "Diagnose the broken body part. Earns **800 coins**."),
    "PinHead":           ("💊", "Deal in a dark alley and escape the cops. Earns **10,000 coins!**"),
}

STORE_ITEMS = {
    "🚗 Cars": [
        {"name": "Ferrari SF90", "price": 250000, "desc": "A hybrid masterpiece from Maranello. 0-60 in 2.5 seconds. 🔴", "image": "https://images.unsplash.com/photo-1592853625511-ad0edcc69c07?w=800"},
        {"name": "Lamborghini Huracán", "price": 220000, "desc": "Raw Italian aggression in a sleek, sculpted body. 🟡", "image": "https://images.unsplash.com/photo-1544636331-e26879cd4d9b?w=800"},
        {"name": "Porsche 911 GT3", "price": 180000, "desc": "Track-bred precision with everyday usability. A legend. 🏁", "image": "https://images.unsplash.com/photo-1503376780353-7e6692767b70?w=800"},
        {"name": "McLaren 720S", "price": 300000, "desc": "Carbon fiber everything. Feels like flying on asphalt. ⚡", "image": "https://images.unsplash.com/photo-1558618666-fcd25c85cd64?w=800"},
        {"name": "Rolls-Royce Phantom", "price": 500000, "desc": "The pinnacle of British luxury. Float, don't drive. 👑", "image": "https://images.unsplash.com/photo-1563132337-f159f484226c?w=800"},
        {"name": "Bugatti Chiron", "price": 3000000, "desc": "1,500 horsepower. Top speed limited to 261 mph. Unearthly. 🔵", "image": "https://images.unsplash.com/photo-1580274455191-1c62238fa333?w=800"},
        {"name": "Aston Martin DB11", "price": 195000, "desc": "Bond approved. Effortlessly sophisticated at every speed. 🕴️", "image": "https://images.unsplash.com/photo-1617814076229-5b2b544e2c6c?w=800"},
        {"name": "Bentley Continental GT", "price": 270000, "desc": "Hand-stitched leather and 626 bhp. The grand tourer. 🍃", "image": "https://images.unsplash.com/photo-1606664515524-ed2f786a0bd6?w=800"},
    ],
    "🏠 Houses": [
        {"name": "Beverly Hills Mansion", "price": 10000000, "desc": "8 bedrooms, pool, tennis court, and a view that never gets old. 🌴", "image": "https://images.unsplash.com/photo-1564013799919-ab600027ffc6?w=800"},
        {"name": "Malibu Beach House", "price": 7500000, "desc": "Wake up to ocean waves every single morning. Sand not included. 🌊", "image": "https://images.unsplash.com/photo-1499793983690-e29da59ef1c2?w=800"},
        {"name": "NYC Penthouse", "price": 15000000, "desc": "360° skyline views. Private rooftop. You're above everyone now. 🏙️", "image": "https://images.unsplash.com/photo-1522708323590-d24dbb6b0267?w=800"},
        {"name": "Jungle Treehouse", "price": 850000, "desc": "Hidden deep in the rainforest. Solar powered, off the grid. 🌿", "image": "https://images.unsplash.com/photo-1520250497591-112f2f40a3f4?w=800"},
        {"name": "Scottish Castle", "price": 25000000, "desc": "700 years of history. Moat optional. Dragons not included. 🏰", "image": "https://images.unsplash.com/photo-1467269204594-9661b134dd2b?w=800"},
        {"name": "Tuscany Villa", "price": 4200000, "desc": "Rolling Italian hills, a vineyard, and endless sunsets. 🍷", "image": "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?w=800"},
        {"name": "Modern Glass House", "price": 3000000, "desc": "Floor to ceiling windows. Minimalist. Architecture at its finest. 🪟", "image": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?w=800"},
        {"name": "Mountain Log Cabin", "price": 600000, "desc": "Pine trees, fireplace, and silence. Cozy season all year round. 🌲", "image": "https://images.unsplash.com/photo-1449158743715-0a90ebb6d2d8?w=800"},
    ],
    "🦁 Exotic Animals": [
        {"name": "White Lion Cub", "price": 500000, "desc": "Majestic and rare. Only ~13 white lions exist in the wild. 🦁", "image": "https://images.unsplash.com/photo-1546182990-dffeafbe841d?w=800"},
        {"name": "Bengal Tiger", "price": 750000, "desc": "800 lbs of pure power. Comes with its own personal chef. 🐯", "image": "https://images.unsplash.com/photo-1561731216-c3a4d99437d5?w=800"},
        {"name": "Cheetah", "price": 350000, "desc": "0-70 in 3 seconds. The fastest land animal. Also very soft. 🐆", "image": "https://images.unsplash.com/photo-1509479100390-3f595febb378?w=800"},
        {"name": "Hyacinth Macaw", "price": 120000, "desc": "The world's largest parrot. Deep cobalt blue and incredibly loud. 🦜", "image": "https://images.unsplash.com/photo-1552728089-57bdde30beb3?w=800"},
        {"name": "Golden Capuchin Monkey", "price": 80000, "desc": "Tiny, chaotic, and utterly adorable. Will steal your phone. 🐒", "image": "https://images.unsplash.com/photo-1540573133985-87b6da6d54a9?w=800"},
        {"name": "Black Panther", "price": 900000, "desc": "Sleek, silent, and powerful. Actually a melanistic leopard. 🖤", "image": "https://images.unsplash.com/photo-1516026672322-bc52d61a55d5?w=800"},
        {"name": "Indian Peacock", "price": 45000, "desc": "Living art. Its tail fan spans up to 6 feet wide. Stunning. 🦚", "image": "https://images.unsplash.com/photo-1548550023-2bdb3c5beed7?w=800"},
        {"name": "Arctic Fox", "price": 95000, "desc": "Cloud-white fur and curious blue eyes. The fluffiest flex. 🦊", "image": "https://images.unsplash.com/photo-1474511320723-9a56873867b5?w=800"},
    ],
}

SOCIAL_PLATFORMS = [
    app_commands.Choice(name="🎮 Twitch", value="Twitch"),
    app_commands.Choice(name="📺 YouTube", value="YouTube"),
    app_commands.Choice(name="🐦 Twitter / X", value="Twitter/X"),
    app_commands.Choice(name="📸 Instagram", value="Instagram"),
    app_commands.Choice(name="🎵 TikTok", value="TikTok"),
    app_commands.Choice(name="🎵 Spotify", value="Spotify"),
    app_commands.Choice(name="👾 Discord Server", value="Discord"),
    app_commands.Choice(name="📘 Facebook", value="Facebook"),
    app_commands.Choice(name="🖼️ Other", value="Other"),
]

PROFILE_BANNERS = [
    "✨ ━━━━━━━━━━━━━━━━━━━━━━━━ ✨",
    "💫 ━━━━━━━━━━━━━━━━━━━━━━━━ 💫",
    "🌸 ━━━━━━━━━━━━━━━━━━━━━━━━ 🌸",
    "🎀 ━━━━━━━━━━━━━━━━━━━━━━━━ 🎀",
    "🌟 ━━━━━━━━━━━━━━━━━━━━━━━━ 🌟",
    "💜 ━━━━━━━━━━━━━━━━━━━━━━━━ 💜",
    "🔥 ━━━━━━━━━━━━━━━━━━━━━━━━ 🔥",
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

HELP_COMMANDS = [
    {"name": "daily", "usage": "/daily", "desc": "Claim daily XP and coins."},
    {"name": "rep", "usage": "/rep @user", "desc": "Give a reputation point."},
    {"name": "grind", "usage": "/grind <genre>", "desc": "Guess the emoji combo. Win 30 XP or lose 15 XP."},
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
    {"name": "clearlevelchannel", "usage": "/clearlevelchannel", "desc": "Reset level-up messages to same channel."},
    {"name": "setxpmultiplier", "usage": "/setxpmultiplier <num>", "desc": "Set XP multiplier."},
    {"name": "blacklistxp", "usage": "/blacklistxp #channel", "desc": "Block XP in channel."},
    {"name": "unblacklistxp", "usage": "/unblacklistxp #channel", "desc": "Re-enable XP in a blacklisted channel."},
    {"name": "resetuserxp", "usage": "/resetuserxp @user", "desc": "Reset user XP."},
    {"name": "setlevel", "usage": "/setlevel @user <level> [xp]", "desc": "Admin: set user level/xp."},
    {"name": "pocket", "usage": "/pocket [@user]", "desc": "Check your pocket and bank balance."},
    {"name": "deposit", "usage": "/deposit <amount>", "desc": "Deposit coins into the Koni Bank."},
    {"name": "withdraw", "usage": "/withdraw <amount>", "desc": "Withdraw coins from the Koni Bank."},
    {"name": "givecoins", "usage": "/givecoins @user <amount>", "desc": "Admin: give coins to a user."},
    {"name": "setbalance", "usage": "/setbalance @user <amount>", "desc": "Admin: set a user coin balance."},
    {"name": "work", "usage": "/work", "desc": "Clock in and choose a job to earn coins."},
    {"name": "shop", "usage": "/shop", "desc": "View background shop items."},
    {"name": "buybackground", "usage": "/buybackground <n>", "desc": "Buy a background."},
    {"name": "store", "usage": "/store", "desc": "Browse the Koni Luxury Store."},
    {"name": "properties", "usage": "/properties [@user]", "desc": "View all luxury items you own."},
    {"name": "rob", "usage": "/rob @user <amount>", "desc": "Play RPS to rob someone's bank. Lose = jail."},
    {"name": "setcolor", "usage": "/setcolor #hex", "desc": "Set rank card color."},
    {"name": "clearcolor", "usage": "/clearcolor", "desc": "Reset your rank card color to default."},
    {"name": "setbadge", "usage": "/setbadge <badge>", "desc": "Set profile badge."},
    {"name": "clearbadge", "usage": "/clearbadge", "desc": "Remove your active badge."},
    {"name": "profile", "usage": "/profile [@user]", "desc": "View user profile."},
    {"name": "addsocial", "usage": "/addsocial <platform> <handle>", "desc": "Add a social to your profile."},
    {"name": "removesocial", "usage": "/removesocial <platform>", "desc": "Remove a social from your profile."},
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
    {"name": "clearlevelupbackground", "usage": "/clearlevelupbackground", "desc": "Reset level-up background to default."},
    {"name": "setrolereward", "usage": "/setrolereward <level> @role", "desc": "Set role reward."},
    {"name": "removerolereward", "usage": "/removerolereward <level>", "desc": "Remove role reward."},
    {"name": "rolerewards", "usage": "/rolerewards", "desc": "List role rewards."},
    {"name": "trackrole", "usage": "/trackrole @role", "desc": "Add a role to the tracker."},
    {"name": "untrackrole", "usage": "/untrackrole @role", "desc": "Remove a role from the tracker."},
    {"name": "trackrolelist", "usage": "/trackrolelist", "desc": "Post the live role tracker panel."},
    {"name": "trackroleall", "usage": "/trackroleall", "desc": "Track every role in the server."},
    {"name": "untrackroleall", "usage": "/untrackroleall", "desc": "Remove all roles from the tracker."},
    {"name": "trackrolelist_clear", "usage": "/trackrolelist_clear", "desc": "Remove the live role tracker panel."},
]

# ================== HELP UI ==================
def help_embed():
    categories = {
        "🎮 Fun / Social": ["daily", "rep", "grind", "8ball", "meme", "roast"],
        "🏆 Leveling": ["rank", "leaderboard", "prestige", "levelroles", "levelnotify", "backgrounds"],
        "💬 Chat Boosters": ["question", "wouldyourather", "topic"],
        "🛠️ Admin": ["setlevelchannel", "clearlevelchannel", "setxpmultiplier", "blacklistxp", "unblacklistxp", "resetuserxp", "setlevel", "setxp", "setcooldown", "clearlevelupbackground"],
        "💰 Economy": ["pocket", "deposit", "withdraw", "givecoins", "setbalance", "work", "shop", "buybackground", "gamblerist", "koniheist", "divorce", "rob", "store", "properties"],
        "🎨 Cosmetics": ["setcolor", "clearcolor", "setbadge", "clearbadge", "profile", "addsocial", "removesocial", "voicebonus", "afk", "marry"],
        "📌 Role Tracking": ["trackrole", "untrackrole", "trackrolelist", "trackroleall", "untrackroleall", "trackrolelist_clear"],
        "🖼️ Backgrounds": ["setrankbackground", "setlevelupbackground", "setrolereward", "removerolereward", "rolerewards"],
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


class HelpSelect(discord.ui.Select):
    def __init__(self, options):
        super().__init__(placeholder="Select a command for details...", min_values=1, max_values=1, options=options)

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

    @discord.ui.button(label="Grind", style=discord.ButtonStyle.secondary, emoji="🧠")
    async def grind_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await tree.get_command("grind").callback(interaction, genre=app_commands.Choice(name="🎬 Disney Movies", value="Disney Movies"))

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

    @discord.ui.button(label="Pocket", style=discord.ButtonStyle.secondary, emoji="💰")
    async def pocket_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await tree.get_command("pocket").callback(interaction)

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
        font = ImageFont.truetype("arialbd.ttf", 72)
    except:
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
        except:
            font = ImageFont.load_default()
    draw.text((250, 70), f"{member.display_name} reached Level {level}!", font=font, fill=(255, 255, 255))
    buf = io.BytesIO()
    await member.display_avatar.with_size(128).save(buf)
    buf.seek(0)
    av = Image.open(buf).convert("RGBA").resize((120, 120))
    mask = av.split()[3]
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
    if not auto_update_role_tracker.is_running():
        auto_update_role_tracker.start()
    print(f"🤖 Logged in as {bot.user}")


@bot.event
async def on_message(message):
    if message.author.bot or not message.guild:
        return
    gset, settings = get_guild_settings(message.guild.id)
    glevels, levels = get_level_data(message.guild.id)
    economy_guild, economy = get_economy_data(message.guild.id)
    econ_user = ensure_user_economy(economy_guild, message.author.id)
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
    if econ_user.get("afk"):
        econ_user["afk"] = False
        econ_user["afk_reason"] = None
        save_store(ECONOMY_STORE, economy)
        try:
            await message.channel.send(f"👋 Welcome back, {message.author.mention}! Your AFK is now off.")
        except discord.HTTPException:
            pass
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
        bonus_xp = int(gset.get("voice_bonus_xp", 10) * gset.get("xp_multiplier", 1.0))
        user["xp"] += bonus_xp
        econ_user["last_voice_bonus"] = now
        save_store(LEVEL_STORE, levels)
        save_store(ECONOMY_STORE, economy)


@bot.event
async def on_member_update(before, after):
    if before.roles == after.roles:
        return
    data = load_store(ROLE_TRACKER_STORE, {})
    gid = str(after.guild.id)
    guild_data = data.get(gid, {})
    tracked = guild_data.get("tracked", {})
    list_msg = guild_data.get("list_message")
    changed_role_ids = {str(r.id) for r in set(before.roles) ^ set(after.roles)}
    if not any(rid in tracked for rid in changed_role_ids):
        return
    if not list_msg:
        return
    try:
        ch = after.guild.get_channel(list_msg["channel_id"])
        if not ch:
            return
        msg = await ch.fetch_message(list_msg["message_id"])
        embed = build_role_tracker_embed(after.guild, list(tracked.keys()))
        await msg.edit(embed=embed)
    except Exception:
        pass


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
                    embed = discord.Embed(title="📌 Tracked Roles", description="\n".join(desc_lines), color=discord.Color.blurple())
                    await msg.edit(embed=embed)
            except Exception:
                pass


@tasks.loop(minutes=2)
async def auto_update_role_tracker():
    data = load_store(ROLE_TRACKER_STORE, {})
    for guild in bot.guilds:
        gid = str(guild.id)
        guild_data = data.get(gid, {})
        tracked = guild_data.get("tracked", {})
        list_msg = guild_data.get("list_message")
        if not list_msg:
            continue
        try:
            ch = guild.get_channel(list_msg["channel_id"])
            if not ch:
                continue
            msg = await ch.fetch_message(list_msg["message_id"])
            embed = build_role_tracker_embed(guild, list(tracked.keys()))
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


# ================== ROLE TRACKER HELPER ==================
def build_role_tracker_embed(guild, tracked_role_ids):
    embed = discord.Embed(title="📊 Role Tracker", color=discord.Color.blurple(), timestamp=discord.utils.utcnow())
    if not tracked_role_ids:
        embed.description = "No roles are currently being tracked."
        embed.set_footer(text="Use /trackrole to add roles")
        return embed
    lines = []
    for rid in tracked_role_ids:
        role = guild.get_role(int(rid))
        if not role:
            continue
        count = sum(1 for m in guild.members if role in m.roles)
        bar_filled = int((count / max(guild.member_count, 1)) * 10)
        bar = "█" * bar_filled + "░" * (10 - bar_filled)
        lines.append(f"{role.mention}\n`{bar}` **{count}** members")
    embed.description = "\n\n".join(lines)
    embed.set_footer(text=f"Tracking {len(tracked_role_ids)} role(s) • Last updated")
    return embed

# ================== STORE VIEWS ==================
class StoreCategoryView(discord.ui.View):
    def __init__(self, user_id, guild_id):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild_id = guild_id

    def build_embed(self):
        embed = discord.Embed(
            title="🏬 Koni Luxury Store",
            description=(
                "```\n"
                "  💎  Welcome to the Koni Store!\n"
                "  ══════════════════════════════\n"
                "  Browse our exclusive collections\n"
                "  and flex on everyone. 👑\n"
                "  ══════════════════════════════\n"
                "```\n"
                "**Choose a category to start browsing:**\n\n"
                "🚗 **Cars** — Speed, luxury, and prestige\n"
                "🏠 **Houses** — From cabins to castles\n"
                "🦁 **Exotic Animals** — The rarest companions\n\n"
                "*Purchases come from your pocket first, then bank.*"
            ),
            color=discord.Color.gold()
        )
        embed.set_footer(text="Use /properties to view everything you own")
        return embed

    @discord.ui.button(label="🚗 Cars", style=discord.ButtonStyle.primary)
    async def cars_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your store session.", ephemeral=True)
            return
        view = StoreBrowseView(self.user_id, "🚗 Cars", self.guild_id)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)

    @discord.ui.button(label="🏠 Houses", style=discord.ButtonStyle.primary)
    async def houses_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your store session.", ephemeral=True)
            return
        view = StoreBrowseView(self.user_id, "🏠 Houses", self.guild_id)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)

    @discord.ui.button(label="🦁 Exotic Animals", style=discord.ButtonStyle.primary)
    async def animals_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your store session.", ephemeral=True)
            return
        view = StoreBrowseView(self.user_id, "🦁 Exotic Animals", self.guild_id)
        await interaction.response.edit_message(embed=view.build_embed(), view=view)


class StoreBrowseView(discord.ui.View):
    def __init__(self, user_id, category, guild_id):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.category = category
        self.guild_id = guild_id
        self.items = STORE_ITEMS[category]
        self.index = 0

    def build_embed(self):
        item = self.items[self.index]
        embed = discord.Embed(
            title=f"{self.category} — {item['name']}",
            description=(
                f"*{item['desc']}*\n\n"
                f"💰 **Price:** `{item['price']:,}` coins\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=discord.Color.gold()
        )
        embed.set_image(url=item["image"])
        embed.set_footer(text=f"Item {self.index + 1} of {len(self.items)}  •  Use ◀ ▶ to browse  •  🛒 to buy")
        return embed

    async def update(self, interaction: discord.Interaction):
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your store session.", ephemeral=True)
            return
        self.index = (self.index - 1) % len(self.items)
        await self.update(interaction)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your store session.", ephemeral=True)
            return
        self.index = (self.index + 1) % len(self.items)
        await self.update(interaction)

    @discord.ui.button(label="🛒 Buy", style=discord.ButtonStyle.success, row=0)
    async def buy_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your store session.", ephemeral=True)
            return
        item = self.items[self.index]
        economy_guild, economy = get_economy_data(self.guild_id)
        econ_user = ensure_user_economy(economy_guild, self.user_id)
        prop_guild, prop_data = get_property_data(self.guild_id)
        user_props = ensure_user_properties(prop_guild, self.user_id)
        already_owned = any(p["name"] == item["name"] and p["category"] == self.category for p in user_props)
        if already_owned:
            await interaction.response.send_message(f"✅ You already own **{item['name']}**!", ephemeral=True)
            return
        total_coins = econ_user.get("coins", 0) + econ_user.get("bank", 0)
        if total_coins < item["price"]:
            await interaction.response.send_message(
                f"❌ You need **{item['price']:,} coins** total.\n"
                f"💵 Pocket: `{econ_user.get('coins', 0):,}` + 🏦 Bank: `{econ_user.get('bank', 0):,}` = `{total_coins:,}` total.",
                ephemeral=True
            )
            return
        remaining = item["price"]
        if econ_user.get("coins", 0) >= remaining:
            econ_user["coins"] -= remaining
        else:
            remaining -= econ_user.get("coins", 0)
            econ_user["coins"] = 0
            econ_user["bank"] = econ_user.get("bank", 0) - remaining
        user_props.append({
            "name": item["name"], "category": self.category,
            "desc": item["desc"], "image": item["image"], "price": item["price"]
        })
        save_store(ECONOMY_STORE, economy)
        save_store(PROPERTY_STORE, prop_data)
        buy_embed = discord.Embed(
            title="🎉 Purchase Successful!",
            description=(
                f"You are now the proud owner of a **{item['name']}**! 🏆\n\n"
                f"*{item['desc']}*\n\n"
                f"💸 **Paid:** `{item['price']:,}` coins\n"
                f"💵 **Pocket:** `{econ_user.get('coins', 0):,}` coins\n"
                f"🏦 **Bank:** `{econ_user.get('bank', 0):,}` coins\n\n"
                f"View your new property with `/properties`! 🏠"
            ),
            color=discord.Color.green()
        )
        buy_embed.set_image(url=item["image"])
        await interaction.response.edit_message(embed=buy_embed, view=None)

    @discord.ui.button(label="🔙 Categories", style=discord.ButtonStyle.danger, row=0)
    async def back_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your store session.", ephemeral=True)
            return
        cat_view = StoreCategoryView(self.user_id, self.guild_id)
        await interaction.response.edit_message(embed=cat_view.build_embed(), view=cat_view)


class PropertiesView(discord.ui.View):
    def __init__(self, user_id, properties):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.properties = properties
        self.index = 0

    def build_embed(self):
        prop = self.properties[self.index]
        cat_colors = {
            "🚗 Cars": discord.Color.red(),
            "🏠 Houses": discord.Color.blue(),
            "🦁 Exotic Animals": discord.Color.green(),
        }
        color = cat_colors.get(prop["category"], discord.Color.gold())
        embed = discord.Embed(
            title=f"{prop['category']} — {prop['name']}",
            description=(
                f"*{prop['desc']}*\n\n"
                f"💰 **Paid:** `{prop.get('price', 0):,}` coins\n\n"
                f"━━━━━━━━━━━━━━━━━━━━━━"
            ),
            color=color
        )
        embed.set_image(url=prop["image"])
        embed.set_footer(text=f"Property {self.index + 1} of {len(self.properties)}  •  ◀ ▶ to browse")
        return embed

    @discord.ui.button(emoji="◀️", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ These aren't your properties.", ephemeral=True)
            return
        self.index = (self.index - 1) % len(self.properties)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(emoji="▶️", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ These aren't your properties.", ephemeral=True)
            return
        self.index = (self.index + 1) % len(self.properties)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="🗂️ Summary", style=discord.ButtonStyle.primary)
    async def summary_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ These aren't your properties.", ephemeral=True)
            return
        cars = [p for p in self.properties if p["category"] == "🚗 Cars"]
        houses = [p for p in self.properties if p["category"] == "🏠 Houses"]
        animals = [p for p in self.properties if p["category"] == "🦁 Exotic Animals"]
        total_spent = sum(p.get("price", 0) for p in self.properties)
        def fmt_list(items):
            return "\n".join([f"• {p['name']}" for p in items]) if items else "*None*"
        embed = discord.Embed(
            title="📋 Property Summary",
            description=(
                f"**Total items owned:** {len(self.properties)}\n"
                f"**Total spent:** `{total_spent:,}` coins\n\n"
                f"🚗 **Cars ({len(cars)})**\n{fmt_list(cars)}\n\n"
                f"🏠 **Houses ({len(houses)})**\n{fmt_list(houses)}\n\n"
                f"🦁 **Exotic Animals ({len(animals)})**\n{fmt_list(animals)}"
            ),
            color=discord.Color.gold()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


# ================== ROB VIEWS ==================
class BailView(discord.ui.View):
    def __init__(self, user_id, bail_amount, economy_guild, economy):
        super().__init__(timeout=120)
        self.user_id = user_id
        self.bail_amount = bail_amount
        self.economy_guild = economy_guild
        self.economy = economy

    @discord.ui.button(label="💸 Pay Bail", style=discord.ButtonStyle.danger)
    async def pay_bail(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your bail hearing!", ephemeral=True)
            return
        econ_user = ensure_user_economy(self.economy_guild, self.user_id)
        if econ_user.get("coins", 0) < self.bail_amount:
            await interaction.response.send_message(
                f"❌ You need **{self.bail_amount:,} coins** to bail out but only have **{econ_user.get('coins', 0):,}**.",
                ephemeral=True
            )
            return
        econ_user["coins"] -= self.bail_amount
        econ_user["jail"] = False
        econ_user["jail_until"] = 0
        econ_user["bail_amount"] = 0
        save_store(ECONOMY_STORE, self.economy)
        for item in self.children:
            item.disabled = True
        embed = discord.Embed(
            title="🔓 You're Free!",
            description=(
                f"You paid **{self.bail_amount:,} coins** bail and walked out the front door. 🚶\n\n"
                f"*Don't let us catch you again...* 👮"
            ),
            color=discord.Color.green()
        )
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⛓️ Serve My Time", style=discord.ButtonStyle.secondary)
    async def serve_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your bail hearing!", ephemeral=True)
            return
        econ_user = ensure_user_economy(self.economy_guild, self.user_id)
        remaining = max(0, int(econ_user.get("jail_until", 0) - time.time()))
        mins = remaining // 60
        secs = remaining % 60
        for item in self.children:
            item.disabled = True
        embed = discord.Embed(
            title="⛓️ Sitting in a Cell...",
            description=(
                f"You chose to serve your time.\n"
                f"⏳ Time remaining: **{mins}m {secs}s**\n\n"
                f"*You hear distant sirens and the sound of regret.*"
            ),
            color=discord.Color.greyple()
        )
        await interaction.response.edit_message(embed=embed, view=self)


class RPSView(discord.ui.View):
    def __init__(self, robber_id, target, amount, economy_guild, economy):
        super().__init__(timeout=30)
        self.robber_id = robber_id
        self.target = target
        self.amount = amount
        self.economy_guild = economy_guild
        self.economy = economy

    async def resolve(self, interaction: discord.Interaction, player_choice: str):
        bot_choice = random.choice(["rock", "paper", "scissors"])
        emojis = {"rock": "🪨", "paper": "📄", "scissors": "✂️"}
        beats = {"rock": "scissors", "paper": "rock", "scissors": "paper"}
        if player_choice == bot_choice:
            outcome = "tie"
        elif beats[player_choice] == bot_choice:
            outcome = "win"
        else:
            outcome = "lose"
        for item in self.children:
            item.disabled = True
        robber = ensure_user_economy(self.economy_guild, self.robber_id)
        if outcome == "win":
            stolen = min(self.amount, self.target.get("bank", 0))
            self.target["bank"] = max(0, self.target.get("bank", 0) - stolen)
            robber["coins"] = robber.get("coins", 0) + stolen
            save_store(ECONOMY_STORE, self.economy)
            embed = discord.Embed(
                title="🎉 Heist Successful!",
                description=(
                    f"You chose {emojis[player_choice]} | Bank chose {emojis[bot_choice]}\n\n"
                    f"💰 You slipped away with **{stolen:,} coins** from their bank!\n"
                    f"The loot has been added to your pocket. 🏃‍♂️💨"
                ),
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=embed, view=self)
        elif outcome == "tie":
            embed = discord.Embed(
                title="🤝 It's a Tie!",
                description=(
                    f"You chose {emojis[player_choice]} | Bank chose {emojis[bot_choice]}\n\n"
                    f"A standoff. Nobody wins this round. Try again later! 😤"
                ),
                color=discord.Color.yellow()
            )
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            jail_minutes = 10
            robber["jail"] = True
            robber["jail_until"] = time.time() + (jail_minutes * 60)
            robber["bail_amount"] = self.amount
            save_store(ECONOMY_STORE, self.economy)
            embed = discord.Embed(
                title="🚨 BUSTED! You're Going to Jail!",
                description=(
                    f"You chose {emojis[player_choice]} | Bank chose {emojis[bot_choice]}\n\n"
                    f"🚔 The police caught you red-handed!\n"
                    f"You've been sentenced to **{jail_minutes} minutes** in jail.\n\n"
                    f"💸 Bail out now for **{self.amount:,} coins** from your pocket,\n"
                    f"or sit and serve your time.\n\n"
                    f"⚠️ While in jail you **cannot work or rob anyone**."
                ),
                color=discord.Color.red()
            )
            bail_view = BailView(self.robber_id, self.amount, self.economy_guild, self.economy)
            await interaction.response.edit_message(embed=embed, view=bail_view)

    @discord.ui.button(label="🪨 Rock", style=discord.ButtonStyle.secondary)
    async def rock(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.robber_id:
            await interaction.response.send_message("❌ This isn't your heist!", ephemeral=True)
            return
        await self.resolve(interaction, "rock")

    @discord.ui.button(label="📄 Paper", style=discord.ButtonStyle.secondary)
    async def paper(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.robber_id:
            await interaction.response.send_message("❌ This isn't your heist!", ephemeral=True)
            return
        await self.resolve(interaction, "paper")

    @discord.ui.button(label="✂️ Scissors", style=discord.ButtonStyle.secondary)
    async def scissors(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.robber_id:
            await interaction.response.send_message("❌ This isn't your heist!", ephemeral=True)
            return
        await self.resolve(interaction, "scissors")


# ================== WORK VIEWS ==================
class HidingSpotView(discord.ui.View):
    def __init__(self, user_id, hiding_spots, economy_guild, economy):
        super().__init__(timeout=15)
        self.user_id = user_id
        self.hiding_spots = hiding_spots
        self.economy_guild = economy_guild
        self.economy = economy

        for emoji, name in hiding_spots:
            btn = discord.ui.Button(label=f"{emoji} {name}", style=discord.ButtonStyle.primary)

            def make_callback(e=emoji, n=name):
                async def callback(interaction: discord.Interaction):
                    if interaction.user.id != self.user_id:
                        await interaction.response.send_message("❌ This isn't your hide!", ephemeral=True)
                        return
                    for item in self.children:
                        item.disabled = True
                    cop_spots = random.sample([spot_name for _, spot_name in self.hiding_spots], 2)
                    econ_user = ensure_user_economy(self.economy_guild, self.user_id)
                    if n in cop_spots:
                        result_embed = discord.Embed(
                            title="🚔 You Got Caught!",
                            description=(
                                f"You hid **{e} {n}**...\n"
                                f"but the cops checked there! 🚨\n\n"
                                f"They searched: **{', '.join(cop_spots)}**\n\n"
                                f"You were arrested. No pay. 😤"
                            ),
                            color=discord.Color.red()
                        )
                    else:
                        pay = 10000
                        econ_user["bank"] = econ_user.get("bank", 0) + pay
                        save_store(ECONOMY_STORE, self.economy)
                        result_embed = discord.Embed(
                            title="😮‍💨 You Got Away!",
                            description=(
                                f"You hid **{e} {n}** and stayed perfectly still...\n\n"
                                f"The cops searched: **{', '.join(cop_spots)}**\n"
                                f"They never found you! 🏃‍♂️💨\n\n"
                                f"💸 Your cut of **{pay:,} coins** has been sent to\n"
                                f"the **Koni Banking Company**! 🏦\n\n"
                                f"*Don't spend it all in one place... or do.*"
                            ),
                            color=discord.Color.green()
                        )
                    await interaction.response.edit_message(embed=result_embed, view=self)
                return callback

            btn.callback = make_callback()
            self.add_item(btn)


class PinHeadItemView(discord.ui.View):
    def __init__(self, user_id, requested_item, economy_guild, economy):
        super().__init__(timeout=20)
        self.user_id = user_id
        self.requested_item = requested_item
        self.economy_guild = economy_guild
        self.economy = economy

        for emoji, name in PINHEAD_ITEMS:
            btn = discord.ui.Button(label=emoji, style=discord.ButtonStyle.secondary)

            def make_callback(e=emoji, n=name):
                async def callback(interaction: discord.Interaction):
                    if interaction.user.id != self.user_id:
                        await interaction.response.send_message("❌ This isn't your deal!", ephemeral=True)
                        return
                    for item in self.children:
                        item.disabled = True
                    req_emoji, req_name = self.requested_item
                    if n == req_name:
                        cop_embed = discord.Embed(
                            title="🚨 COPS! RUN!",
                            description=(
                                f"You handed over the **{e}** — perfect!\n\n"
                                f"🚔 **SUDDENLY — SIRENS EVERYWHERE!** 🚔\n"
                                f"*Police cars screech around the corner!*\n\n"
                                f"**QUICK! Pick a hiding spot!**"
                            ),
                            color=discord.Color.red()
                        )
                        hiding_spots = random.sample(HIDING_SPOTS_LIST, 3)
                        hide_view = HidingSpotView(self.user_id, hiding_spots, self.economy_guild, self.economy)
                        await interaction.response.edit_message(embed=cop_embed, view=hide_view)
                    else:
                        wrong_embed = discord.Embed(
                            title="😡 That's Not What I Asked For!",
                            description=(
                                f"The dealer wanted **{req_name}** {req_emoji}\n"
                                f"You gave them **{n}** {e}\n\n"
                                f"Deal's off. Get outta here! 😤\n"
                                f"*No pay this time.*"
                            ),
                            color=discord.Color.red()
                        )
                        await interaction.response.edit_message(embed=wrong_embed, view=self)
                return callback

            btn.callback = make_callback()
            self.add_item(btn)


class JobSelectView(discord.ui.View):
    def __init__(self, user_id, economy_guild, economy):
        super().__init__(timeout=30)
        self.user_id = user_id
        self.economy_guild = economy_guild
        self.economy = economy
        self.picked = False

    async def run_job(self, interaction: discord.Interaction, job_name: str):
        if self.picked:
            return
        self.picked = True
        for item in self.children:
            item.disabled = True
        econ_user = ensure_user_economy(self.economy_guild, self.user_id)
        econ_user.setdefault("job_counts", {})[job_name] = econ_user["job_counts"].get(job_name, 0) + 1
        econ_user["last_work"] = time.time()
        save_store(ECONOMY_STORE, self.economy)
        emoji, _ = JOB_DESCRIPTIONS[job_name]
        start_embed = discord.Embed(
            title=f"{emoji} Starting: {job_name}!",
            description="Clocking in... get ready! ⏰",
            color=discord.Color.blurple()
        )
        await interaction.response.edit_message(embed=start_embed, view=self)
        if job_name == "Streamer":
            await job_streamer(interaction, self.economy_guild, self.economy)
        elif job_name == "Garbage Collector":
            await job_garbage_collector(interaction, self.economy_guild, self.economy)
        elif job_name == "Fast Food Worker":
            await job_fast_food(interaction, self.economy_guild, self.economy)
        elif job_name == "Doctor":
            await job_doctor(interaction, self.economy_guild, self.economy)
        elif job_name == "PinHead":
            await job_pinhead(interaction, self.economy_guild, self.economy)

    @discord.ui.button(label="📺 Streamer", style=discord.ButtonStyle.primary)
    async def streamer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your shift!", ephemeral=True)
            return
        await self.run_job(interaction, "Streamer")

    @discord.ui.button(label="🗑️ Garbage Collector", style=discord.ButtonStyle.secondary)
    async def garbage_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your shift!", ephemeral=True)
            return
        await self.run_job(interaction, "Garbage Collector")

    @discord.ui.button(label="🍔 Fast Food Worker", style=discord.ButtonStyle.secondary)
    async def fastfood_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your shift!", ephemeral=True)
            return
        await self.run_job(interaction, "Fast Food Worker")

    @discord.ui.button(label="👨‍⚕️ Doctor", style=discord.ButtonStyle.success)
    async def doctor_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your shift!", ephemeral=True)
            return
        await self.run_job(interaction, "Doctor")

    @discord.ui.button(label="💊 PinHead", style=discord.ButtonStyle.danger)
    async def pinhead_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This isn't your shift!", ephemeral=True)
            return
        await self.run_job(interaction, "PinHead")
    

# ================== JOB FUNCTIONS ==================
async def job_streamer(interaction: discord.Interaction, economy_guild, economy):
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    setup_embed = discord.Embed(
        title="📺 Streamer — Going Live!",
        description=(
            "```\n"
            "  🖥️  ╔══════════════════╗\n"
            "  📷  ║  🔴 LIVE          ║\n"
            "  🎤  ║  Koni Bot TV      ║\n"
            "  💡  ╚══════════════════╝\n"
            "  🪑  [You sit at your desk]\n"
            "```\n"
            "Your chat is sending heart emojis!\n"
            "**Type the COLOR of each heart as fast as you can!**\n\n"
            "*Starting in 3 seconds...*"
        ),
        color=discord.Color.purple()
    )
    await interaction.channel.send(embed=setup_embed)
    await asyncio.sleep(3)

    hearts = random.sample(HEART_COLORS, 6)
    score = 0

    def check(m):
        return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id

    for i, (emoji, color) in enumerate(hearts, 1):
        round_embed = discord.Embed(
            title=f"📺 Live Stream — Heart {i}/6",
            description=(
                f"Your chat explodes with hearts!\n\n"
                f"# {emoji} {emoji} {emoji} {emoji} {emoji}\n\n"
                f"**What color is this heart?**\n"
                f"*Type it in chat — you have 5 seconds!*"
            ),
            color=discord.Color.purple()
        )
        round_embed.set_footer(text=f"Score so far: {score}/{i - 1}")
        await interaction.channel.send(embed=round_embed)
        try:
            response = await bot.wait_for("message", timeout=5.0, check=check)
            if response.content.strip().lower() == color:
                score += 1
                await response.add_reaction("✅")
            else:
                await response.add_reaction("❌")
        except asyncio.TimeoutError:
            pass
        await asyncio.sleep(0.5)

    pay = 600
    econ_user["bank"] = econ_user.get("bank", 0) + pay
    save_store(ECONOMY_STORE, economy)
    stars = "⭐" * score + "☆" * (6 - score)
    result_embed = discord.Embed(
        title="📺 Stream Ended — Paycheck Time!",
        description=(
            f"**Hearts matched:** {score}/6\n"
            f"**Rating:** {stars}\n\n"
            f"🎉 Congrats! Your paycheck of **{pay:,} coins** has been\n"
            f"sent to the **Koni Banking Company**! 🏦"
        ),
        color=discord.Color.green()
    )
    await interaction.channel.send(embed=result_embed)


async def job_garbage_collector(interaction: discord.Interaction, economy_guild, economy):
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    setup_embed = discord.Embed(
        title="🗑️ Garbage Collector — Starting Shift!",
        description=(
            "```\n"
            "  🚛  Koni Waste Management Co.\n"
            "  ══════════════════════════════\n"
            "  [  conveyor belt starting up  ]\n"
            "  ══════════════════════════════\n"
            "```\n"
            "Items will roll across the belt!\n"
            "**Type `trash` when you see the crumpled paper** 📄\n\n"
            "*Starting in 3 seconds...*"
        ),
        color=discord.Color.dark_grey()
    )
    await interaction.channel.send(embed=setup_embed)
    await asyncio.sleep(3)

    sequence = ["normal"] * 8
    trash_positions = random.sample(range(8), 3)
    for pos in trash_positions:
        sequence[pos] = "trash"

    caught = 0
    missed = 0
    total_trash = len(trash_positions)

    def check(m):
        return (
            m.author.id == interaction.user.id
            and m.channel.id == interaction.channel.id
            and m.content.strip().lower() == "trash"
        )

    belt_msg = await interaction.channel.send("🏭 Belt is warming up...")

    for i, item_type in enumerate(sequence):
        if item_type == "trash":
            item = TRASH_ITEM
            color = discord.Color.yellow()
            note = "⚠️ **TRASH SPOTTED! Type `trash` NOW!**"
        else:
            item = random.choice(CONVEYOR_ITEMS)
            color = discord.Color.dark_grey()
            note = "Keep watching the belt..."

        slots = ["▫️"] * 8
        slots[i] = item
        belt_display = " ".join(slots)

        belt_embed = discord.Embed(
            title="🗑️ Garbage Collector — On the Job",
            description=(
                f"```\n"
                f"  ════ CONVEYOR BELT ════\n"
                f"  {belt_display}\n"
                f"  ══════════════════════\n"
                f"```\n"
                f"{note}"
            ),
            color=color
        )
        belt_embed.set_footer(text=f"Item {i + 1}/8 | Caught: {caught} | Missed: {missed}")
        await belt_msg.edit(embed=belt_embed)

        if item_type == "trash":
            try:
                await bot.wait_for("message", timeout=3.0, check=check)
                caught += 1
            except asyncio.TimeoutError:
                missed += 1
        else:
            await asyncio.sleep(2.5)

    pay = 500
    econ_user["bank"] = econ_user.get("bank", 0) + pay
    save_store(ECONOMY_STORE, economy)
    result_embed = discord.Embed(
        title="🗑️ Shift Complete!",
        description=(
            f"**Trash caught:** {caught}/{total_trash}\n"
            f"**Missed:** {missed}\n\n"
            f"💸 Paycheck of **{pay:,} coins** sent to the **Koni Banking Company**! 🏦"
        ),
        color=discord.Color.green()
    )
    await interaction.channel.send(embed=result_embed)


async def job_fast_food(interaction: discord.Interaction, economy_guild, economy):
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    setup_embed = discord.Embed(
        title="🍔 Fast Food Worker — Starting Shift!",
        description=(
            "```\n"
            "  🏪  Koni Burger™\n"
            "  ┌─────────────────────────┐\n"
            "  │   🧑‍🍳 You man the counter │\n"
            "  └─────────────────────────┘\n"
            "```\n"
            "Orders slide across the counter!\n"
            "**Type `trash` when a non-food item slides by** 🧹\n\n"
            "*Starting in 3 seconds...*"
        ),
        color=discord.Color.orange()
    )
    await interaction.channel.send(embed=setup_embed)
    await asyncio.sleep(3)

    sequence = ["food"] * 8
    non_food_positions = random.sample(range(8), 3)
    for pos in non_food_positions:
        sequence[pos] = "non-food"

    caught = 0
    missed = 0
    total_non_food = len(non_food_positions)

    def check(m):
        return (
            m.author.id == interaction.user.id
            and m.channel.id == interaction.channel.id
            and m.content.strip().lower() == "trash"
        )

    counter_msg = await interaction.channel.send("🍔 Counter is opening...")

    for i, item_type in enumerate(sequence):
        if item_type == "non-food":
            item = NON_FOOD_ITEM
            color = discord.Color.red()
            note = "🚨 **NOT FOOD! Type `trash` quick!**"
        else:
            item = random.choice(FOOD_ITEMS)
            color = discord.Color.orange()
            note = "Serve the order normally..."

        slots = ["▫️"] * 8
        slots[i] = item
        counter_display = " ".join(slots)

        counter_embed = discord.Embed(
            title="🍔 Fast Food Worker — On the Counter",
            description=(
                f"```\n"
                f"  ═══ COUNTER ═══\n"
                f"  {counter_display}\n"
                f"  ════════════════\n"
                f"```\n"
                f"{note}"
            ),
            color=color
        )
        counter_embed.set_footer(text=f"Item {i + 1}/8 | Caught: {caught} | Missed: {missed}")
        await counter_msg.edit(embed=counter_embed)

        if item_type == "non-food":
            try:
                await bot.wait_for("message", timeout=3.0, check=check)
                caught += 1
            except asyncio.TimeoutError:
                missed += 1
        else:
            await asyncio.sleep(2.5)

    pay = 550
    econ_user["bank"] = econ_user.get("bank", 0) + pay
    save_store(ECONOMY_STORE, economy)
    result_embed = discord.Embed(
        title="🍔 Shift Over!",
        description=(
            f"**Non-food caught:** {caught}/{total_non_food}\n"
            f"**Missed:** {missed}\n\n"
            f"💸 Paycheck of **{pay:,} coins** sent to the **Koni Banking Company**! 🏦"
        ),
        color=discord.Color.green()
    )
    await interaction.channel.send(embed=result_embed)


async def job_doctor(interaction: discord.Interaction, economy_guild, economy):
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    patient = random.choice(BODY_PARTS)

    setup_embed = discord.Embed(
        title="👨‍⚕️ Doctor — Patient Incoming!",
        description=(
            "```\n"
            "  🏥  Koni Medical Center\n"
            "  ══════════════════════════\n"
            "  [A patient rushes through\n"
            "   the door clutching a limb]\n"
            "  ══════════════════════════\n"
            "```\n"
            "Study the X-Ray and **type the name of the broken body part!**\n"
            "*You have 15 seconds to diagnose.*"
        ),
        color=discord.Color.blue()
    )
    await interaction.channel.send(embed=setup_embed)
    await asyncio.sleep(2)

    xray_embed = discord.Embed(
        title="👨‍⚕️ X-Ray Results",
        description=(
            f"🩻 **Patient X-Ray:**\n\n"
            f"{patient['display']}\n\n"
            f"**Which body part is broken?**\n"
            f"*Type your answer in chat — 15 seconds!*"
        ),
        color=discord.Color.blue()
    )
    await interaction.channel.send(embed=xray_embed)

    def check(m):
        return m.author.id == interaction.user.id and m.channel.id == interaction.channel.id

    try:
        response = await bot.wait_for("message", timeout=15.0, check=check)
        answer = response.content.strip().lower()
        if answer in patient["answers"]:
            pay = 800
            econ_user["bank"] = econ_user.get("bank", 0) + pay
            save_store(ECONOMY_STORE, economy)
            await response.add_reaction("✅")
            result_embed = discord.Embed(
                title="👨‍⚕️ Correct Diagnosis!",
                description=(
                    f"✅ It was the **{patient['name']}**!\n\n"
                    f"The patient will make a full recovery! 🏥\n\n"
                    f"💸 Paycheck of **{pay:,} coins** sent to the **Koni Banking Company**! 🏦"
                ),
                color=discord.Color.green()
            )
        else:
            await response.add_reaction("❌")
            result_embed = discord.Embed(
                title="👨‍⚕️ Wrong Diagnosis!",
                description=(
                    f"❌ It was the **{patient['name']}**, not `{response.content}`!\n\n"
                    f"The patient is calling their lawyer... 😬\n"
                    f"*No pay this time.*"
                ),
                color=discord.Color.red()
            )
    except asyncio.TimeoutError:
        result_embed = discord.Embed(
            title="👨‍⚕️ Patient Walked Out!",
            description=(
                f"You took too long! The patient left.\n"
                f"It was the **{patient['name']}** by the way.\n"
                f"*No pay this time.*"
            ),
            color=discord.Color.red()
        )
    await interaction.channel.send(embed=result_embed)


async def job_pinhead(interaction: discord.Interaction, economy_guild, economy):
    requested_item = random.choice(PINHEAD_ITEMS)
    req_emoji, req_name = requested_item

    setup_embed = discord.Embed(
        title="💊 PinHead — Shady Meeting...",
        description=(
            "```\n"
            "  🌑  Dark Alley, 2:00 AM\n"
            "  ════════════════════════\n"
            "  [A hooded figure steps out\n"
            "   from the shadows...]\n"
            "  ════════════════════════\n"
            "```\n"
            f"*\"Psst... hey. You got the* **{req_emoji}** *?\"*\n\n"
            f"**Pick the right item from the buttons below!**\n"
            f"⚠️ *Wrong item = deal's off. Right item = cops show up.*"
        ),
        color=discord.Color.dark_purple()
    )
    view = PinHeadItemView(interaction.user.id, requested_item, economy_guild, economy)
    await interaction.channel.send(embed=setup_embed, view=view)

    
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
    sorted_users = sorted(glevels.items(), key=lambda x: (x[1].get("level", 1), x[1].get("xp", 0)), reverse=True)[:10]
    embed = discord.Embed(title="🏆 Level Leaderboard", color=discord.Color.gold())
    for i, (user_id, data) in enumerate(sorted_users, start=1):
        member = interaction.guild.get_member(int(user_id))
        if member:
            embed.add_field(name=f"{i}. {member.display_name}", value=f"Level {data.get('level', 1)} | {data.get('xp', 0)} XP", inline=False)
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


@tree.command(name="clearlevelupbackground", description="Reset level-up background to default")
@app_commands.checks.has_permissions(administrator=True)
async def clearlevelupbackground(interaction: discord.Interaction):
    gset, settings = get_guild_settings(interaction.guild.id)
    gset["levelup_bg"] = None
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message("✅ Level-up background reset to default.", ephemeral=True)


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
    await send_response(interaction, f"✅ Daily claimed! +{base_coins + bonus} coins, +{base_xp + bonus} XP. 🔥 Streak: {econ_user['daily_streak']}")


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
    receiver["rep"] = receiver.get("rep", 0) + 1
    giver["rep_last"] = now
    giver["rep_given_to"] = member.id
    save_store(ECONOMY_STORE, economy)
    embed = discord.Embed(
        title="⭐ Rep Given!",
        description=f"You gave **{member.display_name}** a reputation point!\nThey now have **{receiver['rep']}** rep. 🌟",
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed)


@tree.command(name="grind", description="Guess the emoji combo and win 30 XP!")
@app_commands.describe(genre="Pick your category")
@app_commands.choices(genre=GRIND_GENRE_CHOICES)
async def grind(interaction: discord.Interaction, genre: app_commands.Choice[str]):
    uid = interaction.user.id
    now = time.time()
    cooldown = 120
    if uid in GRIND_COOLDOWNS and now - GRIND_COOLDOWNS[uid] < cooldown:
        remaining = int(cooldown - (now - GRIND_COOLDOWNS[uid]))
        await interaction.response.send_message(f"⏳ You're still cooling down! Try again in **{remaining}s**.", ephemeral=True)
        return
    question = random.choice(GRIND_QUESTIONS[genre.value])
    emojis = question["emojis"]
    answers = question["answer"]
    time_limit = 180
    embed = discord.Embed(
        title="🧠 Time to put your brain to the test!",
        description=(
            f"**Win this and you'll get +30 XP!**\n"
            f"Koni will laugh at you if you lose this and take away 15 XP >:)\n\n"
            f"**Category:** {genre.name}\n\n"
            f"# {emojis}\n\n"
            f"⏱️ You have **3:00** to answer!\n"
            f"Type your answer in the chat below."
        ),
        color=discord.Color.blurple()
    )
    embed.set_footer(text=f"Requested by {interaction.user.display_name}")
    await interaction.response.send_message(embed=embed)
    prompt_msg = await interaction.original_response()
    GRIND_COOLDOWNS[uid] = now
    countdown_stop = asyncio.Event()

    async def countdown_task():
        for remaining in range(time_limit - 1, 0, -1):
            if countdown_stop.is_set():
                return
            await asyncio.sleep(1)
            if countdown_stop.is_set():
                return
            if remaining % 15 == 0 or remaining <= 10:
                mins = remaining // 60
                secs = remaining % 60
                try:
                    updated_embed = discord.Embed(
                        title="🧠 Time to put your brain to the test!",
                        description=(
                            f"**Win this and you'll get +30 XP!**\n"
                            f"Koni will laugh at you if you lose this and take away 15 XP >:)\n\n"
                            f"**Category:** {genre.name}\n\n"
                            f"# {emojis}\n\n"
                            f"⏱️ You have **{mins}:{secs:02d}** to answer!\n"
                            f"Type your answer in the chat below."
                        ),
                        color=discord.Color.blurple()
                    )
                    updated_embed.set_footer(text=f"Requested by {interaction.user.display_name}")
                    await prompt_msg.edit(embed=updated_embed)
                except discord.HTTPException:
                    return

    countdown = asyncio.create_task(countdown_task())

    def check(msg):
        return msg.author.id == interaction.user.id and msg.channel.id == interaction.channel.id

    try:
        msg = await bot.wait_for("message", timeout=float(time_limit), check=check)
        countdown_stop.set()
        await countdown
    except asyncio.TimeoutError:
        countdown_stop.set()
        await countdown
        glevels, levels = get_level_data(interaction.guild.id)
        user = glevels.setdefault(str(interaction.user.id), {"xp": 0, "level": 1, "last": 0})
        user["xp"] = max(0, user["xp"] - 15)
        save_store(LEVEL_STORE, levels)
        timeout_embed = discord.Embed(
            title="😂 Koni is laughing at you!",
            description=f"You ran out of time! The answer was **{answers[0].title()}**\n\n-15 XP has been taken. Embarrassing! 💀",
            color=discord.Color.red()
        )
        timeout_embed.set_image(url=LAUGH_IMAGE_URL)
        await interaction.followup.send(embed=timeout_embed)
        return

    if msg.content.strip().lower() in answers:
        glevels, levels = get_level_data(interaction.guild.id)
        user = glevels.setdefault(str(interaction.user.id), {"xp": 0, "level": 1, "last": 0})
        user["xp"] += 30
        save_store(LEVEL_STORE, levels)
        win_embed = discord.Embed(
            title="🎉 Correct!",
            description=f"**{answers[0].title()}** was right!\n\n+30 XP added. Koni is impressed... barely. 😏",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=win_embed)
    else:
        glevels, levels = get_level_data(interaction.guild.id)
        user = glevels.setdefault(str(interaction.user.id), {"xp": 0, "level": 1, "last": 0})
        user["xp"] = max(0, user["xp"] - 15)
        save_store(LEVEL_STORE, levels)
        lose_embed = discord.Embed(
            title="😂 Koni is HOWLING!",
            description=f"Wrong! The answer was **{answers[0].title()}**\n\n-15 XP taken. You call yourself a gamer? 💀",
            color=discord.Color.red()
        )
        lose_embed.set_image(url=LAUGH_IMAGE_URL)
        await interaction.followup.send(embed=lose_embed)


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


@tree.command(name="clearlevelchannel", description="Reset level-up messages back to same channel")
@app_commands.checks.has_permissions(administrator=True)
async def clearlevelchannel(interaction: discord.Interaction):
    gset, settings = get_guild_settings(interaction.guild.id)
    gset["level_channel"] = None
    save_store(SETTINGS_STORE, settings)
    await interaction.response.send_message("✅ Level-up channel cleared.", ephemeral=True)


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


@tree.command(name="unblacklistxp", description="Re-enable XP in a blacklisted channel")
@app_commands.checks.has_permissions(administrator=True)
async def unblacklistxp(interaction: discord.Interaction, channel: discord.TextChannel):
    gset, settings = get_guild_settings(interaction.guild.id)
    if str(channel.id) in gset["ignored_channels"]:
        gset["ignored_channels"].remove(str(channel.id))
        save_store(SETTINGS_STORE, settings)
        await interaction.response.send_message(f"✅ XP re-enabled in {channel.mention}", ephemeral=True)
    else:
        await interaction.response.send_message("❌ That channel isn't blacklisted.", ephemeral=True)


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
    await interaction.response.send_message(f"✅ Set {member.mention} to level {max(1, int(level))} with {max(0, int(xp))} XP.", ephemeral=True)


@tree.command(name="pocket", description="Check your wallet and bank balance")
async def pocket(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, member.id)
    coins = econ_user.get("coins", 0)
    bank = econ_user.get("bank", 0)
    embed = discord.Embed(
        title=f"👛 {member.display_name}'s Wallet",
        description=(
            f"💵 **Pocket** — `{coins:,}` coins\n"
            f"🏦 **Bank** — `{bank:,}` coins\n"
            f"💰 **Total** — `{coins + bank:,}` coins"
        ),
        color=discord.Color.gold()
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Use /deposit and /withdraw to move your coins")
    await interaction.response.send_message(embed=embed)


@tree.command(name="deposit", description="Deposit coins from your pocket into the Koni Bank")
@app_commands.describe(amount="Amount to deposit, or type 'all'")
async def deposit(interaction: discord.Interaction, amount: str):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    if amount.lower() == "all":
        amt = econ_user.get("coins", 0)
    else:
        try:
            amt = int(amount)
        except ValueError:
            await interaction.response.send_message("❌ Enter a number or `all`.", ephemeral=True)
            return
    if amt <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
        return
    if econ_user.get("coins", 0) < amt:
        await interaction.response.send_message(f"❌ You only have **{econ_user.get('coins', 0):,}** coins in your pocket.", ephemeral=True)
        return
    econ_user["coins"] -= amt
    econ_user["bank"] = econ_user.get("bank", 0) + amt
    save_store(ECONOMY_STORE, economy)
    embed = discord.Embed(title="🏦 Deposit Successful!", description=f"**{amt:,} coins** safely stored in the Koni Bank! 💸", color=discord.Color.green())
    embed.add_field(name="💵 Pocket", value=f"`{econ_user['coins']:,}` coins", inline=True)
    embed.add_field(name="🏦 Bank", value=f"`{econ_user['bank']:,}` coins", inline=True)
    await interaction.response.send_message(embed=embed)


@tree.command(name="withdraw", description="Withdraw coins from the Koni Bank to your pocket")
@app_commands.describe(amount="Amount to withdraw, or type 'all'")
async def withdraw(interaction: discord.Interaction, amount: str):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    if amount.lower() == "all":
        amt = econ_user.get("bank", 0)
    else:
        try:
            amt = int(amount)
        except ValueError:
            await interaction.response.send_message("❌ Enter a number or `all`.", ephemeral=True)
            return
    if amt <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
        return
    if econ_user.get("bank", 0) < amt:
        await interaction.response.send_message(f"❌ You only have **{econ_user.get('bank', 0):,}** coins in your bank.", ephemeral=True)
        return
    econ_user["bank"] -= amt
    econ_user["coins"] = econ_user.get("coins", 0) + amt
    save_store(ECONOMY_STORE, economy)
    embed = discord.Embed(title="💵 Withdrawal Successful!", description=f"**{amt:,} coins** moved to your pocket! 💸", color=discord.Color.green())
    embed.add_field(name="💵 Pocket", value=f"`{econ_user['coins']:,}` coins", inline=True)
    embed.add_field(name="🏦 Bank", value=f"`{econ_user['bank']:,}` coins", inline=True)
    await interaction.response.send_message(embed=embed)


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


@tree.command(name="work", description="Clock in for your shift and choose a job to earn coins")
async def work(interaction: discord.Interaction):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    if is_in_jail(econ_user):
        remaining = max(0, int(econ_user.get("jail_until", 0) - time.time()))
        mins = remaining // 60
        secs = remaining % 60
        save_store(ECONOMY_STORE, economy)
        await interaction.response.send_message(
            f"⛓️ **You're in jail!** You can't work right now.\n"
            f"⏳ Time remaining: **{mins}m {secs}s**\n"
            f"💸 Bail amount: **{econ_user.get('bail_amount', 0):,} coins**",
            ephemeral=True
        )
        return
    now = time.time()
    if now - econ_user.get("last_work", 0) < 3600:
        remaining = int(3600 - (now - econ_user.get("last_work", 0)))
        mins = remaining // 60
        secs = remaining % 60
        await interaction.response.send_message(f"⏳ You already worked recently! Rest up.\nTry again in **{mins}m {secs}s**.", ephemeral=True)
        return
    desc_lines = [f"{emoji} **{job}** — {desc}" for job, (emoji, desc) in JOB_DESCRIPTIONS.items()]
    embed = discord.Embed(
        title="💼 Time to Clock In!",
        description=(
            "```\n"
            "  🏢  Koni Employment Agency\n"
            "  ══════════════════════════\n"
            "  Choose your job for today!\n"
            "  ══════════════════════════\n"
            "```\n" +
            "\n".join(desc_lines) +
            "\n\n*Pick a job below — you have 30 seconds!*"
        ),
        color=discord.Color.blurple()
    )
    embed.set_footer(text="💡 All paychecks go directly to your Koni Bank account 🏦")
    view = JobSelectView(interaction.user.id, economy_guild, economy)
    await interaction.response.send_message(embed=embed, view=view)


@tree.command(name="shop", description="View the background shop")
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


@tree.command(name="store", description="Browse the Koni Luxury Store — cars, houses, and exotic animals")
async def store(interaction: discord.Interaction):
    view = StoreCategoryView(interaction.user.id, interaction.guild.id)
    await interaction.response.send_message(embed=view.build_embed(), view=view)


@tree.command(name="properties", description="View all the luxury items you own")
async def properties(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    prop_guild, _ = get_property_data(interaction.guild.id)
    user_props = ensure_user_properties(prop_guild, member.id)
    if not user_props:
        embed = discord.Embed(
            title="🏬 No Properties Yet!",
            description=f"**{member.display_name}** doesn't own anything from the Koni Store yet.\n\nHead to `/store` to start building your empire! 👑",
            color=discord.Color.greyple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return
    view = PropertiesView(member.id, user_props)
    await interaction.response.send_message(embed=view.build_embed(), view=view)


@tree.command(name="rob", description="Play rock paper scissors to rob coins from someone's bank")
@app_commands.describe(member="The user you want to rob", amount="How many coins to attempt to steal")
async def rob(interaction: discord.Interaction, member: discord.Member, amount: int):
    if member.bot or member.id == interaction.user.id:
        await interaction.response.send_message("❌ You can't rob that user.", ephemeral=True)
        return
    if amount <= 0:
        await interaction.response.send_message("❌ Amount must be greater than 0.", ephemeral=True)
        return
    economy_guild, economy = get_economy_data(interaction.guild.id)
    robber = ensure_user_economy(economy_guild, interaction.user.id)
    target = ensure_user_economy(economy_guild, member.id)
    if is_in_jail(robber):
        remaining = max(0, int(robber.get("jail_until", 0) - time.time()))
        mins = remaining // 60
        secs = remaining % 60
        save_store(ECONOMY_STORE, economy)
        await interaction.response.send_message(
            f"⛓️ **You're in jail!** You can't rob anyone right now.\n"
            f"⏳ Time remaining: **{mins}m {secs}s**\n"
            f"💸 Bail amount: **{robber.get('bail_amount', 0):,} coins**",
            ephemeral=True
        )
        return
    if target.get("bank", 0) <= 0:
        await interaction.response.send_message(f"❌ {member.display_name}'s bank is completely empty. Nothing to steal!", ephemeral=True)
        return
    if target.get("bank", 0) < amount:
        await interaction.response.send_message(
            f"❌ {member.display_name} only has **{target.get('bank', 0):,} coins** in their bank.\n"
            f"Try robbing **{target.get('bank', 0):,}** or less.", ephemeral=True
        )
        return
    embed = discord.Embed(
        title="🦹 Robbery in Progress!",
        description=(
            f"You're targeting **{member.display_name}** for **{amount:,} coins** from their bank!\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🪨 **Rock** beats ✂️ Scissors\n"
            f"📄 **Paper** beats 🪨 Rock\n"
            f"✂️ **Scissors** beats 📄 Paper\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏆 **Win** → Steal **{amount:,} coins** straight to your pocket\n"
            f"🚔 **Lose** → Jail + bail of **{amount:,} coins**\n"
            f"🤝 **Tie** → Nobody wins, try again later\n\n"
            f"*Make your move! You have 30 seconds.*"
        ),
        color=discord.Color.dark_orange()
    )
    embed.set_footer(text=f"Robber: {interaction.user.display_name} | Target: {member.display_name}")
    view = RPSView(interaction.user.id, target, amount, economy_guild, economy)
    await interaction.response.send_message(embed=embed, view=view)


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


@tree.command(name="profile", description="View a user's full profile card")
async def profile(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    member = member or interaction.user
    glevels, _ = get_level_data(interaction.guild.id)
    gset, _ = get_guild_settings(interaction.guild.id)
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, member.id)
    user_level_data = glevels.get(str(member.id), {"xp": 0, "level": 1})
    level = user_level_data.get("level", 1)
    xp = user_level_data.get("xp", 0)
    required_xp = xp_needed(level)
    rewards = gset.get("role_rewards", {})
    if not rewards:
        role_reward_text = "*No role rewards configured in this server*"
    else:
        earned = [(int(lvl), rid) for lvl, rid in rewards.items() if int(lvl) <= level]
        if earned:
            best = max(earned, key=lambda x: x[0])
            role = interaction.guild.get_role(int(best[1]))
            role_reward_text = f"{role.mention} *(Level {best[0]})*" if role else "Unknown Role"
        else:
            role_reward_text = "None earned yet — keep leveling! 📈"
    married_to = econ_user.get("married_to")
    if married_to:
        partner = interaction.guild.get_member(int(married_to))
        marriage_text = f"💍 {partner.mention}" if partner else "💍 *Partner not in server*"
    else:
        marriage_text = "💔 Single"
    divorced_count = econ_user.get("divorced_count", 0)
    rep_given_to = econ_user.get("rep_given_to")
    if rep_given_to:
        rep_target = interaction.guild.get_member(int(rep_given_to))
        rep_text = f"{rep_target.mention}" if rep_target else "*Someone not in server*"
    else:
        rep_text = "*Nobody yet*"
    job_counts = econ_user.get("job_counts", {})
    job_emojis = {
        "Streamer": "📺", "Garbage Collector": "🗑️",
        "Fast Food Worker": "🍔", "Doctor": "👨‍⚕️", "PinHead": "💊"
    }
    if job_counts:
        fav_job = max(job_counts, key=job_counts.get)
        fav_count = job_counts[fav_job]
        fav_job_text = f"{job_emojis.get(fav_job, '👔')} {fav_job} *({fav_count}x)*"
    else:
        fav_job_text = "*Never worked 😴*"
    socials = econ_user.get("socials", {})
    socials_text = "\n".join([f"**{p}** — {h}" for p, h in socials.items()]) if socials else "*No socials added yet*"
    color_hex = econ_user.get("color")
    try:
        color = discord.Color(int(color_hex.strip("#"), 16)) if color_hex else discord.Color.blurple()
    except Exception:
        color = discord.Color.blurple()
    badge = econ_user.get("badge") or ""
    prestige = econ_user.get("prestige", 0)
    prestige_stars = "⭐" * prestige if prestige else ""
    banner = random.choice(PROFILE_BANNERS)
    bar_fill = int((xp / required_xp) * 10) if required_xp else 0
    xp_bar = "█" * bar_fill + "░" * (10 - bar_fill)
    embed = discord.Embed(
        title=f"{banner}",
        description=f"## {prestige_stars} {member.display_name} {badge}\n*{member.name}*",
        color=color
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.add_field(name="📊 Level", value=f"**{level}**\n`{xp_bar}` {xp:,}/{required_xp:,} XP", inline=True)
    embed.add_field(name="⭐ Rep", value=f"**{econ_user.get('rep', 0)}** points\nRepping: {rep_text}", inline=True)
    embed.add_field(name="👔 Fav Job", value=fav_job_text, inline=True)
    embed.add_field(name="💵 Pocket", value=f"`{econ_user.get('coins', 0):,}` coins", inline=True)
    embed.add_field(name="🏦 Bank", value=f"`{econ_user.get('bank', 0):,}` coins", inline=True)
    embed.add_field(name="🎭 Latest Role Reward", value=role_reward_text, inline=False)
    embed.add_field(name="💍 Relationship", value=marriage_text, inline=True)
    embed.add_field(name="💔 Times Divorced", value=f"**{divorced_count}**", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)
    embed.add_field(name="📱 Socials & Streams", value=socials_text, inline=False)
    embed.set_footer(text=f"Prestige {prestige} • {member.display_name}", icon_url=member.display_avatar.url)
    await interaction.response.send_message(embed=embed)


@tree.command(name="addsocial", description="Add a social media or stream link to your profile")
@app_commands.describe(platform="Which platform", handle="Your username or full link")
@app_commands.choices(platform=SOCIAL_PLATFORMS)
async def addsocial(interaction: discord.Interaction, platform: app_commands.Choice[str], handle: str):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    econ_user.setdefault("socials", {})[platform.value] = handle
    save_store(ECONOMY_STORE, economy)
    await interaction.response.send_message(f"✅ Added **{platform.name}**: `{handle}` to your profile!", ephemeral=True)


@tree.command(name="removesocial", description="Remove a social from your profile")
@app_commands.describe(platform="Which platform to remove")
@app_commands.choices(platform=SOCIAL_PLATFORMS)
async def removesocial(interaction: discord.Interaction, platform: app_commands.Choice[str]):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    if platform.value not in econ_user.get("socials", {}):
        await interaction.response.send_message(f"❌ You don't have **{platform.name}** on your profile.", ephemeral=True)
        return
    del econ_user["socials"][platform.value]
    save_store(ECONOMY_STORE, economy)
    await interaction.response.send_message(f"✅ Removed **{platform.name}** from your profile.", ephemeral=True)


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


@tree.command(name="clearcolor", description="Reset your rank card color to default")
async def clearcolor(interaction: discord.Interaction):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    econ_user["color"] = None
    save_store(ECONOMY_STORE, economy)
    await interaction.response.send_message("🎨 Rank card color reset to default.", ephemeral=True)


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


@tree.command(name="clearbadge", description="Remove your active badge")
async def clearbadge(interaction: discord.Interaction):
    economy_guild, economy = get_economy_data(interaction.guild.id)
    econ_user = ensure_user_economy(economy_guild, interaction.user.id)
    econ_user["badge"] = None
    save_store(ECONOMY_STORE, economy)
    await interaction.response.send_message("🏅 Badge removed.", ephemeral=True)


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
    user["divorced_count"] = user.get("divorced_count", 0) + 1
    partner["married_to"] = None
    partner["divorced_count"] = partner.get("divorced_count", 0) + 1
    save_store(ECONOMY_STORE, economy)
    await interaction.response.send_message(
        "💔 How could you! you dirty bastard whyd you cheat?! thats it if i cant have you nobody can! *grabs shotgun*"
    )


# ================== ROLE TRACKER COMMANDS ==================
@tree.command(name="trackrole", description="Add a role to the tracker")
@app_commands.checks.has_permissions(administrator=True)
async def trackrole(interaction: discord.Interaction, role: discord.Role):
    guild_data, data = get_tracker_data(interaction.guild.id)
    tracked = guild_data.setdefault("tracked", {})
    if str(role.id) in tracked:
        await interaction.response.send_message(f"❌ {role.mention} is already being tracked.", ephemeral=True)
        return
    tracked[str(role.id)] = role.name
    save_store(ROLE_TRACKER_STORE, data)
    list_msg = guild_data.get("list_message")
    if list_msg:
        try:
            ch = interaction.guild.get_channel(list_msg["channel_id"])
            msg = await ch.fetch_message(list_msg["message_id"])
            await msg.edit(embed=build_role_tracker_embed(interaction.guild, list(tracked.keys())))
        except Exception:
            pass
    await interaction.response.send_message(f"✅ Now tracking {role.mention}.", ephemeral=True)


@tree.command(name="untrackrole", description="Remove a role from the tracker")
@app_commands.checks.has_permissions(administrator=True)
async def untrackrole(interaction: discord.Interaction, role: discord.Role):
    guild_data, data = get_tracker_data(interaction.guild.id)
    tracked = guild_data.setdefault("tracked", {})
    if str(role.id) not in tracked:
        await interaction.response.send_message(f"❌ {role.mention} is not being tracked.", ephemeral=True)
        return
    del tracked[str(role.id)]
    save_store(ROLE_TRACKER_STORE, data)
    list_msg = guild_data.get("list_message")
    if list_msg:
        try:
            ch = interaction.guild.get_channel(list_msg["channel_id"])
            msg = await ch.fetch_message(list_msg["message_id"])
            await msg.edit(embed=build_role_tracker_embed(interaction.guild, list(tracked.keys())))
        except Exception:
            pass
    await interaction.response.send_message(f"✅ Stopped tracking {role.mention}.", ephemeral=True)


@tree.command(name="trackroleall", description="Track every role in the server")
@app_commands.checks.has_permissions(administrator=True)
async def trackroleall(interaction: discord.Interaction):
    guild_data, data = get_tracker_data(interaction.guild.id)
    tracked = guild_data.setdefault("tracked", {})
    added = 0
    for role in interaction.guild.roles:
        if role.is_default():
            continue
        if str(role.id) not in tracked:
            tracked[str(role.id)] = role.name
            added += 1
    save_store(ROLE_TRACKER_STORE, data)
    list_msg = guild_data.get("list_message")
    if list_msg:
        try:
            ch = interaction.guild.get_channel(list_msg["channel_id"])
            msg = await ch.fetch_message(list_msg["message_id"])
            await msg.edit(embed=build_role_tracker_embed(interaction.guild, list(tracked.keys())))
        except Exception:
            pass
    await interaction.response.send_message(f"✅ Now tracking all {added} roles.", ephemeral=True)


@tree.command(name="untrackroleall", description="Remove all roles from the tracker")
@app_commands.checks.has_permissions(administrator=True)
async def untrackroleall(interaction: discord.Interaction):
    guild_data, data = get_tracker_data(interaction.guild.id)
    guild_data["tracked"] = {}
    save_store(ROLE_TRACKER_STORE, data)
    list_msg = guild_data.get("list_message")
    if list_msg:
        try:
            ch = interaction.guild.get_channel(list_msg["channel_id"])
            msg = await ch.fetch_message(list_msg["message_id"])
            await msg.edit(embed=build_role_tracker_embed(interaction.guild, []))
        except Exception:
            pass
    await interaction.response.send_message("✅ All roles untracked.", ephemeral=True)


@tree.command(name="trackrolelist", description="Post the live role tracker panel in this channel")
@app_commands.checks.has_permissions(administrator=True)
async def trackrolelist(interaction: discord.Interaction):
    guild_data, data = get_tracker_data(interaction.guild.id)
    tracked = guild_data.get("tracked", {})
    embed = build_role_tracker_embed(interaction.guild, list(tracked.keys()))
    await interaction.response.send_message("✅ Role tracker posted!", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    guild_data["list_message"] = {"channel_id": interaction.channel.id, "message_id": msg.id}
    save_store(ROLE_TRACKER_STORE, data)


@tree.command(name="trackrolelist_clear", description="Remove the live role tracker panel")
@app_commands.checks.has_permissions(administrator=True)
async def trackrolelist_clear(interaction: discord.Interaction):
    guild_data, data = get_tracker_data(interaction.guild.id)
    list_msg = guild_data.get("list_message")
    if list_msg:
        try:
            ch = interaction.guild.get_channel(list_msg["channel_id"])
            msg = await ch.fetch_message(list_msg["message_id"])
            await msg.delete()
        except Exception:
            pass
        guild_data["list_message"] = None
        save_store(ROLE_TRACKER_STORE, data)
    await interaction.response.send_message("✅ Role tracker panel removed.", ephemeral=True)


# ================== START BOT ==================
if __name__ == "__main__":
    bot.run(os.getenv("DISCORD_TOKEN"))        
