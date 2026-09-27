import asyncio
import logging
import random
import sqlite3
import aiohttp
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================= КОНФИГУРАЦИЯ =================
# Замените на токен вашего бота от @BotFather
BOT_TOKEN = "8684125903:AAGlja8nj_r3HCb8aZwubOqJ_MAGDFAWCoc" 

# Ваш API ключ из PiarFlow (или токен, указанный в запросе)
PIARFLOW_API_KEY = "XIKkM70c5VtJ3PU78j7yqeGjAFwM5zYO"
PIARFLOW_BASE_URL = "https://piarflow.com/v1" # Актуальный базовый URL API [[1]]

# Курс обмена: 10 Звезд = 1 T Coin
EXCHANGE_RATE = 10

# Замените на ваш реальный числовой Telegram ID для доступа к админ-панели
ADMIN_ID = 5356400377  
# =================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- База данных (SQLite) ---
def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            stars_balance INTEGER DEFAULT 0,
            tcoin_balance INTEGER DEFAULT 0,
            referral_code TEXT,
            referred_by INTEGER,
            is_admin INTEGER DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def create_user(user_id: int, username: str, referral_code: str, referred_by: int = None):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username, referral_code, referred_by, is_admin)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, username, referral_code, referred_by, 1 if user_id == ADMIN_ID else 0))
    conn.commit()
    conn.close()

def update_balance(user_id: int, stars: int = 0, tcoin: int = 0):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE users 
        SET stars_balance = stars_balance + ?, tcoin_balance = tcoin_balance + ?
        WHERE user_id = ?
    """, (stars, tcoin, user_id))
    conn.commit()
    conn.close()

def set_admin(user_id: int, is_admin: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_admin = ? WHERE user_id = ?", (is_admin, user_id))
    conn.commit()
    conn.close()

init_db()

# --- Интеграция с PiarFlow API ---
async def get_piarflow_tasks(user_id: int, chat_id: int):
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        payload = {"user_id": user_id, "chat_id": chat_id, "max_sponsors": 5}
        async with session.post(f"{PIARFLOW_BASE_URL}/sponsors", json=payload, headers=headers) as response:
            return await response.json()

async def check_piarflow_tasks(user_id: int, links: list):
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        payload = {"user_id": user_id, "links": links}
        async with session.post(f"{PIARFLOW_BASE_URL}/sponsors/check", json=payload, headers=headers) as response:
            return await response.json()

# Временное хранилище для ссылок заданий (в продакшене рекомендуется использовать Redis или FSM aiogram)
user_tasks = {}

# --- Обработчики команд ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        ref_code = f"ref_{message.from_user.id}"
        referred_by = None
        args = message.text.split()
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                referred_by = int(args[1].replace("ref_", ""))
            except ValueError:
                pass
        
        create_user(message.from_user.id, message.from_user.username or "User", ref_code, referred_by)
        if referred_by:
            update_balance(referred_by, stars=5) # Бонус рефереру
            try:
                await bot.send_message(referred_by, f"🎉 По вашей ссылке зарегистрировался новый пользователь! Вам начислено 5 ⭐️.")
            except Exception:
                pass

    user = get_user(message.from_user.id)
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user[4]}"
    
    text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"💰 Твой баланс:\n"
        f"⭐️ Звезды: {user[2]}\n"
        f"🪙 T Coin: {user[3]}\n\n"
        f"🔗 Твоя реферальная ссылка:\n"
        f"`{ref_link}`\n"
        f"(За каждого друга ты получаешь 5 ⭐️)\n\n"
        f"Используй кнопки ниже для управления!"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📋 Выполнить задания", callback_data="tasks"))
    builder.row(InlineKeyboardButton(text="🔄 Обмен Звезд на T Coin", callback_data="exchange"))
    builder.row(InlineKeyboardButton(text="🎮 Игры в чате", callback_data="games"))
    if user[6]:
        builder.row(InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin"))
        
    await message.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.callback_query(F.data == "tasks")
async def cmd_tasks(callback: CallbackQuery):
    await callback.answer()
    tasks_data = await get_piarflow_tasks(callback.from_user.id, callback.from_user.id)
    
    if tasks_data.get("status") == "ok" and tasks_data.get("sponsors"):
        text = "📋 Доступные задания:\n\n"
        builder = InlineKeyboardBuilder()
        links = []
        
        for idx, sponsor in enumerate(tasks_data["sponsors"]):
            price = sponsor.get('price', 1)
            text += f"{idx+1}. Подпишись и получи {price} ⭐️\n"
            links.append(sponsor["link"])
            builder.row(InlineKeyboardButton(text=f"🔗 Задание {idx+1}", url=sponsor["link"]))
            
        user_tasks[callback.from_user.id] = links
        builder.row(InlineKeyboardButton(text="✅ Проверить выполнение", callback_data="check_tasks"))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
        
        await callback.message.edit_text(text, reply_markup=builder.as_markup())
    else:
        await callback.message.edit_text("🎉 На данный момент заданий нет. Загляни позже!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ]))

@dp.callback_query(F.data == "check_tasks")
async def cmd_check_tasks(callback: CallbackQuery):
    await callback.answer()
    links = user_tasks.get(callback.from_user.id, [])
    if not links:
        await callback.message.edit_text("❌ Сначала получите задания!")
        return
        
    check_data = await check_piarflow_tasks(callback.from_user.id, links)
    
    if check_data.get("status") == "ok":
        completed = [s for s in check_data.get("sponsors", []) if s.get("status") == "subscribed"]
        if completed:
            reward = len(completed) * 5 # 5 звезд за каждое выполненное задание
            update_balance(callback.from_user.id, stars=reward)
            await callback.message.edit_text(f"✅ Отлично! Вы выполнили {len(completed)} заданий.\nВам начислено {reward} ⭐️!")
            user_tasks.pop(callback.from_user.id, None)
        else:
            await callback.message.edit_text("⏳ Задания еще не выполнены. Подпишитесь на каналы и нажмите 'Проверить' снова.")
    else:
        await callback.message.edit_text("❌ Ошибка при проверке заданий. Попробуйте позже.")

@dp.callback_query(F.data == "exchange")
async def cmd_exchange(callback: CallbackQuery):
    await callback.answer()
    user = get_user(callback.from_user.id)
    stars = user[2]
    available_tcoin = stars // EXCHANGE_RATE
    
    text = (
        f"🔄 Обмен Звезд на T Coin\n"
        f"Курс: {EXCHANGE_RATE} ⭐️ = 1 🪙 T Coin\n\n"
        f"Ваш баланс: {stars} ⭐️\n"
        f"Доступно для обмена: {available_tcoin} 🪙\n\n"
        f"Нажмите кнопку ниже, чтобы обменять все доступные Звезды."
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text=f"Обменять {available_tcoin} 🪙", callback_data="do_exchange"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@dp.callback_query(F.data == "do_exchange")
async def cmd_do_exchange(callback: CallbackQuery):
    await callback.answer()
    user = get_user(callback.from_user.id)
    stars = user[2]
    
    if stars >= EXCHANGE_RATE:
        exchange_amount = stars // EXCHANGE_RATE
        stars_to_deduct = exchange_amount * EXCHANGE_RATE
        
        update_balance(callback.from_user.id, stars=-stars_to_deduct, tcoin=exchange_amount)
        await callback.message.edit_text(f"✅ Успешно обменено!\nСписано: {stars_to_deduct} ⭐️\nНачислено: {exchange_amount} 🪙 T Coin")
    else:
        await callback.message.edit_text(f"❌ Недостаточно Звезд для обмена. Нужно минимум {EXCHANGE_RATE} ⭐️.")

@dp.callback_query(F.data == "games")
async def cmd_games(callback: CallbackQuery):
    await callback.answer()
    text = (
        "🎮 Игры за T Coin прямо в чате!\n\n"
        "🎰 `/play slots <ставка>` - Слоты (шанс на x2 или x5)\n"
        "🪙 `/play coinflip <ставка>` - Орел или Решка (шанс 50%, выплата x2)\n\n"
        "Минимальная ставка: 1 🪙\nПример: `/play coinflip 10`"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
    await callback.message.edit_text(text, reply_markup=builder.as_markup())

@dp.message(Command("play"))
async def cmd_play(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        return
        
    args = message.text.split()
    if len(args) < 3:
        await message.answer("⚠️ Использование: `/play <игра> <ставка>`\nПример: `/play coinflip 10`")
        return
        
    game_type = args[1].lower()
    try:
        bet = int(args[2])
    except ValueError:
        await message.answer("❌ Ставка должна быть числом!")
        return
        
    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше 0!")
        return
        
    if user[3] < bet:
        await message.answer("❌ Недостаточно T Coin для этой ставки!")
        return
        
    update_balance(message.from_user.id, tcoin=-bet)
    
    if game_type == "coinflip":
        win = random.choice([True, False])
        if win:
            winnings = bet * 2
            update_balance(message.from_user.id, tcoin=winnings)
            await message.answer(f"🪙 Монетка подброшена...\n🎉 Выпал выигрыш! Вы получили {winnings} 🪙 T Coin!")
        else:
            await message.answer(f"🪙 Монетка подброшена...\n😔 Не повезло. Вы проиграли {bet} 🪙 T Coin.")
            
    elif game_type == "slots":
        slots = [random.randint(1, 5) for _ in range(3)]
        await message.answer(f"🎰 Крутим барабаны: [{slots[0]}] [{slots[1]}] [{slots[2]}]")
        
        if slots[0] == slots[1] == slots[2]:
            winnings = bet * 5
            update_balance(message.from_user.id, tcoin=winnings)
            await message.answer(f"🎉 ДЖЕКПОТ! Вы получили {winnings} 🪙 T Coin!")
        elif slots[0] == slots[1] or slots[1] == slots[2] or slots[0] == slots[2]:
            winnings = bet * 2
            update_balance(message.from_user.id, tcoin=winnings)
            await message.answer(f"✅ Пара совпала! Вы получили {winnings} 🪙 T Coin!")
        else:
            await message.answer(f"😔 Нет совпадений. Вы проиграли {bet} 🪙 T Coin.")
    else:
        await message.answer("❌ Неизвестная игра. Доступны: `slots`, `coinflip`")

@dp.callback_query(F.data == "admin")
async def cmd_admin(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or not user[6]:
        await callback.answer("❌ У вас нет прав администратора!", show_alert=True)
        return
        
    text = (
        "👑 Админ-панель\n\n"
        "Доступные команды в чате:\n"
        "`/add_stars <user_id> <кол-во>` - добавить Звезды\n"
        "`/add_tcoin <user_id> <кол-во>` - добавить T Coin\n"
        "`/set_admin <user_id> <1/0>` - выдать/снять права админа\n"
        "`/stats` - общая статистика бота"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())

@dp.message(Command("add_stars", "add_tcoin", "set_admin", "stats"))
async def cmd_admin_actions(message: Message):
    user = get_user(message.from_user.id)
    if not user or not user[6]:
        return
        
    args = message.text.split()
    cmd = args[0].replace("/", "")
    
    if cmd == "stats":
        conn = sqlite3.connect("bot_database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*), SUM(stars_balance), SUM(tcoin_balance) FROM users")
        total_users, total_stars, total_tcoin = cursor.fetchone()
        conn.close()
        await message.answer(f"📊 Статистика бота:\n👥 Пользователей: {total_users or 0}\n⭐️ Всего Звезд: {total_stars or 0}\n🪙 Всего T Coin: {total_tcoin or 0}")
        return
        
    if len(args) < 3:
        await message.answer(f"⚠️ Использование: `/{cmd} <user_id> <значение>`")
        return
        
    try:
        target_user_id = int(args[1])
        value = int(args[2])
    except ValueError:
        await message.answer("❌ Неверный формат. ID и значение должны быть числами.")
        return
        
    if cmd == "add_stars":
        update_balance(target_user_id, stars=value)
        await message.answer(f"✅ Начислено {value} ⭐️ пользователю {target_user_id}")
    elif cmd == "add_tcoin":
        update_balance(target_user_id, tcoin=value)
        await message.answer(f"✅ Начислено {value} 🪙 пользователю {target_user_id}")
    elif cmd == "set_admin":
        if value not in [0, 1]:
            await message.answer("❌ Значение должно быть 0 или 1")
            return
        set_admin(target_user_id, value)
        await message.answer(f"✅ Права администратора пользователя {target_user_id} изменены на {value}")

@dp.callback_query(F.data == "back_to_menu")
async def cmd_back(callback: CallbackQuery):
    await callback.answer()
    user = get_user(callback.from_user.id)
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user[4]}"
    text = (
        f"👋 Привет, {callback.from_user.first_name}!\n\n"
        f"💰 Твой баланс:\n"
        f"⭐️ Звезды: {user[2]}\n"
        f"🪙 T Coin: {user[3]}\n\n"
        f"🔗 Твоя реферальная ссылка:\n"
        f"`{ref_link}`"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📋 Выполнить задания", callback_data="tasks"))
    builder.row(InlineKeyboardButton(text="🔄 Обмен Звезд на T Coin", callback_data="exchange"))
    builder.row(InlineKeyboardButton(text="🎮 Игры в чате", callback_data="games"))
    if user[6]:
        builder.row(InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin"))
        
    await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=builder.as_markup())

async def main():
    print("✅ Бот успешно запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
