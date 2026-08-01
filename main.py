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
users_col = db["users"]
user_game_profiles_col = db["user_game_profiles"]
characters_col = db["characters"]
muted_registry_col = db["muted_registry"]

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
# 🚀 ADVANCED SYSTEM LOGIC: REAL-TIME USER METRICS TRACKER
def track_user_metrics(user_id, username, first_name):
    async def _track_bg():
        try:
            await users_col.update_one(
                {"user_id": user_id},
                {
                    "$set": {
                        "username": username,
                        "first_name": first_name,
                        "last_active": datetime.now(TZ)
                    }
                },
                upsert=True
            )
        except Exception as e:
            print(f"Error in track_user_metrics: {e}")
            
    try:
        asyncio.create_task(_track_bg())
    except Exception:
        pass

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
# 🚀 Mute သက်တမ်း မှတ်သားရန် Function အသစ်
async def register_temporary_mute(chat_id, user_id, duration_minutes=60):
    expiry_time = datetime.now(TZ) + timedelta(minutes=duration_minutes)
    await muted_registry_col.update_one(
        {"chat_id": chat_id, "user_id": user_id},
        {"$set": {"expiry": expiry_time}},
        upsert=True
    )

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
        f"🌤️ <b><u>မိုးလေဝသနှင့် ရာသီဥတု</u></b>\n"
        f"📍 <b>တိုင်းဒေသကြီး/ပြည်နယ်:</b> <code>{data['name']}</code>\n"
        f"🌡️ <b>လက်ရှိအပူချိန်:</b> <code>{data['temp']}</code>\n"
        f"☁️ <b>မိုးလေဝသ အခြေအနေ:</b> <code>{data['condition']}</code>\n"
        f"💧 <b>လေထုစိုထိုင်းဆ:</b> <code>{data['humidity']}</code>\n"
        f"💨 <b>လေတိုက်နှုန်း:</b> <code>{data['wind']}</code>\n"
        f"⏰ <b>နောက်ဆုံး Update:</b> <code>ယနေ့ ည ၀၈:၀၀ နာရီ</code>"
    )

async def weather_daily_cron_loop():
    while True:
        try:
            now = datetime.now(TZ)
            if now.hour == 20 and now.minute == 0:
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
# 🚀 SYSTEM INITIALIZATION GATEWAY (အမှန်ကန်ဆုံး ပေါင်းစပ်ပြီးသားဗားရှင်း)
# ==========================================
async def start_system():
    threading.Thread(target=run_flask, daemon=True).start()
    print("Starting Main Bot Engine (Sovereign System Plus Architecture)...")
    
    # 🗄️ Active Loop ထဲရောက်မှ Index တွေကို စနစ်တကျ Auto Sync လုပ်ပေးခြင်း (ဒါကြောင့် Render error မတက်တော့ပါ)
    try:
        await users_col.create_index("user_id", unique=True)
        await user_game_profiles_col.create_index("user_id", unique=True)
        await characters_col.create_index("name", unique=True)
        print("Database Indexes synchronized successfully! ✔️")
    except Exception as e:
        print(f"Index creation error: {e}")

    # Bot Engine ကို စတင်ပတ်ခြင်း
    await bot1.start(bot_token=MAIN_BOT_TOKEN)
    me_main = await bot1.get_me()
    bot_ids.append(me_main.id)
    print(f"Sovereign Engine synchronized as @{me_main.username}")
    
    # Background Worker Coroutines
    asyncio.create_task(weather_daily_cron_loop())
    
    # Bot ကို အမြဲတမ်း Live ဖြစ်နေအောင် ထိန်းထားပေးမည့်အဆင့်
    await bot1.run_until_disconnected()

if __name__ == '__main__':
    try: 
        asyncio.run(start_system())
    except (KeyboardInterrupt, SystemExit): 
        print("Sovereign Core Shutting Down Safely.")
