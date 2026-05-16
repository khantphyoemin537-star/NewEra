import io
import asyncio
import logging
import random
import os
import threading
import re
from datetime import datetime, timedelta
import pytz
from flask import Flask
# 🛠️ pymongo အစား motor ကို ပြောင်းသုံးထားပါတယ်
from motor.motor_asyncio import AsyncIOMotorClient
from telethon.tl.types import User
from html import escape as escape_html
from telethon import TelegramClient, events, types, Button 
from telethon.tl.functions.channels import GetParticipantRequest
from telethon.tl.types import (
    ChannelParticipantAdmin, 
    ChannelParticipantCreator, 
    ChannelParticipantsAdmins,
    ChatAdminRights
)
from html import escape as escape_html
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
def home(): return "BoDx Sovereign System & Guard Squad Active!"

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
MAIN_BOT_TOKEN = "8338525059:AAEMDI6gBX0hzcCozymzVV7EmgDeh_73jeA"

# [Bots 2-5] Guard / Shooter Squad
SQUAD_TOKENS = [
    "8498307038:AAHlikDQK1kN49_XEpogM_uAzUYmV3D6RyU",
    "8449026098:AAH2GZB8NGsHWirxPc-Kpz-8wVsx-zEhjzk",
    "8547705095:AAG4BJZb04jAjT_yNeOA4N_A_fM-iWon05A",
    "8666805453:AAFChDLiNU0p4YmA7apAkpT-PQi0OcuE2LQ"
]

SPECIFIC_GROUP = -1003580630981 
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

# ==========================================
# 🤖 CLIENTS SETUP
# ==========================================
bot1 = TelegramClient('bot_main_session', APP_ID, APP_HASH)
squad_bots = [TelegramClient(f'bot_squad_{i}', APP_ID, APP_HASH) for i in range(len(SQUAD_TOKENS))]
squad_master = squad_bots[0]

all_bots = [bot1] + squad_bots
bot_ids = []
bot_names = []

# ==========================================
# 📊 STATE VARIABLES
# ==========================================
sticker_spam_data = {}
bot_bully_tasks = {}      
shoot_tasks = {}          
tracking_targets = {} 
dark_passenger_targets = {}
learning_status = {}      
talking_status = {}       
message_counts = {}       
GLOBAL_TALK = False 
# ==========================================
# 🛠️ HELPERS (ASYNC REFRACTORED)
# ==========================================
def bq(text): return f"<blockquote><b>{text}</b></blockquote>"

def owner_tag():
    return f"<a href='tg://user?id={OWNER_ID}'>Khant Thu Rain</a>"

async def is_allowed(user_id):
    if user_id == OWNER_ID: return True
    # Motor Call ကို await သုံးထားပါတယ်
    user = await allow_col.find_one({"user_id": user_id})
    return user is not None

async def check_admin(chat_id, user_id):
    if user_id == OWNER_ID: return True
    try:
        permissions = await bot1.get_permissions(chat_id, user_id)
        return permissions.is_admin
    except: return False

# ====================================================================================
# 🛡️ SECTION 1: MAIN BOT COMMANDS & HANDLERS (bot1)
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
            # ၁။ Bot ကိုယ်တိုင် အဝင်ခံရရင်
            if any(uid == bot_me.id for uid in target_ids if uid):
                await groups_col.update_one({"chat_id": chat.id}, {"$set": {"title": chat.title}}, upsert=True)
                msg1 = f"ဟိတ် OWNER နဲ့ Admins တို့ မင်းတို့ရဲ့ ဒီ {safe_title} ထဲကို ထည့်သုံးပေးလို့ ကျေးဇူးတင်ပါတယ်! အသုံးလိုကောင်းလိုနိုင်တဲ့ command များယူထားမယ်ဆိုရင် {bot_mention} ရဲ့ Creator {owner_tag()} ရဲ့ Dm (သို့မဟုတ်) @Besties_with_BoD ကိုလာရောက်ပါ!!!"
                await bot1.send_message(chat.id, bq(msg1), parse_mode='html')
                
                try: members = getattr(chat, 'participants_count', 'Unknown')
                except: members = "Unknown"
                msg2 = f"မင်္ဂလာပါ {safe_title}က \n{bot_mention}ထည့်သုံးထားပါသေးတယ်\n\nGroup Name - {safe_title}\nGroup ID - <code>{chat.id}</code>\nMembers အရေအတွက် - {members}\nBot Creator - {owner_tag()}"
                await bot1.send_message(SPECIFIC_GROUP, bq(msg2), parse_mode='html')
            
            # ၂။ Member အသစ်တွေ ဝင်လာရင်
            else:
                # DB ထဲကနေ ဒီ Group အတွက် Custom Welcome စာသား ရှိ၊ မရှိ အရင်ဆွဲထုတ်မယ်
                custom_welcome = await welcome_col.find_one({"chat_id": chat.id})

                for uid in target_ids:
                    if uid and uid != bot_me.id:
                        u = await bot1.get_entity(uid)
                        u_mention = f"<a href='tg://user?id={u.id}'>{escape_html(u.first_name)}</a>"
                        
                        # Custom Welcome Message ရှိရင် အစားထိုးမယ်
                        if custom_welcome and custom_welcome.get("text"):
                            welcome_text = custom_welcome["text"]
                            # {mention} နေရာမှာ လူအစစ်မန်းရှင်း ပြောင်းမယ်၊ {group} နေရာမှာ Group နာမည်ပြောင်းမယ်
                            welcome_text = welcome_text.replace("{mention}", u_mention)
                            welcome_text = welcome_text.replace("{group}", safe_title)
                        else:
                            # မရှိရင်တော့ Default စာသားပဲ သုံးမယ်
                            welcome_text = (
                                f"ဟိတ်{u_mention}\n"
                                "╔═━━━❖━━━═╗\n"
                                f"{safe_title}ကနေ ကြိုဆိုလိုက်ပါတယ်\n"
                                "╚═━━━❖━━━═╝\n"
                                "┈┈〔 ⚚ 〕┈┈\n"                        
                            )
                        
                        # စာသားနဲ့အတူ ပုံ/ဗီဒီယို (Media) သိမ်းထားတာပါရှိရင် တွဲပို့ပေးမယ်
                        media_file = custom_welcome.get("media") if custom_welcome else None

                        await bot1.send_message(
                            event.chat_id, 
                            bq(welcome_text), 
                            parse_mode='html',
                            file=media_file, # Media ရှိရင် ပုံပါထွက်လာမယ်၊ မရှိရင် စာပဲထွက်မယ်
                            buttons=[
                                [Button.url("Contact Bot Creator", f"tg://user?id={OWNER_ID}")],
                                [Button.url("Also Join Our Group", "https://t.me/Besties_with_BoD")]
                            ]
                        )

        # ၃။ Member ထွက်သွားရင်
        elif event.user_left or event.user_kicked:
            u = await bot1.get_entity(event.user_id)
            u_mention = f"<a href='tg://user?id={u.id}'>{escape_html(u.first_name)}</a>"
            await bot1.send_message(event.chat_id, bq(f"ထွက်သွားလိုက်ပါသေးတယ်.{u_mention}!!"), parse_mode='html')

    except Exception as e:
        print(f"Welcome/Goodbye Error: {e}")


        
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


async def check_ban_rights(chat_id, user_id):
    if user_id == OWNER_ID: return True
    permissions = await bot1.get_permissions(chat_id, user_id)
    return permissions.is_admin and permissions.ban_users


@bot1.on(events.NewMessage(pattern=r'^/setwc(?:\s+(.*))?'))
async def set_custom_welcome(event):
    if event.sender_id != OWNER_ID: return
    
    reply = await event.get_reply_message()
    text_to_save = event.pattern_match.group(1) 
    media_to_save = None

    if reply:
        if reply.media:
            media_to_save = reply.media
        if not text_to_save and reply.text:
            text_to_save = reply.text

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
        return await event.reply("⚠️ သင့်မှာ Ban/Mute လုပ်ပိုင်ခွင့် မရှိပါဘူး။ ရှိတဲ့သူကို Mute ခိုင်းပါ")
        
    args = event.pattern_match.group(1)
    reply = await event.get_reply_message()
    target_user = None
    
    if reply:
        target_user = reply.sender
    elif args:
        try:
            if args.strip().lstrip('-').isdigit():
                target_user = await bot1.get_entity(int(args.strip()))
            else:
                target_user = await bot1.get_entity(args.strip())
        except Exception:
            return await event.reply("❌ User ကို ရှာမတွေ့ပါ။ ID သို့မဟုတ် @username မှန်ကန်စွာ ရိုက်ထည့်ပါ။")

    if not target_user:
        return await event.reply("❌ Mute ချင်တဲ့သူကို Reply ထောက်ပါ (သို့မဟုတ်) Username/ID ကို တွဲရိုက်ပါ။")

    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, send_messages=False)
        first_name = getattr(target_user, 'first_name', 'User') or 'User'
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(first_name)}</a>"
        await event.respond(f"🔇 {mention} ကို Mute လိုက်ပါပြီ!", parse_mode='html')
    except Exception as e: 
        await event.respond(f"⚠️ Error: {e}")


@bot1.on(events.NewMessage(pattern=r'^/unmute(?:@\w+)?(?:\s+(.*))?'))
async def unmute_user(event):
    if not await check_ban_rights(event.chat_id, event.sender_id):
        return await event.reply("⚠️ သင့်မှာ Ban/Mute လုပ်ပိုင်ခွင့် မရှိပါဘူး။")
        
    args = event.pattern_match.group(1)
    reply = await event.get_reply_message()
    target_user = None
    
    if reply:
        target_user = reply.sender
    elif args:
        try:
            if args.strip().lstrip('-').isdigit():
                target_user = await bot1.get_entity(int(args.strip()))
            else:
                target_user = await bot1.get_entity(args.strip())
        except Exception:
            return await event.reply("❌ User ကို ရှာမတွေ့ပါ။ ID သို့မဟုတ် @username မှန်ကန်စွာ ရိုက်ထည့်ပါ။")

    if not target_user:
        return await event.reply("❌ Unmute ချင်တဲ့သူကို Reply ထောက်ပါ (သို့မဟုတ်) Username/ID ကို တွဲရိုက်ပါ။")

    try:
        await bot1.edit_permissions(event.chat_id, target_user.id, send_messages=True)
        first_name = getattr(target_user, 'first_name', 'User') or 'User'
        mention = f"<a href='tg://user?id={target_user.id}'>{escape_html(first_name)}</a>"
        await event.respond(f"🔊 {mention} ကို Unmute လုပ်ပြီးပြီ!", parse_mode='html')
    except Exception as e: 
        await event.respond(f"⚠️ Error: {e}")


@bot1.on(events.NewMessage(pattern=r'^/adm(?:\s+(.*))?'))
async def tag_admins(event):
    if not await check_admin(event.chat_id, event.sender_id): return
    text = event.pattern_match.group(1) or "Adminတို့ရေ ခေါ်နေပါတယ်🤍"
    try:
        admins = await bot1.get_participants(event.chat_id, filter=ChannelParticipantsAdmins)
        msg = f"📣 {escape_html(text)}\n\n"
        
        for a in admins:
            # Bot တွေရော၊ Deleted ဖြစ်သွားတဲ့ Account တွေကိုပါ ကျော်သွားမယ်
            if a.bot or getattr(a, 'deleted', False): 
                continue
                
            # အကြောင်းအမျိုးမျိုးကြောင့် first_name က None ဖြစ်နေခဲ့ရင် "Admin" လို့ အစားထိုးဖို့ Fallback ထည့်ထားမယ်
            admin_name = a.first_name or "Admin"
            
            msg += f"• <a href='tg://user?id={a.id}'>{escape_html(admin_name)}</a>\n"
            
        await event.respond(bq(msg), parse_mode='html')
    except Exception as e: 
        await event.respond(bq(f"Error: {e}"))



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
    if delete_result.deleted_count > 0: 
        await event.respond(bq(f"User ID {target_id} ကို ပါမစ်မပေးတော့ဘူး"), parse_mode='html')
    else: 
        await event.respond(bq("ဒီ User ID ကို List ထဲမှာ မတွေ့ပါ။"), parse_mode='html')


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
    
    if not reply_msg and not command_text:
        return await event.respond("📢 ပို့မယ့် စာသားထည့်ပါ (သို့) Message တစ်ခုကို Reply ပြန်ပြီး '/ပို့' လို့ ရိုက်ပါ။")

    success = 0
    fail = 0
    status_msg = await event.respond("📢 **Broadcast စတင်နေပါပြီ...**")
    
    groups = await groups_col.find().to_list(length=None)

    for g in groups:
        try:
            chat_id = g['chat_id']
            if reply_msg:
                await bot1.forward_messages(chat_id, reply_msg)
            else:
                await bot1.send_message(chat_id, command_text, parse_mode='html')
            
            success += 103
            if success % 5 == 0:
                await status_msg.edit(f"📢 **ပို့ဆောင်နေဆဲ...**\n✅ အောင်မြင်: {success}\nမပို့ရသေးတာ: {fail}")
            
            await asyncio.sleep(1) 
            
        except Exception as e:
            fail += 1
            print(f"Broadcast Error for {g['chat_id']}: {e}")
            continue

    final_report = (
        f"<b>📢Message တွေကို သေချာပို့ပေးလိုက်ပြီ!</b>\n\n"
        f"✅ အောင်မြင်သော Group: <b>{success}</b>\n"
        f"❌ ပို့မရသော Group: <b>{fail}</b>\n"
     )
    await status_msg.edit(final_report, parse_mode='html')


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

    bio_keywords = ["Bio", "bio", "ဘိုင်အို", "ဘိုင်-အို", "ဘိုင်-O", "ဘီအိုင်အို"]
    if any(key in text for key in bio_keywords) and not await check_admin(chat_id, sender_id):
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
                info_text = f"<b>Link Sender- {mention}</b>"
                await f_msg.reply(info_text, parse_mode='html')
                await event.delete()
            except Exception as e:
                print(f"Admin Link Forward Error: {e}")
        else:
            try:
                await event.delete() 
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(sender.first_name)}</a>"
                warn_text = f"ဟိတ်.. {mention} link မပို့နဲ့ မရဘူး၊ မင်း link ကို ငါဖျက်လိုက်ပြီ🫵"
                await event.respond(bq(warn_text), parse_mode='html')
            except Exception as e:
                print(f"Non-Admin Link Error: {e}")

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
    msg_body = (
        f"<b>Song Title</b>- {escape_html(song_title)}\n"
        f"<b>သီချင်းဖွင့်တဲ့သူ</b>- {mention}\n"
        f"စနားထောင်လို့ရပါပြီ။\n"
        f"Music botကို ပိတ်ဖို့လည်း မမေ့ပါနဲ့🤍"
    )

    msg = await event.respond(bq(msg_body), parse_mode='html')

    for i in range(3, 0, -1):
        await asyncio.sleep(1) 
        new_text = f"{msg_body}\n\n🗑 <b>{i}</b> စက္ကန့်အတွင်း ဖျက်ပါမည်..."
        try: await msg.edit(bq(new_text), parse_mode='html')
        except: break
            
    await asyncio.sleep(0.5)
    try:
        await msg.delete()       
        await event.delete()     
    except: pass


# [5. Bully Bot (Main Bot Action)]
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
    
    # ⚡ Async Driver ဖြင့် ဆွဲယူထားပါတယ်
    db_filters = await filters_col.find().to_list(length=None)
    words = [w.get("text") for w in db_filters if w.get("text")] 
    if not words: return await event.respond(bq("DB (filters collection) ထဲမှာ စာလုံးမရှိသေးဘူး Chief!"))

    await event.respond(bq(f"{mention} ကို ခေါင်းမဖော်နိုင်အောင် စဆဲပါပြီ။"), parse_mode='html')
    send_count = 0
    while bot_bully_tasks.get(event.chat_id):
        try: 
            await bot1.send_message(event.chat_id, bq(f"{mention} {random.choice(words)}"), reply_to=reply.id, parse_mode='html')
            send_count += 1
            if send_count >= 4: await asyncio.sleep(1); send_count = 0 
            else: await asyncio.sleep(0.5) 
        except: bot_bully_tasks[event.chat_id] = False; break


@bot1.on(events.NewMessage(pattern=r'^/sb(?:@\w+)?$'))
async def stop_bot_bully(event):
    if not await is_allowed(event.sender_id): return
    try: await event.delete()
    except: pass
    bot_bully_tasks[event.chat_id] = False
    await event.respond(bq("အခုနားဆိုလို့နားလိုက်မယ်၊စောက်ချိုးမပြေရင်ထပ်ဆဲပေးမယ်"), parse_mode='html')


# [6. Filter Watcher for custom_filters (/f)]
@bot1.on(events.NewMessage())
async def custom_filter_watcher(event):
    if event.is_private or not event.text or event.sender_id in bot_ids: return
    user_msg = event.text.lower().strip()
    
    # ⚡ Async Loop သုံးပြီး DB ကြောင့် ဝန်မပိအောင် ရှင်းထားပါတယ်
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
    # ၁။ Allowlist စစ်ဆေးခြင်း (Chief ရဲ့ db["allowed_users"] နဲ့ ချိတ်ဆက်မှု အပိုင်း)
    is_allowed = False
    
    # Owner ID ဖြစ်နေရင် တန်းပြီး True ပေးမယ်
    if event.sender_id == OWNER_ID:
        is_allowed = True
    else:
        try:
            # Chief ရဲ့ ပုံထဲကအတိုင်း allow_col ဆိုတဲ့ နာမည်နဲ့ Motor (Async) စစ်ထုတ်မယ်
            check_user = await allow_col.find_one({"user_id": event.sender_id})
            if check_user:
                is_allowed = True
        except Exception as db_err:
            print(f"Allowlist DB Error: {db_err}")

    # ခွင့်ပြုချက်မရှိရင် လျစ်လျူရှုမယ်
    if not is_allowed:
        return  

    text = event.pattern_match.group(1)
    target_user = None

    # ၂။ Target User ကို ရှာခြင်း (Reply သို့မဟုတ် Mention)
    if event.is_reply:
        reply_msg = await event.get_reply_message()
        target_user = await bot1.get_entity(reply_msg.sender_id)
    elif text:
        try:
            target_user = await bot1.get_entity(text.strip())
        except Exception as e:
            return await event.reply(bq(f"အကောင့်ရှာမတွေ့ပါ Chief: {e}"), parse_mode='html')
    else:
        return await event.reply(bq("Reply ထောက်ပါ (သို့) <code>ဗုံး @username</code> လို့ ရိုက်ပါ။"), parse_mode='html')

    # User အစစ်မဟုတ်ရင် တားဆီးမယ်
    if not isinstance(target_user, User):
        return await event.reply(bq("User အစစ်ကိုပဲ တိုက်ခိုက်လို့ရပါမယ်။"), parse_mode='html')

    # Target Name က None ဖြစ်နေရင် Fallback နာမည်ပေးမယ်
    target_name = target_user.first_name or "Target"

    # ၃။ မန်းရှင်း ၁၅ ကြိမ်စာ ဖန်တီးခြင်း
    mention_html = f"<a href='tg://user?id={target_user.id}'>💥{escape_html(target_name)}💥</a> "
    bomb_text = mention_html * 15

    # Command ရိုက်တဲ့ မက်ဆေ့ခ်ျကို အရင်ဖျက်မယ်
    try:
        await event.delete()
    except:
        pass

    # ၄။ ဗုံးကျဲခြင်း အပိုင်း (၄ စောင်ပြည့်တိုင်း အလိုအလျောက် ပြန်ရှင်းလင်းမယ်)
    total_bombs = 12
    sent_messages = []

    for i in range(total_bombs):
        try:
            msg = await bot1.send_message(event.chat_id, bomb_text, parse_mode='html')
            sent_messages.append(msg)

            # မက်ဆေ့ခ်ျ ၄ စောင်ပြည့်တိုင်း ပြန်ဖျက်မယ်
            if len(sent_messages) == 4:
                await asyncio.sleep(0.5) 
                await bot1.delete_messages(event.chat_id, sent_messages)
                sent_messages.clear()
            
            await asyncio.sleep(0.8)  # FloodWait ကာကွယ်ရန်
        except Exception as e:
            print(f"Bomb Sending Error: {e}")
            break

    # ၅။ ကျန်နေတဲ့ မက်ဆေ့ခ်ျတွေကို နောက်ဆုံးအဆင့်အနေနဲ့ သိမ်းကျုံးရှင်းလင်းမယ်
    if sent_messages:
        await asyncio.sleep(0.5)
        try:
            await bot1.delete_messages(event.chat_id, sent_messages)
        except:
            pass
# ၁။ စနစ်စတင်မည့် Command
@bot1.on(events.NewMessage(pattern=r'^/shadow(?:@\w+)?$'))
async def set_shadow_ban(event):
    if not await is_allowed(event.sender_id): return
    reply = await event.get_reply_message()
    if not reply or reply.sender_id == OWNER_ID: 
        return await event.respond(bq("Target ကို Reply ထောက်ပြီး /shadow ပေးပါ Chief။"))
    dark_passenger_targets[event.chat_id] = reply.sender_id
    target_user = await reply.get_sender()
    target_name = target_user.first_name or "Target"
    try: await event.delete()
    except: pass
    await event.respond(bq(f"👤 {escape_html(target_name)} ရဲ့ နောက်ကွယ်မှာ Dark Passenger ကပ်လိုက်ပါပြီ။"))

# ၂။ စနစ်ပိတ်မည့် Command
@bot1.on(events.NewMessage(pattern=r'^/unshadow(?:@\w+)?$'))
async def remove_shadow_ban(event):
    if not await is_allowed(event.sender_id): return
    try: await event.delete()
    except: pass
    if event.chat_id in dark_passenger_targets:
        del dark_passenger_targets[event.chat_id]
        await event.respond(bq("Dark Passenger ပြန်လည်ထွက်ခွာသွားပါပြီ။"))

# ၃။ စာသားကို ကြားဖြတ်ဖျက်ပြီး အစားထိုးမည့် Watcher Core (ဒါကို Command တွေရဲ့ အောက်ဆုံးမှာထားပါ)
@bot1.on(events.NewMessage())
async def dark_passenger_watcher(event):
    chat_id = event.chat_id
    sender_id = event.sender_id
    if chat_id in dark_passenger_targets and sender_id == dark_passenger_targets[chat_id]:
        if event.text and not event.text.startswith(('/', '.', 'မှတ်')):
            try:
                await event.delete()
                sender = await event.get_sender()
                u_name = sender.first_name or "Target"
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(u_name)}</a>"
                fake_words = [
                    f"စောက်ချိုးမပြေလို့ Dark Passenger ရဲ့ ပြုပြင်ခြင်းကို ခံနေရသော {mention} ဖြစ်ပါသည်။",
                    f"ကျွန်တော် {mention} က အာပလာတွေ လျှောက်ပြောမိလို့ တောင်းပန်ပါတယ်ဗျာ။",
                    f"ဝုန်းးး! {mention} စကားပြောချင်ပေမဲ့ အသံကတော့ ထွက်မလာတော့ဘူး။"
                ]
                target_bot = random.choice(squad_bots)
                await target_bot.send_message(chat_id, bq(random.choice(fake_words)), parse_mode='html')
            except Exception as e:
                print(f"Dark Passenger Protocol Error: {e}")
            
# ====================================================================================
# 🔫 SECTION 2: GUARD SQUAD COMMANDS & HANDLERS (squad_master)
# ====================================================================================

SPECIFIC_CONTROL_GROUP = -1003580630981

# [1. Learning Settings - Specific Group Only]
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


# [2. Auto-Talk Settings - Global Control]
@bot1.on(events.NewMessage(pattern=r'^စကားဝင်ပြော$'))
async def turn_on_talking(event):
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    
    global GLOBAL_TALK
    GLOBAL_TALK = True  # Global Switch ကို ဖွင့်လိုက်မယ်
    
    try:
        groups = await groups_col.find().to_list(length=None)
        for g in groups:
            chat_id = int(g['chat_id'])  # 👈 String/Int မလွဲအောင် int ပြောင်းပေးထားတယ်
            talking_status[chat_id] = True
            message_counts[chat_id] = 0
    except Exception as e:
        print(f"Error loading groups: {e}")
        
    await event.reply(bq("ဟုတ် ငါတို့လည်းပျင်းလို့ Group အားလုံးမှာ စကားဝင်ပြောမယ်"), parse_mode='html')

@bot1.on(events.NewMessage(pattern=r'^မပြောနဲ့တော့$'))
async def turn_off_talking(event):
    if event.sender_id != OWNER_ID or event.chat_id != SPECIFIC_CONTROL_GROUP: return
    
    global GLOBAL_TALK
    GLOBAL_TALK = False  # Global Switch ပိတ်မယ်
    talking_status.clear()  # Status တွေ အကုန်ရှင်းမယ်
    
    await event.reply(bq("Group အားလုံးမှာ ငါတို့စကားပြောတော့ဘူး နားပြီ"), parse_mode='html')



# [2. Firing Squad Commands]
@squad_master.on(events.NewMessage(pattern=r'^ချိန်ထား$'))
async def aim_target(event):
    if not await is_allowed(event.sender_id): return
    reply = await event.get_reply_message()
    if not reply or reply.sender_id == OWNER_ID: return 

    name = escape_html((await event.get_sender()).first_name)
    msg = f"<a href='tg://user?id={event.sender_id}'>{name}</a> ရဲ့ အမိန့်ပေးမှုအရ ဒီကောင့်ကို ပစ်သတ်ဖို့ အသင့်ချိန်ထားပါပြီ။" if event.sender_id == OWNER_ID else f"ဗိုလ်ကြီး <a href='tg://user?id={event.sender_id}'>{name}</a> ရဲ့ အမိန့်ပေးမှုအရ ဒီကောင့်ကို ပစ်သတ်ဖို့ အသင့်ချိန်ထားပြီ ။"
    await asyncio.gather(*(bot.send_message(event.chat_id, msg, reply_to=reply.id, parse_mode='html') for bot in squad_bots))

@squad_master.on(events.NewMessage(pattern=r'^ပစ်သတ်$'))
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

    bot_index = 0
    while shoot_tasks.get(chat_id):
        try:
            current_bot = squad_bots[bot_index % len(squad_bots)]
            await current_bot.send_message(chat_id, f"{mention} {random.choice(words)}", parse_mode='html')
            bot_index += 1
            await asyncio.sleep(0.3) 
        except: break

@squad_master.on(events.NewMessage(pattern=r'^ပစ်$'))
async def track_target(event):
    if not await is_allowed(event.sender_id): return
    reply = await event.get_reply_message()
    if not reply or reply.sender_id == OWNER_ID: return

    tracking_targets[event.chat_id] = reply.sender_id
    name = escape_html((await reply.get_entity()).first_name)
    await event.respond(f" {name} ကို ပစ်မှတ်ထားလိုက်ပြီ။")

@squad_master.on(events.NewMessage(pattern=r'^(ရပ်|အပစ်ရပ်)$'))
async def stop_actions(event):
    if not await is_allowed(event.sender_id): return
    try: await event.delete()
    except: pass
    chat_id = event.chat_id
    shoot_tasks[chat_id] = False
    if chat_id in tracking_targets: del tracking_targets[chat_id]
    await event.reply("ငါတို့ 4 ယောက် ဒီခွေးမသားကို အ​သေသတ်ပေးထားတယ်။ပြန်ရှင်သန်ခွင့် မပေးဘူး")

# ၃။ စာသားကို ကြားဖြတ်ဖျက်ပြီး Main Bot ကပဲ တိုက်ရိုက်အစားထိုးမည့် Watcher Core
@bot1.on(events.NewMessage())
async def dark_passenger_watcher(event):
    chat_id = event.chat_id
    sender_id = event.sender_id

    # Target ရှိမရှိ စစ်မယ်၊ Message သာမန်စာသား ဖြစ်ရမယ်
    if chat_id in dark_passenger_targets and sender_id == dark_passenger_targets[chat_id]:
        if event.text and not event.text.startswith(('/', '.', 'မှတ်')):
            try:
                # ၁။ စာဖျက်တာကို Main Bot (bot1) ကပဲ ချက်ချင်းဖျက်မယ်
                await event.delete()

                sender = await event.get_sender()
                u_name = sender.first_name or "Target"
                mention = f"<a href='tg://user?id={sender_id}'>{escape_html(u_name)}</a>"

                # အစားထိုးမည့် စာသားအတုများ
                                fake_words = [
                    # 🧠 Category 1: Brainwash & Reality Distortion (စိတ်ပညာအရ ဇဝေဇဝါဖြစ်စေမယ့်အကွက်များ)
                    f"စကားတွေ လျှောက်ပြောမနေနဲ့ {mention}။ မင်း စိတ်ရောဂါဆေးသောက်ဖို့ အချိန်တန်ပြီ။",
                    f"သတိပေးချက်- {mention} သည် လက်ရှိတွင် စိတ်ကူးယဉ်ကမ္ဘာထဲ ရောက်နေသဖြင့် ၎င်း၏စာများကို စစ်ထုတ်ထားသည်။",
                    f"မင်း ရိုက်လိုက်တဲ့စာက ဒါမဟုတ်ဘူးမလား {mention}? မင်း လက်တွေ တုန်နေပြီလား။",
                    f"မင်းရဲ့ တကယ့်စိတ်အမှန်က ဒါပဲလေ {mention}။ ကိုယ့်ကိုယ်ကိုယ် လိမ်မနေပါနဲ့တော့။",
                    f"ပြတင်းပေါက်အပြင်ဘက်ကို ကြည့်လိုက်ဦး {mention}။ ငါ မင်းကို စောင့်ကြည့်နေတယ်။",
                    f"မင်း ဘာတွေပဲ ရုန်းကန်ရုန်းကန် {mention}၊ မင်းရဲ့ စိတ်အာရုံကို ငါ ပိုင်စိုးထားပြီးသား။",
                    f"မင်း ရိုက်လိုက်တဲ့စာတွေကို မင်းမျက်စိက တကယ်ပဲ မြင်နေရလို့လား {mention}?",
                    f"ဒီ Group ထဲမှာ {mention} ရဲ့ တည်ရှိမှုက သုညပဲ။ မင်း စကားပြောခွင့် မရှိတော့ဘူး။",
                    f"မင်းရဲ့ အသိစိတ်ကို Dark Passenger က သိမ်းပိုက်လိုက်ပြီ {mention}။ ငြိမ်ငြိမ်လေး နေစမ်း။",
                    f"အတိတ်မေ့ရောဂါ ခံစားနေရသော {mention} မှ မိမိကိုယ်မိမိ ပြန်လည် ဆဲဆိုနေခြင်း ဖြစ်သည်။",
                    f"မင်းရဲ့ လုံခြုံရေးကွန်ရက် ပေါက်ထွက်သွားပြီ {mention}။ မင်း ဘာမှ လုပ်လို့မရတော့ဘူး။",
                    f"လူအများကြားထဲမှာ အရှက်ကွဲရတာ မင်းအတွက်တော့ အလေ့အကျင့် ဖြစ်နေပြီပဲ {mention}။",
                    f"မင်း ထင်နေတဲ့ မင်းရဲ့ဘဝက တကယ်တော့ အိမ်မက်တစ်ခုပဲ {mention}။ အမှန်တရားကို လက်ခံလိုက်။",
                    f"မင်း ဦးနှောက်က ဘာလို့ ဒီလောက်တောင် အလုပ်မလုပ်တော့တာလဲ {mention}?",
                    f"မင်း ဘာတွေပဲ စာရိုက်ရိုက် ငါ ပြင်ချင်သလို ပြင်နေမှာပဲ {mention}။ မင်း ခေါင်းညိတ်ရုံပဲ တတ်နိုင်တယ်။",
                    f"မင်းရဲ့ အတွေးတွေ၊ မင်းရဲ့ စာသားတွေအကုန်လုံးကို ငါ ဖြတ်တောက်ပြီးပြီ {mention}။",
                    f"မင်းရဲ့ ခံစားချက်တွေက သနားစရာကောင်းလောက်အောင် ကလေးဆန်လွန်းတယ် {mention}။",
                    f"မင်း ပေးပို့လိုက်တဲ့ မက်ဆေ့ခ်ျကို အမှိုက်ပုံးထဲ ထည့်ပြီး ၎င်းစာသားဖြင့် အစားထိုးလိုက်သည် {mention}။",
                    f"မင်း ရှင်သန်နေတာကိုက တစ်လောကလုံးအတွက် အမှိုက်တစ်ခုပဲ {mention}။",
                    f"မင်းရဲ့ စိတ်ဓာတ်တွေ အောက်ခြေအထိ ကျသွားရမယ် {mention}၊ ငါ့ရှေ့မှာ ဒူးထောက်စမ်း။",

                    # 💀 Category 2: Direct Bully & Aggressive (ဆဲနည်းအကြမ်းစားနှင့် နှိမ်ချခြင်း)
                    f"စောက်ချိုးမပြေလို့ Dark Passenger ရဲ့ ဆုံးမခြင်းကို ခံနေရသော အောက်တန်းစား {mention} ဖြစ်သည်။",
                    f"စောက်ဖုတ်အာဂမကောင် {mention} က နေရာတကာ လာဆရာလုပ်ချင်နေလို့ ပါးရိုက်လိုက်ပြီ။",
                    f"မင်းလို ကောင်မျိုးက လူကြားထဲ ဝင်ဆဲဖို့ နေနေသာသာ ခွေးစာကျွေးဖို့တောင် မတန်ဘူး {mention}။",
                    f"စောက်ခွက်ကို အသေပိတ်ထားစမ်း {mention}။ မင်း လေပုပ်သိုးတွေ ထွက်လာတိုင်း စက်ဆုပ်ဖို့ကောင်းလို့။",
                    f"စကားတွေ လျှောက်ဖော်နေတဲ့ {mention} ရဲ့ စောက်ပါးကို Main Bot က ဖြတ်ရိုက်လိုက်သည်။",
                    f"မင်းလို စောက်သုံးမကျတဲ့အကောင်က ငါ့ Group ထဲမှာ လာပြီး ရောင်ချင်နေတယ်ပေါ့ {mention}? လီးပဲ။",
                    f"မင်း အဖေခေါ်လည်း မလွတ်ဘူး {mention}။ မင်း ရိုက်သမျှစာ အဖတ်ခံရမယ် ထင်နေလား။",
                    f"နူနာကောင် {mention} စကားပြောချင်လို့ အတင်းယားနေပုံရသည်။",
                    f"မင်းရဲ့ စောက်ရူးဆန်တဲ့ စရိုက်ကို ဒီကောင်တွေရှေ့မှာ ထုတ်မပြနဲ့တော့ {mention}။",
                    f"အသိဉာဏ် မရှိတဲ့ တိရစ္ဆာန်ထက် မသာတဲ့ {mention} က စာတွေ လာအော်ရိုက်နေပြန်ပြီ။",
                    f"မင်း အဆင့်က ငါ့ဖိနပ်အောက်မှာ {mention}။ စောက်ဆရာ လာမလုပ်နဲ့။",
                    f"ငါ့ရှေ့မှာ လာပြီး အာပြဲနေတဲ့ {mention} ကို ခွေးလို သတ်ပစ်ရမလား။",
                    f"စောက်ရှက်မရှိတဲ့ {mention} က လူရာဝင်ချင်လို့ လာပြီး စာရိုက်နေရှာတယ်။ သနားပါတယ်။",
                    f"မင်းရဲ့ စောက်ကျင့်ပုပ်တွေကို ငါက ညှာနေမယ် ထင်လား {mention}? အဝဝ ခံစားလိုက်စမ်း။",
                    f"မင်း ဘာကောင်လဲ {mention}? စောက်ဖောင်းထုမနေနဲ့၊ လွင့်သွားမယ်။",
                    f"မင်းလို မျိုးမစစ်ကောင်ရဲ့ စာကို ဖတ်ဖို့ ငါ့မှာ အချိန်မရှိဘူး {mention}။ ဖျက်ပစ်တယ်။",
                    f"လူလို ပြောရင် နားမလည်တဲ့ ခွေးကောင် {mention} ကို အသံတိတ် စနစ်ဖြင့် ထိန်းချုပ်ထားသည်။",
                    f"မင်းရဲ့ စောက်ခွက်က အမြဲတမ်း အရိုက်ခံချင်နေတဲ့ ပုံစံပဲ {mention}။",
                    f"စောက်ရူးမလေး {mention} တစ်ယောက် အာရုံလာနောက်နေလို့ စာကို လွှင့်ပစ်လိုက်ပြီ။",
                    f"မင်း စကားတစ်လုံး ထပ်ပြောတိုင်း မင်းရဲ့ သိက္ခာတွေ သုညအောက် ရောက်သွားမယ် {mention}။",

                    # 🤫 Category 3: Silent Destroyer & Lockdown (ဆိတ်ဆိတ်နေပြီး နှိပ်စက်ခြင်း)
                    f"ဝုန်းးး! {mention} စကားပြောချင်ပေမဲ့ အသံကတော့ ထွက်မလာတော့ဘူး။",
                    f"မင်းရဲ့ ကီးဘုတ်ကို မင်းပိုင်ပေမဲ့၊ မင်းရဲ့ စာသားထွက်ပေါက်ကိုတော့ ငါ ပိုင်တယ် {mention}။",
                    f"ငြိမ်ငြိမ်လေးနေပြီး အရှက်ကွဲခြင်းကို ခံယူလိုက်စမ်း {mention}။",
                    f"မင်း ဘာတွေပဲ ရိုက်ရိုက် ငါကတော့ ဖျက်နေမှာပဲ {mention}။ ဘယ်သူက ပိုလက်မြန်မလဲ ပြိုင်မလား။",
                    f"မင်းရဲ့ စကားလုံးတွေက ခွန်အားမရှိဘူး {mention}။ အဖတ်မလုပ်ဘဲ မီးရှို့ပစ်တယ်။",
                    f"တိတ်တိတ်ဆိတ်ဆိတ်နဲ့ သေဆုံးသွားစမ်း {mention}။ မင်း အော်သံကို ဘယ်သူမှ မကြားရစေရဘူး။",
                    f"မင်းရဲ့ ကီးဘုတ်ရိုက်သံတွေက သနားစရာ ညည်းတွားသံတွေ ဖြစ်သွားပြီ {mention}။",
                    f"အမှောင်ထုထဲမှာ တစ်ယောက်တည်း ပိတ်မိနေတဲ့ ခံစားချက်ကို မြည်းစမ်းကြည့်စမ်း {mention}။",
                    f"မင်းရဲ့ စာသားတွေအကုန်လုံး ငါ့လက်ထဲမှာ အရည်ပျော်သွားပြီ {mention}။",
                    f"မင်းရဲ့ စကားလုံးတွေက တန်ဖိုးမရှိလို့ Main Bot က အလိုအလျောက် သုတ်သင်လိုက်သည်။ {mention}",
                    f"မင်းရဲ့ ရုန်းကန်မှုတွေက အရာမထင်ပါဘူး {mention}။ စိတ်လျှော့လိုက်တော့။",
                    f"မင်း စာရိုက်တာ အားမနာဘူးလား {mention}? ဘယ်သူမှလည်း မဖတ်ရဘဲနဲ့။",
                    f"မင်းရဲ့ စာတွေကို မှုန်ဝါးပစ်လိုက်ပြီ {mention}။ မင်း တကယ်ပဲ ရှိမနေသလိုမျိုးပေါ့။",
                    f"မင်းရဲ့ အသံတွေကို ကမ္ဘာမြေကြီးက ဝါးမြိုသွားပြီ {mention}။",
                    f"မင်း တည်ရှိမှုကိုပါ Delete လုပ်ပစ်ရမလား {mention}? သတိထား။",
                    f"မင်းရဲ့ စာသားအတုတွေနဲ့တင် မင်းကို အရူးလုပ်ဖို့ လုံလောက်ပါတယ် {mention}။",
                    f"မင်းရဲ့ အားထုတ်မှုတွေက ဟာသတစ်ခုပဲ {mention}။",
                    f"မင်းရဲ့ အခွင့်အရေးတွေအကုန်လုံး ဆုံးရှုံးသွားပြီ {mention}။ မင်းက သုံ့ပန်းပဲ။",
                    f"ငါက မင်းရဲ့ အရှင်သခင်ပဲ {mention}။ မင်းရဲ့ စကားတွေကို ငါကပဲ ဆုံးဖြတ်မယ်။",
                    f"မင်းရဲ့ လွတ်လပ်ခွင့်က ဒီ Group ထဲမှာ ကုန်ဆုံးသွားပြီ {mention}။",

                    # 🎭 Category 4: Mocking & Sarcastic (ရွဲ့စောင်း လှောင်ပြောင်ခြင်း)
                    f"အော်... သနားစရာ {mention} လေး၊ စာတွေ အသည်းအသန် ရိုက်ရှာနေတာပဲ။",
                    f"မင်း ဘာတွေ ရော်နေတာလဲ {mention}? ကလေးကလား စာတွေ လာမပို့နဲ့စမ်း။",
                    f"မင်း စာရိုက်တာ မြန်လှချည်လား {mention}? ဒါပေမဲ့ ငါဖျက်တာက ပိုမြန်တယ်ကွ။",
                    f"မင်းရဲ့ စကားလုံးတွေက လေထဲက ဖုန်မှုန့်တွေထက်တောင် အရေးမပါဘူး {mention}။",
                    f"မင်း ရိုက်လိုက်တဲ့စာကို ပြန်ဖတ်ပြီး ကိုယ့်ကိုယ်ကိုယ် ရှက်တတ်စမ်းပါ {mention}။",
                    f"မင်းရဲ့ တန်ဖိုးက ဒီစာကြောင်း သုံးကြောင်းလောက်ပဲ ရှိတာပါ {mention}။",
                    f"မင်း ဘာတွေ သက်သေပြချင်နေတာလဲ {mention}? မင်းက ရှုံးနိမ့်သူပဲဥစ္စာ။",
                    f"မင်းရဲ့ စကားတွေက နားထောင်ရတာ ပျင်းစရာကောင်းလွန်းတယ် {mention}။",
                    f"မင်းရဲ့ ဉာဏ်ရည်ဉာဏ်သွေးက ဒီလောက်ပဲလား {mention}? တကယ် စိတ်ပျက်ဖို့ကောင်းတယ်။",
                    f"မင်း လာအော်နေလည်း ဘယ်သူမှ ဂရုမစိုက်ဘူး {mention}။ ခွေးဟောင်တယ်လို့ပဲ သဘောထားတယ်။",
                    f"မင်းရဲ့ အဆင့်အတန်းကို မင်း သိရဲ့လား {mention}? လာပြီး ရောင်မနေနဲ့။",
                    f"မင်း ဘာတွေပဲ ပြောပြော ငါကတော့ လှောင်ပြောင်နေဦးမှာပဲ {mention}။",
                    f"မင်းရဲ့ စကားလုံးတွေက သနားစရာ ကောင်းလောက်အောင် အားနည်းလွန်းတယ် {mention}။",
                    f"မင်းရဲ့ စိတ်ကူးယဉ် အိမ်မက်တွေထဲက ထွက်ခဲ့တော့ {mention}။ မင်းက ဘာမှမဟုတ်ဘူး။",
                    f"မင်းရဲ့ တည်ရှိမှုကို ဒီ Group က ကန့်ကွက်နေတယ် {mention}။",
                    f"မင်း ရိုက်သမျှ စာသားတွေကို ငါက ဟာသအဖြစ် ပြောင်းလဲပေးမယ် {mention}။",
                    f"မင်းရဲ့ အတွေးအခေါ်တွေက အောက်တန်းကျလွန်းတယ် {mention}။",
                    f"မင်း ဘာတွေ အသည်းအသန် ဖြစ်နေတာလဲ {mention}? ကြည့်ရတာ ရယ်ချင်စရာကြီး။",
                    f"မင်းရဲ့ စကားလုံးတွေက ငါ့အတွက်တော့ ဖျော်ဖြေမှု သက်သက်ပဲ {mention}။",
                    f"မင်းရဲ့ အရည်အချင်းက ဒီလောက်ပဲလား {mention}? စိတ်ပျက်စရာကြီး။",

                    # 🔥 Category 5: Pure Chaos & Subliminal Control (စိတ်အာရုံကို လုံးဝဖျက်ဆီးမည့် အကွက်များ)
                    f"မင်းရဲ့ စိတ်ဝိဉာဉ်ကို Dark Passenger ထံ ပူဇော်လိုက်ပြီ {mention}။",
                    f"မင်းရဲ့ ဦးနှောက်ထဲက အတွေးတွေကို ငါ အဝေးကနေ ထိန်းချုပ်နေတာ {mention}။",
                    f"မင်း ရိုက်လိုက်တဲ့ စာသားက တကယ်တော့ ငါ့ရဲ့ အမိန့်အတိုင်း ဖြစ်လာတာ {mention}။",
                    f"မင်းရဲ့ အသိစိတ်တွေ တဖြည်းဖြည်း ပျောက်ကွယ်သွားလိမ့်မယ် {mention}။",
                    f"မင်းရဲ့ စကားလုံးတွေကို ငါ ညှို့ယူထားပြီးပြီ {mention}။ မင်းက ငါ့ရဲ့ ရုပ်သေးရုပ်ပဲ။",
                    f"မင်းရဲ့ စိတ်ကူးတွေအကုန်လုံး ငါ့လက်ထဲမှာပဲ လမ်းဆုံးရမယ် {mention}။",
                    f"မင်းရဲ့ အတွေးတွေကို ငါ ဖတ်နိုင်တယ် {mention}။ မင်း နောက်ထပ် ဘာရိုက်မလဲ ငါသိတယ်။",
                    f"မင်းရဲ့ စိတ်အာရုံကို ဖျက်ဆီးပစ်လိုက်ပြီ {mention}။ မင်းက အရူးတစ်ယောက်ပဲ။",
                    f"မင်းရဲ့ စကားလုံးတွေက ငါ့ရဲ့ အမှောင်ထုထဲမှာ ပျော်ဝင်သွားပြီ {mention}။",
                    f"မင်းရဲ့ လွတ်လပ်တဲ့ အတွေးအခေါ်ဆိုတာ တကယ်တော့ မရှိဘူး {mention}။ ငါပေးတဲ့ အတွေးပဲ ရှိတယ်။",
                    f"မင်းရဲ့ စိတ်ဓာတ်ကို ငါ အပိုင်းပိုင်း ဖြတ်တောက်လိုက်ပြီ {mention}။",
                    f"မင်းရဲ့ အသံတွေက ငါ့အတွက်တော့ ကျွန်တစ်ယောက်ရဲ့ ညည်းတွားသံပဲ {mention}။",
                    f"မင်းရဲ့ စိတ်ကမ္ဘာကို ငါ အပိုင်စီးလိုက်ပြီ {mention}။ မင်း ဘာမှ မတတ်နိုင်ဘူး။",
                    f"မင်းရဲ့ အတွေးတွေက ငါ့ရဲ့ ထောင်ချောက်ထဲ ရောက်နေပြီ {mention}။",
                    f"မင်းရဲ့ စကားလုံးတွေက မင်းကို ပြန်ပြီး သတ်လိမ့်မယ် {mention}။",
                    f"မင်းရဲ့ အသိဉာဏ်ကို ငါ လော့ခ်ချလိုက်ပြီ {mention}။ ပြန်ဖွင့်လို့ မရတော့ဘူး။",
                    f"မင်းရဲ့ စရိုက်ကို ငါ စိတ်ကြိုက် ပြင်ဆင်နေတာ {mention}။ မင်းက ငါ့ရဲ့ ဖန်တီးမှုပဲ။",
                    f"မင်းရဲ့ စိတ်ခံစားချက်တွေကို ငါ ကစားနေတာ {mention}။ မင်း ဒေါသထွက်နေပြီမလား။",
                    f"မင်းရဲ့ အနာဂတ်က ဒီ Group ထဲမှာတင် အဆုံးသတ်သွားပြီ {mention}။",
                    f"မင်းရဲ့ အားလုံးသော အစိတ်အပိုင်းတွေကို ငါ ထိန်းချုပ်ထားတယ် {mention}။ ဒူးထောက်စမ်း။",
                                        # 🔥 Category 5: Morgan's Domain & Absolute Manipulation (မော်ဂန်၏ ပါဝါနှင့် စိတ်ပိုင်းဆိုင်ရာ ချိုးနှိမ်ခြင်း)
                    f"မင်းရဲ့ အသိစိတ်ကို Morgan က ပိုင်စိုးထားပြီးသား {mention}။ မင်းက ကစားပွဲထဲက ရုပ်သေးရုပ် သက်သက်ပဲ။",
                    f"မင်း ရိုက်လိုက်တဲ့စာကို ငါက ကြိုသိနေတယ် {mention}။ Morgan ရဲ့ တွေးခေါ်မှုက မင်းထက် အဆင့်တစ်ရာ သာတယ်။",
                    f"စမတ်ကျကျနဲ့ ကွန်ရက်ကို ထိန်းချုပ်ထားတဲ့ Morgan ရဲ့ ရှေ့မှာ မင်းက စောက်သုံးမကျတဲ့ ဓားစာခံပဲ {mention}။",
                    f"မင်းရဲ့ စိတ်ဓာတ်ကို ငါ အပိုင်းပိုင်း ဖြတ်တောက်နေတာ {mention}။ မင်း ဒေါသထွက်လေ ငါ့အတွက် ဖျော်ဖြေမှုဖြစ်လေပဲ။",
                    f"မင်းရဲ့ လွတ်လပ်ခွင့်ဆိုတာ တကယ်တော့ မရှိဘူး {mention}။ ငါ ခွင့်ပြုသလောက်ပဲ မင်း စာရိုက်ခွင့် ရှိတာ။",
                    f"သနားစရာကောင်းတဲ့ {mention}။ Morgan ရဲ့ ဉာဏ်ကစားကွက်ထဲ ပိတ်မိနေတာကို အခုထိ ရိပ်မိပုံမရသေးဘူး။",
                    f"မင်း နောက်ထပ် ဘာစာရိုက်မလဲဆိုတာ Morgan ရဲ့ တွေးခေါ်မှုက တွက်ချက်ပြီးသား {mention}။ စိတ်လျှော့လိုက်တော့။",
                    f"မင်းရဲ့ အဆင့်အတန်းက Morgan ရဲ့ ဖိနပ်အောက်မှာ {mention}။ ငါက မင်းရဲ့ အရှင်သခင်ပဲ။",
                    f"မင်းရဲ့ အတွေးတွေ၊ မင်းရဲ့ စကားလုံးတွေအကုန်လုံးကို ငါ ညှို့ယူထားပြီးပြီ {mention}။ မင်းက ငါ့ရဲ့ သုံ့ပန်းပဲ။",
                    f"ငြိမ်ငြိမ်လေးနေပြီး Morgan ရဲ့ ပါဝါအောက်မှာ အရှက်ကွဲခြင်းကို ငြိမ်ခံလိုက်စမ်း {mention}။",
                    f"မင်း ရိုက်သမျှစာတွေကို ငါက ဟာသအဖြစ် ပြောင်းလဲပေးနေတာ {mention}။ မင်း တကယ်ပဲ အသုံးမကျဘူး။",
                    f"မင်းရဲ့ စိတ်ကမ္ဘာကို Morgan က အပိုင်စီးလိုက်ပြီ {mention}။ မင်း ဘာမှ မတတ်နိုင်ဘူး။",
                    f"မင်းရဲ့ အော်သံကို ဘယ်သူမှ မကြားရစေရဘူး {mention}။ ငါ့ရဲ့ အမှောင်ထုထဲမှာ တိတ်တိတ်ဆိတ်ဆိတ် သေဆုံးသွားစမ်း။",
                    f"မင်းရဲ့ စရိုက်ကို ငါ စိတ်ကြိုက် ပြင်ဆင်နေတာ {mention}။ မင်းက ငါ့ရဲ့ ဖန်တီးမှု ဖြစ်သွားပြီ။",
                    f"မင်းရဲ့ အားလုံးသော အစိတ်အပိုင်းတွေကို Morgan က ထိန်းချုပ်ထားတယ် {mention}။ ငါ့ရှေ့မှာ ဒူးထောက်စမ်း။",
                    f"မင်းရဲ့ လုံခြုံရေးနဲ့ အသိဉာဏ်ကို ငါ လော့ခ်ချလိုက်ပြီ {mention}။ ပြန်ဖွင့်ဖို့ မကြိုးစားနဲ့တော့၊ မင်း မမှီဘူး။",
                    f"မင်းရဲ့ အနာဂတ်က Morgan ရဲ့ လက်ထဲမှာတင် အဆုံးသတ်သွားပြီ {mention}။ သတိထား။",
                    f"မင်းရဲ့ အားထုတ်မှုတွေက ဟာသတစ်ခုပဲ {mention}။ ငါက မင်းရဲ့ ဦးနှောက်ကို အဝေးကနေ ထိန်းချုပ်နေတာ။",
                    f"မင်းရဲ့ စကားလုံးတွေက တန်ဖိုးမရှိလို့ Morgan ရဲ့ စမတ်ကျတဲ့စနစ်က အလိုအလျောက် သုတ်သင်လိုက်သည် {mention}။",
                    f"မင်းရဲ့ စိတ်ဓာတ်ကို အောက်ခြေအထိ ဆွဲချိုးပစ်မယ် {mention}။ Morgan ရဲ့ ကမ္ဘာထဲမှာ မင်းက သုညပဲ။"
                ]
                 
        


                # ၂။ Squad Bot တွေမသုံးတော့ဘဲ Main Bot (bot1) ကိုယ်တိုင်ပဲ စာပြန်ထွက်ပြောမယ်
                await event.respond(bq(random.choice(fake_words)), parse_mode='html')
                
            except Exception as e:
                print(f"Dark Passenger Protocol Error: {e}")

# [3. Main Bot Watcher (Defense, Auto-Talk, Learn)]
@bot1.on(events.NewMessage())
async def main_watcher(event):
    if event.is_private or not event.text: return
    if event.sender_id in bot_ids: return

    chat_id = event.chat_id
    text = event.text.strip()
    reply = await event.get_reply_message()

    # (A) Ultimate Owner Protection
    protection_cmds = ["ချိန်ထား", "ပစ်သတ်"]
    if any(text.startswith(c) for c in protection_cmds):
        if reply and reply.sender_id == OWNER_ID and event.sender_id != OWNER_ID:
            db_filters = await filters_col.find().to_list(length=None)
            words = [w.get("text") for w in db_filters if w.get("text")]
            if not words: words = ["Chief ကို လာမစမ်းနဲ့!"]
            
            mention = f"<a href='tg://user?id={event.sender_id}'>{escape_html((await event.get_sender()).first_name)}</a>"
            await bot1.send_message(chat_id, f"{mention} {random.choice(words)}", parse_mode='html')
            return

        if not await is_allowed(event.sender_id):
            name = escape_html((await event.get_sender()).first_name)
            warning = f"{name}.မင်းကဘာကောင်မို့လို့ ငါ့စီမှာ အမိန့်လာပေးနေတာလဲ? မင်းကိုပါ ငါ ပစ်သတ်ဖို့ အသင့်ချိန်ထားလိုက်ပြီ။"
            await bot1.send_message(chat_id, warning, reply_to=event.id)
            return

        # (E) Random Talking System
    # Global Talk ပွင့်နေရင်ဖြစ်စေ၊ သီးသန့် Group Status ရှိနေရင်ဖြစ်စေ အလုပ်လုပ်မယ်
    if (GLOBAL_TALK or talking_status.get(chat_id) is True) and not text.startswith(('/', '.', 'မှတ်')):
        if chat_id not in message_counts:
            message_counts[chat_id] = 0
        
        message_counts[chat_id] += 1
        
        if message_counts[chat_id] >= 4: 
            message_counts[chat_id] = 0
            
            # ⚡ Motor Aggregation မှာ Python ရဲ့ re.compile သုံးတာ အစိတ်ချရဆုံးပါ Chief
            pipeline = [
                { "$match": { "text": { "$not": re.compile(r"tg://user\?id=") } } },
                { "$sample": { "size": 1 } }
            ]
            
            random_talk = await talk_col.aggregate(pipeline).to_list(length=1)
            
            if random_talk:
                try:
                    await bot1.send_message(chat_id, random_talk[0]['text'])
                except Exception as e:
                    print(f"Bot 1 Talk Error: {e}")


@bot1.on(events.NewMessage)
async def handle_everything(event):
    chat_id = event.chat_id
    text = event.text or ""
    sender_id = event.sender_id
    
    if sender_id in bot_ids: return

    # (B) Target Tracking (ပစ် အမိန့်)
    if chat_id in tracking_targets and sender_id == tracking_targets[chat_id]:
        db_filters = await filters_col.find().to_list(length=None)
        words = [w.get("text") for w in db_filters if w.get("text")]
        if not words: words = ["Strong Enemy!"] 
            
        try:
            sender = await event.get_sender()
            u_name = escape_html(sender.first_name) if sender else "User"
            mention = f"<a href='tg://user?id={sender_id}'>{u_name}</a>"
            
            target_bot = random.choice(squad_bots)
            await target_bot.send_message(chat_id, f"{mention} {random.choice(words)}", parse_mode='html')
        except Exception as e:
            print(f"Tracking Error: {e}")
        return 

    # (D) Message Learning
    if learning_status.get(chat_id, False) and not text.startswith(('/', '.', 'မှတ်', '@')):
        # ⚡ Async DB Check & Insert ဖြင့် လုံးဝ လေးမသွားအောင် ပြင်ဆင်ထားပါတယ်
        talker = await talker_col.find_one({"user_id": sender_id})
        
        if talker and len(text) > 1 and not re.search(r'https?://', text):
            await talk_col.insert_one({
                "text": text, 
                "nickname": talker.get("nickname", "Anonymous"),
                "chat_id": chat_id 
            })

# ==========================================
# 🚀 START SYSTEM
# ==========================================
async def start_system():
    threading.Thread(target=run_flask, daemon=True).start()

    print("Starting all 5 bots and fetching IDs & Names...")
    
    await bot1.start(bot_token=MAIN_BOT_TOKEN)
    me_main = await bot1.get_me()
    bot_ids.append(me_main.id)
    bot_names.append(me_main.first_name)
    
    for i, bot in enumerate(squad_bots):
        await bot.start(bot_token=SQUAD_TOKENS[i])
        me_squad = await bot.get_me()
        bot_ids.append(me_squad.id)
        bot_names.append(me_squad.first_name)

    print(f"✅ BoDx Sovereign System Online with {len(all_bots)} Bots!")
    print(f"🤖 Bot Names: {', '.join(bot_names)}")
    
    await asyncio.gather(*(bot.run_until_disconnected() for bot in all_bots))

if __name__ == "__main__":
    asyncio.run(start_system())

