import logging
import sqlite3
import asyncio
from collections import defaultdict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters, CallbackContext,
    CallbackQueryHandler, ConversationHandler, ContextTypes
)

from flask import Flask
from threading import Thread


TOKEN = "8058572872:AAFsJIWjrNUQj07bu5ee1rUwozJp5KIhRLc"
ADMIN_CHAT_ID = -1003719140425
CHAT_INVITE_LINK = "https://t.me/+E8PkKKy4StM1NTgy"
CHANNEL_INVITE_LINK = "https://t.me/+4pJatOG46rk5MGFi"
DATABASE_NAME = "art_house.db"

NICKNAME, AGE, PHOTOS = range(3)

media_groups = defaultdict(list)
media_group_timers = {}

RULES_TEXT = """
Правила хауса:
☆゜・。。・゜・。。・゜・。。・゜★
1. Общение
✦ Уважительное отношение ко всем участникам.  
✦ Спам запрещён.
✦ Под запретом: обсуждение политики, пропаганда, вложение NSFW контента, нежелательное оскорбление или издевательство. 

2. Уход в рест (перерыв)
✦ Если нужно взять паузу - в комментарии под постом РЕСТ.

3. Выполнение заданий
✦ Запрещена обводка, срисовка, копирование чужих работ, использование ИИ (нейросети, генераторы изображений).  
✦ Работа должна быть подписана вашим никнеймом (который указывали в анкете)

4. Сроки сдачи
✦ Пока что сроков сдачи у нас нет и их можно выполнять по желанию. 

☆゜・。。・゜・。。・゜・。。・゜★
"""

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

def init_db():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS applications (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            nickname TEXT,
            age INTEGER,
            photos TEXT,
            status TEXT DEFAULT 'pending',
            admin_decision TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_application(user_id: int, username: str, nickname: str, age: int, photos: list):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO applications 
        (user_id, username, nickname, age, photos, status)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, username, nickname, age, str(photos), 'pending'))
    conn.commit()
    conn.close()

def update_application_status(user_id: int, status: str, admin_decision: str = None):
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE applications 
        SET status = ?, admin_decision = ?
        WHERE user_id = ?
    ''', (status, admin_decision, user_id))
    conn.commit()
    conn.close()

async def start(update: Update, context: CallbackContext) -> int:
    await update.message.reply_photo(
        photo="https://telegraphoto.site/images/4d239585-e3ac-4baa-a2d6-2b0849f31ee7.jpg",
        caption="Добро пожаловать в арт-хаус Лунариум!\n\nДля вступления заполни анкету. Придумай себе имя:"
    )
    return NICKNAME

async def nickname(update: Update, context: CallbackContext) -> int:
    context.user_data['nickname'] = update.message.text
    await update.message.reply_photo(
        photo="https://telegraphoto.site/images/052a332b-fe64-4a2a-b8e4-18066b5fd478.jpg",
        caption="Сколько тебе лет?:"
    )
    return AGE

async def age(update: Update, context: CallbackContext) -> int:
    try:
        age = int(update.message.text)
        if age < 12:
            await update.message.reply_text("❌ Извини, в хаус можно только с 12 лет.")
            return ConversationHandler.END
        context.user_data['age'] = age
        await update.message.reply_photo(
            photo="https://telegraphoto.site/images/e95d7934-0ef8-403d-9dc1-f2255e2dd18f.jpg",
            caption="Прикрепи 2–5 своих работ (отправь все фото ОДНИМ сообщением):"
        )
        return PHOTOS
    except ValueError:
        await update.message.reply_text("⚠️ Введи число!")
        return AGE

async def photos(update: Update, context: CallbackContext) -> int:
    message = update.message
    user = message.from_user
    media_group_id = message.media_group_id

    if not media_group_id:
        await message.reply_text("⚠️ Пожалуйста, отправь 2–5 фото одним сообщением (альбомом).")
        return PHOTOS

    media_groups[media_group_id].append(message)

    if media_group_id in media_group_timers:
        media_group_timers[media_group_id].cancel()

    media_group_timers[media_group_id] = asyncio.create_task(
        process_media_group(media_group_id, context, user.id)
    )
    return PHOTOS

async def process_media_group(media_group_id, context, user_id):
    await asyncio.sleep(2.5)

    messages = media_groups.pop(media_group_id, [])
    media_group_timers.pop(media_group_id, None)

    if not messages:
        await context.bot.send_message(chat_id=user_id, text="⚠️ Не удалось получить изображения.")
        return

    file_ids = []
    for msg in messages:
        if msg.photo:
            file_ids.append(msg.photo[-1].file_id)

    if len(file_ids) < 2 or len(file_ids) > 5:
        await context.bot.send_message(
            chat_id=user_id,
            text="❌ Нужно отправить от 2 до 5 фото одним сообщением (альбомом).\nПопробуй ещё раз:"
        )
        await context.bot.send_message(chat_id=user_id, text="Прикрепи свои работы заново:")
        return

    user_data = context.application.user_data[user_id]
    username = (await context.bot.get_chat(user_id)).username or ""

    save_application(
        user_id=user_id,
        username=username,
        nickname=user_data.get("nickname", ""),
        age=user_data.get("age", 0),
        photos=file_ids
    )

    media_group = []
    for i, file_id in enumerate(file_ids):
        if i == 0:
            media_group.append(InputMediaPhoto(
                media=file_id,
                caption=(
                    f"📝 Новая анкета!\n\n"
                    f"👤 @{username}\n"
                    f"🎨 Ник: {user_data['nickname']}\n"
                    f"🔞 Возраст: {user_data['age']}"
                )
            ))
        else:
            media_group.append(InputMediaPhoto(media=file_id))

    try:
        await context.bot.send_media_group(chat_id=ADMIN_CHAT_ID, media=media_group)
    except Exception as e:
        logging.error(f"Ошибка при отправке медиагруппы: {e}")
        await context.bot.send_message(user_id, "⚠️ Не удалось отправить работы администратору.")
        return

    keyboard = [[
        InlineKeyboardButton("✅ Одобрить", callback_data=f"approve_{user_id}"),
        InlineKeyboardButton("❌ Отклонить", callback_data=f"reject_{user_id}")
    ]]
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text="Решение по заявке:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

    await context.bot.send_message(user_id, "✅ Анкета отправлена на модерацию!")

async def admin_decision(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()

    action, user_id = query.data.split('_')
    user_id = int(user_id)

    if action == "approve":
        update_application_status(user_id, "approved", "Принято админом")
        keyboard = [[InlineKeyboardButton("✅ Принимаю правила", callback_data=f"accept_{user_id}")]]
        await context.bot.send_message(
            chat_id=user_id,
            text=f"⭐ Ты принят!\n\n{RULES_TEXT}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        await query.edit_message_text("Заявка одобрена!")
    else:
        update_application_status(user_id, "rejected", "Отклонено админом")
        await context.bot.send_message(chat_id=user_id, text="❌ Твоя заявка отклонена.")
        await query.edit_message_text("Заявка отклонена.")

async def accept_rules(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    await query.answer()
    user_id = int(query.data.split('_')[1])

    await context.bot.send_message(
        chat_id=user_id,
        text=f"🔗 Чат: {CHAT_INVITE_LINK}\n📢 Канал: {CHANNEL_INVITE_LINK}\n\nДобро пожаловать!",
        disable_web_page_preview=True
    )
    await query.edit_message_text("✅ Ты теперь участник!")

async def cancel(update: Update, context: CallbackContext) -> int:
    await update.message.reply_text("❌ Анкета отменена.")
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host="0.0.0.0", port=8080)

def main():
    init_db()

    application = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            NICKNAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, nickname)],
            AGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, age)],
            PHOTOS: [MessageHandler(filters.PHOTO, photos)]
        },
        fallbacks=[CommandHandler('cancel', cancel)],
        allow_reentry=True
    )

    application.add_handler(conv_handler)
    application.add_handler(CallbackQueryHandler(admin_decision, pattern=r'^(approve|reject)_\d+$'))
    application.add_handler(CallbackQueryHandler(accept_rules, pattern=r'^accept_\d+$'))
    application.add_error_handler(error_handler)

    flask_thread = Thread(target=run_flask, daemon=True)
    flask_thread.start()

    application.run_polling()

if __name__ == '__main__':
    main()
