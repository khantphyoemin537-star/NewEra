# -*- coding: utf-8 -*-
"""
BOD Social & Match Bot  (v3)

  * Social feed : text / photo / video / voice / album posts, 7 reactions (one per member),
                  comments you can actually read, polls, share links, Feed + Top
  * Deep links  : t.me/<bot>?start=post_<id>  opens that post
  * Albums      : stored with sendMediaGroup and shown as ONE grid (reactions sit in a message right under it)
  * Matchmaking : name, age (18+), gender, "looking for", bio, profile photo, mutual-like -> match
  * Premium emoji on inline buttons (icon_custom_emoji_id) with automatic plain-emoji fallback
  * Safety      : report a post (5 reasons, auto-hidden after 3 reports) · moderator buttons · block people
                  · ban users · /reports /ban /unban /stats for moderators
  * Match extras: region + city, Match Filter (place / age / gender), "who liked me" list with teaser notice
  * v3 additions:
      - Auto-post     : every new post is pushed to every group / channel the bot lives in - groups are detected
                        automatically the moment the bot is added (no IDs to type); /autopost on|off for admins
      - Live Feed     : members get new posts pushed to their DM (opt-out: /live off), max one per LIVE_MIN_GAP seconds
      - Mentions      : names in posts / comments / matches are clickable tg://user links (work WITHOUT a @username)
      - Match contact : full Telegram name + @username + "chat" button, privacy-safe fallback
      - Comeback      : passes return to the deck after PASS_RECYCLE_DAYS, /pause /resume, welcome-back boost,
                        profiles of people who blocked the bot are hidden until they return, idle-user nudges
      - Moderation    : group copies of a post are deleted when the post is removed / hidden / its author banned
  * Config only from .env   (API_ID, API_HASH, BOT_TOKEN, MONGO_URI, OWNER_ID, STORAGE_GROUP_ID, BOT_USERNAME, MODERATOR_IDS,
                             AUTO_POST_GROUP_IDS, LIVE_FEED_DEFAULT, LIVE_MIN_GAP, POST_COOLDOWN, PASS_RECYCLE_DAYS, REENGAGE_AFTER_DAYS)

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
import contextvars
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

from telethon import TelegramClient, events, utils as tl_utils
from telethon.tl.types import (MessageMediaPhoto, MessageMediaDocument, PeerChat, PeerChannel,
                               UpdateChannelParticipant, UpdateChatParticipantAdd, UpdateChatParticipantDelete,
                               ChannelParticipantBanned, ChannelParticipantLeft)
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
REPORT_HIDE_AT     = 3                         # distinct reports that hide a post / profile until a moderator decides
LIKE_NOTICE_COOLDOWN = 6 * 3600                # at most one "someone liked you" teaser per 6 hours

def _id_set(name: str) -> set:
    out = set()
    for p in os.environ.get(name, "").replace(" ", "").split(","):
        if p.lstrip("-").isdigit():
            out.add(int(p))
    return out

POST_COOLDOWN        = _int_env("POST_COOLDOWN", 20)         # seconds a member must wait between two posts (moderators exempt)
PASS_RECYCLE_DAYS    = _int_env("PASS_RECYCLE_DAYS", 3)      # a "Pass" comes back into the match deck after this many days
LIVE_MIN_GAP         = _int_env("LIVE_MIN_GAP", 300)         # a member gets at most one pushed (Live Feed) post per this many seconds
REENGAGE_AFTER_DAYS  = _int_env("REENGAGE_AFTER_DAYS", 2)    # idle this long + somebody liked them -> one gentle nudge
LIVE_FEED_DEFAULT    = os.environ.get("LIVE_FEED_DEFAULT", "1").strip().lower() not in ("0", "false", "no", "off")
AUTO_POST_GROUP_IDS  = _id_set("AUTO_POST_GROUP_IDS")        # optional: groups / channels to register at start-up (bot must be inside)
BOT_ID               = 0                                     # filled in main()

MODS = ({OWNER_ID} | _id_set("MODERATOR_IDS")) - {0}      # may use the moderation buttons and /ban /unban /reports /stats

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
    "block": "🚫", "filter": "⚙️", "loc": "📍", "ban": "⛔", "ok": "✅", "back": "↩️",
}
EMOJI_FALLBACK.update({"bell": "🔔", "pause": "⏸", "play": "▶️", "chat": "💬", "group": "👥", "refresh": "🔄"})
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
_sent_ids: contextvars.ContextVar = contextvars.ContextVar("sent_ids", default=None)   # lets broadcast remember message ids
_USER_BTN_ERR = ("button_user_privacy_restricted", "button_user_invalid")

def _mids(res: dict) -> list:
    r = res.get("result")
    if isinstance(r, list):
        return [m["message_id"] for m in r if isinstance(m, dict) and "message_id" in m]
    if isinstance(r, dict) and "message_id" in r:
        return [r["message_id"]]
    return []

def _has_user_btn(kb: list) -> bool:
    return any((b.get("url") or "").startswith("tg://user") for row in kb for b in row)

def _drop_user_buttons(kb: list) -> list:
    rows = [[b for b in row if not (b.get("url") or "").startswith("tg://user")] for row in kb]
    return [r for r in rows if r]

def _note_dead_chat(chat_id, res: dict):
    """A private chat that answers 'blocked / deactivated' is unreachable until the member comes back."""
    desc = (res.get("description") or "").lower()
    if (not res.get("ok") and isinstance(chat_id, int) and chat_id > 0
            and any(k in desc for k in ("bot was blocked", "user is deactivated", "chat not found"))):
        spawn(_mark_unreachable(chat_id))

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
            ids = _sent_ids.get()
            if ids is not None:
                ids.extend(_mids(res))
            return res
        desc = (res.get("description") or "").lower()
        if kb and any(e in desc for e in _USER_BTN_ERR) and _has_user_btn(kb):
            # the other person's privacy forbids tg://user buttons -> send the same message without them
            again = dict(payload)
            if text_key and text is not None:
                again[text_key] = text
            return await tg(method, kb=_drop_user_buttons(kb), _files=_files, text_key=text_key, **again)
        if any(f in desc for f in _FATAL):
            break
        if icons and has_icons:
            icon_attempt_failed = True
    _note_dead_chat(payload.get("chat_id"), res)
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
reports_col = db["reports"]
blocks_col = db["blocks"]
bans_col = db["bans"]
members_col = db["members"]      # everybody who ever opened the bot (fresh name / @username / live-feed switch)
groups_col = db["groups"]        # groups & channels that receive auto-posts

banned: set = set()          # filled from the "bans" collection at start-up (see load_bans)

bot = TelegramClient("social_match_session", API_ID, API_HASH)

def now_utc() -> datetime:
    return datetime.now(timezone.utc)

def new_id() -> str:
    return uuid.uuid4().hex[:8]

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)

def _aware(dt):
    """Mongo returns naive datetimes - treat them as UTC."""
    if not dt:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

_bg_tasks: set = set()

def spawn(coro):
    """Fire-and-forget task that cannot be garbage-collected half way through."""
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t

_touch_at: dict = {}
_revived: set = set()          # members who just came back (were unreachable / away for days) -> /start greets them
TOUCH_EVERY = 120

def _full_name(u) -> str:
    return f"{getattr(u, 'first_name', '') or ''} {getattr(u, 'last_name', '') or ''}".strip()[:60]

async def _mark_unreachable(uid: int):
    """The member blocked the bot / deleted the account: hide the profile until they come back."""
    _touch_at.pop(uid, None)
    try:
        await members_col.update_one({"user_id": uid}, {"$set": {"unreachable": True},
                                     "$setOnInsert": {"joined_at": now_utc(), "live": False}}, upsert=True)
        await users_col.update_many({"user_id": uid}, {"$set": {"unreachable": True}})
    except Exception as e:
        print(f"⚠️ mark_unreachable: {e}")

async def record_user(uid: int, sender):
    """Keep the member's CURRENT Telegram name / @username fresh - they feed every clickable mention."""
    now = now_utc()
    fields = {"first_name": (getattr(sender, "first_name", "") or "")[:64],
              "last_name": (getattr(sender, "last_name", "") or "")[:64],
              "tg_name": _full_name(sender) or "User", "username": getattr(sender, "username", None),
              "last_seen": now, "unreachable": False}
    before = await members_col.find_one_and_update(
        {"user_id": uid}, {"$set": fields, "$setOnInsert": {"joined_at": now, "live": LIVE_FEED_DEFAULT}}, upsert=True)
    if before:
        away = _aware(before.get("last_seen"))
        if before.get("unreachable") or (away and now - away > timedelta(days=REENGAGE_AFTER_DAYS + 1)):
            _revived.add(uid)
    await users_col.update_one({"user_id": uid}, {"$set": {k: fields[k] for k in ("tg_name", "username", "last_seen", "unreachable")}})

async def touch_user(event):
    """Called before every handler (throttled) - never raises."""
    try:
        uid = getattr(event, "sender_id", None)
        if not getattr(event, "is_private", False):
            cid = getattr(event, "chat_id", None)            # a command / reaction seen in a group = the bot lives there
            if (cid and cid < 0 and cid != STORAGE_GROUP_ID and cid not in _seen_groups
                    and (hasattr(event, "raw_text") or hasattr(event, "data"))):
                await register_group(cid, await _chat_title(event))
            return
        if not uid:
            return
        t = time.monotonic()
        if t - _touch_at.get(uid, -1e9) < TOUCH_EVERY:
            return
        _touch_at[uid] = t
        sender = await event.get_sender()
        if sender is None or getattr(sender, "bot", False):
            return
        await record_user(uid, sender)
    except Exception as e:
        print(f"⚠️ touch_user: {e}")

async def _identity(uid: int) -> dict:
    """Best known {tg_name, username} of a member: live from Telegram, else what we stored."""
    m = await members_col.find_one({"user_id": uid}) or {}
    ident = {"tg_name": m.get("tg_name"), "username": m.get("username")}
    try:
        ent = await bot.get_entity(uid)
        ident = {"tg_name": _full_name(ent) or ident["tg_name"], "username": getattr(ent, "username", None)}
    except Exception:
        pass
    return ident

async def ensure_indexes():
    for coro in (
        users_col.create_index("user_id", unique=True),
        posts_col.create_index("post_id", unique=True),
        posts_col.create_index([("created_at", -1)]),
        swipes_col.create_index([("from_id", 1), ("to_id", 1)], unique=True),
        states_col.create_index("user_id", unique=True),
        reports_col.create_index([("post_id", 1), ("reporter", 1)], unique=True),
        blocks_col.create_index([("blocker", 1), ("blocked", 1)], unique=True),
        blocks_col.create_index("blocked"),
        bans_col.create_index("user_id", unique=True),
        members_col.create_index("user_id", unique=True),
        members_col.create_index([("live", 1), ("last_live_at", 1)]),
        groups_col.create_index("chat_id", unique=True),
        users_col.create_index([("active", 1), ("gender", 1)]),
        swipes_col.create_index([("to_id", 1), ("action", 1)]),
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

def deep_link(arg: str) -> str:
    return f"https://t.me/{BOT_USERNAME}?start={arg}"

def share_url(post_id: str) -> str:
    return (f"https://t.me/share/url?url={quote(post_link(post_id), safe='')}"
            f"&text={quote('ဒီ Post လေးကြည့်ကြည့်ပါ 👀')}")

def person(uid, name: str | None = None, username: str | None = None, bold: bool = True) -> str:
    """Clickable name that opens the member's profile - works WITHOUT a @username (tg://user?id=...).
       The @username is appended when there is one."""
    label = esc(((name or "").strip() or "User")[:60])
    if bold:
        label = f"<b>{label}</b>"
    out = f'<a href="tg://user?id={int(uid)}">{label}</a>' if uid else label
    if username:
        out += f" (@{esc(username)})"
    return out

def has_real_media(msg) -> bool:
    """Photo / video / voice / audio / file / sticker — but NOT a link preview."""
    return isinstance(getattr(msg, "media", None), (MessageMediaPhoto, MessageMediaDocument))

def safe(name: str):
    """Log errors instead of dying silently, and stop the 'loading' spinner on buttons."""
    def deco(fn):
        async def wrapper(event):
            uid = getattr(event, "sender_id", None)
            if uid in banned and uid not in MODS:                 # banned members are ignored everywhere
                if getattr(event, "data", None) is not None:
                    try:
                        await event.answer("🚫 သင့်အကောင့်ကို ပိတ်ထားပါတယ်။", alert=True)
                    except Exception:
                        pass
                return
            await touch_user(event)
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
    if ctx == "n":                                   # pushed to my DM by Live Feed
        return [[B("Feed ကြည့်မည်", "menu:feed", icon="feed"), B("Live ပိတ်မည်", "live:off", icon="bell")]]
    return []                                        # "g" = group / channel copy: nothing extra

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
        [B(f"Share ({shares})", f"share:{pid}{sfx}", icon="share"), B("Report", f"rp:s:{pid}", icon="report")],
    ]
    if ctx == "g":      # in groups / channels Comment, Share and Report continue in the bot's private chat (URL buttons)
        n_cm = len(post.get("comments") or [])
        rows[2] = [B(f"Comments ({n_cm})", url=deep_link(f"cv_{pid}"), icon="comment"),
                   B("Comment ရေးမည်", url=deep_link(f"cw_{pid}"), icon="post")]
        rows[3] = [B(f"Share ({shares})", url=share_url(pid), icon="share"), B("Report", url=deep_link(f"rp_{pid}"), icon="report")]
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

async def menu_rows(uid) -> list:
    n = len(await liker_profiles(uid)) if uid else 0
    live_on = ((await members_col.find_one({"user_id": uid}) or {}).get("live", LIVE_FEED_DEFAULT)) if uid else LIVE_FEED_DEFAULT
    likers = (B(f"ကိုယ့်ကို Like လုပ်သူများ ({n})", "menu:likers", icon="love", style="success") if n
              else B("ကိုယ့်ကို Like လုပ်သူများ", "menu:likers", icon="love"))
    return [
        [B("Post တင်မည်", "menu:post", icon="post"), B("Poll တင်မည်", "menu:poll", icon="poll")],
        [B("Feed ကြည့်မည်", "menu:feed", icon="feed"), B("Top Posts", "menu:top", icon="top")],
        [B("သူငယ်ချင်း / ရည်းစား ရှာမည်", "menu:match", icon="match", style="primary")],
        [likers, B("Match Filter", "menu:filter", icon="filter")],
        [B("ကျွန်ုပ်၏ Profile", "menu:myprofile", icon="user"), B("Block စာရင်း", "menu:blocked", icon="block")],
        [B(f"Live Feed: {'ON' if live_on else 'OFF'}", "live:toggle", icon="bell")],
        [B("Group ထဲ ထည့်မည်", url=f"https://t.me/{BOT_USERNAME}?startgroup=true", icon="group"),
         B("Channel ထဲ ထည့်မည်", url=f"https://t.me/{BOT_USERNAME}?startchannel=true&admin=post_messages", icon="group")],
    ]

async def send_menu(chat_id):
    await send_text(chat_id, (f"{pe('fire')} <b>BOD Social &amp; Match မှ ကြိုဆိုပါတယ်!</b>\n\n"
                              f"ဒီနေ့ ဘာလုပ်ချင်ပါသလဲ?"), await menu_rows(chat_id))

# ============================================================
# 📰 SHOWING POSTS
# ============================================================
def post_header(post: dict) -> str:
    return f"{pe('user')} {person(post.get('author_id'), post.get('author_name'), post.get('author_username'))}"

def post_caption(post: dict) -> str:
    t = esc(post.get("text") or "")
    return f"{post_header(post)}\n\n{t}" if t else post_header(post)

async def show_post(chat_id, post: dict, ctx: str = "", prefix: str = "") -> dict:
    pid = post["post_id"]
    if post.get("hidden") and chat_id not in MODS:                     # reported / banned author: only moderators may look
        return await send_text(chat_id, f"{pe('info')} ဒီ Post ကို Admin စစ်ဆေးနေလို့ ခေတ္တပိတ်ထားပါတယ်။")
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
    uid = event.sender_id
    await clear_state(uid)
    arg = event.pattern_match.group(1)
    if not arg:
        await welcome_back(event.chat_id, uid)
    kind, _, pid = (arg or "").partition("_")          # post_<id> | cv_<id> comments | cw_<id> write comment | rp_<id> report
    if kind in ("post", "cv", "cw", "rp") and pid:
        post = await posts_col.find_one({"post_id": pid})
        if post:
            await open_post_link(event, kind, post)
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
    if event.sender_id != post["author_id"] and event.sender_id not in MODS:
        await send_text(event.chat_id, f"{pe('info')} ကိုယ့် Post ကိုပဲ ဖျက်လို့ရပါတယ်။")
        return
    await remove_post(post)
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
    elif action == "likers":
        await show_likers(chat, uid)
    elif action == "filter":
        await show_filter(chat, uid)
    elif action == "blocked":
        await show_blocked(chat, uid)
    elif action == "myprofile":
        user = await users_col.find_one({"user_id": uid})
        if not user:
            await send_text(chat, f"{pe('info')} Match Profile မရှိသေးပါ။", [[B("Profile ဖန်တီးမည်", "menu:match", icon="match")]])
            return
        await _show_my_profile(chat, user, [[B("ပြင်မည်", "mp:edit", icon="edit"), B("ဖျက်မည်", "mp:del", icon="trash", style="danger")],
                                     [B("နေရာပြင်မည်", "mp:loc", icon="loc"), B("Filter", "menu:filter", icon="filter")],
                                     [B("Menu", "menu:home", icon="fire")]])

# ============================================================
# 📰 FEED  ·  🏆 TOP
# ============================================================
async def _feed_query(uid) -> dict:
    """Visible posts only: not hidden by reports / bans, and not written by someone I blocked."""
    q: dict = {"hidden": {"$ne": True}}
    blocked = await blocked_ids(uid) if uid else set()
    if blocked:
        q["author_id"] = {"$nin": list(blocked)}
    return q

async def show_feed(chat_id, n: int):
    docs = await posts_col.find(await _feed_query(chat_id)).sort("created_at", -1).skip(n).limit(1).to_list(1)
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
    docs = await posts_col.find({**await _feed_query(chat_id), "is_poll": {"$ne": True}}).sort("created_at", -1).limit(300).to_list(300)
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
def _post_doc(uid: int, sender, text: str, **extra) -> dict:
    return {"post_id": new_id(), "author_id": uid, "author_name": display_name(sender),
            "author_username": getattr(sender, "username", None), "text": text, "created_at": now_utc(),
            "reactions": {}, "comments": [], "shared_by": [], "views": 0, **extra}

async def publish(chat_id, post: dict):
    await posts_col.insert_one(post)
    await clear_state(post["author_id"])
    await send_text(chat_id, (f"{pe('check')} Post တင်ပြီးပါပြီ!\n"
                              f"<i>ဖျက်ချင်ရင် <code>/delpost {post['post_id']}</code></i>\n"
                              f"{pe('info')} <i>Group တွေနဲ့ Live Feed ဖွင့်ထားသူတွေဆီ အလိုအလျောက် ပို့ပေးနေပါပြီ။</i>"))
    await show_post(chat_id, post)
    enqueue_broadcast(post, exclude=chat_id)

async def save_single_post(event, text: str):
    msg, uid, chat = event.message, event.sender_id, event.chat_id
    if not await post_cooldown_ok(chat, uid):
        return
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
    await publish(chat, _post_doc(uid, sender, text, **extra))

@bot.on(events.Album(func=_private))
@safe("album")
async def album_handler(event):
    uid, chat = event.sender_id, event.chat_id
    state = await get_state(uid)
    if not state or state.get("step") != "post_content":
        return
    if not await post_cooldown_ok(chat, uid):
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
    await publish(chat, _post_doc(uid, sender, text, album=album, album_msg_ids=ids))
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
        body = "\n\n".join(f"{person(c.get('uid'), c.get('name'), c.get('username'))}\n{esc((c.get('text') or '')[:300])}" for c in chunk)
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
    uname = getattr(sender, "username", None)
    await posts_col.update_one({"post_id": pid}, {"$push": {"comments": {
        "$each": [{"uid": uid, "name": name, "username": uname, "text": text[:MAX_COMMENT], "at": now_utc()}], "$slice": -MAX_COMMENTS_KEPT}}})
    await send_text(chat, f"{pe('check')} Comment ရေးပြီးပါပြီ။", [[B("Comments ကြည့်မည်", f"cm:view:{pid}", icon="comment")]])
    if post["author_id"] != uid and uid not in await blocked_ids(post["author_id"]):
        await send_text(post["author_id"], (f"{pe('comment')} <b>Comment အသစ်!</b>\n\n"
                                            f"{person(uid, name, uname)}: {esc(text[:300])}"),
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
    if not await post_cooldown_ok(event.chat_id, event.sender_id):
        return
    sender = await event.get_sender()
    await publish(event.chat_id, _post_doc(event.sender_id, sender, state["question"],
                                           is_poll=True, poll_options=opts[:MAX_POLL_OPTIONS]))

# ============================================================
# 🛡️ SAFETY  (post reports · moderators · blocks · bans)
# ============================================================
async def notify_mods(text: str, kb: list | None = None):
    for m in MODS:
        await send_text(m, text, kb)

async def remove_post(post: dict):
    """Delete a post, its reports and every media message it keeps in the storage group."""
    pid = post["post_id"]
    spawn(purge_group_copies(post))
    await posts_col.delete_one({"post_id": pid})
    await reports_col.delete_many({"post_id": pid})
    stored = ([post["storage_msg_id"]] if post.get("storage_msg_id") else []) \
        + list(post.get("storage_msg_ids") or []) + list(post.get("album_msg_ids") or [])
    for mid in stored:
        await tg("deleteMessage", chat_id=STORAGE_GROUP_ID, message_id=mid)

# ---------- bans ----------
async def ban_user(uid: int, by: int = 0, reason: str = ""):
    banned.add(uid)
    await bans_col.update_one({"user_id": uid}, {"$set": {"by": by, "reason": reason[:200], "at": now_utc()}}, upsert=True)
    await users_col.update_one({"user_id": uid}, {"$set": {"active": False}})
    await posts_col.update_many({"author_id": uid}, {"$set": {"hidden": True, "hidden_reason": "ban"}})
    spawn(purge_author_group_copies(uid))

async def unban_user(uid: int):
    banned.discard(uid)
    await bans_col.delete_one({"user_id": uid})
    await users_col.update_one({"user_id": uid}, {"$set": {"active": True}})
    await posts_col.update_many({"author_id": uid, "hidden_reason": "ban"}, {"$set": {"hidden": False, "hidden_reason": None}})

async def load_bans():
    banned.clear()
    try:
        banned.update(d["user_id"] for d in await bans_col.find({}).to_list(100000))
    except Exception as e:
        print(f"⚠️ load_bans: {e}")

# ---------- blocks ----------
async def blocked_ids(uid: int) -> set:
    return {b["blocked"] for b in await blocks_col.find({"blocker": uid}).to_list(2000)}

async def blocked_by_ids(uid: int) -> set:
    return {b["blocker"] for b in await blocks_col.find({"blocked": uid}).to_list(2000)}

async def block_user(uid: int, target: int, name: str | None = None):
    if uid == target:
        return
    prof = await users_col.find_one({"user_id": target})
    name = (name or (prof or {}).get("name") or "User")[:40]
    await blocks_col.update_one({"blocker": uid, "blocked": target}, {"$set": {"name": name, "at": now_utc()}}, upsert=True)
    await swipes_col.update_one({"from_id": uid, "to_id": target}, {"$set": {"action": "pass", "at": now_utc()}}, upsert=True)

async def show_blocked(chat_id, uid: int, edit_msg: int | None = None):
    rows = await blocks_col.find({"blocker": uid}).sort("at", -1).limit(20).to_list(20)
    if not rows:
        text, kb = f"{pe('block')} <b>Block စာရင်း</b>\n\nBlock လုပ်ထားသူ မရှိပါဘူး။", [[B("Menu", "menu:home", icon="fire")]]
    else:
        text = (f"{pe('block')} <b>Block စာရင်း</b> ({len(rows)})\n\n"
                f"<i>Block လုပ်ထားသူတွေကို Match Profile၊ Likes နဲ့ Feed မှာ မမြင်ရပါဘူး။ ပြန်ဖွင့်ချင်ရင် နှိပ်ပါ။</i>")
        kb = [[B(f"Unblock · {r.get('name') or r['blocked']}", f"bl:u:{r['blocked']}", icon="ok")] for r in rows] \
            + [[B("Menu", "menu:home", icon="fire")]]
    if edit_msg:
        await tg("editMessageText", kb=kb, text_key="text", chat_id=chat_id, message_id=edit_msg, text=text)
    else:
        await send_text(chat_id, text, kb)

@bot.on(events.NewMessage(pattern=r"^/blocked\s*$", incoming=True, func=_private))
@safe("blocked_cmd")
async def blocked_cmd(event):
    await show_blocked(event.chat_id, event.sender_id)

@bot.on(events.CallbackQuery(pattern=rb"^bl:"))
@safe("block_cb")
async def block_cb(event):
    parts = event.data.decode().split(":")
    uid, chat, mid = event.sender_id, event.chat_id, event.query.msg_id
    if parts[1] == "u":                                             # unblock from the list
        await blocks_col.delete_one({"blocker": uid, "blocked": int(parts[2])})
        await event.answer("Unblock လုပ်ပြီးပါပြီ")
        await show_blocked(chat, uid, edit_msg=mid)
        return
    target, ctx = int(parts[1]), (parts[2] if len(parts) > 2 else "c")
    await block_user(uid, target)
    await event.answer("🚫 Block လုပ်ပြီးပါပြီ")
    if ctx == "n":                                                  # from a "match" notification
        await tg("editMessageText", kb=[], text_key="text", chat_id=chat, message_id=mid,
                 text=f"{pe('block')} Block လုပ်ပြီးပါပြီ။ ဒီသူနဲ့ ထပ်မတွေ့တော့ပါဘူး။")
        return
    await tg("deleteMessage", chat_id=chat, message_id=mid)
    await (show_likers(chat, uid) if ctx == "l" else find_match(chat, uid))

# ---------- reporting a post ----------
REPORT_REASONS = {"spam": "Spam / ကြော်ငြာ", "nsfw": "မသင့်လျော်တဲ့ အကြောင်းအရာ (18+)",
                  "abuse": "ဆဲဆို / နှောင့်ယှက်", "fake": "လိမ်လည် / အတု", "other": "အခြား"}

async def _report_summary(post: dict) -> str:
    reps = await reports_col.find({"post_id": post["post_id"]}).to_list(200)
    tally: dict[str, int] = {}
    for r in reps:
        tally[r.get("reason", "other")] = tally.get(r.get("reason", "other"), 0) + 1
    why = " · ".join(f"{k}×{v}" for k, v in tally.items()) or "-"
    status = "  <b>(ဝှက်ထားပြီး)</b>" if post.get("hidden") else ""
    return (f"🚩 <b>Post Report</b> ({post.get('report_count', len(reps))}){status}\n\n"
            f"Post: <code>{post['post_id']}</code> · Author: {person(post.get('author_id'), post.get('author_name'), post.get('author_username'))} (<code>{post['author_id']}</code>)\n"
            f"Reasons: {esc(why)}\n\n{esc((post.get('text') or '')[:300]) or '<i>(media / poll)</i>'}")

def _mod_post_kb(post: dict) -> list:
    pid = post["post_id"]
    return [[B("Post ကြည့်မည်", url=post_link(pid), icon="info")],
            [B("ဖျက်မည်", f"mod:del:{pid}", icon="trash", style="danger"),
             B("ပြဿနာမရှိ", f"mod:ok:{pid}", icon="ok", style="success")],
            [B("Author ကို Ban", f"mod:ban:{post['author_id']}", icon="ban", style="danger")]]

@bot.on(events.CallbackQuery(pattern=rb"^rp:"))
@safe("report")
async def report_cb(event):
    parts = event.data.decode().split(":")
    action, uid, chat, mid = parts[1], event.sender_id, event.chat_id, event.query.msg_id
    if action == "x":
        await event.answer()
        await tg("deleteMessage", chat_id=chat, message_id=mid)
        return
    pid = parts[2] if len(parts) > 2 else ""
    post = await posts_col.find_one({"post_id": pid})
    if not post:
        await event.answer("Post မတွေ့တော့ပါ။", alert=True)
        return

    if action == "b":                                               # block the author from the report message
        await block_user(uid, post["author_id"], post.get("author_name"))
        await event.answer("🚫 Block လုပ်ပြီးပါပြီ")
        await tg("editMessageText", kb=[], text_key="text", chat_id=chat, message_id=mid,
                 text=f"{pe('block')} {esc(post.get('author_name') or 'User')} ကို Block လုပ်ပြီးပါပြီ။")
        return

    if post["author_id"] == uid:
        await event.answer("ကိုယ့် Post ကို Report မလုပ်နိုင်ပါ။", alert=True)
        return
    if await reports_col.find_one({"post_id": pid, "reporter": uid}):
        await event.answer("ဒီ Post ကို Report လုပ်ပြီးသားပါ။", alert=True)
        return

    if action == "s":                                               # step 1: pick a reason
        await event.answer()
        rows = [[B(label, f"rp:r:{pid}:{code}")] for code, label in REPORT_REASONS.items()] + [[B("မလုပ်တော့ပါ", "rp:x", icon="cancel")]]
        await send_text(chat, f"{pe('report')} <b>ဘာကြောင့် Report လုပ်မလဲ?</b>", rows,
                        reply_parameters={"message_id": mid, "allow_sending_without_reply": True})
        return

    if action == "r":                                               # step 2: file it
        code = parts[3] if len(parts) > 3 and parts[3] in REPORT_REASONS else "other"
        try:
            await reports_col.insert_one({"post_id": pid, "reporter": uid, "reason": code, "at": now_utc()})
        except Exception:                                           # lost a race with a double tap
            await event.answer("ဒီ Post ကို Report လုပ်ပြီးသားပါ။", alert=True)
            return
        await posts_col.update_one({"post_id": pid}, {"$inc": {"report_count": 1}})
        post = await posts_col.find_one({"post_id": pid})
        n = post.get("report_count", 1)
        hide = n >= REPORT_HIDE_AT and not post.get("report_ok") and not post.get("hidden")
        if hide:
            await posts_col.update_one({"post_id": pid}, {"$set": {"hidden": True, "hidden_reason": "reports"}})
            post["hidden"] = True
            spawn(purge_group_copies(post))
            await send_text(post["author_id"], (f"{pe('info')} သင့် Post (<code>{pid}</code>) ကို Report အများကြီးရလို့ "
                                                f"Admin စစ်ဆေးတဲ့အထိ ခေတ္တပိတ်ထားပါတယ်။"))
        if n == 1 or hide:                                          # first report + the moment it gets hidden
            await notify_mods(await _report_summary(post), _mod_post_kb(post))
        await event.answer("Report လုပ်ပြီးပါပြီ။ ကျေးဇူးတင်ပါတယ်။")
        await tg("editMessageText", kb=[[B("Author ကို Block လုပ်မည်", f"rp:b:{pid}", icon="block"), B("ပိတ်မည်", "rp:x", icon="cancel")]],
                 text_key="text", chat_id=chat, message_id=mid,
                 text=f"{pe('check')} <b>Report လုပ်ပြီးပါပြီ</b>\n<i>{esc(REPORT_REASONS[code])}</i>\n\nAdmin တွေ စစ်ဆေးပေးပါလိမ့်မယ်။")

# ---------- moderator actions ----------
@bot.on(events.CallbackQuery(pattern=rb"^mod:"))
@safe("mod")
async def mod_cb(event):
    if event.sender_id not in MODS:
        await event.answer("Admin only", alert=True)
        return
    parts = event.data.decode().split(":")
    action, chat, mid = parts[1], event.chat_id, event.query.msg_id
    await event.answer()
    async def done(note: str):
        await tg("editMessageText", kb=[], text_key="text", chat_id=chat, message_id=mid, text=note)
    if action == "del":
        post = await posts_col.find_one({"post_id": parts[2]})
        if post:
            await remove_post(post)
            await send_text(post["author_id"], f"{pe('info')} သင့် Post (<code>{post['post_id']}</code>) ကို Admin က ဖျက်လိုက်ပါတယ်။")
        await done(f"🗑 Post <code>{esc(parts[2])}</code> ကို ဖျက်ပြီးပါပြီ။")
    elif action == "ok":
        pid = parts[2]
        await posts_col.update_one({"post_id": pid}, {"$set": {"report_ok": True, "report_count": 0}})
        await posts_col.update_one({"post_id": pid, "hidden_reason": "reports"}, {"$set": {"hidden": False, "hidden_reason": None}})
        await reports_col.delete_many({"post_id": pid})
        await done(f"✅ Post <code>{esc(pid)}</code> — ပြဿနာမရှိပါ။ (နောက်ထပ် Report တွေနဲ့ အလိုအလျောက် မဝှက်တော့ပါ)")
    elif action == "ban":
        target = int(parts[2])
        if target in MODS:
            await done("Admin ကို Ban မလုပ်နိုင်ပါ။")
            return
        await ban_user(target, by=event.sender_id, reason="moderator")
        await send_text(target, f"{pe('block')} သင့်အကောင့်ကို စည်းကမ်းဖောက်ဖျက်မှုကြောင့် ပိတ်လိုက်ပါတယ်။")
        await done(f"⛔ <code>{target}</code> ကို Ban လုပ်ပြီးပါပြီ။")
    elif action == "unban":
        await unban_user(int(parts[2]))
        await done(f"✅ <code>{esc(parts[2])}</code> ကို Unban လုပ်ပြီးပါပြီ။")
    elif action == "rest":                                          # restore a profile that was auto-deactivated by reports
        target = int(parts[2])
        await users_col.update_one({"user_id": target}, {"$set": {"active": True, "report_ok": True}})
        await reports_col.delete_many({"post_id": f"u{target}"})
        await done(f"✅ Profile <code>{target}</code> ကို ပြန်ဖွင့်ပေးပြီးပါပြီ။")
    else:
        await done("ပယ်ချပြီးပါပြီ။")

def _mod(e) -> bool:
    return _private(e) and e.sender_id in MODS

@bot.on(events.NewMessage(pattern=r"^/ban\s+(\d+)(?:\s+(.+))?\s*$", incoming=True, func=_mod))
@safe("ban_cmd")
async def ban_cmd(event):
    target, reason = int(event.pattern_match.group(1)), event.pattern_match.group(2) or ""
    if target in MODS:
        await send_text(event.chat_id, "Admin ကို Ban မလုပ်နိုင်ပါ။")
        return
    await ban_user(target, by=event.sender_id, reason=reason)
    await send_text(event.chat_id, f"⛔ <code>{target}</code> ကို Ban လုပ်ပြီးပါပြီ။", [[B("Unban", f"mod:unban:{target}", icon="ok")]])

@bot.on(events.NewMessage(pattern=r"^/unban\s+(\d+)\s*$", incoming=True, func=_mod))
@safe("unban_cmd")
async def unban_cmd(event):
    target = int(event.pattern_match.group(1))
    await unban_user(target)
    await send_text(event.chat_id, f"✅ <code>{target}</code> ကို Unban လုပ်ပြီးပါပြီ။")

@bot.on(events.NewMessage(pattern=r"^/reports\s*$", incoming=True, func=_mod))
@safe("reports_cmd")
async def reports_cmd(event):
    docs = await posts_col.find({"report_count": {"$gt": 0}, "report_ok": {"$ne": True}}).sort("report_count", -1).limit(5).to_list(5)
    if not docs:
        await send_text(event.chat_id, f"{pe('check')} စစ်ဆေးစရာ Report မရှိပါဘူး။")
        return
    for d in docs:
        await send_text(event.chat_id, await _report_summary(d), _mod_post_kb(d))

@bot.on(events.NewMessage(pattern=r"^/stats\s*$", incoming=True, func=_mod))
@safe("stats_cmd")
async def stats_cmd(event):
    c = users_col.count_documents
    users, active = await c({}), await c({"active": {"$ne": False}})
    posts, hidden = await posts_col.count_documents({"hidden": {"$ne": True}}), await posts_col.count_documents({"hidden": True})
    pending = await posts_col.count_documents({"report_count": {"$gt": 0}, "report_ok": {"$ne": True}})
    await send_text(event.chat_id, (f"{pe('stats')} <b>Bot Stats</b>\n\n"
                                    f"{pe('user')} Profiles: <b>{active}</b> active / {users} total\n"
                                    f"{pe('post')} Posts: <b>{posts}</b> visible · {hidden} hidden\n"
                                    f"🚩 Pending reports: <b>{pending}</b>\n"
                                    f"{pe('block')} Banned: <b>{len(banned)}</b>\n"
                                    f"👥 Members: <b>{await members_col.count_documents({})}</b> · "
                                    f"🔔 Live: <b>{await members_col.count_documents({'live': {'$ne': False}, 'unreachable': {'$ne': True}})}</b>\n"
                                    f"💬 Groups: <b>{await groups_col.count_documents({'enabled': {'$ne': False}})}</b>"))

# ============================================================
# ❤️ MATCHMAKING  (gender · location · "who liked me" · filters)
# ============================================================
GENDERS = {"male": ("👨", "ကျား"), "female": ("👩", "မ"), "other": ("🧑", "အခြား")}
LOOKING = {"male": "ကျား", "female": "မ", "any": "အားလုံး"}
REGIONS = {"ygn": "ရန်ကုန်", "mdy": "မန္တလေး", "npt": "နေပြည်တော်", "bgo": "ပဲခူး", "ayw": "ဧရာဝတီ", "mgw": "မကွေး",
           "sgg": "စစ်ကိုင်း", "tnt": "တနင်္သာရီ", "kch": "ကချင်", "kyh": "ကယား", "kyn": "ကရင်", "chn": "ချင်း",
           "mon": "မွန်", "rkh": "ရခိုင်", "shn": "ရှမ်း", "abr": "ပြည်ပ"}
AGE_PRESETS = {"any": "အသက်မရွေး", "18-25": "18–25", "26-35": "26–35", "36-45": "36–45", "46-99": "46+"}

def norm_city(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())

def region_rows(prefix: str) -> list:
    keys = list(REGIONS)
    return [[B(REGIONS[k], f"{prefix}:{k}") for k in keys[i:i + 3]] for i in range(0, len(keys), 3)]

async def start_profile(chat_id, uid: int, upgrade: bool = False):
    await clear_state(uid)
    await set_state(uid, step="match_name")
    intro = "Profile အသစ်ပြန်ဖန်တီးပါမယ်။\n\n" if upgrade else ""
    await send_text(chat_id, (f"{pe('user')} {intro}သင့်နာမည် (သို့) အမည်ပြောင် ကို ရိုက်ထည့်ပါ -\n"
                              f"<i>ပယ်ဖျက်ချင်ရင် /cancel</i>"))

def card_text(p: dict) -> str:
    g = GENDERS.get(p.get("gender"), ("🧑", ""))
    loc = " · ".join(x for x in (REGIONS.get(p.get("region")), p.get("city")) if x)
    loc_line = f"{pe('loc')} {esc(loc)}\n" if loc else ""
    return (f"{pe('match')} <b>{esc(p.get('name') or 'User')}</b>, {p.get('age', '?')}\n"
            f"{g[0]} {g[1]}  ·  ရှာနေတာ: <b>{LOOKING.get(p.get('looking_for'), 'အားလုံး')}</b>\n"
            f"{loc_line}\n"
            f"{pe('post')} {esc(p.get('bio') or '')}")

async def show_card(chat_id, p: dict, kb: list, prefix: str = ""):
    text = prefix + card_text(p)
    if p.get("photo_msg_id"):
        res = await tg("copyMessage", kb=kb, text_key="caption", chat_id=chat_id, from_chat_id=STORAGE_GROUP_ID,
                       message_id=p["photo_msg_id"], caption=text)
        if res.get("ok"):
            return
    await send_text(chat_id, text, kb)

def swipe_kb(target_id: int, ctx: str = "c") -> list:
    """ctx 'c' = normal browsing, 'l' = the 'who liked me' list."""
    sfx = ":l" if ctx == "l" else ""
    rows = [[B("Like", f"match:like:{target_id}{sfx}", icon="love", style="success"),
             B("Pass", f"match:pass:{target_id}{sfx}", icon="dislike", style="danger")],
            [B("Report", f"match:report:{target_id}{sfx}", icon="report"), B("Block", f"bl:{target_id}:{ctx}", icon="block")]]
    rows.append([B("ရပ်မည်", "menu:home", icon="menu")] if ctx == "l" else
                [B("Filter", "menu:filter", icon="filter"), B("ရပ်မည်", "menu:home", icon="menu")])
    return rows

# ---------- finding someone ----------
def _age_range(code: str):
    try:
        lo, hi = code.split("-")
        return int(lo), int(hi)
    except ValueError:
        return None

async def find_match(chat_id, uid: int):
    me = await users_col.find_one({"user_id": uid})
    if not me or not me.get("gender"):
        await start_profile(chat_id, uid, upgrade=bool(me))
        return
    if me.get("paused"):                                                      # opening Match = "I'm back"
        await set_paused(uid, False)
        me["paused"] = False
    cutoff = now_utc() - timedelta(days=PASS_RECYCLE_DAYS)
    swiped = [s["to_id"] for s in await swipes_col.find({"from_id": uid}).to_list(10000)
              if s.get("action") != "pass" or (_aware(s.get("at")) or _EPOCH) >= cutoff]      # old passes return to the deck
    liked_me = {s["from_id"] for s in await swipes_col.find({"to_id": uid, "action": "like"}).to_list(2000)}
    gone = (await blocked_ids(uid)) | (await blocked_by_ids(uid)) | banned
    q = {"user_id": {"$ne": uid, "$nin": swiped + list(gone)}, "active": {"$ne": False},
         "paused": {"$ne": True}, "unreachable": {"$ne": True},
         "looking_for": {"$in": ["any", me["gender"]]}}                       # they must want someone like me
    if me.get("looking_for") in ("male", "female"):
        q["gender"] = me["looking_for"]                                       # and I must want someone like them
    where = me.get("pref_where") or "any"
    if where == "city" and me.get("city_norm"):
        q["city_norm"] = me["city_norm"]
    elif where == "region" and me.get("region"):
        q["region"] = me["region"]
    elif where.startswith("rg:") and where[3:] in REGIONS:
        q["region"] = where[3:]
    rng = _age_range(me.get("pref_age") or "any")
    if rng:
        q["age"] = {"$gte": rng[0], "$lte": rng[1]}
    cands = []
    if where == "region" and me.get("city_norm"):                             # "my region": people from my own town first
        cands = await _sample_users({**q, "city_norm": me["city_norm"]})
    if not cands:
        cands = await _sample_users(q)
    if not cands:
        narrowed = where != "any" or (me.get("pref_age") or "any") != "any"
        hint = "ဒီ Filter နဲ့ ရှာမတွေ့ပါဘူး။ Filter ကို ပြင်ကြည့်ပါ။" if narrowed else "အခုလောလောဆယ် ရှာမတွေ့တော့ပါဘူး။ နောက်မှ ပြန်ကြည့်ပါ။"
        await send_text(chat_id, f"{pe('info')} {hint}", await _recycle_rows(uid) + [[B("Filter ပြင်မည်", "menu:filter", icon="filter"), B("Menu", "menu:home", icon="fire")]])
        return
    target = _pick_best(cands, me, liked_me)
    await show_card(chat_id, target, swipe_kb(target["user_id"]))

# ---------- who liked me ----------
async def liker_profiles(uid: int, limit: int = 50) -> list:
    likes = await swipes_col.find({"to_id": uid, "action": "like"}).sort("at", -1).limit(200).to_list(200)
    ids = [s["from_id"] for s in likes]
    if not ids:
        return []
    mine = {s["to_id"] for s in await swipes_col.find({"from_id": uid}).to_list(5000)}
    gone = (await blocked_ids(uid)) | (await blocked_by_ids(uid)) | banned
    ids = [i for i in ids if i not in mine and i not in gone]
    if not ids:
        return []
    profs = {p["user_id"]: p for p in await users_col.find({"user_id": {"$in": ids}, "active": {"$ne": False}, "paused": {"$ne": True}, "unreachable": {"$ne": True}}).to_list(200)}
    return [profs[i] for i in ids if i in profs][:limit]

async def show_likers(chat_id, uid: int):
    ps = await liker_profiles(uid)
    if not ps:
        await send_text(chat_id, f"{pe('info')} Like လုပ်ထားသူ အသစ် မရှိသေးပါဘူး။",
                        [[B("Match ရှာမည်", "menu:match", icon="match"), B("Menu", "menu:home", icon="fire")]])
        return
    p = ps[0]
    await show_card(chat_id, p, swipe_kb(p["user_id"], "l"),
                    prefix=f"{pe('love')} <b>ကိုယ့်ကို Like လုပ်ထားသူ</b> · ကျန်တာ {len(ps)}\n\n")

async def notify_liked(target_id: int):
    """A teaser (no names) so people come back — at most once per LIKE_NOTICE_COOLDOWN."""
    t = await users_col.find_one({"user_id": target_id})
    if not t or t.get("active") is False or t.get("paused") or t.get("unreachable") or target_id in banned:
        return
    last = t.get("last_like_notice")
    if last:
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if (now_utc() - last).total_seconds() < LIKE_NOTICE_COOLDOWN:
            return
    await users_col.update_one({"user_id": target_id}, {"$set": {"last_like_notice": now_utc()}})
    await send_text(target_id, f"{pe('love')} <b>တစ်ယောက်ယောက်က ကိုယ့်ကို Like လုပ်ထားပါတယ်!</b>\nဘယ်သူလဲ ကြည့်ချင်ရင် နှိပ်ပါ။",
                    [[B("ကြည့်မယ်", "menu:likers", icon="love", style="primary")]])

# ---------- match ----------
async def _contact_card(user_id: int, prof: dict) -> tuple:
    """(html, chat_url) for the OTHER person of a match: full Telegram name as a clickable mention,
       @username when there is one, and the nickname they used in their match profile."""
    ident = await _identity(user_id)
    full = (ident.get("tg_name") or prof.get("tg_name") or prof.get("name") or "User").strip()
    uname = ident.get("username") or prof.get("username")
    nick = (prof.get("name") or "").strip()
    out = person(user_id, full, uname)
    if nick and nick.lower() != full.lower():
        out += f"\n{pe('match')} Profile နာမည်: <b>{esc(nick)}</b>"
    if not uname:
        out += "\n<i>Username မရှိပါဘူး - နာမည်ကို နှိပ်ရင် Profile ပွင့်ပါမယ်။</i>"
    return out, (f"https://t.me/{uname}" if uname else f"tg://user?id={user_id}")

async def notify_match(a: int, b: int):
    pa, pb = await users_col.find_one({"user_id": a}), await users_col.find_one({"user_id": b})
    for me, other, prof in ((a, b, pb or {}), (b, a, pa or {})):
        who, url = await _contact_card(other, prof)
        await send_text(me, (f"{pe('match')} <b>IT'S A MATCH!</b> {pe('match')}\n\n"
                             f"သင်တို့နှစ်ယောက် တစ်ယောက်ကိုတစ်ယောက် သဘောကျသွားပါပြီ!\n\n"
                             f"{pe('user')} {who}\n\n"
                             f"<i>အောက်က ခလုတ်ကိုနှိပ်ပြီး စကားစပြောလိုက်ပါ။</i>"),
                        [[B("စကားပြောမည်", url=url, icon="chat", style="primary")],
                         [B("Block", f"bl:{other}:n", icon="block")]])

async def _report_profile(reporter: int, target_id: int):
    """A profile report counts distinct reporters; REPORT_HIDE_AT of them deactivate the profile until a moderator decides."""
    rid = f"u{target_id}"
    try:
        await reports_col.insert_one({"post_id": rid, "reporter": reporter, "reason": "profile", "at": now_utc()})
    except Exception:
        return
    n = await reports_col.count_documents({"post_id": rid})
    who = await users_col.find_one({"user_id": target_id}) or {}
    hide = n >= REPORT_HIDE_AT and not who.get("report_ok") and who.get("active") is not False
    if hide:
        await users_col.update_one({"user_id": target_id}, {"$set": {"active": False}})
    if n == 1 or hide:
        kb = [[B("Ban", f"mod:ban:{target_id}", icon="ban", style="danger"), B("Profile ပြန်ဖွင့်", f"mod:rest:{target_id}", icon="ok", style="success")]]
        await notify_mods((f"🚩 <b>Profile Report</b> ({n})" + ("  <b>(ဝှက်ထားပြီး)</b>" if hide else "") +
                           f"\n\nUser: <code>{target_id}</code> · {person(target_id, who.get('tg_name') or who.get('name'), who.get('username'))} · “{esc(who.get('name') or '?')}”, {who.get('age', '?')}\n"
                           f"Bio: {esc(who.get('bio') or '')}"), kb)

@bot.on(events.CallbackQuery(pattern=rb"^match:"))
@safe("match")
async def match_cb(event):
    parts = event.data.decode().split(":")
    action, target_id, ctx = parts[1], int(parts[2]), (parts[3] if len(parts) > 3 else "c")
    uid, chat = event.sender_id, event.chat_id
    prev = await swipes_col.find_one_and_update({"from_id": uid, "to_id": target_id},
                                {"$set": {"action": {"like": "like", "report": "report"}.get(action, "pass"), "at": now_utc()}}, upsert=True)
    already_liked = action == "like" and bool(prev) and prev.get("action") == "like"      # double-tap guard (no double match)
    await tg("deleteMessage", chat_id=chat, message_id=event.query.msg_id)
    if action == "report":
        await _report_profile(uid, target_id)
        await event.answer("Report လုပ်ပြီးပါပြီ။ ကျေးဇူးတင်ပါတယ်။")
    elif action == "like":
        if already_liked:
            await event.answer("Like လုပ်ပြီးသားပါ")
        elif target_id in banned or target_id in await blocked_by_ids(uid):
            await event.answer("ဒီ Profile မရှိတော့ပါ။")
        elif await swipes_col.find_one({"from_id": target_id, "to_id": uid, "action": "like"}):
            await event.answer("🎉 Match ဖြစ်သွားပါပြီ!")
            await notify_match(uid, target_id)
        else:
            await event.answer("Like လုပ်လိုက်ပါပြီ")
            await notify_liked(target_id)
    else:
        await event.answer("Pass")
    await (show_likers(chat, uid) if ctx == "l" else find_match(chat, uid))

# ---------- filter screen ----------
def filter_screen(me: dict):
    where, age, look = me.get("pref_where") or "any", me.get("pref_age") or "any", me.get("looking_for") or "any"
    def m(sel: bool, text: str) -> str:
        return f"✅ {text}" if sel else text
    where_label = {"any": "နေရာမရွေး", "city": "ကိုယ့်မြို့", "region": "ကိုယ့်ဒေသ"}.get(where) or f"ဒေသ - {REGIONS.get(where[3:], '?')}"
    mine = " · ".join(x for x in (REGIONS.get(me.get("region")), me.get("city")) if x) or "မထည့်ရသေးပါ"
    text = (f"{pe('filter')} <b>Match Filter</b>\n\n"
            f"{pe('loc')} နေရာ: <b>{esc(where_label)}</b>\n"
            f"🎂 အသက်: <b>{AGE_PRESETS.get(age, esc(age))}</b>\n"
            f"{pe('user')} ရှာနေတာ: <b>{LOOKING.get(look, 'အားလုံး')}</b>\n\n"
            f"<i>ကိုယ့်နေရာ: {esc(mine)}</i>")
    ages = list(AGE_PRESETS.items())
    kb = [[B(m(where == "any", "နေရာမရွေး"), "fl:w:any"), B(m(where == "city", "ကိုယ့်မြို့"), "fl:w:city")],
          [B(m(where == "region", "ကိုယ့်ဒေသ"), "fl:w:region"), B(m(where.startswith("rg:"), "ဒေသရွေးမည်"), "fl:pick")],
          [B(m(age == k, lbl), f"fl:a:{k}") for k, lbl in ages[:3]],
          [B(m(age == k, lbl), f"fl:a:{k}") for k, lbl in ages[3:]],
          [B(m(look == k, LOOKING[k]), f"fl:g:{k}") for k in ("male", "female", "any")]]
    if not me.get("region"):
        kb.append([B("ကိုယ့်နေရာ ထည့်မည်", "mp:loc", icon="loc")])
    kb.append([B("Match ရှာမည်", "fl:done", icon="match", style="primary")])
    return text, kb

async def show_filter(chat_id, uid: int, edit_msg: int | None = None):
    me = await users_col.find_one({"user_id": uid})
    if not me or not me.get("gender"):
        await send_text(chat_id, f"{pe('info')} Filter သုံးဖို့ Match Profile အရင်ဖန်တီးပါ။",
                        [[B("Profile ဖန်တီးမည်", "menu:match", icon="match")]])
        return
    text, kb = filter_screen(me)
    if edit_msg:
        await tg("editMessageText", kb=kb, text_key="text", chat_id=chat_id, message_id=edit_msg, text=text)
    else:
        await send_text(chat_id, text, kb)

@bot.on(events.NewMessage(pattern=r"^/filter\s*$", incoming=True, func=_private))
@safe("filter_cmd")
async def filter_cmd(event):
    await show_filter(event.chat_id, event.sender_id)

@bot.on(events.CallbackQuery(pattern=rb"^fl:"))
@safe("filter")
async def filter_cb(event):
    parts = event.data.decode().split(":")
    action, uid, chat, mid = parts[1], event.sender_id, event.chat_id, event.query.msg_id
    me = await users_col.find_one({"user_id": uid})
    if not me:
        await event.answer("Profile အရင်ဖန်တီးပါ။", alert=True)
        return
    val = parts[2] if len(parts) > 2 else ""
    if action == "done":
        await event.answer()
        await tg("deleteMessage", chat_id=chat, message_id=mid)
        await find_match(chat, uid)
        return
    if action == "pick":
        await event.answer()
        await tg("editMessageText", kb=region_rows("fl:rg") + [[B("နောက်သို့", "fl:back", icon="back")]], text_key="text",
                 chat_id=chat, message_id=mid, text=f"{pe('loc')} <b>ရှာချင်တဲ့ ဒေသကို ရွေးပါ</b>")
        return
    if action == "w":
        if val == "city" and not me.get("city_norm"):
            await event.answer("မြို့ မထည့်ရသေးပါ။ 'ကိုယ့်နေရာ ထည့်မည်' ကိုနှိပ်ပါ။", alert=True)
            return
        if val == "region" and not me.get("region"):
            await event.answer("ဒေသ မထည့်ရသေးပါ။ 'ကိုယ့်နေရာ ထည့်မည်' ကိုနှိပ်ပါ။", alert=True)
            return
        if val in ("any", "city", "region"):
            await users_col.update_one({"user_id": uid}, {"$set": {"pref_where": val}})
    elif action == "rg" and val in REGIONS:
        await users_col.update_one({"user_id": uid}, {"$set": {"pref_where": f"rg:{val}"}})
    elif action == "a" and val in AGE_PRESETS:
        await users_col.update_one({"user_id": uid}, {"$set": {"pref_age": val}})
    elif action == "g" and val in LOOKING:
        await users_col.update_one({"user_id": uid}, {"$set": {"looking_for": val}})
    await event.answer()
    await show_filter(chat, uid, edit_msg=mid)

# ---------- profile creation / editing ----------
async def after_city(chat_id, uid: int, state: dict, city: str | None):
    city = (city or "").strip()[:40] or None
    fields = {"region": state.get("region"), "city": city, "city_norm": norm_city(city) if city else None}
    if state.get("loc_only"):
        await users_col.update_one({"user_id": uid}, {"$set": fields})
        await clear_state(uid)
        await send_text(chat_id, f"{pe('check')} နေရာ ပြင်ပြီးပါပြီ။")
        me = await users_col.find_one({"user_id": uid})
        if me:
            await show_card(chat_id, me, [[B("Filter", "menu:filter", icon="filter"), B("Menu", "menu:home", icon="fire")]])
        return
    await set_state(uid, step="match_bio", **fields)
    await send_text(chat_id, f"{pe('info')} သင့်အကြောင်း အတိုချုပ် (Bio) ရေးပါ -")

@bot.on(events.CallbackQuery(pattern=rb"^mp:"))
@safe("profile_cb")
async def profile_cb(event):
    parts = event.data.decode().split(":")
    action, uid, chat = parts[1], event.sender_id, event.chat_id
    state = await get_state(uid) or {}
    step = state.get("step")
    await event.answer()
    if action == "g" and step == "match_gender":
        await set_state(uid, step="match_look", gender=parts[2])
        await send_text(chat, f"{pe('match')} ဘယ်သူ့ကို ရှာချင်ပါသလဲ?",
                        [[B("ကျား", "mp:l:male"), B("မ", "mp:l:female"), B("အားလုံး", "mp:l:any")]])
    elif action == "l" and step == "match_look":
        await set_state(uid, step="match_region", looking_for=parts[2])
        await send_text(chat, f"{pe('loc')} <b>သင်နေတဲ့ ဒေသကို ရွေးပါ -</b>", region_rows("mp:rg"))
    elif action == "rg" and step == "match_region" and len(parts) > 2 and parts[2] in REGIONS:
        await set_state(uid, step="match_city", region=parts[2])
        await send_text(chat, (f"{pe('loc')} <b>{REGIONS[parts[2]]}</b> — မြို့ / မြို့နယ်ကို ရိုက်ထည့်ပါ\n"
                               f"<i>ဥပမာ - အင်းစိန်၊ ဗိုလ်ချုပ်၊ Singapore</i>"),
                        [[B("Skip", "mp:cityskip", icon="next")]])
    elif action == "cityskip" and step == "match_city":
        await after_city(chat, uid, state, None)
    elif action == "skip" and step == "match_photo":
        await finish_profile(chat, uid, state, None)
    elif action == "loc":
        if not await users_col.find_one({"user_id": uid}):
            await send_text(chat, f"{pe('info')} Match Profile အရင်ဖန်တီးပါ။", [[B("Profile ဖန်တီးမည်", "menu:match", icon="match")]])
            return
        await clear_state(uid)
        await set_state(uid, step="match_region", loc_only=True)
        await send_text(chat, f"{pe('loc')} <b>သင်နေတဲ့ ဒေသကို ရွေးပါ -</b>", region_rows("mp:rg"))
    elif action in ("pause", "resume"):
        await _pause_flow(chat, uid, action == "pause")
    elif action == "recycle":                                       # bring every "Pass" back into the deck
        await swipes_col.delete_many({"from_id": uid, "action": "pass"})
        await find_match(chat, uid)
    elif action == "edit":
        await start_profile(chat, uid, upgrade=True)
    elif action == "del":
        await users_col.delete_one({"user_id": uid})
        await send_text(chat, f"{pe('check')} Match Profile ကို ဖျက်လိုက်ပါပြီ။", [[B("Menu", "menu:home", icon="fire")]])

async def finish_profile(chat_id, uid: int, state: dict, photo_msg_id: int | None):
    ident = await _identity(uid)
    old = await users_col.find_one({"user_id": uid}) or {}
    now = now_utc()
    doc = {"user_id": uid, "name": state["name"], "age": state["age"], "gender": state["gender"],
           "looking_for": state["looking_for"], "region": state.get("region"), "city": state.get("city"),
           "city_norm": state.get("city_norm"), "bio": state["bio"], "photo_msg_id": photo_msg_id,
           "username": ident["username"], "tg_name": ident["tg_name"],
           # moderation is never overridden: a profile hidden by reports / a ban stays hidden when it is re-created
           "active": old.get("active") is not False and uid not in banned,
           "paused": False, "unreachable": False, "last_seen": now, "boost_until": now + timedelta(hours=24),
           "updated_at": now}
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
    elif step in ("match_gender", "match_look", "match_region"):
        await send_text(chat, "အပေါ်က ခလုတ်တွေကို နှိပ်ပြီး ရွေးပေးပါ။")
    elif step == "match_city":
        if not text:
            await send_text(chat, "မြို့ / မြို့နယ်ကို စာသားနဲ့ ရိုက်ပါ။ မထည့်ချင်ရင် Skip ကိုနှိပ်ပါ။")
            return
        await after_city(chat, uid, state, text)
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
_hint_at: dict = {}

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
        t = time.monotonic()
        if t - _hint_at.get(event.sender_id, -1e9) > 30:                  # at most one hint per 30 s
            _hint_at[event.sender_id] = t
            await send_menu(event.chat_id)
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
# 👥 GROUPS  ·  🔔 LIVE FEED  ·  📣 AUTO-BROADCAST  ·  💌 COMEBACK
# ============================================================
broadcast_queue = None              # asyncio.Queue, created in main()
_seen_groups: set = set()

def _group(e) -> bool:
    return not getattr(e, "is_private", False)

def _cmd_for_me(event) -> bool:
    """'/autopost@SomeOtherBot' is not meant for us."""
    first = ((event.raw_text or "").split() or [""])[0]
    if "@" in first:
        return first.split("@", 1)[1].lower() == (BOT_USERNAME or "").lower()
    return True

async def _chat_title(event) -> str:
    try:
        return getattr(await event.get_chat(), "title", "") or ""
    except Exception:
        return ""

async def register_group(chat_id: int, title: str = "", enable: bool = False):
    """Remember a group / channel the bot lives in.  enable=True force-enables it (bot was just added);
       otherwise an admin's earlier '/autopost off' is respected."""
    if not chat_id or chat_id > 0 or chat_id == STORAGE_GROUP_ID:
        return
    now = now_utc()
    s, oi = {"updated_at": now}, {"added_at": now}
    if title:
        s["title"] = title[:100]
    if enable:
        s.update(enabled=True, removed=False, fails=0)
    else:
        oi.update(enabled=True, removed=False, fails=0)
    await groups_col.update_one({"chat_id": chat_id}, {"$set": s, "$setOnInsert": oi}, upsert=True)
    _seen_groups.add(chat_id)

async def seed_groups():
    for gid in AUTO_POST_GROUP_IDS:
        await register_group(gid)

async def _is_group_admin(event) -> bool:
    if event.sender_id in MODS:
        return True
    try:
        perms = await bot.get_permissions(event.chat_id, event.sender_id)
        return bool(perms.is_admin or perms.is_creator)
    except Exception:
        return False

def _group_welcome() -> str:
    return (f"{pe('fire')} <b>BOD Social &amp; Match</b> ကို ထည့်ပေးလို့ ကျေးဇူးတင်ပါတယ်!\n\n"
            f"ဒီ Bot မှာ တင်တဲ့ Post အသစ်တွေ ဒီနေရာကို <b>အလိုအလျောက်</b> တက်လာပါမယ်။ "
            f"Reaction ပေးလို့ရပါတယ်၊ Comment / Share / Report ကိုနှိပ်ရင် Bot ထဲမှာ ဆက်လုပ်ရပါမယ်။\n\n"
            f"<i>Admin တွေက /autopost off နဲ့ ပိတ်၊ /autopost on နဲ့ ပြန်ဖွင့်နိုင်ပါတယ်။</i>")

def _open_bot_kb() -> list:
    return [[B("Bot ကို ဖွင့်မည်", url=f"https://t.me/{BOT_USERNAME}", icon="fire", style="primary")]]

_added_at: dict = {}

async def _chat_info(chat_id) -> dict:
    res = await api("getChat", chat_id=chat_id)
    return (res.get("result") or {}) if res.get("ok") else {}

async def on_bot_added(chat_id: int, title: str = ""):
    """The bot just got into a group / channel -> remember it, say hello, tell the moderators.  No ID typing needed."""
    if not chat_id or chat_id > 0 or chat_id == STORAGE_GROUP_ID:
        return
    t = time.monotonic()
    if t - _added_at.get(chat_id, -1e9) < 30:                 # several Telegram updates describe the same "added" event
        return
    _added_at[chat_id] = t
    info = await _chat_info(chat_id)
    title = title or info.get("title") or ""
    await register_group(chat_id, title, enable=True)
    if info.get("type") != "channel":                          # no chatter in broadcast channels
        await send_text(chat_id, _group_welcome(), _open_bot_kb())
    await notify_mods(f"✅ <b>Auto-post စာရင်းထဲ အလိုအလျောက် ထည့်ပြီးပါပြီ</b>\n💬 {esc(title or '?')} · <code>{chat_id}</code>")

async def on_bot_removed(chat_id: int):
    _seen_groups.discard(chat_id)
    _added_at.pop(chat_id, None)
    await groups_col.update_one({"chat_id": chat_id}, {"$set": {"enabled": False, "removed": True}})

@bot.on(events.ChatAction())
@safe("group_track")
async def group_track(event):
    """Service message: the bot was added to / removed from a group."""
    if not BOT_ID or BOT_ID not in set(getattr(event, "user_ids", None) or []):
        return
    if event.user_added or event.user_joined:
        title = ""
        try:
            title = getattr(await event.get_chat(), "title", "") or ""
        except Exception:
            pass
        await on_bot_added(event.chat_id, title)
    elif event.user_kicked or event.user_left:
        await on_bot_removed(event.chat_id)

@bot.on(events.Raw((UpdateChannelParticipant, UpdateChatParticipantAdd, UpdateChatParticipantDelete)))
@safe("my_membership")
async def my_membership(update):
    """MTProto tells a bot whenever ITS OWN membership changes (added, promoted, removed, banned) - groups AND channels."""
    if not BOT_ID or getattr(update, "user_id", None) != BOT_ID:
        return
    if isinstance(update, UpdateChatParticipantAdd):
        await on_bot_added(tl_utils.get_peer_id(PeerChat(update.chat_id)))
    elif isinstance(update, UpdateChatParticipantDelete):
        await on_bot_removed(tl_utils.get_peer_id(PeerChat(update.chat_id)))
    else:
        chat_id = tl_utils.get_peer_id(PeerChannel(update.channel_id))
        new = update.new_participant
        if new is None or isinstance(new, (ChannelParticipantLeft, ChannelParticipantBanned)):
            await on_bot_removed(chat_id)
        elif update.prev_participant is None:                  # freshly added (as member or straight as admin)
            await on_bot_added(chat_id)
        else:                                                  # promoted / demoted: keep it known, never override '/autopost off'
            await register_group(chat_id)

@bot.on(events.NewMessage(pattern=r"(?i)^/autopost(?:@\w+)?(?:\s+(on|off))?\s*$", incoming=True, func=_group))
@safe("autopost_cmd")
async def autopost_cmd(event):
    if not _cmd_for_me(event):
        return
    chat = event.chat_id
    await register_group(chat, await _chat_title(event))
    arg = (event.pattern_match.group(1) or "").lower()
    g = await groups_col.find_one({"chat_id": chat}) or {}
    on = g.get("enabled") is not False
    if arg:
        if not await _is_group_admin(event):
            await send_text(chat, f"{pe('info')} Group Admin တွေပဲ ပြောင်းလို့ရပါတယ်။")
            return
        on = arg == "on"
        await groups_col.update_one({"chat_id": chat}, {"$set": {"enabled": on, "fails": 0}})
    await send_text(chat, (f"{pe('post')} <b>Auto-post:</b> {'🟢 ON' if on else '🔴 OFF'}\n"
                           f"<i>Admin: /autopost on · /autopost off</i>"), _open_bot_kb())

@bot.on(events.NewMessage(pattern=r"(?i)^/(?:start|help)(?:@\w+)?(?:\s+\S+)?\s*$", incoming=True, func=_group))
@safe("group_start")
async def group_start(event):                       # also what "Add to group" (?startgroup=true) sends
    if not _cmd_for_me(event):
        return
    await register_group(event.chat_id, await _chat_title(event))
    await send_text(event.chat_id, _group_welcome(), _open_bot_kb())

@bot.on(events.NewMessage(incoming=True, func=_group))
@safe("group_seen")
async def group_seen(event):                        # fallback registration: any message seen in a group
    if event.chat_id not in _seen_groups:
        await register_group(event.chat_id, await _chat_title(event))

# ---------- moderator tools for groups ----------
@bot.on(events.NewMessage(pattern=r"^/groups\s*$", incoming=True, func=_mod))
@safe("groups_cmd")
async def groups_cmd(event):
    gs = await groups_col.find({}).sort("added_at", -1).limit(60).to_list(60)
    if not gs:
        await send_text(event.chat_id, f"{pe('info')} Group / Channel မရှိသေးပါ။ Bot ကို ထည့်ပါ (သို့) /addgroup &lt;chat_id&gt;")
        return
    lines = [f"{'🟢' if g.get('enabled') is not False else ('⚫' if g.get('removed') else '🔴')} {esc(g.get('title') or '?')} · <code>{g['chat_id']}</code>"
             for g in gs]
    await send_text(event.chat_id, f"💬 <b>Auto-post targets</b> ({len(gs)})\n\n" + "\n".join(lines) +
                    "\n\n<i>/addgroup &lt;chat_id&gt; · /delgroup &lt;chat_id&gt;</i>")

@bot.on(events.NewMessage(pattern=r"^/addgroup\s+(-?\d+)\s*$", incoming=True, func=_mod))
@safe("addgroup_cmd")
async def addgroup_cmd(event):
    gid = int(event.pattern_match.group(1))
    chk = await api("getChat", chat_id=gid)
    if not chk.get("ok"):
        await send_text(event.chat_id, f"{pe('info')} ဒီ Chat ကို မရောက်နိုင်ပါ - Bot က အထဲမှာ ရှိရဲ့လား စစ်ပါ။\n<code>{esc(str(chk.get('description')))}</code>")
        return
    await register_group(gid, (chk.get("result") or {}).get("title") or "", enable=True)
    await send_text(event.chat_id, f"{pe('check')} <code>{gid}</code> ကို Auto-post စာရင်းထဲ ထည့်ပြီးပါပြီ။")

@bot.on(events.NewMessage(pattern=r"^/delgroup\s+(-?\d+)\s*$", incoming=True, func=_mod))
@safe("delgroup_cmd")
async def delgroup_cmd(event):
    gid = int(event.pattern_match.group(1))
    await groups_col.update_one({"chat_id": gid}, {"$set": {"enabled": False}})
    await send_text(event.chat_id, f"{pe('check')} <code>{gid}</code> ကို Auto-post မှ ပိတ်လိုက်ပါပြီ။")

# ---------- delete group copies when a post goes away ----------
async def purge_group_copies(post: dict):
    for g in post.get("group_msgs") or []:
        for mid in g.get("ids") or []:
            await tg("deleteMessage", chat_id=g["chat"], message_id=mid)
    if post.get("group_msgs"):
        await posts_col.update_one({"post_id": post["post_id"]}, {"$unset": {"group_msgs": ""}})

async def purge_author_group_copies(uid: int):
    for p in await posts_col.find({"author_id": uid, "group_msgs.0": {"$exists": True}}).to_list(500):
        await purge_group_copies(p)

# ---------- the broadcast engine ----------
def enqueue_broadcast(post: dict, exclude: int = 0):
    if broadcast_queue is None:
        return
    try:
        broadcast_queue.put_nowait((post["post_id"], exclude))
    except Exception as e:
        print(f"⚠️ enqueue_broadcast: {e}")

async def _gather_limited(coros: list, limit: int = 5):
    sem = asyncio.Semaphore(limit)
    async def run(c):
        async with sem:
            try:
                return await c
            except Exception:
                traceback.print_exc()
    return await asyncio.gather(*(run(c) for c in coros))

async def _deliver_to_group(post: dict, g: dict):
    gid = g["chat_id"]
    ids: list = []
    token = _sent_ids.set(ids)
    try:
        res = await show_post(gid, post, ctx="g")
    finally:
        _sent_ids.reset(token)
    if res.get("ok"):
        await groups_col.update_one({"chat_id": gid}, {"$set": {"fails": 0, "last_post_at": now_utc()}})
        if ids:                                   # remembered so the copies can be deleted if the post is removed
            await posts_col.update_one({"post_id": post["post_id"]}, {"$push": {
                "group_msgs": {"$each": [{"chat": gid, "ids": ids}], "$slice": -300}}})
        return
    new_gid = (res.get("parameters") or {}).get("migrate_to_chat_id")
    if new_gid:                                   # basic group became a supergroup: the chat id changed -> follow it
        await groups_col.update_one({"chat_id": gid}, {"$set": {"enabled": False, "removed": True, "migrated_to": new_gid}})
        await register_group(new_gid, g.get("title") or "", enable=True)
        if not g.get("_migrated"):
            await _deliver_to_group(post, {"chat_id": new_gid, "title": g.get("title"), "fails": 0, "_migrated": True})
        return
    desc = (res.get("description") or "").lower()
    dead = any(k in desc for k in ("kicked", "not a member", "chat not found", "chat was deleted", "was upgraded"))
    fails = int(g.get("fails") or 0) + 1
    upd = {"fails": fails}
    if dead or fails >= 5:                        # gone for good / keeps failing -> stop trying (admin: /autopost on)
        upd.update(enabled=False, removed=dead)
    await groups_col.update_one({"chat_id": gid}, {"$set": upd})
    print(f"⚠️ auto-post to {gid} failed: {desc}")

async def _broadcast_groups(post: dict):
    targets = [g for g in await groups_col.find({"enabled": {"$ne": False}}).to_list(2000) if g["chat_id"] != STORAGE_GROUP_ID]
    await _gather_limited([_deliver_to_group(post, g) for g in targets], 4)

async def _broadcast_live(post: dict, exclude: int = 0):
    """Push the post to every member who left Live Feed on - never to the author, people in a block relation
       with the author, banned or unreachable members - and at most one push per LIVE_MIN_GAP seconds."""
    author, now = post["author_id"], now_utc()
    skip = {author, exclude} | set(banned)
    try:
        for b in await blocks_col.find({"$or": [{"blocker": author}, {"blocked": author}]}).to_list(5000):
            skip.update((b["blocker"], b["blocked"]))
    except Exception:
        pass
    q = {"live": {"$ne": False}, "unreachable": {"$ne": True}, "user_id": {"$nin": list(skip)},
         "$or": [{"last_live_at": {"$exists": False}}, {"last_live_at": {"$lt": now - timedelta(seconds=LIVE_MIN_GAP)}}]}
    members = await members_col.find(q, {"user_id": 1}).limit(5000).to_list(5000)

    async def one(uid: int):
        res = await show_post(uid, post, ctx="n")
        if res.get("ok"):
            await members_col.update_one({"user_id": uid}, {"$set": {"last_live_at": now_utc()}})
        await asyncio.sleep(0.05)
    await _gather_limited([one(m["user_id"]) for m in members], 5)

async def broadcast_worker():
    while True:
        pid, exclude = await broadcast_queue.get()
        try:
            post = await posts_col.find_one({"post_id": pid})
            if post and not post.get("hidden"):
                await _broadcast_groups(post)
                await _broadcast_live(post, exclude)
        except Exception:
            print("❌ broadcast failed")
            traceback.print_exc()
        finally:
            broadcast_queue.task_done()

async def post_cooldown_ok(chat_id, uid: int) -> bool:
    if POST_COOLDOWN <= 0 or uid in MODS:
        return True
    last = await posts_col.find_one({"author_id": uid}, sort=[("created_at", -1)])
    at = _aware(last.get("created_at")) if last else None
    if at:
        wait = POST_COOLDOWN - (now_utc() - at).total_seconds()
        if wait > 0:
            await send_text(chat_id, f"{pe('info')} Post တွေ ဆက်တိုက်မတင်ပါနဲ့ - {int(wait) + 1} စက္ကန့်စောင့်ပြီး ပြန်ပို့ပါ။")
            return False
    return True

# ---------- Live Feed switch ----------
@bot.on(events.NewMessage(pattern=r"(?i)^/live(?:\s+(on|off))?\s*$", incoming=True, func=_private))
@safe("live_cmd")
async def live_cmd(event):
    uid, arg = event.sender_id, (event.pattern_match.group(1) or "").lower()
    cur = (await members_col.find_one({"user_id": uid}) or {}).get("live", LIVE_FEED_DEFAULT)
    new = cur if not arg else arg == "on"
    if arg:
        await members_col.update_one({"user_id": uid}, {"$set": {"live": new}}, upsert=True)
    await send_text(event.chat_id, (f"{pe('post')} <b>Live Feed:</b> {'🔔 ON' if new else '🔕 OFF'}\n"
                                    f"<i>ON ဆိုရင် Post အသစ်တွေ ဒီ Chat ထဲကို အလိုအလျောက် ရောက်လာပါမယ်။</i>"),
                    [[B("ပိတ်မည်" if new else "ဖွင့်မည်", f"live:{'off' if new else 'on'}", icon="bell")]])

@bot.on(events.CallbackQuery(pattern=rb"^live:"))
@safe("live_cb")
async def live_cb(event):
    action, uid = event.data.decode().split(":")[1], event.sender_id
    cur = (await members_col.find_one({"user_id": uid}) or {}).get("live", LIVE_FEED_DEFAULT)
    new = (not cur) if action == "toggle" else action == "on"
    await members_col.update_one({"user_id": uid}, {"$set": {"live": new}}, upsert=True)
    await event.answer("🔔 Live Feed ဖွင့်လိုက်ပါပြီ" if new else "🔕 Live Feed ပိတ်လိုက်ပါပြီ")
    if action == "toggle":
        await tg("editMessageReplyMarkup", kb=await menu_rows(uid), chat_id=event.chat_id, message_id=event.query.msg_id)

# ---------- comeback: pause / resume / welcome back / recycling / nudges ----------
async def set_paused(uid: int, paused: bool) -> bool:
    upd = {"paused": paused}
    if not paused:
        upd["boost_until"] = now_utc() + timedelta(hours=24)          # back on top of the deck for a day
    r = await users_col.update_one({"user_id": uid}, {"$set": upd})
    return r.matched_count > 0

async def _pause_flow(chat_id, uid: int, paused: bool):
    if not await set_paused(uid, paused):
        await send_text(chat_id, f"{pe('info')} Match Profile မရှိသေးပါ။", [[B("Profile ဖန်တီးမည်", "menu:match", icon="match")]])
        return
    if paused:
        await send_text(chat_id, f"⏸ <b>Profile ကို ခဏဝှက်လိုက်ပါပြီ။</b>\nတခြားသူတွေ မတွေ့တော့ပါဘူး။ ပြန်လာရင် /resume (သို့) /start",
                        [[B("ပြန်ဖွင့်မည်", "mp:resume", icon="play")]])
    else:
        await send_text(chat_id, f"▶️ <b>Profile ကို ပြန်ဖွင့်လိုက်ပါပြီ!</b>\nနောက် ၂၄ နာရီ ထိပ်ဆုံးမှာ ပေါ်ပါမယ်။",
                        [[B("Match ရှာမည်", "menu:match", icon="match", style="primary")]])

@bot.on(events.NewMessage(pattern=r"(?i)^/(pause|resume)\s*$", incoming=True, func=_private))
@safe("pause_cmd")
async def pause_cmd(event):
    await _pause_flow(event.chat_id, event.sender_id, event.pattern_match.group(1).lower() == "pause")

async def _show_my_profile(chat_id, user: dict, rows: list):
    paused = bool(user.get("paused"))
    rows.insert(max(0, len(rows) - 1), [B("ပြန်ဖွင့်မည်" if paused else "ခဏဝှက်မည်",
                                          "mp:resume" if paused else "mp:pause", icon="play" if paused else "pause")])
    status = ("⛔ <b>Admin စစ်ဆေးနေလို့ Profile ကို ခေတ္တဝှက်ထားပါတယ်။</b>\n\n" if user.get("active") is False
              else "⏸ <b>Profile ကို ခဏဝှက်ထားပါတယ်။</b>\n\n" if paused else "")
    await show_card(chat_id, user, rows, prefix=status)

async def welcome_back(chat_id, uid: int):
    """Plain /start by someone who paused, blocked the bot or stayed away for days -> profile is back on top.
       A profile hidden by MODERATION (reports / ban) is never re-opened here."""
    back = uid in _revived
    _revived.discard(uid)
    me = await users_col.find_one({"user_id": uid})
    if not me or me.get("active") is False or not (back or me.get("paused")):
        return
    await users_col.update_one({"user_id": uid}, {"$set": {"paused": False, "unreachable": False,
                                                           "boost_until": now_utc() + timedelta(hours=24)}})
    n = len(await liker_profiles(uid))
    extra = f"\n{pe('love')} သင့်ကို Like လုပ်ထားသူ <b>{n}</b> ယောက် စောင့်နေပါတယ်!" if n else ""
    await send_text(chat_id, (f"{pe('fire')} <b>မင်္ဂလာပါ၊ ပြန်ရောက်လာပါပြီ!</b>\n"
                              f"သင့် Match Profile ကို ၂၄ နာရီ ထိပ်ဆုံးမှာ တင်ပေးလိုက်ပါပြီ။{extra}"),
                    [[B("Match ရှာမည်", "menu:match", icon="match", style="primary")]])

async def open_post_link(event, kind: str, post: dict):
    """Deep links from group copies: post_<id> · cv_<id> (comments) · cw_<id> (write comment) · rp_<id> (report)."""
    chat, uid, pid = event.chat_id, event.sender_id, post["post_id"]
    if kind == "post":
        await show_post(chat, post, ctx="d")
    elif kind == "cv":
        text, rows = comments_view(post, 0)
        await send_text(chat, text, rows)
    elif kind == "cw":
        await set_state(uid, step="comment", post_id=pid)
        await send_text(chat, f"{pe('comment')} သင့် Comment ကို ရိုက်ထည့်ပါ -\n<i>ပယ်ဖျက်ချင်ရင် /cancel</i>")
    elif kind == "rp":
        if post["author_id"] == uid:
            await send_text(chat, f"{pe('info')} ကိုယ့် Post ကို Report မလုပ်နိုင်ပါ။")
        elif await reports_col.find_one({"post_id": pid, "reporter": uid}):
            await send_text(chat, f"{pe('info')} ဒီ Post ကို Report လုပ်ပြီးသားပါ။")
        else:
            rows = [[B(label, f"rp:r:{pid}:{code}")] for code, label in REPORT_REASONS.items()] + [[B("မလုပ်တော့ပါ", "rp:x", icon="cancel")]]
            await send_text(chat, f"{pe('report')} <b>ဘာကြောင့် Report လုပ်မလဲ?</b>", rows)

async def _sample_users(q: dict, n: int = 40) -> list:
    """A random sample of the pool (not just the first 30 rows)."""
    try:
        return await users_col.aggregate([{"$match": q}, {"$sample": {"size": n}}]).to_list(n)
    except Exception:
        return await users_col.find(q).limit(n).to_list(n)

def _pick_best(cands: list, me: dict, liked_me: set) -> dict:
    """Random, but tilted towards: recently active, has a photo, already liked me, same town / region, just came back."""
    now = now_utc()
    def score(u: dict) -> float:
        s = random.random() * 2.0
        ls = _aware(u.get("last_seen"))
        if ls:
            s += max(0.0, 3.0 - (now - ls).total_seconds() / 86400 * 0.3)
        if u.get("photo_msg_id"):
            s += 1.0
        if u["user_id"] in liked_me:
            s += 2.5
        if me.get("city_norm") and u.get("city_norm") == me["city_norm"]:
            s += 1.5
        elif me.get("region") and u.get("region") == me["region"]:
            s += 0.7
        bu = _aware(u.get("boost_until"))
        if bu and bu > now:
            s += 3.0
        return s
    return max(cands, key=score)

async def _recycle_rows(uid: int) -> list:
    if await swipes_col.count_documents({"from_id": uid, "action": "pass"}):
        return [[B("Pass လုပ်ထားသူတွေ ပြန်ကြည့်မည်", "mp:recycle", icon="refresh")]]
    return []

async def reengage_once():
    """Idle members who have people waiting for them get ONE nudge (then 3 days of silence)."""
    now = now_utc()
    q = {"active": {"$ne": False}, "paused": {"$ne": True}, "unreachable": {"$ne": True},
         "last_seen": {"$lt": now - timedelta(days=REENGAGE_AFTER_DAYS)},
         "$or": [{"last_nudge": {"$exists": False}}, {"last_nudge": {"$lt": now - timedelta(days=3)}}]}
    for u in await users_col.find(q).limit(100).to_list(100):
        uid = u["user_id"]
        if uid in banned:
            continue
        await users_col.update_one({"user_id": uid}, {"$set": {"last_nudge": now_utc()}})
        n = len(await liker_profiles(uid))
        if n:
            await send_text(uid, (f"{pe('love')} <b>သင့်ကို Like လုပ်ထားသူ {n} ယောက် စောင့်နေပါတယ်!</b>\n"
                                  f"ဘယ်သူလဲ ကြည့်ချင်ရင် နှိပ်ပါ။"),
                            [[B("ကြည့်မယ်", "menu:likers", icon="love", style="primary")]])
            await asyncio.sleep(0.1)

async def reengage_loop():
    await asyncio.sleep(90)
    while True:
        try:
            await reengage_once()
        except Exception:
            print("❌ reengage failed")
            traceback.print_exc()
        await asyncio.sleep(3600)

async def verify_groups():
    """Self-healing: switch off groups the bot was removed from while it was offline, switch the ones it was
       added back to on again, follow supergroup migrations.  An admin's '/autopost off' is never overridden."""
    q = {"$or": [{"enabled": {"$ne": False}}, {"removed": True}]}
    for g in await groups_col.find(q).to_list(2000):
        gid = g["chat_id"]
        res = await api("getChatMember", chat_id=gid, user_id=BOT_ID)
        new_gid = (res.get("parameters") or {}).get("migrate_to_chat_id")
        if res.get("ok"):
            status = (res.get("result") or {}).get("status")
            if status in ("left", "kicked"):
                await groups_col.update_one({"chat_id": gid}, {"$set": {"enabled": False, "removed": True}})
            elif g.get("removed") and not g.get("migrated_to"):
                await groups_col.update_one({"chat_id": gid}, {"$set": {"enabled": True, "removed": False, "fails": 0}})
            if not g.get("title"):
                info = await _chat_info(gid)
                if info.get("title"):
                    await groups_col.update_one({"chat_id": gid}, {"$set": {"title": info["title"][:100]}})
        elif new_gid:
            await groups_col.update_one({"chat_id": gid}, {"$set": {"enabled": False, "removed": True, "migrated_to": new_gid}})
            await register_group(new_gid, g.get("title") or "", enable=True)
        elif any(k in (res.get("description") or "").lower() for k in ("kicked", "not a member", "chat not found", "deactivated")):
            await groups_col.update_one({"chat_id": gid}, {"$set": {"enabled": False, "removed": True}})
        await asyncio.sleep(0.2)

async def group_health_loop():
    await asyncio.sleep(20)
    while True:
        try:
            await verify_groups()
        except Exception:
            print("❌ verify_groups failed")
            traceback.print_exc()
        await asyncio.sleep(6 * 3600)

async def setup_commands():
    private = [("start", "စတင်မည် / Menu"), ("menu", "Menu ဖွင့်မည်"), ("feed", "Feed ကြည့်မည်"), ("top", "Top Posts"),
               ("filter", "Match Filter"), ("live", "Live Feed ဖွင့်/ပိတ်"), ("pause", "Profile ခဏဝှက်မည်"),
               ("resume", "Profile ပြန်ဖွင့်မည်"), ("blocked", "Block စာရင်း"), ("cancel", "ပယ်ဖျက်မည်")]
    await api("setMyCommands", commands=[{"command": c, "description": d} for c, d in private],
              scope={"type": "all_private_chats"})
    await api("setMyCommands", commands=[{"command": "autopost", "description": "Auto-post ဖွင့်/ပိတ် (Admin)"}],
              scope={"type": "all_group_chats"})

# ============================================================
# 🚀 STARTUP
# ============================================================
async def main():
    global BOT_USERNAME, BOT_ID, broadcast_queue
    validate_env()
    await bot.start(bot_token=BOT_TOKEN)
    me = await bot.get_me()
    BOT_USERNAME = BOT_USERNAME or me.username
    BOT_ID = me.id
    await ensure_indexes()
    await load_bans()
    await seed_groups()
    await setup_commands()
    chk = await api("getChat", chat_id=STORAGE_GROUP_ID)
    if not chk.get("ok"):
        print("⚠️ Storage group not reachable — add the bot to STORAGE_GROUP_ID as an admin, or media posts will fail.")
    print(f"🤖 Social & Match Bot is running as @{BOT_USERNAME}")
    broadcast_queue = asyncio.Queue()
    spawn(broadcast_worker())
    spawn(reengage_loop())
    spawn(group_health_loop())
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
