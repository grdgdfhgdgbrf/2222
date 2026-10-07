import os
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ConversationHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes
)
from openai import OpenAI
import base64

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# DeepSeek API клиент
client = OpenAI(
    api_key="sk-37c63ff3d8994af0a9ad42f98ae3e0aa",
    base_url="https://api.deepseek.com"
)

# Состояния диалога
SUBJECT, AUTHOR, GRADE, PART, PAGE, NUMBER, PHOTO = range(7)

# Хранилище данных пользователей
user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало работы с ботом"""
    user_id = update.effective_user.id
    user_data[user_id] = {}
    
    keyboard = [
        [InlineKeyboardButton("📝 Ввести данные вручную", callback_data="manual")],
        [InlineKeyboardButton("📷 Определить по фото", callback_data="photo")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        "👋 Привет! Я бот для поиска готовых домашних заданий (ГДЗ).\n\n"
        "Как ты хочешь найти решение?",
        reply_markup=reply_markup
    )
    return SUBJECT

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data[user_id] = {}
    
    if query.data == "manual":
        await query.edit_message_text("📚 Введи предмет (например: математика, русский язык, физика):")
        return SUBJECT
    elif query.data == "photo":
        await query.edit_message_text("📷 Отправь фото задания:")
        return PHOTO

async def get_subject(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение предмета"""
    user_id = update.effective_user.id
    user_data[user_id]['subject'] = update.message.text
    await update.message.reply_text("✍️ Введи автора учебника:")
    return AUTHOR

async def get_author(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение автора"""
    user_id = update.effective_user.id
    user_data[user_id]['author'] = update.message.text
    await update.message.reply_text("📖 Введи класс (например: 5, 6, 7):")
    return GRADE

async def get_grade(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение класса"""
    user_id = update.effective_user.id
    user_data[user_id]['grade'] = update.message.text
    await update.message.reply_text("📑 Введи часть (если есть, иначе напиши 'нет'):")
    return PART

async def get_part(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение части"""
    user_id = update.effective_user.id
    user_data[user_id]['part'] = update.message.text
    await update.message.reply_text("📄 Введи номер страницы:")
    return PAGE

async def get_page(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение страницы"""
    user_id = update.effective_user.id
    user_data[user_id]['page'] = update.message.text
    await update.message.reply_text("✏️ Введи номер задания:")
    return NUMBER

async def get_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение номера задания и поиск решения"""
    user_id = update.effective_user.id
    user_data[user_id]['number'] = update.message.text
    
    await update.message.reply_text("🔍 Ищу решение...")
    
    # Формируем запрос к DeepSeek
    data = user_data[user_id]
    prompt = f"""Найди готовое домашнее задание (ГДЗ) с подробным решением.
Предмет: {data['subject']}
Автор: {data['author']}
Класс: {data['grade']}
Часть: {data['part']}
Страница: {data['page']}
Номер задания: {data['number']}

Предоставь подробное решение с объяснением каждого шага."""

    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.7
        )
        
        solution = response.choices[0].message.content
        
        await update.message.reply_text(
            f"✅ Решение найдено!\n\n{solution}",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка при запросе к DeepSeek: {e}")
        await update.message.reply_text("❌ Произошла ошибка при поиске решения. Попробуй еще раз.")
    
    # Предлагаем начать заново
    keyboard = [
        [InlineKeyboardButton("🔄 Найти другое задание", callback_data="restart")],
        [InlineKeyboardButton("❌ Завершить", callback_data="end")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Что дальше?", reply_markup=reply_markup)
    
    return ConversationHandler.END

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка фото задания"""
    user_id = update.effective_user.id
    
    await update.message.reply_text("🔍 Анализирую изображение...")
    
    try:
        # Получаем фото
        photo = update.message.photo[-1]  # Берем фото наибольшего размера
        file = await context.bot.get_file(photo.file_id)
        
        # Скачиваем фото
        photo_bytes = await file.download_as_bytearray()
        photo_base64 = base64.b64encode(photo_bytes).decode('utf-8')
        
        # Отправляем в DeepSeek Vision
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Определи задание на этом изображении и предоставь подробное решение с объяснением каждого шага. Если это задача из учебника, укажи предмет, автора, класс и номер задания если возможно."
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{photo_base64}"
                            }
                        }
                    ]
                }
            ],
            temperature=0.7
        )
        
        solution = response.choices[0].message.content
        
        await update.message.reply_text(
            f"✅ Решение:\n\n{solution}",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Ошибка при обработке фото: {e}")
        await update.message.reply_text("❌ Не удалось распознать изображение. Попробуй отправить более четкое фото или введи данные вручную.")
    
    # Предлагаем начать заново
    keyboard = [
        [InlineKeyboardButton("🔄 Найти другое задание", callback_data="restart")],
        [InlineKeyboardButton("❌ Завершить", callback_data="end")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Что дальше?", reply_markup=reply_markup)
    
    return ConversationHandler.END

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перезапуск бота"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data[user_id] = {}
    
    keyboard = [
        [InlineKeyboardButton("📝 Ввести данные вручную", callback_data="manual")],
        [InlineKeyboardButton("📷 Определить по фото", callback_data="photo")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.edit_message_text(
        "👋 Давай найдем еще одно решение!\n\n"
        "Как ты хочешь найти решение?",
        reply_markup=reply_markup
    )
    return SUBJECT

async def end(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Завершение работы"""
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("👋 До встречи! Возвращайся, если понадобится помощь с домашним заданием!")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена диалога"""
    user_id = update.effective_user.id
    if user_id in user_data:
        del user_data[user_id]
    
    await update.message.reply_text("❌ Диалог отменен. Используй /start чтобы начать заново.")
    return ConversationHandler.END

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда помощи"""
    await update.message.reply_text(
        "📚 *Помощь по использованию бота:*\n\n"
        "1️⃣ Используй /start чтобы начать\n"
        "2️⃣ Выбери способ поиска:\n"
        "   • 📝 Ввод данных вручную (предмет, автор, класс, часть, страница, номер)\n"
        "   • 📷 Загрузка фото задания\n"
        "3️⃣ Получи подробное решение\n\n"
        "Используй /cancel чтобы отменить текущий диалог",
        parse_mode='Markdown'
    )

def main():
    """Запуск бота"""
    # Создаем приложение
    application = Application.builder().token("8684125903:AAGlja8nj_r3HCb8aZwubOqJ_MAGDFAWCoc").build()
    
    # Создаем обработчик диалога
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            SUBJECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, get_subject),
                CallbackQueryHandler(button_handler)
            ],
            AUTHOR: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_author)],
            GRADE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_grade)],
            PART: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_part)],
            PAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_page)],
            NUMBER: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_number)],
            PHOTO: [MessageHandler(filters.PHOTO, handle_photo)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(restart, pattern='^restart$'),
            CallbackQueryHandler(end, pattern='^end$')
        ],
        allow_reentry=True
    )
    
    # Добавляем обработчики
    application.add_handler(conv_handler)
    application.add_handler(CommandHandler('help', help_command))
    
    # Запускаем бота
    print("🤖 Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
