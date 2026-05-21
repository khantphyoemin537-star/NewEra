 io
import asyncio
import logging
import random
import os
import threading
import re
from datetime import datetime, timedelta
import pytz
from flask import Flask
from motor.motor_asyncio import AsyncIOMotorClient
from telethon.tl.types import User
from html import escape as escape_html
from telethon import TelegramClient, events, types, Button 

# --- ⚠️ ERROR ဖြစ်စေတဲ့ GetParticipants ကို ဖယ်ရှားပြီး သေချာ ပြန်ပြင်ထားတဲ့အပိုင်း ---
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
OWNER_ID = 7693106830
MONGO_URI = "mongodb+srv://khantphyoemin537_db_user:9VRKiaeZkz7rJdpz@cluster0.w6tgi8j.mongodb.net/?appName=Cluster0&tlsAllowInvalidCertificates=true"
APP_ID = 35766004
APP_HASH = 'd15b4226b81724722279bae6af69e22d'

# [Bot 1] Main Sovereign Bot
MAIN_BOT_TOKEN = "8111794244:AAG0m2GAwSBqSr6W4cAIZpxzVpE7WGNThOo"

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
admin_cache = {}          # {chat_id: set(admin_ids)}
active_rank_messages = {} #
bot_bully_tasks = {}      
shoot_tasks = {}          
tracking_targets = {} 
dark_passenger_targets = {}
learning_status = {}      
talking_status = {}       
message_counts = {}       
GLOBAL_TALK = False 
TRAINING_ENABLED_MORGAN = False      # Morgan စာသင်စနစ်အတွက် Global Status
group_msg_counters = {}
# ==========================================
# 🛠️ HELPERS
# ==========================================
def bq(text): return f"<blockquote><b>{text}</b></blockquote>"

def owner_tag():
    return f"<a href='tg://user?id={OWNER_ID}'>Khant Thu Rain</a>"

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
    """Group ရဲ့ Admin စာရင်းကို Cache ထဲမှာ Update လုပ်ပေးမည့် Function"""
    try:
        # 🎯 GetParticipants နေရာတွင် GetParticipantsRequest ဟု ပြောင်းလဲထားပါသည်
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
    """Group စတင်ခြေရာခံသည့် အချိန်မှစ၍ လက်ရှိအထိ စုစုပေါင်း စက္ကန့်ကို တွက်ချက်ခြင်း"""
    doc = await system_col.find_one({"chat_id": chat_id, "type": "uptime_tracker"})
    if not doc:
        now = datetime.now(pytz.utc)
        await system_col.insert_one({"chat_id": chat_id, "type": "uptime_tracker", "start_time": now})
        return 1
    return (datetime.now(pytz.utc) - doc["start_time"].replace(tzinfo=pytz.utc)).total_seconds()

async def generate_rank_text(chat_id, page=1):
    """ခေတ်မီဆန်းသစ်ပြီး ဆွဲဆောင်မှုရှိသော Ranking UI ကို ထုတ်လုပ်ပေးမည့် 🌟 Function"""
    cursor = rank_col.find({"chat_id": chat_id}).sort("total_messages", -1)
    all_admins = await cursor.to_list(length=100)
    
    total_tracked_seconds = await get_group_uptime(chat_id)
    
    start_idx = 0 if page == 1 else 5
    end_idx = 5 if page == 1 else 10
    display_admins = all_admins[start_idx:end_idx]
    
    text = "📊 <b>⚚𝘽𝙤𝘿𝙭 𝙈𝙤𝙧𝙜𝙖𝙣 𝙋𝘼𝙍𝘼𝘿𝙊𝙓 - ᴀᴅᴍɪɴ ʀᴀɴᴋɪɴɢ</b> 📊\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"📅 <b>Batch:</b> {datetime.now(pytz.timezone('Asia/Yangon')).strftime('%Y-%m-%d %I:%M %p')}\n"
    text += f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    medals = {1: "🥇", 2: "🥈", 3: "🥉", 4: "🌟", 5: "👑", 6: "⚡", 7: "✨", 8: "💠", 9: "💎", 10: "🔥"}
    
    if not display_admins:
        text += "<i>Ranking စာရင်း မရှိသေးပါ ခင်ဗျာ။</i>\n"
    else:
        for index, admin in enumerate(display_admins, start=start_idx + 1):
            medal = medals.get(index, "🔹")
            name = admin.get("first_name", "Unknown Admin")
            username = f"(@{admin['username']})" if admin.get("username") else ""
            
            active_sec = admin.get("active_seconds", 0)
            act_percentage = min((active_sec / total_tracked_seconds) * 100, 100.0)
            if act_percentage < 5.0 and admin.get("total_messages", 0) > 0:
                act_percentage = min(5.0 + (admin.get("total_messages", 0) * 0.1), 99.8)

            text += f"{medal} <b>{index}. {name}</b> {username}\n"
            text += f" ├─ 💬 <b>Messages:</b> <code>{admin.get('total_messages', 0):,}</code>\n"
            text += f" ├─ 🗑 <b>Deleted:</b> <code>{admin.get('deleted_messages', 0):,}</code>\n"
            text += f" └─ ⚡ <b>Presence:</b> <code>{act_percentage:.1f}%</code>\n\n"
            
    text += f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    text += f"⏳ <i>ဤစာမျက်နှာသည် ၁ မိနစ်လျှင် တစ်ကြိမ် Auto-update ဖြစ်နေပါမည်။</i>"
    return text

@bot1.on(events.NewMessage(incoming=True))
async def admin_activity_tracker(event):
    """Admin များ၏ မက်ဆေ့ချ်နှင့် အွန်လိုင်းကြာချိန် (Presence) ကို ခြေရာခံမည့် Tracker"""
    if not event.is_group or not event.sender_id:
        return
        
    chat_id = event.chat_id
    user_id = event.sender_id
    
    if chat_id not in admin_cache:
        await update_admin_cache(event.client, chat_id)
        
    if user_id not in admin_cache.get(chat_id, set()):
        return

    sender = await event.get_sender()
    first_name = sender.first_name if hasattr(sender, 'first_name') else "Admin"
    username = sender.username if hasattr(sender, 'username') else None
    
    now = datetime.now(pytz.utc)
    
    doc = await rank_col.find_one({"chat_id": chat_id, "user_id": user_id})
    if not doc:
        await rank_col.insert_one({
            "chat_id": chat_id, "user_id": user_id, "first_name": first_name, "username": username,
            "total_messages": 1, "deleted_messages": 0, "active_seconds": 60, "last_active": now
        })
    else:
        last_active = doc.get("last_active", now).replace(tzinfo=pytz.utc)
        time_diff = (now - last_active).total_seconds()
        added_seconds = time_diff if time_diff < 300 else 60
        
        await rank_col.update_one(
            {"chat_id": chat_id, "user_id": user_id},
            {
                "$inc": {"total_messages": 1, "active_seconds": int(added_seconds)},
                "$set": {"first_name": first_name, "username": username, "last_active": now}
            }
        )

@bot1.on(events.MessageDeleted())
async def admin_deletion_tracker(event):
    """Admin များ သူတစ်ပါး သို့မဟုတ် Bot စာများကို ဖျက်လိုက်ပါက ခြေရာခံမည့် Tracker"""
    if not event.chat_id:
        return
    chat_id = event.chat_id
    
    try:
        await asyncio.sleep(1) 
        async for log in bot1.iter_admin_log(chat_id, limit=1, filter=ChannelAdminLogEventsFilter(delete=True)):
            admin_id = log.user_id
            if chat_id in admin_cache and admin_id in admin_cache[chat_id]:
                await rank_col.update_one(
                    {"chat_id": chat_id, "user_id": admin_id},
                    {"$inc": {"deleted_messages": 1}}
                )
            break
    except Exception as e:
        print(f"Error tracking deletion log: {e}")

@bot1.on(events.NewMessage(pattern=r'^/rank$'))
async def show_ranking(event):
    if not event.is_group: return
    chat_id = event.chat_id
    await update_admin_cache(event.client, chat_id)
    
    rank_text = await generate_rank_text(chat_id, page=1)
    buttons = [Button.inline("ဆက်ကြည့်ရန် ➡️", data=f"rank_page_2")]
    
    msg = await event.respond(rank_text, parse_mode='html', buttons=buttons)
    active_rank_messages[msg.id] = {
        "chat_id": chat_id, "page": 1, "last_action": datetime.now()
    }

@bot1.on(events.CallbackQuery(pattern=r'^rank_page_(1|2)$'))
async def on_rank_pagination(event):
    msg_id = event.message_id
    page = int(event.pattern_match.group(1))
    
    if msg_id in active_rank_messages:
        active_rank_messages[msg_id]["page"] = page
        active_rank_messages[msg_id]["last_action"] = datetime.now()
        
    chat_id = event.chat_id
    rank_text = await generate_rank_text(chat_id, page=page)
    
    if page == 1:
        buttons = [Button.inline("ဆက်ကြည့်ရန် ➡️", data="rank_page_2")]
    else:
        buttons = [Button.inline("⬅️ ရှေ့သို့ပြန်သွားရန်", data="rank_page_1")]
        
    await event.edit(rank_text, parse_mode='html', buttons=buttons)

@bot1.on(events.NewMessage(pattern=r'^/rankadd'))
async def add_rank_messages(event):
    if not event.is_group: return
    chat_id = event.chat_id
    if event.sender_id not in admin_cache.get(chat_id, set()) and event.sender_id != OWNER_ID:
        return await event.reply("❌ ဤ Command ကို Admin များနှင့် မော်ဂန်သာ အသုံးပြုနိုင်ပါသည်။")
        
    args = event.text.split()
    target_user_id = None
    amount = 0
    
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        target_user_id = reply_msg.sender_id
        try: amount = int(args[1]) if len(args) > 1 else 0
        except ValueError: pass
    else:
        if len(args) < 3:
            return await event.reply("💡 <b>အသုံးပြုပုံ:</b>\n<code>/rankadd @username 1000</code>\n<code>/rankadd 12345678 1000</code>\nသို့မဟုတ် User ကို Reply ထောက်ပြီး <code>/rankadd 1000</code>")
            
        user_param = args[1]
        try: amount = int(args[2])
        except ValueError: return await event.reply("❌ ပေါင်းထည့်မည့် စာစောင်အရေအတွက်မှာ ကိန်းဂဏန်း ဖြစ်ရပါမည်။")
            
        if user_param.startswith("@"):
            username_clean = user_param.replace("@", "")
            doc = await rank_col.find_one({"chat_id": chat_id, "username": username_clean})
            if doc: target_user_id = doc["user_id"]
        elif user_param.isdigit():
            target_user_id = int(user_param)
        else:
            doc = await rank_col.find_one({"chat_id": chat_id, "first_name": {"$regex": user_param, "$options": "i"}})
            if doc: target_user_id = doc["user_id"]

    if not target_user_id:
        return await event.reply("❌ ၎င်း Admin အား Database စနစ်ထဲတွင် ရှာမတွေ့ပါ ခင်ဗျာ။")

    res = await rank_col.update_one(
        {"chat_id": chat_id, "user_id": target_user_id},
        {"$inc": {"total_messages": amount}}
    )
    
    if res.modified_count > 0:
        await event.reply(f"✅ သတ်မှတ်ထားသော Admin ၏ စုစုပေါင်း Message ထဲသို့ <b>{amount:,}</b> စောင် အောင်မြင်စွာ ပေါင်းထည့်ပေးပြီးပါပြီ မော်ဂန် 🔥")
    else:
        await event.reply("❌ မအောင်မြင်ပါ။ ၎င်းအသုံးပြုသူသည် ဤစနစ်တွင် Admin ဖြစ်နေရပါမည်။")

async def live_rank_updater_loop():
    """၁ မိနစ်တစ်ခါ လက်ရှိပြထားသော Ranking Message များကို Auto-Update လုပ်ပေးမည့် စက်ဝန်း"""
    while True:
        await asyncio.sleep(60)
        expired_ids = []
        now = datetime.now()
        
        for msg_id, data in list(active_rank_messages.items()):
            if (now - data["last_action"]).total_seconds() > 900:
                expired_ids.append(msg_id)
                continue
                
            try:
                updated_text = await generate_rank_text(data["chat_id"], data["page"])
                buttons = [Button.inline("ဆက်ကြည့်ရန် ➡️", data="rank_page_2")] if data["page"] == 1 else [Button.inline("⬅️ ရှေ့သို့ပြန်သွားရန်", data="rank_page_1")]
                await bot1.edit_message(data["chat_id"], msg_id, updated_text, parse_mode='html', buttons=buttons)
            except Exception: pass
                
        for e_id in expired_ids: active_rank_messages.pop(e_id, None)

async def auto_broadcast_rank_loop():
    """၃ နာရီလျှင် တစ်ကြိမ် Group များထဲသို့ Rank ကို Auto ထုတ်ပြန်ပေးမည့် စက်ဝန်း"""
    while True:
        await asyncio.sleep(3 * 3600)
        try:
            distinct_chats = await rank_col.distinct("chat_id")
            for chat_id in distinct_chats:
                rank_text = await generate_rank_text(chat_id, page=1)
                buttons = [Button.inline("ဆက်ကြည့်ရန် ➡️", data="rank_page_2")]
                msg = await bot1.send_message(chat_id, rank_text, parse_mode='html', buttons=buttons)
                active_rank_messages[msg.id] = {
                    "chat_id": chat_id, "page": 1, "last_action": datetime.now()
                }
        except Exception as e: print(f"Error in auto broadcast loop: {e}")    
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
                msg1 = f"ဟိတ် OWNER နဲ့ Admins တို့ မင်းတို့ရဲ့ ဒီ {safe_title} ထဲကို ထည့်သုံးပေးလို့ ကျေးဇူးတင်ပါတယ်! အသုံးလိုကောင်းလိုနိုင်တဲ့ command များယူထားမယ်ဆိုရင် {bot_mention} ရဲ့ Creator {owner_tag()} ရဲ့ Dm (သို့မဟုတ်) @Besties_with_BoD ကိုလာရောက်ပါ!!!"
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
                                f"ဟိတ်{u_mention}\n"
                                "╔═━━━❖━━━═╗\n"
                                f"{safe_title}ကနေ ကြိုဆိုလိုက်ပါတယ်\n"
                                "╚═━━━❖━━━═╝\n"
                                "┈┈〔 ⚚ 〕┈┈\n"                        
                            )
                        
                        media_file = custom_welcome.get("media") if custom_welcome else None
                        await bot1.send_message(
                            event.chat_id, 
                            bq(welcome_text), 
                            parse_mode='html',
                            file=media_file,
                            buttons=[
                                [Button.url("Contact Bot Creator", f"tg://user?id={OWNER_ID}")],
                                [Button.url("Also Join Our Group", "https://t.me/Besties_with_BoD")]
                            ]
                        )
        elif event.user_left or event.user_kicked:
            u = await bot1.get_entity(event.user_id)
            u_mention = f"<a href='tg://user?id={u.id}'>{escape_html(u.first_name)}</a>"
            await bot1.send_message(event.chat_id, bq(f"ထွက်သွားလိုက်ပါသေးတယ်.{u_mention}!!"), parse_mode='html')

    except Exception as e:
        print(f"Welcome/Goodbye Error: {e}")
# ==========================================
# 🧠 CHATBOT TRAINING SYSTEM (TELETHON)
# ==========================================

# Training Mode ရဲ့ Global Status
TRAINING_ENABLED = True

# 👑 OWNER COMMAND: စာသင်စနစ် ဖွင့်ခြင်း (/ron)
@bot1.on(events.NewMessage(pattern=r'^/ron$'))
async def turn_on_training(event):
    global TRAINING_ENABLED
    if event.sender_id != OWNER_ID:
        return
        
    TRAINING_ENABLED = True
    await event.reply("✅ Sovereign Training Mode ကို ဖွင့်လိုက်ပါပြီ။\nယခုမှစ၍ /r ဖြင့် စာသင်နိုင်ပါသည်။")

# 👑 OWNER COMMAND: စာသင်စနစ် ပိတ်ခြင်း (/roff)
@bot1.on(events.NewMessage(pattern=r'^/roff$'))
async def turn_off_training(event):
    global TRAINING_ENABLED
    if event.sender_id != OWNER_ID:
        return
        
    TRAINING_ENABLED = False
    await event.reply("⛔ Sovereign Training Mode ကို ပိတ်လိုက်ပါပြီ။\nယခုတွင် /r Command အသုံးပြု၍ မရနိုင်တော့ပါ။")

# 📝 TRAINING COMMAND: အဖြေများ ခွဲထုတ်ပြီး DB တွင် သိမ်းဆည်းခြင်း (/r [မေးခွန်း])
@bot1.on(events.NewMessage(pattern=r'^/r(\s+.*)?$'))
async def train_bot(event):
    global TRAINING_ENABLED
    
    # စစ်ဆေးချက် ၁: Training Mode ဖွင့်ထားသလား
    if not TRAINING_ENABLED:
        await event.reply("⚠️ လက်ရှိတွင် Owner မှ Chatbot Training Mode ကို ပိတ်ထားပါတယ်ဗျာ။")
        return

    # စစ်ဆေးချက် ၂: Reply ပြန်ထားခြင်း ရှိမရှိ
    if not event.is_reply:
        await event.reply("❌ အသုံးပြုပုံ မှားယွင်းနေပါသည်။\nအဖြေများပါသော စာသားကို Reply ပြန်ပြီး `/r [မေးခွန်း]` ဟု ရိုက်ပေးပါ။\nဥပမာ- `/r နေကောင်းလား`")
        return

    # စစ်ဆေးချက် ၃: Keyphrase (မေးခွန်း) ပါမပါ
    args = event.pattern_match.group(1)
    if not args:
        await event.reply("❌ မေးခွန်း (Keyphrase) ထည့်သွင်းပေးရန် လိုအပ်ပါသည်။")
        return
        
    keyphrase = args.strip().lower()

    # Reply ထားတဲ့ Message မူရင်းစာသားကို ဆွဲယူခြင်း
    reply_msg = await event.get_reply_message()
    if not reply_msg or not reply_msg.text:
        await event.reply("❌ စာသား (Text) ပါဝင်သော Message ကိုသာ သင်ပေး၍ ရပါမည်။")
        return

    # 🔍 Regex Logic: မျက်တောင်အဖွင့်အပိတ် " " ကြားထဲက စာလုံးများကို တစ်ကြောင်းချင်းစီ ခွဲထုတ်ခြင်း
    new_responses = re.findall(r'"([^"]*)"', reply_msg.text)
    
    if not new_responses:
        await event.reply("❌ အဖြေများကို မျက်တောင်အဖွင့်အပိတ် \" \" ထဲတွင် တစ်ကြောင်းချင်းစီ ထည့်ပေးပါဗျာ။\nဥပမာ -\n\"အဖြေ ၁\"\n\"အဖြေ ၂\"")
        return

    # 🗄️ Motor Async MongoDB Operation (ans_col သို့ ပြောင်းလဲထားသည်)
    existing_doc = await ans_col.find_one({"keyphrase": keyphrase})
    
    if existing_doc:
        # ရှိပြီးသားဆိုရင် အသစ်ထပ်ပေါင်းမယ် (စာသားတူရင် ဖယ်မည့် set စနစ်)
        existing_responses = existing_doc.get("responses", [])
        updated_responses = list(set(existing_responses + new_responses))
        await ans_col.update_one(
            {"keyphrase": keyphrase}, 
            {"$set": {"responses": updated_responses}}
        )
        action_msg = f"အဖြေအသစ်များကို ပေါင်းထည့်လိုက်ပါပြီ။ (စုစုပေါင်းအဖြေ: {len(updated_responses)} ခု)"
    else:
        # အသစ်စက်စက်ဆိုရင် Insert လုပ်မယ်
        await ans_col.insert_one({"keyphrase": keyphrase, "responses": new_responses})
        action_msg = "အစုံလိုက် အသစ်စက်စက် မှတ်သားလိုက်ပါပြီ။"

    # သင်ကြားမှု အောင်မြင်ကြောင်း ရိုးရိုးစာသားဖြင့် ပြန်ပြပေးခြင်း
    debug_list = "\n".join([f"• {r}" for r in new_responses])
    await event.reply(f"✨ စကားလုံးအသစ် မှတ်သားမှု အောင်မြင်သည်!\n🔑 Key: {keyphrase}\n📝 ခွဲထုတ်ရရှိသည့် အဖြေများ ({len(new_responses)} ခု):\n{debug_list}\n\n💡 {action_msg}")


# 💬 AUTOMATIC CHAT RESPONDER: လူတွေပြောတာနဲ့ ဆက်စပ်ပြီး ပြန်ဖြေပေးသည့် အပိုင်း
@bot1.on(events.NewMessage(incoming=True))
async def chatbot_auto_responder(event):
    # private chat တွေ သို့မဟုတ် command တွေကိုကျော်မယ်
    if event.is_private or not event.text or event.text.startswith(('/', '.', 'မှတ်')):
        return

    user_text = event.text.lower()
    
    # ans_col ထဲက Data တွေကို လှမ်းစစ်ခြင်း
    cursor = ans_col.find()
    async for doc in cursor:
        keyphrase = doc.get("keyphrase")
        if keyphrase and keyphrase in user_text:
            responses = doc.get("responses", [])
            if responses:
                chosen_response = random.choice(responses)
                await event.reply(chosen_response)
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
                action_msg = f"{mention} ကို Sticker ပို့ခွင့် ပိတ်လိုက်ပါပြီ။\nအကြောင်းရင်း- 1 မိနစ်အတွင်း Stickerများစွာ Spam တဲ့အတွက် ဖြစ်ပါတယ်။"
            
            await event.respond(bq(action_msg), parse_mode='html')
            del sticker_spam_data[sender_id]
            return
        except Exception as e: 
            print(f"Spam Filter Error: {e}")

    if len(recent_times) >= 3:
        time_diff = (recent_times[-1] - recent_times[-3]).total_seconds()
        if time_diff <= 1.0: 
            await event.delete()
        
@bot1.on(events.NewMessage(pattern=r'^[/.]f\s+(.*)'))
async def add_filter(event):
    if not await check_admin(event.chat_id, event.sender_id): return
    input_str = event.pattern_match.group(1).split(None, 1)
    keyword = input_str[0].lower()
    reply = await event.get_reply_message()

    if reply:
        media, m_type = None, None
        if reply.sticker: media, m_type = reply.media, "sticker"
        elif reply.photo: media, m_type = reply.media, "photo"
        elif reply.video: media, m_type = reply.media, "video"
        elif reply.text: media, m_type = reply.text, "text"

        if media:
            await custom_filters_col.update_one({"keyword": keyword}, {"$set": {"content": media, "type": m_type, "chat_id": "global"}}, upsert=True)
            await event.reply(bq(f"အိုကေ! '{keyword}' အတွက် {m_type} filter ကို Group အားလုံးအတွက် မှတ်လိုက်ပြီ ✅"), parse_mode='html')
    elif len(input_str) > 1:
        await custom_filters_col.update_one({"keyword": keyword}, {"$set": {"content": input_str[1], "type": "text", "chat_id": "global"}}, upsert=True)
        await event.reply(bq(f"အိုကေ! '{keyword}' ဆိုရင် '{input_str[1]}' လို့ Group အားလုံးမှာ ပြန်ပေးမယ်။ ✅"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^[/.]id'))
async def get_user_id(event):
    reply = await event.get_reply_message()
    if reply:
        target_id, user = reply.sender_id, await reply.get_sender()
        name = escape_html(user.first_name) if user else "User"
        msg = f"👤 <b>Name:</b> {name}\n🆔 <b>User ID:</b> <code>{target_id}</code>"
    else: msg = f"🆔 <b>Your ID:</b> <code>{event.sender_id}</code>"
    await event.respond(bq(msg), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^[/.]gid'))
async def get_group_id(event):
    if event.is_private: return await event.respond(bq("ဒါက Private Chat မို့လို့ Group ID မရှိပါဘူး!"), parse_mode='html')
    await event.respond(bq(f"📍 <b>Group:</b> {escape_html(event.chat.title)}\n🌐 <b>Chat ID:</b> <code>{event.chat_id}</code>"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/setwc(?:\s+(.*))?'))
async def set_custom_welcome(event):
    if event.sender_id != OWNER_ID: return
    
    reply = await event.get_reply_message()
    text_to_save = event.pattern_match.group(1) 
    media_to_save = None

    if reply:
        if reply.media: media_to_save = reply.media
        if not text_to_save and reply.text: text_to_save = reply.text

    if not text_to_save and not media_to_save:
        return await event.respond(bq("❌ အမှား- Welcome အတွက် စာသား (သို့) ပုံ တစ်ခုခု ထည့်ပေးပါ။\nပုံကို Reply ပြန်ပြီး /setwc [စာသား] လို့ ရိုက်နိုင်ပါတယ်။"), parse_mode='html')

    await welcome_col.update_one(
        {"chat_id": event.chat_id},
        {"$set": {"text": text_to_save, "media": media_to_save}},
        upsert=True
    )
    await event.respond(bq(f"✅ <b>{escape_html(event.chat.title)}</b> အတွက် Welcome Message ကို မှတ်သားလိုက်ပါပြီ။"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/mute(?:@\w+)?(?:\s+(.*))?'))
async def mute_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id):
        return await event.reply("⚠️ သင့်မှာ Ban/Mute လုပ်ပိုင်ခွင့် မရှိပါဘူး။")
        
    args = event.pattern_match.group(1)
    reply = await event.get_reply_message()
    target_user = None
    
    if reply: target_user = reply.sender
    elif args:
        try: target_user = await bot1.get_entity(int(args.strip()) if args.strip().lstrip('-').isdigit() else args.strip())
        except Exception: return await event.reply("❌ User ကို ရှာမတွေ့ပါ။ ID သို့မဟုတ် @username မှန်ကန်စွာ ရိုက်ထည့်ပါ။")

    if not target_user: return await event.reply("❌ Mute ချင်တဲ့သူကို Reply ထောက်ပါ (သို့မဟုတ်) Username/ID ကို တွဲရိုက်ပါ။")

    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, send_messages=False)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User') or 'User')}</a>"
        await event.respond(f"🔇 {mention} ကို Mute လိုက်ပါပြီ!", parse_mode='html')
    except Exception as e: await event.respond(f"⚠️ Error: {e}")

@bot1.on(events.NewMessage(pattern=r'^/unmute(?:@\w+)?(?:\s+(.*))?'))
async def unmute_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id):
        return await event.reply("⚠️ သင့်မှာ Ban/Mute လုပ်ပိုင်ခွင့် မရှိပါဘူး။")
        
    args = event.pattern_match.group(1)
    reply = await event.get_reply_message()
    target_user = None
    
    if reply: target_user = reply.sender
    elif args:
        try: target_user = await bot1.get_entity(int(args.strip()) if args.strip().lstrip('-').isdigit() else args.strip())
        except Exception: return await event.reply("❌ User ကို ရှာမတွေ့ပါ။")

    if not target_user: return await event.reply("❌ Unmute ချင်တဲ့သူကို Reply ထောက်ပါ။")

    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, send_messages=True)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User') or 'User')}</a>"
        await event.respond(f"🔊 {mention} ကို Unmute လုပ်ပြီးပြီ!", parse_mode='html')
    except Exception as e: await event.respond(f"⚠️ Error: {e}")

@bot1.on(events.NewMessage(pattern=r'^/adm(?:\s+(.*))?'))
async def tag_admins(event):
    if not await check_admin(event.chat_id, event.sender_id): return
    text = event.pattern_match.group(1) or "Adminတို့ရေ ခေါ်နေပါတယ်🤍"
    try:
        admins = await bot1.get_participants(event.chat_id, filter=ChannelParticipantsAdmins)
        msg = f"📣 {escape_html(text)}\n\n"
        for a in admins:
            if a.bot or getattr(a, 'deleted', False): continue
            msg += f"• <a href='tg://user?id={a.id}'>{escape_html(a.first_name or 'Admin')}</a>\n"
        await event.respond(bq(msg), parse_mode='html')
    except Exception as e: await event.respond(bq(f"Error: {e}"))

@bot1.on(events.NewMessage(pattern=r'^/addallow(?:@\w+)?$'))
async def add_allow(event):
    if event.sender_id != OWNER_ID: return
    reply = await event.get_reply_message()
    if reply:
        await allow_col.update_one({"user_id": reply.sender_id}, {"$set": {"name": reply.sender.first_name}}, upsert=True)
        await event.reply(bq(f"{escape_html(reply.sender.first_name)} ကို Allow List ထည့်ပြီးပါပြီ! ✅"), parse_mode='html')
    else: await event.reply(bq("Allow ပေးချင်တဲ့သူကို Reply ထောက်ပြီးမှ Command ရိုက်"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/removeallow(?:@\w+)?\s+(\d+)'))
async def remove_allow(event):
    if event.sender_id != OWNER_ID: return
    target_id = int(event.pattern_match.group(1))
    delete_result = await allow_col.delete_one({"user_id": target_id})
    if delete_result.deleted_count > 0: await event.respond(bq(f"User ID {target_id} ကို ပါမစ်မပေးတော့ဘူး"), parse_mode='html')
    else: await event.respond(bq("ဒီ User ID ကို List ထဲမှာ မတွေ့ပါ။"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/allowlist(?:@\w+)?$'))
async def allow_list(event):
    if event.sender_id != OWNER_ID: return
    users = await allow_col.find().to_list(length=None)
    msg = "<b>✅ Allowed Users List:</b>\n\n" + "".join([f"• <a href='tg://user?id={u.get('user_id')}'>{escape_html(u.get('name', 'Unknown'))}</a> (<code>{u.get('user_id')}</code>)\n" for u in users]) if users else "Allow List မှာ မရှိသေးပါ။"
    await event.reply(bq(msg), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/ပို့(?:@\w+)?(?:\s+(.*))?'))
async def broadcast(event):
    if event.sender_id != OWNER_ID: return
    reply_msg = await event.get_reply_message()
    command_text = event.pattern_match.group(1)
    
    if not reply_msg and not command_text: return await event.respond("📢 ပို့မယ့် စာသားထည့်ပါ (သို့) Message တစ်ခုကို Reply ပြန်ပြီး '/ပို့' လို့ ရိုက်ပါ။")

    success = 0
    fail = 0
    status_msg = await event.respond("📢 **Broadcast စတင်နေပါပြီ...**")
    groups = await groups_col.find().to_list(length=None)

    for g in groups:
        try:
            if reply_msg: await bot1.forward_messages(g['chat_id'], reply_msg)
            else: await bot1.send_message(g['chat_id'], command_text, parse_mode='html')
            success += 1
            if success % 5 == 0: await status_msg.edit(f"📢 **ပို့ဆောင်နေဆဲ...**\n✅ အောင်မြင်: {success}\nမပို့ရသေးတာ: {fail}")
            await asyncio.sleep(1) 
        except Exception as e:
            fail += 1
            continue

    await status_msg.edit(f"<b>📢Message တွေကို သေချာပို့ပေးလိုက်ပြီ!</b>\n\n✅ အောင်မြင်သော Group: <b>{success}</b>\n❌ ပို့မရသော Group: <b>{fail}</b>\n", parse_mode='html')

# ====================================================================================
# 🗄️ DATABASE DASHBOARD SYSTEM (OWNER ONLY)
# ====================================================================================

@bot1.on(events.NewMessage(pattern=r'^ပြအုံး$'))
async def db_dashboard_main(event):
    # Owner တစ်ယောက်တည်းသာ ခွင့်ပြုမည်
    if event.sender_id != OWNER_ID:
        return

    # Loading ပြပေးခြင်း
    status_msg = await event.respond("📊 <i>Database စနစ်များကို စစ်ဆေးနေပါသည်...</i>", parse_mode='html')

    try:
        # Collection တစ်ခုချင်းစီရဲ့ Document အရေအတွက်ကို လှမ်းတွက်ခြင်း
        custom_filters_count = await custom_filters_col.count_documents({})
        filters_count = await filters_col.count_documents({})
        allow_count = await allow_col.count_documents({})
        groups_count = await groups_col.count_documents({})
        talk_count = await talk_col.count_documents({})
        talker_count = await talker_col.count_documents({})
        welcome_count = await welcome_col.count_documents({})
        ans_count = await ans_col.count_documents({})
        morgan_count = await morgan_col.count_documents({})
        rank_count = await rank_col.count_documents({})
        system_count = await system_col.count_documents({})

        # စုစုပေါင်း Data ပမာဏ တွက်ချက်ခြင်း
        total_data = (custom_filters_count + filters_count + allow_count + groups_count + 
                      talk_count + talker_count + welcome_count + ans_count + morgan_count + 
                      rank_count + system_count)

        # 🎛️ UI Main Text Layout
        dashboard_text = (
            "⚙️ <b>⚚𝘽𝙤𝘿𝙭 𝙈𝙤𝙧𝙜𝙖𝙣 𝙋𝘼𝙍𝘼𝘿𝙊𝙓 - 𝘿𝘽 𝘿𝘼𝙎𝙃𝘽𝙊𝘼𝙍𝘿</b> ⚙️\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 <b>System Owner:</b> {owner_tag()}\n"
            f"📊 <b>Total Collections:</b> <code>11 Collections</code>\n"
            f"🗂️ <b>Total Active Data:</b> <code>{total_data:,} entries</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "📋 <b>Collections Overview:</b>\n"
            f" ├─ 🏷️ Custom Filters: <code>{custom_filters_count}</code>\n"
            f" ├─ ☣️ Bully Filters: <code>{filters_count}</code>\n"
            f" ├─ 👑 Allowed Users: <code>{allow_count}</code>\n"
            f" ├─ 👥 Active Groups: <code>{groups_count}</code>\n"
            f" ├─ 💬 Chatbot Keyphrases: <code>{ans_count}</code>\n"
            f" └─ 🎭 Morgan Lines: <code>{morgan_count}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "💡 <i>အချက်အလက်များကို အသေးစိတ်ကြည့်ရှုရန် အောက်ပါ Button များကို နှိပ်ပါ။</i>"
        )

        # 📱 Inline Buttons အခင်းအကျင်း
        buttons = [
            [
                Button.inline("🏷️ Custom Filters", data="db_detail_custom_filters"),
                Button.inline("☣️ Bully Filters", data="db_detail_filters")
            ],
            [
                Button.inline("👑 Allowed Users", data="db_detail_allowed_users"),
                Button.inline("👥 Active Groups", data="db_detail_active_groups")
            ],
            [
                Button.inline("💬 Chatbot Answers", data="db_detail_chatbot_answers"),
                Button.inline("🎭 Morgan Talk", data="db_detail_morgan_talk")
            ],
            [
                Button.inline("📊 Rank & System DB", data="db_detail_system_rank")
            ]
        ]

        await status_msg.edit(dashboard_text, parse_mode='html', buttons=buttons)

    except Exception as e:
        await status_msg.edit(f"❌ <b>DB Dashboard Error:</b>\n<code>{e}</code>", parse_mode='html')


# 🔄 INLINE BUTTON CLICK HANDLER (DETAILED VIEW)
@bot1.on(events.CallbackQuery(pattern=r'^db_detail_(.*)$'))
async def on_db_detail_click(event):
    # Owner မဟုတ်ရင် လုပ်ဆောင်ခွင့်မပေးပါ
    if event.sender_id != OWNER_ID:
        return await event.answer("⚠️ မင်းက စနစ်ရဲ့ အရှင်သခင် မဟုတ်ဘူး", alert=True)

    target_db = event.pattern_match.group(1)
    detail_text = ""
    
    # 🔙 Main Menu ပြန်သွားမည့် Button
    back_button = [[Button.inline("🔙 ပင်မစာမျက်နှာသို့", data="db_dashboard_back")]]

    try:
        if target_db == "custom_filters":
            detail_text = "🏷️ <b>CUSTOM FILTERS DETAIL</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
            cursor = custom_filters_col.find().limit(15)
            async for doc in cursor:
                detail_text += f"• 🔑 <code>{doc.get('keyword')}</code> ➜ <i>[{doc.get('type')}]</i>\n"
            
        elif target_db == "filters":
            detail_text = "☣️ <b>BULLY FILTERS (WORDS LIST)</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
            cursor = filters_col.find().limit(20)
            words = []
            async for doc in cursor:
                if doc.get('text'): words.append(f"<code>{doc.get('text')}</code>")
            detail_text += ", ".join(words) if words else "<i>ဘာစာလုံးမှ မရှိသေးပါ။</i>"

        elif target_db == "allowed_users":
            detail_text = "👑 <b>ALLOWED USERS LIST</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
            cursor = allow_col.find()
            async for doc in cursor:
                detail_text += f"• <a href='tg://user?id={doc.get('user_id')}'>{escape_html(doc.get('name', 'Unknown'))}</a> (<code>{doc.get('user_id')}</code>)\n"

        elif target_db == "active_groups":
            detail_text = "👥 <b>ACTIVE GROUPS LIST</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
            cursor = groups_col.find()
            async for doc in cursor:
                detail_text += f"• 🌐 {escape_html(doc.get('title'))} (<code>{doc.get('chat_id')}</code>)\n"

        elif target_db == "chatbot_answers":
            detail_text = "💬 <b>CHATBOT LEARNING KEYPHRASES</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
            cursor = ans_col.find().limit(10)
            async for doc in cursor:
                detail_text += f"• 🔑 <b>Key:</b> <code>{doc.get('keyphrase')}</code> ({len(doc.get('responses', []))} responses)\n"

        elif target_db == "morgan_talk":
            detail_text = "🎭 <b>MORGAN BULK TALK SAMPLES (Last 10)</b>\n━━━━━━━━━━━━━━━━━━━━━\n"
            count = await morgan_col.count_documents({})
            detail_text += f"📝 Total Lines Learned: <code>{count}</code>\n\n"
            cursor = morgan_col.find().sort("_id", -1).limit(10)
            async for doc in cursor:
                detail_text += f"• \"<i>{escape_html(doc.get('text'))}</i>\"\n"

        elif target_db == "system_rank":
            rank_count = await rank_col.count_documents({})
            talk_count = await talk_col.count_documents({})
            talker_count = await talker_col.count_documents({})
            system_count = await system_col.count_documents({})
            
            detail_text = (
                "📊 <b>TRACKER & INTERNAL SYSTEM DB</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━\n"
                f"• 📈 Admin Rank Logs: <code>{rank_count} entries</code>\n"
                f"• 🗣️ Random Talk Pool: <code>{talk_count} sentences</code>\n"
                f"• 👤 Talkers/Nicknames: <code>{talker_count} users</code>\n"
                f"• ⚙️ System/Uptime Docs: <code>{system_count} docs</code>\n"
            )

        if not detail_text:
            detail_text = "❌ အချက်အလက်များ ရှာမတွေ့ပါ သို့မဟုတ် သိမ်းဆည်းထားခြင်း မရှိသေးပါ။"

        await event.edit(detail_text, parse_mode='html', buttons=back_button)

    except Exception as e:
        await event.edit(f"❌ <b>Error fetching details:</b>\n<code>{e}</code>", buttons=back_button, parse_mode='html')


# 🔄 BACK TO DASHBOARD HOME HANDLER
@bot1.on(events.CallbackQuery(pattern=r'^db_dashboard_back$'))
async def on_db_dashboard_back(event):
    if event.sender_id != OWNER_ID:
        return
        
    # မူလ Dashboard ကို ပြန်ခေါ်ရန် အပေါ်က Main Function ကို လှမ်းမောင်းနှင်ခြင်း
    await event.delete()
    # Event ရဲ့ မက်ဆေ့ခ်ျအသစ်ပုံစံအတိုင်း ပုံဖျက်ပြီး Main Cmd ကို ပြန်ပတ်စေခြင်း
    event.text = "ပြအုံး"
    await db_dashboard_main(event)
# ====================================================================================
# 📜 SOVEREIGN SYSTEM COMMANDS DIRECTORY (OWNER ONLY)
# ====================================================================================

@bot1.on(events.NewMessage(pattern=r'^cmd$'))
async def system_commands_directory(event):
    # Owner သာလျှင် ကြည့်ရှုခွင့်ပေးမည်
    if event.sender_id != OWNER_ID:
        return

    status_msg = await event.respond("<i>စနစ်တစ်ခုလုံး၏ Commands Manual ကို ဖတ်ရှုနေပါသည်...</i>", parse_mode='html')

    main_menu_text = (
        "📜 <b>⚚𝘽𝙤𝘿𝙭 𝙈𝙤𝙧𝙜𝙖𝙣 𝙋𝘼𝙍𝘼𝘿𝙊𝙓</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👑 <b>BoD System Owner:</b> {owner_tag()}\n"
        "📊 <b>System Status:</b> <code>Active & Protected</code>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <i>Command တစ်ခုချင်းစီရဲ့ အသုံးပြုပုံ၊ ဘာလုပ်ပေးတယ်၊ ဘယ်သူတွေ သုံးခွင့်ရှိလဲဆိုတာကို Detailed ကျကျ ကြည့်ရှုရန် အောက်ပါ အမျိုးအစားအလိုက် Button များကို နှိပ်ပါ Chief။</i>"
    )

    # 📱 အမျိုးအစားအလိုက် ခွဲပြပေးမည့် Inline Buttons
    buttons = [
        [
            Button.inline("📊 Rank & Stats", data="cmd_cat_rank"),
            Button.inline("🛡️ Protection & Filter", data="cmd_cat_protect")
        ],
        [
            Button.inline("💬 Chatbot & Morgan", data="cmd_cat_chat"),
            Button.inline("☣️ Bully & Attack", data="cmd_cat_bully")
        ],
        [
            Button.inline("⚙️ Owner Control", data="cmd_cat_owner")
        ]
    ]

    await status_msg.edit(main_menu_text, parse_mode='html', buttons=buttons)


# 🔄 COMMAND DETAILS CALLBACK HANDLER
@bot1.on(events.CallbackQuery(pattern=r'^cmd_cat_(.*)$'))
async def on_cmd_cat_click(event):
    if event.sender_id != OWNER_ID:
        return await event.answer("⚠️ မင်းက စနစ်ရဲ့ အရှင်သခင် မဟုတ်ဘူး ဟန်နီ!", alert=True)

    category = event.pattern_match.group(1)
    detail_text = ""
    back_button = [[Button.inline("🔙 ပင်မစာမျက်နှာသို့", data="cmd_directory_back")]]

    if category == "rank":
        detail_text = (
            "📊 <b>RANKING & STATUS COMMANDS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "💬 <b>Command:</b> <code>/rank</code>\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> Admin များ၏ စာပို့မှုနှုန်း၊ ဖျက်မှုနှုန်းနှင့် Presence UI ကို စာမျက်နှာအလိုက် လှလှပပ ပြသပေးခြင်း။ (၁ မိနစ်တစ်ခါ Auto-Update ဖြစ်သည်)\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Everyone (In Group)</code>\n\n"
            "➕ <b>Command:</b> <code>/rankadd [@username/ID] [အရေအတွက်]</code>\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> သတ်မှတ်ထားသော Admin ၏ စုစုပေါင်း Message စာရင်းထဲသို့ စာစောင်အရေအတွက် အစုလိုက် ပေါင်းထည့်ပေးခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Owner & Admins</code>\n\n"
            "🆔 <b>Command:</b> <code>/id</code> သို့မဟုတ် <code>/gid</code>\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> မိမိ သို့မဟုတ် Reply ထောက်ထားသူ၏ User ID နှင့် Group ID ကို ထုတ်ပြပေးခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Everyone</code>"
        )

    elif category == "protect":
        detail_text = (
            "🛡️ <b>PROTECTION & FILTER COMMANDS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🏷️ <b>Command:</b> <code>/f [keyword]</code> (Reply ဖြင့်ဖြစ်စေ စာသားဖြင့်ဖြစ်စေ)\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> သတ်မှတ်ထားသော Keyword ကို Group အားလုံးတွင် Global Auto-Filter (ပုံ၊ Sticker၊ စာသား) အဖြစ် အလုပ်လုပ်စေရန် သိမ်းဆည်းခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Group Admins</code>\n\n"
            "👋 <b>Command:</b> <code>/setwc [စာသား]</code> (Reply ဖြင့်ဖြစ်စေ)\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> လူသစ်ဝင်လာပါက ကြိုဆိုမည့် Custom Welcome Message နှင့် Media ကို သတ်မှတ်ခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Owner Only</code>\n\n"
            "🔇 <b>Command:</b> <code>/mute</code> နှင့် <code>/unmute</code>\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> သတ်မှတ်ထားသော User အား စာပို့ခွင့် ပိတ်ခြင်း/ပြန်ဖွင့်ခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Admins (with Ban Rights)</code>"
        )

    elif category == "chat":
        detail_text = (
            "💬 <b>CHATBOT & MORGAN SYSTEMS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "📝 <b>Command:</b> <code>/r [မေးခွန်း]</code> (အဖြေကို မျက်တောင်အဖွင့်အပိတ် \" \" ဖြင့် Reply ပြန်ရန်)\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> Chatbot စနစ်သို့ Keyword အလိုက် ကျပန်းတုံ့ပြန်မည့် အဖြေများကို အစုလိုက် သင်ကြားမှတ်သားစေခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Everyone (ဖွင့်ထားစဉ်)</code>\n\n"
            "🤖 <b>Command:</b> <code>/ron</code> နှင့် <code>/roff</code>\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> Sovereign Training Mode နှင့် Morgan bulk messages သင်ကြားရေးစနစ်ကို DM/Group ထဲတွင် ဖွင့်ခြင်း/ပိတ်ခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Owner Only</code>\n\n"
            "🎭 <b>Morgan System Trigger:</b>\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> Group များထဲတွင် စာ ၁၀၀ ပြည့်မြောက်တိုင်း Morgan Collection ထဲမှ ကျပန်းစာသားတစ်ကြောင်းကို <code>#Morgan</code> တဂ်ဖြင့် Normal Message အဖြစ် ဝင်ရောက်စကားပြောခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Automated System</code>"
        )

    elif category == "bully":
        detail_text = (
            "☣️ <b>BULLY, ATTACK & TARGETING SYSTEMS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "🤬 <b>Command:</b> <code>/b</code> (Target အား Reply ပြန်ရန်)\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> <code>filters_col</code> ထဲမှ စကားလုံးများဖြင့် Target ခေါင်းမဖော်နိုင်အောင် တစ်စက္ကန့်ချင်းစီ ဆဲဆိုတိုက်ခိုက်ခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Allowed Users Only</code>\n\n"
            "🛑 <b>Command:</b> <code>/sb</code>\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> အထက်ပါ Bully Loop တိုက်ခိုက်မှုကို ချက်ချင်းရပ်တန့်စေခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Allowed Users Only</code>\n\n"
            "💥 <b>Command:</b> <code>ဗုံး [@username]</code> သို့မဟုတ် Reply\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> Target အား ဖုန်းဟန်းသွားစေမည့် Bomb Tag Messages များစွာဖြင့် အမြန်နှုန်းဖြင့် ပစ်ခတ်တိုက်ခိုက်ပြီး Auto-Delete ပြန်လုပ်ခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Owner & Allowed Users</code>\n\n"
            "🎯 <b>Commands:</b> <code>ချိန်ထား</code> / <code>ပစ်သတ်</code> / <code>ပစ်</code> / <code>ရပ်</code>\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> Target တစ်ယောက်ချင်းစီကို စောင့်ကြည့်ပြီး စာပို့သမျှကို Filter စာလုံးများဖြင့် လိုက်လံပစ်ခတ်ချေမှုန်းခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Allowed Users Only</code>"
        )

    elif category == "owner":
        detail_text = (
            "⚙️ <b>OWNER EXCLUSIVE CONTROL COMMANDS</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━\n"
            "👑 <b>Command:</b> <code>/addallow</code> / <code>/removeallow</code>\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> Bot ရဲ့ Bully တိုက်ခိုက်ရေး Command များကို သုံးစွဲခွင့်ရှိမည့် ဗိုလ်ကြီးများ (Allowed List) ကို ထည့်သွင်းခြင်း/ဖယ်ရှားခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Owner Only</code>\n\n"
            "📋 <b>Command:</b> <code>/allowlist</code>\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> လက်ရှိ ပါမစ်ရထားသော Allowed Users အားလုံးကို တဂ်ဖြင့် စာရင်းထုတ်ပြခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Owner Only</code>\n\n"
            "📢 <b>Command:</b> <code>/ပို့ [စာသား]</code> သို့မဟုတ် Message အား Reply ပြန်ရန်\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> Bot ရှိနေသော Active Groups အားလုံးထဲသို့ သတင်းစကားများကို Global Broadcast စနစ်ဖြင့် တစ်ပြိုင်နက် လှမ်းပို့ခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Owner Only</code>\n\n"
            "🗄️ <b>Command:</b> <code>ပြအုံး</code>\n"
            "├─ <b>လုပ်ဆောင်ချက်:</b> Database Collections အားလုံးထဲက Data အရေအတွက်နှင့် အသေးစိတ် Sample များကို Inline Dashboard ဖြင့် ကြည့်ရှုခြင်း။\n"
            "└─ <b>အသုံးပြုပိုင်ခွင့်:</b> <code>Owner Only</code>"
        )

    await event.edit(detail_text, parse_mode='html', buttons=back_button)


# 🔄 BACK TO DIRECTORY HOME
@bot1.on(events.CallbackQuery(pattern=r'^cmd_directory_back$'))
async def on_cmd_directory_back(event):
    if event.sender_id != OWNER_ID:
        return
        
    await event.delete()
    event.text = "cmd"
    await system_commands_directory(event)

@bot1.on(events.NewMessage())
async def protection_logic(event):
    if event.is_private: return
    if not event.text or event.sender_id == OWNER_ID or event.sender_id in bot_ids: return

    text, chat_id, sender_id = event.text.strip(), event.chat_id, event.sender_id
    sender = await event.get_sender()

    if re.search(r'/harem(@\w+)?', text) or re.search(r'/waifu(@\w+)?', text):
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

    if any(key in text for key in ["Bio", "bio", "ဘိုင်အို", "ဘိုင်-အို", "ဘိုင်-O", "ဘီအိုင်အို"]) and not await check_admin(chat_id, sender_id):
        try:
            await event.delete()
            await event.respond(bq("bioမှာဘာဖြစ်တာလဲ၊မသိချင်ဘူး ဖျက်လိုက်ပြီ။"), parse_mode='html')
            return 
        except: pass

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
                await event.respond(bq(f"ဟိတ်.. {mention} link မပို့နဲ့ မရဘူး၊ မင်း link ကို ငါဖျက်လိုက်ပြီ🫵"), parse_mode='html')
            except: pass

    if chat_id == SPECIFIC_GROUP:
        if re.search(r'^[/,.](harem|gift|check)', text.lower()) or any(k in text.lower() for k in ["ကတ်ဂေ့", "ကဒ်ဂေ့"]):
            mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name)}</a>"
            msg = f"ဟိတ်... {mention} !! <b>{escape_html(event.chat.title)}</b> ထဲမှာ Character Catcher Bot ကို ကဒ်ကောက်ဖို့ပဲ ရတော့မယ်။ကျန်တဲ့ Giftပေးတာ,Haremတာ,Checkတာတွေအတွက် သီးသန့် Group Chat တစ်ခု ဖွင့်ပေးထားပါတယ်၊အဲ့ထဲမှာ စိတ်ကြိုက် ကဒ်ဂေ့၊ဟာရမ်း၊ချက်ခ်လုပ်ကြပါ သူငယ်ချင်းတို့🤍 သီးသန့် Group Mention Link - https://t.me/catchbot_gift_harem_check_only"
            try: await event.reply(bq(msg), parse_mode='html', link_preview=False)
            except: pass

@bot1.on(events.NewMessage(pattern=r'^/play(?:\s+(.*))?'))
async def play_response(event):
    if event.is_private: return
    song_title = event.pattern_match.group(1)
    if not song_title: return 
    
    mention = f"<a href='tg://user?id={event.sender_id}'>{escape_html((await event.get_sender()).first_name)}</a>"
    msg_body = f"<b>Song Title</b>- {escape_html(song_title)}\n<b>သီချင်းဖွင့်တဲ့သူ</b>- {mention}\nစနားထောင်လို့ရပါပြီ။\nMusic botကို ပိတ်ဖို့လည်း မမေ့ပါနဲ့🤍"
    msg = await event.respond(bq(msg_body), parse_mode='html')

    for i in range(3, 0, -1):
        await asyncio.sleep(1) 
        try: await msg.edit(bq(f"{msg_body}\n\n🗑 <b>{i}</b> စက္ကန့်အတွင်း ဖျက်ပါမည်..."), parse_mode='html')
        except: break
            
    await asyncio.sleep(0.5)
    try:
        await msg.delete()       
        await event.delete()     
    except: pass

@bot1.on(events.NewMessage(pattern=r'^/b(?:@\w+)?$'))
async def bot_bully(event):
    if not await is_allowed(event.sender_id): 
        return await event.reply(bq("မင်းမှာ ဒီ Command ကို သုံးပိုင်ခွင့်မရှိဘူး။သုံးခွင့်နဲ့အသုံးပြုနည်းများအတွက် @Besties_with_BoD ကိုလာ "), parse_mode='html')
    reply = await event.get_reply_message()
    if not reply: return await event.respond(bq("ဘယ်ကောင့်ကို ခေါင်းမဖော်နိုင်အောင် ဆဲပေးရမလဲ၊Replyပြန်လိုက် "), parse_mode='html')
    try: await event.delete()
    except: pass

    t = await reply.get_sender()
    if not t: return
    if t.id == OWNER_ID: return await event.respond(bq("ဟိတ်ကောင် Creatorကို ပြန်ပြီးဆဲဆိုခွင့် မပေးထားဘူး🔥"), parse_mode='html')

    bot_bully_tasks[event.chat_id] = True
    mention = f"<a href='tg://user?id={t.id}'>{escape_html(t.first_name)}</a>"
    
    db_filters = await filters_col.find().to_list(length=None)
    words = [w.get("text") for w in db_filters if w.get("text")] 
    if not words: return await event.respond(bq("DB (filters collection) ထဲမှာ စာလုံးမရှိသေးဘူး Chief!"))

    await event.respond(bq(f"{mention} ကို ခေါင်းမဖော်နိုင်အောင် စဆဲပါပြီ။"), parse_mode='html')
    
    # ⚠️ FloodWait ကာကွယ်ရန် Single Bot အတွက် Delay တိုးထားပါတယ်
    while bot_bully_tasks.get(event.chat_id):
        try: 
            await bot1.send_message(event.chat_id, bq(f"{mention} {random.choice(words)}"), reply_to=reply.id, parse_mode='html')
            await asyncio.sleep(1.2) # ၁ စက္ကန့်ကျော် ခြားပေးခြင်းဖြင့် Telegram Ban ရန်မှ ကာကွယ်မယ်
        except: bot_bully_tasks[event.chat_id] = False; break

@bot1.on(events.NewMessage(pattern=r'^/sb(?:@\w+)?$'))
async def stop_bot_bully(event):
    if not await is_allowed(event.sender_id): return
    try: await event.delete()
    except: pass
    bot_bully_tasks[event.chat_id] = False
    await event.respond(bq("အခုနားဆိုလို့နားလိုက်မယ်၊စောက်ချိုးမပြေရင်ထပ်ဆဲပေးမယ်"), parse_mode='html')

@bot1.on(events.NewMessage())
async def custom_filter_watcher(event):
    if event.is_private or not event.text or event.sender_id in bot_ids: return
    user_msg = event.text.lower().strip()
    
    async for item in custom_filters_col.find():
        keyword = item["keyword"].lower().strip()
        is_match = (user_msg == keyword) or (f" {keyword} " in f" {user_msg} ") or user_msg.startswith(f"{keyword} ") or user_msg.endswith(f" {keyword}")
        if is_match:
            try:
                if item["type"] == "text": await event.reply(item["content"])
                else: await event.reply(file=item["content"])
                break 
            except Exception as e: print(f"Filter Response Error: {e}")

@bot1.on(events.NewMessage(pattern=r'^ဗုံး(?:\s+(.*))?'))
async def bomb_attack(event):
    is_allowed_user = False
    if event.sender_id == OWNER_ID: is_allowed_user = True
    else:
        try:
            if await allow_col.find_one({"user_id": event.sender_id}): is_allowed_user = True
        except: pass

    if not is_allowed_user: return  
    text = event.pattern_match.group(1)
    target_user = None

    if event.is_reply: target_user = await bot1.get_entity((await event.get_reply_message()).sender_id)
    elif text:
        try: target_user = await bot1.get_entity(text.strip())
        except Exception as e: return await event.reply(bq(f"အကောင့်ရှာမတွေ့ပါ Chief: {e}"), parse_mode='html')
    else: return await event.reply(bq("Reply ထောက်ပါ (သို့) <code>ဗုံး @username</code> လို့ ရိုက်ပါ။"), parse_mode='html')

    if not isinstance(target_user, User): return await event.reply(bq("User အစစ်ကိုပဲ တိုက်ခိုက်လို့ရပါမယ်။"), parse_mode='html')
    
    mention_html = f"<a href='tg://user?id={target_user.id}'>💥{escape_html(target_user.first_name or 'Target')}💥</a> "
    bomb_text = mention_html * 15

    try: await event.delete()
    except: pass

    total_bombs = 12
    sent_messages = []

    for i in range(total_bombs):
        try:
            msg = await bot1.send_message(event.chat_id, bomb_text, parse_mode='html')
            sent_messages.append(msg)
            if len(sent_messages) == 4:
                await asyncio.sleep(0.5) 
                await bot1.delete_messages(event.chat_id, sent_messages)
                sent_messages.clear()
            await asyncio.sleep(0.8) 
        except: break

    if sent_messages:
        await asyncio.sleep(0.5)
        try: await bot1.delete_messages(event.chat_id, sent_messages)
        except: pass

@bot1.on(events.NewMessage(pattern=r'^/shadow(?:@\w+)?$'))
async def set_shadow_ban(event):
    if not await is_allowed(event.sender_id): return
    reply = await event.get_reply_message()
    if not reply or reply.sender_id == OWNER_ID: return await event.respond(bq("Target ကို Reply ထောက်ပြီး /shadow ပေးပါ Chief။"))
    dark_passenger_targets[event.chat_id] = reply.sender_id
    try: await event.delete()
    except: pass
    await event.respond(bq(f"👤 {escape_html((await reply.get_sender()).first_name or 'Target')} ရဲ့ နောက်ကွယ်မှာ Dark Passenger ကပ်လိုက်ပါပြီ။"))

@bot1.on(events.NewMessage(pattern=r'^/unshadow(?:@\w+)?$'))
async def remove_shadow_ban(event):
    if not await is_allowed(event.sender_id): return
    try: await event.delete()
    except: pass
    if event.chat_id in dark_passenger_targets:
        del dark_passenger_targets[event.chat_id]
        await event.respond(bq("Dark Passenger ပြန်လည်ထွက်ခွာသွားပါပြီ။"))

@bot1.on(events.NewMessage(pattern=r'^လိုက်မှတ်$'))
async def turn_on_learning(event):
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    learning_status[SPECIFIC_CONTROL_GROUP] = True
    await event.reply(bq("ဒီ Group တစ်ခုတည်းအတွက်ပဲ စကားများမှတ်သားခြင်း စနစ် ဖွင့်လိုက်ပြီ။"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^မမှတ်နဲ့တော့$'))
async def turn_off_learning(event):
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    learning_status[SPECIFIC_CONTROL_GROUP] = False
    await event.reply(bq("ဒီ Group အတွက် စကားများမှတ်သားခြင်း စနစ် ပိတ်လိုက်ပြီ။"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^စကားဝင်ပြော$'))
async def turn_on_talking(event):
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    global GLOBAL_TALK
    GLOBAL_TALK = True
    try:
        groups = await groups_col.find().to_list(length=None)
        for g in groups:
            chat_id = int(g['chat_id'])
            talking_status[chat_id] = True
            message_counts[chat_id] = 0
    except: pass
    await event.reply(bq("ဟုတ် ငါတို့လည်းပျင်းလို့ Group အားလုံးမှာ စကားဝင်ပြောမယ်"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^မပြောနဲ့တော့$'))
async def turn_off_talking(event):
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    global GLOBAL_TALK
    GLOBAL_TALK = False
    talking_status.clear()
    await event.reply(bq("Group အားလုံးမှာ ငါတို့စကားပြောတော့ဘူး နားပြီ"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^ချိန်ထား$'))
async def aim_target(event):
    if not await is_allowed(event.sender_id): return
    reply = await event.get_reply_message()
    if not reply or reply.sender_id == OWNER_ID: return 
    name = escape_html((await event.get_sender()).first_name)
    msg = f"<a href='tg://user?id={event.sender_id}'>{name}</a> ရဲ့ အမိန့်ပေးမှုအရ ဒီကောင့်ကို ပစ်သတ်ဖို့ အသင့်ချိန်ထားပါပြီ။" if event.sender_id == OWNER_ID else f"ဗိုလ်ကြီး <a href='tg://user?id={event.sender_id}'>{name}</a> ရဲ့ အမိန့်ပေးမှုအရ ဒီကောင့်ကို ပစ်သတ်ဖို့ အသင့်ချိန်ထားပြီ ။"
    await bot1.send_message(event.chat_id, msg, reply_to=reply.id, parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^ပစ်သတ်$'))
async def fire_target(event):
    if not await is_allowed(event.sender_id): return
    reply = await event.get_reply_message()
    if not reply or reply.sender_id == OWNER_ID: return
    try: await event.delete()
    except: pass

    chat_id = event.chat_id
    target = await reply.get_sender()
    shoot_tasks[chat_id] = True 
    mention = f"<a href='tg://user?id={target.id}'>{escape_html(target.first_name)}</a>"
    
    db_filters = await filters_col.find().to_list(length=None)
    words = [w.get("text") for w in db_filters if w.get("text")]
    if not words: words = ["သေစမ်း", "အပြတ်ရှင်းမယ်"]

    # ⚠️ Single Bot ဖြစ်သွားလို့ Rate Limit မငြိအောင် Delay ပြင်ပေးထားတယ်
    while shoot_tasks.get(chat_id):
        try:
            await bot1.send_message(chat_id, f"{mention} {random.choice(words)}", parse_mode='html')
            await asyncio.sleep(1.2) 
        except: break

@bot1.on(events.NewMessage(pattern=r'^ပစ်$'))
async def track_target(event):
    if not await is_allowed(event.sender_id): return
    reply = await event.get_reply_message()
    if not reply or reply.sender_id == OWNER_ID: return

    tracking_targets[event.chat_id] = reply.sender_id
    name = escape_html((await reply.get_entity()).first_name)
    await event.respond(f" {name} ကို ပစ်မှတ်ထားလိုက်ပြီ။")

@bot1.on(events.NewMessage(pattern=r'^(ရပ်|အပစ်ရပ်)$'))
async def stop_actions(event):
    if not await is_allowed(event.sender_id): return
    try: await event.delete()
    except: pass
    chat_id = event.chat_id
    shoot_tasks[chat_id] = False
    if chat_id in tracking_targets: del tracking_targets[chat_id]
    await event.reply("ငါ ဒီခွေးမသားကို အ​သေသတ်ပေးထားတယ်။ပြန်ရှင်သန်ခွင့် မပေးဘူး")

# [DARK PASSENGER & MAIN WATCHER LOGIC]
@bot1.on(events.NewMessage())
async def dark_passenger_watcher(event):
    chat_id = event.chat_id
    sender_id = event.sender_id

    # 1. Dark Passenger (Shadow Ban) Check
    if chat_id in dark_passenger_targets and sender_id == dark_passenger_targets[chat_id]:
        if event.text and not event.text.startswith(('/', '.', 'မှတ်')):
            try:
                await event.delete()
                u_name = (await event.get_sender()).first_name or "Target"
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(u_name)}</a>"
                fake_words = [
                    f"{mention} really thought he cooked with that message… whole thing came out raw. - crd to Morgan",
                    f"Morgan ရဲ့ Domain ထဲ ရောက်နေတာတောင် နေရာတကာ လာအာချင်နေတယ် {mention}။ Quiet down fr.",
                    f"မင်းရဲ့ အသိစိတ်တွေ တဖြည်းဖြည်း ပျောက်ကွယ်သွားလိမ့်မယ် {mention}။ You are being erased."
                ]
                await event.respond(bq(random.choice(fake_words)), parse_mode='html')
            except: pass
        return

    # 2. Main Bot Defense, Auto-Talk & Tracking 
    if event.is_private or not event.text or sender_id in bot_ids: return
    text = event.text.strip()
    reply = await event.get_reply_message()

    # Protection against targeting Owner
    protection_cmds = ["ချိန်ထား", "ပစ်သတ်"]
    if any(text.startswith(c) for c in protection_cmds):
        if reply and reply.sender_id == OWNER_ID and event.sender_id != OWNER_ID:
            db_filters = await filters_col.find().to_list(length=None)
            words = [w.get("text") for w in db_filters if w.get("text")] or ["Chief ကို လာမစမ်းနဲ့!"]
            mention = f"<a href='tg://user?id={event.sender_id}'>{escape_html((await event.get_sender()).first_name)}</a>"
            await bot1.send_message(chat_id, f"{mention} {random.choice(words)}", parse_mode='html')
            return

        if not await is_allowed(event.sender_id):
            name = escape_html((await event.get_sender()).first_name)
            await bot1.send_message(chat_id, f"{name}.မင်းကဘာကောင်မို့လို့ ငါ့စီမှာ အမိန့်လာပေးနေတာလဲ? မင်းကိုပါ ငါ ပစ်သတ်ဖို့ အသင့်ချိန်ထားလိုက်ပြီ။", reply_to=event.id)
            return

    # Random Talking System
    if (GLOBAL_TALK or talking_status.get(chat_id) is True) and not text.startswith(('/', '.', 'မှတ်')):
        if chat_id not in message_counts: message_counts[chat_id] = 0
        message_counts[chat_id] += 1
        
        if message_counts[chat_id] >= 4: 
            message_counts[chat_id] = 0
            pipeline = [{"$match": {"text": {"$not": re.compile(r"tg://user\?id=")}}}, {"$sample": {"size": 1}}]
            random_talk = await talk_col.aggregate(pipeline).to_list(length=1)
            if random_talk:
                try: await bot1.send_message(chat_id, random_talk[0]['text'])
                except: pass

    # Tracking System (`ပစ်` ဖြင့် မှတ်ထားသူ)
    if chat_id in tracking_targets and sender_id == tracking_targets[chat_id]:
        db_filters = await filters_col.find().to_list(length=None)
        words = [w.get("text") for w in db_filters if w.get("text")] or ["Strong Enemy!"] 
        try:
            u_name = escape_html((await event.get_sender()).first_name)
            await bot1.send_message(chat_id, f"<a href='tg://user?id={sender_id}'>{u_name}</a> {random.choice(words)}", parse_mode='html')
        except: pass

    # Message Learning
    if learning_status.get(chat_id, False) and not text.startswith(('/', '.', 'မှတ်', '@')):
        talker = await talker_col.find_one({"user_id": sender_id})
        if talker and len(text) > 1 and not re.search(r'https?://', text):
            await talk_col.insert_one({"text": text, "nickname": talker.get("nickname", "Anonymous"), "chat_id": chat_id})
# ====================================================================================
# 🎭 MORGAN AUTOMATIC TALK SYSTEM (STRICT OWNER DM & GROUP TRIGGER)
# ====================================================================================

# 👑 OWNER DM COMMAND: Morgan စာသင်စနစ် ဖွင့်ခြင်း (/ron)
@bot1.on(events.NewMessage(pattern=r'^/ron$'))
async def turn_on_morgan_training(event):
    global TRAINING_ENABLED_MORGAN
    if not event.is_private or event.sender_id != OWNER_ID:
        return
        
    TRAINING_ENABLED_MORGAN = True
    await event.reply("✅ Morgan Training Mode ကို ဖွင့်လိုက်ပါပြီ။\nယခုမှစ၍ Bot DM တွင် စာသားများကို အစုလိုက် (\" \" ခံပြီး) ပို့နိုင်ပါပြီ ဆရာကြီး။")

# 👑 OWNER DM COMMAND: Morgan စာသင်စနစ် ပိတ်ခြင်း (/roff)
@bot1.on(events.NewMessage(pattern=r'^/roff$'))
async def turn_off_morgan_training(event):
    global TRAINING_ENABLED_MORGAN
    if not event.is_private or event.sender_id != OWNER_ID:
        return
        
    TRAINING_ENABLED_MORGAN = False
    await event.reply("⛔ Morgan Training Mode ကို ပိတ်လိုက်ပါပြီ။")

# 📝 DM TRAINING: Owner ပို့လိုက်သော အဖြေ ၁၀၀ အစုလိုက်ကို ဖတ်ပြီး DB တွင် သိမ်းခြင်း
@bot1.on(events.NewMessage(incoming=True))
async def save_morgan_bulk_messages(event):
    global TRAINING_ENABLED_MORGAN
    # Owner ဖြစ်ပြီး DM ဖြစ်ရမည်၊ Command မဟုတ်ရပါ
    if not event.is_private or event.sender_id != OWNER_ID or event.text.startswith('/'):
        return
    
    # /ron မလုပ်ထားရင် အလုပ်မလုပ်ပါ
    if not TRAINING_ENABLED_MORGAN:
        return

    # မျက်တောင်အဖွင့်အပိတ် " " ထဲက စာသားများကို ရှာဖွေခွဲထုတ်ခြင်း
    new_responses = re.findall(r'"([^"]*)"', event.text)
    
    if not new_responses:
        return await event.reply("❌ အဖြေများကို မျက်တောင်အဖွင့်အပိတ် \" \" ထဲတွင် တစ်ကြောင်းချင်းစီ ထည့်ပေးပါဗျာ။")

    # DB ထဲသို့ Bulk Insert (အစုလိုက်) တစ်ခါတည်း သိမ်းဆည်းခြင်း
    documents = [{"text": r.strip()} for r in new_responses if r.strip()]
    if documents:
        await morgan_col.insert_many(documents)
        await event.reply(f"✨ Morgan စကားပြောစနစ်အတွက် စာသားအသစ် ({len(documents)} ခု) ကို DB တွင် အောင်မြင်စွာ မှတ်သားပြီးပါပြီဗျာ!")

# 💬 GROUP CHAT WATCHER: စာ ၁၀ ကြောင်းပြည့်တိုင်း #morgan ဖြင့် ဝင်ပြောခြင်း
@bot1.on(events.NewMessage(incoming=True))
async def morgan_group_counter_handler(event):
    global group_msg_counters
    
    # Private chat ဖြစ်နေရင် သို့မဟုတ် စာသားမပါရင် သို့မဟုတ် Command တွေဖြစ်ရင် ကျော်မယ် (Group မျိုးစုံမှာ အလုပ်လုပ်စေရန်)
    if event.is_private or not event.text or event.text.startswith(('/', '.', 'မှတ်')):
        return
        
    chat_id = event.chat_id
    
    # သက်ဆိုင်ရာ Group အလိုက် Message အရေအတွက်ကို တစ်တိုးခြင်း
    group_msg_counters[chat_id] = group_msg_counters.get(chat_id, 0) + 1
    
    # စာ ၄ စောင်ပြည့်သွားသောအခါ
    if group_msg_counters[chat_id] >= 100:
        group_msg_counters[chat_id] = 0 # Counter ကို ၀ ပြန်လုပ်မယ်
        
        # morgan_col ထဲကနေ ကျပန်း စာတစ်ကြောင်း နှိုက်ယူခြင်း
        pipeline = [{"$sample": {"size": 1}}]
        async for doc in morgan_col.aggregate(pipeline):
            morgan_text = doc.get("text")
            if morgan_text:
                # ရိုရိုသေသေ Reply မထောက်တော့ဘဲ Group ထဲကို Normal Message အနေနဲ့ပဲ လှမ်းပို့ပါမယ် ဆရာကြီး
                await event.client.send_message(chat_id, f"{morgan_text}\n\n#Morgan")
                break

# ==========================================
# 🚀 START SYSTEM
# ==========================================
async def start_system():
    threading.Thread(target=run_flask, daemon=True).start()
    print("Starting Main Bot (Sovereign System)...")
    
    await bot1.start(bot_token=MAIN_BOT_TOKEN)
    me_main = await bot1.get_me()
    bot_ids.append(me_main.id)
    bot_names.append(me_main.first_name)
    
    print(f"✅ BoD Sovereign System Online with 1 Main Bot!")
    print(f"🤖 Bot Name: {me_main.first_name}")
    
    await bot1.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(start_system())

