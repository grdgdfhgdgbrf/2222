import asyncio
import logging
import random
import sqlite3
import aiohttp
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

# ================= КОНФИГУРАЦИЯ =================
BOT_TOKEN = "8684125903:AAGlja8nj_r3HCb8aZwubOqJ_MAGDFAWCoc"
PIARFLOW_API_KEY = "XIKkM70c5VtJ3PU78j7yqeGjAFwM5zYO"
PIARFLOW_BASE_URL = "https://piarflow.com/v1"

# Замените на ваш реальный числовой Telegram ID
ADMIN_ID = 5356400377  

# Настройки по умолчанию
DEFAULT_EXCHANGE_RATE = 10
DAILY_BONUS_STARS = 10
DAILY_BONUS_TCOIN = 5
REFERRAL_BONUS = 5
MAX_TASKS_PER_DAY = 10

# Кеш для API запросов
api_cache = {}
cache_ttl = 300  # 5 минут
# =================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= FSM СОСТОЯНИЯ =================
class AdminStates(StatesGroup):
    waiting_for_broadcast = State()
    waiting_for_user_id = State()
    waiting_for_amount = State()
    waiting_for_promo_code = State()
    waiting_for_promo_value = State()

class UserStates(StatesGroup):
    waiting_for_promo_input = State()
# =================================================

# ================= БАЗА ДАННЫХ =================
def init_db():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            stars_balance INTEGER DEFAULT 0,
            tcoin_balance INTEGER DEFAULT 0,
            referral_code TEXT,
            referred_by INTEGER,
            is_admin INTEGER DEFAULT 0,
            is_banned INTEGER DEFAULT 0,
            last_daily_bonus TEXT,
            tasks_completed_today INTEGER DEFAULT 0,
            last_task_date TEXT,
            total_tasks_completed INTEGER DEFAULT 0,
            total_referrals INTEGER DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица настроек
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    
    # Таблица промокодов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            stars_reward INTEGER DEFAULT 0,
            tcoin_reward INTEGER DEFAULT 0,
            max_uses INTEGER DEFAULT 100,
            current_uses INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица использованных промокодов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS used_promo_codes (
            user_id INTEGER,
            promo_code TEXT,
            used_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, promo_code)
        )
    """)
    
    # Таблица транзакций
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount INTEGER,
            description TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Таблица достижений
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            user_id INTEGER,
            achievement_type TEXT,
            unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, achievement_type)
        )
    """)
    
    # Инициализация настроек по умолчанию
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('exchange_rate', ?)", (str(DEFAULT_EXCHANGE_RATE),))
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('bot_active', '1')")
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('maintenance_mode', '0')")
    
    conn.commit()
    conn.close()

def get_user(user_id: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def create_user(user_id: int, username: str, first_name: str, referral_code: str, referred_by: int = None):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO users (user_id, username, first_name, referral_code, referred_by, is_admin)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, username, first_name, referral_code, referred_by, 1 if user_id == ADMIN_ID else 0))
    conn.commit()
    conn.close()

def update_balance(user_id: int, stars: int = 0, tcoin: int = 0, description: str = ""):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    # Обновляем баланс
    cursor.execute("""
        UPDATE users 
        SET stars_balance = stars_balance + ?, tcoin_balance = tcoin_balance + ?
        WHERE user_id = ?
    """, (stars, tcoin, user_id))
    
    # Записываем транзакцию
    if stars != 0:
        cursor.execute("""
            INSERT INTO transactions (user_id, type, amount, description)
            VALUES (?, 'stars', ?, ?)
        """, (user_id, stars, description or ("Изменение баланса звезд" if stars > 0 else "Списание звезд")))
    
    if tcoin != 0:
        cursor.execute("""
            INSERT INTO transactions (user_id, type, amount, description)
            VALUES (?, 'tcoin', ?, ?)
        """, (user_id, tcoin, description or ("Изменение баланса T Coin" if tcoin > 0 else "Списание T Coin")))
    
    conn.commit()
    conn.close()

def get_setting(key: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    res = cursor.fetchone()
    conn.close()
    return res[0] if res else None

def set_setting(key: str, value: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

def ban_user(user_id: int, ban_status: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_banned = ? WHERE user_id = ?", (ban_status, user_id))
    conn.commit()
    conn.close()

def get_promo_code(code: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM promo_codes WHERE code = ? AND is_active = 1", (code,))
    promo = cursor.fetchone()
    conn.close()
    return promo

def use_promo_code(user_id: int, code: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    # Проверяем, не использовал ли пользователь уже этот промокод
    cursor.execute("SELECT * FROM used_promo_codes WHERE user_id = ? AND promo_code = ?", (user_id, code))
    if cursor.fetchone():
        conn.close()
        return False, "already_used"
    
    # Обновляем счетчик использований
    cursor.execute("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE code = ?", (code,))
    
    # Записываем использование
    cursor.execute("INSERT INTO used_promo_codes (user_id, promo_code) VALUES (?, ?)", (user_id, code))
    
    conn.commit()
    conn.close()
    return True, "success"

def create_promo_code(code: str, stars: int, tcoin: int, max_uses: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO promo_codes (code, stars_reward, tcoin_reward, max_uses)
        VALUES (?, ?, ?, ?)
    """, (code, stars, tcoin, max_uses))
    conn.commit()
    conn.close()

def get_user_transactions(user_id: int, limit: int = 10):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT type, amount, description, created_at 
        FROM transactions 
        WHERE user_id = ? 
        ORDER BY created_at DESC 
        LIMIT ?
    """, (user_id, limit))
    transactions = cursor.fetchall()
    conn.close()
    return transactions

def update_daily_bonus(user_id: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET last_daily_bonus = ? WHERE user_id = ?", 
                   (datetime.now().strftime("%Y-%m-%d"), user_id))
    conn.commit()
    conn.close()

def can_claim_daily_bonus(user_id: int) -> bool:
    user = get_user(user_id)
    if not user or not user[9]:  # last_daily_bonus (индекс 9)
        return True
    last_bonus = datetime.strptime(user[9], "%Y-%m-%d")
    return (datetime.now() - last_bonus).days >= 1

def increment_task_count(user_id: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        UPDATE users 
        SET tasks_completed_today = tasks_completed_today + 1,
            last_task_date = ?,
            total_tasks_completed = total_tasks_completed + 1
        WHERE user_id = ?
    """, (today, user_id))
    conn.commit()
    conn.close()

def reset_daily_task_count_for_user(user_id: int):
    """Сбрасывает счетчик заданий для конкретного пользователя"""
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("""
        UPDATE users 
        SET tasks_completed_today = 0
        WHERE user_id = ? AND last_task_date != ?
    """, (user_id, today))
    conn.commit()
    conn.close()

def increment_referral_count(user_id: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET total_referrals = total_referrals + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def unlock_achievement(user_id: int, achievement_type: str):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO achievements (user_id, achievement_type) VALUES (?, ?)", 
                   (user_id, achievement_type))
    conn.commit()
    conn.close()

def get_user_achievements(user_id: int):
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT achievement_type FROM achievements WHERE user_id = ?", (user_id,))
    achievements = [row[0] for row in cursor.fetchall()]
    conn.close()
    return achievements

def get_all_users():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_banned = 0")
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

def get_bot_stats():
    conn = sqlite3.connect("bot_database.db")
    cursor = conn.cursor()
    
    stats = {}
    
    # Общая статистика
    cursor.execute("SELECT COUNT(*) FROM users")
    stats['total_users'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0")
    stats['active_users'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT SUM(stars_balance), SUM(tcoin_balance) FROM users")
    total_stars, total_tcoin = cursor.fetchone()
    stats['total_stars'] = total_stars or 0
    stats['total_tcoin'] = total_tcoin or 0
    
    # Статистика за сегодня
    today = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE DATE(created_at) = ?", (today,))
    stats['transactions_today'] = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at) = ?", (today,))
    stats['new_users_today'] = cursor.fetchone()[0]
    
    # Статистика по промокодам
    cursor.execute("SELECT COUNT(*) FROM promo_codes WHERE is_active = 1")
    stats['active_promos'] = cursor.fetchone()[0]
    
    conn.close()
    return stats

init_db()
# =================================================

# ================= PIARFLOW API =================
async def get_piarflow_task(user_id: int, chat_id: int):
    """Получает одно задание из PiarFlow"""
    cache_key = f"task_{user_id}"
    
    # Проверяем кеш
    if cache_key in api_cache:
        cached_data, timestamp = api_cache[cache_key]
        if datetime.now().timestamp() - timestamp < cache_ttl:
            return cached_data
    
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {PIARFLOW_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {"user_id": user_id, "chat_id": chat_id, "max_sponsors": 1}
        
        try:
            async with session.post(f"{PIARFLOW_BASE_URL}/sponsors", json=payload, headers=headers) as response:
                result = await response.json()
                # Сохраняем в кеш
                api_cache[cache_key] = (result, datetime.now().timestamp())
                return result
        except Exception as e:
            logging.error(f"Error fetching PiarFlow task: {e}")
            return {"status": "error", "message": str(e)}

async def check_piarflow_task(user_id: int, link: str):
    """Проверяет выполнение задания"""
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {PIARFLOW_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {"user_id": user_id, "links": [link]}
        
        try:
            async with session.post(f"{PIARFLOW_BASE_URL}/sponsors/check", json=payload, headers=headers) as response:
                return await response.json()
        except Exception as e:
            logging.error(f"Error checking PiarFlow task: {e}")
            return {"status": "error", "message": str(e)}

# Временное хранилище для текущих заданий
user_current_task: Dict[int, Dict] = {}
# =================================================

# ================= УТИЛИТЫ =================
def format_game_result(emoji: str, value: int) -> str:
    """Форматирует результат игры с эмодзи"""
    if emoji == "🎰":
        if value >= 60:
            return f"🎰 [{value}] - 🔥🔥🔥 ДЖЕКПОТ!"
        elif value >= 40:
            return f"🎰 [{value}] - 🍒🍒🍒 Отличный выигрыш!"
        elif value >= 20:
            return f"🎰 [{value}] - 🍋🍒🍋 Почти!"
        else:
            return f"🎰 [{value}] - 🍋🍋🍋 Не повезло"
    elif emoji == "🎲":
        symbols = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
        return f"🎲 Выпало: {symbols.get(value, value)} ({value})"
    elif emoji == "🎯":
        if value == 6:
            return f"🎯 [{value}] - 🎯 ЯБЛОЧКО!"
        elif value >= 4:
            return f"🎯 [{value}] - 🎯 Отличный бросок!"
        else:
            return f"🎯 [{value}] - 🎯 Попробуйте еще"
    elif emoji == "🏀":
        if value >= 4:
            return f"🏀 [{value}] - 🏀 ПОПАДАНИЕ!"
        else:
            return f"🏀 [{value}] - 🏀 Промах"
    elif emoji == "⚽":
        if value >= 4:
            return f"⚽ [{value}] - ⚽ ГОЛ!"
        else:
            return f"⚽ [{value}] - ⚽ Вратарь спас"
    elif emoji == "🎳":
        if value == 6:
            return f"🎳 [{value}] - 🎳 СТРАЙК!"
        elif value >= 4:
            return f"🎳 [{value}] - 🎳 Отлично!"
        else:
            return f"🎳 [{value}] - 🎳 Слабый бросок"
    return f"🎮 Результат: {value}"

def get_user_level(total_tasks: int) -> Tuple[str, int]:
    """Возвращает уровень пользователя и прогресс до следующего"""
    levels = [
        (0, "🥉 Новичок"),
        (10, "🥈 Опытный"),
        (25, "🥇 Мастер"),
        (50, "💎 Эксперт"),
        (100, "👑 Легенда")
    ]
    
    current_level = levels[0]
    next_level = levels[1] if len(levels) > 1 else levels[0]
    
    for i, (threshold, name) in enumerate(levels):
        if total_tasks >= threshold:
            current_level = (threshold, name)
            if i + 1 < len(levels):
                next_level = levels[i + 1]
            else:
                next_level = current_level
    
    progress = total_tasks - current_level[0]
    needed = next_level[0] - current_level[0]
    
    return current_level[1], int((progress / needed) * 100) if needed > 0 else 100

def format_number(num: int) -> str:
    """Форматирует большие числа"""
    if num >= 1000000:
        return f"{num / 1000000:.1f}M"
    elif num >= 1000:
        return f"{num / 1000:.1f}K"
    return str(num)
# =================================================

# ================= ГЛАВНОЕ МЕНЮ =================
@dp.message(Command("start"))
async def cmd_start(message: Message):
    # Проверка на бан
    user = get_user(message.from_user.id)
    if user and user[8]:  # is_banned
        await message.answer("❌ Вы заблокированы администратором.")
        return
    
    # Проверка режима обслуживания
    maintenance = get_setting("maintenance_mode")
    if maintenance == "1" and message.from_user.id != ADMIN_ID:
        await message.answer("🔧 Бот находится на техническом обслуживании. Попробуйте позже.")
        return
    
    # Регистрация нового пользователя
    if not user:
        ref_code = f"ref_{message.from_user.id}"
        referred_by = None
        args = message.text.split()
        
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                referred_by = int(args[1].replace("ref_", ""))
                if referred_by == message.from_user.id:
                    referred_by = None
            except ValueError:
                pass
        
        create_user(
            message.from_user.id,
            message.from_user.username or "User",
            message.from_user.first_name or "User",
            ref_code,
            referred_by
        )
        
        # Бонус рефереру
        if referred_by:
            update_balance(referred_by, stars=REFERRAL_BONUS, description=f"Реферальный бонус от {message.from_user.id}")
            increment_referral_count(referred_by)
            try:
                await bot.send_message(
                    referred_by,
                    f"🎉 <b>По вашей ссылке зарегистрировался друг!</b>\n\n"
                    f"Вам начислено <b>{REFERRAL_BONUS} ⭐️</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    user = get_user(message.from_user.id)
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user[5]}"  # referral_code
    rate = int(get_setting("exchange_rate"))
    level, progress = get_user_level(user[12])  # total_tasks_completed
    
    text = (
        f"👋 <b>Привет, {message.from_user.first_name}!</b>\n\n"
        f"📊 <b>Ваш профиль:</b>\n"
        f"🎖 Уровень: {level} ({progress}%)\n\n"
        f"💰 <b>Баланс:</b>\n"
        f"⭐️ Звезды: <code>{format_number(user[3])}</code>\n"
        f"🪙 T Coin: <code>{format_number(user[4])}</code>\n\n"
        f"📈 <b>Статистика:</b>\n"
        f"✅ Выполнено заданий: {user[12]}\n"
        f"👥 Приглашено друзей: {user[13]}\n\n"
        f"🔗 <b>Реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n"
        f"<i>(+{REFERRAL_BONUS} ⭐️ за каждого друга)</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="📋 Взять задание", callback_data="task_get"))
    builder.row(InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily_bonus"))
    builder.row(InlineKeyboardButton(text="🔄 Обмен валют", callback_data="exchange"))
    builder.row(InlineKeyboardButton(text="🎮 Игры (10 видов)", callback_data="games_menu"))
    builder.row(InlineKeyboardButton(text="🎟 Промокод", callback_data="promo_enter"))
    builder.row(InlineKeyboardButton(text="📊 История транзакций", callback_data="transactions"))
    
    if user[7]:  # is_admin
        builder.row(InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin"))
    
    await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
# =================================================

# ================= ЕЖЕДНЕВНЫЙ БОНУС =================
@dp.callback_query(F.data == "daily_bonus")
async def cmd_daily_bonus(callback: CallbackQuery):
    await callback.answer()
    
    if can_claim_daily_bonus(callback.from_user.id):
        update_balance(
            callback.from_user.id,
            stars=DAILY_BONUS_STARS,
            tcoin=DAILY_BONUS_TCOIN,
            description="Ежедневный бонус"
        )
        update_daily_bonus(callback.from_user.id)
        
        text = (
            f"🎁 <b>Ежедневный бонус получен!</b>\n\n"
            f"⭐️ +{DAILY_BONUS_STARS} Звезд\n"
            f"🪙 +{DAILY_BONUS_TCOIN} T Coin\n\n"
            f"Возвращайтесь завтра за новым бонусом!"
        )
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu"))
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        user = get_user(callback.from_user.id)
        last_bonus = datetime.strptime(user[9], "%Y-%m-%d")  # last_daily_bonus
        next_bonus = last_bonus + timedelta(days=1)
        time_left = next_bonus - datetime.now()
        hours = time_left.seconds // 3600
        minutes = (time_left.seconds % 3600) // 60
        
        text = (
            f"⏰ <b>Бонус уже получен!</b>\n\n"
            f"Следующий бонус будет доступен через:\n"
            f"🕐 {hours}ч {minutes}мин\n\n"
            f"Возвращайтесь завтра!"
        )
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu"))
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
# =================================================

# ================= ПРОМОКОДЫ =================
@dp.callback_query(F.data == "promo_enter")
async def cmd_promo_enter(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    
    text = (
        "🎟 <b>Ввод промокода</b>\n\n"
        "Отправьте промокод сообщением в чат.\n"
        "Промокоды дают дополнительные бонусы!"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu"))
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await state.set_state(UserStates.waiting_for_promo_input)

@dp.message(UserStates.waiting_for_promo_input)
async def process_promo_code(message: Message, state: FSMContext):
    await state.clear()
    
    code = message.text.strip().upper()
    promo = get_promo_code(code)
    
    if not promo:
        await message.answer("❌ Промокод не найден или неактивен.")
        return
    
    if promo[4] >= promo[3]:  # current_uses >= max_uses
        await message.answer("❌ Промокод исчерпан.")
        return
    
    success, status = use_promo_code(message.from_user.id, code)
    
    if not success:
        if status == "already_used":
            await message.answer("❌ Вы уже использовали этот промокод.")
        return
    
    stars_reward = promo[1]
    tcoin_reward = promo[2]
    
    if stars_reward > 0 or tcoin_reward > 0:
        update_balance(
            message.from_user.id,
            stars=stars_reward,
            tcoin=tcoin_reward,
            description=f"Промокод: {code}"
        )
    
    text = (
        f"✅ <b>Промокод активирован!</b>\n\n"
        f"🎟 Код: <code>{code}</code>\n\n"
    )
    
    if stars_reward > 0:
        text += f"⭐️ +{stars_reward} Звезд\n"
    if tcoin_reward > 0:
        text += f"🪙 +{tcoin_reward} T Coin\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu"))
    
    await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
# =================================================

# ================= ИСТОРИЯ ТРАНЗАКЦИЙ =================
@dp.callback_query(F.data == "transactions")
async def cmd_transactions(callback: CallbackQuery):
    await callback.answer()
    
    transactions = get_user_transactions(callback.from_user.id, limit=10)
    
    if not transactions:
        text = "📊 <b>История транзакций</b>\n\nУ вас пока нет транзакций."
    else:
        text = "📊 <b>Последние транзакции:</b>\n\n"
        for trans in transactions:
            trans_type, amount, description, date = trans
            emoji = "🟢" if amount > 0 else "🔴"
            currency = "⭐️" if trans_type == "stars" else "🪙"
            sign = "+" if amount > 0 else ""
            text += f"{emoji} {sign}{amount} {currency}\n"
            text += f"   <i>{description}</i>\n"
            text += f"   <code>{date}</code>\n\n"
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu"))
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
# =================================================

# ================= ЗАДАНИЯ =================
@dp.callback_query(F.data == "task_get")
async def cmd_task_get(callback: CallbackQuery):
    await callback.answer()
    
    user = get_user(callback.from_user.id)
    
    # Проверка лимита заданий в день
    today = datetime.now().strftime("%Y-%m-%d")
    if user[11] != today:  # last_task_date != today
        reset_daily_task_count_for_user(callback.from_user.id)
        user = get_user(callback.from_user.id)
    
    if user[10] >= MAX_TASKS_PER_DAY:  # tasks_completed_today
        text = (
            f"⏰ <b>Лимит заданий на сегодня исчерпан!</b>\n\n"
            f"Вы выполнили {MAX_TASKS_PER_DAY} заданий.\n"
            f"Возвращайтесь завтра!"
        )
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu"))
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        return
    
    task_data = await get_piarflow_task(callback.from_user.id, callback.from_user.id)
    
    if task_data.get("status") == "ok" and task_data.get("sponsors"):
        sponsor = task_data["sponsors"][0]
        link = sponsor["link"]
        price = sponsor.get("price", 5)
        user_current_task[callback.from_user.id] = {"link": link, "price": price}
        
        text = (
            f"📋 <b>Текущее задание:</b>\n\n"
            f"Подпишитесь на канал и получите <b>{price} ⭐️</b>.\n\n"
            f"🔗 <b>Ссылка:</b>"
        )
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔗 Подписаться", url=link))
        builder.row(InlineKeyboardButton(text="✅ Проверить подписку", callback_data="task_check"))
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        text = "🎉 <b>На данный момент заданий нет.</b>\n\nЗагляните позже!"
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

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
            update_balance(callback.from_user.id, stars=reward, description="Выполнение задания")
            increment_task_count(callback.from_user.id)
            user_current_task.pop(callback.from_user.id, None)
            
            # Проверка достижений
            user = get_user(callback.from_user.id)
            if user[12] == 10:
                unlock_achievement(callback.from_user.id, "first_10_tasks")
            elif user[12] == 50:
                unlock_achievement(callback.from_user.id, "first_50_tasks")
            
            text = (
                f"✅ <b>Отлично!</b>\n\n"
                f"Вам начислено <b>{reward} ⭐️</b>!\n\n"
                f"📊 Выполнено заданий сегодня: {user[10]}/{MAX_TASKS_PER_DAY}\n"
                f"📈 Всего выполнено: {user[12]}"
            )
            
            builder = InlineKeyboardBuilder()
            if user[10] < MAX_TASKS_PER_DAY:
                builder.row(InlineKeyboardButton(text="📋 Следующее задание", callback_data="task_get"))
            builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu"))
            
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
        else:
            await callback.answer("⏳ Вы еще не подписались. Подпишитесь и нажмите снова.", show_alert=True)
    else:
        await callback.answer("❌ Ошибка проверки. Попробуйте позже.", show_alert=True)
# =================================================

# ================= ОБМЕН ВАЛЮТ =================
@dp.callback_query(F.data == "exchange")
async def cmd_exchange(callback: CallbackQuery):
    await callback.answer()
    
    user = get_user(callback.from_user.id)
    rate = int(get_setting("exchange_rate"))
    available_tcoin = user[3] // rate  # stars_balance
    
    text = (
        f"🔄 <b>Обмен Звезд на T Coin</b>\n\n"
        f"💱 <b>Курс:</b> <code>{rate} ⭐️ = 1 🪙</code>\n\n"
        f"⭐️ Ваш баланс: <code>{format_number(user[3])}</code>\n"
        f"🪙 Доступно для обмена: <code>{format_number(available_tcoin)}</code>"
    )
    
    builder = InlineKeyboardBuilder()
    if available_tcoin > 0:
        builder.row(InlineKeyboardButton(
            text=f"🔄 Обменять всё ({available_tcoin} 🪙)",
            callback_data=f"do_exchange_{available_tcoin}"
        ))
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.callback_query(F.data.startswith("do_exchange_"))
async def cmd_do_exchange(callback: CallbackQuery):
    await callback.answer()
    
    amount = int(callback.data.split("_")[-1])
    user = get_user(callback.from_user.id)
    rate = int(get_setting("exchange_rate"))
    stars_to_deduct = amount * rate
    
    if user[3] >= stars_to_deduct:  # stars_balance
        update_balance(
            callback.from_user.id,
            stars=-stars_to_deduct,
            tcoin=amount,
            description=f"Обмен {stars_to_deduct} ⭐️ на {amount} 🪙"
        )
        
        text = (
            f"✅ <b>Обмен выполнен успешно!</b>\n\n"
            f"📉 Списано: {stars_to_deduct} ⭐️\n"
            f"📈 Начислено: {amount} 🪙\n\n"
            f"💰 Новый баланс:\n"
            f"⭐️ {user[3] - stars_to_deduct}\n"
            f"🪙 {user[4] + amount}"
        )
        
        builder = InlineKeyboardBuilder()
        builder.row(InlineKeyboardButton(text="🔙 В меню", callback_data="back_to_menu"))
        
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())
    else:
        await callback.answer("❌ Недостаточно средств!", show_alert=True)
# =================================================

# ================= ИГРЫ =================
@dp.callback_query(F.data == "games_menu")
async def cmd_games_menu(callback: CallbackQuery):
    await callback.answer()
    
    text = (
        "🎮 <b>Игровой зал за T Coin</b>\n\n"
        "Используйте команды в чате:\n\n"
        "1️⃣ 🎰 <code>/slots</code> или <code>/s</code> - Слоты (до x5)\n"
        "2️⃣ 🎲 <code>/dice</code> или <code>/d</code> - Кости (Больше/Меньше)\n"
        "3️⃣ 🎯 <code>/darts</code> или <code>/da</code> - Дартс (В яблочко!)\n"
        "4️⃣ 🏀 <code>/basket</code> или <code>/b</code> - Баскетбол\n"
        "5️⃣ ⚽ <code>/foot</code> или <code>/f</code> - Футбол\n"
        "6️⃣ 🎳 <code>/bowl</code> или <code>/bo</code> - Боулинг\n"
        "7️⃣ 💣 <code>/mines</code> или <code>/m</code> - Мины (Безопасный кубик)\n"
        "8️⃣ 🗼 <code>/tower</code> или <code>/t</code> - Башня (Покорение вершины)\n"
        "9️⃣ 🚀 <code>/crash</code> или <code>/c</code> - Краш (Рискни всем)\n"
        "🔟 💰 <code>/double</code> или <code>/dn</code> - Удвоение (Только 6)\n\n"
        "<i>Пример: <code>/s 10</code> (ставка 10 монет)</i>"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(Command("slots", "s", "dice", "d", "darts", "da", "basket", "b", "foot", "f", "bowl", "bo", "mines", "m", "tower", "t", "crash", "c", "double", "dn"))
async def play_game(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        return
    
    if user[8]:  # is_banned
        await message.answer("❌ Вы заблокированы.")
        return
    
    args = message.text.split()
    cmd = args[0].replace("/", "").lower()
    
    # Конфигурация игр
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
        "mines": {"emoji": "🎲", "name": "Мины", "win": lambda v: (v >= 3, 2)},
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
        await message.answer(
            f"⚠️ Укажите ставку!\nПример: <code>/{cmd} 10</code>",
            parse_mode="HTML"
        )
        return
    
    try:
        bet = int(args[1])
    except ValueError:
        await message.answer("❌ Ставка должна быть числом!")
        return
    
    if bet <= 0:
        await message.answer("❌ Ставка должна быть больше 0!")
        return
    
    if user[4] < bet:  # tcoin_balance
        await message.answer("❌ Недостаточно T Coin!")
        return
    
    # Списываем ставку
    update_balance(message.from_user.id, tcoin=-bet, description=f"Ставка в игре '{config['name']}'")
    
    # Отправляем анимированный кубик
    dice_msg = await message.answer_dice(emoji=config["emoji"])
    value = dice_msg.dice.value
    
    # Проверяем выигрыш
    is_win, multiplier = config["win"](value)
    result_text = format_game_result(config["emoji"], value)
    
    if is_win:
        winnings = bet * multiplier
        update_balance(
            message.from_user.id,
            tcoin=winnings,
            description=f"Выигрыш в игре '{config['name']}'"
        )
        
        await message.answer(
            f"{result_text}\n\n"
            f"🎉 <b>ПОБЕДА!</b>\n\n"
            f"💰 Ставка: {bet} 🪙\n"
            f"📈 Множитель: x{multiplier}\n"
            f"✅ Выигрыш: <b>{winnings} 🪙</b>",
            parse_mode="HTML"
        )
    else:
        await message.answer(
            f"{result_text}\n\n"
            f"😔 <b>Проигрыш.</b>\n\n"
            f"Вы потеряли {bet} 🪙. Попробуйте еще раз!",
            parse_mode="HTML"
        )
# =================================================

# ================= АДМИН-ПАНЕЛЬ =================
@dp.callback_query(F.data == "admin")
async def cmd_admin(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user or not user[7]:  # is_admin
        await callback.answer("❌ Нет прав!", show_alert=True)
        return
    
    await callback.answer()
    
    stats = get_bot_stats()
    rate = int(get_setting("exchange_rate"))
    bot_active = get_setting("bot_active")
    maintenance = get_setting("maintenance_mode")
    
    text = (
        f"👑 <b>Админ-панель</b>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"✅ Активных: {stats['active_users']}\n"
        f"🆕 Новых сегодня: {stats['new_users_today']}\n"
        f"💰 Всего Звезд: {format_number(stats['total_stars'])}\n"
        f"🪙 Всего T Coin: {format_number(stats['total_tcoin'])}\n"
        f"📝 Транзакций сегодня: {stats['transactions_today']}\n"
        f"🎟 Активных промокодов: {stats['active_promos']}\n\n"
        f"⚙️ <b>Настройки:</b>\n"
        f"💱 Курс обмена: {rate} ⭐️ = 1 🪙\n"
        f"🟢 Бот активен: {'Да' if bot_active == '1' else 'Нет'}\n"
        f"🔧 Режим обслуживания: {'Вкл' if maintenance == '1' else 'Выкл'}\n\n"
        f"<b>Команды:</b>\n"
        f"• <code>/broadcast</code> - Рассылка сообщения\n"
        f"• <code>/addstars &lt;id&gt; &lt;кол-во&gt;</code>\n"
        f"• <code>/addtcoin &lt;id&gt; &lt;кол-во&gt;</code>\n"
        f"• <code>/reset &lt;id&gt;</code> - Сброс баланса\n"
        f"• <code>/ban &lt;id&gt;</code> - Забанить пользователя\n"
        f"• <code>/unban &lt;id&gt;</code> - Разбанить\n"
        f"• <code>/setrate &lt;число&gt;</code> - Курс обмена\n"
        f"• <code>/makeadmin &lt;id&gt; &lt;1/0&gt;</code>\n"
        f"• <code>/createpromo &lt;код&gt; &lt;звезды&gt; &lt;tcoin&gt; &lt;лимит&gt;</code>\n"
        f"• <code>/togglebot</code> - Вкл/Выкл бота\n"
        f"• <code>/maintenance</code> - Режим обслуживания\n"
        f"• <code>/userstats &lt;id&gt;</code> - Статистика пользователя"
    )
    
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
    
    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=builder.as_markup())

@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    user = get_user(message.from_user.id)
    if not user or not user[7]:  # is_admin
        return
    
    await message.answer("📢 Отправьте сообщение для рассылки всем пользователям:")
    await state.set_state(AdminStates.waiting_for_broadcast)

@dp.message(AdminStates.waiting_for_broadcast)
async def process_broadcast(message: Message, state: FSMContext):
    await state.clear()
    
    users = get_all_users()
    success_count = 0
    fail_count = 0
    
    status_msg = await message.answer(f"📤 Начинаю рассылку для {len(users)} пользователей...")
    
    for user_id in users:
        try:
            await bot.send_message(user_id, message.text, parse_mode="HTML")
            success_count += 1
            await asyncio.sleep(0.05)  # Задержка для избежания лимитов
        except Exception:
            fail_count += 1
    
    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"📤 Успешно: {success_count}\n"
        f"❌ Ошибок: {fail_count}",
        parse_mode="HTML"
    )

@dp.message(Command("ban", "unban"))
async def cmd_ban(message: Message):
    user = get_user(message.from_user.id)
    if not user or not user[7]:  # is_admin
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer(f"⚠️ Использование: <code>{args[0]} &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    
    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return
    
    cmd = args[0].replace("/", "")
    
    if cmd == "ban":
        ban_user(target_id, 1)
        await message.answer(f"🚫 Пользователь {target_id} заблокирован.")
    else:
        ban_user(target_id, 0)
        await message.answer(f"✅ Пользователь {target_id} разблокирован.")

@dp.message(Command("createpromo"))
async def cmd_createpromo(message: Message):
    user = get_user(message.from_user.id)
    if not user or not user[7]:  # is_admin
        return
    
    args = message.text.split()
    if len(args) < 5:
        await message.answer(
            "⚠️ Использование: <code>/createpromo &lt;код&gt; &lt;звезды&gt; &lt;tcoin&gt; &lt;лимит&gt;</code>\n"
            "Пример: <code>/createpromo BONUS100 50 20 100</code>",
            parse_mode="HTML"
        )
        return
    
    try:
        code = args[1].upper()
        stars = int(args[2])
        tcoin = int(args[3])
        max_uses = int(args[4])
        
        create_promo_code(code, stars, tcoin, max_uses)
        
        await message.answer(
            f"✅ <b>Промокод создан!</b>\n\n"
            f"🎟 Код: <code>{code}</code>\n"
            f"⭐️ Звезды: {stars}\n"
            f"🪙 T Coin: {tcoin}\n"
            f"🔢 Лимит использований: {max_uses}",
            parse_mode="HTML"
        )
    except ValueError:
        await message.answer("❌ Ошибка формата. Все значения должны быть числами.")

@dp.message(Command("togglebot"))
async def cmd_togglebot(message: Message):
    user = get_user(message.from_user.id)
    if not user or not user[7]:  # is_admin
        return
    
    current = get_setting("bot_active")
    new_status = "0" if current == "1" else "1"
    set_setting("bot_active", new_status)
    
    status = "🔴 Выключен" if new_status == "0" else "🟢 Включен"
    await message.answer(f"✅ Бот {status}")

@dp.message(Command("maintenance"))
async def cmd_maintenance(message: Message):
    user = get_user(message.from_user.id)
    if not user or not user[7]:  # is_admin
        return
    
    current = get_setting("maintenance_mode")
    new_status = "0" if current == "1" else "1"
    set_setting("maintenance_mode", new_status)
    
    status = "🔧 Включен" if new_status == "1" else "✅ Выключен"
    await message.answer(f"✅ Режим обслуживания {status}")

@dp.message(Command("userstats"))
async def cmd_userstats(message: Message):
    user = get_user(message.from_user.id)
    if not user or not user[7]:  # is_admin
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("⚠️ Использование: <code>/userstats &lt;user_id&gt;</code>", parse_mode="HTML")
        return
    
    try:
        target_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return
    
    target_user = get_user(target_id)
    if not target_user:
        await message.answer("❌ Пользователь не найден.")
        return
    
    level, progress = get_user_level(target_user[12])
    
    text = (
        f"📊 <b>Статистика пользователя</b>\n\n"
        f"👤 ID: <code>{target_user[0]}</code>\n"
        f"📝 Username: @{target_user[1] or 'N/A'}\n"
        f"👤 Имя: {target_user[2]}\n"
        f"🎖 Уровень: {level} ({progress}%)\n\n"
        f"💰 <b>Баланс:</b>\n"
        f"⭐️ Звезды: {format_number(target_user[3])}\n"
        f"🪙 T Coin: {format_number(target_user[4])}\n\n"
        f"📈 <b>Активность:</b>\n"
        f"✅ Выполнено заданий: {target_user[12]}\n"
        f"📅 Заданий сегодня: {target_user[10]}/{MAX_TASKS_PER_DAY}\n"
        f"👥 Приглашено друзей: {target_user[13]}\n\n"
        f"🚫 Заблокирован: {'Да' if target_user[8] else 'Нет'}\n"
        f"👑 Админ: {'Да' if target_user[7] else 'Нет'}\n"
        f"📅 Регистрация: {target_user[14]}"
    )
    
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("addstars", "addtcoin", "reset", "setrate", "makeadmin", "stats"))
async def cmd_admin_actions(message: Message):
    user = get_user(message.from_user.id)
    if not user or not user[7]:  # is_admin
        return
    
    args = message.text.split()
    cmd = args[0].replace("/", "")
    
    if cmd == "stats":
        stats = get_bot_stats()
        await message.answer(
            f"📊 <b>Статистика бота:</b>\n\n"
            f"👥 Пользователей: {stats['total_users']}\n"
            f"✅ Активных: {stats['active_users']}\n"
            f"🆕 Новых сегодня: {stats['new_users_today']}\n"
            f"⭐️ Всего Звезд: {format_number(stats['total_stars'])}\n"
            f"🪙 Всего T Coin: {format_number(stats['total_tcoin'])}\n"
            f"📝 Транзакций сегодня: {stats['transactions_today']}",
            parse_mode="HTML"
        )
        return
    
    if cmd in ["addstars", "addtcoin", "reset", "makeadmin"]:
        if len(args) < 2:
            await message.answer(f"⚠️ Использование: <code>/{cmd} &lt;user_id&gt; [значение]</code>", parse_mode="HTML")
            return
        
        try:
            target_id = int(args[1])
            val = int(args[2]) if len(args) > 2 and cmd != "reset" else 0
        except ValueError:
            await message.answer("❌ Ошибка формата. ID должен быть числом.")
            return
        
        if cmd == "addstars":
            update_balance(target_id, stars=val, description=f"Начисление администратором")
            await message.answer(f"✅ Начислено {val} ⭐️ пользователю {target_id}")
        elif cmd == "addtcoin":
            update_balance(target_id, tcoin=val, description=f"Начисление администратором")
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
            await message.answer("⚠️ Использование: <code>/setrate &lt;новое_значение&gt;</code>", parse_mode="HTML")
            return
        try:
            new_rate = int(args[1])
            if new_rate <= 0:
                raise ValueError
            set_setting("exchange_rate", str(new_rate))
            await message.answer(f"✅ Курс обмена изменен: <code>{new_rate} ⭐️ = 1 🪙</code>", parse_mode="HTML")
        except ValueError:
            await message.answer("❌ Значение должно быть положительным числом.")
# =================================================

# ================= ВОЗВРАТ В МЕНЮ =================
@dp.callback_query(F.data == "back_to_menu")
async def cmd_back(callback: CallbackQuery):
    await callback.answer()
    callback.message.text = "/start"
    await cmd_start(callback.message)
# =================================================

# ================= ЗАПУСК БОТА =================
async def main():
    print("✅ Бот успешно запущен...")
    print(f"👑 Админ ID: {ADMIN_ID}")
    print(f"💱 Курс обмена: {DEFAULT_EXCHANGE_RATE} ⭐️ = 1 🪙")
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
