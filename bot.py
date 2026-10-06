import asyncio
import logging
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart

# Токен от @BotFather
BOT_TOKEN = "8996813076:AAEPRaOZ8O6WoIagzMUdnV49K2zP293vyDg"
# Username бота БЕЗ символа @ (например, "my_super_bot")
BOT_USERNAME = "tntgame_chatbot"

async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()

    @dp.message(CommandStart())
    async def cmd_start(message: types.Message):
        await message.answer(
            f"Привет! Я бот @{BOT_USERNAME}.\n"
            "В группе напиши: @бот напиши привет\n"
            "И я напишу 'привет'."
        )

    # Обработчик: реагируем только если в сообщении есть упоминание нашего бота
    @dp.message(F.mention)
    async def handle_mention(message: types.Message):
        # Получаем username упомянутого пользователя (без @)
        mentioned_username = message.mention.lower()

        # Проверяем, что упомянули именно нашего бота
        if mentioned_username != BOT_USERNAME.lower():
            return  # Это упоминание кого-то другого, игнорируем

        # Извлекаем текст после упоминания
        text = message.text or ""
        # Убираем сам mention (@username) из текста
        # В Telegram mention может быть в начале, поэтому ищем его и обрезаем
        mention_str = f"@{BOT_USERNAME}"
        if mention_str.lower() in text.lower():
            # Находим позицию упоминания и берём всё после него
            idx = text.lower().find(mention_str.lower())
            command_text = text[idx + len(mention_str):].strip()
        else:
            command_text = ""

        if not command_text:
            await message.reply("Ты меня позвал, но ничего не сказал 🤔")
            return

        # Парсим простую команду: "напиши X"
        # Пользователь пишет: "@бот напиши старт" -> бот пишет "старт"
        lower_cmd = command_text.lower()
        if lower_cmd.startswith("напиши "):
            # Извлекаем то, что нужно написать
            to_write = command_text[len("напиши "):].strip()
            await message.reply(to_write)
        else:
            # Если команда не распознана — просто эхом повторяем
            await message.reply(f"Вы сказали мне: {command_text}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
