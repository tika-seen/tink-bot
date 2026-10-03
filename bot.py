import os
import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

TOKEN = os.environ.get("BOT_TOKEN")

# Состояния
NAME, AGE, ABOUT, PHOTO, PARTNER_GENDER, PARTNER_AGE = range(6)

conn = sqlite3.connect("dating.db", check_same_thread=False)
cur = conn.cursor()
cur.execute("""CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    name TEXT,
    age INTEGER,
    about TEXT,
    photos TEXT,
    partner_gender TEXT,
    partner_age_min INTEGER,
    partner_age_max INTEGER
)""")
cur.execute("""CREATE TABLE IF NOT EXISTS likes (
    from_id INTEGER,
    to_id INTEGER,
    valentine INTEGER DEFAULT 0
)""")
conn.commit()


def main_menu():
    return ReplyKeyboardMarkup([
        ["👀 Искать", "💗 Лайки"],
        ["💖 Мэтчи", "💌 Валентинки"],
        ["✏️ Моя анкета", "🗑 Удалить анкету"]
    ], resize_keyboard=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if cur.fetchone():
        await update.message.reply_text("Ты уже зарегистрирован(а) 💕", reply_markup=main_menu())
        return ConversationHandler.END
    await update.message.reply_text("Привет! Давай создадим анкету 💕\n\nКак тебя зовут?")
    return NAME


async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["name"] = update.message.text
    await update.message.reply_text("Сколько тебе лет? (от 15 до 99)")
    return AGE


async def get_age(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        age = int(update.message.text)
        if age < 15 or age > 99:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Возраст должен быть числом от 15 до 99. Попробуй ещё:")
        return AGE
    context.user_data["age"] = age
    await update.message.reply_text("Расскажи о себе или нажми «Пропустить»",
        reply_markup=ReplyKeyboardMarkup([["Пропустить"]], resize_keyboard=True))
    return ABOUT


async def get_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Пропустить":
        context.user_data["about"] = ""
    else:
        context.user_data["about"] = update.message.text
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
        await update.message.reply_text("Максимум 3. Дальше выбери пол партнёра:",
            reply_markup=ReplyKeyboardMarkup([["М", "Ж", "Всё равно"]], resize_keyboard=True))
        return PARTNER_GENDER
    await update.message.reply_text(f"Добавлено ({len(photos)}/3). Добавить ещё или Готово?",
        reply_markup=ReplyKeyboardMarkup([["Добавить ещё", "Готово"]], resize_keyboard=True))
    return PHOTO


async def photo_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Готово":
        await update.message.reply_text("Выбери пол партнёра:",
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
        await update.message.reply_text("Напиши в формате 15-25 (от 15 до 99)")
        return PARTNER_AGE
    user = update.effective_user
    cur.execute("INSERT OR REPLACE INTO users VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", (
        user.id, user.username or "", context.user_data["name"], context.user_data["age"],
        context.user_data["about"], ",".join(context.user_data["photos"]),
        context.user_data["partner_gender"], amin, amax
    ))
    conn.commit()
    await update.message.reply_text("Анкета готова! 💕", reply_markup=main_menu())
    return ConversationHandler.END


async def find(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    cur.execute("""SELECT user_id, name, age, about, photos FROM users
                   WHERE user_id != ? AND user_id NOT IN
                   (SELECT to_id FROM likes WHERE from_id = ?) LIMIT 1""", (user_id, user_id))
    row = cur.fetchone()
    if not row:
        await update.message.reply_text("Анкеты закончились 😔")
        return
    uid, name, age, about, photos = row
    text = f"👤 {name}, {age}\n\n{about or '—'}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("❤️ Лайк", callback_data=f"like_{uid}"),
         InlineKeyboardButton("💌 Валентинка", callback_data=f"val_{uid}")],
        [InlineKeyboardButton("👎 Пропустить", callback_data="skip")]
    ])
    if photos:
        fid = photos.split(",")[0]
        await update.message.reply_photo(fid, caption=text, reply_markup=kb)
    else:
        await update.message.reply_text(text, reply_markup=kb)


async def like_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data
    me = q.from_user.id
    if data == "skip":
        await q.edit_message_caption("Пропущено")
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
    cur.execute("SELECT name, age, about FROM users WHERE user_id = ?", (update.effective_user.id,))
    row = cur.fetchone()
    if row:
        await update.message.reply_text(f"👤 {row[0]}, {row[1]}\n\n{row[2] or '—'}")


async def delete_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cur.execute("DELETE FROM users WHERE user_id = ?", (update.effective_user.id,))
    cur.execute("DELETE FROM likes WHERE from_id = ? OR to_id = ?",
                (update.effective_user.id, update.effective_user.id))
    conn.commit()
    await update.message.reply_text("Анкета удалена 🗑 Напиши /start чтобы создать заново.")


def main():
    app = Application.builder().token(TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_age)],
            ABOUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_about)],
            PHOTO: [
                MessageHandler(filters.PHOTO | filters.VIDEO, get_photo),
                MessageHandler(filters.Regex("^(Добавить ещё|Готово)$"), photo_choice)
            ],
            PARTNER_GENDER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_gender)],
            PARTNER_AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_partner_age)],
        },
        fallbacks=[]
    )
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex("^👀 Искать$"), find))
    app.add_handler(MessageHandler(filters.Regex("^✏️ Моя анкета$"), my_profile))
    app.add_handler(MessageHandler(filters.Regex("^🗑 Удалить анкету$"), delete_profile))
    app.add_handler(CallbackQueryHandler(like_handler))
    app.run_polling()


if __name__ == "__main__":
    main()
