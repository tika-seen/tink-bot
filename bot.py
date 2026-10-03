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

NAME, AGE, MY_GENDER, ABOUT, CITY, GEO, RADIUS, PHOTO, PARTNER_GENDER, PARTNER_AGE = range(10)
VERIFY_VIDEO = 100

conn = sqlite3.connect("dating.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    age INTEGER,
    my_gender TEXT,
    about TEXT,
    city TEXT,
    lat REAL,
    lon REAL,
    radius INTEGER DEFAULT 50,
    photos TEXT,
    partner_gender TEXT,
    partner_age_min INTEGER,
    partner_age_max INTEGER,
    verified INTEGER DEFAULT 0,
    premium_until TEXT,
    likes_today INTEGER DEFAULT 0,
    likes_date TEXT,
    verify_attempts INTEGER DEFAULT 0,
    super_likes_today INTEGER DEFAULT 0,
    last_shown INTEGER DEFAULT 0,
    hidden INTEGER DEFAULT 0,
    last_active TEXT
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
        ["💖 Мэтчи", "💌 Валентинки"],
        ["👁 Кто лайкнул", "✏️ Моя анкета"],
        ["⭐ Premium", "✅ Верификация"],
        ["📍 Радиус поиска", "↩️ Вернуть анкету"],
        ["🗑 Удалить анкету"]
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


async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id == ADMIN_ID:
        return True
    try:
        member = await context.bot.get_chat_member(CHANNEL, user_id)
        return member.status in ["member", "administrator", "creator"]
    except:
        return False


async def sub_gate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Подписаться", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
        [InlineKeyboardButton("✅ Проверить", callback_data="check_sub")]
    ])
    await update.message.reply_text("Чтобы пользоваться ботом, подпишись на наш канал 💕", reply_markup=kb)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Сколько тебе лет? (15–99)")
    return AGE


async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def get_my_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    g = update.message.text
    if g not in ["М", "Ж"]:
        await update.message.reply_text("Выбери М или Ж")
        return MY_GENDER
    context.user_data["my_gender"] = g
    await update.message.reply_text("Расскажи о себе или нажми «Пропустить»",
        reply_markup=ReplyKeyboardMarkup([["Пропустить"]], resize_keyboard=True))
    return ABOUT


async def get_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["about"] = "" if update.message.text == "Пропустить" else update.message.text
    await update.message.reply_text("Напиши свой город:")
    return CITY


async def get_city(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["city"] = update.message.text.strip()
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Отправить гео", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await update.message.reply_text(
        "Отправь свою геолокацию (по желанию) — так тебя увидят те, кто ближе.\n"
        "Или нажми «Пропустить».",
        reply_markup=ReplyKeyboardMarkup([["Пропустить"]], resize_keyboard=True)
    )
    return GEO


async def get_geo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.location:
        context.user_data["lat"] = update.message.location.latitude
        context.user_data["lon"] = update.message.location.longitude
    else:
        context.user_data["lat"] = None
        context.user_data["lon"] = None
    await update.message.reply_text(
        "Радиус поиска в км (5–100). Напиши число:",
        reply_markup=ReplyKeyboardMarkup([["5", "10", "25"], ["50", "75", "100"]], resize_keyboard=True)
    )
    return RADIUS


async def get_radius(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def photo_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Готово":
        await update.message.reply_text("Пол партнёра:",
            reply_markup=ReplyKeyboardMarkup([["М", "Ж", "Всё равно"]], resize_keyboard=True))
        return PARTNER_GENDER
    await update.message.reply_text("Отправь ещё фото или видео")
    return PHOTO


async def get_partner_gender(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["partner_gender"] = update.message.text
    await update.message.reply_text("Возраст партнёра от и до (например: 15-25)")
    return PARTNER_AGE


async def get_partner_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def find(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        if city != my_city:
            continue
        dist = None
        if my_lat and my_lon and lat and lon:
            dist = haversine(my_lat, my_lon, lat, lon)
            if dist > my_radius:
                continue
        candidates.append((dist if dist is not None else 9999, uid, name, age, about, photos, gender, city, dist))

    if not candidates:
        await update.message.reply_text("В твоём городе/радиусе пока никого нет 😔")
        return

    candidates.sort(key=lambda x: x[0])
    dist, uid, name, age, about, photos, gender, city, real_dist = candidates[0]
    cur.execute("UPDATE users SET last_shown = ? WHERE user_id = ?", (uid, user_id))
    conn.commit()
    badge = " ⭐" if is_premium(uid) else ""
    dist_text = f"\n📍 {round(real_dist, 1)} км" if real_dist is not None else f"\n🏙 {city}"
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


async def like_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def my_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("""SELECT name, age, my_gender, about, photos, verified, city, radius
                   FROM users WHERE user_id = ?""", (user_id,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Анкеты нет. /start")
        return
    name, age, gender, about, photos, verified, city, radius = row
    status = []
    if verified:
        status.append("✅")
    if is_premium(user_id):
        status.append("⭐")
    text = f"👤 {name}, {age} ({gender}) {' '.join(status)}\n🏙 {city} · 📍 {radius} км\n\n{about or '—'}"
    photos_list = photos.split(",") if photos else []
    if photos_list:
        for i, fid in enumerate(photos_list):
            if i == 0:
                await update.message.reply_photo(fid, caption=text)
            else:
                await update.message.reply_photo(fid)
    else:
        await update.message.reply_text(text)


async def who_liked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("""SELECT u.name, u.username, l.valentine, l.super FROM likes l
                   JOIN users u ON u.user_id = l.from_id WHERE l.to_id = ?""", (user_id,))
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("Тебя пока никто не лайкнул")
        return
    lines = []
    for n, u, v, s in rows:
        mark = "💌" if v else ("⭐" if s else "❤️")
        lines.append(f"{mark} {n} — @{u or 'скрыт'}")
    await update.message.reply_text("👁 Кто тебя лайкнул:\n" + "\n".join(lines))


async def my_likes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("""SELECT u.name, u.username FROM likes l
                   JOIN users u ON u.user_id = l.to_id WHERE l.from_id = ?""", (user_id,))
    rows = cur.fetchall()
    text = "\n".join([f"{n} — @{u or 'скрыт'}" for n, u in rows]) if rows else "Пусто"
    await update.message.reply_text("💗 Лайки:\n" + text)


async def my_matches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("""SELECT u.name, u.username FROM likes l1
                   JOIN likes l2 ON l1.to_id = l2.from_id AND l1.from_id = l2.to_id
                   JOIN users u ON u.user_id = l1.to_id WHERE l1.from_id = ?""", (user_id,))
    rows = cur.fetchall()
    text = "\n".join([f"{n} — @{u or 'скрыт'}" for n, u in rows]) if rows else "Пусто"
    await update.message.reply_text("💖 Мэтчи:\n" + text)


async def my_valentines(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("""SELECT u.name, u.username FROM likes l
                   JOIN users u ON u.user_id = l.from_id
                   WHERE l.to_id = ? AND l.valentine = 1""", (user_id,))
    rows = cur.fetchall()
    text = "\n".join([f"{n} — @{u or 'скрыт'}" for n, u in rows]) if rows else "Пусто"
    await update.message.reply_text("💌 Валентинки:\n" + text)


async def change_radius(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Выбери новый радиус (км):",
        reply_markup=ReplyKeyboardMarkup([["5", "10", "25"], ["50", "75", "100"]], resize_keyboard=True))
    return RADIUS + 1000


async def set_radius(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        r = int(update.message.text)
        if r < 5 or r > 100:
            raise ValueError
    except:
        await update.message.reply_text("Число от 5 до 100")
        return RADIUS + 1000
    cur.execute("UPDATE users SET radius = ? WHERE user_id = ?", (r, update.effective_user.id))
    conn.commit()
    await update.message.reply_text(f"✅ Радиус изменён на {r} км", reply_markup=main_menu())
    return ConversationHandler.END


async def back_anketa(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_premium(update.effective_user.id):
        await update.message.reply_text("Возврат анкеты доступен только с ⭐ Premium")
        return
    user_id = update.effective_user.id
    cur.execute("SELECT last_shown FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        await update.message.reply_text("Нет анкеты для возврата")
        return
    last_id = row[0]
    cur.execute("SELECT user_id, name, age, about, photos, my_gender FROM users WHERE user_id = ?", (last_id,))
    r = cur.fetchone()
    if not r:
        await update.message.reply_text("Анкета недоступна")
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


async def verify_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cur.execute("SELECT verified, verify_attempts FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Сначала создай анкету /start")
        return ConversationHandler.END
    verified, attempts = row
    if verified:
        await update.message.reply_text("Ты уже верифицирован ✅")
        return ConversationHandler.END
    if attempts >= MAX_VERIFY_ATTEMPTS:
        await update.message.reply_text("Ты исчерпал(а) 15 попыток верификации.")
        return ConversationHandler.END
    code = str(random.randint(1000, 9999))
    tasks = ["покажи два пальца", "покажи большой палец вверх", "покажи ладонь",
             "покажи три пальца", "покажи знак ОК", "помаши рукой"]
    task = random.choice(tasks)
    context.user_data["verify_code"] = code
    context.user_data["verify_task"] = task
    await update.message.reply_text(
        f"Запиши видео-кружок 📹\n\n1. Скажи код: {code}\n2. {task.capitalize()}\n\n"
        f"Попытка {attempts + 1} из {MAX_VERIFY_ATTEMPTS}"
    )
    return VERIFY_VIDEO


async def verify_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.video_note:
        await update.message.reply_text("Нужен именно видео-кружок (Video Note)")
        return VERIFY_VIDEO
    uid = update.effective_user.id
    code = context.user_data.get("verify_code", "????")
    task = context.user_data.get("verify_task", "")
    cur.execute("UPDATE users SET verify_attempts = verify_attempts + 1 WHERE user_id = ?", (uid,))
    conn.commit()
    if ADMIN_ID:
        try:
            await context.bot.send_video_note(ADMIN_ID, update.message.video_note.file_id)
            await context.bot.send_message(
                ADMIN_ID,
                f"Заявка на верификацию от {uid}\nКод: {code}\nЗадание: {task}\n\n"
                f"/approve {uid}\n/reject {uid}"
            )
        except:
            await update.message.reply_text("Ошибка отправки модератору.")
            return ConversationHandler.END
    await update.message.reply_text("Заявка отправлена ✅ Ожидай проверки.", reply_markup=main_menu())
    return ConversationHandler.END


async def approve(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("Использование: /approve USER_ID")
        return
    cur.execute("UPDATE users SET verified = 1 WHERE user_id = ?", (uid,))
    conn.commit()
    await update.message.reply_text(f"✅ {uid} верифицирован")
    try:
        await context.bot.send_message(uid, "✅ Верификация пройдена! Теперь 500 лайков в день.")
    except:
        pass


async def reject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("Использование: /reject USER_ID")
        return
    cur.execute("SELECT verify_attempts FROM users WHERE user_id = ?", (uid,))
    row = cur.fetchone()
    attempts = row[0] if row else 0
    await update.message.reply_text(f"❌ {uid} отклонён ({attempts}/{MAX_VERIFY_ATTEMPTS})")
    try:
        await context.bot.send_message(uid, f"❌ Верификация не пройдена. Попыток: {attempts}/{MAX_VERIFY_ATTEMPTS}")
    except:
        pass


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE verified = 1")
    ver = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE premium_until IS NOT NULL AND premium_until >= ?", (today(),))
    prem = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM likes")
    likes = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM likes WHERE valentine = 1")
    vals = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM likes WHERE super = 1")
    supers = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM reports")
    reps = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users WHERE last_active = ?", (today(),))
    active = cur.fetchone()[0]
    text = (
        f"📊 Статистика Тинк\n\n"
        f"👥 Всего: {total}\n"
        f"✅ Верифицированных: {ver}\n"
        f"⭐ Premium: {prem}\n"
        f"🟢 Активных сегодня: {active}\n\n"
        f"❤️ Лайков: {likes}\n"
        f"💌 Валентинок: {vals}\n"
        f"⭐ Супер-лайков: {supers}\n"
        f"🚨 Жалоб: {reps}"
    )
    await update.message.reply_text(text)


async def grant_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(context.args[0])
        days = int(context.args[1])
    except:
        await update.message.reply_text("Использование: /grant_premium USER_ID ДНИ")
        return
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (uid,))
    if not cur.fetchone():
        await update.message.reply_text("Такого пользователя нет в базе")
        return
    until = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    cur.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (until, uid))
    conn.commit()
    await update.message.reply_text(f"⭐ {uid} получил Premium до {until}")
    try:
        await context.bot.send_message(uid, f"⭐ Тебе выдан Premium до {until}!")
    except:
        pass


async def revoke_premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    try:
        uid = int(context.args[0])
    except:
        await update.message.reply_text("Использование: /revoke_premium USER_ID")
        return
    cur.execute("UPDATE users SET premium_until = NULL WHERE user_id = ?", (uid,))
    conn.commit()
    await update.message.reply_text(f"❌ Premium у {uid} забран")


async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if is_premium(update.effective_user.id):
        if update.effective_user.id == ADMIN_ID:
            await update.message.reply_text("⭐ У тебя Premium навсегда (создатель)")
            return
        cur.execute("SELECT premium_until FROM users WHERE user_id = ?", (update.effective_user.id,))
        until = cur.fetchone()[0]
        await update.message.reply_text(f"⭐ Premium активен до {until}")
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("⭐ Купить Premium (20 звёзд)", callback_data="buy_premium")]
    ])
    await update.message.reply_text(
        "⭐ Premium на 3 дня — 20 звёзд\n\n"
        "Что даёт:\n"
        "• Супер-лайк (5/день)\n"
        "• Безлимитные лайки\n"
        "• До 6 фото\n"
        "• Значок ⭐ в анкете\n"
        "• Возврат анкеты\n"
        "• Приоритет в поиске\n"
        "• Скрыть онлайн",
        reply_markup=kb
    )


async def buy_premium(update: Update, context: Context
