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
BOT_TOKEN = "8684125903:AAGlja8nj_r3HCb8aZwubOqJ_MAGDFAWCoc"
PIARFLOW_API_KEY = "XIKkM70c5VtJ3PU78j7yqeGjAFwM5zYO"
PIARFLOW_BASE_URL = "https://piarflow.com/v1"

# Замените на ваш реальный числовой Telegram ID
ADMIN_ID = 5356400377  
# =================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- База данных ---
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

init_db()

# --- PiarFlow API (1 задание за раз) ---
async def get_piarflow_task(user_id: int, chat_id: int):
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        # max_sponsors=1 для получения одного задания
        payload = {"user_id": user_id, "chat_id": chat_id, "max_sponsors": 1}
        async with session.post(f"{PIARFLOW_BASE_URL}/sponsors", json=payload, headers=headers) as response:
            return await response.json()

async def check_piarflow_task(user_id: int, link: str):
    async with aiohttp.ClientSession() as session:
        headers = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        payload = {"user_id": user_id, "links": [link]}
        async with session.post(f"{PIARFLOW_BASE_URL}/sponsors/check", json=payload, headers=headers) as response:
            return await response.json()

user_current_task = {}

# --- Форматирование результатов игр (аналог slotmap) ---
def format_game_result(emoji: str, value: int, game_name: str) -> str:
    """Преобразует числовое значение кубика Telegram в красивую строку с эмодзи"""
    if emoji == "🎰":
        if value >= 60: return f"🎰 [{value}] - 🔥🔥🔥 ДЖЕКПОТ!"
        if value >= 40: return f"🎰 [{value}] - 🍒🍒🍒 Отличный выигрыш!"
        return f"🎰 [{value}] - 🍋🍒🍋 Попробуйте еще раз"
    elif emoji == "🎲":
        symbols = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
        return f"🎲 Выпало: {symbols.get(value, value)} ({value})"
    elif emoji == "🎯":
        return f"🎯 Дартс: попадание на {value} из 6"
    elif emoji == "🏀":
        return f"🏀 Бросок: {value} очков"
    elif emoji == "⚽":
        return f"⚽ Удар: {value} из 6"
    elif emoji == "🎳":
        return f"🎳 Сбито кеглей: {value}"
    return f"🎮 Результат: {value}"

# --- Обработчики ---
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
            update_balance(referred_by, stars=5)
            try:
                await bot.send_message(referred_by, f"🎉 По вашей ссылке зарегистрировался друг! +5 ⭐️")
            except Exception:
                pass

    user = get_user(message.from_user.id)
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user[4]}"
    rate = get_setting("exchange_rate")
    
    text = (
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"💰 <b>Твой баланс:</b>\n"
        f"⭐️ Звезды: <code>{user[2]}</code>\n"
        f"🪙 T Coin: <code>{user[3]}</code>\n\n"
        f"🔗 <b>Реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n"
        f"<i>(+5 ⭐️ за каждого друга)</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📋 Взять задание", callback_data="task_get", style="primary"))
    builder.row(InlineKeyboardButton(text="🔄 Обмен валют", callback_data="exchange", style="primary"))
    builder.row(InlineKeyboardButton(text="🎮 Игры (10 видов)", callback_data="games_menu", style="success"))
    if user[6]:
        builder.row(InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin", style="danger"))
        
    await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())

# --- ЗАДАНИЯ (1 за раз) ---
@dp.callback_query(F.data == "task_get")
async def cmd_task_get(callback: CallbackQuery):
    await callback.answer()
    task_data = await get_piarflow_task(callback.from_user.id, callback.from_user.id)
    
    if task_data.get("status") == "ok" and task_data.get("sponsors"):
        sponsor = task_data["sponsors"][0]
        link = sponsor["link"]
        price = sponsor.get("price", 5)
        user_current_task[callback.from_user.id] = {"link": link, "price": price}
        
        text = f"📋 <b>Текущее задание:</b>\n\nПодпишись на канал и получи <b>{price} ⭐️</b>.\n\n🔗 Ссылка:"
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔗 Подписаться", url=link, style="primary"))
        builder.row(InlineKeyboardButton(text="✅ Проверить подписку", callback_data="task_check", style="success"))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu", style="danger"))
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await callback.message.edit_text("🎉 На данный момент заданий нет. Загляни позже!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu", style="primary")]
        ]))

@dp.callback_query(F.data == "task_check")
async def cmd_task_check(callback: CallbackQuery):
    await callback.answer()
    task = user_current_task.get(callback.from_user.id)
    if not task:
        await callback.message.edit_text("❌ Сначала получите задание!")
        return
        
    check_data = await check_piarflow_task(callback.from_user.id, task["link"])
    
    if check_data.get("status") == "ok":
        completed = [s for s in check_data.get("sponsors", []) if s.get("status") == "subscribed"]
        if completed:
            reward = task["price"]
            update_balance(callback.from_user.id, stars=reward)
            user_current_task.pop(callback.from_user.id, None)
            
            text = f"✅ <b>Отлично!</b>\nВам начислено <b>{reward} ⭐️</b>!\n\nХотите взять следующее задание?"
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text="📋 Следующее задание", callback_data="task_get", style="success"))
            builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu", style="primary"))
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        else:
            await callback.answer("⏳ Вы еще не подписались. Подпишитесь и нажмите снова.", show_alert=True)
    else:
        await callback.answer("❌ Ошибка проверки. Попробуйте позже.", show_alert=True)

# --- ОБМЕН ---
@dp.callback_query(F.data == "exchange")
async def cmd_exchange(callback: CallbackQuery):
    await callback.answer()
    user = get_user(callback.from_user.id)
    rate = get_setting("exchange_rate")
    available_tcoin = user[2] // rate
    
    text = (
        f"🔄 <b>Обмен Звезд на T Coin</b>\n\n"
        f"💱 Курс: <code>{rate} ⭐️ = 1 🪙</code>\n"
        f"⭐️ Ваш баланс: <code>{user[2]}</code>\n"
        f"🪙 Доступно для обмена: <code>{available_tcoin}</code>"
    )
    
    builder = InlineKeyboardBuilder()
    if available_tcoin > 0:
        builder.row(InlineKeyboardButton(text=f"🔄 Обменять всё", callback_data=f"do_exchange_{available_tcoin}", style="success"))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu", style="primary"))
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("do_exchange_"))
async def cmd_do_exchange(callback: CallbackQuery):
    await callback.answer()
    amount = int(callback.data.split("_")[-1])
    user = get_user(callback.from_user.id)
    rate = get_setting("exchange_rate")
    stars_to_deduct = amount * rate
    
    if user[2] >= stars_to_deduct:
        update_balance(callback.from_user.id, stars=-stars_to_deduct, tcoin=amount)
        await callback.message.edit_text(f"✅ <b>Успешно!</b>\nСписано: {stars_to_deduct} ⭐️\nНачислено: {amount} 🪙", parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu", style="primary")]
        ]))
    else:
        await callback.answer("❌ Недостаточно средств!", show_alert=True)

# --- ИГРЫ (10 видов с короткими командами) ---
@dp.callback_query(F.data == "games_menu")
async def cmd_games_menu(callback: CallbackQuery):
    await callback.answer()
    text = (
        "🎮 <b>Игровой зал за T Coin</b>\n\n"
        "Используйте команды в чате:\n"
        "1️⃣ 🎰 `/slots` или `/s` - Слоты (до x5)\n"
        "2️⃣ 🎲 `/dice` или `/d` - Кости (Больше/Меньше)\n"
        "3️⃣ 🎯 `/darts` или `/da` - Дартс (В яблочко!)\n"
        "4️⃣ 🏀 `/basket` или `/b` - Баскетбол\n"
        "5️⃣ ⚽ `/foot` или `/f` - Футбол\n"
        "6️⃣ 🎳 `/bowl` или `/bo` - Боулинг\n"
        "7️⃣ 💣 `/mines` или `/m` - Мины (Безопасный кубик)\n"
        "8️⃣ 🗼 `/tower` или `/t` - Башня (Покорение вершины)\n"
        "9️⃣ 🚀 `/crash` или `/c` - Краш (Рискни всем)\n"
        "🔟 💰 `/double` или `/dn` - Удвоение (Только 6)\n\n"
        "<i>Пример: `/s 10` (ставка 10 монет)</i>"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu", style="primary"))
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

# Универсальный обработчик игр
@dp.message(Command("slots", "s", "dice", "d", "darts", "da", "basket", "b", "foot", "f", "bowl", "bo", "mines", "m", "tower", "t", "crash", "c", "double", "dn"))
async def play_game(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        return
        
    args = message.text.split()
    cmd = args[0].replace("/", "").lower()
    
    # Маппинг команд на эмодзи и логику
    games_config = {
        "slots": {"emoji": "🎰", "name": "Слоты", "win": lambda v: (v >= 60, 5 if v >= 60 else (2 if v >= 40 else 0))},
        "s": {"emoji": "🎰", "name": "Слоты", "win": lambda v: (v >= 60, 5 if v >= 60 else (2 if v >= 40 else 0))},
        "dice": {"emoji": "🎲", "name": "Кости", "win": lambda v: (v >= 4, 2)},
        "d": {"emoji": "🎲", "name": "Кости", "win": lambda v: (v >= 4, 2)},
        "darts": {"emoji": "🎯", "name": "Дартс", "win": lambda v: (v == 6, 5 if v == 6 else (2 if v == 5 else 0))},
        "da": {"emoji": "🎯", "name": "Дартс", "win": lambda v: (v == 6, 5 if v == 6 else (2 if v == 5 else 0))},
        "basket": {"emoji": "🏀", "name": "Баскетбол", "win": lambda v: (v >= 4, 2)},
        "b": {"emoji": "🏀", "name": "Баскетбол", "win": lambda v: (v >= 4, 2)},
        "foot": {"emoji": "⚽", "name": "Футбол", "win": lambda v: (v >= 4, 2)},
        "f": {"emoji": "⚽", "name": "Футбол", "win": lambda v: (v >= 4, 2)},
        "bowl": {"emoji": "🎳", "name": "Боулинг", "win": lambda v: (v == 6, 3)},
        "bo": {"emoji": "🎳", "name": "Боулинг", "win": lambda v: (v == 6, 3)},
        "mines": {"emoji": "🎲", "name": "Мины", "win": lambda v: (v >= 3, 2)}, # 1-2 = мина, 3-6 = безопасно
        "m": {"emoji": "🎲", "name": "Мины", "win": lambda v: (v >= 3, 2)},
        "tower": {"emoji": "🎯", "name": "Башня", "win": lambda v: (v >= 5, 2)},
        "t": {"emoji": "🎯", "name": "Башня", "win": lambda v: (v >= 5, 2)},
        "crash": {"emoji": "🎲", "name": "Краш", "win": lambda v: (v == 6, 3)},
        "c": {"emoji": "🎲", "name": "Краш", "win": lambda v: (v == 6, 3)},
        "double": {"emoji": "🎲", "name": "Удвоение", "win": lambda v: (v == 6, 5)},
        "dn": {"emoji": "🎲", "name": "Удвоение", "win": lambda v: (v == 6, 5)},
    }
    
    config = games_config.get(cmd)
    if not config:
        return
        
    if len(args) < 2:
        await message.answer(f"⚠️ Укажите ставку!\nПример: <code>/{cmd} 10</code>", parse_mode="HTML")
        return
        
    try:
        bet = int(args[1])
    except ValueError:
        await message.answer("❌ Ставка должна быть числом!")
        return
        
    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше 0!")
        return
        
    if user[3] < bet:
        await message.answer("❌ Недостаточно T Coin!")
        return
        
    # Списываем ставку
    update_balance(message.from_user.id, tcoin=-bet)
    
    # Отправляем анимированный кубик
    dice_msg = await message.answer_dice(emoji=config["emoji"])
    value = dice_msg.dice.value
    
    # Проверяем выигрыш
    is_win, multiplier = config["win"](value)
    result_text = format_game_result(config["emoji"], value, config["name"])
    
    if is_win:
        winnings = bet * multiplier
        update_balance(message.from_user.id, tcoin=winnings)
        await message.answer(
            f"{result_text}\n\n🎉 <b>ПОБЕДА!</b>\nСтавка: {bet} 🪙\nМножитель: x{multiplier}\nВыигрыш: <b>{winnings} 🪙</b>",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"{result_text}\n\n😔 <b>Проигрыш.</b>\nВы потеряли {bet} 🪙. Попробуйте еще раз!",
            parse_mode="HTML"
        )

# --- АДМИН-ПАНЕЛЬ ---
@dp.callback_query(F.data == "admin")
async def cmd_admin(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or not user[6]:
        await callback.answer("❌ Нет прав!", show_alert=True)
        return
        
    text = (
        "👑 <b>Админ-панель</b>\n\n"
        "Команды в чате:\n"
        "• `/addstars <id> <кол-во>`\n"
        "• `/addtcoin <id> <кол-во>`\n"
        "• `/reset <id>` - Сбросить баланс игрока в 0\n"
        "• `/setrate <число>` - Изменить курс обмена\n"
        "• `/makeadmin <id> <1/0>` - Выдать/снять админку\n"
        "• `/stats` - Статистика бота"
    )
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu", style="primary"))
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(Command("addstars", "addtcoin", "reset", "setrate", "makeadmin", "stats"))
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
        await message.answer(
            f"📊 <b>Статистика:</b>\n"
            f"👥 Пользователей: {total_users or 0}\n"
            f"⭐️ Всего Звезд: {total_stars or 0}\n"
            f"🪙 Всего T Coin: {total_tcoin or 0}",
            parse_mode="HTML"
        )
        return
        
    if cmd in ["addstars", "addtcoin", "reset", "makeadmin"]:
        if len(args) < 2:
            await message.answer(f"⚠️ Использование: `/{cmd} <user_id> [значение]`")
            return
        try:
            target_id = int(args[1])
            val = int(args[2]) if len(args) > 2 and cmd != "reset" else 0
        except ValueError:
            await message.answer("❌ Ошибка формата. ID должен быть числом.")
            return
            
        if cmd == "addstars":
            update_balance(target_id, stars=val)
            await message.answer(f"✅ Начислено {val} ⭐️ пользователю {target_id}")
        elif cmd == "addtcoin":
            update_balance(target_id, tcoin=val)
            await message.answer(f"✅ Начислено {val} 🪙 пользователю {target_id}")
        elif cmd == "reset":
            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET stars_balance=0, tcoin_balance=0 WHERE user_id=?", (target_id,))
            conn.commit()
            conn.close()
            await message.answer(f"🔄 Баланс пользователя {target_id} полностью сброшен.")
        elif cmd == "makeadmin":
            if val not in [0, 1]:
                await message.answer("❌ Значение должно быть 0 или 1")
                return
            conn = sqlite3.connect("bot_database.db")
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_admin=? WHERE user_id=?", (val, target_id))
            conn.commit()
            conn.close()
            await message.answer(f"✅ Права админа пользователя {target_id} изменены на {val}")
            
    elif cmd == "setrate":
        if len(args) < 2:
            await message.answer("⚠️ Использование: `/setrate <новое_значение>`")
            return
        try:
            new_rate = int(args[1])
            if new_rate <= 0:
                raise ValueError
            set_setting("exchange_rate", str(new_rate))
            await message.answer(f"✅ Курс обмена изменен: <code>{new_rate} ⭐️ = 1 🪙</code>", parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Значение должно быть положительным числом.")

@dp.callback_query(F.data == "back_to_menu")
async def cmd_back(callback: CallbackQuery):
    await callback.answer()
    # Имитируем команду /start для возврата в главное меню
    callback.message.text = "/start"
    await cmd_start(callback.message)

async def main():
    print("✅ Бот успешно запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
