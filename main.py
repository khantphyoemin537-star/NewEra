# -*- coding: utf-8 -*-
"""
BOD Social & Match Bot  (v2)

  * Social feed : text / photo / video / voice / album posts, 7 reactions (one per member),
                  comments you can actually read, polls, share links, Feed + Top
  * Deep links  : t.me/<bot>?start=post_<id>  opens that post
  * Albums      : stored with sendMediaGroup and shown as ONE grid (reactions sit in a message right under it)
  * Matchmaking : name, age (18+), gender, "looking for", bio, profile photo, mutual-like -> match
  * Premium emoji on inline buttons (icon_custom_emoji_id) with automatic plain-emoji fallback
  * Config only from .env   (API_ID, API_HASH, BOT_TOKEN, MONGO_URI, OWNER_ID, STORAGE_GROUP_ID, BOT_USERNAME)

pip install telethon motor python-dotenv
"""
import os
import re
import json
import html
import time
import uuid
import random
import asyncio
import traceback
import urllib.request
import urllib.error
from datetime import datetime, timezone
from urllib.parse import quote

from telethon import TelegramClient, events
from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
from motor.motor_asyncio import AsyncIOMotorClient
from dotenv import load_dotenv

load_dotenv()

# ============================================================
# ⚙️ CONFIG  (everything comes from .env — nothing secret lives in the code)
# ============================================================
def _int_env(name: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default

API_ID           = _int_env("API_ID")
API_HASH         = os.environ.get("API_HASH", "")
BOT_TOKEN        = os.environ.get("BOT_TOKEN", "")
MONGO_URI        = os.environ.get("MONGO_URI", "")
OWNER_ID         = _int_env("OWNER_ID")
STORAGE_GROUP_ID = _int_env("STORAGE_GROUP_ID")                 # private group where post media is kept
BOT_USERNAME     = os.environ.get("BOT_USERNAME", "").lstrip("@")   # optional - detected automatically when empty
API_URL          = f"https://api.telegram.org/bot{BOT_TOKEN}/"

MAX_POST_TEXT      = 3000
MAX_COMMENT        = 500
MAX_COMMENTS_KEPT  = 500
COMMENTS_PER_PAGE  = 8
MAX_POLL_OPTIONS   = 10
MIN_AGE, MAX_AGE   = 18, 99
MAX_UPLOAD_BYTES   = 49 * 1024 * 1024          # Bot API upload limit is 50 MB
CAPTION_LIMIT      = 1000                      # Telegram caption limit is 1024

def validate_env():
    missing = [n for n in ("API_ID", "API_HASH", "BOT_TOKEN", "MONGO_URI", "STORAGE_GROUP_ID") if not os.environ.get(n)]
    if missing:
        raise SystemExit("❌ Missing in .env: " + ", ".join(missing))

esc = html.escape

# ============================================================
# ✨ PREMIUM EMOJI REGISTRY
# ============================================================
PREMIUM_EMOJI = {
    # Reactions
    "love": 6329898676013505314,     # 🤩
    "like": 5465465194056525619,     # 👍
    "haha": 5406913184810409829,     # 😂
    "sad": 6177233797189211160,      # 🥺
    "dislike": 6174726983692326430,  # 👎
    "care": 6176993798711677814,     # 🤗
    "yuck": 6176805232467514463,     # 🤮

    # System
    "comment": 5215327832040811010,
    "share": 6240200624793720535,
    "fire": 5402406965252989103,
    "info": 5456309534962234647,
    "match": 5217449524410199951,
    "user": 5465465194056525619,
    "stats": 5231200819986047254,
    "post": 6039522349517115015,
    "poll": 5422357698228290320,
    "top": 5373110220232870002,
}

EMOJI_FALLBACK = {
    "love": "🤩", "like": "👍", "haha": "😂", "sad": "🥺",
    "dislike": "👎", "care": "🤗", "yuck": "🤮",
    "comment": "💬", "share": "🔗", "fire": "🔥", "info": "ℹ️",
    "match": "🎉", "user": "👤", "stats": "📊", "post": "📝",
    "poll": "📊", "top": "🏆",
    # no premium id yet -> plain emoji until you add one above
    "check": "✅", "feed": "📰", "report": "🚩", "edit": "✏️", "trash": "🗑", "menu": "🏠",
    "cancel": "✖️", "next": "➡️", "older": "⬅️", "newer": "➡️", "photo": "📷",
}
REACTIONS = ("love", "like", "haha", "sad", "dislike", "care", "yuck")

def pe(key: str) -> str:
    """Premium emoji for message TEXT (falls back to a normal emoji when no id is set)."""
    eid = PREMIUM_EMOJI.get(key)
    fb = EMOJI_FALLBACK.get(key, "✨")
    return f'<tg-emoji emoji-id="{eid}">{fb}</tg-emoji>' if eid else fb

_TG_EMOJI_RE = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', re.S)

def plain_emoji(text: str) -> str:
    return _TG_EMOJI_RE.sub(r"\1", text)

def strip_tags(text: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", plain_emoji(text)))
# ============================================================
# 🌍 WEB SERVER (For Render/Heroku)
# ============================================================
async def _health(reader, writer):
    await reader.read(100)
    writer.write(b"HTTP/1.1 200 OK\r\nContent-Type: text/plain\r\nContent-Length: 2\r\n\r\nOK")
    await writer.drain()
    writer.close()

async def start_health_server():
    port = int(os.environ.get("PORT", 10000))
    try:
        srv = await asyncio.start_server(_health, "0.0.0.0", port)
        async with srv:
            await srv.serve_forever()
    except Exception:
        pass

# ============================================================
# 🌐 BOT API CLIENT  (+ premium-icon buttons with automatic fallback)
# ============================================================
def _encode_multipart(fields: dict, files: list):
    """multipart/form-data body. files = [(field, filename, bytes, mime), ...]"""
    boundary = "----bod" + os.urandom(12).hex()
    chunks = []
    for k, v in fields.items():
        if isinstance(v, bool):
            v = "true" if v else "false"
        elif isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8"))
    for field, filename, content, mime in files:
        chunks.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
                      f"Content-Type: {mime}\r\n\r\n".encode("utf-8") + content + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"

def _api_sync(method: str, payload: dict, files: list | None = None) -> dict:
    if files:
        data, ctype = _encode_multipart(payload, files)
    else:
        data, ctype = json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json"
    req = urllib.request.Request(API_URL + method, data=data, headers={"Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=90 if files else 30) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "description": f"HTTP {e.code}"}
    except Exception as e:
        return {"ok": False, "description": f"{type(e).__name__}: {e}"}

async def api(method: str, _files: list | None = None, **payload) -> dict:
    payload = {k: v for k, v in payload.items() if v is not None}
    res: dict = {}
    for attempt in range(2):
        res = await asyncio.to_thread(_api_sync, method, payload, _files)
        wait = (res.get("parameters") or {}).get("retry_after")
        if res.get("ok") or not wait or attempt:
            break
        await asyncio.sleep(min(int(wait), 20))
    if not res.get("ok"):
        print(f"⚠️ Bot API {method}: {res.get('description')}")
    return res

# ---- buttons ---------------------------------------------------------------
def B(text: str, data: str | None = None, *, url: str | None = None, icon: str | None = None, style: str | None = None) -> dict:
    """One inline button. `icon` is a key of PREMIUM_EMOJI/EMOJI_FALLBACK; `style` = primary | success | danger."""
    return {"text": text, "data": data, "url": url, "icon": icon, "style": style}

def render_kb(rows: list, icons: bool) -> list:
    out = []
    for row in rows:
        r = []
        for b in row:
            d = {"text": b["text"]}
            if b.get("data"):
                d["callback_data"] = b["data"]
            if b.get("url"):
                d["url"] = b["url"]
            icon = b.get("icon")
            eid = PREMIUM_EMOJI.get(icon) if icon else None
            if icon and icons and eid:
                d["icon_custom_emoji_id"] = str(eid)                       # real premium emoji on the button
            elif icon:
                d["text"] = f"{EMOJI_FALLBACK.get(icon, '')} {b['text']}".strip()
            if icons and b.get("style"):
                d["style"] = b["style"]
            r.append(d)
        out.append(r)
    return out

_FATAL = ("chat not found", "bot was blocked", "forbidden", "user is deactivated", "not enough rights",
          "have no rights", "message to edit not found", "message can't be edited", "message is not modified",
          "message to delete not found", "message to copy not found", "too many requests")
_icons_off_until = 0.0

async def tg(method: str, kb: list | None = None, _files: list | None = None, text_key: str | None = None, **payload) -> dict:
    """Call a Bot API method.
       kb  = rows of B() buttons.   text_key = the payload key holding HTML text ("text" or "caption").
       Tries premium icons first; if Telegram refuses, retries with plain-emoji buttons, then plain text.
       If icons were the problem they stay off for 10 minutes so we don't double every call."""
    global _icons_off_until
    text = payload.pop(text_key, None) if text_key else None
    has_icons = bool(kb) and any(b.get("icon") or b.get("style") for row in kb for b in row)
    variants = []
    if has_icons and time.monotonic() >= _icons_off_until:
        variants.append((text, True, "HTML"))
    variants.append((text, False, "HTML"))
    if text and plain_emoji(text) != text:
        variants.append((plain_emoji(text), False, "HTML"))
    if text:
        variants.append((strip_tags(text), False, None))
    tried, res, icon_attempt_failed = set(), {}, False
    for t, icons, pm in variants:
        p = dict(payload)
        if text_key and t is not None:
            p[text_key] = t
            if pm:
                p["parse_mode"] = pm
        if kb is not None:
            p["reply_markup"] = {"inline_keyboard": render_kb(kb, icons)}
        sig = json.dumps(p, sort_keys=True, default=str)
        if sig in tried:
            continue
        tried.add(sig)
        res = await api(method, _files=_files, **p)
        if res.get("ok"):
            if icon_attempt_failed and not icons:
                _icons_off_until = time.monotonic() + 600
            return res
        if any(f in (res.get("description") or "").lower() for f in _FATAL):
            break
        if icons and has_icons:
            icon_attempt_failed = True
    return res

async def send_text(chat_id, text: str, kb: list | None = None, **extra) -> dict:
    return await tg("sendMessage", kb=kb, text_key="text", chat_id=chat_id, text=text,
                    link_preview_options={"is_disabled": True}, **extra)

# ============================================================
# 🗄️ DATABASE
# ============================================================
_mongo = AsyncIOMotorClient(MONGO_URI)
db = _mongo["social_match_bot"]
users_col  = db["users"]
posts_col  = db["posts"]
swipes_col = db["swipes"]
states_col = db["states"]

bot = TelegramClient("social_match_session", API_ID, API_HASH)

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def new_id() -> str:
    return uuid.uuid4().hex[:8]

async def ensure_indexes():
    for coro in (
        users_col.create_index("user_id", unique=True),
        posts_col.create_index("post_id", unique=True),
        posts_col.create_index([("created_at", -1)]),
        swipes_col.create_index([("from_id", 1), ("to_id", 1)], unique=True),
        states_col.create_index("user_id", unique=True),
        states_col.create_index("updated_at", expireAfterSeconds=7200),     # forgotten half-finished flows expire
    ):
        try:
            await coro
        except Exception as e:
            print(f"⚠️ index: {e}")

async def set_state(uid: int, **kv):
    kv["updated_at"] = now_utc()
    await states_col.update_one({"user_id": uid}, {"$set": kv}, upsert=True)

async def get_state(uid: int) -> dict | None:
    return await states_col.find_one({"user_id": uid})

async def clear_state(uid: int):
    await states_col.delete_one({"user_id": uid})

def display_name(u) -> str:
    n = f"{getattr(u, 'first_name', '') or ''} {getattr(u, 'last_name', '') or ''}".strip()
    return n[:60] or "User"

def post_link(post_id: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start=post_{post_id}"

def has_real_media(msg) -> bool:
    """Photo / video / voice / audio / file / sticker — but NOT a link preview."""
    return isinstance(getattr(msg, "media", None), (MessageMediaPhoto, MessageMediaDocument))

def safe(name: str):
    """Log errors instead of dying silently, and stop the 'loading' spinner on buttons."""
    def deco(fn):
        async def wrapper(event):
            try:
                await fn(event)
            except Exception:
                print(f"❌ handler {name} failed")
                traceback.print_exc()
                if getattr(event, "data", None) is not None:
                    try:
                        await event.answer("⚠️ တစ်ခုခုမှားသွားပါတယ်။ ပြန်စမ်းကြည့်ပါ။", alert=True)
                    except Exception:
                        pass
        wrapper.__name__ = fn.__name__
        return wrapper
    return deco

# ============================================================
# 🎨 KEYBOARDS
# ============================================================
def _ctx_rows(ctx: str) -> list:
    """ctx: ''  | 'f<n>' = Feed position n | 'd' = opened from a share link."""
    if ctx.startswith("f") and ctx[1:].isdigit():
        return [[B("Next Post", f"feed:{int(ctx[1:]) + 1}", icon="next")]]
    if ctx == "d":
        return [[B("Menu", "menu:home", icon="fire")]]
    return []

def post_kb(post: dict, ctx: str = "") -> list:
    pid, sfx = post["post_id"], (f":{ctx}" if ctx else "")
    r = post.get("reactions") or {}
    def rb(k):
        return B(str(len(r.get(k, []))), f"react:{k}:{pid}{sfx}", icon=k)
    shares = max(len(post.get("shared_by") or []), int(post.get("shares") or 0))
    rows = [
        [rb("love"), rb("like"), rb("haha"), rb("sad")],
        [rb("dislike"), rb("care"), rb("yuck")],
        [B(f"Comments ({len(post.get('comments') or [])})", f"cm:view:{pid}", icon="comment"),
         B("Comment ရေးမည်", f"cm:write:{pid}", icon="post")],
        [B(f"Share ({shares})", f"share:{pid}{sfx}", icon="share")],
    ]
    return rows + _ctx_rows(ctx)

def poll_kb(post: dict, ctx: str = "") -> list:
    pid, sfx = post["post_id"], (f":{ctx}" if ctx else "")
    opts = post["poll_options"]
    total = sum(len(o["votes"]) for o in opts) or 0
    rows = []
    for i, o in enumerate(opts):
        n = len(o["votes"])
        pct = f" · {round(n * 100 / total)}%" if total else ""
        rows.append([B(f"{o['text']}  ({n}{pct})", f"vote:{pid}:{i}{sfx}")])
    return rows + _ctx_rows(ctx)

def menu_kb() -> list:
    return [
        [B("Post တင်မည်", "menu:post", icon="post"), B("Poll တင်မည်", "menu:poll", icon="poll")],
        [B("Feed ကြည့်မည်", "menu:feed", icon="feed"), B("Top Posts", "menu:top", icon="top")],
        [B("သူငယ်ချင်း / ရည်းစား ရှာမည်", "menu:match", icon="match", style="primary")],
        [B("ကျွန်ုပ်၏ Match Profile", "menu:myprofile", icon="user")],
    ]

async def send_menu(chat_id):
    await send_text(chat_id, (f"{pe('fire')} <b>BOD Social &amp; Match မှ ကြိုဆိုပါတယ်!</b>\n\n"
                              f"ဒီနေ့ ဘာလုပ်ချင်ပါသလဲ?"), menu_kb())

# ============================================================
# 📰 SHOWING POSTS
# ============================================================
def post_header(post: dict) -> str:
    return f"{pe('user')} <b>{esc(post.get('author_name') or 'User')}</b>"

def post_caption(post: dict) -> str:
    t = esc(post.get("text") or "")
    return f"{post_header(post)}\n\n{t}" if t else post_header(post)

async def show_post(chat_id, post: dict, ctx: str = "", prefix: str = "") -> dict:
    pid = post["post_id"]
    try:
        await posts_col.update_one({"post_id": pid}, {"$inc": {"views": 1}})
    except Exception:
        pass
    if post.get("is_poll"):
        text = f"{prefix}{pe('poll')} <b>POLL</b>\n\n{post_header(post)}\n\n❓ {esc(post.get('text') or '')}"
        return await send_text(chat_id, text, poll_kb(post, ctx))

    kb, header = post_kb(post, ctx), prefix + post_caption(post)

    if post.get("album"):                                   # ONE grid, reactions in a message right under it
        res = await tg("sendMediaGroup", chat_id=chat_id,
                       media=[{"type": a["type"], "media": a["file_id"]} for a in post["album"]])
        first = (res.get("result") or [{}])[0].get("message_id") if res.get("ok") else None
        extra = {"reply_parameters": {"message_id": first, "allow_sending_without_reply": True}} if first else {}
        return await send_text(chat_id, header, kb, **extra)

    if post.get("storage_msg_ids"):                         # posts made by the old version (album copied one by one)
        await tg("copyMessages", chat_id=chat_id, from_chat_id=STORAGE_GROUP_ID, message_ids=post["storage_msg_ids"])
        return await send_text(chat_id, header, kb)

    if post.get("storage_msg_id"):
        if len(strip_tags(header)) <= CAPTION_LIMIT:
            res = await tg("copyMessage", kb=kb, text_key="caption", chat_id=chat_id,
                           from_chat_id=STORAGE_GROUP_ID, message_id=post["storage_msg_id"], caption=header)
            if res.get("ok"):
                return res
        await tg("copyMessage", chat_id=chat_id, from_chat_id=STORAGE_GROUP_ID, message_id=post["storage_msg_id"], caption="")
        return await send_text(chat_id, header, kb)

    return await send_text(chat_id, header, kb)

async def refresh_kb(event, post_id: str, ctx: str):
    """Re-draw the buttons (new counts) of the message the member just pressed."""
    post = await posts_col.find_one({"post_id": post_id})
    if post:
        kb = poll_kb(post, ctx) if post.get("is_poll") else post_kb(post, ctx)
        await tg("editMessageReplyMarkup", kb=kb, chat_id=event.chat_id, message_id=event.query.msg_id)

# ============================================================
# 🚀 /start  ·  MENU  ·  DEEP LINKS
# ============================================================
def _private(e) -> bool:
    return bool(getattr(e, "is_private", False))

@bot.on(events.NewMessage(pattern=r"^/start(?:\s+(\S+))?\s*$", incoming=True, func=_private))
@safe("start")
async def start_cmd(event):
    await clear_state(event.sender_id)
    arg = event.pattern_match.group(1)
    if arg and arg.startswith("post_"):
        post = await posts_col.find_one({"post_id": arg[5:]})
        if post:
            await show_post(event.chat_id, post, ctx="d")
            return
        await send_text(event.chat_id, f"{pe('info')} ဒီ Post ကို မတွေ့တော့ပါဘူး။ ဖျက်လိုက်ပြီး ဖြစ်နိုင်ပါတယ်။")
    await send_menu(event.chat_id)

@bot.on(events.NewMessage(pattern=r"^/(?:menu|help)\s*$", incoming=True, func=_private))
@safe("menu_cmd")
async def menu_cmd(event):
    await clear_state(event.sender_id)
    await send_menu(event.chat_id)

@bot.on(events.NewMessage(pattern=r"^/cancel\s*$", incoming=True, func=_private))
@safe("cancel")
async def cancel_cmd(event):
    await clear_state(event.sender_id)
    await send_text(event.chat_id, f"{pe('check')} ပယ်ဖျက်လိုက်ပါပြီ။", [[B("Menu", "menu:home", icon="fire")]])

@bot.on(events.NewMessage(pattern=r"^/feed\s*$", incoming=True, func=_private))
@safe("feed_cmd")
async def feed_cmd(event):
    await show_feed(event.chat_id, 0)

@bot.on(events.NewMessage(pattern=r"^/top\s*$", incoming=True, func=_private))
@safe("top_cmd")
async def top_cmd(event):
    await show_top(event.chat_id)

@bot.on(events.NewMessage(pattern=r"^/delpost\s+(\w+)\s*$", incoming=True, func=_private))
@safe("delpost")
async def delpost_cmd(event):
    pid = event.pattern_match.group(1)
    post = await posts_col.find_one({"post_id": pid})
    if not post:
        await send_text(event.chat_id, f"{pe('info')} Post မတွေ့ပါ။")
        return
    if event.sender_id not in (post["author_id"], OWNER_ID):
        await send_text(event.chat_id, f"{pe('info')} ကိုယ့် Post ကိုပဲ ဖျက်လို့ရပါတယ်။")
        return
    await posts_col.delete_one({"post_id": pid})
    stored = ([post["storage_msg_id"]] if post.get("storage_msg_id") else []) \
        + list(post.get("storage_msg_ids") or []) + list(post.get("album_msg_ids") or [])
    for mid in stored:
        await tg("deleteMessage", chat_id=STORAGE_GROUP_ID, message_id=mid)
    await send_text(event.chat_id, f"{pe('check')} Post <code>{esc(pid)}</code> ကို ဖျက်လိုက်ပါပြီ။")

@bot.on(events.CallbackQuery(pattern=rb"^menu:"))
@safe("menu_cb")
async def menu_cb(event):
    action, uid, chat = event.data.decode().split(":")[1], event.sender_id, event.chat_id
    await event.answer()
    if action == "home":
        await clear_state(uid)
        await send_menu(chat)
    elif action == "post":
        await set_state(uid, step="post_content")
        await send_text(chat, (f"{pe('post')} သင့်ရဲ့ Post ကို ပို့ပေးပါ။\n\n"
                               f"စာသား၊ ဓာတ်ပုံ၊ ဗီဒီယို၊ Voice သို့မဟုတ် ပုံအများကြီး (Album) ပို့လို့ရပါတယ်။\n"
                               f"<i>ပယ်ဖျက်ချင်ရင် /cancel</i>"))
    elif action == "poll":
        await set_state(uid, step="poll_question")
        await send_text(chat, f"{pe('poll')} Poll အတွက် မေးခွန်းကို ရိုက်ထည့်ပါ -")
    elif action == "feed":
        await show_feed(chat, 0)
    elif action == "top":
        await show_top(chat)
    elif action == "match":
        user = await users_col.find_one({"user_id": uid})
        if user and user.get("gender"):
            await find_match(chat, uid)
        else:
            await start_profile(chat, uid, upgrade=bool(user))
    elif action == "myprofile":
        user = await users_col.find_one({"user_id": uid})
        if not user:
            await send_text(chat, f"{pe('info')} Match Profile မရှိသေးပါ။", [[B("Profile ဖန်တီးမည်", "menu:match", icon="match")]])
            return
        await show_card(chat, user, [[B("ပြင်မည်", "mp:edit", icon="edit"), B("ဖျက်မည်", "mp:del", icon="trash", style="danger")],
                                     [B("Menu", "menu:home", icon="fire")]])

# ============================================================
# 📰 FEED  ·  🏆 TOP
# ============================================================
async def show_feed(chat_id, n: int):
    docs = await posts_col.find({}).sort("created_at", -1).skip(n).limit(1).to_list(1)
    if not docs:
        text = "Post မရှိသေးပါ။ ပထမဆုံး Post ကို တင်ကြည့်ပါ!" if n == 0 else "နောက်ထပ် Post မရှိတော့ပါဘူး။ ပြန်ကြည့်ဖို့ Feed ကို ပြန်နှိပ်ပါ။"
        await send_text(chat_id, f"{pe('info')} {text}", [[B("Menu", "menu:home", icon="fire")]])
        return
    await show_post(chat_id, docs[0], ctx=f"f{n}")

@bot.on(events.CallbackQuery(pattern=rb"^feed:"))
@safe("feed_cb")
async def feed_cb(event):
    await event.answer()
    n = event.data.decode().split(":")[1]
    await show_feed(event.chat_id, int(n) if n.isdigit() else 0)

def post_score(p: dict) -> int:
    reacts = sum(len(v) for v in (p.get("reactions") or {}).values())
    shares = max(len(p.get("shared_by") or []), int(p.get("shares") or 0))
    return reacts + 2 * len(p.get("comments") or []) + 3 * shares

async def show_top(chat_id):
    docs = await posts_col.find({"is_poll": {"$ne": True}}).sort("created_at", -1).limit(300).to_list(300)
    docs = sorted((d for d in docs if post_score(d) > 0), key=post_score, reverse=True)[:3]
    if not docs:
        await send_text(chat_id, f"{pe('info')} Reaction ရထားတဲ့ Post မရှိသေးပါ။", [[B("Menu", "menu:home", icon="fire")]])
        return
    await send_text(chat_id, f"{pe('top')} <b>TOP POSTS</b>\n<i>Reaction · Comment · Share အများဆုံး</i>")
    for i, d in enumerate(docs, 1):
        await show_post(chat_id, d, prefix=f"{pe('top')} <b>#{i}</b> · <b>{post_score(d)}</b> points\n\n")

# ============================================================
# 📝 POST CREATION  (text · single media · album · poll)
# ============================================================
def _post_doc(uid: int, name: str, text: str, **extra) -> dict:
    return {"post_id": new_id(), "author_id": uid, "author_name": name, "text": text, "created_at": now_utc(),
            "reactions": {}, "comments": [], "shared_by": [], "views": 0, **extra}

async def publish(chat_id, post: dict):
    await posts_col.insert_one(post)
    await clear_state(post["author_id"])
    await send_text(chat_id, (f"{pe('check')} Post တင်ပြီးပါပြီ!\n"
                              f"<i>ဖျက်ချင်ရင် <code>/delpost {post['post_id']}</code></i>"))
    await show_post(chat_id, post)

async def save_single_post(event, text: str):
    msg, uid, chat = event.message, event.sender_id, event.chat_id
    text = text[:MAX_POST_TEXT]
    media = has_real_media(msg)
    if not text and not media:
        await send_text(chat, f"{pe('info')} စာသား၊ ဓာတ်ပုံ၊ ဗီဒီယို၊ Voice တစ်ခုခု ပို့ပေးပါ။")
        return
    extra = {}
    if media:
        res = await tg("copyMessage", chat_id=STORAGE_GROUP_ID, from_chat_id=chat, message_id=msg.id)
        if not res.get("ok"):
            await send_text(chat, f"{pe('info')} Media သိမ်းလို့မရပါဘူး။ Bot က Storage Group ထဲမှာ ရှိမရှိ စစ်ပါ။")
            return
        extra["storage_msg_id"] = res["result"]["message_id"]
    sender = await event.get_sender()
    await publish(chat, _post_doc(uid, display_name(sender), text, **extra))

@bot.on(events.Album(func=_private))
@safe("album")
async def album_handler(event):
    uid, chat = event.sender_id, event.chat_id
    state = await get_state(uid)
    if not state or state.get("step") != "post_content":
        return
    text = next((m.raw_text for m in event.messages if m.raw_text), "")[:MAX_POST_TEXT]
    files, media, skipped = [], [], 0
    for i, m in enumerate(event.messages):
        if isinstance(m.media, MessageMediaPhoto):
            kind, mime, ext = "photo", "image/jpeg", "jpg"
        elif getattr(m, "video", None):
            kind, mime, ext = "video", "video/mp4", "mp4"
        else:
            skipped += 1
            continue
        if (getattr(getattr(m, "file", None), "size", 0) or 0) > MAX_UPLOAD_BYTES:
            skipped += 1
            continue
        data = await m.download_media(file=bytes)
        files.append((f"f{i}", f"f{i}.{ext}", data, mime))
        media.append({"type": kind, "media": f"attach://f{i}"})
    if len(media) < 2:
        await send_text(chat, f"{pe('info')} Album အတွက် ဓာတ်ပုံ/ဗီဒီယို အနည်းဆုံး ၂ ခု (တစ်ခုချင်း ၄၉MB အောက်) လိုပါတယ်။")
        return
    res = await tg("sendMediaGroup", _files=files, chat_id=STORAGE_GROUP_ID, media=media)
    if not res.get("ok"):
        await send_text(chat, f"{pe('info')} Album သိမ်းလို့မရပါဘူး။ Bot က Storage Group ထဲမှာ ရှိမရှိ စစ်ပါ။")
        return
    album, ids = [], []
    for m in res["result"]:
        ids.append(m["message_id"])
        if m.get("photo"):
            album.append({"type": "photo", "file_id": m["photo"][-1]["file_id"]})
        elif m.get("video"):
            album.append({"type": "video", "file_id": m["video"]["file_id"]})
    sender = await event.get_sender()
    await publish(chat, _post_doc(uid, display_name(sender), text, album=album, album_msg_ids=ids))
    if skipped:
        await send_text(chat, f"{pe('info')} ပံ့ပိုးမထားတဲ့ ဖိုင် {skipped} ခုကို ချန်ထားခဲ့ပါတယ်။")

# ============================================================
# ❤️ REACTIONS · POLL VOTES · SHARE
# ============================================================
def _ctx(parts: list, i: int) -> str:
    return parts[i] if len(parts) > i else ""

@bot.on(events.CallbackQuery(pattern=rb"^react:"))
@safe("react")
async def react_cb(event):
    parts = event.data.decode().split(":")
    r_type, pid, ctx, uid = parts[1], parts[2], _ctx(parts, 3), event.sender_id
    if r_type not in REACTIONS:
        await event.answer()
        return
    post = await posts_col.find_one({"post_id": pid})
    if not post:
        await event.answer("Post မတွေ့တော့ပါ။", alert=True)
        return
    if uid in (post.get("reactions") or {}).get(r_type, []):                     # same reaction again = remove it
        await posts_col.update_one({"post_id": pid}, {"$pull": {f"reactions.{r_type}": uid}})
        await event.answer("Reaction ဖျက်လိုက်ပါပြီ")
    else:                                                                        # one reaction per member: switch
        await posts_col.update_one({"post_id": pid}, {
            "$pull": {f"reactions.{k}": uid for k in REACTIONS if k != r_type},
            "$addToSet": {f"reactions.{r_type}": uid}})
        await event.answer(f"{EMOJI_FALLBACK[r_type]} Reaction ပေးလိုက်ပါပြီ!")
    await refresh_kb(event, pid, ctx)

@bot.on(events.CallbackQuery(pattern=rb"^vote:"))
@safe("vote")
async def vote_cb(event):
    parts = event.data.decode().split(":")
    pid, ctx, uid = parts[1], _ctx(parts, 3), event.sender_id
    post = await posts_col.find_one({"post_id": pid})
    if not post or not post.get("is_poll"):
        await event.answer("Poll မတွေ့ပါ။", alert=True)
        return
    try:
        idx = int(parts[2])
        opts = post["poll_options"]
        voted_same = uid in opts[idx]["votes"]
    except (ValueError, IndexError):
        await event.answer()
        return
    for o in opts:
        if uid in o["votes"]:
            o["votes"].remove(uid)
    if not voted_same:
        opts[idx]["votes"].append(uid)
    await posts_col.update_one({"post_id": pid}, {"$set": {"poll_options": opts}})
    await event.answer("မဲပေးပြီးပါပြီ။" if not voted_same else "မဲ ပြန်ရုပ်သိမ်းလိုက်ပါပြီ။")
    await refresh_kb(event, pid, ctx)

@bot.on(events.CallbackQuery(pattern=rb"^share:"))
@safe("share")
async def share_cb(event):
    parts = event.data.decode().split(":")
    pid, ctx = parts[1], _ctx(parts, 2)
    await event.answer()
    await posts_col.update_one({"post_id": pid}, {"$addToSet": {"shared_by": event.sender_id}})
    link = post_link(pid)
    share_url = f"https://t.me/share/url?url={quote(link, safe='')}&text={quote('ဒီ Post လေးကြည့်ကြည့်ပါ 👀')}"
    await send_text(event.chat_id, (f"{pe('share')} <b>Share Link</b>\n\n<code>{esc(link)}</code>\n\n"
                                    f"<i>ဒီ Link ကိုနှိပ်တဲ့သူတိုင်း Post ကို တိုက်ရိုက်မြင်ရပါမယ်။</i>"),
                    [[B("Telegram မှာ ပို့မည်", url=share_url, icon="share", style="primary")]])
    await refresh_kb(event, pid, ctx)

# ============================================================
# 💬 COMMENTS  (write + READ)
# ============================================================
def comments_view(post: dict, page: int):
    cs = post.get("comments") or []
    n = len(cs)
    pages = max(1, -(-n // COMMENTS_PER_PAGE))
    page = max(0, min(page, pages - 1))
    end = n - page * COMMENTS_PER_PAGE                       # page 0 = the newest comments
    chunk = cs[max(0, end - COMMENTS_PER_PAGE):end]
    pid = post["post_id"]
    head = f"{pe('comment')} <b>Comments</b> ({n}) · စာမျက်နှာ {page + 1}/{pages}\n\n"
    if chunk:
        body = "\n\n".join(f"<b>{esc(c.get('name') or 'User')}</b>\n{esc((c.get('text') or '')[:300])}" for c in chunk)
    else:
        body = "Comment မရှိသေးပါဘူး။ ပထမဆုံး ရေးကြည့်ပါ!"
    nav = []
    if page + 1 < pages:
        nav.append(B("အဟောင်း", f"cm:p:{pid}:{page + 1}", icon="older"))
    if page > 0:
        nav.append(B("အသစ်", f"cm:p:{pid}:{page - 1}", icon="newer"))
    rows = ([nav] if nav else []) + [[B("Comment ရေးမည်", f"cm:write:{pid}", icon="post"), B("ပိတ်မည်", "cm:x", icon="cancel")]]
    return head + body, rows

@bot.on(events.CallbackQuery(pattern=rb"^cm:"))
@safe("comments_cb")
async def comments_cb(event):
    parts = event.data.decode().split(":")
    action, chat, uid = parts[1], event.chat_id, event.sender_id
    if action == "x":
        await event.answer()
        await tg("deleteMessage", chat_id=chat, message_id=event.query.msg_id)
        return
    pid = parts[2] if len(parts) > 2 else ""
    post = await posts_col.find_one({"post_id": pid})
    if not post:
        await event.answer("Post မတွေ့တော့ပါ။", alert=True)
        return
    await event.answer()
    if action == "view":
        text, rows = comments_view(post, 0)
        await send_text(chat, text, rows, reply_parameters={"message_id": event.query.msg_id, "allow_sending_without_reply": True})
    elif action == "p":
        text, rows = comments_view(post, int(parts[3]) if len(parts) > 3 and parts[3].isdigit() else 0)
        await tg("editMessageText", kb=rows, text_key="text", chat_id=chat, message_id=event.query.msg_id, text=text,
                 link_preview_options={"is_disabled": True})
    elif action == "write":
        await set_state(uid, step="comment", post_id=pid)
        await send_text(chat, f"{pe('comment')} သင့် Comment ကို ရိုက်ထည့်ပါ -\n<i>ပယ်ဖျက်ချင်ရင် /cancel</i>")

async def add_comment(event, state: dict, text: str):
    uid, chat, pid = event.sender_id, event.chat_id, state["post_id"]
    post = await posts_col.find_one({"post_id": pid})
    await clear_state(uid)
    if not post:
        await send_text(chat, f"{pe('info')} Post မတွေ့တော့ပါ။")
        return
    sender = await event.get_sender()
    name = display_name(sender)
    await posts_col.update_one({"post_id": pid}, {"$push": {"comments": {
        "$each": [{"uid": uid, "name": name, "text": text[:MAX_COMMENT], "at": now_utc()}], "$slice": -MAX_COMMENTS_KEPT}}})
    await send_text(chat, f"{pe('check')} Comment ရေးပြီးပါပြီ။", [[B("Comments ကြည့်မည်", f"cm:view:{pid}", icon="comment")]])
    if post["author_id"] != uid:
        await send_text(post["author_id"], (f"{pe('comment')} <b>Comment အသစ်!</b>\n\n"
                                            f"<b>{esc(name)}</b>: {esc(text[:300])}"),
                        [[B("Comments ကြည့်မည်", f"cm:view:{pid}", icon="comment")]])

# ============================================================
# 📊 POLL CREATION
# ============================================================
async def poll_question_step(event, text: str):
    if not text:
        await send_text(event.chat_id, "မေးခွန်းကို စာသားနဲ့ ရိုက်ထည့်ပါ။")
        return
    await set_state(event.sender_id, step="poll_options", question=text[:250])
    await send_text(event.chat_id, (f"{pe('poll')} ရွေးချယ်စရာ (Options) တွေကို ကော်မာ (,) ဒါမှမဟုတ် စာကြောင်းခွဲပြီး ရိုက်ထည့်ပါ။\n"
                                    f"ဥပမာ - Apple, Orange, Banana"))

async def poll_options_step(event, text: str, state: dict):
    seen, opts = set(), []
    for o in re.split(r"[,\n،]", text):
        o = o.strip()[:60]
        if o and o.lower() not in seen:
            seen.add(o.lower())
            opts.append({"text": o, "votes": []})
    if len(opts) < 2:
        await send_text(event.chat_id, "အနည်းဆုံး ၂ ခု ပေးပါ။ (ကော်မာနဲ့ ခြားပါ)")
        return
    sender = await event.get_sender()
    await publish(event.chat_id, _post_doc(event.sender_id, display_name(sender), state["question"],
                                           is_poll=True, poll_options=opts[:MAX_POLL_OPTIONS]))

# ============================================================
# ❤️ MATCHMAKING
# ============================================================
GENDERS = {"male": ("👨", "ကျား"), "female": ("👩", "မ"), "other": ("🧑", "အခြား")}
LOOKING = {"male": "ကျား", "female": "မ", "any": "အားလုံး"}

async def start_profile(chat_id, uid: int, upgrade: bool = False):
    await set_state(uid, step="match_name")
    intro = "Profile အသစ်ပြန်ဖန်တီးပါမယ်။\n\n" if upgrade else ""
    await send_text(chat_id, (f"{pe('user')} {intro}သင့်နာမည် (သို့) အမည်ပြောင် ကို ရိုက်ထည့်ပါ -\n"
                              f"<i>ပယ်ဖျက်ချင်ရင် /cancel</i>"))

def card_text(p: dict) -> str:
    g = GENDERS.get(p.get("gender"), ("🧑", ""))
    return (f"{pe('match')} <b>{esc(p.get('name') or 'User')}</b>, {p.get('age', '?')}\n"
            f"{g[0]} {g[1]}  ·  ရှာနေတာ: <b>{LOOKING.get(p.get('looking_for'), 'အားလုံး')}</b>\n\n"
            f"{pe('post')} {esc(p.get('bio') or '')}")

async def show_card(chat_id, p: dict, kb: list):
    text = card_text(p)
    if p.get("photo_msg_id"):
        res = await tg("copyMessage", kb=kb, text_key="caption", chat_id=chat_id, from_chat_id=STORAGE_GROUP_ID,
                       message_id=p["photo_msg_id"], caption=text)
        if res.get("ok"):
            return
    await send_text(chat_id, text, kb)

def swipe_kb(target_id: int) -> list:
    return [[B("Like", f"match:like:{target_id}", icon="love", style="success"),
             B("Pass", f"match:pass:{target_id}", icon="dislike", style="danger")],
            [B("Report", f"match:report:{target_id}", icon="report"), B("ရပ်မည်", "menu:home", icon="menu")]]

async def find_match(chat_id, uid: int):
    me = await users_col.find_one({"user_id": uid})
    if not me or not me.get("gender"):
        await start_profile(chat_id, uid, upgrade=bool(me))
        return
    swiped = [s["to_id"] for s in await swipes_col.find({"from_id": uid}).to_list(5000)]
    q = {"user_id": {"$ne": uid, "$nin": swiped}, "active": {"$ne": False},
         "looking_for": {"$in": ["any", me["gender"]]}}                       # they must want someone like me
    if me.get("looking_for") in ("male", "female"):
        q["gender"] = me["looking_for"]                                       # and I must want someone like them
    cands = await users_col.find(q).limit(30).to_list(30)
    if not cands:
        await send_text(chat_id, f"{pe('info')} အခုလောလောဆယ် ရှာမတွေ့တော့ပါဘူး။ နောက်မှ ပြန်ကြည့်ပါ။",
                        [[B("Menu", "menu:home", icon="fire")]])
        return
    target = random.choice(cands)
    await show_card(chat_id, target, swipe_kb(target["user_id"]))

async def _contact_line(user_id: int, prof: dict) -> str:
    link = f"<a href=\"tg://user?id={user_id}\">{esc(prof.get('name') or 'Chat')}</a>"
    try:
        uname = getattr(await bot.get_entity(user_id), "username", None)
    except Exception:
        uname = None
    uname = uname or prof.get("username")
    return link + (f" (@{esc(uname)})" if uname else "")

async def notify_match(a: int, b: int):
    pa, pb = await users_col.find_one({"user_id": a}), await users_col.find_one({"user_id": b})
    for me, other, prof in ((a, b, pb or {}), (b, a, pa or {})):
        await send_text(me, (f"{pe('match')} <b>IT'S A MATCH!</b> {pe('match')}\n\n"
                             f"သင်တို့နှစ်ယောက် တစ်ယောက်ကိုတစ်ယောက် သဘောကျသွားပါပြီ!\n\n"
                             f"{pe('user')} {await _contact_line(other, prof)}"))

@bot.on(events.CallbackQuery(pattern=rb"^match:"))
@safe("match")
async def match_cb(event):
    _, action, target = event.data.decode().split(":")
    target_id, uid, chat = int(target), event.sender_id, event.chat_id
    await swipes_col.update_one({"from_id": uid, "to_id": target_id},
                                {"$set": {"action": "like" if action == "like" else "pass", "at": now_utc()}}, upsert=True)
    await tg("deleteMessage", chat_id=chat, message_id=event.query.msg_id)
    if action == "report":
        who = await users_col.find_one({"user_id": target_id}) or {}
        if OWNER_ID:
            await send_text(OWNER_ID, (f"🚩 <b>Profile Report</b>\n\nReporter: <code>{uid}</code>\n"
                                       f"Reported: <code>{target_id}</code> · {esc(who.get('name') or '?')}, {who.get('age', '?')}\n"
                                       f"Bio: {esc(who.get('bio') or '')}"))
        await event.answer("Report လုပ်ပြီးပါပြီ။ ကျေးဇူးတင်ပါတယ်။")
    elif action == "like":
        mutual = await swipes_col.find_one({"from_id": target_id, "to_id": uid, "action": "like"})
        if mutual:
            await event.answer("🎉 Match ဖြစ်သွားပါပြီ!")
            await notify_match(uid, target_id)
        else:
            await event.answer("Like လုပ်လိုက်ပါပြီ")
    else:
        await event.answer("Pass")
    await find_match(chat, uid)

@bot.on(events.CallbackQuery(pattern=rb"^mp:"))
@safe("profile_cb")
async def profile_cb(event):
    parts = event.data.decode().split(":")
    action, uid, chat = parts[1], event.sender_id, event.chat_id
    state = await get_state(uid) or {}
    await event.answer()
    if action == "g" and state.get("step") == "match_gender":
        await set_state(uid, step="match_look", gender=parts[2])
        await send_text(chat, f"{pe('match')} ဘယ်သူ့ကို ရှာချင်ပါသလဲ?",
                        [[B("ကျား", "mp:l:male"), B("မ", "mp:l:female"), B("အားလုံး", "mp:l:any")]])
    elif action == "l" and state.get("step") == "match_look":
        await set_state(uid, step="match_bio", looking_for=parts[2])
        await send_text(chat, f"{pe('info')} သင့်အကြောင်း အတိုချုပ် (Bio) ရေးပါ -")
    elif action == "skip" and state.get("step") == "match_photo":
        await finish_profile(chat, uid, state, None)
    elif action == "edit":
        await start_profile(chat, uid, upgrade=True)
    elif action == "del":
        await users_col.delete_one({"user_id": uid})
        await send_text(chat, f"{pe('check')} Match Profile ကို ဖျက်လိုက်ပါပြီ။", [[B("Menu", "menu:home", icon="fire")]])

async def finish_profile(chat_id, uid: int, state: dict, photo_msg_id: int | None):
    try:
        uname = getattr(await bot.get_entity(uid), "username", None)
    except Exception:
        uname = None
    doc = {"user_id": uid, "name": state["name"], "age": state["age"], "gender": state["gender"],
           "looking_for": state["looking_for"], "bio": state["bio"], "photo_msg_id": photo_msg_id,
           "username": uname, "active": True, "updated_at": now_utc()}
    await users_col.update_one({"user_id": uid}, {"$set": doc}, upsert=True)
    await clear_state(uid)
    await send_text(chat_id, f"{pe('match')} Profile ဖန်တီးပြီးပါပြီ။ စတင်ရှာဖွေပါမည်...")
    await find_match(chat_id, uid)

async def profile_steps(event, step: str, text: str, state: dict):
    uid, chat = event.sender_id, event.chat_id
    if step == "match_name":
        if not text:
            await send_text(chat, "နာမည်ကို စာသားနဲ့ ရိုက်ပါ။")
            return
        await set_state(uid, step="match_age", name=text[:40])
        await send_text(chat, f"{pe('user')} သင့်အသက်ကို ရိုက်ထည့်ပါ - <i>(အသက် {MIN_AGE} နှစ်နှင့်အထက်သာ)</i>")
    elif step == "match_age":
        if not text.isdigit() or not (MIN_AGE <= int(text) <= MAX_AGE):
            await send_text(chat, f"အသက်ကို ဂဏန်းနဲ့ပဲ ရိုက်ပါ။ ({MIN_AGE}–{MAX_AGE} နှစ်အတွင်းသာ လက်ခံပါတယ်)")
            return
        await set_state(uid, step="match_gender", age=int(text))
        await send_text(chat, f"{pe('user')} သင်ရဲ့ လိင်ကို ရွေးပါ -",
                        [[B("ကျား 👨", "mp:g:male"), B("မ 👩", "mp:g:female"), B("အခြား 🧑", "mp:g:other")]])
    elif step in ("match_gender", "match_look"):
        await send_text(chat, "အပေါ်က ခလုတ်တွေကို နှိပ်ပြီး ရွေးပေးပါ။")
    elif step == "match_bio":
        if not text:
            await send_text(chat, "Bio ကို စာသားနဲ့ ရေးပါ။")
            return
        await set_state(uid, step="match_photo", bio=text[:300])
        await send_text(chat, (f"{pe('post')} Profile ဓာတ်ပုံ တစ်ပုံ ပို့ပေးပါ။\n"
                               f"<i>ဓာတ်ပုံမပါဘဲ ဆက်သွားချင်ရင် Skip ကိုနှိပ်ပါ။</i>"),
                        [[B("Skip", "mp:skip", icon="next")]])
    elif step == "match_photo":
        if not isinstance(event.message.media, MessageMediaPhoto):
            await send_text(chat, "ဓာတ်ပုံ (Photo) တစ်ပုံပဲ ပို့ပါ။ မပို့ချင်ရင် Skip ကိုနှိပ်ပါ။")
            return
        res = await tg("copyMessage", chat_id=STORAGE_GROUP_ID, from_chat_id=chat, message_id=event.message.id)
        if not res.get("ok"):
            await send_text(chat, f"{pe('info')} ဓာတ်ပုံသိမ်းလို့မရပါဘူး။ Skip နှိပ်ပြီး ဆက်သွားနိုင်ပါတယ်။")
            return
        await finish_profile(chat, uid, state, res["result"]["message_id"])

# ============================================================
# ✍️ ONE HANDLER FOR EVERY TYPED STEP
# ============================================================
@bot.on(events.NewMessage(incoming=True, func=_private))
@safe("creation")
async def creation_handler(event):
    msg = event.message
    if getattr(msg, "grouped_id", None):
        return                                   # album items are handled once, by album_handler
    text = (event.raw_text or "").strip()
    if text.startswith("/"):
        return                                   # commands are never content
    state = await get_state(event.sender_id)
    if not state:
        return
    step = state.get("step", "")
    if step == "post_content":
        await save_single_post(event, text)
    elif step == "poll_question":
        await poll_question_step(event, text)
    elif step == "poll_options":
        await poll_options_step(event, text, state)
    elif step.startswith("match_"):
        await profile_steps(event, step, text, state)
    elif step == "comment":
        if not text:
            await send_text(event.chat_id, "Comment ကို စာသားနဲ့ ရေးပါ။")
            return
        await add_comment(event, state, text)

# ============================================================
# 🚀 STARTUP
# ============================================================
async def main():
    global BOT_USERNAME
    validate_env()
    asyncio.create_task(start_health_server())
 
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    BOT_USERNAME = BOT_USERNAME or me.username
    await ensure_indexes()
    chk = await api("getChat", chat_id=STORAGE_GROUP_ID)
    if not chk.get("ok"):
        print("⚠️ Storage group not reachable — add the bot to STORAGE_GROUP_ID as an admin, or media posts will fail.")
    print(f"🤖 Social & Match Bot is running as @{BOT_USERNAME}")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
