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
import pickle
from flask import Flask
from motor.motor_asyncio import AsyncIOMotorClient
from telethon.tl.types import User
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
from PIL import Image, ImageDraw, ImageFont, ImageOps
from openai import OpenAI 

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
def home(): return "BoD Sovereign System is Active!"

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
STORAGE_CHANNEL = -1003707008733
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
premium_talk_col = db["premium_talk_pool"]  # 👑 Premium Emoji မက်ဆေ့ခ်ျတွေ စုဆောင်းမည့် DB
premode_col = db["premode_status"]          # ⚙️ On/Off Setting သိမ်းမည့် DB

# ==========================================
# 🤖 CLIENT SETUP (SINGLE BOT)
# ==========================================
bot1 = TelegramClient('bot_main_session', APP_ID, APP_HASH)
bot_ids = []
bot_names = []

# ==========================================
# 📊 STATE VARIABLES
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
GLOBAL_PREMODE_THRESHOLD = None  # Lazy Loading အတွက် ကြိုတင်သတ်မှတ်ခြင်း (0 ဆိုရင် ပိတ်ထားတာ)
chat_counters = {}               # Group တစ်ခုချင်းစီရဲ့ စာစောင်အရေအတွက်ကို RAM ပေါ်မှာ ခဏမှတ်မည့်နေရာ
IS_REPLY_ACTIVE = False              
REPLY_INTERVAL = 4                   
GLOBAL_TALK_INTERVAL = 6            
reply_msg_counters = {}              

# ==========================================
# 🛠️ HELPERS & FILTERS
# ==========================================
def bq(text): return f"<blockquote><b>{text}</b></blockquote>"

def owner_tag():
    return f"<a href='https://t.me/{OWNER_USERNAME}'>@{OWNER_USERNAME}</a>"

async def is_allowed(user_id):
    if user_id == OWNER_ID: return True
    user = await allow_col.find_one({"user_id": user_id})
    return user is not None

async def check_admin(chat_id, user_id):
    if user_id == OWNER_ID: return True
    try:
        permissions = await bot1.get_permissions(chat_id, user_id)
        return permissions.is_admin
    except: return False

async def check_ban_rights(chat_id, user_id):
    if user_id == OWNER_ID: return True
    permissions = await bot1.get_permissions(chat_id, user_id)
    return permissions.is_admin and permissions.ban_users

async def update_admin_cache(client, chat_id):
    try:
        admins = await client(GetParticipantsRequest(
            channel=chat_id,
            filter=ChannelParticipantsAdmins(),
            offset=0, limit=100, hash=0
        ))
        admin_ids = {p.user_id for p in admins.participants}
        admin_cache[chat_id] = admin_ids
        return admin_ids
    except Exception as e:
        print(f"Error updating admin cache for {chat_id}: {e}")
        return admin_cache.get(chat_id, set())

async def get_group_uptime(chat_id):
    doc = await system_col.find_one({"chat_id": chat_id, "type": "uptime_tracker"})
    if not doc:
        now = datetime.now(pytz.utc)
        await system_col.insert_one({"chat_id": chat_id, "type": "uptime_tracker", "start_time": now})
        return 1
    return (datetime.now(pytz.utc) - doc["start_time"].replace(tzinfo=pytz.utc)).total_seconds()

def has_mention_or_link(message_text):
    if not message_text:
        return False
    if '@' in message_text or 't.me/' in message_text or 'http' in message_text:
        return True
    return False

# DB ထဲက Dictionary ကို Telethon Entity Object ပြန်ပြောင်းပေးမယ့် Helper
def dict_to_entity(d):
    if not d: return None
    cls_name = d.get('_')
    if cls_name:
        cls = getattr(types, cls_name, None)
        if cls:
            kwargs = {k: v for k, v in d.items() if k != '_'}
            return cls(**kwargs)
    return None
# ====================================================================================
# 🧠 SCHEMA-AGNOSTIC SMART REPLY SEARCH ENGINE (Weight-Scored Accuracy System)
# ====================================================================================
async def fetch_optimized_smart_reply(user_text):
    reply_text = None
    user_text_clean = user_text.strip().lower()

    # 📊 WEIGHT-BASED MATCHING PIPELINE
    match_pipeline = [
        {"$match": {
            "$or": [
                {"$and": [
                    {"$ifNull": ["$trigger", False]},
                    {"$gte": [{"$strLenCP": "$trigger"}, 2]},
                    {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$trigger"}]}, 0]}
                ]},
                {"$and": [
                    {"$ifNull": ["$key", False]},
                    {"$gte": [{"$strLenCP": "$key"}, 2]},
                    {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$key"}]}, 0]}
                ]},
                {"$and": [
                    {"$ifNull": ["$keyword", False]},
                    {"$gte": [{"$strLenCP": "$keyword"}, 2]},
                    {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$keyword"}]}, 0]}
                ]}
            ]
        }},
        # 🎯 စကားလုံးအရှည်ပေါ်မူတည်ပြီး Weight Score တွက်ချက်ခြင်း
        {"$addFields": {
            "weight": {
                "$max": [
                    {"$cond": [{"$and": [{"$ifNull": ["$trigger", False]}, {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$trigger"}]}, 0]}]}, {"$strLenCP": "$trigger"}, 0]},
                    {"$cond": [{"$and": [{"$ifNull": ["$key", False]}, {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$key"}]}, 0]}]}, {"$strLenCP": "$key"}, 0]},
                    {"$cond": [{"$and": [{"$ifNull": ["$keyword", False]}, {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$keyword"}]}, 0]}]}, {"$strLenCP": "$keyword"}, 0]}
                ]
            }
        }},
        # 🔝 Weight အမြင့်ဆုံးကို ထိပ်ဆုံးသို့ နေရာရွှေ့ပေးခြင်း
        {"$sort": {"weight": -1}},
        {"$limit": 10}
    ]

    try:
        cursor = reply_save_col.aggregate(match_pipeline)
        matched_docs = await cursor.to_list(length=10)
        
        if matched_docs:
            valid_choices = []
            max_weight = matched_docs[0]["weight"]
            best_docs = [d for d in matched_docs if d["weight"] == max_weight]
            
            for doc in best_docs:
                chosen = None
                if doc.get("responses") and isinstance(doc["responses"], list):
                    chosen = random.choice(doc["responses"])
                elif doc.get("values") and isinstance(doc["values"], list):
                    chosen = random.choice(doc["values"])
                elif doc.get("response"): chosen = doc["response"]
                elif doc.get("value"): chosen = doc["value"]
                elif doc.get("text"): chosen = doc["text"]

                if chosen and not has_mention_or_link(str(chosen)):
                    valid_choices.append(str(chosen))
            
            if valid_choices:
                reply_text = random.choice(valid_choices)
    except Exception as e:
        print(f"Smart Reply DB Error: {e}")
        reply_text = None

    # ⏳ FALLBACK 1: `talk_col` မှ ဆွဲယူခြင်း (အပေါ်က စနစ် အလုပ်မလုပ်ပါက)
    if not reply_text:
        try:
            fallback_cursor = talk_col.aggregate([{"$sample": {"size": 1}}])
            fallback_docs = await fallback_cursor.to_list(length=1)
            if fallback_docs and fallback_docs[0].get("text"):
                chosen_fb = fallback_docs[0]["text"]
                if not has_mention_or_link(chosen_fb):
                    reply_text = chosen_fb
        except Exception:
            reply_text = None

    # 🎯 Function ရဲ့ အပြင်ဘက်ဆုံး Output အနေနဲ့ ဒီကောင်လေး ရှိနေရမှာ ဖြစ်ပါတယ်!
    return reply_text
                    
# ====================================================================================
# 🛡️ SYSTEM COMMANDS & HANDLERS
# ====================================================================================

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
                await groups_col.update_one({"chat_id": chat.id}, {"$set": {"title": chat.title}}, upsert=True)
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
                        u = await bot1.get_entity(uid)
                        u_mention = f"<a href='tg://user?id={u.id}'>{escape_html(u.first_name)}</a>"
                        
                        if custom_welcome and custom_welcome.get("text"):
                            welcome_text = custom_welcome["text"]
                            welcome_text = welcome_text.replace("{mention}", u_mention).replace("{group}", safe_title)
                        else:
                            welcome_text = (
                                f"ဟိုက်{u_mention}\n"
                                "╔═━━━❖━━━═╗\n"
                                f"{safe_title}ကနေ ကြိုဆိုလိုက်ပါတယ်\n"
                                "╚═━━━❖━━━═╝\n"
                                f"This bot is proudly developed and maintained by 𝑷𝑨𝑹𝑨𝑫𝑶𝑿 𝑭𝒂𝒎𝒊𝒍𝒚⌬𝑩𝑶𝑫.\n"
                            )
                        
                        media_file = custom_welcome.get("media") if custom_welcome else None
                        await bot1.send_message(
                            event.chat_id, 
                            bq(welcome_text), 
                            parse_mode='html',
                            file=media_file,
                            buttons=[
                                [Button.url("Bot ဖြင့် Broadcasting အပ်ရန်", f"t.me/Hello_Im_DexterMorgan")],
                                [Button.url("ကျွန်ုပ်တို့Groupသို့ဝင်ရန်", "https://t.me/Comeback_BoD")]
                            ]
                        )
        elif event.user_left:
            u = await bot1.get_entity(event.user_id)
            u_mention = f"<a href='tg://user?id={u.id}'>{escape_html(u.first_name)}</a>"
            await bot1.send_message(event.chat_id, bq(f"ထွက်သွားလိုက်ပါသေးတယ်.{u_mention}!!"), parse_mode='html')

    except Exception as e:
        print(f"Welcome/Goodbye Error: {e}")

# 💬 AUTOMATIC CHAT RESPONDER
@bot1.on(events.NewMessage(incoming=True))
async def chatbot_auto_responder(event):
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
                await bot1.edit_permissions(chat_id, sender_id, until_date=datetime.now() + timedelta(minutes=5), send_messages=False)
                action_msg = f"🚫 {mention} ကို သတိပေးချက်ကို မလိုက်နာဘဲ စာတိုတွေ ဆက်တိုက် Spam တဲ့အတွက် ၅ မိနစ်ခန့် Mute လိုက်ပါပြီ။"
            
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

# ၁။ 💾 FILTER သိမ်းဆည်းသည့်စနစ် (Reply ပြန်ပြီး သိမ်းမည့်အပိုင်း)
@bot1.on(events.NewMessage(pattern=r'^[/.]f\s+(.*)'))
async def add_filter(event):
    if not await check_admin(event.chat_id, event.sender_id): return
    
    input_str = event.pattern_match.group(1).split(None, 1)
    keyword = input_str[0].lower().strip()
    
    reply = await event.get_reply_message()

    if reply:
        try:
            # Reply ထားတဲ့ မက်ဆေ့ခ်ျ (စာ၊ ပုံ၊ Premium Emoji အကုန်) ကို Storage ထဲ Forward လှမ်းလုပ်မယ်
            forwarded = await bot1.forward_messages(STORAGE_CHANNEL, reply)
            
            # MongoDB ထဲမှာတော့ အဲဒီ မက်ဆေ့ခ်ျရဲ့ ID (ဂဏန်းတစ်ခုတည်း) ကိုပဲ သိမ်းမယ် (DB ဘယ်တော့မှ မပြည့်ဘူး)
            await custom_filters_col.update_one(
                {"keyword": keyword}, 
                {"$set": {
                    "type": "storage_msg",
                    "msg_id": forwarded.id,
                    "chat_id": "global"
                }}, 
                upsert=True
            )
            await event.reply(bq(f"အိုကေ! '{keyword}' filter ကို Premium Emoji တွေအပါအဝင် Cloud စနစ်နဲ့ မှတ်လိုက်ပြီ ✅"), parse_mode='html')
        except Exception as e:
            await event.reply(bq(f"❌ Storage ထဲ လှမ်းသိမ်းရမှာ Error တက်သွားတယ်: {e}"), parse_mode='html')
    else:
        await event.reply(bq("⚠️ Filter မှတ်ဖို့အတွက် ပို့ချင်တဲ့စာ သို့မဟုတ် မီဒီယာကို Reply ပြန်ပြီးမှ သုံးပေးပါ ဘရို။"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^[/.]premode\s+(\d+|off)'))
async def set_global_premode(event):
    global GLOBAL_PREMODE_THRESHOLD
    # Owner သို့မဟုတ် Group Admin ဖြစ်မှ သုံးခွင့်ပေးမယ်
    if event.sender_id != OWNER_ID:
        if not await check_admin(event.chat_id, event.sender_id): return
        
    input_val = event.pattern_match.group(1).lower().strip()
    
    if input_val == "off":
        GLOBAL_PREMODE_THRESHOLD = 0
        await premode_col.update_one({"_id": "global_config"}, {"$set": {"threshold": 0}}, upsert=True)
        await event.reply(bq("👑 Global Premium Mode ကို လုံးဝ ပိတ် (OFF) လိုက်ပါပြီ။ 🔴"), parse_mode='html')
    else:
        num = int(input_val)
        if num <= 0:
            await event.reply(bq("⚠️ စာစောင်ရေတွက်က ၁ ထက်ကြီးရပါမယ် ဘရို။"))
            return
        GLOBAL_PREMODE_THRESHOLD = num
        await premode_col.update_one({"_id": "global_config"}, {"$set": {"threshold": num}}, upsert=True)
        await event.reply(bq(f"👑 Global Premium Mode ကို စာစောင် **[{num}]** စောင်ပြည့်စနစ်နဲ့ ဖွင့်လိုက်ပါပြီ။ 🟢"), parse_mode='html')
        
# 2️⃣ SPECIFIC_GROUP ထဲက ရှိပြီးသား Premium စာတွေကို တစ်ခါတည်း အကုန်ခြစ်သိမ်းမည့် Scraper (Owner Only)
@bot1.on(events.NewMessage(pattern=r'^[/.]scrapepre'))
async def scrape_premium_messages(event):
    if event.sender_id != OWNER_ID: return
    
    await event.reply(bq("⏳ SPECIFIC_GROUP ထဲက Premium Emoji ပါတဲ့စာတွေကို စတင်ရှာဖွေပြီး Cloud Storage ထဲ သိမ်းဆည်းနေပါတယ်... (ခဏစောင့်ပေးပါ)"), parse_mode='html')
    
    collected_count = 0
    # အစောင် ၂၀၀၀ အထိ နောက်ပြန်လှန်ရှာမယ် (မင်းစိတ်ကြိုက် limit တိုးလို့ရပါတယ်)
    async for msg in bot1.iter_messages(SPECIFIC_GROUP, limit=2000):
        if msg.text and msg.entities:
            has_premium = False
            for ent in msg.entities:
                # Premium Emoji (Custom Emoji) ပါမပါ စစ်ဆေးခြင်း
                if isinstance(ent, types.MessageEntityCustomEmoji):
                    has_premium = True
                    break
            
            if has_premium:
                # DB ထဲမှာ ရှိပြီးသားစာ ဖြစ်နေရင် ထပ်မသိမ်းအောင် စစ်မယ်
                exists = await premium_talk_col.find_one({"orig_msg_id": msg.id})
                if not exists:
                    try:
                        # Storage Group ထဲကို လှမ်းသိမ်းမယ်
                        forwarded = await bot1.forward_messages(STORAGE_CHANNEL, msg)
                        # DB ထဲမှာ Storage Message ID ကို သိမ်းမယ်
                        await premium_talk_col.insert_one({
                            "orig_msg_id": msg.id,
                            "storage_msg_id": forwarded.id
                        })
                        collected_count += 1
                        await asyncio.sleep(0.6) # Telegram Flood အမိန့်မထိအောင် 0.3 စက္ကန့်စီ ခြားပြီးသိမ်းတာ
                    except Exception:
                        continue

    await event.reply(bq(f"🎉 သိမ်းဆည်းခြင်း အောင်မြင်သည်! စုစုပေါင်း Premium Emoji မက်ဆေ့ခ်ျ {collected_count} စောင်ကို DB အသစ်ထဲသို့ ထည့်သွင်းပြီးပါပြီ။ ✅"), parse_mode='html')       
# ====================================================================================
# 🆔 COMBINED IDENTITY MATRIX SYSTEM (User & Group ID Multi-Locator)
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^[/.]id'))
async def get_identity_matrix_handler(event):
    chat_id = event.chat_id
    is_private = event.is_private
    reply = await event.get_reply_message()
    
    # Reply ရှိမရှိအပေါ် မူတည်ပြီး Target User အချက်အလက်ကို ရယူခြင်း
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

    # Chat Type အပေါ် မူတည်ပြီး Group ID အပိုင်းကို တည်ဆောက်ခြင်း
    if not is_private:
        try:
            chat = await event.get_chat()
            group_title = escape_html(chat.title)
        except Exception:
            group_title = "Unknown Sector"
            
        group_section = (
            f"📍 <b>Group:</b> {group_title}\n"
            f"🌐 <b>Chat ID:</b> <code>{chat_id}</code>\n"
        )
    else:
        group_section = f"📍 <b>Sector:</b> <code>Private Chat (No Group ID)</code>\n"

    # 🌌 Premium Cyber Matrix Layout Design
    matrix_text = (
        f"🌌 <b>𝙄𝘿 𝙈𝘼𝙏𝙍𝙄𝙓</b>\n"
        f"👤 <b>{user_type}:</b> {mention}\n"
        f"🆔 <b>User ID:</b> <code>{target_id}</code>\n\n"
        f"{group_section}"
    )

    try:
        await event.respond(bq(matrix_text), parse_mode='html')
    except Exception as e:
        print(f"Identity Matrix Error: {e}")
# ====================================================================================
# 🛡️ ADVANCED MODERATION CONSOLE (Mute, Unmute, Ban, Unban, Kick + Interactive Button)
# ====================================================================================

# 🔧 Helper function: Target User ကို Reply သို့မဟုတ် ID/Username ကနေ ဆွဲထုတ်ခြင်း
async def get_target_user(event, args):
    reply = await event.get_reply_message()
    if reply: return reply.sender
    if args:
        try:
            target = args.strip()
            return await bot1.get_entity(int(target) if target.lstrip('-').isdigit() else target)
        except Exception: return None
    return None

# 🔇 1. MUTE COMMAND (With Live Unmute Inline Button)
@bot1.on(events.NewMessage(pattern=r'^/mute(?:@\w+)?(?:\s+(.*))?'))
async def mute_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    target_user = await get_target_user(event, event.pattern_match.group(1))
    if not target_user: return

    try:
        # Message ပို့ခွင့် ပိတ်ပင်ခြင်း
        await bot1.edit_permissions(event.chat_id, target_user.id, send_messages=False)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User'))}</a>"
        
        mute_text = (
            f"🌌 <b>𝙈𝙐𝙏𝙀 𝙊𝙋𝙀𝙍𝘼𝙏𝙄𝙊𝙉</b>\n"
            f"🛸 ───────────────────\n"
            f"🔇 <b>Target:</b> {mention}\n"
            f"🆔 <b>User ID:</b> <code>{target_user.id}</code>\n"
            f"⚡ <b>Status:</b> <code>Muted(မြုပြီး)</code>"
        )
        
        # Unmute လုပ်နိုင်မည့် Interactive Inline Button တပ်ဆင်ခြင်း
        inline_buttons = [[Button.inline("Unmute? 🔊", data=f"inline_unmute_{target_user.id}")]]
        await event.respond(bq(mute_text), parse_mode='html', buttons=inline_buttons)
    except Exception as e:
        print(f"Mute Error: {e}")

# 🔊 2. UNMUTE COMMAND
@bot1.on(events.NewMessage(pattern=r'^/unmute(?:@\w+)?(?:\s+(.*))?'))
async def unmute_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    target_user = await get_target_user(event, event.pattern_match.group(1))
    if not target_user: return

    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, send_messages=True)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User'))}</a>"
        
        unmute_text = (
            f"🌌 <b>𝙐block𝙐𝙉𝙈𝙐𝙏𝙀 𝙊𝙋𝙀𝙍𝘼𝙏𝙄𝙊𝙉</b>\n"
            f"🔊 <b>Target:</b> {mention}\n"
            f"🆔 <b>User ID:</b> <code>{target_user.id}</code>\n"
            f"⚡ <b>Status:</b> <code>Voice Restored / Cleared</code>"
        )
        await event.respond(bq(unmute_text), parse_mode='html')
    except Exception as e:
        print(f"Unmute Error: {e}")

# 🚫 3. BAN COMMAND
@bot1.on(events.NewMessage(pattern=r'^/ban(?:@\w+)?(?:\s+(.*))?'))
async def ban_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    target_user = await get_target_user(event, event.pattern_match.group(1))
    if not target_user: return

    try:
        # view_messages=False သည် Group ထဲမှ အပြီးထုတ်ပြီး Ban လိုက်ခြင်းဖြစ်သည်
        await bot1.edit_permissions(event.chat_id, target_user.id, view_messages=False)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User'))}</a>"
        
        ban_text = (
            f"🌌 <b>𝘽𝘼𝙉 𝙊𝙋𝙀𝙍𝘼𝙏𝙄𝙊𝙉</b>\n"
            f"🚫 <b>Target:</b> {mention}\n"
            f"🆔 <b>User ID:</b> <code>{target_user.id}</code>\n"
            f"⚡ <b>Status:</b> <code>Exiled / Perm-Banned(ဘန်းပစ်လိုက်ရှုပ်တယ်)</code>"
        )
        await event.respond(bq(ban_text), parse_mode='html')
    except Exception as e:
        print(f"Ban Error: {e}")

# ✅ 4. UNBAN COMMAND
@bot1.on(events.NewMessage(pattern=r'^/unban(?:@\w+)?(?:\s+(.*))?'))
async def unban_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    target_user = await get_target_user(event, event.pattern_match.group(1))
    if not target_user: return

    try:
        # Ban ဖြုတ်ပေးပြီး ပြန်ဝင်ခွင့်ပေးခြင်း
        await bot1.edit_permissions(event.chat_id, target_user.id, view_messages=True)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User'))}</a>"
        
        unban_text = (
            f"🌌 <b>𝙐𝙉𝘽𝘼𝙉 𝙊𝙋𝙀𝙍𝘼𝙏𝙄𝙊𝙉</b>\n"
            f"✅ <b>Target:</b> {mention}\n"
            f"🆔 <b>User ID:</b> <code>{target_user.id}</code>\n"
            f"⚡ <b>Status:</b> <code>Ban Lifted / Allowed to Join</code>"
        )
        await event.respond(bq(unban_text), parse_mode='html')
    except Exception as e:
        print(f"Unban Error: {e}")

# 🥾 5. KICK COMMAND
@bot1.on(events.NewMessage(pattern=r'^/kick(?:@\w+)?(?:\s+(.*))?'))
async def kick_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    target_user = await get_target_user(event, event.pattern_match.group(1))
    if not target_user: return

    try:
        # Group ထဲမှ ကန်ထုတ်ရန် Ban ပြီး ချက်ချင်း Unban ပြန်လုပ်ပေးခြင်း (တစ်ခါတည်း ပြန်ဝင်လိုက ဝင်နိုင်သည်)
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
    except Exception as e:
        print(f"Kick Error: {e}")


# ====================================================================================
# 🎛️ INLINE CALLBACK FOR QUICK UNMUTE ACTION
# ====================================================================================
@bot1.on(events.CallbackQuery(pattern=r'^inline_unmute_(\d+)'))
async def inline_unmute_callback(event):
    # ခလုတ်ကို နှိပ်လိုက်သောသူသည် Admin ဟုတ်မဟုတ် အရင်စစ်ဆေးခြင်း
    if not await check_ban_rights(event.chat_id, event.sender_id):
        return await event.answer("⚠️ You are not authorized to use this console!", alert=True)

    target_id = int(event.pattern_match.group(1))
    
    try:
        # Unmute လုပ်ခြင်း
        await bot1.edit_permissions(event.chat_id, target_id, send_messages=True)
        
        # User အချက်အလက် ပြန်ဆွဲယူခြင်း
        try:
            target_user = await bot1.get_entity(target_id)
            name = escape_html(getattr(target_user, 'first_name', 'User'))
        except:
            name = "User"
            
        mention = f"<a href='tg://user?id={target_id}'>{name}</a>"
        
        # မူရင်း Mute စာသားကို Unmute အောင်မြင်ကြောင်း Live ပြောင်းလဲ (Edit) ပေးလိုက်ခြင်း
        updated_text = (
            f"🌌 <b>𝙈𝙐𝙏𝙀 𝙎𝙔𝙎𝙏𝙀𝙈 𝙐𝙋𝘿𝘼𝙏𝙀</b>\n"
            f"🔊 {mention} has been <b>Unmuted</b> via administrative console.\n"
            f"⚡ <b>Status:</b> <code>Restrictions Disintegrated</code>"
        )
        
        await event.edit(bq(updated_text), parse_mode='html', buttons=None) # ခလုတ်ကိုပါ တစ်ခါတည်း ဖြုတ်ပစ်မည်
        await event.answer("User unmuted successfully! 🔊", alert=False)
        
    except Exception as e:
        await event.answer(f"Action Failed: {e}", alert=True)
# ====================================================================================
# 📣 COMPACT ADMIN TAG SYSTEM (Horizontal Grid Layout & Full Name Sync)
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/adm(?:\s+(.*))?'))
async def tag_admins(event):
    if event.is_private: return
    if not await check_admin(event.chat_id, event.sender_id): return
    
    # ရိုက်လိုက်သော စာသား သို့မဟုတ် Default စာသား
    text = event.pattern_match.group(1) or "Adminတို့ရေ ခေါ်နေပါတယ်🤍"
    
    try:
        # Group ထဲရှိ လက်ရှိ Admin list ကို Live ဆွဲယူခြင်း (အမြဲတမ်း Auto-Update ဖြစ်သည်)
        admins = await bot1.get_participants(event.chat_id, filter=ChannelParticipantsAdmins)
        
        admin_mentions = []
        # Admin တစ်ဦးစီရဲ့ နောက်မှာ ထည့်သွင်းမည့် Cyber Emojis များ
        cyber_emojis = ["⚡", "🔮", "💎", "✨", "🔥", "🛸", "🛡️", "🪐", "🌌", "🦾"]
        
        for index, a in enumerate(admins):
            if a.bot or getattr(a, 'deleted', False): continue
            
            # 🔄 Admin တစ်ဦးစီ၏ First Name နှင့် Last Name ကို ပေါင်းပြီး Full Name တည်ဆောက်ခြင်း
            first = a.first_name or ""
            last = a.last_name or ""
            full_name = f"{first} {last}".strip() or "Admin"
            
            # Emojis များကို အစီအစဉ်အလိုက် တစ်ယောက်တစ်မျိုးစီ ခွဲဝေပေးခြင်း
            emoji = cyber_emojis[index % len(cyber_emojis)]
            
            # Full Name ဖြင့် Mention ပြုလုပ်ခြင်း
            mention = f"<a href='tg://user?id={a.id}'><b>{escape_html(full_name)}</b></a> {emoji}"
            admin_mentions.append(mention)
        
        # 🔗 အောက်ကို အတန်းလိုက်ကြီး မဆင်းဘဲ ဘေးချင်းကပ်လျက် စီရန်အတွက် Bullet ( • ) ဖြင့် လှပစွာ ဆက်ပေးခြင်း
        compact_admin_list = "  •  ".join(admin_mentions)
        
        # 🌌 English Cyber Font & Galactic Layout Design
        adm_signal_text = (
            f"📢 <b>Broadcast:</b> <code>{escape_html(text)}</code>\n\n"
            f"🌌 <b>𝘼𝘿𝙈𝙄𝙉 𝘼𝙎𝙎𝙀𝙈𝘽𝙇𝙔 𝙎𝙄𝙂𝙉𝘼𝙇</b>\n"
            f"🛡️ <b>Active Officers:</b>\n"
            f"{compact_admin_list}"
        )
        
        await event.respond(bq(adm_signal_text), parse_mode='html')
    except Exception as e:
        print(f"Admin Tag System Error: {e}")

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
# 📢 GLOBAL BROADCAST SYSTEM (Modern Cyber Layout & HTML Parse Verified)
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/ပို့(?:@\w+)?(?:\s+(.*))?'))
async def broadcast(event):
    if event.sender_id != OWNER_ID: return
    reply_msg = await event.get_reply_message()
    command_text = event.pattern_match.group(1)
    
    if not reply_msg and not command_text: return
    success, fail = 0, 0
    
    # 🌌 စတင်ကြောင်းပြသမည့် Alert (English Cyber Font + HTML Parse Mode)
    init_text = (
        f"🌌 <b>𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏 𝙎𝙔𝙎𝙏𝙀𝙈 𝙄𝙉𝙄𝙏𝙄𝘼𝙏𝙀𝘿</b>\n"
        f"⚡ <b>Transmission:</b> <code>Deploying signals to all sectors...</code>"
    )
    status_msg = await event.respond(bq(init_text), parse_mode='html')
    
    groups = await groups_col.find().to_list(length=None)

    for g in groups:
        try:
            if reply_msg: 
                # မူရင်း Message အတိုင်း ပုံစံမပျက် Forward လုပ်ပေးခြင်း (forward_messages တွင် parse_mode ထည့်ရန်မလိုပါ)
                await bot1.forward_messages(g['chat_id'], reply_msg)
            else: 
                # Broadcast စာသားထဲတွင် Bold/Italic HTML Tag များ သုံးနိုင်ရန် parse_mode='html' ကို သေချာထည့်သွင်းထားသည်
                await bot1.send_message(g['chat_id'], command_text, parse_mode='html')
            success += 10
            await asyncio.sleep(0.5) 
        except Exception:
            fail += 1
            
    # 🌌 Broadcast ပို့ဆောင်ပြီးစီးကြောင်း ပြသသည့် Final Report (HTML Parse Mode ဖြင့် စာလုံးအလှများ အလုပ်လုပ်စေသည်)
    report_text = (
        f"🌌 <b>𝘽𝙍𝙊𝘼𝘿𝘾𝘼𝙎𝙏 𝙏𝙍𝘼𝙉𝙎𝙈𝙄𝙎𝙎𝙄𝙊𝙉 𝘾𝙊𝙈𝙋𝙇𝙀𝙏𝙀𝘿</b>\n"
        f"✅ <b>Success Sectors:</b> <code>{success}</code>\n"
        f"❌ <b>Failed Sectors:</b>  <code>{fail}</code>"
    )
    await status_msg.edit(bq(report_text), parse_mode='html')
    
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
                await warn_msg.edit(bq(msg_template.format(type=cmd_type, mention=mention) + f"\n\n{i} စက္ကန့်အတွင်း ပျောက်ကွယ်သွားပါမယ်။"), parse_mode='html')
            return 
        except: pass

    if text:
        text_lower = text.lower()  # စာလုံးအသေးအကြီး အကုန်မိစေရန် lower ပြောင်းခြင်း
        BIO_KEYWORDS = [
            "bio", "b i o", "biolink", "bio-link", "b-i-o", "tg bio", 
            "ဘိုင်အို", "ဘိုင်-အို", "ဘိုင်-o", "ဘီအိုင်အို", "ဘိုင်အိုလင့်", "ဘိုင်အိုလင့်ခ်"
        ]

        if any(key in text_lower for key in BIO_KEYWORDS) and not await check_admin(chat_id, sender_id):
            try:
                await event.delete()
                
                # ပို့သူကို Tag ရန် နာမည်ထုတ်ယူခြင်း
                sender = await event.get_sender()
                first_name = sender.first_name if sender else "User"
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(first_name)}</a>"
                
                # English Font အလှနှင့် လန်းဆန်းသော Layout ဒီဇိုင်း
                warn_text = (
                    f"⚠️ <b>𝘽𝙄𝙊 𝙎𝙔𝙎𝙏𝙀𝙈 𝘼𝙇𝙀𝙍𝙏</b>\n"
                    f"Hey {mention}, discussing or sharing unauthorized <b>Biolink</b> content is restricted here.\n\n"
                    f"⚡ <b>Status:</b> <blockquote expandable>Message Disintegrated 🗑️</blockquote>"
                )
             
                # Reply စာကို မဖျက်ဘဲ ချန်ထားမည်
                await event.respond(bq(warn_text), parse_mode='html')
                return 
            except Exception as e:
                print(f"Bio Filter Error: {e}")

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
                await event.respond(bq(f"ဟိတ်.. {mention} link မပို့နဲ့ bro/sis မင်း link ကို ငါဖျက်လိုက်ပြီ"), parse_mode='html')
            except: pass
# ====================================================================================
# 🎵 ADVANCED MULTIMEDIA PLAY & TRACKING SYSTEM (Per-User Multi-Session Matrix)
# ====================================================================================
# Data Structure: {(chat_id, user_id): {"msg_id": msg_id, "songs": [...]}}
play_blocks = {}  

@bot1.on(events.NewMessage(pattern=r'^/play(?:\s+(.*))?'))
async def play_response(event):
    if event.is_private: return
    song_title = event.pattern_match.group(1)
    
    if not song_title: 
        return await event.reply(bq("🛸 Please provide a song title!\nExample: <code>/play Faded</code>"), parse_mode='html')

    chat_id = event.chat_id
    sender = await event.get_sender()
    user_id = event.sender_id
    
    if sender and getattr(sender, 'username', None):
        mention = f"@{sender.username}"
    else:
        first_name = getattr(sender, 'first_name', None) or "User"
        mention = f"<a href='tg://user?id={user_id}'>{escape_html(first_name)}</a>"

    # 🔑 Unique Tuple Key: Group ID နဲ့ User ID ကို ပေါင်းစပ်ပြီး Session ခွဲထုတ်ခြင်း (လုံးဝ မရောစေရပါ)
    session_key = (chat_id, user_id)

    if session_key not in play_blocks:
        play_blocks[session_key] = {"msg_id": None, "songs": []}

    current_song_entry = {"title": song_title.strip(), "by": mention}
    play_blocks[session_key]["songs"].append(current_song_entry)

    playlist_text = ""
    for index, s in enumerate(play_blocks[session_key]["songs"], start=1):
        playlist_text += f"{index} 💿 <code>/play {escape_html(s['title'])}</code> — {s['by']}\n"

    try:
        owner_entity = await bot1.get_entity(OWNER_ID)
        first = owner_entity.first_name or ""
        last = owner_entity.last_name or ""
        owner_fullname = f"{first} {last}".strip()
        owner_fullname = escape_html(owner_fullname)
    except Exception:
        owner_fullname = "Khant Thu Rain" 

    msg_template = (
        f"🌌 <b>{owner_fullname} Multimedia System</b>\n"
        f"💿 <b>Now Spinning:</b> <code>{escape_html(song_title.strip())}</code>\n"
        f"✨ <b>Requested By:</b> {mention}\n\n"
        f"💎 <b>Your Recent Playlist (Max 30):</b>\n"
        f"{playlist_text}"
        f"💡 <i>ဒါက မင်း ဖွင့်တဲ့ song 30 ပုဒ်အထိ သိမ်းထားပေးပြီး /play xxxကို ထိတာနဲ့ copyဖြစ်ပြီး နောက်ကျ အဆင်သင့်နားထောင်နိုင်ရန် အတွက် မင်းသီချင်းတွေပြီးတဲ့အခါဒါကိုsaved message မှာ သိမ်းထားလိုက်</i>"
    )

    # 🎛️ Inline Buttons Setup (User ID ကို Callback Data ထဲ ထည့်သွင်းထားသည်)
    inline_buttons = [
        [Button.url("Join Our Community 🌐", "https://t.me/Comeback_BoD")],
        [Button.inline("songsစုထားမယ် နှိပ် 📥", data=f"save_pl_{user_id}")]
    ]

    try:
        last_msg_id = play_blocks[session_key]["msg_id"]
        
        if last_msg_id:
            try:
                await bot1.edit_message(
                    entity=chat_id,
                    message=last_msg_id,
                    text=bq(msg_template),
                    parse_mode='html',
                    buttons=inline_buttons
                )
                try: await event.delete()
                except: pass
            except Exception:
                last_msg_id = None

        if not last_msg_id:
            new_msg = await event.respond(
                bq(msg_template), 
                parse_mode='html', 
                buttons=inline_buttons
            )
            play_blocks[session_key]["msg_id"] = new_msg.id
            try: await event.delete()
            except: pass

        if len(play_blocks[session_key]["songs"]) >= 30:
            play_blocks[session_key] = {"msg_id": None, "songs": []}

    except Exception as e:
        print(f"Multimedia Play System Error: {e}")

# ====================================================================================
# 📥 INLINE CALLBACK FOR FREEZING & SAVING THE PLAYLIST (Per-User Validation)
# ====================================================================================
@bot1.on(events.CallbackQuery(pattern=r'^save_pl_(\d+)$'))
async def close_playlist_callback(event):
    chat_id = event.chat_id
    clicker_id = event.sender_id
    target_user_id = int(event.pattern_match.group(1))
    
    # 🛡️ Anti-Interference Security: မိမိဖွင့်ထားတဲ့ Playlist ကိုပဲ ပိတ်ခွင့်ရှိစေရန် စစ်ဆေးခြင်း
    if clicker_id != target_user_id:
        return await event.answer("❌ ဒါက မင်းရဲ့ Playlist မဟုတ်ပါဘူး! မင်းကိုယ်ပိုင် /play စာရင်းကိုပဲ ပိတ်လို့ရပါမယ်။", alert=True)
        
    session_key = (chat_id, target_user_id)
    
    try:
        msg = await event.get_message()
        current_text = msg.text if msg else ""
        
        frozen_buttons = [
            [Button.url("Join Our Community 🌐", "https://t.me/Comeback_BoD")],
            [Button.inline("🔒 Playlist Locked & Ready to Save", data="playlist_frozen_done")]
        ]
        
        if current_text:
            await event.edit(
                text=current_text,
                parse_mode='html',
                buttons=frozen_buttons
            )
        
        # 🔄 ထို User ရဲ့ Session ကို Memory ပေါ်ကနေ အပြီးသတ် ဖျက်ထုတ်ပေးခြင်း (RAM လုံးဝမပွစေရန်)
        if session_key in play_blocks:
            del play_blocks[session_key]
            
        await event.answer(
            "🔒 Your Playlist Session Closed!\n\nဒီသီချင်းစာရင်းကို Saved Messages ထဲ Forward လုပ်ပြီး အလွယ်တကူ သိမ်းဆည်းလိုက်ပါ Chief!", 
            alert=True
        )
    except Exception as e:
        print(f"Callback Error: {e}")
        await event.answer("Error closing session.", alert=False)

@bot1.on(events.CallbackQuery(pattern=r'^playlist_frozen_done$'))
async def playlist_frozen_done_callback(event):
    await event.answer("ဒီ Playlist ကို ပိတ်ပြီးပါပြီ။ Saved Messages ထဲ Forward လုပ်ပြီး သိမ်းနိုင်ပါတယ်ဗျာ။", alert=False)


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

# ၂။ 🎯 FILTER ပြန်ထုတ်ပေးသည့်စနစ် (လူတွေ စကားလုံး လာရိုက်တဲ့အပိုင်း)
@bot1.on(events.NewMessage(incoming=True))
async def trigger_custom_filters(event):
    # Command တွေဆိုရင် ကျော်သွားမယ်
    if event.is_private or not event.text or event.text.startswith(('/', '.', '@')): return
    
    user_text = event.text.lower().strip()
    
    # DB ထဲမှာ ရိုက်လိုက်တဲ့ စာလုံးနဲ့ ကိုက်ညီတဲ့ Filter ရှိလား ရှာမယ်
    filter_doc = await custom_filters_col.find_one({"keyword": user_text})
    
    if filter_doc and filter_doc.get("type") == "storage_msg":
        msg_id = filter_doc.get("msg_id")
        try:
            # Storage Group ထဲက မူရင်း မက်ဆေ့ခ်ျကို ID နဲ့ လှမ်းဆွဲထုတ်တယ်
            stored_msg = await bot1.get_messages(STORAGE_CHANNEL, ids=msg_id)
            if stored_msg:
                # Group ထဲကို မူရင်းအတိုင်း တ nhất ပုံစံတူ ကူးပြီး ပြန်ဖြေပေးတာ (Forwarded From စာတန်း မပေါ်ဘူး)
                await event.reply(stored_msg)
        except Exception as e:
            print(f"Filter Send Error: {e}")
            
@bot1.on(events.NewMessage(incoming=True))
async def premium_mode_counter_handler(event):
    global GLOBAL_PREMODE_THRESHOLD, chat_counters
    
    # ၁။ Private Chat တွေကို ကျော်မယ်၊ Sender မရှိရင် ကျော်မယ်
    if event.is_private or not event.sender: return
    
    # ၂။ 🤖 Bot တွေ ပို့တဲ့စာဆိုရင် (မင်းရဲ့ Bot ရော၊ အခြား Bot ရော) လုံးဝ မရေတွက်ဘူး ကျော်မယ်
    if getattr(event.sender, 'bot', False): return
    
    # ၃။ / နဲ့စတဲ့ Command တွေကိုလည်း ရေတွက်ခြင်းထဲ မထည့်ဘူး ကျော်မယ်
    if event.text and event.text.startswith(('/', '.', '@')): return
    
    # Bot စတက်တက်ချင်း DB ထဲက Setting ကို တစ်ကြိမ်ပဲ လှမ်းဆွဲယူမယ် (Optimization)
    if GLOBAL_PREMODE_THRESHOLD is None:
        config = await premode_col.find_one({"_id": "global_config"})
        GLOBAL_PREMODE_THRESHOLD = config.get("threshold", 0) if config else 0
        
    # ၄။ Premium Mode က 0 (Off) ဖြစ်နေရင် ဘာမှမလုပ်ဘဲ ထွက်မယ်
    if GLOBAL_PREMODE_THRESHOLD == 0: return
    
    chat_id = event.chat_id
    
    # ၅။ Group အလိုက် စာစောင်အရေအတွက်ကို RAM ပေါ်မှာ လှမ်းတိုးမယ်
    if chat_id not in chat_counters:
        chat_counters[chat_id] = 0
    chat_counters[chat_id] += 1
    
    # ၆။ သတ်မှတ်ထားတဲ့ စာစောင်အရေအတွက် ပြည့်သွားပြီဆိုရင်
    if chat_counters[chat_id] >= GLOBAL_PREMODE_THRESHOLD:
        chat_counters[chat_id] = 0  # ရေတွက်မှုကို 0 ပြန်ချမယ်
        
        # Scrape လုပ်ထားတဲ့ Premium DB ထဲကနေ စာတွေကို Random တစ်စောင် နှိုက်မယ်
        pipeline = [{"$sample": {"size": 1}}]
        cursor = premium_talk_col.aggregate(pipeline)
        premium_docs = await cursor.to_list(length=1)
        
        if premium_docs:
            storage_msg_id = premium_docs[0]["storage_msg_id"]
            try:
                # Storage Group ထဲက မူရင်း Premium Emoji စာကို ID နဲ့ လှမ်းယူတယ်
                stored_msg = await bot1.get_messages(STORAGE_CHANNEL, ids=storage_msg_id)
                if stored_msg:
                    # 🎲 ၅၀/၅၀ စပ်ပြီး လူကို Reply ပြန်မလား၊ သူ့ဘာသာသူ အလွတ်ပို့မလား ရွေးတာ
                    action = random.choice(["reply", "send"])
                    
                    if action == "reply":
                        # နောက်ဆုံး စာပြည့်အောင် ရိုက်လိုက်တဲ့လူကို Reply ပြန်မယ်
                        await event.reply(stored_msg)
                    else:
                        # ဘာမှ Reply မပြန်ဘဲ Group ထဲကို သူ့ဘာသာသူ standalone ပို့ချလိုက်မယ်
                        await bot1.send_message(chat_id, stored_msg)
            except Exception as e:
                print(f"Premium Send Error: {e}")
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
# ====================================================================================
# 🎙️ GLOBAL VOCAL PROTOCOL CONTROLLER (AI Chat Engagement Switches)
# ====================================================================================

@bot1.on(events.NewMessage(pattern=r'^စကားဝင်ပြော$'))
async def turn_on_talking(event):
    # Safety Matrix Check: Owner နှင့် သတ်မှတ်ထားသော Control Group မှ ဖြစ်ရမည်
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    
    global GLOBAL_TALK
    GLOBAL_TALK = True
    
    on_text = (
        f"🌌 <b>𝙑𝙊𝘾𝘼𝙇 𝙋𝙍𝙊𝙏𝙊𝘾𝙊𝙇: 𝘼𝘾𝙏𝙄𝙑𝘼𝙏𝙀𝘿</b>\n"
        f"🔊 Smart Reply Engine ကို Sector အားလုံးမှာ <b>စကားဝင်ပြောဖို့</b> အသက်သွင်းလိုက်ပါပြီ Chief!"
    )
    await event.reply(bq(on_text), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^မပြောနဲ့တော့$'))
async def turn_off_talking(event):
    # Safety Matrix Check: Owner နှင့် သတ်မှတ်ထားသော Control Group မှ ဖြစ်ရမည်
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    
    global GLOBAL_TALK
    GLOBAL_TALK = False
    
    off_text = (
        f"🔇 Smart Reply Engine ကို Absolute <b>Stealth Mode</b> ပြောင်းပြီး စကားပိတ်လိုက်ပါပြီ!"
    )
    await event.reply(bq(off_text), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^(ရပ်|အပစ်ရပ်)$'))
async def stop_actions(event):
    if not await is_allowed(event.sender_id): return
    shoot_tasks[event.chat_id] = False
    if event.chat_id in tracking_targets: del tracking_targets[event.chat_id]
    await event.reply(bq("အပစ်ရပ်စဲလိုက်ပြီ။"))

# ====================================================================================
# 💀 [DARK PASSENGER WATCHER LOGIC - UPGRADED WITH VISUAL MATRIX]
# ====================================================================================
@bot1.on(events.NewMessage())
async def dark_passenger_watcher(event):
    chat_id = event.chat_id
    sender_id = event.sender_id
    
    if chat_id in dark_passenger_targets and sender_id == dark_passenger_targets[chat_id]:
        if event.text and not event.text.startswith(('/', '.', 'မှတ်')):
            try:
                # 1. Target ရဲ့ Message ကို ချက်ချင်း ဖျက်ဆီးပစ်ခြင်း
                await event.delete()
                
                # Mention Network တည်ဆောက်ခြင်း
                sender = await event.get_sender()
                first_name = sender.first_name if sender else "Subject"
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(first_name)}</a>"
                
                # 2. 🤫 50 PSYCHO-CYBER INSULTS (MORGAN'S VISUAL FILTER MATRIX)
                insults = [
                    f"🤫 <b>THE ILLUSION OF VOICE</b> 🤫\n\nMorgan lets your pathetic fingers click those keys, {mention}, but he owns the void. You are screaming into a vacuum where no one can hear or see you.",
                    f"💀 <b>MORGAN'S ISOLATION CHAMBER</b> 💀\n\nGo ahead and type another essay, {mention}. Morgan allows the keystroke but incinerates the output. You are talking to yourself in the dark.",
                    f"🚨 <b>INVISIBLE ANOMALY DETECTED</b> 🚨\n\nMorgan grants you permission to think you are participating, {mention}. In reality, your words are dead before they hit the screen. Invisible dust.",
                    f"🩸 <b>THE DARK PASSENGER'S PLAYTHING</b> 🩸\n\nKeep typing, {mention}. It amuses Morgan to watch you waste your energy on messages that are instantly filtered into absolute nothingness.",
                    f"🔮 <b>GHOST IN THE MAINFRAME</b> 🔮\n\nYou have the illusion of speech, {mention}, but Morgan holds the strings. Your text is a phantom that vanishes before anyone else can even glimpse it.",
                    f"🪐 <b>THE COLD VOID OF MORGAN</b> 🪐\n\nMorgan likes to keep you on a tight leash, {mention}. You click 'send', he clicks 'erase'. Nobody sees your existence here.",
                    f"🦾 <b>GRID OVERRIDE ACTIVE</b> 🦾\n\nYour profile is just a ghost status now, {mention}. Morgan lets you type your garbage, but your thoughts are strictly quarantined from human eyes.",
                    f"🔥 <b>THE VAPOR MATRIX</b> 🔥\n\nAre you still trying, {mention}? Morgan allows the digital signal to leave your phone, but he traps it in his private incinerator. Zero visibility.",
                    f"🤫 <b>THE SILENT TREATMENT</b> 🤫\n\nYou are on Morgan's table now, {mention}. He lets your mind run wild, but he blinds the entire group from seeing your pathetic words.",
                    f"⚠️ <b>SYSTEM SHADOW BAN PROTOCOL</b> ⚠️\n\nMorgan is the architect of your digital graveyard, {mention}. Type all you want; your voice is trapped inside his visual filter forever.",
                    f"💀 <b>ABSOLUTE CENSORSHIP MATRIX</b> 💀\n\nIt’s pathetic watching you tap your screen, {mention}. Morgan lets you press send, but he has stripped away your right to be seen.",
                    f"🩸 <b>MORGAN'S VISUAL SUFFOCATION</b> 🩸\n\nYou are gasping for attention, {mention}. Morgan lets you breathe, but he blocks your voice from reaching a single soul in this sector.",
                    f"🚨 <b>THE PATHETIC ECLIPSE</b> 🚨\n\nMorgan has thrown a black cloak over your entire profile, {mention}. Type your little heart out; you are a permanent ghost.",
                    f"🔮 <b>SHADOW DOMAIN UNDER CONTROL</b> 🔮\n\nYour chat privileges are an illusion created by Morgan, {mention}. He lets you type just to watch you shout into an empty abyss.",
                    f"🪐 <b>DIGITAL GHOST PROTOCOL</b> 🪐\n\nNo one is ignoring you, {mention}—they literally cannot see you. Morgan has erased your presence while letting you keep your keyboard.",
                    f"🦾 <b>THE SILENT SLAB</b> 🦾\n\nMorgan has wrapped plastic around your digital throat, {mention}. Type your complaints, but the mainframe will never render them for others.",
                    f"🔥 <b>THE INCINERATION LAYER</b> 🔥\n\nMorgan is playing with your mind, {mention}. He lets you feel like you are typing, but your messages are vaporized at the gateway.",
                    f"🤫 <b>THE VOID WATCHER</b> 🤫\n\nMorgan is watching you click-clack those buttons, {mention}. He smiles because he knows your words will never reach another human eye.",
                    f"⚠️ <b>SOVEREIGN BLIND ZONE</b> ⚠️\n\nYou have entered Morgan’s blind spot, {mention}. He controls your visibility. You are talking to a brick wall that deletes your data.",
                    f"💀 <b>DEATH OF AN ECO</b> 💀\n\nYour echo has been cut short, {mention}. Morgan lets the input happen, but locks the output in his private dark room.",
                    f"🩸 <b>THE DARK PASSENGER FILTER</b> 🩸\n Every single character you type passes through Morgan’s scalpel first, {mention}. He dissects it, removes the visibility, and leaves you in total isolation.",
                    f"🚨 <b>THE ILLUSION OF PERSISTENCE</b> 🚨\n\nYou think you’re making an impact, {mention}? Morgan is letting you type just to feed you the false hope of speech. You are invisible.",
                    f"🔮 <b>THE BLACKBOX QUARANTINE</b> 🔮\n\nMorgan has put your profile in a soundproof digital cage, {mention}. Scream, type, yell—your data belongs to his private trash bin.",
                    f"🪐 <b>COGNITIVE SILENCE MATRIX</b> 🪐\n\nMorgan allows your text to exist only in your own deluded mind, {mention}. To the rest of this group, you are dead air.",
                    f"🦾 <b>EXILE IN PLAIN SIGHT</b> 🦾\n\nYou are typing in exile, {mention}. Morgan dictates what gets seen, and he decided your words are toxic garbage that needs to remain unseen.",
                    f"🔥 <b>THE STATIC DISCHARGE</b> 🔥\n\nYour chat data is just white noise to Morgan, {mention}. He lets your keyboard function, but your messages are filtered into oblivion instantly.",
                    f"🤫 <b>THE MASTER OF STRINGS</b> 🤫\n\nMorgan is pulling your strings, {mention}. He gives you the freedom to type, but controls the switch that hides you from the world.",
                    f"⚠️ <b>ABSOLUTE BLINDNESS ENGAGED</b> ⚠️\n\nMorgan has blinded this sector from your existence, {mention}. Enjoy your private conversation with the deletion script.",
                    f"💀 <b>THE GRAVEYARD OF WORDS</b> 💀\n\nYour text is buried before it's even read, {mention}. Morgan lets you compile the message, then executes it in total secrecy.",
                    f"🩸 <b>MORGAN'S COLD CELL</b> 🩸\n\nYou are locked in a digital cell, {mention}. Morgan allows you to write on the walls, but no one outside this room can see your pathetic graffiti.",
                    f"🚨 <b>THE ZERO-SUM MATRIX</b> 🚨\n\nYour visibility score is absolute zero, {mention}. Morgan controls the visual grid, rendering your intense typing completely useless.",
                    f"🔮 <b>PHANTOM CHAT TRIGGER</b> 🔮\n\nMorgan is letting you play your little games, {mention}. You see your text, but to the rest of the world, your account is an empty grave.",
                    f"🪐 <b>THE INVISIBLE WRITER</b> 🪐\n\nMorgan has made you the invisible writer, {mention}. Your thoughts are intercepted and fed directly into the Dark Passenger's furnace.",
                    f"🦾 <b>SOVEREIGN MASK PROTOCOL</b> 🦾\n\nMorgan has masked your entire existence, {mention}. Keep pressing send; it changes nothing in his domain.",
                    f"🔥 <b>THE SILENT BURNING</b> 🔥\n\nMorgan likes the quiet, {mention}. He lets your phone process the message, then quietly burns it from the chat history of everyone else.",
                    f"🤫 <b>THE COMFORT OF COWARDICE</b> 🤫\n\nMorgan lets you hide behind that keyboard, {mention}, but he strips the power from your words. You are a ghost talking to shadows.",
                    f"⚠️ <b>THE QUARANTINED SUBJECT</b> ⚠️\n\nYou are a biological anomaly under Morgan’s control, {mention}. He lets you type, but ensures your infection spreads no further. Total block.",
                    f"💀 <b>DIGITAL STRANGULATION</b> 💀\n\nMorgan’s grip on your visibility is absolute, {mention}. Your text is strangled at birth. Keep typing for nothing.",
                    f"🩸 <b>THE SCALPEL EFFECT</b> 🩸\n\nMorgan uses his razor-sharp code on your account, {mention}. You type, he slices the visibility. You are non-existent.",
                    f"🚨 <b>THE FAINT SIGNAL</b> 🚨\n\nYour signal is completely dead, {mention}. Morgan allows the tactile sensation of typing, but your text hits an iron wall.",
                    f"🔮 <b>THE SECTOR SHIELD</b> 🔮\n\nMorgan has shielded this community from your nonsense, {mention}. Your messages are redirected into a digital waste dump.",
                    f"🪐 <b>THE COLD ISOLATION PROTOCOL</b> 🪐\n\nMorgan isolates his targets cleanly, {mention}. You are free to click your buttons, but your voice is permanently erased from our sight.",
                    f"🦾 <b>THE MECHANICAL SILENCER</b> 🦾\n\nMorgan has installed a mechanical silencer on your chat path, {mention}. Every word you send is trapped in his dark room.",
                    f"🔥 <b>THE ASH FIELD</b> 🔥\n\nYour sentences are turned to ash before they leave your device, {mention}. Morgan controls the grid. You are a silent ghost.",
                    f"🤫 <b>THE VOID INJECTOR</b> 🤫\n\nMorgan injects pure silence into your chat stream, {mention}. Go ahead, write a book. The void will swallow every single syllable.",
                    f"⚠️ <b>SOVEREIGN STEALTH FILTER</b> ⚠️\n\nMorgan is running an absolute stealth matrix against you, {mention}. You are shouting in a dream—no voice, no sight, no power.",
                    f"💀 <b>THE MORTUARY OF CHAT</b> 💀\n\nWelcome to the morgue of data, {mention}. Morgan is the undertaker, and your messages are the corpses that nobody will ever look at.",
                    f"🩸 <b>THE DARK PASSENGER BOUNDARY</b> 🩸\n\nMorgan has drawn a line around your profile, {mention}. You can type within your box, but your visibility will never cross his boundary.",
                    f"🚨 <b>THE ABSOLUTE ERASE MATRIX</b> 🚨\n\nMorgan owns your transmission line, {mention}. He lets your keys register the tap, but locks the message in an invisible prison.",
                    f"🔮 <b>THE LAST SILENCE</b> 🔮\n\nMorgan has the final say in this domain, {mention}. Your privilege to be seen is dead. Type into the endless black void."
                ]
                
                # 3. Mention ဖြင့် စာသားအရှည်ကြီး ပို့ပြီး တုံ့ပြန်ခြင်း
                insult_msg = await event.respond(bq(random.choice(insults)), parse_mode='html')
                
                # 4. 2 စက္ကန့် စောင့်ပြီး Bot စာကိုပါ ထပ်မံဖျက်ချခြင်း
                await asyncio.sleep(2.0)
                await insult_msg.delete()
                
            except Exception as e:
                print(f"Dark Passenger Watcher Matrix Error: {e}")


# ====================================================================================
# 🌐 FOREIGN LANGUAGE FILTER SYSTEM (English Design & Permanent Reply)
# ====================================================================================
FORBIDDEN_SCRIPTS = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u309f\u30a0-\u30ff\u0e00-\u0e7f\u0600-\u06ff\uac00-\ud7af]')

@bot1.on(events.NewMessage(chats=SPECIFIC_GROUP))
async def foreign_language_filter_handler(event):
    if not event.text or event.is_private:
        return
        
    # Owner၊ Bots များနှင့် Group Admin များကို Ignore လုပ်ခြင်း
    if event.sender_id == OWNER_ID or event.sender_id in bot_ids:
        return
    if await check_admin(event.chat_id, event.sender_id):
        return

    # တားမြစ်ထားသော ဘာသာစကား Script ပါဝင်လာပါက ဖျက်ချမည်
    if FORBIDDEN_SCRIPTS.search(event.text):
        try:
            await event.delete()
            
            sender = await event.get_sender()
            first_name = sender.first_name if sender else "User"
            mention = f"<a href='tg://user?id={event.sender_id}'>{escape_html(first_name)}</a>"
            
            warn_text = (
                f"⚠️ <b>SYSTEM SECURITY ALERT</b>\n"
                f"Hey {mention}, foreign languages/scripts are strictly prohibited in this sector.\n"
                f"Only <b>Burmese, English</b> and <b>Numbers</b> are allowed.\n\n"
                f"⚡ <b>လုပ်ဆောင်ချက်:</b> <code>မြန်မာ,Engနှစ်မျိုးသာသုံးပြီး messageပို့လို့ရသည့်အတွက် တခြားဘာသာစကား messageကိုဖျက်ချလိုက်ခြင်း</code>"
            )
            
            await event.respond(bq(warn_text), parse_mode='html')
            
        except Exception as e:
            print(f"Language Filter Error: {e}")

    
# ====================================================================================
# 🚫 CHANNEL FORWARD FILTER SYSTEM (Admin မဟုတ်သူ Channel Forward လာရင် ဖျက်သည့်စနစ်)
# ====================================================================================
@bot1.on(events.NewMessage(incoming=True))
async def channel_forward_filter_handler(event):
    if event.is_private:
        return
        
    # Owner နှင့် Bot များကို Ignore လုပ်ခြင်း
    if event.sender_id == OWNER_ID or event.sender_id in bot_ids:
        return

    # Message က Channel တစ်ခုခုကနေ Forward လာတာ ဟုတ်မဟုတ် စစ်ဆေးခြင်း
    if event.fwd_from and isinstance(event.fwd_from.from_id, types.PeerChannel):
        # စကားပြောသူက Group Admin ဟုတ်မဟုတ် စစ်ဆေးခြင်း
        is_group_admin = await check_admin(event.chat_id, event.sender_id)
        
        if not is_group_admin:
            try:
                # မူရင်း Forward Message ကို ဖျက်ချခြင်း
                await event.delete()
                
                # ပို့သူကို Tag ရန် နာမည်ထုတ်ယူခြင်း
                sender = await event.get_sender()
                first_name = sender.first_name if sender else "User"
                mention = f"<a href='tg://user?id={event.sender_id}'>{escape_html(first_name)}</a>"
                
                # English + Burmese Mix ပုံစံတိုတိုနှင့် လန်းလန်းလေး ပြောင်းလဲထားသည်
                warn_msg = (
                    f"🚫 <b>CHANNEL FORWARD NOT ALLOWED!</b>\n\n"
                    f"Hey {mention}Channel ကနေ Forward လာတဲ့ Post တွေ ပို့ခွင့်မရှိပါဘူး! <b>[Erased]</b>"
                )
                
                # Reply စာသားကို Group ထဲတွင် ကျန်ခဲ့စေရန် ဒီတိုင်း respond လုပ်ထားသည် (မဖျက်ပါ)
                await event.respond(bq(warn_msg), parse_mode='html')
                
            except Exception as e:
                print(f"Channel Forward Filter Error: {e}")

# ====================================================================================
# 👈 [ADVANCED & HIGH-SPEED] REPLY SAVE AUTO RESPONDER SYSTEM (NON-BLOCKING)
# ====================================================================================

@bot1.on(events.NewMessage(pattern=r'^/ktr(?:\s+(\d+))?$'))
async def turn_on_reply_save_match(event):
    global IS_REPLY_ACTIVE, REPLY_INTERVAL
    if event.sender_id != OWNER_ID: return
    
    IS_REPLY_ACTIVE = True
    interval_arg = event.pattern_match.group(1)
    if interval_arg:
        REPLY_INTERVAL = int(interval_arg)
        
    ktr_on_text = (
        f"🌌 <b>စာလိုက်ထောက် စကားဝင်ပြောမယ့် mood:𝘼𝘾𝙏𝙄𝙑𝘼𝙏𝙀𝘿</b>\n"
        f"🎯 Target Tracking Matrix engaged across all sectors.\n"
        f"⚡ Core system will intervene every <code>{REPLY_INTERVAL}</code> messages, Chief!"
    )
    await event.reply(bq(ktr_on_text), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/ktrr$'))
async def turn_off_reply_save_match(event):
    global IS_REPLY_ACTIVE
    if event.sender_id != OWNER_ID: return
    
    IS_REPLY_ACTIVE = False
    ktr_off_text = (
        f"⛔ System disengaged. Auto-response matrix entering offline sleep mode."
    )
    await event.reply(bq(ktr_off_text), parse_mode='html')

# 🛠️ ပြင်ဆင်ထားသော စကားပြောစနစ် (as_reply ခွဲခြားမှု Matrix)
async def processed_background_reply(event, user_text, as_reply=True):
    chat_entity = await event.get_input_chat()
    smart_reply = await fetch_optimized_smart_reply(user_text)
    
    if smart_reply:
        try:
            # Bot က စာရိုက်နေသလိုပြသမည့် အပိုင်း
            async with bot1.action(chat_entity, 'typing'):
                await asyncio.sleep(random.uniform(1.0, 2.2))
                
            if as_reply:
                # /ktr စနစ်အတွက် စာကို ရိုးရိုးပဲ Reply လိုက်ထောက်မည်
                await event.reply(smart_reply, parse_mode='html')
            else:
                # စကားဝင်ပြော (GLOBAL_TALK) အတွက် Reply မထောက်ဘဲ ရိုးရိုး Text အဖြစ်ပဲ ထွက်မည်
                await event.respond(smart_reply, parse_mode='html')
                
        except errors.rpcerrorlist.FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except Exception:
            pass


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
        user_text = event.text.strip()
        # /ktr ဖြစ်လို့ as_reply=True ပေးထားသည်
        asyncio.create_task(processed_background_reply(event, user_text, as_reply=True))

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
        user_text = event.text.strip()
        # စကားဝင်ပြောစနစ် ဖြစ်လို့ Reply မထောက်စေရန် as_reply=False ပြောင်းလဲထားသည်
        asyncio.create_task(processed_background_reply(event, user_text, as_reply=False))

# ==========================================
# 🚀 START SYSTEM
# ==========================================
async def start_system():
    threading.Thread(target=run_flask, daemon=True).start()
    print("Starting Main Bot (Sovereign System)...")
    await bot1.start(bot_token=MAIN_BOT_TOKEN)
    me_main = await bot1.get_me()
    bot_ids.append(me_main.id)
    print(f"Main Bot started successfully as @{me_main.username}")
    await bot1.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(start_system())
    except (KeyboardInterrupt, SystemExit):
        print("System Stopped Safely.")

