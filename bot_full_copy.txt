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

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
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
        "xp_range": [30, 60],
        "cooldown": 5,
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
    {"name": "balance", "usage": "/balance [@user]", "desc": "Check coin balance."},
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
    {"name": "setrankbackground", "usage": "/setrankbackground <image>", "desc": "Set rank background."},
    {"name": "setlevelupbackground", "usage": "/setlevelupbackground <image>", "desc": "Set level-up background."},
    {"name": "setrolereward", "usage": "/setrolereward <level> @role", "desc": "Set role reward."},
    {"name": "removerolereward", "usage": "/removerolereward <level>", "desc": "Remove role reward."},
    {"name": "rolerewards", "usage": "/rolerewards", "desc": "List role rewards."},
    {"name": "trackrole", "usage": "/trackrole @role", "desc": "Track a role count."},
    {"name": "untrackrole", "usage": "/untrackrole @role", "desc": "Untrack a role."},
    {"name": "trackrolelist", "usage": "/trackrolelist", "desc": "Post tracked roles list."},
    {"name": "trackroleall", "usage": "/trackroleall", "desc": "Track all roles."},
    {"name": "untrackroleall", "usage": "/untrackroleall", "desc": "Untrack all roles."}
]

def help_embed():
    categories = {
        "🎮 Fun / Social": ["daily", "rep", "coinflip", "8ball", "meme", "roast"],
        "🏆 Leveling": ["rank", "leaderboard", "prestige", "levelroles", "levelnotify", "backgrounds"],
        "💬 Chat Boosters": ["question", "wouldyourather", "topic"],
        "🛠️ Admin": ["setlevelchannel", "setxpmultiplier", "blacklistxp", "resetuserxp", "setxp", "setcooldown"],
        "💰 Economy": ["balance", "work", "shop", "buybackground", "gamblerist", "koniheist", "divorce"],
        "🎨 Cosmetics": ["setcolor", "setbadge", "profile", "voicebonus", "afk", "marry"],
        "📌 Role Tracking": ["trackrole", "untrackrole", "trackrolelist", "trackroleall", "untrackroleall"],
        "🖼️ Backgrounds": ["setrankbackground", "setlevelupbackground", "setrolereward", "removerolereward", "rolerewards"]
    }
    embed = discord.Embed(
        title="📖 Command Center",
        description="Use the buttons below to run popular commands without typing `/`, or select a command to view usage.",
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
    "You're the reason the \"undo\" button exists.",
    "You're the sequel nobody wanted.",
    "You're a day-one bug with no hotfix.",
    "You're the slow clap of disappointment.",
    "You're the backup plan's backup plan.",
    "You're a salad without the dressing.",
    "You're a GPS that says \"recalculating\" forever.",
    "You're a sunrise in grayscale.",
    "You're a default ringtone in a world of playlists.",
    "You're an off-brand superhero.",
    "You're a puzzle with missing pieces.",
    "You're a shortcut to nowhere.",
    "You're the Wi-Fi signal in a basement.",
    "You're a vending machine that keeps your coins.",
    "You're a crowd with no cheers.",
    "You're a mic drop with no mic.",
    "You're a warm soda on a hot day.",
    "You're a loading bar stuck at 99%.",
    "You're a group chat on mute.",
    "You're the reason autocorrect gives up.",
    "You're a sock with no pair.",
    "You're a spoiler in a bad movie.",
    "You're a \"maybe\" in a world of \"yes.\"",
    "You're a punchline without the setup.",
    "You're the dull side of a butter knife.",
    "You're a pop-up ad with no close button.",
    "You're a playlist with no bangers.",
    "You're a flashlight with dying batteries.",
    "You're a failed captcha.",
    "You're a sneeze that never comes.",
    "You're a plot twist no one noticed.",
    "You're a trophy with no competition.",
    "You're a selfie without the filter.",
    "You're a book with missing pages.",
    "You're a remix that ruined the original.",
    "You're a bridge to nowhere.",
    "You're a \"k\" in a sea of messages.",
    "You're a keyboard missing the spacebar.",
    "You're a knock-knock joke with no door.",
    "You're a pizza with no toppings.",
    "You're a calendar with no weekends.",
    "You're a donut with no hole.",
    "You're an elevator stuck between floors.",
    "You're a battery with no charge.",
    "You're a prologue with no story.",
    "You're a trailer that spoiled everything.",
    "You're a whisper in a thunderstorm.",
    "You're a firework that won't spark.",
    "You're a chair with one leg.",
    "You're a jigsaw missing the corner piece.",
    "You're a comet that never arrives.",
    "You're a stopwatch with no time.",
    "You're a checkbox with no label.",
    "You're a riddle with no answer.",
    "You're the \"skip\" button that doesn't work.",
    "You're a cup of decaf in a rush.",
    "You're a storm with no rain.",
    "You're a movie with no plot.",
    "You're a lantern with no light.",
    "You're a banter with no bite.",
    "You're a trophy for participation.",
    "You're an alarm that never rings.",
    "You're a lullaby in a mosh pit.",
    "You're a snowman in summer.",
    "You're a bookmark in an empty book.",
    "You're a dial without a number.",
    "You're a candle with no wick.",
    "You're a puzzle made of mashed potatoes.",
    "You're a stopwatch in a slow-motion scene.",
    "You're a paintbrush without paint.",
    "You're a compass that points to \"meh.\"",
    "You're an echo in a void.",
    "You're a snack that's all crumbs.",
    "You're a DJ with no drops.",
    "You're a montage without music.",
    "You're a high five with no hand.",
    "You're a fireworks show in broad daylight.",
    "You're a snowball in a volcano.",
    "You're a riddle with a typo.",
    "You're a mirror with no reflection.",
    "You're a joke that needs subtitles.",
    "You're a sunset behind clouds.",
    "You're a ladder to nowhere.",
    "You're a map with no legend.",
    "You're a compass pointing to \"nope.\"",
    "You're a ping with no pong.",
    "You're a battery that only shows 1%.",
    "You're a recipe with missing ingredients.",
    "You're a book with only the index.",
    "You're a record with no music.",
    "You're a helmet without a bike.",
    "You're a tent without poles.",
    "You're a race with no finish line.",
    "You're a sandwich with no filling.",
    "You're a ticket to nowhere.",
    "You're a parade with no floats.",
    "You're a lighthouse with no light.",
    "You're a comedy without timing.",
    "You're a dance with no rhythm.",
    "You're a treasure map that leads to socks.",
    "You're a camera with no lens.",
    "You're a puzzle with extra pieces.",
    "You're a marathon with no training.",
    "You're a nap in a hurricane.",
    "You're a rocket with no fuel.",
    "You're a scoreboard with no points.",
    "You're a cheer with no crowd.",
    "You're a highlight reel of bloopers.",
    "You're a script with no dialogue.",
    "You're a painter who uses invisible ink.",
    "You're a flashlight in the sun.",
    "You're a raincoat in the desert.",
    "You're a handshake with no fingers.",
    "You're a GPS in airplane mode.",
    "You're a toaster with no bread.",
    "You're a pillow with no fluff.",
    "You're a smile with no teeth.",
    "You're a marathon in flip-flops.",
    "You're a drumline with no beat.",
    "You're a zip file with no data.",
    "You're a server with no uptime.",
    "You're a mod with no permissions.",
    "You're a headphone with one side.",
    "You're a code block with syntax errors.",
    "You're a quest with no reward.",
    "You're a raid boss with no loot.",
    "You're a potion with no effects.",
    "You're a level-up with no stats.",
    "You're a skill tree with no skills.",
    "You're a crit with no damage.",
    "You're a mount with no speed.",
    "You're a guild with no members.",
    "You're a leaderboard with no names.",
    "You're a lobby with no players.",
    "You're a respawn with no checkpoint.",
    "You're a glitch with no fix.",
    "You're a loot box with no loot.",
    "You're a perk with no perks.",
    "You're a daily quest with no reward.",
    "You're a dungeon with no exits.",
    "You're a quest marker on the wrong map.",
    "You're a leaderboard with negative points.",
    "You're a rarity that's just common.",
    "You're an epic fail with rare vibes.",
    "You're a boss fight with no boss.",
    "You're a team chat with no team.",
    "You're a ping with 999ms.",
    "You're a battle pass with no tiers.",
    "You're a sprint with no finish.",
    "You're a patch that added bugs.",
    "You're a debug log in a love letter.",
    "You're a settings menu with no options.",
    "You're a raid with no strategy.",
    "You're a max level with min effort.",
    "You're a loot drop of disappointment.",
    "You're an upgrade that downgraded.",
    "You're a buff that feels like a nerf.",
    "You're a nerf disguised as a buff.",
    "You're a healer who needs healing.",
    "You're a tank with no armor.",
    "You're a DPS with no damage.",
    "You're a support with no support.",
    "You're a sniper with no scope.",
    "You're a runner with no stamina.",
    "You're a mage with no mana.",
    "You're a rogue with no stealth.",
    "You're a bard with no song.",
    "You're a warrior with no sword.",
    "You're a wizard with no spells.",
    "You're a potion that's just water.",
    "You're a scroll with no text.",
    "You're a shield made of paper.",
    "You're a sword made of rubber.",
    "You're a bow with no string.",
    "You're a spell with no effect.",
    "You're a trap that doesn't trigger.",
    "You're a treasure chest with no treasure.",
    "You're a key with no lock.",
    "You're a lock with no key.",
    "You're a map that lies.",
    "You're a quest giver with no quest.",
    "You're a quest with no XP.",
    "You're a campfire with no warmth.",
    "You're a tavern with no ale.",
    "You're a dragon with no fire.",
    "You're a phoenix that never rises.",
    "You're a storm with no thunder.",
    "You're a legend nobody heard.",
    "You're a hero with no story.",
    "You're a villain with no plan.",
    "You're a sidekick with no hero.",
    "You're a cliffhanger that falls flat.",
    "You're a reboot that nobody watched.",
    "You're a sequel with no original.",
    "You're a crossover no one asked for.",
    "You're a twist that's just tangled.",
    "You're a finale with no climax.",
    "You're a teaser with no release.",
    "You're a leak with no content.",
    "You're a spoiler for a boring plot.",
    "You're a recap with no new info.",
    "You're a binge with no fun.",
    "You're a marathon of commercials.",
    "You're a highlight reel of lowlights.",
    "You're a \"soon\" that never arrives.",
    "You're a feature stuck in beta.",
    "You're a keyboard warrior with no Wi-Fi.",
    "You're a meme from last year.",
    "You're a screenshot with no context.",
    "You're a chat bubble with no text.",
    "You're a status set to \"busy.\"",
    "You're a notification with no content.",
    "You're a pin without a board.",
    "You're a thread with no replies.",
    "You're a sticker with no stick.",
    "You're an emoji that nobody uses.",
    "You're a reaction with no message.",
    "You're a modmail with no mod.",
    "You're a server with no boosts.",
    "You're a ping that's always @everyone.",
    "You're a loudspeaker with no message.",
    "You're a voice channel with no voice.",
    "You're a DM that never gets opened.",
    "You're a report with no evidence.",
    "You're a cooldown with no ability.",
    "You're a queue with no game.",
    "You're a lobby with no match.",
    "You're a lost packet.",
    "You're a dropped frame.",
    "You're a ping spike.",
    "You're a laggy day in a fast world.",
    "You're a buffer wheel in human form.",
    "You're a loading screen tip nobody reads.",
    "You're a side note in your own story.",
    "You're a \"last seen\" in real life.",
    "You're a ghost message.",
    "You're a reply that says \"lol\" only.",
    "You're a joke with no punch.",
    "You're a pun without the fun.",
    "You're a summary of nothing.",
    "You're a blank page.",
    "You're a highlight that dims.",
    "You're a spark that fizzles.",
    "You're a flicker in a blackout.",
    "You're a vibe check that failed.",
    "You're a hero who skipped the tutorial.",
    "You're a legend in your own group chat.",
    "You're a meme in the worst way.",
    "You're a plot hole with legs.",
    "You're a cliff note to a short story.",
    "You're a chapter that got deleted.",
    "You're a tune that never lands.",
    "You're a chorus with no hook.",
    "You're a beat with no drop.",
    "You're a rapper with no bars.",
    "You're a singer with no chorus.",
    "You're a mixtape of static.",
    "You're a playlist full of ads.",
    "You're a radio that only plays dead air.",
    "You're a ringtone on silent.",
    "You're a speaker with no volume.",
    "You're a silent alarm.",
    "You're a group project with no effort.",
    "You're the Wi-Fi password nobody remembers.",
    "You're a password reset email.",
    "You're a captcha that fails.",
    "You're a two-factor code that expired.",
    "You're a download stuck at 0%.",
    "You're a pop quiz with no answer key.",
    "You're a sticky note that fell off.",
    "You're a meeting that should've been an email.",
    "You're a reply-all in a disaster.",
    "You're a voicemail nobody checks.",
    "You're an agenda with no agenda.",
    "You're a calendar invite to nowhere.",
    "You're a \"reply later\" that never comes.",
    "You're a draft with no send.",
    "You're a screen protector with bubbles.",
    "You're a screenshot of a black screen.",
    "You're a selfie with the lens cap on.",
    "You're a timer that never starts.",
    "You're a bell that never rings.",
    "You're a doorbell with no door.",
    "You're a hallway with no doors.",
    "You're a keychain with no keys.",
    "You're a treasure with no map.",
    "You're a quiz with no questions.",
    "You're a playlist skip in human form.",
    "You're a charging cable that only works at one angle.",
    "You're the \"are you still watching?\" pop-up.",
    "You're a rainy day with no puddles.",
    "You're a rainbow in black and white.",
    "You're the human version of \"maybe later.\"",
    "You're a notification for low storage.",
    "You're a software update at 2 AM.",
    "You're a reboot without the fix.",
    "You're a recycle bin full of mistakes.",
    "You're a broken link.",
    "You're a QR code that leads nowhere.",
    "You're the last slice no one wants.",
    "You're a party with no music.",
    "You're a cake with no frosting.",
    "You're a candle that got snuffed.",
    "You're a flashlight that's always dim.",
    "You're the \"free trial\" that ends early.",
    "You're the fine print nobody reads.",
    "You're a warning label with no hazard.",
    "You're a map that says \"You are lost.\"",
    "You're a signpost pointing to \"shrug.\"",
    "You're a GPS that says \"good luck.\"",
    "You're a trail with no end.",
    "You're a crossword with no clues.",
    "You're a puzzle without a picture.",
    "You're a board game with missing pieces.",
    "You're a dice roll that always hits 1.",
    "You're a deck of cards missing aces.",
    "You're a trophy for last place.",
    "You're a selfie stick with no phone.",
    "You're a live stream with no viewers.",
    "You're a video with no audio.",
    "You're a podcast that never starts.",
    "You're a mixtape with only the intro.",
    "You're a finale that never airs.",
    "You're a sequel to a forgotten movie.",
    "You're an update that fixed nothing."
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
        embed = discord.Embed(
            title=f"/{cmd['name']}",
            description=cmd["desc"],
            color=discord.Color.green()
        )
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

    while user["xp"] >= xp_needed(user["level"]):
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
        await send_response(interaction, "⏳ You already claimed your daily. Come back later!", ephemeral=True)
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
    await send_response(interaction, result)

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
    await send_response(interaction, f"💰 {member.display_name} has {econ_user['coins']} coins.")

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
    save_json(ECONOMY_FILE, economy)
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

@tree.command(name="roast", description="Roast someone creatively")
async def roast(interaction: discord.Interaction, member: discord.Member):
    if member.bot:
        await interaction.response.send_message("🤖 Roasting bots is too easy.", ephemeral=True)
        return
    if member.id == interaction.user.id:
        await interaction.response.send_message("😅 Self-roast? Bold move.", ephemeral=True)
        return
    roast_line = random.choice(ROAST_LINES)
    embed = discord.Embed(
        description=f"{member.mention} {roast_line}",
        color=discord.Color.orange()
    )
    embed.set_image(url=LAUGH_IMAGE_URL)
    await interaction.response.send_message(embed=embed)

@tree.command(name="help", description="Show the command center")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(embed=help_embed(), view=HelpView(), ephemeral=True)

@bot.command(name="help")
async def help_prefix(ctx: commands.Context):
    await ctx.send(embed=help_embed(), view=HelpView())

# ================== RUN ==================
bot.run(os.getenv("DISCORD_TOKEN"))
