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
from openai import OpenAI, APIConnectionError, APITimeoutError, AuthenticationError, RateLimitError
import base64

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# DeepSeek API клиент
client = OpenAI(
    api_key="sk-c9c29cf3cd1d446aa5a13a7c62ba6ddb",
    base_url="https://api.deepseek.com",
    timeout=30.0
)

# Состояния диалога
SUBJECT, AUTHOR, GRADE, PART, PAGE, NUMBER, PHOTO = range(7)

# Хранилище данных пользователей
user_data = {}

# Флаг доступности API
api_available = False


async def check_api_health() -> tuple[bool, str]:
    """
    Проверка работоспособности DeepSeek API.
    Возвращает (статус, сообщение).
    """
    global api_available
    try:
        # Простой тестовый запрос
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=5,
            temperature=0
        )
        api_available = True
        logger.info("✅ DeepSeek API доступен")
        return True, "✅ DeepSeek API работает корректно"
    except AuthenticationError as e:
        api_available = False
        logger.error(f"❌ Ошибка авторизации: {e}")
        return False, "❌ Ошибка авторизации. Проверь API ключ."
    except APIConnectionError as e:
        api_available = False
        logger.error(f"❌ Нет подключения к API: {e}")
        return False, "❌ Нет подключения к DeepSeek API. Проверь интернет."
    except APITimeoutError as e:
        api_available = False
        logger.error(f"❌ Таймаут API: {e}")
        return False, "❌ Таймаут при обращении к API. Попробуй позже."
    except RateLimitError as e:
        api_available = False
        logger.error(f"❌ Превышен лимит: {e}")
        return False, "❌ Превышен лимит запросов к API."
    except Exception as e:
        api_available = False
        logger.error(f"❌ Неизвестная ошибка: {e}")
        return False, f"❌ Неизвестная ошибка: {str(e)[:100]}"


async def post_init(application: Application):
    """Выполняется после инициализации бота — проверка API"""
    print("🔍 Проверяю работоспособность DeepSeek API...")
    status, message = await check_api_health()
    print(message)
    if not status:
        print("⚠️ Бот запущен, но API недоступен. Некоторые функции могут не работать.")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало работы с ботом"""
    user_id = update.effective_user.id
    user_data[user_id] = {}
    
    # Проверяем API при старте
    status, message = await check_api_health()
    if not status:
        await update.message.reply_text(
            f"{message}\n\n"
            "Попробуй позже или используй /check для повторной проверки."
        )
        return ConversationHandler.END
    
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


async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда ручной проверки работоспособности API"""
    await update.message.reply_text("🔍 Проверяю работоспособность DeepSeek API...")
    status, message = await check_api_health()
    await update.message.reply_text(message)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    user_data[user_id] = {}
    
    # Проверка API перед началом диалога
    status, message = await check_api_health()
    if not status:
        await query.edit_message_text(
            f"{message}\n\nПопробуй позже или используй /check."
        )
        return ConversationHandler.END
    
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


async def call_deepseek_with_retry(prompt: str, max_retries: int = 2) -> tuple[bool, str]:
    """
    Вызов DeepSeek API с повторными попытками.
    Возвращает (успех, результат/ошибка).
    """
    last_error = None
    for attempt in range(max_retries + 1):
        try:
            response = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                timeout=30.0
            )
            return True, response.choices[0].message.content
        except (APIConnectionError, APITimeoutError) as e:
            last_error = e
            logger.warning(f"Попытка {attempt + 1}/{max_retries + 1} не удалась: {e}")
            if attempt < max_retries:
                import asyncio
                await asyncio.sleep(2 ** attempt)  # Экспоненциальная задержка
            continue
        except AuthenticationError:
            return False, "❌ Ошибка авторизации. API ключ недействителен."
        except RateLimitError:
            return False, "❌ Превышен лимит запросов. Попробуй через минуту."
        except Exception as e:
            return False, f"❌ Ошибка: {str(e)[:150]}"
    
    return False, f"❌ API недоступен после {max_retries + 1} попыток: {str(last_error)[:100]}"


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

    success, result = await call_deepseek_with_retry(prompt)
    
    if success:
        await update.message.reply_text(
            f"✅ Решение найдено!\n\n{result}",
            parse_mode='Markdown'
        )
    else:
        await update.message.reply_text(result)
    
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
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        photo_bytes = await file.download_as_bytearray()
        photo_base64 = base64.b64encode(photo_bytes).decode('utf-8')
        
        messages = [
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
        ]
        
        # Попытка с retry
        success = False
        for attempt in range(3):
            try:
                response = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=messages,
                    temperature=0.7,
                    timeout=60.0
                )
                solution = response.choices[0].message.content
                success = True
                break
            except (APIConnectionError, APITimeoutError) as e:
                logger.warning(f"Попытка {attempt + 1} не удалась: {e}")
                if attempt < 2:
                    import asyncio
                    await asyncio.sleep(2 ** attempt)
                continue
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка: {str(e)[:150]}")
                return ConversationHandler.END
        
        if success:
            await update.message.reply_text(
                f"✅ Решение:\n\n{solution}",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Не удалось получить ответ от API после нескольких попыток.")
            
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
    
    # Проверка API
    status, message = await check_api_health()
    if not status:
        await query.edit_message_text(
            f"{message}\n\nПопробуй позже или используй /check."
        )
        return ConversationHandler.END
    
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
        "*Дополнительные команды:*\n"
        "/check — проверить работоспособность ИИ\n"
        "/help — показать эту справку\n"
        "/cancel — отменить текущий диалог",
        parse_mode='Markdown'
    )


def main():
    """Запуск бота"""
    # Создаем приложение с post_init для проверки API
    application = (
        Application.builder()
        .token("8684125903:AAGlja8nj_r3HCb8aZwubOqJ_MAGDFAWCoc")
        .post_init(post_init)
        .build()
    )
    
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
    application.add_handler(CommandHandler('check', check_command))
    
    # Запускаем бота
    print("🤖 Бот запущен!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
