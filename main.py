import io
import asyncio
import logging
import random
import os
import threading
import re
import time
from datetime import datetime, timedelta
import pytz
from flask import Flask
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne, ReturnDocument
from html import escape as escape_html
from telethon import TelegramClient, events, types, Button, errors

# --- Telethon Spec Imports ---
from telethon.tl.functions.channels import GetAdminLogRequest, GetParticipantsRequest
from telethon.tl.types import (
    ChannelParticipantAdmin, 
    ChannelParticipantCreator, 
    ChannelParticipantsAdmins,
    ChatAdminRights,
    ChannelAdminLogEventsFilter
)

# ==========================================
# 🌐 DNS FIX FOR MONGODB
# ==========================================
try:
    import dns.resolver
    dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
    dns.resolver.default_resolver.nameservers = ['8.8.8.8', '1.1.1.1']
except: pass

# ==========================================
# 🌐 FLASK KEEP-ALIVE
# ==========================================
app = Flask('')
@app.route('/')
def home(): return "BoD Sovereign System Plus Engine is Active!"

def run_flask(): 
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)

logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.ERROR)

# ==========================================
# ⚙️ CONFIGURATION & TOKENS
# ==========================================
OWNER_ID = 6015356597
OWNER_USERNAME = "Hello_Im_DexterMorgan"
MONGO_URI = "mongodb+srv://khantphyoemin537_db_user:9VRKiaeZkz7rJdpz@cluster0.w6tgi8j.mongodb.net/?appName=Cluster0&tlsAllowInvalidCertificates=true"
APP_ID = 35766004
APP_HASH = 'd15b4226b81724722279bae6af69e22d'
MAIN_BOT_TOKEN = "8575371720:AAEWWV42CGrwooM_joiJXdo2iEw2_7atyXU"

SPECIFIC_GROUP = -1003580630981 
SPECIFIC_CONTROL_GROUP = -1003580630981
STORAGE_CHANNEL = -1003580630981
TZ = pytz.timezone('Asia/Yangon')

# ==========================================
# 🗄️ DATABASE SETUP (MOTOR ASYNC)
# ==========================================
client_mongo = AsyncIOMotorClient(MONGO_URI)
db = client_mongo["telegram_bot"]

custom_filters_col = db["custom_filters"] 
filters_col = db["filters"]               
allow_col = db["allowed_users"]
groups_col = db["active_groups"]
talk_col = db["random_talk"]
talker_col = db["talker"]
welcome_col = db["custom_welcome"] 
ans_col = db["chatbot_answers"]
morgan_col = db["morgan_talk"] 
rank_col = db["rank_col"]
system_col = db["system_col"]
reply_save_col = db["reply_save_col"]

# 📊 TRACKING & GAME SYSTEMS COLLECTIONS
users_col = db["tracked_users"] 
muted_registry_col = db["muted_registry"]
characters_col = db["game_characters"]
user_game_profiles_col = db["user_game_profiles"]
group_spawn_state_col = db["group_spawn_state"]

# Indexing to maintain ultra high-speed lookups
users_col.create_index("user_id", unique=True)
user_game_profiles_col.create_index("user_id", unique=True)
characters_col.create_index("name", unique=True)

# ==========================================
# 🤖 CLIENT SETUP (SINGLE BOT)
# ==========================================
bot1 = TelegramClient('bot_main_session', APP_ID, APP_HASH)
bot_ids = []
bot_names = []

# ==========================================
# 📊 STATE VARIABLES & SPEED CACHE
# ==========================================
sticker_spam_data = {}
char_spam_data = {}
admin_cache = {}          
active_rank_messages = {} 
bot_bully_tasks = {}      
shoot_tasks = {}          
tracking_targets = {} 
dark_passenger_targets = {}
learning_status = {}      
talking_status = {}       
message_counts = {}       
GLOBAL_TALK = False 
TRAINING_ENABLED_MORGAN = False      
group_msg_counters = {}
GLOBAL_PREMODE_THRESHOLD = None  
chat_counters = {}               
IS_REPLY_ACTIVE = False              
REPLY_INTERVAL = 4                   
GLOBAL_TALK_INTERVAL = 6            
reply_msg_counters = {}              
active_card_games = {}
# 💎 PREMIUM MATHEMATICAL BOLD SERIF FONT CONVERTER
def f(text):
    normal = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
    bold = "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣0123456789"
    trans = str.maketrans(normal, bold)
    return str(text).translate(trans)

# ==========================================
# 🛠️ ADVANCED PRODUCTION LOGICS & BUFFERS
# ==========================================
USER_METRICS_BUFFER = []
BUFFER_LOCK = asyncio.Lock()
user_cooldowns = {}

def bq(text): return f"<blockquote><b>{text}</b></blockquote>"

def owner_tag():
    return f"<a href='https://t.me/{OWNER_USERNAME}'>@{OWNER_USERNAME}</a>"

# 🚀 ADVANCED SYSTEM LOGIC 1: DB BULK WRITE BUFFER
def track_user_metrics(user_id, username, first_name):
    if not user_id or user_id in bot_ids: return
    
    async def _async_buffer():
        global USER_METRICS_BUFFER
        async with BUFFER_LOCK:
            USER_METRICS_BUFFER.append(
                UpdateOne(
                    {"user_id": user_id},
                    {"$set": {
                        "username": username or "None",
                        "first_name": first_name or "User",
                        "last_active": datetime.now(TZ)
                    }},
                    upsert=True
                )
            )
            if len(USER_METRICS_BUFFER) >= 100:
                try:
                    await users_col.bulk_write(USER_METRICS_BUFFER, ordered=False)
                    USER_METRICS_BUFFER.clear()
                except Exception as e:
                    await report_system_error("Metrics Bulk Write Buffer", e)
    asyncio.create_task(_async_buffer())

async def periodic_buffer_flusher():
    global USER_METRICS_BUFFER
    while True:
        await asyncio.sleep(30)
        if USER_METRICS_BUFFER:
            async with BUFFER_LOCK:
                try:
                    await users_col.bulk_write(USER_METRICS_BUFFER, ordered=False)
                    USER_METRICS_BUFFER.clear()
                except Exception as e:
                    await report_system_error("Periodic Buffer Flusher", e)

# 🚀 ADVANCED SYSTEM LOGIC 2: COMMAND COOLDOWN RATE-LIMITER
async def is_on_cooldown(user_id, command_name, cooldown_seconds=3):
    if user_id == OWNER_ID: return False, 0
    now = time.time()
    cache_key = (user_id, command_name)
    if cache_key in user_cooldowns:
        elapsed = now - user_cooldowns[cache_key]
        if elapsed < cooldown_seconds:
            return True, int(cooldown_seconds - elapsed)
    user_cooldowns[cache_key] = now
    return False, 0

# 🚀 ADVANCED SYSTEM LOGIC 3: CENTRALIZED ERROR NOTIFICATION TO OWNER DM
async def report_system_error(location, error_msg):
    try:
        alert_text = (
            f"🚨 <b>CRITICAL SYSTEM ERROR REPORT</b>\n"
            f"🛸 ───────────────────\n"
            f"📍 <b>Location:</b> <code>{escape_html(location)}</code>\n"
            f"❌ <b>Error:</b> <code>{escape_html(str(error_msg))}</code>\n"
            f"⏰ <b>Time:</b> <code>{datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')}</code>"
        )
        await bot1.send_message(OWNER_ID, bq(alert_text), parse_mode='html')
    except Exception: pass

# 🚀 ADVANCED SYSTEM LOGIC 4: SMART AUTO-MUTE EXPIRY REGISTRY CHECKER
async def register_temporary_mute(chat_id, user_id, duration_minutes=5):
    unmute_time = datetime.now(TZ) + timedelta(minutes=duration_minutes)
    await muted_registry_col.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$set": {"unmute_time": unmute_time}},
        upsert=True
    )

async def smart_auto_unmute_worker():
    while True:
        try:
            now = datetime.now(TZ)
            cursor = muted_registry_col.find({"unmute_time": {"$lte": now}})
            async for doc in cursor:
                chat_id = doc["chat_id"]
                user_id = doc["user_id"]
                try:
                    await bot1.edit_permissions(chat_id, user_id, send_messages=True)
                    await bot1.send_message(chat_id, bq(f"🔊 <b>Auto-Unmute System:</b> User ID <code>{user_id}</code> သတ်မှတ်ချိန်ပြည့်မြောက်သဖြင့် အလိုအလျောက် စကားပြောခွင့် ပြန်လည်ရရှိပါပြီ။"), parse_mode='html')
                except Exception: pass
                await muted_registry_col.delete_one({"_id": doc["_id"]})
        except Exception as e:
            await report_system_error("Auto Unmute Worker Loop", e)
        await asyncio.sleep(10)

# ==========================================
# 🎮 GAME CONFIGURATION & ENGINE (MAIN 60)
# ==========================================
async def ensure_game_profile(user_id, first_name):
    profile = await user_game_profiles_col.find_one({"user_id": user_id})
    if not profile:
        profile = {
            "user_id": user_id,
            "first_name": first_name,
            "coins": 5000, 
            "caught_cards": []
        }
        await user_game_profiles_col.insert_one(profile)
    return profile

# ==========================================
# 🌤️ MYANMAR WEATHER DASHBOARD DATA ENGINE
# ==========================================
WEATHER_REGIONS_DATA = {
    "mdy": {"name": "မန္တလေး တိုင်းဒေသကြီး", "temp": "၃၈°C", "condition": "☀️ နေသာပြီး အလွန်ပူပြင်းသည်", "humidity": "၄2%", "wind": "၁၂ km/h"},
    "ygn": {"name": "ရန်ကုန် တိုင်းဒေသကြီး", "temp": "၃၂°C", "condition": "🌧️ နေရာကွက်ကျား မိုးရွာနိုင်သည်", "humidity": "၇၈%", "wind": "၁၅ km/h"},
    "npw": {"name": "နေပြည်တော် ကောင်စီနယ်မြေ", "temp": "၃၆°C", "condition": "⛅ တိမ်အသင့်အတင့် ဖြစ်ထွန်းသည်", "humidity": "၅၀%", "wind": "၁၀ km/h"},
    "sgn": {"name": "စစ်ကိုင်း တိုင်းဒေသကြီး", "temp": "၃၇°C", "condition": "☀️ နေသာပြီး ရာသီဥတု ပူပြင်းသည်", "humidity": "၄၅%", "wind": "၉ km/h"},
    "bgo": {"name": "ပဲခူး တိုင်းဒေသကြီး", "temp": "၃၃°C", "condition": "⛅ တိမ်အနည်းငယ် ဖြစ်ထွန်းသည်", "humidity": "၆၅%", "wind": "၁၁ km/h"},
    "mgy": {"name": "မကွေး တိုင်းဒေသကြီး", "temp": "၃၉°C", "condition": "☀️ နေသာပြီး အပူရှိန် အလွန်ပြင်းထန်သည်", "humidity": "၃၈%", "wind": "၁၄ km/h"},
    "ayd": {"name": "ဧရာဝတီ တိုင်းဒေသကြီး", "temp": "၃၁°C", "condition": "🌧️ မိုးသက်လေပြင်း ကျရောက်နိုင်သည်", "humidity": "၈၂%", "wind": "၁၈ km/h"},
    "tny": {"name": "တနင်္သာရီ တိုင်းဒေသကြီး", "temp": "၃၀°C", "condition": "🌧️ မိုးအသင့်အတင့် ရွာသွန်းနိုင်သည်", "humidity": "၈၅%", "wind": "၂၀ km/h"},
    "kcn": {"name": "ကချင် ပြည်နယ်", "temp": "၂၆°C", "condition": "🌫️ မြူဆိုင်းပြီး ရာသီဥတု အေးမြသည်", "humidity": "၇၀%", "wind": "၆ km/h"},
    "kyh": {"name": "ကယား ပြည်နယ်", "temp": "၂၉°C", "condition": "⛅ တိမ်အသင့်အတင့် ဖြစ်ထွန်းသည်", "humidity": "၆၀%", "wind": "၈ km/h"},
    "kyn": {"name": "ကရင် ပြည်နယ်", "temp": "၃၁°C", "condition": "🌧️ နေရာကွက်ကျား မိုးထူထပ်နိုင်သည်", "humidity": "၇၅%", "wind": "၁၃ km/h"},
    "chn": {"name": "ချင်း ပြည်နယ်", "temp": "၂၂°C", "condition": "❄️ ရာသီဥတု အလွန်အေးမြပြီး တိမ်ထူထပ်သည်", "humidity": "၅၅%", "wind": "၇ km/h"},
    "mon": {"name": "မွန် ပြည်နယ်", "temp": "၃၁°C", "condition": "🌧️ မိုးရွာသွန်းရန် ရာခိုင်နှုန်း များသည်", "humidity": "၈0%", "wind": "၁၆ km/h"},
    "shn": {"name": "ရှမ်း ပြည်နယ်", "temp": "၂၅°C", "condition": "🌫️ တောင်ပေါ်ဒေသများ မြူပိတ်ပြီး အေးမြသည်", "humidity": "၆၂%", "wind": "၈ km/h"}
}

def generate_weather_text(region_id):
    data = WEATHER_REGIONS_DATA.get(region_id)
    if not data: return "အချက်အလက် မရှိပါ။"
    return (
        f"🌤️ <b><u>မိုးလေဝသနှင့် ရာသီဥတု အစီရင်ခံစာ</u></b>\n"
        f"📍 <b>တိုင်းဒေသကြီး/ပြည်နယ်:</b> <code>{data['name']}</code>\n"
        f"🌡️ <b>လက်ရှိအပူချိန်:</b> <code>{data['temp']}</code>\n"
        f"☁️ <b>မိုးလေဝသ အခြေအနေ:</b> <code>{data['condition']}</code>\n"
        f"💧 <b>လေထုစိုထိုင်းဆ:</b> <code>{data['humidity']}</code>\n"
        f"💨 <b>လေတိုက်နှုန်း:</b> <code>{data['wind']}</code>\n"
        f"⏰ <b>နောက်ဆုံး Update:</b> <code>ယနေ့ မနက် ၀၆:၀၀ နာရီ</code>"
    )

async def weather_daily_cron_loop():
    while True:
        try:
            now = datetime.now(TZ)
            if now.hour == 6 and now.minute == 0:
                summary_text = (
                    f"☀️ <b>မြန်မာနိုင်ငံလုံးဆိုင်ရာ နေ့စဉ် မိုးလေဝသသတင်းစလွှာ</b>\n"
                    f"📅 <b>နေ့စွဲ:</b> <code>{now.strftime('%Y-%m-%d')}</code>\n\n"
                    f"🇲🇲 မိမိတို့ တိုင်းဒေသကြီးနှင့် ပြည်နယ်အလိုက် အသေးစိတ် ရာသီဥတုကို သိရှိရန် <code>/weather</code> ဟု ရိုက်နှိပ်၍ Dashboard တွင် စစ်ဆေးနိုင်ပါသည် Chief။"
                )
                active_groups = await groups_col.find().to_list(length=None)
                for g in active_groups:
                    try: 
                        await bot1.send_message(g["chat_id"], bq(summary_text), parse_mode='html')
                        await asyncio.sleep(0.2)
                    except Exception: pass
                
                tracked_users = await users_col.find().to_list(length=None)
                for u in tracked_users:
                    try:
                        await bot1.send_message(u["user_id"], bq(summary_text), parse_mode='html')
                        await asyncio.sleep(0.2)
                    except Exception: pass
                    
                await asyncio.sleep(60) 
        except Exception as e:
            await report_system_error("Weather Cron Broadcaster Loop", e)
        await asyncio.sleep(30)

# ==========================================
# 🛠️ ADMIN CAPABILITY CORE ENGINE
# ==========================================
async def is_allowed(user_id):
    if user_id == OWNER_ID: return True
    user = await allow_col.find_one({"user_id": user_id})
    return user is not None

async def check_admin(chat_id, user_id):
    if user_id == OWNER_ID: return True
    now = time.time()
    if chat_id in admin_cache and now < admin_cache[chat_id]["expiry"]:
        return user_id in admin_cache[chat_id]["ids"]
    await update_admin_cache(bot1, chat_id)
    if chat_id in admin_cache:
        return user_id in admin_cache[chat_id]["ids"]
    return False

async def check_ban_rights(chat_id, user_id):
    if user_id == OWNER_ID: return True
    try:
        permissions = await bot1.get_permissions(chat_id, user_id)
        return permissions.is_admin and permissions.ban_users
    except: return False

async def update_admin_cache(client, chat_id):
    try:
        admins = await client(GetParticipantsRequest(
            channel=chat_id, filter=ChannelParticipantsAdmins(),
            offset=0, limit=200, hash=0
        ))
        admin_ids = {p.user_id for p in admins.participants}
        admin_cache[chat_id] = {"ids": admin_ids, "expiry": time.time() + 300}
        return admin_ids
    except Exception as e:
        print(f"Error updating admin cache for {chat_id}: {e}")
        return set()

# ==========================================
# 🧠 SCHEMA-AGNOSTIC SMART REPLY SEARCH ENGINE
# ==========================================
async def fetch_optimized_smart_reply(user_text):
    reply_text = None
    user_text_clean = user_text.strip().lower()

    match_pipeline = [
        {"$match": {
            "$or": [
                {"$and": [{"$ifNull": ["$trigger", False]}, {"$gte": [{"$strLenCP": "$trigger"}, 2]}, {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$trigger"}]}, 0]}]},
                {"$and": [{"$ifNull": ["$key", False]}, {"$gte": [{"$strLenCP": "$key"}, 2]}, {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$key"}]}, 0]}]},
                {"$and": [{"$ifNull": ["$keyword", False]}, {"$gte": [{"$strLenCP": "$keyword"}, 2]}, {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$keyword"}]}, 0]}]}
            ]
        }},
        {"$addFields": {
            "weight": {
                "$max": [
                    {"$cond": [{"$and": [{"$ifNull": ["$trigger", False]}, {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$trigger"}]}, 0]}]}, {"$strLenCP": "$trigger"}, 0]},
                    {"$cond": [{"$and": [{"$ifNull": ["$key", False]}, {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$key"}]}, 0]}]}, {"$strLenCP": "$key"}, 0]},
                    {"$cond": [{"$and": [{"$ifNull": ["$keyword", False]}, {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$keyword"}]}, 0]}]}, {"$strLenCP": "$keyword"}, 0]}
                ]
            }
        }},
        {"$sort": {"weight": -1}},
        {"$limit": 5}
    ]

    try:
        cursor = reply_save_col.aggregate(match_pipeline)
        matched_docs = await cursor.to_list(length=5)
        
        if matched_docs:
            valid_choices = []
            max_weight = matched_docs[0]["weight"]
            best_docs = [d for d in matched_docs if d["weight"] == max_weight]
            
            for doc in best_docs:
                chosen = None
                if doc.get("responses") and isinstance(doc["responses"], list): chosen = random.choice(doc["responses"])
                elif doc.get("values") and isinstance(doc["values"], list): chosen = random.choice(doc["values"])
                elif doc.get("response"): chosen = doc["response"]
                elif doc.get("value"): chosen = doc["value"]
                elif doc.get("text"): chosen = doc["text"]

                if chosen and not ('@' in str(chosen) or 't.me/' in str(chosen)): valid_choices.append(str(chosen))
            
            if valid_choices: reply_text = random.choice(valid_choices)
    except Exception as e:
        print(f"Smart Reply DB Error: {e}")

    if not reply_text:
        try:
            fallback_cursor = talk_col.aggregate([{"$sample": {"size": 1}}])
            fallback_docs = await fallback_cursor.to_list(length=1)
            if fallback_docs and fallback_docs[0].get("text"):
                chosen_fb = fallback_docs[0]["text"]
                if not ('@' in chosen_fb or 't.me/' in chosen_fb): reply_text = chosen_fb
        except Exception: pass

    return reply_text

# ====================================================================================
# 🛡️ SYSTEM COMMANDS & NAVIGATION HANDLERS (START, HELP, GAME)
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/start$'))
async def system_start_router(event):
    is_cd, rem = await is_on_cooldown(event.sender_id, "start", 2)
    if is_cd: return
    
    sender = await event.get_sender()
    track_user_metrics(event.sender_id, getattr(sender, 'username', None), getattr(sender, 'first_name', 'User'))
    
    bot_me = await bot1.get_me()
    welcome_msg = (
        f"🌌 <b>𝑩𝑶𝑫 𝑺𝒐𝒗𝒆𝒓𝒆𝒊𝒈𝒏 𝑺𝒚𝒔𝒕𝒆𝒎 𝑷𝒍𝒖𝒔 𝑬𝒏𝒈𝒊𝒏𝒆</b>\n"
        f"🛸 ───────────────────\n"
        f"🤖 ကျွန်ုပ်သည် Telegram Groups များကို အလိုအလျောက် အဆင့်မြင့်ဆုံး ထိန်းချုပ်ပေးနိုင်သော စနစ်ဖြစ်ပြီး "
        f"ပျော်ရွှင်စရာ Anime Card Spawning Game စနစ်များပါ ပါဝင်ဖွဲ့စည်းထားသော Production-level Bot ဖြစ်ပါသည်။\n\n"
        f"💡 အောက်ပါ Inline Buttons များကို အသုံးပြု၍ လုပ်ငန်းဆောင်တာများနှင့် ကစားနည်းလမ်းညွှန်များကို အလွယ်တကူ လေ့လာနိုင်ပါသည် Chief။"
    )
    buttons = [
        [Button.inline("⚙️ Operational Commands", data="nav_help_main"), Button.inline("🎮 Catching Game Rules", data="nav_game_main")],
        [Button.url("🪐 Add Me To Your Group Chat 🪐", f"https://t.me/{bot_me.username}?startgroup=true")],
        [Button.url("👥 Support Brotherhood Community", "https://t.me/Comeback_BoD")]
    ]
    await event.respond(bq(welcome_msg), parse_mode='html', buttons=buttons)

@bot1.on(events.CallbackQuery())
async def system_callback_router(event):
    data = event.data.decode('utf-8')
    user_id = event.sender_id
    
    # 🌦️ WEATHER SELECTION SYSTEM INTERCEPTOR
    if data.startswith("w_"):
        region_code = data.split("_")[1]
        weather_report_txt = generate_weather_text(region_code)
        back_btn = [[Button.inline("🔙 Back to Weather Dashboard", data="nav_weather_dash")]]
        return await event.edit(bq(weather_report_txt), parse_mode='html', buttons=back_btn)
        
    if data == "nav_weather_dash":
        weather_msg = "🇲🇲 <b>မြန်မာနိုင်ငံ တိုင်းဒေသကြီးများနှင့် ပြည်နယ်များ၏ ရာသီဥတုကို စစ်ဆေးရန် ခလုတ်များကို နှိပ်ပါ-</b>"
        buttons = [
            [Button.inline("မန္တလေး", data="w_mdy"), Button.inline("ရန်ကုန်", data="w_ygn")],
            [Button.inline("နေပြည်တော်", data="w_npw"), Button.inline("စစ်ကိုင်း", data="w_sgn")],
            [Button.inline("ပဲခူး", data="w_bgo"), Button.inline("မကွေး", data="w_mgy")],
            [Button.inline("ဧရာဝတီ", data="w_ayd"), Button.inline("တနင်္သာရီ", data="w_tny")],
            [Button.inline("ကချင်", data="w_kcn"), Button.inline("ကယား", data="w_kyh")],
            [Button.inline("ကရင်", data="w_kyn"), Button.inline("ချင်း", data="w_chn")],
            [Button.inline("မွန်", data="w_mon"), Button.inline("ရှမ်း", data="w_shn")],
            [Button.inline("🔙 Return to Main", data="nav_back_home")]
        ]
        return await event.edit(bq(weather_msg), parse_mode='html', buttons=buttons)

    # UI INLINE INTERACTION MANAGEMENT
    if data == "nav_back_home":
        bot_me = await bot1.get_me()
        welcome_msg = (
            f"🌌 <b>𝑩𝑶𝑫 𝑺𝒐𝒗𝒆𝒓𝒆𝒊𝒈𝒏 𝑺𝒚𝒔𝒕𝒆𝒎 𝑷𝒍𝒖𝒔 𝑬𝒏𝒈𝒊𝒏𝒆</b>\n"
            f"🛸 ───────────────────\n"
            f"🤖 ကျွန်ုပ်သည် Telegram Groups များကို အလိုအလျောက် အဆင့်မြင့်ဆုံး ထိန်းချုပ်ပေးနိုင်သော စနစ်ဖြစ်ပြီး "
            f"ပျော်ရွှင်စရာ Anime Card Spawning Game စနစ်များပါ ပါဝင်ဖွဲ့စည်းထားသော Production-level Bot ဖြစ်ပါသည်။"
        )
        buttons = [
            [Button.inline("⚙️ Operational Commands", data="nav_help_main"), Button.inline("🎮 Catching Game Rules", data="nav_game_main")],
            [Button.url("🪐 Add Me To Your Group Chat 🪐", f"https://t.me/{bot_me.username}?startgroup=true")],
            [Button.url("👥 Support Brotherhood Community", "https://t.me/Comeback_BoD")]
        ]
        return await event.edit(bq(welcome_msg), parse_mode='html', buttons=buttons)

    elif data == "nav_help_main":
        help_text = (
            f"⚙️ <b><u>Operational Moderation Terminal</u></b>\n\n"
            f"🛠️ <code>/id</code> - မိမိ သို့မဟုတ် ရည်ညွှန်းသူ၏ Profile ID Matrix အား ထုတ်ယူခြင်း။\n"
            f"🛠️ <code>/mute [Reply]</code> - စည်းကမ်းဖောက်ဖျက်သူအား စကားပြောခွင့် ကန့်သတ်ခြင်း။\n"
            f"🛠️ <code>/unmute [Reply]</code> - ကန့်သတ်ချက်များအား ပြန်လည်ရုပ်သိမ်းပေးခြင်း။\n"
            f"🛠️ <code>/ban [Reply]</code> - အဖွဲ့ဝင်အဖြစ်မှ ထာဝရထုတ်ပယ် (Exile) ပြုလုပ်ခြင်း။\n"
            f"🛠️ <code>/kick [Reply]</code> - လက်ရှိ Chat Sector မှ ချက်ချင်း ဖယ်ရှားခြင်း။\n"
            f"🛠️ <code>/adm [Text]</code> - လက်ရှိ Group အတွင်းရှိ ရုံးထိုင် အရာရှိ (Admins) အားလုံးကို Tag ခေါ်ယူခြင်း။\n"
            f"🛠️ <code>/calc [Expression]</code> - လျင်မြန်ဘေးကင်းသော သင်္ချာတွက်ချက်မှု Engine။\n"
            f"🛠️ <code>/weather</code> - မြန်မာတစ်နိုင်ငံလုံးဆိုင်ရာ ရာသီဥတု တိုင်းတာရေး Dashboard အား ခေါ်ယူခြင်း။"
        )
        return await event.edit(bq(help_text), parse_mode='html', buttons=[[Button.inline("🔙 Back Menu", data="nav_back_home")]])

    elif data == "nav_game_main":
        game_text = (
            f"🎮 <b><u>BoD Anime Catching Game Console</u></b>\n\n"
            f"⭐ <code>/hai</code> သို့မဟုတ် <code>/profile</code>\n"
            f"<blockquote><b>မိမိပိုင်ဆိုင်သော ငွေသားပမာဏ၊ စုဆောင်းမိထားသော ကတ်ထုပ်များနှင့် Level Stats များကို စစ်ဆေးကြည့်ရှုခြင်း။</b></blockquote>\n"
            f"⭐ <code>/catch [Character Name]</code>\n"
            f"<blockquote><b>ဂရုထဲတွင် စာစုဆောင်းမှု ပြည့်မြောက်၍ ပေါ်ထွက်လာသော Anime ကတ်ပြားအား အမြန်ဆုံး ဖမ်းယူသိမ်းဆည်းခြင်း။</b></blockquote>\n\n"
            f"⚠️ <b><u>ပြည်သူ့ဝန်ထမ်း အရာရှိကြီးများ အသုံးပြုရန် (Admin Utilities):</u></b>\n"
            f"⚙️ <code>/addchar [Name] | [Rarity] | [Media Link]</code> - စနစ်ထဲသို့ ကတ်အသစ် တည့်သွင်းခြင်း။\n"
            f"⚙️ <code>/fspawn</code> သို့မဟုတ် <code>/haii</code> - မက်ဆေ့ခ်ျရေတွက်မှုကို ကျော်ဖြတ်ပြီး ကတ်တစ်ခု ချက်ချင်း Spawn ထုတ်ခြင်း။\n"
            f"⚙️ <code>/haitime [Count]</code> - အလိုအလျောက် ကတ်ထွက်မည့် သတ်မှတ်စာစောင်ရေ ပြောင်းလဲခြင်း။\n"
            f"⚙️ <code>/cleanhai</code> - အချက်အလက်များ လျင်မြန်ပေါ့ပါးစေရန် Database ဇယားများအား အသစ်ပြန်လည် ရှင်းလင်းခြင်း။"
        )
        return await event.edit(bq(game_text), parse_mode='html', buttons=[[Button.inline("🔙 Back Menu", data="nav_back_home")]])

# COMMANDS INTERCEPTORS
@bot1.on(events.NewMessage(pattern=r'^/helpp$'))
async def direct_help_handler(event):
    is_cd, rem = await is_on_cooldown(event.sender_id, "helpp", 2)
    if is_cd: return
    help_text = (
        f"⚙️ <b><u>Operational Moderation Terminal</u></b>\n\n"
        f"🛠️ <code>/id</code> - Profile ID Matrix ထုတ်ယူခြင်း။\n"
        f"🛠️ <code>/mute</code> - စကားပြောခွင့် ကန့်သတ်ခြင်း။\n"
        f"🛠️ <code>/unmute</code> - ကန့်သတ်ချက် ရုပ်သိမ်းခြင်း။\n"
        f"🛠️ <code>/ban</code> - အဖွဲ့ဝင်အဖြစ်မှ ထာဝရထုတ်ပယ်ခြင်း။\n"
        f"🛠️ <code>/kick</code> - Chat Sector မှ ဖယ်ရှားခြင်း။\n"
        f"🛠️ <code>/adm</code> - Group Admins အားလုံးကို Tag ခေါ်ယူခြင်း။\n"
        f"🛠️ <code>/calc</code> - သင်္ချာတွက်ချက်မှု စနစ်။\n"
        f"🛠️ <code>/weather</code> - မိုးလေဝသ တိုင်းဒေသကြီးများ Dashboard။"
    )
    await event.respond(bq(help_text), parse_mode='html', buttons=[[Button.inline("⚙️ Navigation Home", data="nav_back_home")]])

@bot1.on(events.NewMessage(pattern=r'^/game$'))
async def direct_game_guide_handler(event):
    is_cd, rem = await is_on_cooldown(event.sender_id, "game", 2)
    if is_cd: return
    game_text = (
        f"🎮 <b><u>BoD Anime Catching Game Console</u></b>\n\n"
        f"⭐ <code>/hai</code> သို့မဟုတ် <code>/profile</code> - ကိုယ်ပိုင် Stats စစ်ဆေးခြင်း။\n"
        f"⭐ <code>/catch [Name]</code> - ပေါ်လာသော ကတ်ပြားအား ဖမ်းယူခြင်း။\n"
        f"⚙️ <code>/fspawn</code> - ကတ်တစ်ခု ချက်ချင်း Force Spawn ထုတ်ခြင်း။\n"
        f"⚙️ <code>/haitime [Count]</code> - Spawn စာစောင်ရေ ပြောင်းလဲခြင်း။"
    )
    await event.respond(bq(game_text), parse_mode='html', buttons=[[Button.inline("⚙️ Navigation Home", data="nav_back_home")]])

# ====================================================================================
# 🌤️ ADVANCED SYSTEM LOGIC 6: INTERACTIVE WEATHER DASHBOARD & COMMAND
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/weather$'))
async def weather_dashboard_command(event):
    is_cd, rem = await is_on_cooldown(event.sender_id, "weather", 3)
    if is_cd: return await event.reply(bq(f"⚠️ Flood Protection: {rem} စက္ကန့် စောင့်ဆိုင်းပေးပါ။"), parse_mode='html')
    
    weather_msg = "🇲🇲 <b>မြန်မာနိုင်ငံ တိုင်းဒေသကြီးများနှင့် ပြည်နယ်များ၏ ရာသီဥတုကို စစ်ဆေးရန် ခလုတ်များကို နှိပ်ပါ Chief-</b>"
    buttons = [
        [Button.inline("မန္တလေး", data="w_mdy"), Button.inline("ရန်ကုန်", data="w_ygn")],
        [Button.inline("နေပြည်တော်", data="w_npw"), Button.inline("စစ်ကိုင်း", data="w_sgn")],
        [Button.inline("ပဲခူး", data="w_bgo"), Button.inline("မကွေး", data="w_mgy")],
        [Button.inline("ဧရာဝတီ", data="w_ayd"), Button.inline("တနင်္သာရီ", data="w_tny")],
        [Button.inline("ကချင်", data="w_kcn"), Button.inline("ကယား", data="w_kyh")],
        [Button.inline("ကရင်", data="w_kyn"), Button.inline("ချင်း", data="w_chn")],
        [Button.inline("မွန်", data="w_mon"), Button.inline("ရှမ်း", data="w_shn")]
    ]
    await event.respond(bq(weather_msg), parse_mode='html', buttons=buttons)

# ====================================================================================
# 🔢 ADVANCED SYSTEM LOGIC 5: SECURE ARITHMETIC CALCULATOR
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/calc\s+(.*)'))
async def secure_calculator_handler(event):
    is_cd, rem = await is_on_cooldown(event.sender_id, "calc", 2)
    if is_cd: return await event.reply(bq(f"⚠️ Cooldown: {rem} စက္ကန့် စောင့်ပါ။"), parse_mode='html')
    
    raw_expression = event.pattern_match.group(1).strip()
    # Security Sandbox: Match only safe mathematical character arrays
    if not re.match(r'^[0-9\+\-\*\/\.\s\(\)]+$', raw_expression):
        return await event.reply(bq("❌ <b>လုံခြုံရေး သတိပေးချက်:</b> ခွင့်မပြုသော ကာရက်တာများ ပါဝင်နေပါသည်။ ဂဏန်းနှင့် သင်္ချာအော်ပရေတာများသာ အသုံးပြုပါ။"), parse_mode='html')
    
    try:
        calculated_result = eval(raw_expression, {"__builtins__": None}, {})
        response_msg = (
            f"🔢 <b><u>Mathematical Calculation Engine</u></b>\n\n"
            f"🧮 <b>တွက်ချက်မှုစနစ်:</b> <code>{raw_expression}</code>\n"
            f"✨ <b>ရရှိလာသော ရလဒ်:</b> <code>{calculated_result}</code>"
        )
        await event.reply(bq(response_msg), parse_mode='html')
    except Exception as e:
        await event.reply(bq(f"❌ သင်္ချာတွက်ချက်မှု ပုံစံ မှားယွင်းနေပါသည်- {escape_html(str(e))}"), parse_mode='html')

# ==========================================
# ⚙️ CHAT ACTIONS & WELCOME MATRIX
# ==========================================
@bot1.on(events.ChatAction)
async def welcome_goodbye(event):
    try:
        chat = await event.get_chat()
        bot_me = await bot1.get_me()
        bot_mention = f"<a href='tg://user?id={bot_me.id}'>{escape_html(bot_me.first_name)}</a>"
        safe_title = escape_html(chat.title)
        target_ids = event.user_ids or [event.user_id]

        if event.user_added or event.user_joined:
            if any(uid == bot_me.id for uid in target_ids if uid):
                await groups_col.update_one({"chat_id": chat.id}, {"$set": {"title": chat.title, "joined_at": datetime.now(TZ)}}, upsert=True)
                msg1 = f"ဟိတ် OWNER နဲ့ Admins တို့ မင်းတို့ရဲ့ ဒီ {safe_title} ထဲကို ထည့်သုံးပေးလို့ ကျေးဇူးတင်ပါတယ်! အသုံးလိုကောင်းလိုနိုင်တဲ့ command များယူထားမယ်ဆိုရင် {bot_mention} ရဲ့ Creator {owner_tag()} ရဲ့ Dm (သို့မဟုတ်) @Comeback_BoD ကိုလာရောက်ပါ!!!"
                await bot1.send_message(chat.id, bq(msg1), parse_mode='html')
                
                try: members = getattr(chat, 'participants_count', 'Unknown')
                except: members = "Unknown"
                msg2 = f"မင်္ဂလာပါ {safe_title}က \n{bot_mention}ထည့်သုံးထားပါသေးတယ်\n\nGroup Name - {safe_title}\nGroup ID - <code>{chat.id}</code>\nMembers အရေအတွက် - {members}\nBot Creator - {owner_tag()}"
                await bot1.send_message(SPECIFIC_GROUP, bq(msg2), parse_mode='html')
            else:
                custom_welcome = await welcome_col.find_one({"chat_id": chat.id})
                for uid in target_ids:
                    if uid and uid != bot_me.id:
                        try: u = await bot1.get_entity(uid)
                        except: continue
                        track_user_metrics(u.id, u.username, u.first_name) 
                        u_mention = f"<a href='tg://user?id={u.id}'>{escape_html(u.first_name)}</a>"
                        
                        if custom_welcome and custom_welcome.get("text"):
                            welcome_text = custom_welcome["text"].replace("{mention}", u_mention).replace("{group}", safe_title)
                        else:
                            welcome_text = (
                                f"ဟိုက် {u_mention}\n"
                                "╔═━━━❖━━━═╗\n"
                                f"{safe_title} ကနေ ကြိုဆိုလိုက်ပါတယ်\n"
                                "╚═━━━❖━━━═╝\n"
                                f"This bot is proudly developed and maintained by 𝑷𝑨𝑹𝑨𝑫𝑶𝑿 𝑭𝒂𝒎𝒊𝒍𝒚⌬𝑩𝑶𝑫.\n"
                            )
                        
                        media_file = custom_welcome.get("media") if custom_welcome else None
                        await bot1.send_message(
                            event.chat_id, bq(welcome_text), parse_mode='html', file=media_file,
                            buttons=[
                                [Button.url("Bot ဖြင့် Broadcasting အပ်ရန်", f"t.me/Hello_Im_DexterMorgan")],
                                [Button.url("ကျွန်ုပ်တို့Groupသို့ဝင်ရန်", "https://t.me/Comeback_BoD")]
                            ]
                        )
                        
        elif event.user_kicked or event.user_left:
            if event.user_id == bot_me.id:
                await groups_col.delete_one({"chat_id": chat.id})
            else:
                try:
                    u = await bot1.get_entity(event.user_id)
                    u_mention = f"<a href='tg://user?id={u.id}'>{escape_html(u.first_name)}</a>"
                    await bot1.send_message(event.chat_id, bq(f"ထွက်သွားလိုက်ပါသေးတယ်.. {u_mention} !!"), parse_mode='html')
                except: pass
    except Exception as e:
        await report_system_error("Welcome Goodbye Event Tracker", e)

# 💬 AUTOMATIC CHAT RESPONDER & DYNAMIC TRAFFIC INTERCEPTOR
@bot1.on(events.NewMessage(incoming=True))
async def chatbot_auto_responder(event):
    if event.sender_id:
        sender = await event.get_sender()
        if sender and not sender.bot:
            track_user_metrics(event.sender_id, getattr(sender, 'username', None), getattr(sender, 'first_name', None))

    if event.is_private or not event.text or event.text.startswith(('/', '.', 'Hey there','@')): return
    user_text = event.text.lower()
    cursor = ans_col.find()
    async for doc in cursor:
        keyphrase = doc.get("keyphrase")
        if keyphrase and keyphrase in user_text:
            responses = doc.get("responses", [])
            if responses:
                await event.reply(bq(random.choice(responses)), parse_mode='html')
                break

# ====================================================================================
# 📊 PRECISE REAL-TIME METRICS INTEGRATION DASHBOARD
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/stats$'))
async def system_analytics_matrix(event):
    if event.sender_id != OWNER_ID: return
    
    loading = await event.reply("<code>🌌 Core Processor Engine မှ အချက်အလက်များကို ထုတ်ယူနေပါသည်...</code>", parse_mode='html')
    try:
        total_tracked_users = await users_col.count_documents({})
        total_active_groups = await groups_col.count_documents({})
        
        day_ago = datetime.now(TZ) - timedelta(days=1)
        active_24h_users = await users_col.count_documents({"last_active": {"$gte": day_ago}})
        
        metrics_layout = (
            f"🌌 <b>𝙎𝙊𝙑𝙀𝙍𝙀𝙄𝙂🇳 𝘼𝙉𝘼𝙇𝙔𝙏𝙄𝘾𝙎 𝙈𝘼𝙏𝙍𝙄𝙦</b>\n"
            f"🛸 ───────────────────\n"
            f"👥 <b>Total Managed Users:</b> <code>{total_tracked_users} 👤</code>\n"
            f"🔥 <b>Active Users (24H):</b> <code>{active_24h_users} 🔥</code>\n"
            f"📍 <b>Sovereign Sectors (Groups):</b> <code>{total_active_groups} 🪐</code>\n"
            f"⚙️ <b>Engine Status:</b> <code>High-Speed Optimized (No Delay)</code>\n"
            f"🛸 ───────────────────\n"
            f"💡 <i>Telegram API ကို အသုံးမပြုဘဲ Internal Matrix မှ တိုက်ရိုက်တွက်ချက်ထားသဖြင့် ၁၀၀% တိကျပါသည်။</i>"
        )
        await loading.edit(bq(metrics_layout), parse_mode='html')
    except Exception as e:
        await loading.edit(bq(f"❌ Analytics Error: {e}"), parse_mode='html')

# ==========================================
# 🛡️ ANTISPAM MECHANISMS (STICKER & CHARACTER)
# ==========================================
@bot1.on(events.NewMessage)
async def sticker_spam_(event):
    if not event.sticker or event.is_private: return
    if event.sender_id in bot_ids: return

    sender_id = event.sender_id
    chat_id = event.chat_id
    now = datetime.now()

    if sender_id not in sticker_spam_data: 
        sticker_spam_data[sender_id] = {"times": [], "ids": []}
        
    sticker_spam_data[sender_id]["times"].append(now)
    sticker_spam_data[sender_id]["ids"].append(event.id)

    one_minute_ago = now - timedelta(seconds=60)
    valid_data = [(t, i) for t, i in zip(sticker_spam_data[sender_id]["times"], sticker_spam_data[sender_id]["ids"]) if t > one_minute_ago]
    sticker_spam_data[sender_id]["times"] = [x[0] for x in valid_data]
    sticker_spam_data[sender_id]["ids"] = [x[1] for x in valid_data]

    recent_times = sticker_spam_data[sender_id]["times"]
    recent_ids = sticker_spam_data[sender_id]["ids"]

    if len(recent_times) >= 6:
        try:
            is_admin = await check_admin(chat_id, sender_id)
            await bot1.delete_messages(chat_id, recent_ids)
            sender = await event.get_sender()
            mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name)}</a>"

            if is_admin:
                action_msg = f"⚠️ Admin {mention} က Sticker တွေ Spam နေလို့ ပို့ထားသမျှ အကုန်ဖျက်လိုက်ပါတယ်။"
            else:
                await bot1.edit_permissions(chat_id, sender_id, send_stickers=False)
                action_msg = f"{mention} ကို Sticker ပို့ခွင့် ပိတ်လိုက်ပါပြီ။\nအကြောင်းရင်း- Spam တဲ့အတွက် ဖြစ်ပါတယ်။"
            
            await event.respond(bq(action_msg), parse_mode='html')
            del sticker_spam_data[sender_id]
            return
        except Exception as e: print(f"Spam Filter Error: {e}")

    if len(recent_times) >= 3:
        time_diff = (recent_times[-1] - recent_times[-3]).total_seconds()
        if time_diff <= 1.0: 
            await event.delete()

@bot1.on(events.NewMessage)
async def character_spam_filter(event):
    if event.is_private or not event.text: return
    if event.sender_id in bot_ids: return

    text = event.text.strip()
    if len(text) > 3: return 

    sender_id = event.sender_id
    chat_id = event.chat_id
    now = datetime.now()

    if sender_id not in char_spam_data: 
        char_spam_data[sender_id] = {"times": [], "ids": []}
        
    char_spam_data[sender_id]["times"].append(now)
    char_spam_data[sender_id]["ids"].append(event.id)

    one_minute_ago = now - timedelta(seconds=60)
    valid_data = [(t, i) for t, i in zip(char_spam_data[sender_id]["times"], char_spam_data[sender_id]["ids"]) if t > one_minute_ago]
    char_spam_data[sender_id]["times"] = [x[0] for x in valid_data]
    char_spam_data[sender_id]["ids"] = [x[1] for x in valid_data]

    recent_times = char_spam_data[sender_id]["times"]
    recent_ids = char_spam_data[sender_id]["ids"]

    if len(recent_times) >= 6:
        try:
            is_admin = await check_admin(chat_id, sender_id)
            await bot1.delete_messages(chat_id, recent_ids) 
            sender = await event.get_sender()
            mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name)}</a>"

            if is_admin:
                action_msg = f"⚠️ Admin {mention}... သတိပေးထားတဲ့ကြားက စာတိုတွေ ထပ်စပမ်းနေလို့ ဆင်ခြင်ပေးဖို့ မေတ္တာရပ်ခံပါတယ်။"
            else:
                await register_temporary_mute(chat_id, sender_id, duration_minutes=5)
                await bot1.edit_permissions(chat_id, sender_id, until_date=datetime.now() + timedelta(minutes=5), send_messages=False)
                action_msg = f"🚫 {mention} ကို သတိပေးချက်ကို မလိုက်နာဘဲ စာတိုတွေ ဆက်တိုက် Spam တဲ့အတွက် ၅ မိနစ်ခန့် Mute လိုက်ပါပြီ (Auto-Expiry Ensured)။"
            
            await event.respond(bq(action_msg), parse_mode='html') 
            del char_spam_data[sender_id]
            return
        except Exception as e: print(f"Char Spam Mute Error: {e}")

    if len(recent_times) == 5:
        try:
            await bot1.delete_messages(chat_id, recent_ids) 
            sender = await event.get_sender()
            mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name)}</a>"
            
            warn_msg = f"⚠️ {mention} စာ Spam နေလို့ အကုန်ဖျက်လိုက်ပါပြီ။ နောက်တစ်ခါ ထပ်ပို့ရင် 5 မိနစ် Mute ခံရပါလိမ့်မယ်။"
            await event.respond(bq(warn_msg), parse_mode='html') 
        except Exception as e: print(f"Char Spam Warn Error: {e}")

@bot1.on(events.NewMessage(pattern=r'^[/.]f\s+(.*)'))
async def add_filter(event):
    if not await check_admin(event.chat_id, event.sender_id): return
    input_str = event.pattern_match.group(1).split(None, 1)
    keyword = input_str[0].lower().strip()
    reply = await event.get_reply_message()

    if reply:
        try:
            forwarded = await bot1.forward_messages(STORAGE_CHANNEL, reply)
            await custom_filters_col.update_one(
                {"keyword": keyword}, 
                {"$set": {"type": "storage_msg", "msg_id": forwarded.id, "chat_id": "global"}}, 
                upsert=True
            )
            await event.reply(bq(f"အိုကေ! '{keyword}' filter ကို Premium Emoji တွေအပါအဝင် Cloud စနစ်နဲ့ မှတ်လိုက်ပြီ ✅"), parse_mode='html')
        except Exception as e:
            await event.reply(bq(f"❌ Storage ထဲ လှမ်းသိမ်းရမှာ Error တက်သွားတယ်: {e}"), parse_mode='html')
    else:
        await event.reply(bq("⚠️ Filter မှတ်ဖို့အတွက် ပို့ချင်တဲ့စာ သို့မဟုတ် မီဒီယာကို Reply ပြန်ပြီးမှ သုံးပေးပါ ဘရို။"), parse_mode='html')
      
# ====================================================================================
# 🆔 IDENTITY MATRIX SYSTEM
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/id$'))
async def get_identity_matrix_handler(event):
    is_cd, rem = await is_on_cooldown(event.sender_id, "id", 2)
    if is_cd: return
    
    chat_id = event.chat_id
    is_private = event.is_private
    reply = await event.get_reply_message()
    
    if reply:
        target_id = reply.sender_id
        target_user = await reply.get_sender()
        user_type = "Target Profile"
        
        if target_user and getattr(target_user, 'username', None):
            mention = f"@{target_user.username}"
        else:
            first_name = getattr(target_user, 'first_name', None) or "User"
            mention = f"<a href='tg://user?id={target_id}'>{escape_html(first_name)}</a>"
    else:
        target_id = event.sender_id
        sender = await event.get_sender()
        user_type = "Your Profile"
        
        if sender and getattr(sender, 'username', None):
            mention = f"@{sender.username}"
        else:
            first_name = getattr(sender, 'first_name', None) or "User"
            mention = f"<a href='tg://user?id={target_id}'>{escape_html(first_name)}</a>"

    if not is_private:
        try:
            chat = await event.get_chat()
            group_title = escape_html(chat.title)
        except Exception: group_title = "Unknown Sector"
        group_section = f"📍 <b>Group:</b> {group_title}\n🌐 <b>Chat ID:</b> <code>{chat_id}</code>\n"
    else:
        group_section = f"📍 <b>Sector:</b> <code>Private Chat (No Group ID)</code>\n"

    matrix_text = (
        f"🌌 <b>𝙄𝘿 𝙈𝘼𝙏𝙍𝙄𝙦</b>\n"
        f"👤 <b>{user_type}:</b> {mention}\n"
        f"🆔 <b>User ID:</b> <code>{target_id}</code>\n\n"
        f"{group_section}"
    )
    try: await event.respond(bq(matrix_text), parse_mode='html')
    except Exception as e: print(f"Identity Matrix Error: {e}")

# ====================================================================================
# 🛡️ ADVANCED MODERATION CONSOLE
# ====================================================================================
async def get_target_user(event, args):
    reply = await event.get_reply_message()
    if reply: return reply.sender
    if args:
        try:
            target = args.strip()
            return await bot1.get_entity(int(target) if target.lstrip('-').isdigit() else target)
        except Exception: return None
    return None

@bot1.on(events.NewMessage(pattern=r'^/mute(?:@\w+)?(?:\s+(.*))?'))
async def mute_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    target_user = await get_target_user(event, event.pattern_match.group(1))
    if not target_user: return

    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, send_messages=False)
        await register_temporary_mute(event.chat_id, target_user.id, duration_minutes=60)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User'))}</a>"
        mute_text = (
            f"🌌 <b>𝙈𝙐𝙏𝙀 𝙊𝙋𝙀𝙍𝘼𝙏𝙄𝙊𝙉</b>\n"
            f"🛸 ───────────────────\n"
            f"🔇 <b>Target:</b> {mention}\n"
            f"🆔 <b>User ID:</b> <code>{target_user.id}</code>\n"
            f"⚡ <b>Status:</b> <code>Muted (မြုပြီး)</code>"
        )
        inline_buttons = [[Button.inline("Unmute? 🔊", data=f"inline_unmute_{target_user.id}")]]
        await event.respond(bq(mute_text), parse_mode='html', buttons=inline_buttons)
    except Exception as e: print(f"Mute Error: {e}")

@bot1.on(events.NewMessage(pattern=r'^/unmute(?:@\w+)?(?:\s+(.*))?'))
async def unmute_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    target_user = await get_target_user(event, event.pattern_match.group(1))
    if not target_user: return

    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, send_messages=True)
        await muted_registry_col.delete_one({"chat_id": event.chat_id, "user_id": target_user.id})
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User'))}</a>"
        unmute_text = (
            f"🌌 <b>𝙐𝙉𝘽𝘼𝙉 𝙐𝙉𝙈𝙐𝙏𝙀 𝙊𝙋𝙀𝙍𝘼𝙏𝙄𝙊𝙉</b>\n"
            f"🔊 <b>Target:</b> {mention}\n"
            f"🆔 <b>User ID:</b> <code>{target_user.id}</code>\n"
            f"⚡ <b>Status:</b> <code>Voice Restored / Cleared</code>"
        )
        await event.respond(bq(unmute_text), parse_mode='html')
    except Exception as e: print(f"Unmute Error: {e}")

@bot1.on(events.NewMessage(pattern=r'^/ban(?:@\w+)?(?:\s+(.*))?'))
async def ban_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    target_user = await get_target_user(event, event.pattern_match.group(1))
    if not target_user: return

    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, view_messages=False)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User'))}</a>"
        ban_text = (
            f"🌌 <b>𝘽𝘼𝙉 𝙊𝙋𝙀𝙍𝘼𝙏𝙄𝙊𝙉</b>\n"
            f"🚫 <b>Target:</b> {mention}\n"
            f"🆔 <b>User ID:</b> <code>{target_user.id}</code>\n"
            f"⚡ <b>Status:</b> <code>Exiled / Perm-Banned (ဘန်းပစ်လိုက်ရှုပ်တယ်)</code>"
        )
        await event.respond(bq(ban_text), parse_mode='html')
    except Exception as e: print(f"Ban Error: {e}")

@bot1.on(events.NewMessage(pattern=r'^/unban(?:@\w+)?(?:\s+(.*))?'))
async def unban_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    target_user = await get_target_user(event, event.pattern_match.group(1))
    if not target_user: return

    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, view_messages=True)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User'))}</a>"
        unban_text = (
            f"🌌 <b>𝙐𝙉𝘽Α𝙉 𝙊𝙋𝙀𝙍𝘼𝙏𝙄𝙊𝙉</b>\n"
            f"✅ <b>Target:</b> {mention}\n"
            f"🆔 <b>User ID:</b> <code>{target_user.id}</code>\n"
            f"⚡ <b>Status:</b> <code>Ban Lifted / Allowed to Join</code>"
        )
        await event.respond(bq(unban_text), parse_mode='html')
    except Exception as e: print(f"Unban Error: {e}")

@bot1.on(events.NewMessage(pattern=r'^/kick(?:@\w+)?(?:\s+(.*))?'))
async def kick_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    target_user = await get_target_user(event, event.pattern_match.group(1))
    if not target_user: return

    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, view_messages=False)
        await bot1.edit_permissions(event.chat_id, target_user.id, view_messages=True)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User'))}</a>"
        kick_text = (
            f"🌌 <b>𝙆𝙄𝘾𝙆 𝙊𝙋𝙀𝙍𝘼𝙏𝙄𝙊𝙉</b>\n"
            f" <b>Target:</b> {mention}\n"
            f"🆔 <b>User ID:</b> <code>{target_user.id}</code>\n"
            f"⚡ <b>Status:</b> <code>Removed / Kicked from Chat</code>"
        )
        await event.respond(bq(kick_text), parse_mode='html')
    except Exception as e: print(f"Kick Error: {e}")

@bot1.on(events.CallbackQuery(pattern=r'^inline_unmute_(\d+)'))
async def inline_unmute_callback(event):
    if not await check_ban_rights(event.chat_id, event.sender_id):
        return await event.answer("⚠️ You are not authorized to use this console!", alert=True)

    target_id = int(event.pattern_match.group(1))
    try:
        await bot1.edit_permissions(event.chat_id, target_id, send_messages=True)
        await muted_registry_col.delete_one({"chat_id": event.chat_id, "user_id": target_id})
        try:
            target_user = await bot1.get_entity(target_id)
            name = escape_html(getattr(target_user, 'first_name', 'User'))
        except: name = "User"
            
        mention = f"<a href='tg://user?id={target_id}'>{name}</a>"
        updated_text = (
            f"🌌 <b>𝙈𝙐𝙏𝙀 𝙎𝙔𝙎𝙏𝙀𝙈 𝙐評𝘿𝘼𝙏𝙀</b>\n"
            f"🔊 {mention} has been <b>Unmuted</b> via administrative console.\n"
            f"⚡ <b>Status:</b> <code>Restrictions Disintegrated</code>"
        )
        await event.edit(bq(updated_text), parse_mode='html', buttons=None) 
    except Exception as e: await event.answer(f"Action Failed: {e}", alert=True)

# ====================================================================================
# 📣 COMPACT ADMIN TAG SYSTEM
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/adm(?:\s+(.*))?'))
async def tag_admins(event):
    if event.is_private: return
    if not await check_admin(event.chat_id, event.sender_id): return
    text = event.pattern_match.group(1) or "Adminတို့ရေ ခေါ်နေပါတယ်🤍"
    
    try:
        admins = await bot1.get_participants(event.chat_id, filter=ChannelParticipantsAdmins)
        admin_mentions = []
        cyber_emojis = ["⚡", "🔮", "💎", "✨", "🔥", "🛸", "🛡️", "🪐", "🌌", "🦾"]
        
        for index, a in enumerate(admins):
            if a.bot or getattr(a, 'deleted', False): continue
            full_name = f"{a.first_name or ''} {a.last_name or ''}".strip() or "Admin"
            emoji = cyber_emojis[index % len(cyber_emojis)]
            mention = f"<a href='tg://user?id={a.id}'><b>{escape_html(full_name)}</b></a> {emoji}"
            admin_mentions.append(mention)
        
        compact_admin_list = "  •  ".join(admin_mentions)
        adm_signal_text = (
            f"📢 <b>Broadcast:</b> <code>{escape_html(text)}</code>\n\n"
            f"🌌 <b>𝘼𝘿𝙈𝙄🇳 𝘼𝙎𝙎𝙀𝙈𝘽𝙇𝙔 𝙎𝙄𝙂𝙉𝘼𝙇</b>\n"
            f"🛡️ <b>Active Officers:</b>\n"
            f"{compact_admin_list}"
        )
        await event.respond(bq(adm_signal_text), parse_mode='html')
    except Exception as e: print(f"Admin Tag System Error: {e}")

@bot1.on(events.NewMessage(pattern=r'^/addallow(?:@\w+)?$'))
async def add_allow(event):
    if event.sender_id != OWNER_ID: return
    reply = await event.get_reply_message()
    if reply:
        await allow_col.update_one({"user_id": reply.sender_id}, {"$set": {"name": reply.sender.first_name}}, upsert=True)
        await event.reply(bq(f"{escape_html(reply.sender.first_name)} ကို Allow List ထည့်ပြီးပါပြီ! ✅"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/removeallow(?:@\w+)?\s+(\d+)'))
async def remove_allow(event):
    if event.sender_id != OWNER_ID: return
    target_id = int(event.pattern_match.group(1))
    delete_result = await allow_col.delete_one({"user_id": target_id})
    if delete_result.deleted_count > 0: await event.respond(bq(f"User ID {target_id} ကို ပါမစ်မပေးတော့ဘူး"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/allowlist(?:@\w+)?$'))
async def allow_list(event):
    if event.sender_id != OWNER_ID: return
    users = await allow_col.find().to_list(length=None)
    msg = "<b>✅ Allowed Users List:</b>\n\n" + "".join([f"• <a href='tg://user?id={u.get('user_id')}'>{escape_html(u.get('name', 'Unknown'))}</a> (<code>{u.get('user_id')}</code>)\n" for u in users]) if users else "Allow List မှာ မရှိသေးပါ။"
    await event.reply(bq(msg), parse_mode='html')

# ====================================================================================
# 📢 GLOBAL BROADCAST SYSTEM
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/ပို့(?:@\w+)?(?:\s+(.*))?'))
async def broadcast(event):
    if event.sender_id != OWNER_ID: return
    reply_msg = await event.get_reply_message()
    command_text = event.pattern_match.group(1)
    if not reply_msg and not command_text: return
    
    success, fail = 0, 0
    init_text = f"🌌 <b>𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏 𝙎... 𝙄𝙉𝙄𝙏𝙄𝘼𝙏𝙀𝘿</b>\n⚡ <b>Transmission:</b> <code>Deploying signals...</code>"
    status_msg = await event.respond(bq(init_text), parse_mode='html')
    groups = await groups_col.find().to_list(length=None)

    for g in groups:
        chat_id = g['chat_id']
        try:
            if reply_msg: await bot1.forward_messages(chat_id, reply_msg)
            else: await bot1.send_message(chat_id, command_text, parse_mode='html')
            success += 1
            await asyncio.sleep(0.2) 
        except errors.rpcerrorlist.FloodWaitError as e:
            await asyncio.sleep(e.seconds + 2)
            try:
                if reply_msg: await bot1.forward_messages(chat_id, reply_msg)
                else: await bot1.send_message(chat_id, command_text, parse_mode='html')
                success += 1
            except: fail += 1
        except Exception: fail += 1
            
    report_text = f"🌌 <b>𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏 𝙏𝙍𝘼𝙉𝙎𝙈𝙄𝙎𝙎𝙄𝙊𝙉 𝘾𝙊𝙈𝙋𝙇𝙀𝙏𝙀𝘿</b>\n✅ <b>Success Sectors:</b> <code>{success}</code>\n❌ <b>Failed Sectors:</b>  <code>{fail}</code>"
    await status_msg.edit(bq(report_text), parse_mode='html')

# ====================================================================================
# 🛡️ CHANNEL FORWARD, BIO & HARREM FILTERS
# ====================================================================================
@bot1.on(events.NewMessage())
async def protection_logic(event):
    if event.is_private: return
    if not event.text or event.sender_id == OWNER_ID or event.sender_id in bot_ids: return

    text, chat_id, sender_id = event.text.strip(), event.chat_id, event.sender_id
    sender = await event.get_sender()

    if re.search(r'/harrrem(@\w+)?', text) or re.search(r'/waaaifu(@\w+)?', text):
        try:
            mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name)}</a>"
            cmd_type = "harem" if "harem" in text.lower() else "waifu"
            async def delay_delete():
                await asyncio.sleep(2)
                try: await event.delete()
                except: pass
            asyncio.create_task(delay_delete())

            msg_template = "<b>{type} လုပ်သူ-</b> {mention}\nChat သန့်ရှင်းအောင် ဖျက်လိုက်ပါပြီ。"
            warn_msg = await event.respond(bq(msg_template.format(type=cmd_type, mention=mention)), parse_mode='html')
            for i in range(2, -1, -1):
                await asyncio.sleep(1)
                if i == 0: await warn_msg.delete(); break
                await warn_msg.edit(bq(msg_template.format(type=cmd_type, mention=mention) + f"\n\n{i} စက္ကန့်အတွင်း ပျောက်ကွယ်သွားပါမယ်।"), parse_mode='html')
            return 
        except: pass

    if text:
        text_lower = text.lower()
        BIO_KEYWORDS = ["bio", "b i o", "biolink", "bio-link", "b-i-o", "tg bio", "ဘိုင်အို", "ဘိုင်-အို", "ဘိုင်-o", "ဘီအိုင်အို", "b.i.o", "ဘိုင်အိုလင့်", "ဘိုင်အိုလင့်ခ်"]

        if any(key in text_lower for key in BIO_KEYWORDS) and not await check_admin(chat_id, sender_id):
            try:
                await event.delete()
                sender = await event.get_sender()
                first_name = sender.first_name if sender else "User"
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(first_name)}</a>"
                
                warn_text = f"⚠️ <b>❌𝘽𝙄𝙊 𝘼𝙇𝙀𝙍𝙏</b>\n{mention}, ဟိုက်<b>Bio</b> မှာ ဘာဖစ်တာလဲ တိချင်ဝူး.\n\n⚡ <b>Status:</b> <blockquote expandable>Message Disintegrated 🗑️</blockquote>"
                await event.respond(bq(warn_text), parse_mode='html')
                return 
            except Exception as e: print(f"Bio Filter Error: {e}")

    urls = re.findall(r'(https?://\S+|www\.\S+)', text)
    if urls and not (event.audio or event.voice):
        if await check_admin(chat_id, sender_id):
            try:
                f_msg = await bot1.forward_messages(event.chat_id, event.message)
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name)}</a>"
                await f_msg.reply(f"<b>Link Sender- {mention}</b>", parse_mode='html')
                await event.delete()
            except: pass
        else:
            try:
                await event.delete() 
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name)}</a>"
                await event.respond(bq(f"ဟိတ်🐬 {mention} link မပို့နဲ့ bro/sis မင်း link ကို ဖျက်လိုက်ပြီ"), parse_mode='html')
            except: pass

# ====================================================================================
# 🎵 ADVANCED MULTIMEDIA PLAY & TRACKING SYSTEM
# ====================================================================================
play_blocks = {}  

@bot1.on(events.NewMessage(pattern=r'^/play(?:\s+(.*))?'))
async def play_response(event):
    if event.is_private: return
    song_title = event.pattern_match.group(1)
    if not song_title: return await event.reply(bq("🛸 Please provide a song title!\nExample: <code>/play Faded</code>"), parse_mode='html')

    chat_id = event.chat_id
    sender = await event.get_sender()
    user_id = event.sender_id
    
    if sender and getattr(sender, 'username', None): mention = f"@{sender.username}"
    else: mention = f"<a href='tg://user?id={user_id}'>{escape_html(getattr(sender, 'first_name', 'User'))}</a>"

    session_key = (chat_id, user_id)
    if session_key not in play_blocks: play_blocks[session_key] = {"msg_id": None, "songs": []}

    current_song_entry = {"title": song_title.strip(), "by": mention}
    play_blocks[session_key]["songs"].append(current_song_entry)

    playlist_text = ""
    for index, s in enumerate(play_blocks[session_key]["songs"], start=1):
        playlist_text += f"{index} 💿 <code>/play {escape_html(s['title'])}</code> — {s['by']}\n"

    try:
        owner_entity = await bot1.get_entity(OWNER_ID)
        owner_fullname = f"{owner_entity.first_name or ''} {owner_entity.last_name or ''}".strip() or "Khant Thu Rain"
    except Exception: owner_fullname = "Khant Thu Rain" 

    msg_template = (
        f"🌌 <b>{escape_html(owner_fullname)} Multimedia System</b>\n"
        f"💿 <b>Now Spinning:</b> <code>{escape_html(song_title.strip())}</code>\n"
        f"✨ <b>Requested By:</b> {mention}\n\n"
        f"💎 <b>Your Recent Playlist (Max 30):</b>\n"
        f"{playlist_text}"
        f"💡 <i>ဒါက မင်း ဖွင့်တဲ့ song 30 ပုဒ်အထိ သိမ်းထားပေးပြီး /play xxxကို ထိတာနဲ့ copyဖြစ်ပြီ🍬</i>"
    )

    inline_buttons = [
        [Button.url("ကျမတို့ဂလုကိုjoinပေးပါလား ဟိ🤍", "https://t.me/Comeback_BoD")],
        [Button.inline("songsစုထားမယ် နှိပ် 📥", data=f"save_pl_{user_id}")]
    ]

    try:
        last_msg_id = play_blocks[session_key]["msg_id"]
        if last_msg_id:
            try:
                await bot1.edit_message(entity=chat_id, message=last_msg_id, text=bq(msg_template), parse_mode='html', buttons=inline_buttons)
                try: await event.delete()
                except: pass
            except: last_msg_id = None

        if not last_msg_id:
            new_msg = await event.respond(bq(msg_template), parse_mode='html', buttons=inline_buttons)
            play_blocks[session_key]["msg_id"] = new_msg.id
            try: await event.delete()
            except: pass

        if len(play_blocks[session_key]["songs"]) >= 30: play_blocks[session_key] = {"msg_id": None, "songs": []}
    except Exception as e: print(f"Multimedia Play System Error: {e}")

@bot1.on(events.CallbackQuery(pattern=r'^save_pl_(\d+)$'))
async def close_playlist_callback(event):
    chat_id = event.chat_id
    clicker_id = event.sender_id
    target_user_id = int(event.pattern_match.group(1))
    
    if clicker_id != target_user_id:
        return await event.answer("❌ ဒါက မင်းရဲ့ Playlist မဟုတ်ပါဘူး! မင်းကိုယ်ပိုင် /play စာရင်းကိုပဲ ပိတ်လို့ရပါမယ်။", alert=True)
        
    session_key = (chat_id, target_user_id)
    try:
        msg = await event.get_message()
        current_html = msg.html if msg else ""
        frozen_buttons = [[Button.url("Join Our Group", "https://t.me/Comeback_BoD")], [Button.inline("🔒 Playlist Locked & Ready to Save", data="playlist_frozen_done")]]
        if current_html: await event.edit(text=current_html, parse_mode='html', buttons=frozen_buttons)
        if session_key in play_blocks: del play_blocks[session_key]
        await event.answer("🔒 Playlist Terminated!", alert=True)
    except Exception as e: print(f"Callback Error: {e}")

# ====================================================================================
# 👾 CORE GAME UTILITIES HANDLERS (MAIN 60 INTEGRATION)
# ====================================================================================
DEFAULT_SPAWN_INTERVAL = 15

@bot1.on(events.NewMessage(pattern=r'^/addchar\s+(.*)'))
async def game_add_character_handler(event):
    if not await is_allowed(event.sender_id): return
    try:
        segments = event.pattern_match.group(1).split('|')
        if len(segments) < 3:
            return await event.reply(bq("⚠️ <b>အသုံးပြုပုံစံမှားယွင်းနေပါသည်:</b>\n<code>/addchar Name | Rarity | Image_URL_or_FileID</code>"), parse_mode='html')
        
        char_name = segments[0].strip()
        rarity = segments[1].strip()
        media_id = segments[2].strip()
        
        await characters_col.update_one(
            {"name": char_name},
            {"$set": {"rarity": rarity, "media": media_id}},
            upsert=True
        )
        await event.reply(bq(f"✅ <b>Character Added Successfully:</b>\n🎭 <b>အမည်:</b> {f(char_name)}\n💎 <b>Rarity:</b> {rarity}"), parse_mode='html')
    except Exception as e:
        await report_system_error("Game Add Character Engine", e)

@bot1.on(events.NewMessage(pattern=r'^/(?:hai|profile)$'))
async def game_profile_handler(event):
    is_cd, rem = await is_on_cooldown(event.sender_id, "profile", 2)
    if is_cd: return
    
    sender = await event.get_sender()
    fullname = getattr(sender, 'first_name', 'User')
    profile = await ensure_game_profile(event.sender_id, fullname)
    
    cards_count = len(profile.get("caught_cards", []))
    profile_layout = (
        f"🎮 <b><u>{f(fullname)}'s Galactic Ledger Profile</u></b>\n"
        f"🛸 ───────────────────\n"
        f"💰 <b>Wallet Balance:</b> <code>{f(profile['coins'])} Gold Coins 🪙</code>\n"
        f"🃏 <b>Total Caught Cards:</b> <code>{f(cards_count)} Cards 🗃️</code>\n"
        f"🪐 <b>Rank Sector status:</b> <code>Active Player</code>\n"
        f"🛸 ───────────────────"
    )
    await event.respond(bq(profile_layout), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/(?:fspawn|haii)$'))
async def game_force_spawn_handler(event):
    if event.is_private: return
    if not await check_admin(event.chat_id, event.sender_id): return
    
    count = await characters_col.count_documents({})
    if count == 0: return await event.respond(bq("❌ Database ထဲမှာ မည်သည့် Character မှ ထည့်သွင်းထားခြင်း မရှိသေးပါ Chief။"))
    
    random_cursor = characters_col.aggregate([{"$sample": {"size": 1}}])
    docs = await random_cursor.to_list(length=1)
    target_char = docs[0]
    
    await group_spawn_state_col.update_one(
        {"chat_id": event.chat_id},
        {"$set": {"active_character": target_char["name"]}},
        upsert=True
    )
    
    spawn_txt = (
        f"🔮 <b>🌌 𝘼𝙉𝙄𝙈𝙀 𝘾𝘼𝙍𝘿 𝙎𝙋𝘼𝙒𝙉𝙀𝘿 🌌</b>\n"
        f"🛸 ───────────────────\n"
        f"💎 <b>Rarity Status:</b> <code>{target_char['rarity']}</code>\n"
        f"💡 အဆိုပါ ဇာတ်ကောင်အား သင်၏ Collection ထဲသို့ ဖမ်းယူသိမ်းဆည်းရန် အောက်ပါအတိုင်း ရိုက်နှိပ်ပါChief-\n"
        f"👉 <code>/catch {target_char['name']}</code>"
    )
    await bot1.send_message(event.chat_id, bq(spawn_txt), file=target_char["media"], parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/catch\s+(.*)'))
async def game_catch_handler(event):
    if event.is_private: return
    is_cd, rem = await is_on_cooldown(event.sender_id, "catch", 1)
    if is_cd: return
    
    attempt_name = event.pattern_match.group(1).strip().lower()
    state = await group_spawn_state_col.find_one({"chat_id": event.chat_id})
    
    if not state or not state.get("active_character"):
        return await event.reply(bq("❌ လက်ရှိ Sector တွင် ဖမ်းယူရန် မည်သည့်ကတ်မှ ထွက်ပေါ်မနေပါ ဘရို။"), parse_mode='html')
    
    correct_name = state["active_character"]
    if attempt_name == correct_name.lower():
        await group_spawn_state_col.delete_one({"chat_id": event.chat_id})
        sender = await event.get_sender()
        fullname = getattr(sender, 'first_name', 'User')
        
        await ensure_game_profile(event.sender_id, fullname)
        reward_coins = random.randint(1000, 3000)
        
        await user_game_profiles_col.update_one(
            {"user_id": event.sender_id},
            {"$inc": {"coins": reward_coins}, "$push": {"caught_cards": correct_name}}
        )
        
        success_msg = (
            f"🎉 <b>𝙂𝘼𝙈𝙀 𝘾𝘼𝙏𝘾𝙃 𝙎𝙐𝘾𝘾𝙀𝙎𝙎𝙁𝙐𝙇!</b>\n\n"
            f"👤 <b>Player:</b> <a href='tg://user?id={event.sender_id}'>{escape_html(fullname)}</a>\n"
            f"🃏 <b>Caught Character:</b> <code>{f(correct_name)}</code>\n"
            f"🪙 <b>Bonus Earned:</b> <code>+{f(reward_coins)} Gold Coins</code>"
        )
        await event.reply(bq(success_msg), parse_mode='html')
    else:
        await event.reply(bq("❌ ဇာတ်ကောင်အမည် မှားယွင်းနေပါသည်။ စာလုံးပေါင်း သေချာပြန်စစ်ပြီးမှ ထပ်မံကြိုးစားပါ Chief။"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/haitime\s+(\d+)'))
async def game_change_haitime_handler(event):
    if not await check_admin(event.chat_id, event.sender_id): return
    new_interval = int(event.pattern_match.group(1))
    await system_col.update_one(
        {"chat_id": event.chat_id, "type": "spawn_config"},
        {"$set": {"interval": new_interval}},
        upsert=True
    )
    await event.reply(bq(f"⚙️ <b>System Config Updated:</b> အလိုအလျောက် ကတ်ထွက်မည့် သတ်မှတ်စာစောင်ရေအား <code>{new_interval}</code> စောင်သို့ ပြောင်းလဲသတ်မှတ်လိုက်ပါပြီ။"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/give\s+(\d+)'))
async def game_give_coins_handler(event):
    if not await is_allowed(event.sender_id): return
    reply = await event.get_reply_message()
    if not reply: return await event.reply(bq("⚠️ ဒင်္ဂါးပြား ထုတ်ပေးလိုသည့် Player ၏ မက်ဆေ့ခ်ျအား Reply ပြန်၍ သုံးပေးပါ Chief။"), parse_mode='html')
    
    amount = int(event.pattern_match.group(1))
    target_user = await reply.get_sender()
    target_name = getattr(target_user, 'first_name', 'User')
    
    await ensure_game_profile(reply.sender_id, target_name)
    await user_game_profiles_col.update_one({"user_id": reply.sender_id}, {"$inc": {"coins": amount}})
    await event.respond(bq(f"🪙 <b>Administrative Grant:</b> {f(target_name)} ထံသို့ ရွှေဒင်္ဂါး <code>{f(amount)}</code> ပြားအား အခမဲ့ ထုတ်ပေးလိုက်ပါပြီ။"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/takeall\s+(\d+)'))
async def game_takeall_coins_handler(event):
    if event.sender_id != OWNER_ID: return
    amount = int(event.pattern_match.group(1))
    await user_game_profiles_col.update_many({}, {"$inc": {"coins": -amount}})
    await event.respond(bq(f"⚖️ <b>System Penalization Matrix:</b> Database အတွင်းရှိ ကစားသမား အားလုံးထံမှ ရွှေဒင်္ဂါး <code>{f(amount)}</code> ပြားစီအား အဓမ္မ သိမ်းဆည်းလိုက်ပါပြီ။"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/giftall\s+(\d+)'))
async def game_giftall_coins_handler(event):
    if event.sender_id != OWNER_ID: return
    amount = int(event.pattern_match.group(1))
    await user_game_profiles_col.update_many({}, {"$inc": {"coins": amount}})
    await event.respond(bq(f"🎁 <b>Sovereign Global Gift:</b> Database အတွင်းရှိ ကစားသမား အားလုံးထံသို့ တစ်ဦးလျှင် ရွှေဒင်္ဂါး <code>{f(amount)}</code> ပြားစီ အခမဲ့ လက်ဆောင် ဖြန့်ဝေပေးလိုက်ပါပြီ။"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/resetstats$'))
async def game_reset_stats_handler(event):
    if not await check_admin(event.chat_id, event.sender_id): return
    global chat_counters
    chat_counters[event.chat_id] = 0
    await event.reply(bq("⚙️ Active Group Message Counters အားလုံးကို Zero (0) သို့ ပြန်လည် ဆွဲချရှင်းလင်းလိုက်ပါပြီ။"), parse_mode='html')

# ==========================================
# 🧹 OWNER SYSTEM PURGE COMMAND (/cleanhai)
# ==========================================
@bot1.on(events.NewMessage(pattern=r'^/cleanhai(?:@\w+)?$'))
async def clean_all_harem_catches(event):
    """Owner မှ စနစ်အတွင်းရှိ ကစားသမားအားလုံး၏ ဖမ်းမိထားသော ကတ်များ (Vault) နှင့် Catch Records အားလုံးကို ရှင်းလင်းဖျက်သိမ်းသည့် စနစ်"""
    if event.sender_id != OWNER_ID: return
    try:
        # ဒေတာဘေ့စ်အတွင်းရှိ ကစားသမားအားလုံး၏ harem, total_caught နှင့် group_catches များကို Reset ချပြီး favorite ကတ်ကိုပါ ဖျက်ခြင်း
        result = await users_catcher_col.update_many(
            {},
            {
                "$set": {
                    "harem": [],
                    "total_caught": 0,
                    "group_catches": {}
                },
                "$unset": {
                    "fav_card": ""
                }
            }
        )
        
        text = (
            f"🧹 <b>{f('SYSTEM PURGE MATRIX ACTIVATED')}</b>\n"
            f"⚡ ━━━━━━━━━━━━━━━━━━━━ ⚡\n"
            f"<blockquote>Database အတွင်းရှိ ကစားသမားအားလုံးရဲ့ Vault Collection (<code>/hai</code>)၊ Total Catches (<code>/profile</code>) နဲ့ ဖမ်းယူထားသမျှ Item Records အားလုံးကို အောင်မြင်စွာ ရှင်းလင်း (Reset) ပြုလုပ်လိုက်ပါပြီ Boss! ⚠️</blockquote>\n"
            f"📊 <b>{f('Affected Accounts')}:</b> <code>{result.modified_count}</code> ယောက်"
        )
        await event.reply(text, parse_mode='html')
    except Exception as e:
        await event.reply(f"❌ <b>Cleanhai System Fault:</b> <code>{e}</code>", parse_mode='html')
# ==========================================
# 🃏 MULTIPLAYER CARD GAME SYSTEM
# ==========================================
@bot1.on(events.NewMessage(pattern=r'^/cardgame\s+(\d+)$'))
async def create_cardgame_lobby(event):
    if event.is_private: return
    chat_id = event.chat_id
    user_id = event.sender_id
    bet_amount = int(event.pattern_match.group(1))
    
    if bet_amount <= 0:
        return await event.reply("❌ လောင်းကြေးက အနည်းဆုံး 1 MMK ရှိရပါမယ်။")
        
    user_data = await users_catcher_col.find_one({"user_id": user_id})
    if not user_data or user_data.get("wallet_balance", 0) < bet_amount:
        return await event.reply("❌ လောင်းကြေးမလောက်ပါဘူး Bro!")
        
    if chat_id in active_card_games and active_card_games[chat_id]["status"] != "ended":
        return await event.reply("⚠️ ဒီဂရုထဲမှာ လက်ရှိ Active ဖြစ်နေတဲ့ ကစားပွဲ ရှိနေပါသေးတယ်။")
        
    mention = await get_html_mention(event, user_id)
    active_card_games[chat_id] = {
        "host_id": user_id,
        "bet": bet_amount,
        "players": {user_id: mention},
        "status": "lobby",
        "msg_id": None
    }
    
    lobby_text = (
        f"🃏 <b>{f('CARD GAME LOBBY OPENED')}</b>\n"
        f"⚡ ━━━━━━━━━━━━━━━━━━━━ ⚡\n"
        f"👤 <b>Host:</b> {mention}\n"
        f"💵 <b>Bet Stake:</b> <code>{bet_amount:,} MMK</code>\n\n"
        f"<blockquote><b>ကစားလိုသူများအောက်က Button ကိုနှိပ်ပြီး join နိုင်ပါသည်။ Host မှ /startgame ဖြင့် စတင်နိုင်ပါသည်။</b></blockquote>"
    )
    buttons = [[Button.inline("🃏 ပါမယ့်သူဆိုနှိပ်လိုက်", data=f"cardjoin_{chat_id}")]]
    msg = await event.reply(lobby_text, parse_mode='html', buttons=buttons)
    active_card_games[chat_id]["msg_id"] = msg.id

@bot1.on(events.NewMessage(pattern=r'^/startgame(?:@\w+)?$'))
async def start_cardgame_handler(event):
    if event.is_private: return
    chat_id = event.chat_id
    
    if chat_id not in active_card_games:
        return await event.reply("❌ <b>ဒီဂရုမှာ စတင်စရာ ကစားပွဲ Lobby မရှိသေးပါဘူး!</b>", parse_mode='html')
        
    game = active_card_games[chat_id]
    if game["status"] != "lobby": return
    if event.sender_id != game["host_id"]:
        return await event.reply("❌ <b>ပွဲစဉ်ကို Host လုပ်သူသာလျှင် စတင်ခွင့် ရှိပါတယ်။</b>", parse_mode='html')
        
    if len(game["players"]) < 2:
        return await event.reply("👥 <b>ကစားပွဲစတင်ရန် အနည်းဆုံး ကစားသမား ၂ ဦး လိုအပ်ပါတယ် Bro!</b>", parse_mode='html')
        
    game["status"] = "playing"
    
    valid_players = {}
    for p_id, p_name in list(game["players"].items()):
        p_doc = await users_catcher_col.find_one({"user_id": p_id})
        if p_doc and p_doc.get("wallet_balance", 0) >= game["bet"]:
            valid_players[p_id] = p_name
            
    if len(valid_players) < 2:
        game["status"] = "ended"
        del active_card_games[chat_id]
        return await event.reply("❌ ကစားသမားများ ငွေမလုံလောက်တော့သဖြင့် ပွဲပျက်သွားပါပြီ။")
        
    game["players"] = valid_players
    pool = game["bet"] * len(game["players"])
    results = {}
    max_score = -1
    
    for pid, name in game["players"].items():
        card_score = random.randint(1, 10)
        results[pid] = {"name": name, "score": card_score}
        if card_score > max_score:
            max_score = card_score
            
    winners = [pid for pid, data in results.items() if data["score"] == max_score]
    split_prize = pool // len(winners)
    
    for pid in game["players"].keys():
        if pid in winners:
            await users_catcher_col.update_one({"user_id": pid}, {"$inc": {"wallet_balance": split_prize - game["bet"]}})
        else:
            await users_catcher_col.update_one({"user_id": pid}, {"$inc": {"wallet_balance": -game["bet"]}})
            
    res_text = f"🃏 <b>{f('CARD GAME RESULTS')}</b>\n"
    res_text += f"💵 <b>Total Pool:</b> <code>{pool:,} MMK</code>\n"
    res_text += f"⚡ ━━━━━━━━━━━━━━━━━━━━ ⚡\n\n"
    for pid, data in results.items():
        res_text += f"👤 {data['name']} — ရမှတ်: <code>[{data['score']}]</code>\n"
        
    res_text += f"\n🏆 <b>{f('WINNER(S)')}:</b>\n"
    for w_id in winners:
        res_text += f"✨ {results[w_id]['name']} (+<code>{split_prize:,} MMK</code>)\n"
        
    game["status"] = "ended"
    del active_card_games[chat_id]
    await event.reply(res_text, parse_mode='html')
# ==========================================
# 🎰 HI-LO CASINO GAME SYSTEM
# ==========================================
@bot1.on(events.NewMessage(pattern=r'^/hilo\s+(HIGH|LOW)\s+(\d+)$'))
async def hilo_game_handler(event):
    user_id = event.sender_id
    choice = event.pattern_match.group(1).upper()
    bet_amount = int(event.pattern_match.group(2))
    
    if bet_amount <= 0: return
    
    user_data = await users_catcher_col.find_one({"user_id": user_id})
    if not user_data or user_data.get("wallet_balance", 0) < bet_amount:
        return await event.reply("❌ <b>လောင်းကြေးမလောက်ပါဘူး Boss!</b>", parse_mode='html')
        
    cards = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
    card_display = {2:"2", 3:"3", 4:"4", 5:"5", 6:"6", 7:"7", 8:"8", 9:"9", 10:"10", 11:"J", 12:"Q", 13:"K", 14:"A"}
    
    base_card = random.choice(cards)
    new_card = random.choice(cards)
    while new_card == base_card:
        new_card = random.choice(cards)
        
    base_display = card_display[base_card]
    new_display = card_display[new_card]
    
    is_win = False
    if choice == "HIGH" and new_card > base_card:
        is_win = True
    elif choice == "LOW" and new_card < base_card:
        is_win = True
        
    mention = await get_html_mention(event, user_id)
    if is_win:
        await users_catcher_col.update_one({"user_id": user_id}, {"$inc": {"wallet_balance": bet_amount}})
        status_text = f"🎉 <b>{f('CHALLENGE WON')}!!! (+{bet_amount:,} MMK)</b>"
    else:
        await users_catcher_col.update_one({"user_id": user_id}, {"$inc": {"wallet_balance": -bet_amount}})
        status_text = f"💸 <b>{f('CHALLENGE LOST')}... (-{bet_amount:,} MMK)</b>"
        
    result_text = (
        f"🃏 <b>{f('HI-LO CASINO MATRIX RESULTS')}</b>\n"
        f"👤 <b>Player:</b> {mention}\n"
        f"💵 <b>Bet Stake:</b> <code>{bet_amount:,} MMK</code>\n\n"
        f"🎴 ယခင်ပြထားတဲ့ကတ်: <b>[ {base_display} ]</b>\n"
        f"🎲 နောက်ထွက်လာတဲ့ကတ်: ✨ <b>[ {new_display} ]</b> ✨\n"
        f"🎯 မင်းရွေးချယ်ခဲ့တာ: <code>{choice}</code>\n\n"
        f"{status_text}"
    )
    await event.reply(result_text, parse_mode='html')
# ==========================================
# 🎰 SLOTS MACHINE GAME SYSTEM
# ==========================================
@bot1.on(events.NewMessage(pattern=r'^/slots\s+(\d+)$'))
async def slots_game_handler(event):
    user_id = event.sender_id
    bet = int(event.pattern_match.group(1))
    
    if bet <= 0: return
    user_data = await users_catcher_col.find_one({"user_id": user_id})
    if not user_data or user_data.get("wallet_balance", 0) < bet:
        return await event.reply("❌ <b>လောင်းကြေးမလောက်ပါဘူး Boss!</b>", parse_mode='html')
        
    mention = await get_html_mention(event, user_id)
    symbols = ["🍒", "🍋", "🍊", "🍇", "🔔", "⭐", "💎", "🐃", "🦀", "🐄", "🦅"]
    
    anim_msg = await event.reply(f"🎰 {mention} <b>{f('SPINNING MATRIX SLOTS')}... 🌀</b>", parse_mode='html')
    await asyncio.sleep(0.6)
    
    mid_syms = random.choices(symbols, k=7)
    mid_str = " | ".join(mid_syms)
    await bot1.edit_message(
        event.chat_id, anim_msg.id,
        f"🎰 {mention} <b>{f('REELS ARE LOCKING IN')}... 🔥</b>\n\n"
        f"<b>[ {mid_str} ]</b>\n\n"
        f"<i>Decelerating Matrix Engine... ⚡</i>",
        parse_mode='html'
    )
    await asyncio.sleep(0.9)
    
    res_syms = random.choices(symbols, k=7)
    res_str = " | ".join(res_syms)
    
    from collections import Counter
    counts = Counter(res_syms)
    most_common_sym, max_count = counts.most_common(1)[0]
    
    win_amount = 0
    if max_count == 7:
        win_amount = bet * 77 if most_common_sym == "🐃" else bet * 50
        status_text = f"🥶 <b>{f('GOD-TIER JACKPOT')}!!! (+{win_amount:,} MMK)</b>"
    elif max_count == 6:
        win_amount = bet * 25
        status_text = f"💎 <b>{f('MEGA MULTI-MATCH')}!!! (+{win_amount:,} MMK)</b>"
    elif max_count == 5:
        win_amount = bet * 12
        status_text = f"⚡ <b>{f('SUPER MULTI-MATCH')}!! (+{win_amount:,} MMK)</b>"
    elif max_count == 4:
        win_amount = bet * 5
        status_text = f"😲 <b>{f('MULTI-MATCH SUCCESS')}! (+{win_amount:,} MMK)</b>"
    else:
        win_amount = 0
        status_text = f"💸 <b>{f('SLOT ENGINE FAILURE / ရှုံးနိမ့်သွားပါပြီ')} ... (-{bet:,} MMK)</b>"
        
    if win_amount > 0:
        await users_catcher_col.update_one({"user_id": user_id}, {"$inc": {"wallet_balance": win_amount - bet}})
    else:
        await users_catcher_col.update_one({"user_id": user_id}, {"$inc": {"wallet_balance": -bet}})
        
    final_text = (
        f"🎰 <b>{f('SLOT MACHINE REALITY RESULT')}</b>\n"
        f"👤 <b>Player:</b> {mention}\n"
        f"💵 <b>Base Stake:</b> <code>{bet:,} MMK</code>\n\n"
        f"🎰 <b>[ {res_str} ]</b> 🎰\n\n"
        f"✨ <b>Matching Metrics:</b> <code>{max_count}x '{most_common_sym}'</code>\n"
        f"<blockquote>{status_text}</blockquote>"
    )
    await bot1.edit_message(event.chat_id, anim_msg.id, final_text, parse_mode='html')
# ==========================================
# 🪙 COIN FLIP GAME SYSTEM
# ==========================================
@bot1.on(events.NewMessage(pattern=r'^/coin\s+(head|tail|ခေါင်း|ပန်း)\s+(\d+)$'))
async def coin_flip_handler(event):
    user_id = event.sender_id
    choice_input = event.pattern_match.group(1).lower()
    bet_amount = int(event.pattern_match.group(2))
    
    if bet_amount <= 0: return
    user_data = await users_catcher_col.find_one({"user_id": user_id})
    if not user_data or user_data.get("wallet_balance", 0) < bet_amount:
        return await event.reply("❌ <b>လောင်းကြေးမလောက်ပါဘူး Boss!</b>", parse_mode='html')
        
    mention = await get_html_mention(event, user_id)
    animation_msg = await event.reply(f"🪙 {mention} <b>{f('FLIPPING COIN IN THE AIR')}... 🌀</b>", parse_mode='html')
    await asyncio.sleep(1.5)
    
    result = random.choice(["head", "tail"])
    is_win = False
    if choice_input in ["head", "ခေါင်း"] and result == "head": is_win = True
    elif choice_input in ["tail", "ပန်း"] and result == "tail": is_win = True
    
    display_result = "ခေါင်း (HEAD)" if result == "head" else "ပန်း (TAIL)"
    
    if is_win:
        await users_catcher_col.update_one({"user_id": user_id}, {"$inc": {"wallet_balance": bet_amount}})
        await bot1.edit_message(event.chat_id, animation_msg.id, f"🪙 {mention} <b>{f('COIN FLIP SUCCESS')}!!</b>\n✨ ရလဒ်က [ <b>{display_result}</b> ] ဖြစ်ပါတယ်!\n🎉 Boss မှန်သွားလို့ ပွဲနိုင်ပါတယ်။ <code>+{bet_amount:,} MMK</code>", parse_mode='html')
    else:
        await users_catcher_col.update_one({"user_id": user_id}, {"$inc": {"wallet_balance": -bet_amount}})
        await bot1.edit_message(event.chat_id, animation_msg.id, f"🪙 {mention} <b>{f('COIN FLIP FAILED')}..</b>\n💨 ရလဒ်က [ <b>{display_result}</b> ] ဖြစ်ပါတယ်!\n💸 မှားသွားတဲ့အတွက် လောင်းကြေးရှုံးသွားပါပြီ။ <code>-{bet_amount:,} MMK</code>", parse_mode='html')
# ==========================================
# 🎲 INTERACTIVE DICE GAME SYSTEM
# ==========================================
@bot1.on(events.NewMessage(pattern=r'^/dice\s+(\d+)$'))
async def dice_game_handler(event):
    user_id = event.sender_id
    bet_amount = int(event.pattern_match.group(1))
    chat_id = event.chat_id
    
    if bet_amount <= 0: return
    user_data = await users_catcher_col.find_one({"user_id": user_id})
    if not user_data or user_data.get("wallet_balance", 0) < bet_amount:
        return await event.reply("❌ <b>လောင်းကြေးမလောက်ပါဘူး Boss!</b>", parse_mode='html')
        
    mention = await get_html_mention(event, user_id)
    dice_msg = await bot1.send_message(chat_id, file=types.InputMediaDice(emoticon="🎲"))
    await asyncio.sleep(3.5)
    
    dice_value = dice_msg.media.value
    if dice_value >= 4:
        await users_catcher_col.update_one({"user_id": user_id}, {"$inc": {"wallet_balance": bet_amount}})
        await event.reply(f"🎉 {mention} <b>{f('DICE MATCH WIN')}!!!</b>\n🎲 ရလဒ်အမှတ်: <code>{dice_value}</code> (၄ နှင့်အထက်)\n🪙 စနစ်မှ <code>+{bet_amount:,} MMK</code> ထည့်သွင်းပေးလိုက်ပါပြီ။", parse_mode='html')
    else:
        await users_catcher_col.update_one({"user_id": user_id}, {"$inc": {"wallet_balance": -bet_amount}})
        await event.reply(f"💸 {mention} <b>{f('DICE MATCH LOSS')}...</b>\n🎲 ရလဒ်အမှတ်: <code>{dice_value}</code> (၃ နှင့်အောက်)\n📉 သင့်အကောင့်ထဲမှ <code>-{bet_amount:,} MMK</code> နှုတ်ယူလိုက်ပါပြီ။", parse_mode='html')
# ==========================================
# 🌲 TEXT ADVENTURE HUNT GAME SYSTEM
# ==========================================
@bot1.on(events.NewMessage(pattern=r'^/hunt(?:@\w+)?$'))
async def text_adventure_hunt_handler(event):
    user_id = event.sender_id
    mention = await get_html_mention(event, user_id)
    user_doc = await users_catcher_col.find_one({"user_id": user_id})
    
    current_time = time.time()
    last_hunt = user_doc.get("hunt_cooldown", 0) if user_doc else 0
    if current_time - last_hunt < 180:
        return await event.reply(f"⏳ {mention} <b>{f('အမဲလိုက်ထွက်ခြင်း နားပါဦး Bro!')} Cooldown စက္ကန့် {int(180 - (current_time - last_hunt))}s လိုပါသေးသည်။</b>", parse_mode='html')
        
    earned = random.randint(200, 80000)
    hunt_stories = [
        f"🌲 {mention} သည် မှော်တောနက်ကြီးထဲသို့ သတ္တိရှိရှိ ဝင်ရောက်ပြီး သားရဲနဂါးတစ်ကောင်ကို သတ်ဖြတ်ကာ ရတနာသေတ္တာအိုကြီးကို တွေ့ရှိခဲ့သည်။ 💎",
        f"🧙‍♀️ {mention} သည် တောစပ်တွင် လမ်းပျောက်နေသော စုန်းမအိုကြီးကို ကူညီခဲ့သဖြင့် စုန်းမကြီးမှ ကျေးဇူးတုံ့ပြန်သောအားဖြင့် ရွှေဒင်္ဂါးအိတ် ပေးအပ်ခဲ့သည်။ ✨",
        f"🏚 {mention} သည် ပျက်စီးနေသော ရှေးဟောင်းဂူဗိမာန်အတွင်း စွန့်စားရှာဖွေရင်း ဖုံးကွယ်ထားသော လျှို့ဝှက်မြေအောက်ခန်းတစ်ခုကို ဖော်ထုတ်နိုင်ခဲ့သည်။ 🪙",
        f"⚔️ {mention} သည် တောပုန်းဓားပြဂိုဏ်းတစ်ခုနှင့် ထိပ်တိုက်တိုးပြီး ဓားပြဗိုလ်ကို အောင်မြင်စွာ နှိမ်နင်းကာ ၎င်းတို့ခိုးယူထားသော ရိက္ခာဘဏ္ဍာများကို သိမ်းပိုက်နိုင်ခဲ့သည်။ 🔥"
    ]
    
    story = random.choice(hunt_stories)
    await users_catcher_col.update_one(
        {"user_id": user_id},
        {"$set": {"hunt_cooldown": current_time}, "$inc": {"wallet_balance": earned}}
    )
    
    hunt_text = (
        f"🏹 <b>{f('HUNTING EXCURSION REPORT')}</b>\n"
        f"⚡ ━━━━━━━━━━━━━━━━━━━━ ⚡\n"
        f"<blockquote>{story}</blockquote>\n"
        f"💰 <b>Bounty Recovered:</b> <code>+{earned:,} MMK</code>\n"
        f"⏱️ <b>Next Hunt Cooldown:</b> <code>3 Minutes (180s)</code>"
    )
    await event.reply(hunt_text, parse_mode='html')
# ==========================================
# 🛒 PREMIUM AUCTION MARKETPLACE ENGINE
# ==========================================
@bot1.on(events.NewMessage(pattern=r'^/sell\s+([a-zA-Z0-9_]+)\s+(\d+)$'))
async def sell_market_handler(event):
    user_id = event.sender_id
    char_id = event.pattern_match.group(1).upper()
    price = int(event.pattern_match.group(2))
    
    if price <= 0:
        return await event.reply(f"❌ <b>{f('ဈေးနှုန်းက အနည်းဆုံး 1 MMK တော့ ရှိရမယ်လေ Bro!')}</b>", parse_mode='html')
        
    user_doc = await users_catcher_col.find_one({"user_id": user_id})
    user_harem = user_doc.get("harem", []) if user_doc else []
    
    char_item = next((x for x in user_harem if isinstance(x, dict) and x.get("char_id") == char_id and x.get("status") != "market"), None)
    if not char_item:
        return await event.reply(f"❌ <b>{f('ဒီကတ်က သင့် Vault ထဲမှာ အလွတ်မရှိပါဘူး သို့မဟုတ် စျေးကွက်တင်ထားပြီးသားဖြစ်နေပါတယ် Bro!')}</b>", parse_mode='html')
        
    char_data = await characters_base_col.find_one({"char_id": char_id})
    if not char_data: return
    
    listing_id = f"LST{random.randint(10000, 99999)}"
    char_item["status"] = "market"
    char_item["listing_id"] = listing_id
    
    await users_catcher_col.update_one({"user_id": user_id}, {"$set": {"harem": user_harem}})
    sender_name = user_doc.get("fullname", f"Agent {user_id}")
    
    await marketplace_col.insert_one({
        "listing_id": listing_id,
        "seller_id": user_id,
        "seller_name": sender_name,
        "char_id": char_id,
        "char_name": char_data["name"],
        "char_rarity": char_data.get("rarity", "🪵 COMMON"),
        "price": price,
        "listed_date": time.time()
    })
    
    await event.reply(
        f"🛒 <b>{f('MARKETPLACE LISTING SECURED')}</b>\n"
        f"⚡ ━━━━━━━━━━━━━━━━━━━━ ⚡\n"
        f"🆔 <b>Listing ID:</b> <code>{listing_id}</code>\n"
        f"🃏 <b>Character:</b> <code>{char_data['name']}</code> [{char_id}]\n"
        f"💰 <b>Asking Price:</b> <code>{price:,} MMK</code>\n\n"
        f"<blockquote>မိမိတင်ထားသောကတ်အား ပြန်လည်ရုပ်သိမ်းလိုပါက <code>/buy {char_id}</code> ဖြင့် ပြန်လည်ရုပ်သိမ်းနိုင်ပါသည်။</blockquote>",
        parse_mode='html'
    )

@bot1.on(events.NewMessage(pattern=r'^/buy\s+([a-zA-Z0-9_]+)$'))
async def buy_market_handler(event):
    user_id = event.sender_id
    char_id = event.pattern_match.group(1).upper()
    
    my_listing = await marketplace_col.find_one({"char_id": char_id, "seller_id": user_id})
    if my_listing:
        user_doc = await users_catcher_col.find_one({"user_id": user_id})
        user_harem = user_doc.get("harem", []) if user_doc else []
        for x in user_harem:
            if isinstance(x, dict) and x.get("listing_id") == my_listing["listing_id"]:
                x["status"] = "vault"
                del x["listing_id"]
                break
        await users_catcher_col.update_one({"user_id": user_id}, {"$set": {"harem": user_harem}})
        await marketplace_col.delete_one({"listing_id": my_listing["listing_id"]})
        return await event.reply(f"🎉 <b>{f('Direct Purchase Success')}</b>\nမိမိတင်ထားသော အရောင်းစာရင်းကို အောင်မြင်စွာ ဖျက်သိမ်းပြီး Vault ထဲပြန်ထည့်ပေးလိုက်ပါပြီ။", parse_mode='html')
        
    listings = await marketplace_col.find({"char_id": char_id}).sort("price", 1).to_list(length=10)
    if not listings:
        return await event.reply(f"❌ <b>{f('ဒီကတ်အတွက် လက်ရှိရောင်းချသူ မရှိသေးပါဘူး Bro!')}</b>", parse_mode='html')
        
    market_text = f"🛒 <b>{f('MARKETPLACE LISTINGS FOR')} : {char_id}</b>\n⚡ ━━━━ ⚡\n\n"
    buttons = []
    for item in listings:
        market_text += f"👤 <b>Merchant:</b> {item['seller_name']} [<code>{item['seller_id']}</code>]\n💰 <b>Price Value:</b> <code>{item['price']:,} MMK</code>\n\n"
        buttons.append([Button.inline(f"Buy via {item['price']:,} MMK", data=f"mktbuy_{item['listing_id']}")])
        
    await event.reply(market_text, parse_mode='html', buttons=buttons)

@bot1.on(events.NewMessage(pattern=r'^/market$'))
async def view_global_market(event):
    all_listings = await marketplace_col.find().sort("listed_date", -1).limit(20).to_list(length=20)
    if not all_listings:
        return await event.reply(f"🏪 <b>{f('规则 စျေးကွက်ထဲတွင် မည်သည့်ကတ်မှ ရောင်းရန်မရှိသေးပါ Bro!')}</b>", parse_mode='html')
        
    msg = f"🏪 <b>{f('BOD GLOBAL LEADERBOARD AUCTION MARKET')}</b>\n⚡ ━━━━━━━━━━━━━━━━━━━━ ⚡\n\n"
    for item in all_listings:
        msg += f"📦 <b>[{item['char_id']}] {item['char_name']}</b>\n💰 Price: <code>{item['price']:,} MMK</code> | 👤 Seller: {item['seller_name']}\n⚙️ ဝယ်ရန်: <code>/buy {item['char_id']}</code>\n⚡ ━━━━━ ⚡\n"
    await event.reply(msg, parse_mode='html')
# ==========================================
# 🤝 14. PEER TRADE MATRIX (/trade)
# ==========================================
@bot1.on(events.NewMessage(pattern=r'^/trade\s+([a-zA-Z0-9_]+)\s+([a-zA-Z0-9_]+)$'))
async def trade_proposal_handler(event):
    if not event.is_reply:
        return await event.reply(f"❌ <b>{f('Trade လုပ်မယ့်သူရဲ့ စာကို Reply ပြန်ပြီး ခေါ်ယူပေးပါ Bro!')}</b>", parse_mode='html')
        
    my_char_id = event.pattern_match.group(1).upper()
    their_char_id = event.pattern_match.group(2).upper()
    
    sender_id = event.sender_id
    reply_msg = await event.get_reply_message()
    target_id = reply_msg.sender_id
    
    if sender_id == target_id:
        return await event.reply("❌ မိမိကိုယ်တိုင်နဲ့ ကတ်လဲလို့မရပါဘူး Bro!")
        
    s_doc = await users_catcher_col.find_one({"user_id": sender_id})
    s_harem = s_doc.get("harem", []) if s_doc else []
    s_item = next((x for x in s_harem if isinstance(x, dict) and x.get("char_id") == my_char_id and x.get("status") != "market"), None)
    
    if not s_item:
        return await event.reply(f"❌ သင့် Vault ထဲတွင် ကတ် ID [<code>{my_char_id}</code>] မရှိပါ သို့မဟုတ် စျေးကွက်တင်ထားပါသည်။")
        
    t_doc = await users_catcher_col.find_one({"user_id": target_id})
    t_harem = t_doc.get("harem", []) if t_doc else []
    t_item = next((x for x in t_harem if isinstance(x, dict) and x.get("char_id") == their_char_id and x.get("status") != "market"), None)
    
    if not t_item:
        return await event.reply(f"❌ တစ်ဖက်လူ၏ Vault ထဲတွင် ကတ် ID [<code>{their_char_id}</code>] မရှိပါ သို့မဟုတ် စျေးကွက်တင်ထားပါသည်။")
        
    s_mention = await get_html_mention(event, sender_id)
    t_mention = await get_html_mention(event, target_id)
    
    trade_text = (
        f"🤝 <b>{f('PROPOSED TRADE CONTRACT')}</b>\n"
        f"⚡ ━━━━━━━━━━━━━━━━━━━━ ⚡\n"
        f"👤 {s_mention} မှ {t_mention} ထံသို့ ကတ်ချင်းလဲလှယ်ရန် ကမ်းလှမ်းချက်။\n\n"
        f"📤 <b>{f('Your Asset')}:</b> <code>{my_char_id}</code>\n"
        f"📥 <b>{f('Their Asset')}:</b> <code>{their_char_id}</code>\n\n"
        f"<blockquote><b>ကမ်းလှမ်းမှုကို လက်ခံရန် တဖက်လူမှ အောက်က Button ကိုနှိပ်ပါ။</b></blockquote>"
    )
    buttons = [[Button.inline("🤝 ကမ်းလှမ်းချက်ကို လက်ခံသည်", data=f"tradeaccept_{sender_id}_{target_id}_{my_char_id}_{their_char_id}")]]
    await event.reply(trade_text, parse_mode='html', buttons=buttons)
# ==========================================
# ♻️ MELT ENGINE CORE (/scrap)
# ==========================================
@bot1.on(events.NewMessage(pattern=r'^/scrap\s+([a-zA-Z0-9_]+)$'))
async def scrap_card_handler(event):
    user_id = event.sender_id
    char_id = event.pattern_match.group(1).upper()
    mention = await get_html_mention(event, user_id)
    
    user_doc = await users_catcher_col.find_one({"user_id": user_id})
    user_harem = user_doc.get("harem", []) if user_doc else []
    char_item = next((x for x in user_harem if isinstance(x, dict) and x.get("char_id") == char_id and x.get("status") != "market"), None)
    
    if not char_item:
        return await event.reply(f"❌ <b>{f('ဒီကတ်က သင့် Vault ထဲမှာ မရှိပါဘူး Bro!')}</b>", parse_mode='html')
        
    char_base = await characters_base_col.find_one({"char_id": char_id})
    if not char_base: return
    
    refund_val = char_base.get("currency_value", 100) // 2
    user_harem.remove(char_item)
    
    await users_catcher_col.update_one(
        {"user_id": user_id},
        {"$set": {"harem": user_harem}, "$inc": {"wallet_balance": refund_val}}
    )
    
    scrap_msg = (
        f"♻️ <b>{f('ASSET INCINERATION / MELT ENGINE COMPLETED')}</b>\n"
        f"⚡ ━━━━━━━━━━━━━━━━━━━━ ⚡\n"
        f"🃏 <b>Scrapped Card:</b> <code>{char_base['name']}</code> [<code>{char_id}</code>]\n"
        f"🌟 <b>Rarity Grade:</b> {char_base['rarity']}\n"
        f"🪙 <b>Melt Scrap Refund (50%):</b> <code>+{refund_val:,} MMK</code>\n"
        f"<blockquote><b>အိုင်တမ်အား အောင်မြင်စွာ ဖျက်ဆီးပြီး ငွေပြန်အမ်းပေးလိုက်ပါပြီ Boss!</b></blockquote>"
    )
    await event.reply(scrap_msg, parse_mode='html')

# ==========================================
# 🏆 CASINO RICHEST MATRIX (/richest)
# ==========================================
@bot1.on(events.NewMessage(pattern=r'^/richest$'))
async def richest_leaderboard_handler(event):
    cursor = users_catcher_col.find({"wallet_balance": {"$gt": 0}}).sort("wallet_balance", -1).limit(10)
    richest_users = await cursor.to_list(length=10)
    
    if not richest_users:
        return await event.reply(f"🏆 <b>{f('Leaderboard matrix data clear ဖြစ်နေပါတယ် Bro!')}</b>", parse_mode='html')
        
    msg = f"💰 <b>{f('BODကာစီနိုနဲ့Cardဖမ်းလောကရဲ့ - TOP 10 RICHEST players')}</b>\n⚡ ━━━━━⚡\n"
    for i, u in enumerate(richest_users):
        bal = u.get("wallet_balance", 0)
        user_display = u.get('fullname') or f"User {u['user_id']}"
        msg += f"<b>{i+1}.</b> {user_display} — <code>{bal:,} MMK</code> 🪙\n"
    msg += f"\nFamily Cluster: <b>Brotherhood of Dexter</b>"
    await event.reply(msg, parse_mode='html')
# ==========================================
# 🔘 UNIFIED CALLBACK QUERY MATRIX PROCESSOR EXTENSIONS
# ==========================================
@bot1.on(events.CallbackQuery) #function အောက်က if/elif အစုစုထဲမှာ ဒါလေးတွေ ထည့်ပေးပါ-
async def unified_callback_matrix_processor(event):
    if not event.data:
        return
        
    # ⚡ Callback Data ကို String ပြောင်းပြီး '_' နဲ့ ခွဲထုတ်ပေးတဲ့ နှလုံးသားအပိုင်း
    try:
        data_str = event.data.decode('utf-8')
        data_parts = data_str.split('_')
        action_type = data_parts[0]
    except Exception:
        return

    # 🛑 ပထမဆုံး စဖွင့်မယ့် 'if' အခြေအနေ (ဒါက ဘရိုရဲ့ နဂိုမူလ code တစ်ခုခု ဖြစ်ရပါမယ်)
    if action_type == "test":
        await event.answer("System Testing Status: OK ✔️", alert=True)

    elif action_type == "mktbuy":
        listing_id = data_parts[1]
        buyer_id = event.sender_id
        listing = await marketplace_col.find_one({"listing_id": listing_id})
        if not listing: return await event.answer("❌ ဒီအရောင်းစာရင်းက မရှိတော့ပါဘူး သို့မဟုတ် ရောင်းထွက်သွားပါပြီ။", alert=True)
        price = listing["price"]
        seller_id = listing["seller_id"]
        char_id = listing["char_id"]
        if buyer_id == seller_id: return await event.answer("⚠️ မိမိပစ္စည်းကို မိမိပြန်ဝယ်လို့ မရပါဘူး Bro!", alert=True)
        
        buyer_doc = await users_catcher_col.find_one({"user_id": buyer_id})
        if not buyer_doc or buyer_doc.get("wallet_balance", 0) < price:
            return await event.answer("❌ သင့်ထံတွင် ဝယ်ယူရန် ငွေအလုံအလောက်မရှိပါ Bro!", alert=True)
            
        await users_catcher_col.update_one({"user_id": buyer_id}, {"$inc": {"wallet_balance": -price}})
        await users_catcher_col.update_one({"user_id": seller_id}, {"$inc": {"wallet_balance": price}})
        
        s_doc = await users_catcher_col.find_one({"user_id": seller_id})
        s_harem = s_doc.get("harem", [])
        s_item = next((x for x in s_harem if isinstance(x, dict) and x.get("listing_id") == listing_id), None)
        if s_item: s_harem.remove(s_item)
        await users_catcher_col.update_one({"user_id": seller_id}, {"$set": {"harem": s_harem}})
        
        b_mention = await get_html_mention(event, buyer_id)
        await users_catcher_col.update_one(
            {"user_id": buyer_id},
            {"$push": {"harem": {"char_id": char_id, "caught_date": time.time(), "rarity": listing.get("char_rarity", "✨ RARE"), "status": "vault"}}, "$set": {"fullname": b_mention}},
            upsert=True
        )
        await marketplace_col.delete_one({"listing_id": listing_id})
        await event.edit(f"🛍 <b>{f('MARKETPLACE TRANSACTION SUCCESS')}</b>\n{b_mention} မှ ကတ် ID [<code>{char_id}</code>] ကို <code>{price:,} MMK</code> ဖြင့် အောင်မြင်စွာ ဝယ်ယူလိုက်ပါပြီ။ 🔥")

    elif action_type == "cardjoin":
        g_chat_id = int(data_parts[1])
        p_id = event.sender_id
        if g_chat_id not in active_card_games: return await event.answer("❌ ကစားပွဲ သက်တမ်းကုန်သွားပါပြီ။", alert=True)
        game = active_card_games[g_chat_id]
        if game["status"] != "lobby": return await event.answer("❌ ကစားပွဲစတင်သွားပြီဖြစ်၍ join လို့မရတော့ပါ။", alert=True)
        if p_id in game["players"]: return await event.answer("⚠️ သင် join ပြီးသားဖြစ်နေပါတယ် Bro!", alert=True)
        
        p_doc = await users_catcher_col.find_one({"user_id": p_id})
        if not p_doc or p_doc.get("wallet_balance", 0) < game["bet"]:
            return await event.answer("❌ သင့်မှာ လောင်းကြေးအလုံအလောက်မရှိလို့ Join လို့မရပါ Bro!", alert=True)
            
        p_mention = await get_html_mention(event, p_id)
        game["players"][p_id] = p_mention
        
        lobby_text = (
            f"🃏 <b>{f('CARD GAME LOBBY OPENED')}</b>\n"
            f"⚡ ━━━━━━━━━━━━━━━━━━━━ ⚡\n"
            f"👤 <b>Host:</b> {game['players'][game['host_id']]}\n"
            f"💵 <b>Bet Stake:</b> <code>{game['bet']:,} MMK</code>\n\n"
            f"👥 <b>Joined Players ({len(game['players'])}):</b>\n"
        )
        for pl_name in game["players"].values():
            lobby_text += f"• {pl_name}\n"
        lobby_text += f"\n<blockquote><b>ကစားလိုသူများအောက်က Button ကိုနှိပ်ပြီး join နိုင်ပါသည်။ Host မှ /startgame ဖြင့် စတင်နိုင်ပါသည်။</b></blockquote>"
        buttons = [[Button.inline("🃏 ပါမယ့်သူဆိုနှိပ်လိုက်", data=f"cardjoin_{g_chat_id}")]]
        await event.edit(lobby_text, parse_mode='html', buttons=buttons)
        await event.answer("🎉 ကစားပွဲထဲသို့ Join ခြင်းအောင်မြင်ပါသည်။")

    elif action_type == "tradeaccept":
        sender_id = int(data_parts[1])
        target_id = int(data_parts[2])
        my_char_id = data_parts[3]
        their_char_id = data_parts[4]
        if event.sender_id != target_id: return await event.answer("⚠️ ၎င်းကမ်းလှမ်းချက်သည် သင့်အတွက်မဟုတ်ပါ!", alert=True)
        
        s_doc = await users_catcher_col.find_one({"user_id": sender_id})
        t_doc = await users_catcher_col.find_one({"user_id": target_id})
        s_harem = s_doc.get("harem", []) if s_doc else []
        t_harem = t_doc.get("harem", []) if t_doc else []
        
        s_item = next((x for x in s_harem if isinstance(x, dict) and x.get("char_id") == my_char_id and x.get("status") != "market"), None)
        t_item = next((x for x in t_harem if isinstance(x, dict) and x.get("char_id") == their_char_id and x.get("status") != "market"), None)
        
        if not s_item or not t_item: return await event.edit(f"❌ <b>{f('CONTRACT FAILED / ပိုင်ဆိုင်မှု အခြေအနေ ပြောင်းလဲသွားလို့ မအောင်မြင်တော့ပါ!')}</b>", parse_mode='html')
        
        s_harem.remove(s_item)
        t_harem.remove(t_item)
        s_harem.append({"char_id": their_char_id, "caught_date": time.time(), "rarity": t_item.get("rarity", "Unknown"), "status": "vault"})
        t_harem.append({"char_id": my_char_id, "caught_date": time.time(), "rarity": s_item.get("rarity", "Unknown"), "status": "vault"})
        
        await users_catcher_col.update_one({"user_id": sender_id}, {"$set": {"harem": s_harem}})
        await users_catcher_col.update_one({"user_id": target_id}, {"$set": {"harem": t_harem}})
        await event.edit(f"🤝 <b>{f('TRADE CONCLUDED / ကတ်လဲလှယ်ခြင်း လုပ်ငန်းစဉ် အောင်မြင်စွာ ပြီးဆုံးပါပြီ။ 🔥')}</b>", parse_mode='html')

# ====================================================================================
# 💀 BULlY & SHADOW BAN SYSTEM
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/b(?:@\w+)?$'))
async def bot_bully(event):
    if not await is_allowed(event.sender_id): return
    reply = await event.get_reply_message()
    if not reply: return
    try: await event.delete()
    except: pass
    t = await reply.get_sender()
    if not t or t.id == OWNER_ID: return

    bot_bully_tasks[event.chat_id] = True
    mention = f"<a href='tg://user?id={t.id}'>{escape_html(t.first_name)}</a>"
    db_filters = await filters_col.find().to_list(length=None)
    words = [w.get("text") for w in db_filters if w.get("text")] or ["စောက်ချိုးမပြေဘူး"]

    while bot_bully_tasks.get(event.chat_id):
        try: 
            await bot1.send_message(event.chat_id, bq(f"{mention} {random.choice(words)}"), reply_to=reply.id, parse_mode='html')
            await asyncio.sleep(2.0) 
        except: bot_bully_tasks[event.chat_id] = False; break

@bot1.on(events.NewMessage(pattern=r'^/sb(?:@\w+)?$'))
async def stop_bot_bully(event):
    if not await is_allowed(event.sender_id): return
    bot_bully_tasks[event.chat_id] = False
    await event.respond(bq("နားလိုက်ပြီ။"))
                
@bot1.on(events.NewMessage(pattern=r'^/shadow(?:@\w+)?$'))
async def set_shadow_ban(event):
    if not await is_allowed(event.sender_id): return
    reply = await event.get_reply_message()
    if not reply or reply.sender_id == OWNER_ID: return
    dark_passenger_targets[event.chat_id] = reply.sender_id
    await event.respond(bq("Dark Passenger တပ်ဆင်ပြီးပါပြီ။"))

@bot1.on(events.NewMessage(pattern=r'^/unshadow(?:@\w+)?$'))
async def remove_shadow_ban(event):
    if not await is_allowed(event.sender_id): return
    if event.chat_id in dark_passenger_targets:
        del dark_passenger_targets[event.chat_id]
        await event.respond(bq("Dark Passenger ပြန်လည်ထွက်ခွာသွားပါပြီ။"))

@bot1.on(events.NewMessage(pattern=r'^လိုက်မှတ်$'))
async def turn_on_learning(event):
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    learning_status[SPECIFIC_CONTROL_GROUP] = True
    await event.reply(bq("စကားမှတ်သားခြင်း စနစ် ဖွင့်လိုက်ပြီ။"))

@bot1.on(events.NewMessage(pattern=r'^မမှတ်နဲ့တော့$'))
async def turn_off_learning(event):
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    learning_status[SPECIFIC_CONTROL_GROUP] = False
    await event.reply(bq("စကားမှတ်သားခြင်း စနစ် ပိတ်လိုက်ပြီ။"))

@bot1.on(events.NewMessage(pattern=r'^စကားဝင်ပြော$'))
async def turn_on_talking(event):
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    global GLOBAL_TALK
    GLOBAL_TALK = True
    on_text = f"🌌 <b>𝙑𝙊𝘾𝘼𝙇 𝙋𝙍𝙊𝙏𝙊𝘾𝙊𝙇: 𝘼𝘾𝙏𝙄𝙑𝘼𝙏𝙀𝘿</b>\n🔊 Smart Reply Engine ကို Sector အားလုံးမှာ စကားဝင်ပြောဖို့ အသက်သွင်းပြီး"
    await event.reply(bq(on_text), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^မပြောနဲ့တော့$'))
async def turn_off_talking(event):
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    global GLOBAL_TALK
    GLOBAL_TALK = False
    off_text = f"🔇 Smart Reply Engine ကို Absolute <b>Stealth Mode</b> ပြောင်းပြီး စကားပိတ်လိုက်ပါပြီ!"
    await event.reply(bq(off_text), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^(ရပ်|အပစ်ရပ်)$'))
async def stop_actions(event):
    if not await is_allowed(event.sender_id): return
    shoot_tasks[event.chat_id] = False
    if event.chat_id in tracking_targets: del tracking_targets[event.chat_id]
    await event.reply(bq("အပစ်ရပ်စဲလိုက်ပြီ။"))

@bot1.on(events.NewMessage())
async def dark_passenger_watcher(event):
    chat_id = event.chat_id
    sender_id = event.sender_id
    if chat_id in dark_passenger_targets and sender_id == dark_passenger_targets[chat_id]:
        if event.text and not event.text.startswith(('/', '.', 'မှတ်')):
            try:
                await event.delete()
                sender = await event.get_sender()
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name if sender else 'Subject')}</a>"
                insults = [
                    f"🤫 <b>THE ILLUSION OF VOICE</b>\n\nMorgan lets your pathetic fingers click those keys, {mention}, but he owns the void.",
                    f"💀 <b>MORGAN'S ISOLATION CHAMBER</b>\n\nGo ahead and type another essay, {mention}. Morgan allows the keystroke but incinerates the output."
                ]
                insult_msg = await event.respond(bq(random.choice(insults)), parse_mode='html')
                await asyncio.sleep(4.0)
                await insult_msg.delete()
            except: pass

# ====================================================================================
# 🌐 LANGUAGE & FLOOD CONTROL INCOMING GLOBAL COUNTERS
# ====================================================================================
FORBIDDEN_SCRIPTS = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\u0e00-\u0e7f\u0600-\u06ff\uac00-\ud7af]')

@bot1.on(events.NewMessage(incoming=True))
async def global_traffic_processing_matrix(event):
    if event.is_private or not event.text: return
    if event.sender_id == OWNER_ID or event.sender_id in bot_ids: return

    chat_id = event.chat_id
    sender_id = event.sender_id

    # FORBIDDEN LANGUAGE FILTER SYSTEM
    if chat_id == SPECIFIC_GROUP and not await check_admin(chat_id, sender_id):
        if FORBIDDEN_SCRIPTS.search(event.text):
            try:
                await event.delete()
                sender = await event.get_sender()
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name if sender else 'User')}</a>"
                warn_text = f"⚠️ <b>SYSTEM SECURITY ALERT</b>\nHey {mention}, only <b>Burmese, English</b> and <b>Numbers</b> are allowed.\n\n⚡ <b>လုပ်ဆောင်ချက်:</b> တခြားဘာသာစကား messageကိုဖျက်ချလိုက်ခြင်း"
                return await event.respond(bq(warn_text), parse_mode='html')
            except Exception: pass

    # CHANNEL FORWARD FILTER SYSTEM
    if event.fwd_from and isinstance(event.fwd_from.from_id, types.PeerChannel):
        if not await check_admin(chat_id, sender_id):
            try:
                await event.delete()
                sender = await event.get_sender()
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name if sender else 'User')}</a>"
                warn_msg = f"🚫 <b>CHANNEL FORWARD NOT ALLOWED!</b>\n\nHey {mention} Channel ကနေ Forward လာတဲ့ Post တွေ ပို့ခွင့်မရှိပါဘူးရှင့်🌬️<b>[Erased]</b>"
                return await event.respond(bq(warn_msg), parse_mode='html')
            except Exception: pass

    # AUTOMATED ANIME CARD DROP LOGIC (MAIN 60 INTEGRATION REVOLUTION)
    global chat_counters
    if not event.text.startswith(('/', '.', 'မှတ်', '@')):
        chat_counters[chat_id] = chat_counters.get(chat_id, 0) + 1
        
        config_doc = await system_col.find_one({"chat_id": chat_id, "type": "spawn_config"})
        target_trigger_count = config_doc["interval"] if config_doc else DEFAULT_SPAWN_INTERVAL
        
        if chat_counters[chat_id] >= target_trigger_count:
            chat_counters[chat_id] = 0
            # Automated Spawn Dispatcher
            count_chars = await characters_col.count_documents({})
            if count_chars > 0:
                random_cursor = characters_col.aggregate([{"$sample": {"size": 1}}])
                docs = await random_cursor.to_list(length=1)
                target_char = docs[0]
                await group_spawn_state_col.update_one(
                    {"chat_id": chat_id}, {"$set": {"active_character": target_char["name"]}}, upsert=True
                )
                spawn_txt = f"🔮 <b>🌌 𝘼𝙉𝙄𝙈𝙀 𝘾𝘼𝙍𝘿 𝙎𝙋𝘼𝙒𝙉𝙀𝘿 🌌</b>\n🛸 ───────────────────\n💎 <b>Rarity Status:</b> <code>{target_char['rarity']}</code>\n👉 <code>/catch {target_char['name']}</code>"
                try: await bot1.send_message(chat_id, bq(spawn_txt), file=target_char["media"], parse_mode='html')
                except Exception: pass

# ====================================================================================
# 👈 REPLY SAVE AUTO RESPONDER SYSTEM (NON-BLOCKING ASYNC POOL)
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/ktr(?:\s+(\d+))?$'))
async def turn_on_reply_save_match(event):
    global IS_REPLY_ACTIVE, REPLY_INTERVAL
    if event.sender_id != OWNER_ID: return
    IS_REPLY_ACTIVE = True
    interval_arg = event.pattern_match.group(1)
    if interval_arg: REPLY_INTERVAL = int(interval_arg)
        
    ktr_on_text = f"🌌 <b>စာလိုက်ထောက် စကားဝင်ပြောမယ့် mood:𝘼𝘾𝙏𝙄𝙑𝙰𝚃𝙴𝘿</b>\n🎯 Target Tracking Matrix engaged.\n⚡ Core system will intervene every <code>{REPLY_INTERVAL}</code> messages, Chief!"
    await event.reply(bq(ktr_on_text), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/ktrr$'))
async def turn_off_reply_save_match(event):
    global IS_REPLY_ACTIVE
    if event.sender_id != OWNER_ID: return
    IS_REPLY_ACTIVE = False
    ktr_off_text = f"⛔ System disengaged. Auto-response matrix entering offline sleep mode."
    await event.reply(bq(ktr_off_text), parse_mode='html')

async def processed_background_reply(event, user_text, as_reply=True):
    chat_entity = await event.get_input_chat()
    smart_reply = await fetch_optimized_smart_reply(user_text)
    if smart_reply:
        try:
            async with bot1.action(chat_entity, 'typing'):
                await asyncio.sleep(random.uniform(0.5, 1.5))
            if as_reply: await event.reply(smart_reply, parse_mode='html')
            else: await event.respond(smart_reply, parse_mode='html')
        except errors.rpcerrorlist.FloodWaitError as e: await asyncio.sleep(e.seconds + 1)
        except Exception: pass

@bot1.on(events.NewMessage(incoming=True))
async def reply_save_counter_handler(event):
    global reply_msg_counters, IS_REPLY_ACTIVE, REPLY_INTERVAL
    if not IS_REPLY_ACTIVE: return
    if event.is_private or not event.text or event.text.startswith(('/', '.', 'မှတ်', '@')): return
    sender = await event.get_sender()
    if sender and sender.bot: return

    chat_id = event.chat_id
    reply_msg_counters[chat_id] = reply_msg_counters.get(chat_id, 0) + 1
    if reply_msg_counters[chat_id] >= REPLY_INTERVAL:
        reply_msg_counters[chat_id] = 0 
        asyncio.create_task(processed_background_reply(event, event.text.strip(), as_reply=True))

@bot1.on(events.NewMessage(incoming=True))
async def global_talk_counter_handler(event):
    global group_msg_counters, GLOBAL_TALK, GLOBAL_TALK_INTERVAL
    if not GLOBAL_TALK: return
    if event.is_private or not event.text or event.text.startswith(('/', '.', 'မှတ်', '@')): return
    sender = await event.get_sender()
    if sender and sender.bot: return

    chat_id = event.chat_id
    group_msg_counters[chat_id] = group_msg_counters.get(chat_id, 0) + 1
    if group_msg_counters[chat_id] >= GLOBAL_TALK_INTERVAL:
        group_msg_counters[chat_id] = 0
        asyncio.create_task(processed_background_reply(event, event.text.strip(), as_reply=False))

# ==========================================
# 🚀 SYSTEM INITIALIZATION GATEWAY
# ==========================================
async def start_system():
    threading.Thread(target=run_flask, daemon=True).start()
    print("Starting Main Bot Engine (Sovereign System Plus Architecture)...")
    await bot1.start(bot_token=MAIN_BOT_TOKEN)
    me_main = await bot1.get_me()
    bot_ids.append(me_main.id)
    print(f"Sovereign Engine synchronized as @{me_main.username}")
    
    # Background Worker Coroutines
    asyncio.create_task(periodic_buffer_flusher())
    asyncio.create_task(smart_auto_unmute_worker())
    asyncio.create_task(weather_daily_cron_loop())
    
    await bot1.run_until_disconnected()

if __name__ == '__main__':
    try: asyncio.run(start_system())
    except (KeyboardInterrupt, SystemExit): print("Sovereign Core Shutting Down Safely.")
