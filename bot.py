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
MAX_BDAY_CHANGES = 5

NAME, AGE, MY_GENDER, ABOUT, BDAY, CITY_OR_GEO, RADIUS, PHOTO, PARTNER_GENDER, PARTNER_AGE = range(10)
VERIFY_VIDEO = 100
EDIT_VALUE = 300

conn = sqlite3.connect("dating.db", check_same_thread=False)
cur = conn.cursor()

cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT, name TEXT, age INTEGER, my_gender TEXT, about TEXT,
    birthday TEXT DEFAULT '', bday_changes INTEGER DEFAULT 0, bday_gift_year INTEGER DEFAULT 0,
    city TEXT, lat REAL, lon REAL, radius INTEGER DEFAULT 50,
    photos TEXT, partner_gender TEXT, partner_age_min INTEGER, partner_age_max INTEGER,
    verified INTEGER DEFAULT 0, premium_until TEXT,
    likes_today INTEGER DEFAULT 0, likes_date TEXT,
    verify_attempts INTEGER DEFAULT 0, super_likes_today INTEGER DEFAULT 0,
    last_shown INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0, last_active TEXT,
    bonus_date TEXT, invited_by INTEGER DEFAULT 0, invites INTEGER DEFAULT 0,
    bonus_likes INTEGER DEFAULT 0
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS likes (
    from_id INTEGER, to_id INTEGER, valentine INTEGER DEFAULT 0, super INTEGER DEFAULT 0
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS reports (
    from_id INTEGER, to_id INTEGER, reason TEXT, date TEXT
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS anon (
    from_id INTEGER, to_id INTEGER, text TEXT, date TEXT
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


def main_menu():
    return ReplyKeyboardMarkup([
        ["👀 Искать", "💗 Лайки"],
        ["💖 Мэтчи", "✏️ Моя анкета"],
        ["⭐ Premium", "🎁 Бонус"],
        ["👥 Пригласи друга", "📊 Статистика"],
        ["✅ Верификация", "🗑 Удалить анкету"]
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


def bonus_extra(user_id):
    cur.execute("SELECT bonus_likes FROM users WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    return r[0] if r else 0


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
    limit = (500 if verified else 100) + bonus_extra(user_id)
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
    args = context.args
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cur.fetchone():
        check_birthday(update.effective_user.id)
        cur.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (today(), user_id))
        conn.commit()
        await update.message.reply_text("Ты уже зарегистрирован(а) 💕", reply_markup=main_menu())
        return ConversationHandler.END
    context.user_data["ref"] = args[0] if args else None
    await update.message.reply_text("Привет! Давай создадим анкету 💕\n\nКак тебя зовут?")
    return NAME


def check_birthday(user_id):
    cur.execute("SELECT birthday, bday_gift_year FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        return False
    bday, gift_year = row
    try:
        d, m = bday.split(".")
        now = datetime.date.today()
        if int(d) == now.day and int(m) == now.month and gift_year != now.year:
            until = (now + datetime.timedelta(hours=12)).isoformat()
            cur.execute("UPDATE users SET premium_until = ?, bday_gift_year = ? WHERE user_id = ?",
                        (until, now.year, user_id))
            conn.commit()
            return True
    except:
        pass
    return False


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
    await update.message.reply_text("Напиши свой день рождения в формате ДД.ММ (например: 05.04)\n\nИли нажми «Пропустить»",
        reply_markup=ReplyKeyboardMarkup([["Пропустить"]], resize_keyboard=True))
    return BDAY


async def get_bday(update, context):
    if update.message.text == "Пропустить":
        context.user_data["birthday"] = ""
    else:
        t = update.message.text.strip()
        try:
            d, m = t.split(".")
            di, mi = int(d), int(m)
            if di < 1 or di > 31 or mi < 1 or mi > 12:
                raise ValueError
            context.user_data["birthday"] = f"{di:02d}.{mi:02d}"
        except:
            await update.message.reply_text("Формат ДД.ММ (например: 05.04). Попробуй ещё или нажми «Пропустить»")
            return BDAY
    kb = ReplyKeyboardMarkup(
        [[KeyboardButton("📍 Отправить гео", request_location=True)]],
        resize_keyboard=True, one_time_keyboard=True
    )
    await update.message.reply_text("Напиши свой город **или** отправь гео 📍", reply_markup=kb, parse_mode="Markdown")
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
    ref = context.user_data.get("ref")
    inviter = 0
    if ref and ref.startswith("ref"):
        try:
            inviter = int(ref.replace("ref", ""))
            if inviter == user.id:
                inviter = 0
        except:
            inviter = 0
    cur.execute("""INSERT OR REPLACE INTO users
        (user_id, username, name, age, my_gender, about, birthday, bday_changes, bday_gift_year,
         city, lat, lon, radius, photos, partner_gender, partner_age_min, partner_age_max, verified,
         premium_until, likes_today, likes_date, verify_attempts, super_likes_today,
         last_shown, hidden, last_active, bonus_date, invited_by, invites, bonus_likes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (
        user.id, user.username or "", context.user_data["name"], context.user_data["age"],
        context.user_data["my_gender"], context.user_data["about"],
        context.user_data.get("birthday", ""), 0, 0,
        context.user_data["city"], context.user_data.get("lat"), context.user_data.get("lon"),
        context.user_data["radius"],
        ",".join(context.user_data["photos"]),
        context.user_data["partner_gender"], amin, amax,
        0, None, 0, today(), 0, 0, 0, 0, today(), "", inviter, 0, 0
    ))
    conn.commit()
    if inviter:
        cur.execute("UPDATE users SET invites = invites + 1, bonus_likes = bonus_likes + 50 WHERE user_id = ?", (inviter,))
        conn.commit()
        try:
            await context.bot.send_message(inviter, "🎉 По твоей ссылке пришёл друг! +50 лайков навсегда.")
        except:
            pass
    await update.message.reply_text("Анкета готова! 💕", reply_markup=main_menu())
    return ConversationHandler.END


# ---------- Поиск ----------
async def find(update, context):
    user_id = update.effective_user.id
    if check_birthday(user_id):
        await update.message.reply_text("🎂 С днём рождения! Дарю тебе Premium на 12 часов ⭐")
    cur.execute("UPDATE users SET last_active = ? WHERE user_id = ?", (today(), user_id))
    conn.commit()
    if not check_like_limit(user_id):
        await update.message.reply_text("Лимит лайков исчерпан.\n🎁 Бонус +10\n👥 Пригласи друга +50\n⭐ Premium — безлимит")
        return
    cur.execute("SELECT city, lat, lon, radius FROM users WHERE user_id = ?", (user_id,))
    me = cur.fetchone()
    my_city, my_lat, my_lon, my_radius = me if me else (None, None, None, 50)
    cur.execute("""SELECT user_id, name, age, about, photos, my_gender, city, lat, lon, verified, birthday
                   FROM users WHERE user_id != ? AND user_id != ?
                   AND user_id NOT IN (SELECT to_id FROM likes WHERE from_id = ?)""",
                (user_id, ADMIN_ID, user_id))
    rows = cur.fetchall()
    if not rows:
        await update.message.reply_text("Анкеты закончились 😔")
        return
    candidates = []
    now = datetime.date.today()
    for r in rows:
        uid, name, age, about, photos, gender, city, lat, lon, ver, bday = r
        dist = None
        match = False
        if my_lat and my_lon and lat and lon:
            dist = haversine(my_lat, my_lon, lat, lon)
            if dist <= my_radius:
                match = True
        elif my_city and city and my_city == city:
            match = True
        if match:
            is_bday_today = False
            if bday:
                try:
                    d, m = bday.split(".")
                    if int(d) == now.day and int(m) == now.month:
                        is_bday_today = True
                except:
                    pass
            candidates.append((0 if is_bday_today else 1, dist if dist is not None else 9999,
                               uid, name, age, about, photos, gender, city, dist, ver, is_bday_today))
    if not candidates:
        await update.message.reply_text("В твоём городе/радиусе пока никого нет 😔")
        return
    candidates.sort(key=lambda x: (x[0], x[1]))
    _, _, uid, name, age, about, photos, gender, city, real_dist, ver, is_bday_today = candidates[0]
    cur.execute("UPDATE users SET last_shown = ? WHERE user_id = ?", (uid, user_id))
    conn.commit()
    cur.execute("SELECT COUNT(*) FROM likes WHERE to_id = ?", (uid,))
    likes_count = cur.fetchone()[0]
    cur.execute("SELECT last_active FROM users WHERE user_id = ?", (uid,))
    la = cur.fetchone()
    newbie = ""
    if la and la[0] and days_since(la[0]) <= 3:
        newbie = " 🆕"
    badges = ""
    if ver:
        badges += " ✅"
    if is_premium(uid):
        badges += " ⭐"
    if is_bday_today:
        badges += " 🎂"
    if real_dist is not None:
        dist_text = f"\n📍 {round(real_dist, 1)} км"
    elif city:
        dist_text = f"\n🏙 {city}"
    else:
        dist_text = ""
    bday_note = "\n🎂 Сегодня ДР!" if is_bday_today else ""
    text = (f"👤 {name}, {age} ({gender}){badges}{newbie}{dist_text}{bday_note}\n"
            f"❤️ {likes_count} лайков\n\n{about or '—'}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Лайк", callback_data=f"like_{uid}"),
         InlineKeyboardButton("💌 Валентинка", callback_data=f"val_{uid}")],
        [InlineKeyboardButton("⭐ Супер-лайк", callback_data=f"super_{uid}")],
        [InlineKeyboardButton("💬 Анонимка", callback_data=f"anon_{uid}")],
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

    if data.startswith("anon_"):
        target = int(data.split("_")[1])
        context.user_data["anon_to"] = target
        await context.bot.send_message(me, "💬 Напиши анонимное сообщение — оно уйдёт тому, кого ты лайкнул(а):")
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
            try:
                await q.edit_message_caption(f"⭐ Супер-лайк! 💖 Мэтч! @{uname or 'скрыт'}")
            except:
                pass
            try:
                await context.bot.send_message(target, "⭐ Тебя супер-лайкнули! Загляни в бота.")
            except:
                pass
        else:
            try:
                await q.edit_message_caption("⭐ Супер-лайк отправлен!")
            except:
                pass
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
            try:
                await q.edit_message_caption(f"💖 Мэтч! @{uname or 'скрыт'}")
            except:
                pass
        else:
            try:
                await q.edit_message_caption("Отправлено 💕")
            except:
                pass


async def anon_message(update, context):
    target = context.user_data.get("anon_to")
    if not target:
        return
    cur.execute("INSERT INTO anon VALUES (?, ?, ?, ?)",
                (update.effective_user.id, target, update.message.text, today()))
    conn.commit()
    context.user_data["anon_to"] = None
    await update.message.reply_text("💬 Анонимка отправлена!")
    try:
        await context.bot.send_message(target,
            f"💬 Тебе анонимное сообщение:\n\n{update.message.text}")
    except:
        pass


# ---------- Профиль и редактирование ----------
async def my_profile(update, context):
    user_id = update.effective_user.id
    if check_birthday(user_id):
        await update.message.reply_text("🎂 С днём рождения! Дарю тебе Premium на 12 часов ⭐")
    cur.execute("""SELECT name, age, my_gender, about, photos, verified, city, radius, lat, lon, birthday
                   FROM users WHERE user_id = ?""", (user_id,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Анкеты нет. /start")
        return
    name, age, gender, about, photos, verified, city, radius, lat, lon, bday = row
    cur.execute("SELECT COUNT(*) FROM likes WHERE to_id = ?", (user_id,))
    likes_count = cur.fetchone()[0]
    cur.execute("SELECT invites FROM users WHERE user_id = ?", (user_id,))
    invites = cur.fetchone()[0]
    status = []
    if verified:
        status.append("✅")
    if is_premium(user_id):
        status.append("⭐")
    loc = "📍 по гео" if (lat and lon) else (f"🏙 {city}" if city else "")
    bday_line = f"🎂 {bday}\n" if bday else ""
    text = (f"👤 {name}, {age} ({gender}) {' '.join(status)}\n"
            f"{bday_line}{loc} · 📏 {radius} км\n"
            f"❤️ {likes_count} лайков · 👥 {invites} друзей\n\n{about or '—'}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Редактировать", callback_data="edit_menu")],
        [InlineKeyboardButton("👁 Кто лайкнул", callback_data="who_liked"),
         InlineKeyboardButton("💌 Валентинки", callback_data="my_valentines")],
        [InlineKeyboardButton("↩️ Вернуть анкету", callback_data="back_anketa")]
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


async def profile_callback(update, context):
    q = update.callback_query
    await q.answer()
    data = q.data
    user_id = q.from_user.id

    if data == "edit_menu":
        cur.execute("SELECT bday_changes FROM users WHERE user_id = ?", (user_id,))
        r = cur.fetchone()
        changes = r[0] if r else 0
        bday_btn = f"🎂 ДР ({changes}/{MAX_BDAY_CHANGES})" if changes < MAX_BDAY_CHANGES else "🎂 ДР (лимит)"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("Имя", callback_data="edit_name"),
             InlineKeyboardButton("Возраст", callback_data="edit_age")],
            [InlineKeyboardButton("Описание", callback_data="edit_about"),
             InlineKeyboardButton("Фото", callback_data="edit_photo")],
            [InlineKeyboardButton(bday_btn, callback_data="edit_bday")],
            [InlineKeyboardButton("🏙 Город / Гео", callback_data="edit_city")],
            [InlineKeyboardButton("Радиус", callback_data="edit_radius"),
             InlineKeyboardButton("Пол", callback_data="edit_gender")],
            [InlineKeyboardButton("🔙 Назад", callback_data="profile_back")]
        ])
        try:
            await q.edit_message_reply_markup(reply_markup=kb)
        except:
            await context.bot.send_message(user_id, "Что хочешь изменить?", reply_markup=kb)
        return

    if data == "profile_back":
        await my_profile(update, context)
        return

    if data == "who_liked":
        cur.execute("""SELECT u.name, u.username, l.valentine, l.super FROM likes l
                       JOIN users u ON u.user_id = l.from_id WHERE l.to_id = ?""", (user_id,))
        rows = cur.fetchall()
        if not rows:
            await context.bot.send_message(user_id, "Тебя пока никто не лайкнул")
        else:
            lines = []
            for n, u, v, s in rows:
                mark = "💌" if v else ("⭐" if s else "❤️")
                lines.append(f"{mark} {n} — @{u or 'скрыт'}")
            await context.bot.send_message(user_id, "👁 Кто тебя лайкнул:\n" + "\n".join(lines))
        return

    if data == "my_valentines":
        cur.execute("""SELECT u.name, u.username FROM likes l
                       JOIN users u ON u.user_id = l.from_id
                       WHERE l.to_id = ? AND l.valentine = 1""", (user_id,))
        rows = cur.fetchall()
        text = "\n".join([f"{n} — @{u or 'скрыт'}" for n, u in rows]) if rows else "Пусто"
        await context.bot.send_message(user_id, "💌 Валентинки:\n" + text)
        return

    if data == "back_anketa":
        if not is_premium(user_id):
            await context.bot.send_message(user_id, "Только с ⭐ Premium")
            return
        cur.execute("SELECT last_shown FROM users WHERE user_id = ?", (user_id,))
        row = cur.fetchone()
        if not row or not row[0]:
            await context.bot.send_message(user_id, "Нет анкеты для возврата")
            return
        last_id = row[0]
        cur.execute("SELECT user_id, name, age, about, photos, my_gender FROM users WHERE user_id = ?", (last_id,))
        r = cur.fetchone()
        if not r:
            await context.bot.send_message(user_id, "Анкета недоступна")
            return
        uid, name, age, about, photos, gender = r
        text = f"👤 {name}, {age} ({gender})\n\n{about or '—'}"
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("❤️ Лайк", callback_data=f"like_{uid}")],
            [InlineKeyboardButton("⭐ Супер-лайк", callback_data=f"super_{uid}")]
        ])
        photos_list = photos.split(",") if photos else []
        if photos_list:
            await context.bot.send_photo(user_id, photos_list[0], caption=text, reply_markup=kb)
        else:
            await context.bot.send_message(user_id, text, reply_markup=kb)
        return

    if data == "edit_bday":
        cur.execute("SELECT bday_changes FROM users WHERE user_id = ?", (user_id,))
        r = cur.fetchone()
        if r and r[0] >= MAX_BDAY_CHANGES:
            await context.bot.send_message(user_id, "🎂 Лимит изменений ДР исчерпан (5/5)")
            return
        context.user_data["edit_field"] = "bday"
        await context.bot.send_message(user_id, "🎂 Напиши новую дату ДР в формате ДД.ММ:")
        return

    if data.startswith("edit_"):
        field = data.replace("edit_", "")
        context.user_data["edit_field"] = field
        prompts = {
            "name": "Новое имя:",
            "age": "Новый возраст (15–99):",
            "about": "Новое описание:",
            "photo": "Отправь новые фото (старые заменятся):",
            "city": "Напиши город или отправь гео 📍",
            "radius": "Новый радиус (5–100):",
            "gender": "Новый пол:"
        }
        if field == "city":
            kb = ReplyKeyboardMarkup(
                [[KeyboardButton("📍 Отправить гео", request_location=True)], ["🔙 В меню"]],
                resize_keyboard=True, one_time_keyboard=True
            )
            await context.bot.send_message(user_id, prompts["city"], reply_markup=kb)
        elif field == "radius":
            await context.bot.send_message(user_id, prompts["radius"],
                reply_markup=ReplyKeyboardMarkup([["5", "10", "25"], ["50", "75", "100"]], resize_keyboard=True))
        elif field == "gender":
            await context.bot.send_message(user_id, prompts["gender"],
                reply_markup=ReplyKeyboardMarkup([["М", "Ж"]], resize_keyboard=True))
        elif field == "photo":
            context.user_data["edit_photos"] = []
            await context.bot.send_message(user_id, prompts["photo"])
        else:
            await context.bot.send_message(user_id, prompts[field])
        return


async def start_edit(update, context):
    q = update.callback_query
    await q.answer()
    field = q.data.replace("edit_", "")
    user_id = q.from_user.id
    context.user_data["edit_field"] = field
    prompts = {
        "name": "Новое имя:",
        "age": "Новый возраст (15–99):",
        "about": "Новое описание:",
        "photo": "Отправь новые фото:",
        "city": "Напиши город или отправь гео 📍",
        "radius": "Новый радиус (5–100):",
        "gender": "Новый пол:",
        "bday": "Напиши новую дату ДР в формате ДД.ММ:"
    }
    if field == "city":
        kb = ReplyKeyboardMarkup(
            [[KeyboardButton("📍 Отправить гео", request_location=True)], ["🔙 В меню"]],
            resize_keyboard=True, one_time_keyboard=True
        )
        await context.bot.send_message(user_id, prompts["city"], reply_markup=kb)
    elif field == "radius":
        await context.bot.send_message(user_id, prompts["radius"],
            reply_markup=ReplyKeyboardMarkup([["5", "10", "25"], ["50", "75", "100"]], resize_keyboard=True))
    elif field == "gender":
        await context.bot.send_message(user_id, prompts["gender"],
            reply_markup=ReplyKeyboardMarkup([["М", "Ж"]], resize_keyboard=True))
    elif field == "photo":
        context.user_data["edit_photos"] = []
        await context.bot.send_message(user_id, prompts["photo"])
    else:
        await context.bot.send_message(user_id, prompts[field])
    return EDIT_VALUE


async def edit_value(update, context):
    field = context.user_data.get("edit_field")
    if not field:
        await update.message.reply_text("Выбери что редактировать", reply_markup=main_menu())
        return ConversationHandler.END
    user_id = update.effective_user.id

    if field == "name":
        cur.execute("UPDATE users SET name = ? WHERE user_id = ?", (update.message.text, user_id))
        conn.commit()
        await update.message.reply_text("✅ Имя изменено", reply_markup=main_menu())
    elif field == "age":
        try:
            age = int(update.message.text)
            if age < 15 or age > 99:
                raise ValueError
        except:
            await update.message.reply_text("Число от 15 до 99")
            return EDIT_VALUE
        cur.execute("UPDATE users SET age = ? WHERE user_id = ?", (age, user_id))
        conn.commit()
        await update.message.reply_text("✅ Возраст изменён", reply_markup=main_menu())
    elif field == "about":
        cur.execute("UPDATE users SET about = ? WHERE user_id = ?", (update.message.text, user_id))
        conn.commit()
        await update.message.reply_text("✅ Описание изменено", reply_markup=main_menu())
    elif field == "city":
        if update.message.location:
            cur.execute("UPDATE users SET lat = ?, lon = ?, city = '' WHERE user_id = ?",
                        (update.message.location.latitude, update.message.location.longitude, user_id))
        else:
            cur.execute("UPDATE users SET city = ?, lat = NULL, lon = NULL WHERE user_id = ?",
                        (update.message.text.strip(), user_id))
        conn.commit()
        await update.message.reply_text("✅ Обновлено", reply_markup=main_menu())
    elif field == "radius":
        try:
            r = int(update.message.text)
            if r < 5 or r > 100:
                raise ValueError
        except:
            await update.message.reply_text("Число от 5 до 100")
            return EDIT_VALUE
        cur.execute("UPDATE users SET radius = ? WHERE user_id = ?", (r, user_id))
        conn.commit()
        await update.message.reply_text("✅ Радиус изменён", reply_markup=main_menu())
    elif field == "gender":
        g = update.message.text
        if g not in ["М", "Ж"]:
            await update.message.reply_text("М или Ж")
            return EDIT_VALUE
        cur.execute("UPDATE users SET my_gender = ? WHERE user_id = ?", (g, user_id))
        conn.commit()
        await update.message.reply_text("✅ Пол изменён", reply_markup=main_menu())
    elif field == "bday":
        cur.execute("SELECT bday_changes FROM users WHERE user_id = ?", (user_id,))
        r = cur.fetchone()
        changes = r[0] if r else 0
        if changes >= MAX_BDAY_CHANGES:
            await update.message.reply_text("Лимит изменений ДР исчерпан", reply_markup=main_menu())
            context.user_data["edit_field"] = None
            return ConversationHandler.END
        try:
            d, m = update.message.text.strip().split(".")
            di, mi = int(d), int(m)
            if di < 1 or di > 31 or mi < 1 or mi > 12:
                raise ValueError
            bday = f"{di:02d}.{mi:02d}"
        except:
            await update.message.reply_text("Формат ДД.ММ")
            return EDIT_VALUE
        cur.execute("UPDATE users SET birthday = ?, bday_changes = bday_changes + 1 WHERE user_id = ?",
                    (bday, user_id))
        conn.commit()
        await update.message.reply_text(f"✅ ДР изменён ({changes+1}/{MAX_BDAY_CHANGES})", reply_markup=main_menu())
    elif field == "photo":
        photos = context.user_data.get("edit_photos", [])
        limit = get_photo_limit(user_id)
        if update.message.photo:
            photos.append(update.message.photo[-1].file_id)
        elif update.message.video:
            photos.append(update.message.video.file_id)
        else:
            await update.message.reply_text("Нужно фото/видео")
            return EDIT_VALUE
        context.user_data["edit_photos"] = photos
        if len(photos) >= limit:
            cur.execute("UPDATE users SET photos = ? WHERE user_id = ?", (",".join(photos), user_id))
            conn.commit()
            await update.message.reply_text("✅ Фото обновлены", reply_markup=main_menu())
        else:
            await update.message.reply_text(f"({len(photos)}/{limit}) Ещё или Готово?",
                reply_markup=ReplyKeyboardMarkup([["Добавить ещё", "Готово"]], resize_keyboard=True))
            return EDIT_VALUE
    context.user_data["edit_field"] = None
    return ConversationHandler.END


# ---------- Бонусы и прочее ----------
async def bonus(update, context):
    user_id = update.effective_user.id
    cur.execute("SELECT bonus_date FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Сначала /start")
        return
    if row[0] == today():
        await update.message.reply_text("Ты уже получил(а) бонус сегодня. Приходи завтра 💕")
        return
    cur.execute("UPDATE users SET bonus_date = ?, bonus_likes = bonus_likes + 10 WHERE user_id = ?", (today(), user_id))
    conn.commit()
    await update.message.reply_text("🎁 +10 лайков на сегодня!")


async def invite(update, context):
    user_id = update.effective_user.id
    bot_username = (await context.bot.get_me()).username
    link = f"https://t.me/{bot_username}?start=ref{user_id}"
    cur.execute("SELECT invites, bonus_likes FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    invites = row[0] if row else 0
    bonus_l = row[1] if row else 0
    await update.message.reply_text(
        f"👥 Пригласи друга\n\nТвоя ссылка:\n{link}\n\n"
        f"За каждого друга +50 лайков навсегда.\n"
        f"Приглашено: {invites}\nБонусных лайков: +{bonus_l}"
    )


async def my_stats(update, context):
    user_id = update.effective_user.id
    cur.execute("SELECT COUNT(*) FROM likes WHERE from_id = ?", (user_id,))
    likes_given = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM likes WHERE to_id = ?", (user_id,))
    likes_received = cur.fetchone()[0]
    cur.execute("""SELECT COUNT(*) FROM likes l1
                   JOIN likes l2 ON l1.to_id = l2.from_id AND l1.from_id = l2.to_id
                   WHERE l1.from_id = ?""", (user_id,))
    matches = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM likes WHERE to_id = ? AND valentine = 1", (user_id,))
    vals = cur.fetchone()[0]
    cur.execute("SELECT invites, bonus_likes FROM users WHERE user_id = ?", (user_id,))
    r = cur.fetchone()
    invites = r[0] if r else 0
    bonus_l = r[1] if r else 0
    await update.message.reply_text(
        f"📊 Твоя статистика\n\n"
        f"❤️ Лайков поставил(а): {likes_given}\n"
        f"💗 Лайков получил(а): {likes_received}\n"
        f"💖 Мэтчей: {matches}\n"
        f"💌 Валентинок: {vals}\n"
        f"👥 Друзей: {invites}\n"
        f"🎁 Бонусных лайков: +{bonus_l}"
    )


# ---------- Верификация ----------
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
        "⏳ Заявка отправлена на проверку\n\n"
        "Ожидай от 1 до 24 часов. Модератор проверит твой кружок и пришлёт ответ 💕",
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
        await context.bot.send_message(uid,
            "🎉 Поздравляем! Ты прошёл верификацию ✅\n\n"
            "Теперь тебе доступно 500 лайков в день и значок ✅ в анкете.")
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
        await context.bot.send_message(uid,
            f"😔 Верификация не пройдена.\n\nПопыток использовано: {attempts} из {MAX_VERIFY_ATTEMPTS}.\n"
            f"Попробуй снова — нажми «✅ Верификация».")
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


def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            MY_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_my_gender)],
            ABOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_about)],
            BDAY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_bday)],
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
        entry_points=[CallbackQueryHandler(start_edit, pattern="^edit_(name|age|about|photo|city|radius|gender|bday)$")],
        states={EDIT_VALUE: [MessageHandler(filters.ALL & ~filters.COMMAND, edit_value)]},
        fallbacks=[]
    )
    app.add_handler(edit_conv)

    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("grant_premium", grant_premium))
    app.add_handler(CommandHandler("revoke_premium", revoke_premium))
    app.add_handler(MessageHandler(filters.Regex("^👀 Искать$"), find))
    app.add_handler(MessageHandler(filters.Regex("^💗 Лайки$"), my_likes))
    app.add_handler(MessageHandler(filters.Regex("^💖 Мэтчи$"), my_matches))
    app.add_handler(MessageHandler(filters.Regex("^✏️ Моя анкета$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex("^🎁 Бонус$"), bonus))
    app.add_handler(MessageHandler(filters.Regex("^👥 Пригласи друга$"), invite))
    app.add_handler(MessageHandler(filters.Regex("^📊 Статистика$"), my_stats))
    app.add_handler(MessageHandler(filters.Regex("^⭐ Premium$"), premium))
    app.add_handler(MessageHandler(filters.Regex("^✅ Верификация$"), verify_start))
    app.add_handler(MessageHandler(filters.Regex("^🗑 Удалить анкету$"), delete_profile))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, anon_message))
    app.add_handler(CallbackQueryHandler(profile_callback, pattern="^(edit_menu|profile_back|who_liked|my_valentines|back_anketa)$"))
    app.add_handler(CallbackQueryHandler(like_handler))
    app.add_handler(CallbackQueryHandler(buy_premium, pattern="^buy_premium$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.run_polling()


if __name__ == "__main__":
    main()
