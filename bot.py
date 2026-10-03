import os
import sqlite3
import datetime
import random
import math
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
CHANNEL = "@niwzex"
MAX_VERIFY_ATTEMPTS = 15

NAME, AGE, MY_GENDER, ABOUT, CITY_OR_GEO, RADIUS, PHOTO, PARTNER_GENDER, PARTNER_AGE = range(9)
VERIFY_VIDEO = 100
EDIT_CHOICE = 200
EDIT_NAME, EDIT_AGE, EDIT_ABOUT, EDIT_CITY, EDIT_RADIUS, EDIT_GENDER = range(201, 207)
EDIT_PHOTO = 300

conn = sqlite3.connect("dating.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT, name TEXT, age INTEGER, my_gender TEXT, about TEXT,
    city TEXT, lat REAL, lon REAL, radius INTEGER DEFAULT 50,
    photos TEXT, partner_gender TEXT, partner_age_min INTEGER, partner_age_max INTEGER,
    verified INTEGER DEFAULT 0, premium_until TEXT,
    likes_today INTEGER DEFAULT 0, likes_date TEXT,
    verify_attempts INTEGER DEFAULT 0, super_likes_today INTEGER DEFAULT 0,
    last_shown INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, last_active TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS likes (
    from_id INTEGER, to_id INTEGER, valentine INTEGER DEFAULT 0, super INTEGER DEFAULT 0
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS reports (
    from_id INTEGER, to_id INTEGER, reason TEXT, date TEXT
)""")
conn.commit()


def today():
    return datetime.date.today().isoformat()


def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon/2)**2
    return R * 2 * math.asin(math.sqrt(a))


def main_menu():
    return ReplyKeyboardMarkup([
        ["👀 Искать", "💗 Лайки"],
        ["💖 Мэтчи", "✏️ Моя анкета"],
        ["⭐ Premium", "✅ Верификация"],
        ["🗑 Удалить анкету"]
    ], resize_keyboard=True)


def profile_menu():
    return ReplyKeyboardMarkup([
        ["✏️ Редактировать"],
        ["👁 Кто лайкнул", "💌 Валентинки"],
        ["↩️ Вернуть анкету"],
        ["🔙 В меню"]
    ], resize_keyboard=True)


def edit_menu():
    return ReplyKeyboardMarkup([
        ["Имя", "Возраст"],
        ["Описание", "Фото"],
        ["🏙 Город / Гео"],
        ["Радиус", "Пол"],
        ["🔙 Назад"]
    ], resize_keyboard=True)


def is_premium(user_id):
    if user_id == ADMIN_ID:
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
    limit = 500 if verified else 100
    if likes_today >= limit:
        return False
    cur.execute("UPDATE users SET likes_today = likes_today + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    return True


def check_super_limit(user_id):
    if not is_premium(user_id):
        return False
    cur.execute("SELECT super_likes_today, likes_date FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        return False
    super_today, likes_date = row
    if likes_date != today():
        cur.execute("UPDATE users SET super_likes_today = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        super_today = 0
    if super_today >= 5:
        return False
    cur.execute("UPDATE users SET super_likes_today = super_likes_today + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    return True


async def check_subscription(update, context):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
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


# ---------- Регистрация ----------
async def start(update, context):
    if not await check_subscription(update, context):
        await sub_gate(update, context)
        return ConversationHandler.END
    user_id = update.effective_user.id
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cur.fetchone():
        cur.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (today(), user_id))
        conn.commit()
        await update.message.reply_text("Ты уже зарегистрирован(а) 💕", reply_markup=main_menu())
        return ConversationHandler.END
    await update.message.reply_text("Привет! Давай создадим анкету 💕\n\nКак тебя зовут?")
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
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Отправить гео", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await update.message.reply_text(
        "Напиши свой город **или** отправь гео 📍\n\n(Если отправишь гео — город можно не писать)",
        reply_markup=kb, parse_mode="Markdown"
    )
    return CITY_OR_GEO


async def get_city_or_geo(update, context):
    if update.message.location:
        context.user_data["lat"] = update.message.location.latitude
        context.user_data["lon"] = update.message.location.longitude
        context.user_data["city"] = ""
    else:
        context.user_data["city"] = update.message.text.strip()
        context.user_data["lat"] = None
        context.user_data["lon"] = None
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
    cur.execute("""INSERT OR REPLACE INTO users
        (user_id, username, name, age, my_gender, about, city, lat, lon, radius,
         photos, partner_gender, partner_age_min, partner_age_max, verified,
         premium_until, likes_today, likes_date, verify_attempts, super_likes_today,
         last_shown, hidden, last_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
        user.id, user.username or "", context.user_data["name"], context.user_data["age"],
        context.user_data["my_gender"], context.user_data["about"],
        context.user_data["city"], context.user_data.get("lat"), context.user_data.get("lon"),
        context.user_data["radius"],
        ",".join(context.user_data["photos"]),
        context.user_data["partner_gender"], amin, amax,
        0, None, 0, today(), 0, 0, 0, 0, today()
    ))
    conn.commit()
    await update.message.reply_text("Анкета готова! 💕", reply_markup=main_menu())
    return ConversationHandler.END


# ---------- Поиск ----------
async def find(update, context):
    user_id = update.effective_user.id
    cur.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (today(), user_id))
    conn.commit()
    if not check_like_limit(user_id):
        await update.message.reply_text("Лимит лайков исчерпан.\n✅ Верификация — 500/день\n⭐ Premium — безлимит")
        return
    cur.execute("SELECT city, lat, lon, radius FROM users WHERE user_id = ?", (user_id,))
    me = cur.fetchone()
    my_city, my_lat, my_lon, my_radius = me if me else (None, None, None, 50)

    cur.execute("""SELECT user_id, name, age, about, photos, my_gender, city, lat, lon
                   FROM users WHERE user_id != ? AND user_id != ?
                   AND user_id NOT IN (SELECT to_id FROM likes WHERE from_id = ?)""",
                (user_id, ADMIN_ID, user_id))
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("Анкеты закончились 😔")
        return

    candidates = []
    for r in rows:
        uid, name, age, about, photos, gender, city, lat, lon = r
        dist = None
        match = False
        if my_lat and my_lon and lat and lon:
            dist = haversine(my_lat, my_lon, lat, lon)
            if dist <= my_radius:
                match = True
        elif my_city and city and my_city == city:
            match = True
        if match:
            candidates.append((dist if dist is not None else 9999, uid, name, age, about, photos, gender, city, dist))

    if not candidates:
        await update.message.reply_text("В твоём городе/радиусе пока никого нет 😔")
        return

    candidates.sort(key=lambda x: x[0])
    dist, uid, name, age, about, photos, gender, city, real_dist = candidates[0]
    cur.execute("UPDATE users SET last_shown = ? WHERE user_id = ?", (uid, user_id))
    conn.commit()
    badge = " ⭐" if is_premium(uid) else ""
    if real_dist is not None:
        dist_text = f"\n📍 {round(real_dist, 1)} км"
    elif city:
        dist_text = f"\n🏙 {city}"
    else:
        dist_text = ""
    text = f"👤 {name}, {age} ({gender}){badge}{dist_text}\n\n{about or '—'}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Лайк", callback_data=f"like_{uid}"),
         InlineKeyboardButton("💌 Валентинка", callback_data=f"val_{uid}")],
        [InlineKeyboardButton("⭐ Супер-лайк", callback_data=f"super_{uid}")],
        [InlineKeyboardButton("👎 Пропустить", callback_data="skip"),
         InlineKeyboardButton("🚨 Жалоба", callback_data=f"report_{uid}")]
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

    if data.startswith("report_"):
        target = int(data.split("_")[1])
        cur.execute("INSERT INTO reports VALUES (?, ?, ?, ?)", (me, target, "жалоба", today()))
        conn.commit()
        await q.edit_message_caption("Жалоба отправлена 🚨")
        if ADMIN_ID:
            try:
                await context.bot.send_message(ADMIN_ID, f"🚨 Жалоба на {target} от {me}")
            except:
                pass
        return

    if data.startswith("super_"):
        if not check_super_limit(me):
            await q.answer("Супер-лайк доступен только с Premium (5/день)", show_alert=True)
            return
        target = int(data.split("_")[1])
        cur.execute("INSERT INTO likes VALUES (?, ?, 0, 1)", (me, target))
        conn.commit()
        cur.execute("SELECT 1 FROM likes WHERE from_id = ? AND to_id = ?", (target, me))
        if cur.fetchone():
            cur.execute("SELECT username FROM users WHERE user_id = ?", (target,))
            uname = cur.fetchone()[0]
            await q.edit_message_caption(f"⭐ Супер-лайк! 💖 Мэтч! @{uname or 'скрыт'}")
            try:
                await context.bot.send_message(target, "⭐ Тебя супер-лайкнули! Загляни в бота.")
            except:
                pass
        else:
            await q.edit_message_caption("⭐ Супер-лайк отправлен!")
        return

    if data.startswith("like_") or data.startswith("val_"):
        target = int(data.split("_")[1])
        val = 1 if data.startswith("val_") else 0
        cur.execute("INSERT INTO likes VALUES (?, ?, ?, 0)", (me, target, val))
        conn.commit()
        cur.execute("SELECT 1 FROM likes WHERE from_id = ? AND to_id = ?", (target, me))
        if cur.fetchone():
            cur.execute("SELECT username FROM users WHERE user_id = ?", (target,))
            uname = cur.fetchone()[0]
            await q.edit_message_caption(f"💖 Мэтч! @{uname or 'скрыт'}")
        else:
            await q.edit_message_caption("Отправлено 💕")


# ---------- Моя анкета ----------
async def my_profile(update, context):
    user_id = update.effective_user.id
    cur.execute("""SELECT name, age, my_gender, about, photos, verified, city, radius, lat, lon
                   FROM users WHERE user_id = ?""", (user_id,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Анкеты нет. /start")
        return
    name, age, gender, about, photos, verified, city, radius, lat, lon = row
    status = []
    if verified:
        status.append("✅")
    if is_premium(user_id):
        status.append("⭐")
    loc = ""
    if lat and lon:
        loc = "📍 по гео"
    elif city:
        loc = f"🏙 {city}"
    text = f"👤 {name}, {age} ({gender}) {' '.join(status)}\n{loc} · 📏 {radius} км\n\n{about or '—'}"
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
    return EDIT_CHOICE


async def edit_choice(update, context):
    t = update.message.text
    if t == "🔙 Назад":
        await my_profile(update, context)
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
        await update.message.reply_text("Отправь новые фото (старые заменятся)")
        context.user_data["edit_photos"] = []
        return EDIT_PHOTO
    if t == "🏙 Город / Гео":
        kb = ReplyKeyboardMarkup(
            [[KeyboardButton("📍 Отправить гео", request_location=True)], ["🔙 Назад"]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await update.message.reply_text("Напиши город или отправь гео 📍", reply_markup=kb)
        return EDIT_CITY
    if t == "Радиус":
        await update.message.reply_text("Новый радиус (5–100):",
            reply_markup=ReplyKeyboardMarkup([["5", "10", "25"], ["50", "75", "100"]], resize_keyboard=True))
        return EDIT_RADIUS
    if t == "Пол":
        await update.message.reply_text("Новый пол:", reply_markup=ReplyKeyboardMarkup([["М", "Ж"]], resize_keyboard=True))
        return EDIT_GENDER
    await update.message.reply_text("Выбери из меню")
    return EDIT_CHOICE


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


async def save_city_or_geo(update, context):
    if update.message.location:
        cur.execute("UPDATE users SET lat = ?, lon = ?, city = '' WHERE user_id = ?",
                    (update.message.location.latitude, update.message.location.longitude,
                     update.effective_user.id))
    else:
        cur.execute("UPDATE users SET city = ?, lat = NULL, lon = NULL WHERE user_id = ?",
                    (update.message.text.strip(), update.effective_user.id))
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


async def save_edit_photo(update, context):
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
        cur.execute("UPDATE users SET photos = ? WHERE user_id = ?",
                    (",".join(photos), update.effective_user.id))
        conn.commit()
        await update.message.reply_text("✅ Фото обновлены", reply_markup=main_menu())
        return ConversationHandler.END
    await update.message.reply_text(f"({len(photos)}/{limit}) Ещё или Готово?",
        reply_markup=ReplyKeyboardMarkup([["Добавить ещё", "Готово"]], resize_keyboard=True))
    return EDIT_PHOTO


async def edit_photo_done(update, context):
    if update.message.text == "Готово":
        photos = context.user_data.get("edit_photos", [])
        cur.execute("UPDATE users SET photos = ? WHERE user_id = ?",
                    (",".join(photos), update.effective_user.id))
        conn.commit()
        await update.message.reply_text("✅ Фото обновлены", reply_markup=main_menu())
        return ConversationHandler.END
    await update.message.reply_text("Отправь ещё фото")
    return EDIT_PHOTO


# ---------- Остальное ----------
async def who_liked(update, context):
    user_id = update.effective_user.id
    cur.execute("""SELECT u.name, u.username, l.valentine, l.super FROM likes l
                   JOIN users u ON u.user_id = l.from_id WHERE l.to_id = ?""", (user_id,))
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("Тебя пока никто не лайкнул", reply_markup=profile_menu())
        return
    lines = []
    for n, u, v, s in rows:
        mark = "💌" if v else ("⭐" if s else "❤️")
        lines.append(f"{mark} {n} — @{u or 'скрыт'}")
    await update.message.reply_text("👁 Кто тебя лайкнул:\n" + "\n".join(lines), reply_markup=profile_menu())


async def my_valentines(update, context):
    user_id = update.effective_user.id
    cur.execute("""SELECT u.name, u.username FROM likes l
                   JOIN users u ON u.user_id = l.from_id
                   WHERE l.to_id = ? AND l.valentine = 1""", (user_id,))
    rows = cur.fetchall()
    text = "\n".join([f"{n} — @{u or 'скрыт'}" for n, u in rows]) if rows else "Пусто"
    await update.message.reply_text("💌 Валентинки:\n" + text, reply_markup=profile_menu())


async def back_anketa(update, context):
    if not is_premium(update.effective_user.id):
        await update.message.reply_text("Только с ⭐ Premium", reply_markup=profile_menu())
        return
    user_id = update.effective_user.id
    cur.execute("SELECT last_shown FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        await update.message.reply_text("Нет анкеты для возврата", reply_markup=profile_menu())
        return
    last_id = row[0]
    cur.execute("SELECT user_id, name, age, about, photos, my_gender FROM users WHERE user_id = ?", (last_id,))
    r = cur.fetchone()
    if not r:
        await update.message.reply_text("Анкета недоступна", reply_markup=profile_menu())
        return
    uid, name, age, about, photos, gender = r
    text = f"👤 {name}, {age} ({gender})\n\n{about or '—'}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Лайк", callback_data=f"like_{uid}")],
        [InlineKeyboardButton("⭐ Супер-лайк", callback_data=f"super_{uid}")]
    ])
    photos_list = photos.split(",") if photos else []
    if photos_list:
        await update.message.reply_photo(photos_list[0], caption=text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)


async def my_likes(update, context):
    user_id = update.effective_user.id
    cur.execute("""SELECT u.name, u.username FROM likes l
                   JOIN users u ON u.user_id = l.to_id WHERE l.from_id = ?""", (user_id,))
    rows = cur.fetchall()
    text = "\n".join([f"{n} — @{u or 'скрыт'}" for n, u in rows]) if rows else "Пусто"
    await update.message.reply_text("💗 Лайки:\n" + text)


async def my_matches(update, context):
    user_id = update.effective_user.id
    cur.execute("""SELECT u.name, u.username FROM likes l1
                   JOIN likes l2 ON l1.to_id = l2.from_id AND l1.from_id = l2.to_id
                   JOIN users u ON u.user_id = l1.to_id WHERE l1.from_id = ?""", (user_id,))
    rows = cur.fetchall()
    text = "\n".join([f"{n} — @{u or 'скрыт'}" for n, u in rows]) if rows else "Пусто"
    await update.message.reply_text("💖 Мэтчи:\n" + text)


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
        await update.message.reply_text("Нужен видео-кружок")
        return VERIFY_VIDEO
    uid = update.effective_user.id
    code = context.user_data.get("verify_code", "????")
    task = context.user_data.get("verify_task", "")
    cur.execute("UPDATE users SET verify_attempts = verify_attempts + 1 WHERE user_id = ?", (uid,))
    conn.commit()
    if ADMIN_ID:
        try:
            await context.bot.send_video_note(ADMIN_ID, update.message.video_note.file_id)
            await context.bot.send_message(ADMIN_ID,
                f"Заявка от {uid}\nКод: {code}\nЗадание: {task}\n\n/approve {uid}\n/reject {uid}")
        except:
            pass
    await update.message.reply_text("Заявка отправлена ✅", reply_markup=main_menu())
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
        await context.bot.send_message(uid, "✅ Верификация пройдена!")
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
        await context.bot.send_message(uid, f"❌ Верификация не пройдена ({attempts}/{MAX_VERIFY_ATTEMPTS})")
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
    cur.execute("SELECT COUNT(*) FROM likes WHERE super = 1"); supers = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM reports"); reps = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE last_active = ?", (today(),)); active = cur.fetchone()[0]
    await update.message.reply_text(
        f"📊 Тинк\n\n👥 Всего: {total}\n✅ Вериф: {ver}\n⭐ Premium: {prem}\n🟢 Активных: {active}\n\n"
        f"❤️ {likes} · 💌 {vals} · ⭐ {supers} · 🚨 {reps}")


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


async def premium(update, context):
    if is_premium(update.effective_user.id):
        if update.effective_user.id == ADMIN_ID:
            await update.message.reply_text("⭐ У тебя Premium навсегда")
            return
        cur.execute("SELECT premium_until FROM users WHERE user_id = ?", (update.effective_user.id,))
        until = cur.fetchone()[0]
        await update.message.reply_text(f"⭐ Premium активен до {until}")
        return
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("⭐ Купить (20 звёзд)", callback_data="buy_premium")]])
    await update.message.reply_text(
        "⭐ Premium на 3 дня — 20 звёзд\n\n• Супер-лайк 5/день\n• Безлимит лайков\n"
        "• До 6 фото\n• Значок ⭐\n• Возврат анкеты\n• Приоритет в поиске",
        reply_markup=kb)


async def buy_premium(update, context):
    q = update.callback_query
    await q.answer()
    await context.bot.send_invoice(
        chat_id=q.from_user.id, title="Premium 3 дня", description="Все плюшки",
        payload="premium_3d", provider_token="", currency="XTR",
        prices=[LabeledPrice("Premium", 20)])


async def precheckout(update, context):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update, context):
    uid = update.effective_user.id
    until = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
    cur.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (until, uid))
    conn.commit()
    await update.message.reply_text("⭐ Premium активирован до " + until)


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
            EDIT_CHOICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_choice)],
            EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_name)],
            EDIT_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_age)],
            EDIT_ABOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_about)],
            EDIT_CITY: [
                MessageHandler(filters.LOCATION, save_city_or_geo),
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_city_or_geo)
            ],
            EDIT_RADIUS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_radius)],
            EDIT_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_gender)],
            EDIT_PHOTO: [MessageHandler(filters.PHOTO | filters.VIDEO, save_edit_photo),
                         MessageHandler(filters.Regex("^(Добавить ещё|Готово)$"), edit_photo_done)],
        },
        fallbacks=[MessageHandler(filters.Regex("^🔙 В меню$"), back_to_menu)]
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("grant_premium", grant_premium))
    app.add_handler(CommandHandler("revoke_premium", revoke_premium))
    app.add_handler(MessageHandler(filters.Regex("^👀 Искать$"), find))
    app.add_handler(MessageHandler(filters.Regex("^💗 Лайки$"), my_likes))
    app.add_handler(MessageHandler(filters.Regex("^💖 Мэтчи$"), my_matches))
    app.add_handler(MessageHandler(filters.Regex("^✏️ Моя анкета$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex("^✏️ Редактировать$"), edit_start))
    app.add_handler(MessageHandler(filters.Regex("^👁 Кто лайкнул$"), who_liked))
    app.add_handler(MessageHandler(filters.Regex("^💌 Валентинки$"), my_valentines))
    app.add_handler(MessageHandler(filters.Regex("^↩️ Вернуть анкету$"), back_anketa))
    app.add_handler(MessageHandler(filters.Regex("^⭐ Premium$"), premium))
    app.add_handler(MessageHandler(filters.Regex("^✅ Верификация$"), verify_start))
    app.add_handler(MessageHandler(filters.Regex("^🗑 Удалить анкету$"), delete_profile))
    app.add_handler(CallbackQueryHandler(like_handler))
    app.add_handler(CallbackQueryHandler(buy_premium, pattern="^buy_premium$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.run_polling()


if __name__ == "__main__":
    main()
