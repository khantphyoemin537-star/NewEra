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
from telethon.tl.types import User
from html import escape as escape_html
from telethon import TelegramClient, events, types, Button, errors

# --- ERROR ဖြစ်စေတဲ့ GetParticipants ကို ဖယ်ရှားပြီး သေချာ ပြန်ပြင်ထားတဲ့အပိုင်း ---
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
MONGO_URI = "mongodb+srv://khantphyoemin537_db_user:9VRKiaeZkz7rJdpz@cluster0.w6tgi8j.mongodb.net/?appName=Cluster0&tlsAllowInvalidCertificates=true"
APP_ID = 35766004
APP_HASH = 'd15b4226b81724722279bae6af69e22d'

# [Bot 1] Main Sovereign Bot
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

# 👈 GLOBAL STATE FOR REPLY SAVE AUTO RESPONDER
IS_REPLY_ACTIVE = False              
reply_msg_counters = {}              

# ==========================================
# 🛠️ HELPERS & FILTERS
# ==========================================
def bq(text): return f"<blockquote><b>{text}</b></blockquote>"

def owner_tag():
    return f"<a href='tg://user?id={OWNER_ID}'>Hello_Im_DexterMorgan</a>"

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
    """ စာသားထဲတွင် Mention များ၊ Link များ ပါဝင်နေမှု ရှိမရှိ စိစစ်ခြင်း """
    if not message_text:
        return False
    if '@' in message_text or 't.me/' in message_text or 'http' in message_text:
        return True
    return False

# ====================================================================================
# 🧠 HIGH-PERFORMANCE SMART REPLY SEARCH ENGINE (FIXED LOGIC)
# ====================================================================================
async def fetch_optimized_smart_reply(user_text):
    """ reply_save_col ထဲမှ trigger သည် user_text ထဲတွင် ပါဝင်မှု ရှိမရှိ အမြန်ဆုံး ရှာဖွေပေးသည့် စနစ် """
    reply_text = None
    user_text_clean = user_text.strip().lower()

    # 🎯 CORRECT PIPELINE: လူပို့လိုက်တဲ့စာထဲမှာ DB က trigger ပါဝင်နေသလားကို $indexOfCP နဲ့ ရှာဖွေခြင်း
    match_pipeline = [
        {"$match": {
            "$expr": {
                "$and": [
                    {"$gte": [{"$strLenCP": "$trigger"}, 2]}, # trigger စာသား အနည်းဆုံး ၂ လုံးနှင့်အထက်ဖြစ်ရမည်
                    {"$gte": [{"$indexOfCP": [user_text_clean, {"$toLower": "$trigger"}]}, 0]} # လူ့စာသားထဲတွင် trigger ပါဝင်နေရမည်
                ]
            }
        }},
        {"$sample": {"size": 1}} # ကိုက်ညီတာတွေထဲကမှ random ၁ ခု ဆွဲထုတ်ခြင်း
    ]

    try:
        cursor = reply_save_col.aggregate(match_pipeline)
        matched_docs = await cursor.to_list(length=1)
        if matched_docs and matched_docs[0].get("responses"):
            chosen = random.choice(matched_docs[0]["responses"])
            if not has_mention_or_link(chosen):
                reply_text = chosen
    except Exception as e:
        print(f"Smart Reply DB Error: {e}")
        reply_text = None

    # Fallback Mechanism: ကိုက်ညီမှုမရှိပါက random_talk ထဲမှ အမြန်ဆွဲထုတ်ခြင်း
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

    # နောက်ဆုံးပိတ် လုံးဝရှာမတွေ့မှ သုံးမည့် Default စကားလုံးများ
    if not reply_text:
        default_phrases = ["ဟုတ်ပဗျာ", "အေးပါဗျာ", "ဒါနဲ့လေ...", "ဟီးဟီး", "ဟုတ်လား Chief", "အော်... အင်း"]
        reply_text = random.choice(default_phrases)

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
                msg2 = f"မင်္ဂလာပါ {safe_title}က \n{bot_mention}ထည့်သုံးထားပါသေးတယ်\n\nGroup Name - {safe_title}\nGroup ID - <code>{chat.id}</code>\nMembers အရေအတွက် - {members}\nBot Creator - {owner_tag}"
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
                                [Button.url("Also Join Our Group", "https://t.me/Comeback_BoD")]
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
TRAINING_ENABLED = True

@bot1.on(events.NewMessage(pattern=r'^/ron$'))
async def turn_on_training(event):
    global TRAINING_ENABLED
    if event.sender_id != OWNER_ID: return
    TRAINING_ENABLED = True
    await event.reply("✅ Sovereign Training Mode ကို ဖွင့်လိုက်ပါပြီ။\nယခုမှစ၍ /r ဖြင့် စာသင်နိုင်ပါသည်။")

@bot1.on(events.NewMessage(pattern=r'^/roff$'))
async def turn_off_training(event):
    global TRAINING_ENABLED
    if event.sender_id != OWNER_ID: return
    TRAINING_ENABLED = False
    await event.reply("⛔ Sovereign Training Mode ကို ပိတ်လိုက်ပါပြီ။\nယခုတွင် /r Command အသုံးပြု၍ မရနိုင်တော့ပါ။")

@bot1.on(events.NewMessage(pattern=r'^/r(\s+.*)?$'))
async def train_bot(event):
    global TRAINING_ENABLED
    if not TRAINING_ENABLED:
        await event.reply("⚠️ လက်ရှိတွင် Owner မှ Chatbot Training Mode ကို ပိတ်ထားပါတယ်ဗျာ။")
        return
    if not event.is_reply:
        await event.reply("❌ အသုံးပြုပုံ မှားယွင်းနေပါသည်။\nအဖြေများပါသော စာသားကို Reply ပြန်ပြီး `/r [မေးခွန်း]` ဟု ရိုက်ပေးပါ။")
        return
    args = event.pattern_match.group(1)
    if not args:
        await event.reply("❌ မေးခွန်း (Keyphrase) ထည့်သွင်းပေးရန် လိုအပ်ပါသည်။")
        return
        
    keyphrase = args.strip().lower()
    reply_msg = await event.get_reply_message()
    if not reply_msg or not reply_msg.text:
        await event.reply("❌ စာသား (Text) ပါဝင်သော Message ကိုသာ သင်ပေး၍ ရပါမည်။")
        return

    new_responses = re.findall(r'"([^"]*)"', reply_msg.text)
    if not new_responses:
        await event.reply("❌ အဖြေများကို မျက်တောင်အဖွင့်အပိတ် \" \" ထဲတွင် တစ်ကြောင်းချင်းစီ ထည့်ပေးပါဗျာ။")
        return

    existing_doc = await ans_col.find_one({"keyphrase": keyphrase})
    if existing_doc:
        existing_responses = existing_doc.get("responses", [])
        updated_responses = list(set(existing_responses + new_responses))
        await ans_col.update_one({"keyphrase": keyphrase}, {"$set": {"responses": updated_responses}})
        action_msg = f"အဖြေအသစ်များကို ပေါင်းထည့်လိုက်ပါပြီ။ (စုစုပေါင်းအဖြေ: {len(updated_responses)} ခု)"
    else:
        await ans_col.insert_one({"keyphrase": keyphrase, "responses": new_responses})
        action_msg = "အစုံလိုက် အသစ်စက်စက် :)"

    debug_list = "\n".join([f"• {r}" for r in new_responses])
    await event.reply(f"✨ စကားလုံးအသစ် မှတ်သားမှု အောင်မြင်သည်!\n🔑 Key: {keyphrase}\n📝 ခွဲထုတ်ရရှိသည့် အဖြေများ ({len(new_responses)} ခု):\n{debug_list}\n\n💡 {action_msg}")

# ====================================================================================
# 🧹 DISMISS DELETED ADMINS SYSTEM
# ====================================================================================
@bot1.on(events.NewMessage(pattern=r'^/dismiss$'))
async def dismiss_deleted_admins(event):
    if not event.is_group: return await event.reply("❌ ဒီ Command ကို Group များထဲတွင်သာ အသုံးပြုနိုင်ပါသည်။")
    if not await is_allowed(event.sender_id): return

    status_msg = await event.reply("🔍 <i>Admin စာရင်းထဲရှိ Deleted Accounts များကို ရှာဖွေနေပါသည်...</i>", parse_mode='html')
    chat_id = event.chat_id
    deleted_admins_count = 0
    dismissed_count = 0
    failed_count = 0

    try:
        async for participant in event.client.iter_participants(chat_id, filter=ChannelParticipantsAdmins):
            user = participant.user
            if isinstance(participant, ChannelParticipantCreator): continue
            if user.deleted:
                deleted_admins_count += 1
                try:
                    await event.client.edit_admin(
                        chat_id, user.id, change_info=False, post_messages=False, edit_messages=False,
                        delete_messages=False, ban_users=False, invite_users=False, pin_messages=False,
                        add_admins=False, manage_call=False
                    )
                    dismissed_count += 1
                except Exception:
                    failed_count += 1

        if deleted_admins_count == 0:
            await status_msg.edit("✅ <b>စစ်ဆေးမှု ပြီးဆုံးပါပြီ။</b>\n\nဒီ Group ရဲ့ Admin စာရင်းထဲမှာ Deleted Account တစ်ခုမှ မရှိပါဘူး Chief!", parse_mode='html')
        else:
            result_text = (
                "🧹 <b>⚚ 𝘽𝙤延𝙭  - 𝘼𝘿𝙈𝙄index 𝘾𝙇𝙀𝘼𝙉𝙀𝙍</b> 🧹\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"💀 <b>တွေ့ရှိရသော Deleted Admins:</b> <code>{deleted_admins_count} ဦး</code>\n"
                f"✅ <b>အောင်မြင်စွာ ဖြုတ်ချပြီး:</b> <code>{dismissed_count} ဦး</code>\n"
                f"❌ <b>ဖြုတ်ချ၍မရသော အရေအတွက်:</b> <code>{failed_count} ဦး</code>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            await status_msg.edit(result_text, parse_mode='html')
    except Exception as e:
        await status_msg.edit(f"❌ <b>Error:</b>\n<code>{e}</code>", parse_mode='html')

# 💬 AUTOMATIC CHAT RESPONDER
@bot1.on(events.NewMessage(incoming=True))
async def chatbot_auto_responder(event):
    if event.is_private or not event.text or event.text.startswith(('/', '.', 'မှတ်','@')): return
    user_text = event.text.lower()
    cursor = ans_col.find()
    async for doc in cursor:
        keyphrase = doc.get("keyphrase")
        if keyphrase and keyphrase in user_text:
            responses = doc.get("responses", [])
            if responses:
                await event.reply(random.choice(responses))
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

    if not text_to_save and not media_to_save: return

    await welcome_col.update_one(
        {"chat_id": event.chat_id},
        {"$set": {"text": text_to_save, "media": media_to_save}},
        upsert=True
    )
    await event.respond(bq(f"✅ <b>{escape_html(event.chat.title)}</b> အတွက် Welcome Message ကို မှတ်သားလိုက်ပါပြီ။"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^/mute(?:@\w+)?(?:\s+(.*))?'))
async def mute_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    args = event.pattern_match.group(1)
    reply = await event.get_reply_message()
    target_user = None
    if reply: target_user = reply.sender
    elif args:
        try: target_user = await bot1.get_entity(int(args.strip()) if args.strip().lstrip('-').isdigit() else args.strip())
        except Exception: return

    if not target_user: return
    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, send_messages=False)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User'))}</a>"
        await event.respond(f"🔇 {mention} ကို Mute လိုက်ပါပြီ!", parse_mode='html')
    except Exception: pass

@bot1.on(events.NewMessage(pattern=r'^/unmute(?:@\w+)?(?:\s+(.*))?'))
async def unmute_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id): return
    args = event.pattern_match.group(1)
    reply = await event.get_reply_message()
    target_user = None
    if reply: target_user = reply.sender
    elif args:
        try: target_user = await bot1.get_entity(int(args.strip()) if args.strip().lstrip('-').isdigit() else args.strip())
        except Exception: return

    if not target_user: return
    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, send_messages=True)
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(getattr(target_user, 'first_name', 'User'))}</a>"
        await event.respond(f"🔊 {mention} ကို Unmute လုပ်ပြီးပြီ!", parse_mode='html')
    except Exception: pass

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
    except Exception: pass

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

@bot1.on(events.NewMessage(pattern=r'^/ပို့(?:@\w+)?(?:\s+(.*))?'))
async def broadcast(event):
    if event.sender_id != OWNER_ID: return
    reply_msg = await event.get_reply_message()
    command_text = event.pattern_match.group(1)
    
    if not reply_msg and not command_text: return
    success, fail = 0, 0
    status_msg = await event.respond(bq("📢 Broadcast စတင်နေပါပြီ..."))
    groups = await groups_col.find().to_list(length=None)

    for g in groups:
        try:
            if reply_msg: await bot1.forward_messages(g['chat_id'], reply_msg)
            else: await bot1.send_message(g['chat_id'], command_text, parse_mode='html')
            success += 1
            await asyncio.sleep(0.5) 
        except Exception:
            fail += 1
    await status_msg.edit(f"✅ <b>အောင်မြင်သော Group:</b> {success}\n❌ <b>ကျရှုံးသော Group:</b> {fail}", parse_mode='html')

@bot1.on(events.NewMessage())
async def protection_logic(event):
    if event.is_private or not event.text or event.sender_id == OWNER_ID or event.sender_id in bot_ids: return
    text, chat_id, sender_id = event.text.strip(), event.chat_id, event.sender_id

    if re.search(r'/harem(@\w+)?', text) or re.search(r'/waifu(@\w+)?', text):
        try:
            sender = await event.get_sender()
            mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name)}</a>"
            asyncio.create_task(event.delete())
            warn_msg = await event.respond(bq(f"Chat သန့်ရှင်းအောင် ဖျက်လိုက်ပါပြီ။"))
            await asyncio.sleep(2)
            await warn_msg.delete()
            return 
        except: pass

    if any(key in text for key in ["Bio", "bio", "ဘိုင်အို", "ဘိုင်-အို", "ဘိုင်-O", "ဘီအိုင်အို"]) and not await check_admin(chat_id, sender_id):
        try: return await event.delete()
        except: pass

    urls = re.findall(r'(https?://\S+|www\.\S+)', text)
    if urls and not (event.audio or event.voice):
        if await check_admin(chat_id, sender_id):
            try:
                f_msg = await bot1.forward_messages(event.chat_id, event.message)
                await event.delete()
            except: pass
        else:
            try: await event.delete() 
            except: pass

@bot1.on(events.NewMessage(pattern=r'^/play(?:\s+(.*))?'))
async def play_response(event):
    if event.is_private: return
    song_title = event.pattern_match.group(1)
    if not song_title: return 
    try:
        await event.delete()
        mention = f"<a href='tg://user?id={event.sender_id}'>{escape_html((await event.get_sender()).first_name)}</a>"
        msg = await event.respond(bq(f"🎧 Song Title- {escape_html(song_title)}\nသီချင်းဖွင့်သူ- {mention}"))
        await asyncio.sleep(3)
        await msg.delete()
    except: pass

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

@bot1.on(events.NewMessage())
async def custom_filter_watcher(event):
    if event.is_private or not event.text or event.sender_id in bot_ids: return
    user_msg = event.text.lower().strip()
    async for item in custom_filters_col.find():
        keyword = item["keyword"].lower().strip()
        if user_msg == keyword:
            try:
                if item["type"] == "text": await event.reply(item["content"])
                else: await event.reply(file=item["content"])
                break 
            except: pass

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
    await event.reply(bq("Group အားလုံးမှာ စကားဝင်ပြောမယ်"))

@bot1.on(events.NewMessage(pattern=r'^မပြောနဲ့တော့$'))
async def turn_off_talking(event):
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    global GLOBAL_TALK
    GLOBAL_TALK = False
    await event.reply(bq("Group အားလုံးမှာ စကားမပြောတော့ဘူး"))

@bot1.on(events.NewMessage(pattern=r'^(ရပ်|အပစ်ရပ်)$'))
async def stop_actions(event):
    if not await is_allowed(event.sender_id): return
    shoot_tasks[event.chat_id] = False
    if event.chat_id in tracking_targets: del tracking_targets[event.chat_id]
    await event.reply("အပစ်ရပ်စဲလိုက်ပြီ။")

# [DARK PASSENGER WATCHER LOGIC]
@bot1.on(events.NewMessage())
async def dark_passenger_watcher(event):
    chat_id = event.chat_id
    sender_id = event.sender_id
    if chat_id in dark_passenger_targets and sender_id == dark_passenger_targets[chat_id]:
        if event.text and not event.text.startswith(('/', '.', 'မှတ်')):
            try:
                await event.delete()
                fake_words = ["You are being erased.", "Quiet down...", "Morgan ရဲ့ Domain ထဲရောက်နေတာ။"]
                await event.respond(bq(random.choice(fake_words)), parse_mode='html')
            except: pass

# ====================================================================================
# 🎭 MORGAN AUTOMATIC TALK SYSTEM
# ====================================================================================
@bot1.on(events.NewMessage(incoming=True))
async def save_morgan_bulk_messages(event):
    global TRAINING_ENABLED_MORGAN
    if not event.is_private or event.sender_id != OWNER_ID or event.text.startswith('/'): return
    if not TRAINING_ENABLED_MORGAN: return
    new_responses = re.findall(r'"([^"]*)"', event.text)
    if not new_responses: return
    documents = [{"text": r.strip()} for r in new_responses if r.strip()]
    if documents:
        await morgan_col.insert_many(documents)
        await event.reply(bq(f"Morgan စာသားအသစ် ({len(documents)} ခု) သိမ်းပြီးပါပြီ။"))

# ====================================================================================
# 👈 [ADVANCED & HIGH-SPEED] REPLY SAVE AUTO RESPONDER SYSTEM (NON-BLOCKING)
# ====================================================================================

# 👑 OWNER COMMAND: စာလိုက်ထောက်စနစ်ဖွင့်ခြင်း (/ဟိုက်)
@bot1.on(events.NewMessage(pattern=r'^/ktr$'))
async def turn_on_reply_save_match(event):
    global IS_REPLY_ACTIVE
    if event.sender_id != OWNER_ID: return
    IS_REPLY_ACTIVE = True
    await event.reply(bq("🎯 စာလိုက်ထောက်စနစ် (Auto-Responder) ကို Group အားလုံးအတွက် ဖွင့်လိုက်ပါပြီ Chief!"), parse_mode='html')

# 👑 OWNER COMMAND: စာလိုက်ထောက်စနစ်ပိတ်ခြင်း (/ဟိုက်း)
@bot1.on(events.NewMessage(pattern=r'^/ktrr$'))
async def turn_off_reply_save_match(event):
    global IS_REPLY_ACTIVE
    if event.sender_id != OWNER_ID: return
    IS_REPLY_ACTIVE = False
    await event.reply(bq("⛔ စာလိုက်ထောက်စနစ်ကို ပိတ်လိုက်ပါပြီ မောလို့ နားဦးမယ် Chief!"), parse_mode='html')

async def processed_background_reply(event, user_text):
    """ Non-blocking Background Worker: Database ရှာဖွေခြင်းနှင့် စာပြန်ခြင်းများကို သီးခြားလုပ်ဆောင်ပေးသည် """
    chat_entity = await event.get_input_chat()
    
    # 🧠 DB ထဲကနေ Context ကိုက်ညီမယ့် စမတ်အဖြေကို စိစစ်ပြီး အမြန်ဆုံးဆွဲထုတ်ခြင်း
    smart_reply = await fetch_optimized_smart_reply(user_text)
    
    if smart_reply:
        try:
            # စက်ရုပ်လို ချက်ချင်းကြီးမဖြစ်ဘဲ လူလိုသဘာဝကျကျ ဖြစ်သွားစေရန် Typing ပြခြင်း
            async with bot1.action(chat_entity, 'typing'):
                await asyncio.sleep(random.uniform(1.0, 2.2))
                
            # ၅ ကြောင်းမြောက် Message ကို တရားဝင် ထောက်ပြီး Reply ပြန်ပေးခြင်း
            await event.reply(smart_reply)
        except errors.rpcerrorlist.FloodWaitError as e:
            await asyncio.sleep(e.seconds)
        except Exception:
            pass

# 💬 ၅ ကြောင်းမြောက် မက်ဆေ့ခ်ျတိုင်းအား စိစစ်ပြီး သဘာဝကျကျ တုံ့ပြန်မည့် Engine
@bot1.on(events.NewMessage(incoming=True))
async def reply_save_counter_handler(event):
    global reply_msg_counters, IS_REPLY_ACTIVE
    
    # System Switch စစ်ဆေးခြင်း
    if not IS_REPLY_ACTIVE: return
    if event.is_private or not event.text or event.text.startswith(('/', '.', 'မှတ်', '@')): return
    
    # Bot ကိုယ်တိုင် ပို့တာဆိုရင် ကျော်မယ်
    sender = await event.get_sender()
    if sender and sender.bot: return

    chat_id = event.chat_id
    reply_msg_counters[chat_id] = reply_msg_counters.get(chat_id, 0) + 1
    
    # 🎯 အတိအကျ ၅ ကြောင်းမြောက်သို့ ရောက်ရှိလာချိန်
    if reply_msg_counters[chat_id] >= 2:
        reply_msg_counters[chat_id] = 0 # Counter ပြန်သတ်မှတ်ခြင်း
        
        user_text = event.text.strip()
        
        # 🚀 CRITICAL OPTIMIZATION: Main Event Loop မပိတ်ဆို့သွားစေရန် Background Task အဖြစ် လွှဲပြောင်းပေးခြင်း
        asyncio.create_task(processed_background_reply(event, user_text))

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

