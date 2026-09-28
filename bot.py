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
BOT_TOKEN = "8996813076:AAHgcyCWj6l2x3H7xWuW4HCLUkmT8lVRizs"
PIARFLOW_API_KEY = "XIKkM70c5VtJ3PU78j7yqeGjAFwM5zYO"
PIARFLOW_BASE_URL = "https://piarflow.com/v1"
ADMIN_ID = 5356400377  # Замените на ваш реальный ID

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= ИМИТАЦИЯ slotmap =================
# (Встроено, чтобы код работал сразу без pip install несуществующих библиотек)
def get_slot_combination(dice_value: int, symbols: dict = None) -> str:
    default_symbols = {1: '🍒', 2: '🍋', 3: '🍇', 4: '💎', 5: '🔔', 6: '7️⃣'}
    syms = symbols or default_symbols
    
    # Генерируем псевдо-комбинацию на основе значения кости (1-64)
    # Для простоты используем 3 символа, зависящих от значения
    c1 = syms.get((dice_value % 6) + 1, '❓')
    c2 = syms.get(((dice_value // 6) % 6) + 1, '❓')
    c3 = syms.get(((dice_value // 36) % 6) + 1, '❓')
    return f"{c1} {c2} {c3}"

# ================= БАЗА ДАННЫХ =================
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('exchange_rate', '10')")
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

def get_setting(key: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = cursor.fetchone()
    conn.close()
    return int(res[0]) if res else 0

def set_setting(key: str, value: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def reset_user(user_id: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET stars_balance = 0, tcoin_balance = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

init_db()

# Хранилище текущего задания для пользователя (в памяти)
user_current_task = {}

# ================= PIARFLOW API =================
async def get_one_piarflow_task(user_id: int, chat_id: int):
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        payload = {"user_id": user_id, "chat_id": chat_id, "max_sponsors": 5}
        async with session.post(f"{PIARFLOW_BASE_URL}/sponsors", json=payload, headers=headers) as response:
            data = await response.json()
            if data.get("status") == "ok" and data.get("sponsors"):
                # Берем первое невыполненное задание
                for task in data["sponsors"]:
                    if task.get("status") == "unsubscribed":
                        return task
            return None

async def check_piarflow_task(user_id: int, link: str):
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        payload = {"user_id": user_id, "links": [link]}
        async with session.post(f"{PIARFLOW_BASE_URL}/sponsors/check", json=payload, headers=headers) as response:
            data = await response.json()
            if data.get("status") == "ok" and data.get("sponsors"):
                return data["sponsors"][0].get("status") == "subscribed"
            return False

# ================= ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ UI =================
def get_main_kb(user):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📋 Задания", callback_data="tasks", style="primary"))
    builder.row(InlineKeyboardButton(text="🔄 Обмен", callback_data="exchange", style="secondary"))
    builder.row(InlineKeyboardButton(text="🎮 Игры", callback_data="games", style="success"))
    if user and user[6]:
        builder.row(InlineKeyboardButton(text="👑 Админ", callback_data="admin", style="danger"))
    return builder.as_markup()

# ================= ОБРАБОТЧИКИ: СТАРТ И МЕНЮ =================
@dp.message(Command("start", "s"))
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
            update_balance(referred_by, stars=5)
            try:
                await bot.send_message(referred_by, f"🎉 По вашей ссылке зарегистрировался друг! +5 ⭐️")
            except Exception:
                pass
        user = get_user(message.from_user.id)

    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user[4]}"
    
    text = (
        f"👋 *Привет, {message.from_user.first_name}!*\n\n"
        f"💰 *Твой баланс:*\n"
        f"⭐️ Звезды: `{user[2]}`\n"
        f"🪙 T Coin: `{user[3]}`\n\n"
        f"🔗 *Реферальная ссылка:*\n"
        f"`{ref_link}`\n"
        f"_(+5 ⭐️ за каждого друга)_\n\n"
        f"Используй короткие команды:\n"
        f"`/s` - Меню | `/t` - Задания\n"
        f"`/e` - Обмен | `/g` - Игры"
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=get_main_kb(user))

@dp.callback_query(F.data == "back_to_menu")
async def cmd_back(callback: CallbackQuery):
    await callback.answer()
    user = get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"🏠 *Главное меню*\n\n⭐️: `{user[2]}` | 🪙: `{user[3]}`",
        parse_mode="Markdown",
        reply_markup=get_main_kb(user)
    )

# ================= ОБРАБОТЧИКИ: ЗАДАНИЯ (ПО 1) =================
@dp.message(Command("tasks", "t"))
@dp.callback_query(F.data == "tasks")
async def cmd_tasks(event):
    user_id = event.from_user.id
    is_msg = isinstance(event, Message)
    
    task = await get_one_piarflow_task(user_id, user_id)
    
    if not task:
        text = "🎉 На данный момент новых заданий нет! Загляни позже."
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu", style="secondary"))
        if is_msg:
            await event.answer(text, reply_markup=kb.as_markup())
        else:
            await event.message.edit_text(text, reply_markup=kb.as_markup())
            await event.answer()
        return

    user_current_task[user_id] = task["link"]
    price = task.get('price', 5)
    
    text = (
        f"📋 *Активное задание*\n\n"
        f"🎯 Подпишись на канал и получи *{price} ⭐️*\n\n"
        f"Нажми кнопку ниже, чтобы перейти к каналу."
    )
    
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔗 Подписаться", url=task["link"]))
    kb.row(InlineKeyboardButton(text="✅ Проверить выполнение", callback_data="check_task"))
    kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu", style="secondary"))
    
    if is_msg:
        await event.answer(text, parse_mode="Markdown", reply_markup=kb.as_markup())
    else:
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=kb.as_markup())
        await event.answer()

@dp.callback_query(F.data == "check_task")
async def cmd_check_task(callback: CallbackQuery):
    await callback.answer()
    user_id = callback.from_user.id
    link = user_current_task.get(user_id)
    
    if not link:
        await callback.message.edit_text("❌ Ошибка: задание не найдено.")
        return

    is_subscribed = await check_piarflow_task(user_id, link)
    
    if is_subscribed:
        reward = 5 # Можно парсить из API, но для надежности ставим 5
        update_balance(user_id, stars=reward)
        
        text = f"✅ *Отлично!* Задание выполнено.\nВам начислено *{reward} ⭐️*!"
        kb = InlineKeyboardBuilder()
        kb.row(InlineKeyboardButton(text="📋 Следующее задание", callback_data="tasks", style="success"))
        kb.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu", style="secondary"))
        
        user_current_task.pop(user_id, None)
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=kb.as_markup())
    else:
        await callback.answer("⏳ Вы еще не подписались! Подпишитесь и нажмите 'Проверить' снова.", show_alert=True)

# ================= ОБРАБОТЧИКИ: ОБМЕН =================
@dp.message(Command("exchange", "e"))
@dp.callback_query(F.data == "exchange")
async def cmd_exchange(event):
    user_id = event.from_user.id if isinstance(event, CallbackQuery) else event.from_user.id
    is_msg = isinstance(event, Message)
    
    user = get_user(user_id)
    rate = get_setting("exchange_rate")
    available_tcoin = user[2] // rate
    
    text = (
        f"🔄 *Обмен валют*\n\n"
        f"💱 Курс: *{rate} ⭐️ = 1 🪙 T Coin*\n"
        f"⭐️ Ваш баланс: `{user[2]}`\n"
        f"🪙 Доступно для обмена: `{available_tcoin}`\n\n"
        f"Нажмите кнопку, чтобы обменять всё доступное."
    )
    
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=f"🔄 Обменять {available_tcoin} 🪙", callback_data="do_exchange", style="success"))
    kb.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu", style="secondary"))
    
    if is_msg:
        await event.answer(text, parse_mode="Markdown", reply_markup=kb.as_markup())
    else:
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=kb.as_markup())
        await event.answer()

@dp.callback_query(F.data == "do_exchange")
async def cmd_do_exchange(callback: CallbackQuery):
    await callback.answer()
    user = get_user(callback.from_user.id)
    rate = get_setting("exchange_rate")
    
    if user[2] >= rate:
        exchange_amount = user[2] // rate
        stars_to_deduct = exchange_amount * rate
        
        update_balance(callback.from_user.id, stars=-stars_to_deduct, tcoin=exchange_amount)
        await callback.message.edit_text(
            f"✅ *Успешно!*\n\nСписано: `{stars_to_deduct}` ⭐️\nНачислено: `{exchange_amount}` 🪙 T Coin",
            parse_mode="Markdown",
            reply_markup=get_main_kb(user)
        )
    else:
        await callback.answer(f"❌ Нужно минимум {rate} ⭐️ для обмена!", show_alert=True)

# ================= ОБРАБОТЧИКИ: 10 ИГР =================
@dp.message(Command("games", "g"))
@dp.callback_query(F.data == "games")
async def cmd_games(event):
    is_msg = isinstance(event, Message)
    text = (
        f"🎮 *Игровой зал*\n\n"
        f"Используйте команды в чате или кнопки:\n"
        f"🎰 `/spin <ставка>` - Слоты (x5 за джекпот)\n"
        f"🎲 `/hi <ставка>` - Кости (Больше 3 = победа x2)\n"
        f"🎯 `/dart <ставка>` - Дартс (6 = победа x5)\n"
        f"🏀 `/bball <ставка>` - Баскетбол (4-5 = победа x2)\n"
        f"⚽ `/foot <ставка>` - Футбол (4-5 = победа x2)\n"
        f"🎳 `/bowl <ставка>` - Боулинг (6 = страйк x3)\n"
        f"💣 `/mines <ставка>` - Мины (3-6 = безопасно x1.5)\n"
        f"🗼 `/tower <ставка>` - Башня (3 успешных броска x3)\n"
        f"📈 `/crash <ставка>` - Краш (Множитель до x5)\n"
        f"🎡 `/roulette <ставка> <цвет>` - Рулетка (red/black x2)"
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu", style="secondary"))
    
    if is_msg:
        await event.answer(text, parse_mode="Markdown", reply_markup=kb.as_markup())
    else:
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=kb.as_markup())
        await event.answer()

# Вспомогательная функция для проверки ставки
def process_bet(message: Message, game_name: str) -> tuple:
    user = get_user(message.from_user.id)
    args = message.text.split()
    if len(args) < 2:
        return None, None, f"⚠️ Использование: `/{game_name} <ставка>`"
    try:
        bet = int(args[1])
    except ValueError:
        return None, None, "❌ Ставка должна быть числом!"
    if bet <= 0:
        return None, None, "❌ Ставка должна быть больше 0!"
    if user[3] < bet:
        return None, None, f"❌ Недостаточно T Coin! Ваш баланс: {user[3]} 🪙"
    
    update_balance(message.from_user.id, tcoin=-bet)
    return user, bet, None

# 1. Слоты (с использованием вашего кода)
@dp.message(Command("spin"))
async def spin_slot(message: Message):
    user, bet, err = process_bet(message, "spin")
    if err: return await message.answer(err)
    
    slot_message = await message.answer_dice(emoji="🎰")
    dice_value = slot_message.dice.value
    
    MY_SYMBOLS = {'1': '🍒', '2': '🍋', '3': '🍇', '4': '💎', '5': '🔔', '6': '7️⃣'}
    # Адаптируем функцию под наши символы
    combo = get_slot_combination(dice_value, symbols=MY_SYMBOLS)
    
    if dice_value > 50: # Условный джекпот
        win = bet * 5
        update_balance(message.from_user.id, tcoin=win)
        await message.answer(f"🎰 {combo}\n🎉 *ДЖЕКПОТ!* Вы выиграли `{win}` 🪙!", parse_mode="Markdown")
    elif dice_value > 30:
        win = bet * 2
        update_balance(message.from_user.id, tcoin=win)
        await message.answer(f"🎰 {combo}\n✅ Победа! Вы выиграли `{win}` 🪙!", parse_mode="Markdown")
    else:
        await message.answer(f"🎰 {combo}\n😔 Не повезло. Вы проиграли `{bet}` 🪙.", parse_mode="Markdown")

# 2. Кости (Hi/Lo)
@dp.message(Command("hi"))
async def game_dice(message: Message):
    user, bet, err = process_bet(message, "hi")
    if err: return await message.answer(err)
    
    dice_msg = await message.answer_dice(emoji="🎲")
    val = dice_msg.dice.value
    if val >= 4:
        win = bet * 2
        update_balance(message.from_user.id, tcoin=win)
        await message.answer(f"🎲 Выпало: *{val}*\n🎉 Победа! +`{win}` 🪙", parse_mode="Markdown")
    else:
        await message.answer(f"🎲 Выпало: *{val}*\n😔 Проигрыш. -`{bet}` 🪙", parse_mode="Markdown")

# 3. Дартс
@dp.message(Command("dart"))
async def game_dart(message: Message):
    user, bet, err = process_bet(message, "dart")
    if err: return await message.answer(err)
    
    dice_msg = await message.answer_dice(emoji="🎯")
    val = dice_msg.dice.value
    if val == 6:
        win = bet * 5
        update_balance(message.from_user.id, tcoin=win)
        await message.answer(f"🎯 Попадание в яблочко! ({val})\n🎉 +`{win}` 🪙", parse_mode="Markdown")
    else:
        await message.answer(f"🎯 Промах ({val})\n😔 -`{bet}` 🪙", parse_mode="Markdown")

# 4. Баскетбол
@dp.message(Command("bball"))
async def game_bball(message: Message):
    user, bet, err = process_bet(message, "bball")
    if err: return await message.answer(err)
    
    dice_msg = await message.answer_dice(emoji="🏀")
    val = dice_msg.dice.value
    if val >= 4:
        win = bet * 2
        update_balance(message.from_user.id, tcoin=win)
        await message.answer(f"🏀 Попадание! ({val})\n🎉 +`{win}` 🪙", parse_mode="Markdown")
    else:
        await message.answer(f"🏀 Мимо! ({val})\n😔 -`{bet}` 🪙", parse_mode="Markdown")

# 5. Футбол
@dp.message(Command("foot"))
async def game_foot(message: Message):
    user, bet, err = process_bet(message, "foot")
    if err: return await message.answer(err)
    
    dice_msg = await message.answer_dice(emoji="⚽")
    val = dice_msg.dice.value
    if val >= 4:
        win = bet * 2
        update_balance(message.from_user.id, tcoin=win)
        await message.answer(f"⚽ Гол! ({val})\n🎉 +`{win}` 🪙", parse_mode="Markdown")
    else:
        await message.answer(f"⚽ Мимо ворот! ({val})\n😔 -`{bet}` 🪙", parse_mode="Markdown")

# 6. Боулинг
@dp.message(Command("bowl"))
async def game_bowl(message: Message):
    user, bet, err = process_bet(message, "bowl")
    if err: return await message.answer(err)
    
    dice_msg = await message.answer_dice(emoji="🎳")
    val = dice_msg.dice.value
    if val == 6:
        win = bet * 3
        update_balance(message.from_user.id, tcoin=win)
        await message.answer(f"🎳 СТРАЙК! ({val})\n🎉 +`{win}` 🪙", parse_mode="Markdown")
    else:
        await message.answer(f"🎳 Сбито кеглей: {val}\n😔 -`{bet}` 🪙", parse_mode="Markdown")

# 7. Мины (Симуляция на 🎲)
@dp.message(Command("mines"))
async def game_mines(message: Message):
    user, bet, err = process_bet(message, "mines")
    if err: return await message.answer(err)
    
    val = random.randint(1, 6)
    if val >= 3:
        win = int(bet * 1.5)
        update_balance(message.from_user.id, tcoin=win)
        await message.answer(f"💎 Безопасно! ({val})\n🎉 +`{win}` 🪙", parse_mode="Markdown")
    else:
        await message.answer(f"💥 БУМ! Вы наткнулись на мину ({val})\n😔 -`{bet}` 🪙", parse_mode="Markdown")

# 8. Башня (Симуляция: нужно 3 успешных броска подряд)
@dp.message(Command("tower"))
async def game_tower(message: Message):
    user, bet, err = process_bet(message, "tower")
    if err: return await message.answer(err)
    
    await message.answer("🗼 Вы поднимаетесь по башне...")
    await asyncio.sleep(1)
    r1 = random.randint(1, 6)
    await message.answer(f"Этаж 1: 🎲 {r1}")
    if r1 < 3:
        await message.answer(f"😔 Вы упали на 1 этаже! -`{bet}` 🪙", parse_mode="Markdown"); return
    
    await asyncio.sleep(1)
    r2 = random.randint(1, 6)
    await message.answer(f"Этаж 2: 🎲 {r2}")
    if r2 < 3:
        await message.answer(f"😔 Вы упали на 2 этаже! -`{bet}` 🪙", parse_mode="Markdown"); return
        
    await asyncio.sleep(1)
    r3 = random.randint(1, 6)
    await message.answer(f"Этаж 3: 🎲 {r3}")
    if r3 < 3:
        await message.answer(f"😔 Вы упали на вершине! -`{bet}` 🪙", parse_mode="Markdown"); return
        
    win = bet * 3
    update_balance(message.from_user.id, tcoin=win)
    await message.answer(f"🏆 Вы покорили башню! ({r1}-{r2}-{r3})\n🎉 +`{win}` 🪙", parse_mode="Markdown")

# 9. Краш (Симуляция)
@dp.message(Command("crash"))
async def game_crash(message: Message):
    user, bet, err = process_bet(message, "crash")
    if err: return await message.answer(err)
    
    await message.answer("📈 Ракета взлетает...")
    await asyncio.sleep(1)
    multiplier = random.choice([1.1, 1.5, 2.0, 3.0, 5.0, 0.0]) # 0.0 = краш на старте
    
    if multiplier == 0.0:
        await message.answer(f"💥 КРАШ на старте!\n😔 -`{bet}` 🪙", parse_mode="Markdown")
    else:
        win = int(bet * multiplier)
        update_balance(message.from_user.id, tcoin=win)
        await message.answer(f"🚀 Множитель: *x{multiplier}*\n🎉 Вы забрали `{win}` 🪙!", parse_mode="Markdown")

# 10. Рулетка
@dp.message(Command("roulette"))
async def game_roulette(message: Message):
    user = get_user(message.from_user.id)
    args = message.text.split()
    if len(args) < 3:
        return await message.answer("⚠️ Использование: `/roulette <ставка> <red|black>`")
    try:
        bet = int(args[1])
    except ValueError:
        return await message.answer("❌ Ставка должна быть числом!")
        
    color = args[2].lower()
    if color not in ["red", "black"]:
        return await message.answer("❌ Цвет должен быть `red` или `black`")
        
    if user[3] < bet:
        return await message.answer(f"❌ Недостаточно T Coin! Баланс: {user[3]} 🪙")
        
    update_balance(message.from_user.id, tcoin=-bet)
    
    val = random.randint(1, 6)
    result_color = "red" if val <= 3 else "black"
    emoji_color = "🔴" if result_color == "red" else "⚫"
    
    if result_color == color:
        win = bet * 2
        update_balance(message.from_user.id, tcoin=win)
        await message.answer(f"🎡 Выпало: {emoji_color} ({val})\n🎉 Победа! +`{win}` 🪙", parse_mode="Markdown")
    else:
        await message.answer(f"🎡 Выпало: {emoji_color} ({val})\n😔 Проигрыш. -`{bet}` 🪙", parse_mode="Markdown")


# ================= ОБРАБОТЧИКИ: АДМИН =================
@dp.message(Command("admin", "a"))
@dp.callback_query(F.data == "admin")
async def cmd_admin(event):
    user_id = event.from_user.id if isinstance(event, CallbackQuery) else event.from_user.id
    user = get_user(user_id)
    
    if not user or not user[6]:
        if isinstance(event, CallbackQuery):
            await event.answer("❌ У вас нет прав администратора!", show_alert=True)
        else:
            await event.answer("❌ У вас нет прав администратора!")
        return
        
    rate = get_setting("exchange_rate")
    text = (
        f"👑 *Админ-панель*\n\n"
        f"⚙️ Текущий курс обмена: `{rate}` ⭐️ = 1 🪙\n\n"
        f"*Команды:*\n"
        f"`/reset <user_id>` - Сбросить баланс игрока\n"
        f"`/setrate <новое_значение>` - Изменить курс обмена\n"
        f"`/addstars <user_id> <кол-во>` - Начислить Звезды\n"
        f"`/addtcoin <user_id> <кол-во>` - Начислить T Coin\n"
        f"`/stats` - Статистика бота"
    )
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu", style="secondary"))
    
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=kb.as_markup())
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=kb.as_markup())

@dp.message(Command("reset"))
async def admin_reset(message: Message):
    user = get_user(message.from_user.id)
    if not user or not user[6]: return
    
    args = message.text.split()
    if len(args) < 2: return await message.answer("⚠️ `/reset <user_id>`")
    
    try:
        target_id = int(args[1])
    except ValueError:
        return await message.answer("❌ Неверный ID")
        
    reset_user(target_id)
    await message.answer(f"✅ Баланс пользователя `{target_id}` полностью сброшен.", parse_mode="Markdown")

@dp.message(Command("setrate"))
async def admin_setrate(message: Message):
    user = get_user(message.from_user.id)
    if not user or not user[6]: return
    
    args = message.text.split()
    if len(args) < 2: return await message.answer("⚠️ `/setrate <значение>`")
    
    try:
        rate = int(args[1])
        if rate <= 0: raise ValueError
    except ValueError:
        return await message.answer("❌ Курс должен быть положительным числом")
        
    set_setting("exchange_rate", str(rate))
    await message.answer(f"✅ Курс обмена изменен: `{rate}` ⭐️ = 1 🪙", parse_mode="Markdown")

@dp.message(Command("addstars", "addtcoin"))
async def admin_add_balance(message: Message):
    user = get_user(message.from_user.id)
    if not user or not user[6]: return
    
    args = message.text.split()
    if len(args) < 3: return await message.answer(f"⚠️ `/{message.command} <user_id> <кол-во>`")
    
    try:
        target_id = int(args[1])
        amount = int(args[2])
    except ValueError:
        return await message.answer("❌ Неверный формат данных")
        
    if message.command == "addstars":
        update_balance(target_id, stars=amount)
        await message.answer(f"✅ Начислено `{amount}` ⭐️ пользователю `{target_id}`", parse_mode="Markdown")
    else:
        update_balance(target_id, tcoin=amount)
        await message.answer(f"✅ Начислено `{amount}` 🪙 пользователю `{target_id}`", parse_mode="Markdown")

@dp.message(Command("stats"))
async def admin_stats(message: Message):
    user = get_user(message.from_user.id)
    if not user or not user[6]: return
    
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), SUM(stars_balance), SUM(tcoin_balance) FROM users")
    total_users, total_stars, total_tcoin = cursor.fetchone()
    conn.close()
    
    text = (
        f"📊 *Статистика бота*\n\n"
        f"👥 Пользователей: `{total_users or 0}`\n"
        f"⭐️ Всего Звезд: `{total_stars or 0}`\n"
        f"🪙 Всего T Coin: `{total_tcoin or 0}`"
    )
    await message.answer(text, parse_mode="Markdown")

# ================= ЗАПУСК =================
async def main():
    print("✅ Бот успешно запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
