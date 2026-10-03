import os
import sqlite3
import datetime
import random
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, LabeledPrice
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler, PreCheckoutQueryHandler
)

TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))
CHANNEL = "@niwzex"
MAX_VERIFY_ATTEMPTS = 15

NAME, AGE, MY_GENDER, ABOUT, PHOTO, PARTNER_GENDER, PARTNER_AGE = range(7)
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
    photos TEXT,
    partner_gender TEXT,
    partner_age_min INTEGER,
    partner_age_max INTEGER,
    verified INTEGER DEFAULT 0,
    premium_until TEXT,
    likes_today INTEGER DEFAULT 0,
    likes_date TEXT,
    verify_attempts INTEGER DEFAULT 0
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


def main_menu():
    return ReplyKeyboardMarkup([
        ["👀 Искать", "💗 Лайки"],
        ["💖 Мэтчи", "💌 Валентинки"],
        ["✏️ Моя анкета", "⭐ Premium"],
        ["✅ Верификация", "🗑 Удалить анкету"]
    ], resize_keyboard=True)


def is_premium(user_id):
    cur.execute("SELECT premium_until FROM users WHERE user_id = ?", (user_id,))
    row = cur.fetchone()
    if not row or not row[0]:
        return False
    try:
        return datetime.date.fromisoformat(row[0]) >= datetime.date.today()
    except:
        return False


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
    limit = 500 if verified else 100
    if likes_today >= limit:
        return False
    cur.execute("UPDATE users SET likes_today = likes_today + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    return True


async def check_subscription(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
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
    context.user_data["photos"] = []
    await update.message.reply_text("Отправь фото или видео (от 1 до 3)")
    return PHOTO


async def get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    photos = context.user_data.get("photos", [])
    if update.message.photo:
        photos.append(update.message.photo[-1].file_id)
    elif update.message.video:
        photos.append(update.message.video.file_id)
    else:
        await update.message.reply_text("Это не фото и не видео. Попробуй ещё:")
        return PHOTO
    context.user_data["photos"] = photos
    if len(photos) >= 3:
        await update.message.reply_text("Максимум 3. Пол партнёра:",
            reply_markup=ReplyKeyboardMarkup([["М", "Ж", "Всё равно"]], resize_keyboard=True))
        return PARTNER_GENDER
    await update.message.reply_text(f"Добавлено ({len(photos)}/3). Добавить ещё или Готово?",
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
    cur.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        user.id, user.username or "", context.user_data["name"], context.user_data["age"],
        context.user_data["my_gender"], context.user_data["about"],
        ",".join(context.user_data["photos"]),
        context.user_data["partner_gender"], amin, amax,
        0, None, 0, today(), 0
    ))
    conn.commit()
    await update.message.reply_text("Анкета готова! 💕", reply_markup=main_menu())
    return ConversationHandler.END


async def find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not check_like_limit(user_id):
        await update.message.reply_text("Лимит лайков исчерпан.\n✅ Верификация — 500/день\n⭐ Premium — больше возможностей")
        return
    cur.execute("""SELECT user_id, name, age, about, photos, my_gender FROM users
                   WHERE user_id != ? AND user_id NOT IN
                   (SELECT to_id FROM likes WHERE from_id = ?) LIMIT 1""", (user_id, user_id))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Анкеты закончились 😔")
        return
    uid, name, age, about, photos, gender = row
    text = f"👤 {name}, {age} ({gender})\n\n{about or '—'}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Лайк", callback_data=f"like_{uid}"),
         InlineKeyboardButton("💌 Валентинка", callback_data=f"val_{uid}")],
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
        await q.edit_message_caption("Пропущено 👎")
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

    if data.startswith("like_") or data.startswith("val_"):
        target = int(data.split("_")[1])
        val = 1 if data.startswith("val_") else 0
        cur.execute("INSERT INTO likes VALUES (?, ?, ?)", (me, target, val))
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
    cur.execute("""SELECT name, age, my_gender, about, photos, verified, premium_until
                   FROM users WHERE user_id = ?""", (user_id,))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Анкеты нет. /start")
        return
    name, age, gender, about, photos, verified, premium = row
    status = []
    if verified:
        status.append("✅ Верифицирован")
    if premium and is_premium(user_id):
        status.append("⭐ Premium")
    text = f"👤 {name}, {age} ({gender})\n\n{about or '—'}\n\n" + " · ".join(status)
    photos_list = photos.split(",") if photos else []
    if photos_list:
        for i, fid in enumerate(photos_list):
            if i == 0:
                await update.message.reply_photo(fid, caption=text)
            else:
                await update.message.reply_photo(fid)
    else:
        await update.message.reply_text(text)


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
        except Exception as e:
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
        await context.bot.send_message(uid, f"❌ Верификация не пройдена. Попыток использовано: {attempts}/{MAX_VERIFY_ATTEMPTS}")
    except:
        pass


async def premium(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_invoice(
        title="Доступ на 3 дня",
        description="Premium доступ",
        payload="premium_3d",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice("3 дня", 50)]
    )


async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    until = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
    cur.execute("UPDATE users SET premium_until = ? WHERE user_id = ?", (until, uid))
    conn.commit()
    await update.message.reply_text("⭐ Premium активирован до " + until)


async def delete_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    cur.execute("DELETE FROM users WHERE user_id = ?", (uid,))
    cur.execute("DELETE FROM likes WHERE from_id = ? OR to_id = ?", (uid, uid))
    conn.commit()
    await update.message.reply_text("Анкета удалена 🗑 Напиши /start чтобы создать заново.")


def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            MY_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_my_gender)],
            ABOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_about)],
            PHOTO: [
                MessageHandler(filters.PHOTO | filters.VIDEO, get_photo),
                MessageHandler(filters.Regex("^(Добавить ещё|Готово)$"), photo_choice)
            ],
            PARTNER_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_gender)],
            PARTNER_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_age)],
            VERIFY_VIDEO: [MessageHandler(filters.VIDEO_NOTE, verify_video)],
        },
        fallbacks=[]
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(MessageHandler(filters.Regex("^👀 Искать$"), find))
    app.add_handler(MessageHandler(filters.Regex("^💗 Лайки$"), my_likes))
    app.add_handler(MessageHandler(filters.Regex("^💖 Мэтчи$"), my_matches))
    app.add_handler(MessageHandler(filters.Regex("^💌 Валентинки$"), my_valentines))
    app.add_handler(MessageHandler(filters.Regex("^✏️ Моя анкета$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex("^✅ Верификация$"), verify_start))
    app.add_handler(MessageHandler(filters.Regex("^⭐ Premium$"), premium))
    app.add_handler(MessageHandler(filters.Regex("^🗑 Удалить анкету$"), delete_profile))
    app.add_handler(CallbackQueryHandler(like_handler))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.run_polling()


if __name__ == "__main__":
    main()
