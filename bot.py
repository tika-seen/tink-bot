import os
import sqlite3
import datetime
import random
import math
import json
import urllib.request
import urllib.parse
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, LabeledPrice, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler, PreCheckoutQueryHandler
)

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
PARTNER_ID = 5953013280
CHANNEL = "@niwzex"
MAX_VERIFY_ATTEMPTS = 15
REPORT_LIMIT = 10
PREMIUM_FOR_PLUSHKI = 30000

NAME, AGE, MY_GENDER, LANG, ABOUT, CITY_OR_GEO, RADIUS, PHOTO, PARTNER_GENDER, PARTNER_AGE = range(10)
VERIFY_VIDEO = 100
EDIT_NAME, EDIT_AGE, EDIT_ABOUT, EDIT_PHOTO, EDIT_CITY, EDIT_RADIUS, EDIT_GENDER = range(200, 207)
EDIT_SONG = 500
ANON_VAL = 600
ROULETTE_CHAT = 700

conn = sqlite3.connect("dating.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("CREATE INDEX IF NOT EXISTS idx_city ON users(city)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_hidden ON users(hidden)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_user ON users(user_id)")
conn.commit()

cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT, name TEXT, age INTEGER, my_gender TEXT, about TEXT,
    lang TEXT DEFAULT 'ru',
    city TEXT, lat REAL, lon REAL, radius INTEGER DEFAULT 50,
    photos TEXT, partner_gender TEXT, partner_age_min INTEGER, partner_age_max INTEGER,
    verified INTEGER DEFAULT 0, premium_until TEXT,
    likes_today INTEGER DEFAULT 0, likes_date TEXT,
    verify_attempts INTEGER DEFAULT 0,
    last_shown INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, last_active TEXT,
    bonus_date TEXT, invited_by INTEGER DEFAULT 0, invites INTEGER DEFAULT 0,
    plushki INTEGER DEFAULT 0, streak INTEGER DEFAULT 0, streak_date TEXT,
    reports_count INTEGER DEFAULT 0, not_show TEXT DEFAULT '', city_reminded INTEGER DEFAULT 0,
    song TEXT DEFAULT '', roulette_partner INTEGER DEFAULT 0
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS likes (
    from_id INTEGER, to_id INTEGER, valentine INTEGER DEFAULT 0
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS reports (
    from_id INTEGER, to_id INTEGER, reason TEXT, date TEXT
)""")
conn.commit()


def today():
    return datetime.date.today().isoformat()


def days_since(date_str):
    try:
        d = datetime.date.fromisoformat(date_str)
        return (datetime.date.today() - d).days
    except:
        return 999


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def geocode_city(city_name):
    try:
        url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({
            "q": city_name, "format": "json", "limit": 1
        })
        req = urllib.request.Request(url, headers={"User-Agent": "TinkBot/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
            if data:
                return float(data[0]["lat"]), float(data[0]["lon"])
    except Exception as e:
        print("geocode error:", e)
    return None, None


def main_menu():
    return ReplyKeyboardMarkup([
        ["👀 Искать", "❤️ Лайки"],
        ["💖 Мэтчи", "✏️ Моя анкета"],
        ["⭐ Premium", "🎁 Бонус"],
        ["🎵 Песня", "💌 Валентинка"],
        ["🎤 Рулетка"]
    ], resize_keyboard=True)


def profile_menu():
    return ReplyKeyboardMarkup([
        ["✏️ Редактировать", "👥 Пригласи друга"],
        ["✅ Верификация", "🗑 Удалить анкету"],
        ["🔙 В меню"]
    ], resize_keyboard=True)


def edit_menu():
    return ReplyKeyboardMarkup([
        ["Имя", "Возраст"],
        ["Описание", "Фото"],
        ["🏙 Город / Гео", "Радиус"],
        ["Пол", "🔙 Назад"]
    ], resize_keyboard=True)


def is_premium(user_id):
    if user_id in [ADMIN_ID, PARTNER_ID]:
        return True
    cur.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        return False
    try:
        return datetime.date.fromisoformat(row[0]) >= datetime.date.today()
    except:
        return False


def get_photo_limit(user_id):
    return 6 if is_premium(user_id) else 3


def check_like_limit(user_id):
    cur.execute("SELECT verified, likes_today, likes_date FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return False
    verified, likes_today, likes_date = row
    if likes_date != today():
        cur.execute("UPDATE users SET likes_today = 0, likes_date = ? WHERE user_id = ?", (today(), user_id))
        conn.commit()
        likes_today = 0
    if is_premium(user_id):
        cur.execute("UPDATE users SET likes_today = likes_today + 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        return True
    limit = 500 if verified else 150
    if likes_today >= limit:
        return False
    cur.execute("UPDATE users SET likes_today = likes_today + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    return True


async def check_subscription(update, context):
    user_id = update.effective_user.id
    if user_id in [ADMIN_ID, PARTNER_ID]:
        return True
    try:
        member = await context.bot.get_chat_member(CHANNEL, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False


async def sub_gate(update, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Подписаться", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
        [InlineKeyboardButton("✅ Проверить", callback_data="check_sub")]
    ])
    await update.message.reply_text("Чтобы пользоваться ботом, подпишись на наш канал 💕", reply_markup=kb)


async def start(update, context):
    if not await check_subscription(update, context):
        await sub_gate(update, context)
        return ConversationHandler.END
    user_id = update.effective_user.id
    args = context.args
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cur.fetchone():
        if args and args[0].startswith("ref"):
            try:
                inviter = int(args[0].replace("ref", ""))
                if inviter != user_id:
                    cur.execute("SELECT invited_by FROM users WHERE user_id = ?", (user_id,))
                    r = cur.fetchone()
                    if r and r[0] == 0:
                        cur.execute("UPDATE users SET invited_by = ? WHERE user_id = ?", (inviter, user_id))
                        cur.execute("UPDATE users SET invites = invites + 1, plushki = plushki + 100 WHERE user_id = ?", (inviter,))
                        conn.commit()
                        try:
                            await context.bot.send_message(inviter, "🎉 По твоей ссылке пришёл друг! +100 плюшек.")
                        except:
                            pass
            except:
                pass
        cur.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (today(), user_id))
        conn.commit()
        cur.execute("SELECT city, city_reminded FROM users WHERE user_id = ?", (user_id,))
        c = cur.fetchone()
        if c and not c[0] and c[1] == 0:
            cur.execute("UPDATE users SET city_reminded = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            await update.message.reply_text("📍 Ты не указал(а) город. Укажи в «✏️ Моя анкета» → «🏙 Город / Гео».")
        await update.message.reply_text("Ты уже зарегистрирован(а) 💕", reply_markup=main_menu())
        return ConversationHandler.END
    context.user_data["ref"] = args[0] if args else None
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
         InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")],
        [InlineKeyboardButton("🇺🇦 Українська", callback_data="lang_uk"),
         InlineKeyboardButton("🇰🇿 Қазақша", callback_data="lang_kz")]
    ])
    await update.message.reply_text("Выбери язык / Choose language:", reply_markup=kb)
    return LANG


async def get_lang(update, context):
    q = update.callback_query
    await q.answer()
    lang = q.data.replace("lang_", "")
    context.user_data["lang"] = lang
    await q.edit_message_text("Язык выбран ✅\n\nКак тебя зовут?")
    return NAME


async def get_name(update, context):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Сколько тебе лет? (15–99)")
    return AGE


async def get_age(update, context):
    try:
        age = int(update.message.text)
        if age < 15 or age > 99:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Возраст числом от 15 до 99. Попробуй ещё:")
        return AGE
    context.user_data["age"] = age
    await update.message.reply_text("Твой пол:", reply_markup=ReplyKeyboardMarkup([["М", "Ж"]], resize_keyboard=True))
    return MY_GENDER


async def get_my_gender(update, context):
    g = update.message.text
    if g not in ["М", "Ж"]:
        await update.message.reply_text("Выбери М или Ж")
        return MY_GENDER
    context.user_data["my_gender"] = g
    await update.message.reply_text("Расскажи о себе или нажми «Пропустить»",
        reply_markup=ReplyKeyboardMarkup([["Пропустить"]], resize_keyboard=True))
    return ABOUT


async def get_about(update, context):
    context.user_data["about"] = "" if update.message.text == "Пропустить" else update.message.text
    kb = ReplyKeyboardMarkup([
        [KeyboardButton("📍 Отправить гео", request_location=True)],
        ["⏭ Пропустить"]
    ], resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("Напиши свой город 🏙\nили отправь гео 📍\nили нажми «⏭ Пропустить»", reply_markup=kb)
    return CITY_OR_GEO


async def get_city_or_geo(update, context):
    if update.message.location:
        context.user_data["lat"] = update.message.location.latitude
        context.user_data["lon"] = update.message.location.longitude
        context.user_data["city"] = ""
    elif update.message.text == "⏭ Пропустить":
        context.user_data["lat"] = None
        context.user_data["lon"] = None
        context.user_data["city"] = ""
    else:
        city = update.message.text.strip()
        lat, lon = geocode_city(city)
        context.user_data["city"] = city
        context.user_data["lat"] = lat
        context.user_data["lon"] = lon
        if lat:
            await update.message.reply_text(f"🏙 {city} — найдено ✅")
        else:
            await update.message.reply_text(f"🏙 {city} — сохранено")
    await update.message.reply_text("Радиус поиска в км (5–100):",
        reply_markup=ReplyKeyboardMarkup([["5", "10", "25"], ["50", "75", "100"]], resize_keyboard=True))
    return RADIUS


async def get_radius(update, context):
    try:
        r = int(update.message.text)
        if r < 5 or r > 100:
            raise ValueError
    except:
        await update.message.reply_text("Число от 5 до 100")
        return RADIUS
    context.user_data["radius"] = r
    context.user_data["photos"] = []
    limit = get_photo_limit(update.effective_user.id)
    await update.message.reply_text(f"Отправь фото или видео (от 1 до {limit})")
    return PHOTO


async def get_photo(update, context):
    photos = context.user_data.get("photos", [])
    limit = get_photo_limit(update.effective_user.id)
    if update.message.photo:
        photos.append(update.message.photo[-1].file_id)
    elif update.message.video:
        photos.append(update.message.video.file_id)
    else:
        await update.message.reply_text("Это не фото и не видео. Попробуй ещё:")
        return PHOTO
    context.user_data["photos"] = photos
    if len(photos) >= limit:
        await update.message.reply_text(f"Максимум {limit}. Пол партнёра:",
            reply_markup=ReplyKeyboardMarkup([["М", "Ж", "Всё равно"]], resize_keyboard=True))
        return PARTNER_GENDER
    await update.message.reply_text(f"Добавлено ({len(photos)}/{limit}). Добавить ещё или Готово?",
        reply_markup=ReplyKeyboardMarkup([["Добавить ещё", "Готово"]], resize_keyboard=True))
    return PHOTO


async def photo_choice(update, context):
    if update.message.text == "Готово":
        await update.message.reply_text("Пол партнёра:",
            reply_markup=ReplyKeyboardMarkup([["М", "Ж", "Всё равно"]], resize_keyboard=True))
        return PARTNER_GENDER
    await update.message.reply_text("Отправь ещё фото или видео")
    return PHOTO


async def get_partner_gender(update, context):
    context.user_data["partner_gender"] = update.message.text
    await update.message.reply_text("Возраст партнёра от и до (например: 15-25)")
    return PARTNER_AGE


async def get_partner_age(update, context):
    try:
        a, b = update.message.text.split("-")
        amin, amax = int(a), int(b)
        if amin < 15 or amax > 99 or amin > amax:
            raise ValueError
    except:
        await update.message.reply_text("Формат: 15-25 (от 15 до 99)")
        return PARTNER_AGE
    user = update.effective_user
    ref = context.user_data.get("ref")
    inviter = 0
    if ref and ref.startswith("ref"):
        try:
            inviter = int(ref.replace("ref", ""))
            if inviter == user.id:
                inviter = 0
        except:
            inviter = 0
    pl = 1000000 if user.id in [ADMIN_ID, PARTNER_ID] else 0
    cur.execute("""INSERT OR REPLACE INTO users
        (user_id, username, name, age, my_gender, about, lang, city, lat, lon, radius,
         photos, partner_gender, partner_age_min, partner_age_max, verified,
         premium_until, likes_today, likes_date, verify_attempts,
         last_shown, hidden, last_active, bonus_date, invited_by, invites,
         plushki, streak, streak_date, reports_count, not_show, city_reminded,
         song, roulette_partner)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
        user.id, user.username or "", context.user_data["name"], context.user_data["age"],
        context.user_data["my_gender"], context.user_data["about"],
        context.user_data.get("lang", "ru"),
        context.user_data["city"], context.user_data.get("lat"), context.user_data.get("lon"),
        context.user_data["radius"], ",".join(context.user_data["photos"]),
        context.user_data["partner_gender"], amin, amax,
        0, None, 0, today(), 0, 0, 0, today(), "", inviter, 0,
        pl, 0, "", 0, "", 0, "", 0
    ))
    conn.commit()
    if inviter:
        cur.execute("UPDATE users SET invites = invites + 1, plushki = plushki + 100 WHERE user_id = ?", (inviter,))
        conn.commit()
        try:
            await context.bot.send_message(inviter, "🎉 По твоей ссылке пришёл друг! +100 плюшек.")
        except:
            pass
    await update.message.reply_text("Анкета готова! 💕", reply_markup=main_menu())
    return ConversationHandler.END


async def find(update, context):
    user_id = update.effective_user.id
    cur.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (today(), user_id))
    conn.commit()
    if not check_like_limit(user_id):
        await update.message.reply_text("Лимит лайков исчерпан.\n🎁 Бонус\n👥 Пригласи друга\n⭐ Premium")
        return
    cur.execute("SELECT city, lat, lon, radius, not_show FROM users WHERE user_id = ?", (user_id,))
    me = cur.fetchone()
    my_city, my_lat, my_lon, my_radius, my_not_show = me if me else ("", None, None, 50, "")
    not_show_list = [int(x) for x in my_not_show.split(",") if x.strip().isdigit()]
    cur.execute("""SELECT user_id, name, age, about, photos, my_gender, city, lat, lon, verified, song
                   FROM users WHERE user_id != ? AND user_id != ? AND hidden = 0 LIMIT 200""",
                (user_id, ADMIN_ID))
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("Анкеты закончились 😔")
        return
    candidates = []
    for r in rows:
        uid, name, age, about, photos, gender, city, lat, lon, ver, song = r
        if uid in not_show_list or uid == PARTNER_ID:
            continue
        cur.execute("SELECT 1 FROM likes WHERE from_id = ? AND to_id = ?", (user_id, uid))
        if cur.fetchone():
            continue
        dist = None
        match = False
        if my_lat and my_lon and lat and lon:
            dist = haversine(my_lat, my_lon, lat, lon)
            if dist <= my_radius:
                match = True
        elif my_city and city and my_city.lower() == city.lower():
            match = True
        if match:
            candidates.append((dist if dist is not None else 9999, uid, name, age, about, photos, gender, city, dist, ver, song))
    if not candidates:
        await update.message.reply_text("В твоём городе/радиусе пока никого нет 😔")
        return
    candidates.sort(key=lambda x: x[0])
    dist, uid, name, age, about, photos, gender, city, real_dist, ver, song = candidates[0]
    cur.execute("UPDATE users SET last_shown = ? WHERE user_id = ?", (uid, user_id))
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM likes WHERE to_id = ?", (uid,))
    likes_count = cur.fetchone()[0]
    cur.execute("SELECT last_active FROM users WHERE user_id = ?", (uid,))
    la = cur.fetchone()
    newbie = " 🆕" if (la and la[0] and days_since(la[0]) <= 3) else ""
    badges = ""
    if ver:
        badges += " ✅"
    if is_premium(uid):
        badges += " ⭐"
    dist_text = ""
    if real_dist is not None:
        dist_text = f"\n📍 {round(real_dist, 1)} км"
    elif city:
        dist_text = f"\n🏙 {city}"
    song_line = f"\n🎵 {song}" if song else ""
    percent = 0
    if name: percent += 20
    if age: percent += 20
    if about: percent += 20
    if photos: percent += 20
    if city or (lat and lon): percent += 20
    text = (f"👤 {name}, {age} ({gender}){badges}{newbie}{dist_text}{song_line}\n"
            f"❤️ {likes_count} лайков · 📊 {percent}%\n\n{about or '—'}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Лайк", callback_data=f"like_{uid}"),
         InlineKeyboardButton("💌 Валентинка", callback_data=f"val_{uid}")],
        [InlineKeyboardButton("👎 Пропустить", callback_data="skip"),
         InlineKeyboardButton("🚨 Жалоба", callback_data=f"report_{uid}")],
        [InlineKeyboardButton("🚫 Не показывать", callback_data=f"hide_{uid}")]
    ])
    photos_list = photos.split(",") if photos else []
    if photos_list:
        for i, fid in enumerate(photos_list):
            if i == 0:
                await update.message.reply_photo(fid, caption=text, reply_markup=kb)
            else:
                await update.message.reply_photo(fid)
    else:
        await update.message.reply_text(text, reply_markup=kb)


async def like_handler(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    me = q.from_user.id
    if data == "check_sub":
        if await check_subscription(update, context):
            await q.edit_message_text("✅ Спасибо! Напиши /start")
        else:
            await q.answer("Ты ещё не подписан(а)", show_alert=True)
        return
    if data == "skip":
        try:
            await q.edit_message_caption("Пропущено 👎")
        except:
            await q.edit_message_text("Пропущено 👎")
        return
    if data.startswith("hide_"):
        target = int(data.split("_")[1])
        cur.execute("SELECT not_show FROM users WHERE user_id = ?", (me,))
        r = cur.fetchone()
        ns = r[0] if r else ""
        new_ns = (ns + "," + str(target)) if ns else str(target)
        cur.execute("UPDATE users SET not_show = ? WHERE user_id = ?", (new_ns, me))
        conn.commit()
        try:
            await q.edit_message_caption("🚫 Больше не показываем")
        except:
            await q.edit_message_text("🚫 Больше не показываем")
        return
    if data.startswith("report_"):
        target = int(data.split("_")[1])
        cur.execute("INSERT INTO reports VALUES (?, ?, ?, ?)", (me, target, "жалоба", today()))
        cur.execute("UPDATE users SET reports_count = reports_count + 1 WHERE user_id = ?", (target,))
        conn.commit()
        cur.execute("SELECT reports_count FROM users WHERE user_id = ?", (target,))
        rc = cur.fetchone()
        if rc and rc[0] >= REPORT_LIMIT:
            cur.execute("UPDATE users SET hidden = 1 WHERE user_id = ?", (target,))
            conn.commit()
        try:
            await q.edit_message_caption("Жалоба отправлена 🚨")
        except:
            pass
        if ADMIN_ID:
            try:
                await context.bot.send_message(ADMIN_ID, f"🚨 Жалоба на {target} от {me}")
            except:
                pass
        return
    if data.startswith("like_") or data.startswith("val_"):
        target = int(data.split("_")[1])
        val = 1 if data.startswith("val_") else 0
        cur.execute("INSERT INTO likes VALUES (?, ?, ?)", (me, target, val))
        conn.commit()
        cur.execute("SELECT 1 FROM likes WHERE from_id = ? AND to_id = ?", (target, me))
        if cur.fetchone():
            cur.execute("SELECT username FROM users WHERE user_id = ?", (target,))
            uname = cur.fetchone()[0]
            kb = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Написать", url=f"tg://user?id={target}")]])
            try:
                await q.edit_message_caption("💖 Мэтч!", reply_markup=kb)
            except:
                pass
            try:
                await context.bot.send_message(target, "💖 У тебя мэтч! Открой бота.")
            except:
                pass
        else:
            try:
                await q.edit_message_caption("Отправлено 💕")
            except:
                pass


async def my_profile(update, context):
    user_id = update.effective_user.id
    cur.execute("""SELECT name, age, my_gender, about, photos, verified, city, radius, lat, lon, song
                   FROM users WHERE user_id = ?""", (user_id,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Анкеты нет. /start")
        return
    name, age, gender, about, photos, verified, city, radius, lat, lon, song = row
    cur.execute("SELECT COUNT(*) FROM likes WHERE to_id = ?", (user_id,))
    likes_count = cur.fetchone()[0]
    cur.execute("SELECT invites, plushki FROM users WHERE user_id = ?", (user_id,))
    inv = cur.fetchone()
    invites = inv[0] if inv else 0
    pl = inv[1] if inv else 0
    status = []
    if verified: status.append("✅")
    if is_premium(user_id): status.append("⭐")
    loc = "📍 по гео" if (lat and lon) else (f"🏙 {city}" if city else "❌ не указан")
    song_line = f"🎵 {song}\n" if song else ""
    text = (f"👤 {name}, {age} ({gender}) {' '.join(status)}\n"
            f"{song_line}{loc} · 📏 {radius} км\n"
            f"❤️ {likes_count} лайков · 👥 {invites} друзей\n"
            f"💎 {pl} плюшек\n\n{about or '—'}")
    photos_list = photos.split(",") if photos else []
    if photos_list:
        for i, fid in enumerate(photos_list):
            if i == 0:
                await update.message.reply_photo(fid, caption=text, reply_markup=profile_menu())
            else:
                await update.message.reply_photo(fid)
    else:
        await update.message.reply_text(text, reply_markup=profile_menu())


async def edit_start(update, context):
    await update.message.reply_text("Что хочешь изменить?", reply_markup=edit_menu())
    return EDIT_NAME


async def edit_choice(update, context):
    t = update.message.text
    if t == "🔙 Назад":
        await update.message.reply_text("Главное меню", reply_markup=main_menu())
        return ConversationHandler.END
    if t == "Имя":
        await update.message.reply_text("Новое имя:")
        return EDIT_NAME
    if t == "Возраст":
        await update.message.reply_text("Новый возраст (15–99):")
        return EDIT_AGE
    if t == "Описание":
        await update.message.reply_text("Новое описание:")
        return EDIT_ABOUT
    if t == "Фото":
        await update.message.reply_text("Отправь новые фото")
        context.user_data["edit_photos"] = []
        return EDIT_PHOTO
    if t == "🏙 Город / Гео":
        kb = ReplyKeyboardMarkup([
            [KeyboardButton("📍 Отправить гео", request_location=True)],
            ["⏭ Пропустить"]
        ], resize_keyboard=True, one_time_keyboard=True)
        await update.message.reply_text("Напиши город или отправь гео:", reply_markup=kb)
        return EDIT_CITY
    if t == "Радиус":
        await update.message.reply_text("Новый радиус (5–100):",
            reply_markup=ReplyKeyboardMarkup([["5", "10", "25"], ["50", "75", "100"]], resize_keyboard=True))
        return EDIT_RADIUS
    if t == "Пол":
        await update.message.reply_text("Новый пол:",
            reply_markup=ReplyKeyboardMarkup([["М", "Ж"]], resize_keyboard=True))
        return EDIT_GENDER
    await update.message.reply_text("Выбери из меню")
    return EDIT_NAME


async def save_name(update, context):
    cur.execute("UPDATE users SET name = ? WHERE user_id = ?", (update.message.text, update.effective_user.id))
    conn.commit()
    await update.message.reply_text("✅ Имя изменено", reply_markup=main_menu())
    return ConversationHandler.END


async def save_age(update, context):
    try:
        age = int(update.message.text)
        if age < 15 or age > 99:
            raise ValueError
    except:
        await update.message.reply_text("Число от 15 до 99")
        return EDIT_AGE
    cur.execute("UPDATE users SET age = ? WHERE user_id = ?", (age, update.effective_user.id))
    conn.commit()
    await update.message.reply_text("✅ Возраст изменён", reply_markup=main_menu())
    return ConversationHandler.END


async def save_about(update, context):
    cur.execute("UPDATE users SET about = ? WHERE user_id = ?", (update.message.text, update.effective_user.id))
    conn.commit()
    await update.message.reply_text("✅ Описание изменено", reply_markup=main_menu())
    return ConversationHandler.END


async def save_photo(update, context):
    photos = context.user_data.get("edit_photos", [])
    limit = get_photo_limit(update.effective_user.id)
    if update.message.photo:
        photos.append(update.message.photo[-1].file_id)
    elif update.message.video:
        photos.append(update.message.video.file_id)
    else:
        await update.message.reply_text("Нужно фото/видео")
        return EDIT_PHOTO
    context.user_data["edit_photos"] = photos
    if len(photos) >= limit:
        cur.execute("UPDATE users SET photos = ? WHERE user_id = ?", (",".join(photos), update.effective_user.id))
        conn.commit()
        await update.message.reply_text("✅ Фото обновлены", reply_markup=main_menu())
        return ConversationHandler.END
    await update.message.reply_text(f"({len(photos)}/{limit}) Ещё или Готово?",
        reply_markup=ReplyKeyboardMarkup([["Добавить ещё", "Готово"]], resize_keyboard=True))
    return EDIT_PHOTO


async def save_photo_choice(update, context):
    if update.message.text == "Готово":
        photos = context.user_data.get("edit_photos", [])
        cur.execute("UPDATE users SET photos = ? WHERE user_id = ?", (",".join(photos), update.effective_user.id))
        conn.commit()
        await update.message.reply_text("✅ Фото обновлены", reply_markup=main_menu())
        return ConversationHandler.END
    await update.message.reply_text("Отправь ещё фото")
    return EDIT_PHOTO


async def save_city(update, context):
    if update.message.location:
        cur.execute("UPDATE users SET lat = ?, lon = ?, city = '' WHERE user_id = ?",
                    (update.message.location.latitude, update.message.location.longitude, update.effective_user.id))
    elif update.message.text == "⏭ Пропустить":
        cur.execute("UPDATE users SET city = '', lat = NULL, lon = NULL WHERE user_id = ?", (update.effective_user.id,))
    else:
        city = update.message.text.strip()
        lat, lon = geocode_city(city)
        cur.execute("UPDATE users SET city = ?, lat = ?, lon = ? WHERE user_id = ?",
                    (city, lat, lon, update.effective_user.id))
    conn.commit()
    await update.message.reply_text("✅ Обновлено", reply_markup=main_menu())
    return ConversationHandler.END


async def save_radius(update, context):
    try:
        r = int(update.message.text)
        if r < 5 or r > 100:
            raise ValueError
    except:
        await update.message.reply_text("Число от 5 до 100")
        return EDIT_RADIUS
    cur.execute("UPDATE users SET radius = ? WHERE user_id = ?", (r, update.effective_user.id))
    conn.commit()
    await update.message.reply_text("✅ Радиус изменён", reply_markup=main_menu())
    return ConversationHandler.END


async def save_gender(update, context):
    g = update.message.text
    if g not in ["М", "Ж"]:
        await update.message.reply_text("М или Ж")
        return EDIT_GENDER
    cur.execute("UPDATE users SET my_gender = ? WHERE user_id = ?", (g, update.effective_user.id))
    conn.commit()
    await update.message.reply_text("✅ Пол изменён", reply_markup=main_menu())
    return ConversationHandler.END


async def my_likes(update, context):
    user_id = update.effective_user.id
    cur.execute("""SELECT u.name, u.username FROM likes l
                   JOIN users u ON u.user_id = l.to_id WHERE l.from_id = ?""", (user_id,))
    rows = cur.fetchall()
    text = "\n".join([f"{n} — @{u or 'скрыт'}" for n, u in rows]) if rows else "Пусто"
    await update.message.reply_text("❤️ Лайки:\n" + text)


async def my_matches(update, context):
    user_id = update.effective_user.id
    cur.execute("""SELECT u.name, u.username, u.user_id FROM likes l1
                   JOIN likes l2 ON l1.to_id = l2.from_id AND l1.from_id = l2.to_id
                   JOIN users u ON u.user_id = l1.to_id WHERE l1.from_id = ?""", (user_id,))
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("💖 Мэтчей пока нет")
        return
    for n, u, uid in rows:
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("💬 Написать", url=f"tg://user?id={uid}")]])
        await update.message.reply_text(f"💖 {n} — @{u or 'скрыт'}", reply_markup=kb)


async def bonus(update, context):
    user_id = update.effective_user.id
    cur.execute("SELECT bonus_date, streak, streak_date FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Сначала /start")
        return
    bonus_date, streak, streak_date = row
    if bonus_date == today():
        await update.message.reply_text("Ты уже получил(а) бонус. Приходи завтра 💕")
        return
    if streak_date == (datetime.date.today() - datetime.timedelta(days=1)).isoformat():
        streak += 1
    else:
        streak = 1
    plushki = 10 + streak * 5
    cur.execute("UPDATE users SET bonus_date = ?, streak = ?, streak_date = ?, plushki = plushki + ? WHERE user_id = ?",
                (today(), streak, today(), plushki, user_id))
    conn.commit()
    await update.message.reply_text(f"🎁 Бонус!\n+{plushki} плюшек\n🔥 Стрик: {streak} дн.")


async def invite(update, context):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref{user_id}"
    cur.execute("SELECT invites, plushki FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    invites = row[0] if row else 0
    pl = row[1] if row else 0
    await update.message.reply_text(
        f"👥 Пригласи друга\n\nТвоя ссылка:\n{link}\n\nЗа друга +100 плюшек.\n"
        f"Приглашено: {invites}\n💎 Плюшек: {pl}")


async def set_song(update, context):
    await update.message.reply_text("🎵 Напиши название песни (исполнитель — трек):")
    return EDIT_SONG


async def save_song(update, context):
    cur.execute("UPDATE users SET song = ? WHERE user_id = ?", (update.message.text, update.effective_user.id))
    conn.commit()
    await update.message.reply_text("✅ Песня сохранена", reply_markup=main_menu())
    return ConversationHandler.END


async def anon_valentine(update, context):
    user_id = update.effective_user.id
    cur.execute("""SELECT user_id, name FROM users
                   WHERE user_id != ? AND user_id != ? AND user_id != ? AND hidden = 0 LIMIT 1""",
                (user_id, ADMIN_ID, PARTNER_ID))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Нет других пользователей")
        return ConversationHandler.END
    target, name = row
    context.user_data["val_to"] = target
    await update.message.reply_text(f"💌 Напиши анонимную валентинку для {name}:")
    return ANON_VAL


async def send_valentine(update, context):
    target = context.user_data.get("val_to")
    if not target:
        return ConversationHandler.END
    try:
        await context.bot.send_message(target, f"💌 Тебе анонимная валентинка:\n\n{update.message.text}")
    except:
        pass
    await update.message.reply_text("💌 Валентинка отправлена!", reply_markup=main_menu())
    return ConversationHandler.END


async def roulette_start(update, context):
    user_id = update.effective_user.id
    cur.execute("SELECT roulette_partner FROM users WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    if r and r[0]:
        await update.message.reply_text("🎤 Ты уже в рулетке. Пиши голосовые — бот перешлёт.\n/roulette_stop — выйти.")
        return
    cur.execute("""SELECT user_id FROM users WHERE roulette_partner = 0
                   AND user_id != ? AND user_id != ? AND hidden = 0 LIMIT 1""",
                (user_id, ADMIN_ID))
    r = cur.fetchone()
    if not r:
        await update.message.reply_text("🎤 Никого нет. Попробуй позже.")
        return
    partner = r[0]
    cur.execute("UPDATE users SET roulette_partner = ? WHERE user_id = ?", (partner, user_id))
    cur.execute("UPDATE users SET roulette_partner = ? WHERE user_id = ?", (user_id, partner))
    conn.commit()
    await update.message.reply_text("🎤 Ты в рулетке! Пиши голосовые — бот перешлёт.\n/roulette_stop — выйти.")
    try:
        await context.bot.send_message(partner, "🎤 Ты в рулетке! Пиши голосовые.")
    except:
        pass


async def roulette_stop(update, context):
    user_id = update.effective_user.id
    cur.execute("SELECT roulette_partner FROM users WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    if r and r[0]:
        partner = r[0]
        cur.execute("UPDATE users SET roulette_partner = 0 WHERE user_id = ?", (user_id,))
        cur.execute("UPDATE users SET roulette_partner = 0 WHERE user_id = ?", (partner,))
        conn.commit()
        try:
            await context.bot.send_message(partner, "🎤 Собеседник вышел из рулетки.")
        except:
            pass
    await update.message.reply_text("🎤 Ты вышел из рулетки.", reply_markup=main_menu())


async def roulette_forward(update, context):
    user_id = update.effective_user.id
    cur.execute("SELECT roulette_partner FROM users WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    if not r or not r[0]:
        return
    partner = r[0]
    if update.message.voice:
        try:
            await context.bot.send_voice(partner, update.message.voice.file_id)
        except:
            pass
    elif update.message.text:
        try:
            await context.bot.send_message(partner, f"🎤 {update.message.text}")
        except:
            pass


async def premium(update, context):
    user_id = update.effective_user.id
    if is_premium(user_id):
        if user_id in [ADMIN_ID, PARTNER_ID]:
            await update.message.reply_text("⭐ У тебя Premium навсегда")
            return
        cur.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
        until = cur.fetchone()[0]
        await update.message.reply_text(f"⭐ Premium активен до {until}")
        return
    cur.execute("SELECT plushki FROM users WHERE user_id = ?", (user_id,))
    pl = cur.fetchone()[0]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ 3 дня — 30 звёзд", callback_data="buy_3")],
        [InlineKeyboardButton("⭐ 10 дней — 50 звёзд", callback_data="buy_10")],
        [InlineKeyboardButton("⭐ 18 дней — 70 звёзд", callback_data="buy_18")],
        [InlineKeyboardButton(f"💎 Купить за {PREMIUM_FOR_PLUSHKI} плюшек", callback_data="buy_plushki")]
    ])
    await update.message.reply_text(
        f"⭐ Premium\n\n• Кто лайкнул — бесплатно\n• Безлимит лайков\n• До 6 фото\n"
        f"• Значок ⭐\n• Возврат анкеты\n• Приоритет в поиске\n\n💎 У тебя: {pl} плюшек",
        reply_markup=kb)


async def buy_premium_callback(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    user_id = q.from_user.id
    if data == "buy_plushki":
        cur.execute("SELECT plushki FROM users WHERE user_id = ?", (user_id,))
        pl = cur.fetchone()[0]
        if pl < PREMIUM_FOR_PLUSHKI:
            await q.answer(f"Не хватает {PREMIUM_FOR_PLUSHKI - pl} плюшек", show_alert=True)
            return
        until = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
        cur.execute("UPDATE users SET plushki = plushki - ?, premium_until = ? WHERE user_id = ?",
                    (PREMIUM_FOR_PLUSHKI, until, user_id))
        conn.commit()
        await q.edit_message_text(f"⭐ Premium активирован до {until}")
        return
    days = {"buy_3": 3, "buy_10": 10, "buy_18": 18}.get(data)
    price = {"buy_3": 30, "buy_10": 50, "buy_18": 70}.get(data)
    if not days:
        return
    await context.bot.send_invoice(
        chat_id=user_id, title=f"Premium {days} дней", description="Все плюшки",
        payload=f"premium_{days}", provider_token="", currency="XTR",
        prices=[LabeledPrice(f"Premium {days} дней", price)])


async def precheckout(update, context):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update, context):
    uid = update.effective_user.id
    payload = update.message.successful_payment.invoice_payload
    days = int(payload.split("_")[1]) if "_" in payload else 3
    until = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    cur.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (until, uid))
    conn.commit()
    await update.message.reply_text(f"⭐ Premium активирован до {until}")


async def verify_start(update, context):
    uid = update.effective_user.id
    cur.execute("SELECT verified, verify_attempts FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Сначала /start")
        return ConversationHandler.END
    verified, attempts = row
    if verified:
        await update.message.reply_text("Ты уже верифицирован ✅")
        return ConversationHandler.END
    if attempts >= MAX_VERIFY_ATTEMPTS:
        await update.message.reply_text("Ты исчерпал(а) 15 попыток.")
        return ConversationHandler.END
    code = str(random.randint(1000, 9999))
    tasks = ["покажи два пальца", "покажи большой палец вверх", "покажи ладонь",
             "покажи три пальца", "покажи знак ОК", "помаши рукой"]
    task = random.choice(tasks)
    context.user_data["verify_code"] = code
    context.user_data["verify_task"] = task
    await update.message.reply_text(
        f"Запиши видео-кружок 📹\n\n1. Скажи код: {code}\n2. {task.capitalize()}\n\n"
        f"Попытка {attempts + 1} из {MAX_VERIFY_ATTEMPTS}")
    return VERIFY_VIDEO


async def verify_video(update, context):
    if not update.message.video_note:
        await update.message.reply_text("Нужен именно видео-кружок 📹")
        return VERIFY_VIDEO
    uid = update.effective_user.id
    code = context.user_data.get("verify_code", "????")
    task = context.user_data.get("verify_task", "")
    cur.execute("UPDATE users SET verify_attempts = verify_attempts + 1 WHERE user_id = ?", (uid,))
    conn.commit()
    if ADMIN_ID:
        try:
            cur.execute("SELECT name, age, my_gender, about, photos, city FROM users WHERE user_id = ?", (uid,))
            r = cur.fetchone()
            if r:
                name, age, gender, about, photos, city = r
                info = (f"👤 {name}, {age} ({gender})\n🏙 {city or 'гео'}\n\n{about or '—'}\n\n"
                        f"Код: {code}\nЗадание: {task}\n\n/approve {uid}\n/reject {uid}")
                photos_list = photos.split(",") if photos else []
                if photos_list:
                    await context.bot.send_photo(ADMIN_ID, photos_list[0], caption=info)
                else:
                    await context.bot.send_message(ADMIN_ID, info)
                await context.bot.send_video_note(ADMIN_ID, update.message.video_note.file_id)
        except Exception as e:
            print("verify error:", e)
    await update.message.reply_text(
        "⏳ Заявка отправлена на проверку\n\nОжидай от 1 до 24 часов. Модератор проверит твой кружок 💕",
        reply_markup=main_menu())
    return ConversationHandler.END


async def approve(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("/approve ID")
        return
    cur.execute("UPDATE users SET verified = 1 WHERE user_id = ?", (uid,))
    conn.commit()
    await update.message.reply_text(f"✅ {uid} верифицирован")
    try:
        await context.bot.send_message(uid, "🎉 Поздравляем! Ты прошёл верификацию ✅\n\nТеперь 500 лайков в день и значок ✅.")
    except:
        pass


async def reject(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("/reject ID")
        return
    cur.execute("SELECT verify_attempts FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()
    attempts = row[0] if row else 0
    await update.message.reply_text(f"❌ {uid} отклонён ({attempts}/{MAX_VERIFY_ATTEMPTS})")
    try:
        await context.bot.send_message(uid, f"😔 Верификация не пройдена.\n\nПопыток: {attempts} из {MAX_VERIFY_ATTEMPTS}.\nПопробуй снова — «✅ Верификация».")
    except:
        pass


async def stats(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    cur.execute("SELECT COUNT(*) FROM users"); total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE verified = 1"); ver = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE premium_until IS NOT NULL AND premium_until >= ?", (today(),)); prem = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM likes"); likes = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM likes WHERE valentine = 1"); vals = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM reports"); reps = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE last_active = ?", (today(),)); active = cur.fetchone()[0]
    await update.message.reply_text(
        f"📊 Тинк\n\n👥 Всего: {total}\n✅ Вериф: {ver}\n⭐ Premium: {prem}\n🟢 Активных: {active}\n\n"
        f"❤️ {likes} · 💌 {vals} · 🚨 {reps}")


async def grant_premium(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(context.args[0]); days = int(context.args[1])
    except:
        await update.message.reply_text("/grant_premium ID ДНИ")
        return
    until = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    cur.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (until, uid))
    conn.commit()
    await update.message.reply_text(f"⭐ {uid} → Premium до {until}")
    try:
        await context.bot.send_message(uid, f"⭐ Тебе выдан Premium до {until}!")
    except:
        pass


async def revoke_premium(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("/revoke_premium ID")
        return
    cur.execute("UPDATE users SET premium_until = NULL WHERE user_id = ?", (uid,))
    conn.commit()
    await update.message.reply_text(f"❌ Premium у {uid} забран")


async def give_plushki(update, context):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(context.args[0]); amount = int(context.args[1])
    except:
        await update.message.reply_text("/give_plushki ID СУММА")
        return
    cur.execute("UPDATE users SET plushki = plushki + ? WHERE user_id = ?", (amount, uid))
    conn.commit()
    await update.message.reply_text(f"💎 +{amount} плюшек → {uid}")


async def delete_profile(update, context):
    uid = update.effective_user.id
    cur.execute("DELETE FROM users WHERE user_id = ?", (uid,))
    cur.execute("DELETE FROM likes WHERE from_id = ? OR to_id = ?", (uid, uid))
    conn.commit()
    await update.message.reply_text("Анкета удалена 🗑 /start")


async def back_to_menu(update, context):
    await update.message.reply_text("Главное меню", reply_markup=main_menu())


def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            LANG: [CallbackQueryHandler(get_lang, pattern="^lang_")],
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            MY_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_my_gender)],
            ABOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_about)],
            CITY_OR_GEO: [
                MessageHandler(filters.LOCATION, get_city_or_geo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_city_or_geo)
            ],
            RADIUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_radius)],
            PHOTO: [MessageHandler(filters.PHOTO | filters.VIDEO, get_photo),
                    MessageHandler(filters.Regex("^(Добавить ещё|Готово)$"), photo_choice)],
            PARTNER_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_gender)],
            PARTNER_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_age)],
            VERIFY_VIDEO: [MessageHandler(filters.VIDEO_NOTE, verify_video)],
        },
        fallbacks=[]
    )
    app.add_handler(conv)

    edit_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✏️ Редактировать$"), edit_start)],
        states={
            EDIT_NAME: [
                MessageHandler(filters.Regex("^Имя$"), lambda u, c: u.message.reply_text("Новое имя:")),
                MessageHandler(filters.Regex("^Возраст$"), lambda u, c: u.message.reply_text("Новый возраст:")),
                MessageHandler(filters.Regex("^Описание$"), lambda u, c: u.message.reply_text("Новое описание:")),
                MessageHandler(filters.Regex("^Фото$"), lambda u, c: u.message.reply_text("Отправь фото:")),
                MessageHandler(filters.Regex("^🏙 Город / Гео$"), lambda u, c: u.message.reply_text("Город или гео:")),
                MessageHandler(filters.Regex("^Радиус$"), lambda u, c: u.message.reply_text("Новый радиус:")),
                MessageHandler(filters.Regex("^Пол$"), lambda u, c: u.message.reply_text("М или Ж:")),
                MessageHandler(filters.Regex("^🔙 Назад$"), back_to_menu),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_name),
            ],
            EDIT_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_age)],
            EDIT_ABOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_about)],
            EDIT_PHOTO: [MessageHandler(filters.PHOTO | filters.VIDEO, save_photo),
                         MessageHandler(filters.Regex("^(Добавить ещё|Готово)$"), save_photo_choice)],
            EDIT_CITY: [MessageHandler(filters.LOCATION, save_city),
                        MessageHandler(filters.TEXT & ~filters.COMMAND, save_city)],
            EDIT_RADIUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_radius)],
            EDIT_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_gender)],
        },
        fallbacks=[]
    )
    app.add_handler(edit_conv)

    song_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🎵 Песня$"), set_song)],
        states={EDIT_SONG: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_song)]},
        fallbacks=[]
    )
    app.add_handler(song_conv)

    val_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💌 Валентинка$"), anon_valentine)],
        states={ANON_VAL: [MessageHandler(filters.TEXT & ~filters.COMMAND, send_valentine)]},
        fallbacks=[]
    )
    app.add_handler(val_conv)

    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("grant_premium", grant_premium))
    app.add_handler(CommandHandler("revoke_premium", revoke_premium))
    app.add_handler(CommandHandler("give_plushki", give_plushki))
    app.add_handler(CommandHandler("roulette_stop", roulette_stop))
    app.add_handler(MessageHandler(filters.Regex("^👀 Искать$"), find))
    app.add_handler(MessageHandler(filters.Regex("^❤️ Лайки$"), my_likes))
    app.add_handler(MessageHandler(filters.Regex("^💖 Мэтчи$"), my_matches))
    app.add_handler(MessageHandler(filters.Regex("^✏️ Моя анкета$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex("^👥 Пригласи друга$"), invite))
    app.add_handler(MessageHandler(filters.Regex("^⭐ Premium$"), premium))
    app.add_handler(MessageHandler(filters.Regex("^🎁 Бонус$"), bonus))
    app.add_handler(MessageHandler(filters.Regex("^🎤 Рулетка$"), roulette_start))
    app.add_handler(MessageHandler(filters.Regex("^✅ Верификация$"), verify_start))
    app.add_handler(MessageHandler(filters.Regex("^🗑 Удалить анкету$"), delete_profile))
    app.add_handler(MessageHandler(filters.Regex("^🔙 В меню$"), back_to_menu))
    app.add_handler(CallbackQueryHandler(like_handler, pattern="^(check_sub|skip|hide_|report_|like_|val_)"))
    app.add_handler(CallbackQueryHandler(buy_premium_callback, pattern="^(buy_3|buy_10|buy_18|buy_plushki)$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.VOICE | filters.TEXT, roulette_forward))
    app.run_polling()


if __name__ == "__main__":
    main()
