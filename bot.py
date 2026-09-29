# =============================================================================
# РЕФЕРАЛЬНЫЙ БОТ С PIARFLOW, ИГРАМИ И АДМИН-ПАНЕЛЬЮ
# Версия 3.0 - Полная реализация
# =============================================================================

import asyncio
import logging
import random
import sqlite3
import re
import aiohttp
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional, Any, List

# ==================== AIОGRAM ИМПОРТЫ ====================
from aiogram import Bot, Dispatcher, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, LabeledPrice, PreCheckoutQuery,
    SuccessfulPayment, User
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# =============================================================================
# ========================= КОНФИГУРАЦИЯ ====================================
# =============================================================================

# Основные токены (замените на свои)
BOT_TOKEN = "ВАШ_ТОКЕН_TELEGRAM_БОТА"
PIARFLOW_API_KEY = "XIKkM70c5VtJ3PU78j7yqeGjAFwM5zYO"
PIARFLOW_BASE_URL = "https://piarflow.com/v1"

# ID главного администратора (замените на свой)
ADMIN_ID = 123456789

# ==================== НАСТРОЙКИ ПО УМОЛЧАНИЮ ====================
DEFAULT_SETTINGS = {
    "exchange_rate": "10",          # Курс обмена: звёзд → T Coin
    "bot_active": "1",              # Бот активен (1/0)
    "maintenance_mode": "0",        # Режим обслуживания (1/0)
    "min_bet": "10",                # Минимальная ставка в играх
    "max_bet": "50000",             # Максимальная ставка в играх
    "daily_bonus_stars": "10",      # Ежедневный бонус звёзд
    "daily_bonus_tcoin": "5",       # Ежедневный бонус T Coin
    "referral_bonus": "5",          # Бонус за реферала
    "max_tasks_per_day": "10",      # Лимит заданий в день
    "deposit_enabled": "1",         # Пополнение включено (1/0)
    "withdraw_enabled": "1",        # Вывод включён (1/0)
    "games_enabled": "1",           # Игры включены (1/0)
    "transfer_enabled": "1",        # Переводы включены (1/0)
    "verification_required": "1",   # Требуется верификация (1/0)
    "welcome_text": "Добро пожаловать!",  # Текст приветствия
    "support_link": "https://t.me/support",  # Ссылка на поддержку
    "channel_link": "https://t.me/channel",  # Ссылка на канал
    "rules_text": "Правила бота: играйте честно!"  # Текст правил
}

# ==================== ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Временные хранилища в памяти
user_current_task: Dict[int, Dict] = {}
api_cache: Dict[str, Tuple] = {}
pending_deposits: Dict[int, int] = {}  # user_id -> amount (для инвойсов)

# =============================================================================
# ========================= FSM СОСТОЯНИЯ ===================================
# =============================================================================

class AdminStates(StatesGroup):
    """Состояния админ-панели"""
    waiting_broadcast = State()
    waiting_user_id = State()
    waiting_amount = State()
    waiting_promo_code = State()
    waiting_promo_stars = State()
    waiting_promo_tcoin = State()
    waiting_promo_limit = State()
    waiting_setting_value = State()
    waiting_custom_text = State()
    waiting_link = State()

class UserStates(StatesGroup):
    """Состояния пользователя"""
    waiting_promo = State()
    waiting_transfer = State()
    waiting_deposit_amount = State()
    waiting_withdraw_amount = State()
    waiting_support_message = State()

# =============================================================================
# ========================= БАЗА ДАННЫХ =====================================
# =============================================================================

def get_db() -> sqlite3.Connection:
    """Получить подключение к БД"""
    return sqlite3.connect("bot_database.db")

def init_db() -> None:
    """Инициализация базы данных и создание таблиц"""
    conn = get_db()
    c = conn.cursor()

    # Таблица пользователей (16 колонок)
    c.execute("""
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
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_verified INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            total_games_played INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0
        )
    """)

    # Таблица настроек бота
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Таблица промокодов
    c.execute("""
        CREATE TABLE IF NOT EXISTS promo_codes (
            code TEXT PRIMARY KEY,
            stars_reward INTEGER DEFAULT 0,
            tcoin_reward INTEGER DEFAULT 0,
            max_uses INTEGER DEFAULT 100,
            current_uses INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_by INTEGER,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Таблица использованных промокодов
    c.execute("""
        CREATE TABLE IF NOT EXISTS used_promo (
            user_id INTEGER,
            promo_code TEXT,
            used_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, promo_code)
        )
    """)

    # Таблица транзакций
    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            amount INTEGER,
            description TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Таблица заявок на пополнение/вывод
    c.execute("""
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            req_type TEXT,
            amount INTEGER,
            status TEXT DEFAULT 'pending',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            processed_at TEXT
        )
    """)

    # Таблица достижений
    c.execute("""
        CREATE TABLE IF NOT EXISTS achievements (
            user_id INTEGER,
            achievement TEXT,
            unlocked_at TEXT DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, achievement)
        )
    """)

    # Таблица логов админ-действий
    c.execute("""
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            action TEXT,
            target_id INTEGER,
            details TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Инициализация настроек по умолчанию
    for key, value in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))

    conn.commit()
    conn.close()
    logging.info("✅ База данных инициализирована")

# ==================== ФУНКЦИИ РАБОТЫ С ПОЛЬЗОВАТЕЛЯМИ ====================

def get_user(user_id: int) -> Optional[tuple]:
    """Получить данные пользователя по ID"""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row

def get_user_by_username(username: str) -> Optional[tuple]:
    """Получить данные пользователя по username (без @)"""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username.lstrip('@'),)).fetchone()
    conn.close()
    return row

def create_user(user_id: int, username: str, first_name: str,
                referral_code: str, referred_by: Optional[int] = None,
                verified: int = 0) -> None:
    """Создать нового пользователя"""
    conn = get_db()
    is_admin = 1 if user_id == ADMIN_ID else 0
    conn.execute("""
        INSERT INTO users (user_id, username, first_name, referral_code,
                          referred_by, is_admin, is_verified)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, username, first_name, referral_code, referred_by, is_admin, verified))
    conn.commit()
    conn.close()

def update_user_field(user_id: int, field: str, value: Any) -> None:
    """Обновить одно поле пользователя"""
    conn = get_db()
    conn.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()

def update_balance(user_id: int, stars: int = 0, tcoin: int = 0,
                   description: str = "") -> None:
    """Обновить баланс пользователя и записать транзакцию"""
    conn = get_db()
    # Обновляем баланс
    conn.execute("""
        UPDATE users
        SET stars_balance = stars_balance + ?,
            tcoin_balance = tcoin_balance + ?
        WHERE user_id = ?
    """, (stars, tcoin, user_id))

    # Записываем транзакции
    if stars != 0:
        desc = description or ("Звёзды" if stars > 0 else "Списание звёзд")
        conn.execute("""
            INSERT INTO transactions (user_id, type, amount, description)
            VALUES (?, 'stars', ?, ?)
        """, (user_id, stars, desc))

    if tcoin != 0:
        desc = description or ("T Coin" if tcoin > 0 else "Списание T Coin")
        conn.execute("""
            INSERT INTO transactions (user_id, type, amount, description)
            VALUES (?, 'tcoin', ?, ?)
        """, (user_id, tcoin, desc))

    conn.commit()
    conn.close()

def get_transactions(user_id: int, limit: int = 15) -> List[tuple]:
    """Получить последние транзакции пользователя"""
    conn = get_db()
    rows = conn.execute("""
        SELECT type, amount, description, created_at
        FROM transactions
        WHERE user_id = ?
        ORDER BY id DESC
        LIMIT ?
    """, (user_id, limit)).fetchall()
    conn.close()
    return rows

def can_claim_daily(user_id: int) -> bool:
    """Проверить, можно ли получить ежедневный бонус"""
    user = get_user(user_id)
    if not user or not user[9]:  # last_daily_bonus
        return True
    try:
        last = datetime.strptime(user[9], "%Y-%m-%d")
        return (datetime.now() - last).days >= 1
    except ValueError:
        return True

def set_daily_claimed(user_id: int) -> None:
    """Отметить, что бонус получен сегодня"""
    update_user_field(user_id, "last_daily_bonus", datetime.now().strftime("%Y-%m-%d"))

def check_daily_task_reset(user_id: int) -> None:
    """Сбросить счётчик заданий, если новый день"""
    user = get_user(user_id)
    if not user:
        return
    today = datetime.now().strftime("%Y-%m-%d")
    if user[11] and user[11] != today:
        update_user_field(user_id, "tasks_completed_today", 0)

def increment_tasks(user_id: int) -> None:
    """Увеличить счётчик выполненных заданий"""
    conn = get_db()
    today = datetime.now().strftime("%Y-%m-%d")
    conn.execute("""
        UPDATE users
        SET tasks_completed_today = tasks_completed_today + 1,
            last_task_date = ?,
            total_tasks_completed = total_tasks_completed + 1
        WHERE user_id = ?
    """, (today, user_id))
    conn.commit()
    conn.close()

def increment_referrals(user_id: int) -> None:
    """Увеличить счётчик рефералов"""
    conn = get_db()
    conn.execute("UPDATE users SET total_referrals = total_referrals + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def increment_games(user_id: int, won: bool = False) -> None:
    """Увеличить счётчик игр"""
    conn = get_db()
    if won:
        conn.execute("""
            UPDATE users
            SET total_games_played = total_games_played + 1,
                total_wins = total_wins + 1
            WHERE user_id = ?
        """, (user_id,))
    else:
        conn.execute("""
            UPDATE users
            SET total_games_played = total_games_played + 1
            WHERE user_id = ?
        """, (user_id,))
    conn.commit()
    conn.close()

def check_level_up(user_id: int) -> Optional[int]:
    """Проверить повышение уровня и вернуть новый уровень, если произошло"""
    user = get_user(user_id)
    if not user:
        return None
    tasks = user[12]  # total_tasks_completed
    current_level = user[16]  # level

    # Формула уровня: level = 1 + (tasks // 10), максимум 20
    new_level = min(1 + (tasks // 10), 20)

    if new_level > current_level:
        update_user_field(user_id, "level", new_level)
        # Бонус за уровень
        bonus = new_level * 5
        update_balance(user_id, tcoin=bonus, description=f"Бонус за уровень {new_level}")
        return new_level
    return None

def unlock_achievement(user_id: int, achievement: str) -> bool:
    """Разблокировать достижение. Возвращает True, если новое"""
    conn = get_db()
    try:
        conn.execute("INSERT INTO achievements (user_id, achievement) VALUES (?, ?)",
                     (user_id, achievement))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_user_achievements(user_id: int) -> List[str]:
    """Получить список достижений пользователя"""
    conn = get_db()
    rows = conn.execute("SELECT achievement FROM achievements WHERE user_id = ?", (user_id,)).fetchall()
    conn.close()
    return [r[0] for r in rows]

def log_admin_action(admin_id: int, action: str, target_id: Optional[int] = None,
                     details: str = "") -> None:
    """Записать действие администратора в лог"""
    conn = get_db()
    conn.execute("""
        INSERT INTO admin_logs (admin_id, action, target_id, details)
        VALUES (?, ?, ?, ?)
    """, (admin_id, action, target_id, details))
    conn.commit()
    conn.close()

# ==================== ФУНКЦИИ РАБОТЫ С НАСТРОЙКАМИ ====================

def get_setting(key: str) -> Optional[str]:
    """Получить значение настройки"""
    conn = get_db()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row[0] if row else None

def set_setting(key: str, value: Any) -> None:
    """Установить значение настройки"""
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                 (key, str(value)))
    conn.commit()
    conn.close()

def get_all_settings() -> Dict[str, str]:
    """Получить все настройки"""
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return {k: v for k, v in rows}

# ==================== ФУНКЦИИ РАБОТЫ С ПРОМОКОДАМИ ====================

def get_promo(code: str) -> Optional[tuple]:
    """Получить промокод"""
    conn = get_db()
    row = conn.execute("SELECT * FROM promo_codes WHERE code = ? AND is_active = 1",
                       (code,)).fetchone()
    conn.close()
    return row

def create_promo(code: str, stars: int, tcoin: int, max_uses: int,
                 created_by: int) -> bool:
    """Создать промокод. Возвращает True если успешно"""
    conn = get_db()
    try:
        conn.execute("""
            INSERT INTO promo_codes (code, stars_reward, tcoin_reward, max_uses, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (code, stars, tcoin, max_uses, created_by))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def use_promo(user_id: int, code: str) -> Tuple[bool, str]:
    """Использовать промокод. Возвращает (успех, сообщение)"""
    conn = get_db()
    # Проверяем, использовал ли пользователь этот промокод
    if conn.execute("SELECT 1 FROM used_promo WHERE user_id=? AND promo_code=?",
                    (user_id, code)).fetchone():
        conn.close()
        return False, "already_used"

    # Обновляем счётчик использований
    conn.execute("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE code = ?", (code,))
    conn.execute("INSERT INTO used_promo (user_id, promo_code) VALUES (?, ?)", (user_id, code))
    conn.commit()
    conn.close()
    return True, "success"

def delete_promo(code: str) -> bool:
    """Удалить промокод"""
    conn = get_db()
    c = conn.execute("DELETE FROM promo_codes WHERE code = ?", (code,))
    conn.commit()
    conn.close()
    return c.rowcount > 0

def list_promos(limit: int = 20) -> List[tuple]:
    """Список всех промокодов"""
    conn = get_db()
    rows = conn.execute("""
        SELECT code, stars_reward, tcoin_reward, max_uses, current_uses, is_active
        FROM promo_codes ORDER BY created_at DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return rows

# ==================== ФУНКЦИИ РАБОТЫ С ЗАЯВКАМИ ====================

def create_request(user_id: int, req_type: str, amount: int) -> int:
    """Создать заявку, вернуть ID"""
    conn = get_db()
    c = conn.execute("""
        INSERT INTO requests (user_id, req_type, amount)
        VALUES (?, ?, ?)
    """, (user_id, req_type, amount))
    req_id = c.lastrowid
    conn.commit()
    conn.close()
    return req_id

def get_request(req_id: int) -> Optional[tuple]:
    """Получить заявку по ID"""
    conn = get_db()
    row = conn.execute("SELECT * FROM requests WHERE id = ?", (req_id,)).fetchone()
    conn.close()
    return row

def update_request_status(req_id: int, status: str) -> None:
    """Обновить статус заявки"""
    conn = get_db()
    conn.execute("""
        UPDATE requests
        SET status = ?, processed_at = ?
        WHERE id = ?
    """, (status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), req_id))
    conn.commit()
    conn.close()

def get_pending_requests(limit: int = 20) -> List[tuple]:
    """Получить все ожидающие заявки"""
    conn = get_db()
    rows = conn.execute("""
        SELECT id, user_id, req_type, amount, created_at
        FROM requests
        WHERE status = 'pending'
        ORDER BY id DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return rows

# ==================== СТАТИСТИКА ====================

def get_bot_stats() -> Dict[str, Any]:
    """Получить общую статистику бота"""
    conn = get_db()
    stats = {}

    stats['total_users'] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    stats['active_users'] = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0").fetchone()[0]
    stats['banned_users'] = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1").fetchone()[0]
    stats['admins'] = conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1").fetchone()[0]
    stats['verified'] = conn.execute("SELECT COUNT(*) FROM users WHERE is_verified = 1").fetchone()[0]

    row = conn.execute("SELECT COALESCE(SUM(stars_balance), 0), COALESCE(SUM(tcoin_balance), 0) FROM users").fetchone()
    stats['total_stars'] = row[0]
    stats['total_tcoin'] = row[1]

    today = datetime.now().strftime("%Y-%m-%d")
    stats['new_today'] = conn.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at) = ?", (today,)).fetchone()[0]
    stats['tx_today'] = conn.execute("SELECT COUNT(*) FROM transactions WHERE DATE(created_at) = ?", (today,)).fetchone()[0]
    stats['pending_requests'] = conn.execute("SELECT COUNT(*) FROM requests WHERE status = 'pending'").fetchone()[0]
    stats['active_promos'] = conn.execute("SELECT COUNT(*) FROM promo_codes WHERE is_active = 1").fetchone()[0]

    # Топ игроков
    stats['top_games'] = conn.execute("""
        SELECT user_id, total_games_played FROM users
        WHERE total_games_played > 0
        ORDER BY total_games_played DESC LIMIT 5
    """).fetchall()

    stats['top_tasks'] = conn.execute("""
        SELECT user_id, total_tasks_completed FROM users
        WHERE total_tasks_completed > 0
        ORDER BY total_tasks_completed DESC LIMIT 5
    """).fetchall()

    conn.close()
    return stats

# Инициализация БД при запуске
init_db()

# =============================================================================
# ========================= PIARFLOW API ====================================
# =============================================================================

async def pf_get_task(user_id: int, chat_id: int) -> Dict:
    """Получить задание из PiarFlow"""
    cache_key = f"task_{user_id}"

    # Проверяем кеш
    if cache_key in api_cache:
        cached_data, timestamp = api_cache[cache_key]
        if datetime.now().timestamp() - timestamp < 300:  # 5 минут
            return cached_data

    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {PIARFLOW_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {"user_id": user_id, "chat_id": chat_id, "max_sponsors": 1}

        try:
            async with session.post(
                f"{PIARFLOW_BASE_URL}/sponsors",
                json=payload,
                headers=headers
            ) as response:
                result = await response.json()
                api_cache[cache_key] = (result, datetime.now().timestamp())
                return result
        except Exception as e:
            logging.error(f"PiarFlow API error: {e}")
            return {"status": "error", "message": str(e)}

async def pf_check_task(user_id: int, link: str) -> Dict:
    """Проверить выполнение задания"""
    async with aiohttp.ClientSession() as session:
        headers = {
            "Authorization": f"Bearer {PIARFLOW_API_KEY}",
            "Content-Type": "application/json"
        }
        payload = {"user_id": user_id, "links": [link]}

        try:
            async with session.post(
                f"{PIARFLOW_BASE_URL}/sponsors/check",
                json=payload,
                headers=headers
            ) as response:
                return await response.json()
        except Exception as e:
            logging.error(f"PiarFlow check error: {e}")
            return {"status": "error"}

# =============================================================================
# ========================= УТИЛИТЫ =========================================
# =============================================================================

def fmt_number(n: int) -> str:
    """Форматировать большое число (1K, 1M)"""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)

def get_level_info(level: int) -> Tuple[str, str]:
    """Получить название и эмодзи уровня"""
    levels = {
        1: ("🥉 Новичок", "🥉"),
        2: ("🥈 Ученик", "🥈"),
        3: ("🥇 Опытный", "🥇"),
        4: ("💎 Мастер", "💎"),
        5: ("👑 Эксперт", "👑"),
        6: ("🌟 Легенда", "🌟"),
        7: ("🔥 Божество", "🔥"),
    }
    if level >= 7:
        return levels[7]
    return levels.get(level, ("🥉 Новичок", "🥉"))

async def resolve_user_id(arg: str, reply_msg: Optional[Message] = None) -> Optional[int]:
    """
    Определить ID пользователя по аргументу.
    Поддерживает: числовой ID, @username, reply на сообщение.
    """
    # Если есть reply, используем его
    if reply_msg and reply_msg.from_user:
        return reply_msg.from_user.id

    if not arg:
        return None

    arg = arg.strip()

    # Числовой ID
    if arg.isdigit():
        return int(arg)

    # Username (с @ или без)
    if arg.startswith('@'):
        username = arg[1:]
    elif re.match(r'^[a-zA-Z0-9_]{3,}$', arg):
        username = arg
    else:
        return None

    user = get_user_by_username(username)
    return user[0] if user else None

def is_admin(user_id: int) -> bool:
    """Проверить, является ли пользователь админом"""
    user = get_user(user_id)
    return bool(user and user[7])

def is_verified(user_id: int) -> bool:
    """Проверить верификацию"""
    user = get_user(user_id)
    return bool(user and user[15])

def is_bot_active() -> bool:
    """Проверить, активен ли бот"""
    return get_setting("bot_active") == "1"

def is_maintenance() -> bool:
    """Проверить режим обслуживания"""
    return get_setting("maintenance_mode") == "1"

# ==================== КНОПКИ ====================

def btn_back(target: str = "menu") -> InlineKeyboardButton:
    """Кнопка назад"""
    return InlineKeyboardButton(text="🔙 Назад", callback_data=f"back_{target}")

def btn_profile() -> InlineKeyboardButton:
    """Кнопка в профиль"""
    return InlineKeyboardButton(text="🔙 Профиль", callback_data="profile")

def btn_menu() -> InlineKeyboardButton:
    """Кнопка в меню"""
    return InlineKeyboardButton(text="🏠 Главное меню", callback_data="back_menu")

def build_keyboard(rows: List[List[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    """Построить клавиатуру из списка рядов"""
    builder = InlineKeyboardBuilder()
    for row in rows:
        builder.row(*row)
    return builder.as_markup()

# =============================================================================
# ========================= РЕНДЕР МЕНЮ (УНИВЕРСАЛЬНОЕ) =====================
# =============================================================================

async def render(target: Any, text: str, markup: InlineKeyboardMarkup,
                 is_callback: bool = False) -> None:
    """
    Универсальный рендер сообщения.
    Для callback - edit_text, для message - answer.
    """
    try:
        if is_callback:
            await target.edit_text(text, parse_mode="HTML", reply_markup=markup)
        else:
            await target.answer(text, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest as e:
        # Если сообщение не изменилось — игнорируем
        if "message is not modified" not in str(e):
            logging.error(f"Render error: {e}")

async def render_main_menu(target: Any, is_callback: bool = False) -> None:
    """Отрисовать главное меню"""
    user_id = target.from_user.id if hasattr(target, 'from_user') else target.message.from_user.id
    user = get_user(user_id)
    if not user:
        return

    first_name = target.from_user.first_name if hasattr(target, 'from_user') else target.message.from_user.first_name
    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{user[5]}"
    level_name, level_emoji = get_level_info(user[16])

    text = (
        f"👋 <b>Привет, {first_name}!</b>\n\n"
        f"🎖 <b>Уровень:</b> {level_name} (Ур. {user[16]})\n\n"
        f"💰 <b>Баланс:</b>\n"
        f"⭐️ Звёзды: <code>{fmt_number(user[3])}</code>\n"
        f"🪙 T Coin: <code>{fmt_number(user[4])}</code>\n\n"
        f"🔗 <b>Реферальная ссылка:</b>\n"
        f"<code>{ref_link}</code>\n"
        f"<i>+{get_setting('referral_bonus')} ⭐️ за каждого друга</i>"
    )

    keyboard = build_keyboard([
        [InlineKeyboardButton(text="📋 Задания", callback_data="task_get")],
        [InlineKeyboardButton(text="🎮 Игры", callback_data="games_menu"),
         InlineKeyboardButton(text="💱 Обмен", callback_data="exchange")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile")],
    ])

    if user[7]:  # Админ
        keyboard = build_keyboard([
            [InlineKeyboardButton(text="📋 Задания", callback_data="task_get")],
            [InlineKeyboardButton(text="🎮 Игры", callback_data="games_menu"),
             InlineKeyboardButton(text="💱 Обмен", callback_data="exchange")],
            [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
             InlineKeyboardButton(text="👑 Админ", callback_data="admin")],
        ])

    await render(target, text, keyboard, is_callback)

async def render_verify(target: Any, is_callback: bool = False) -> None:
    """Отрисовать экран верификации"""
    user_id = target.from_user.id if hasattr(target, 'from_user') else target.message.from_user.id
    text = (
        "⚠️ <b>Подтверждение регистрации</b>\n\n"
        "Вы перешли по реферальной ссылке.\n"
        "Для доступа подпишитесь на спонсора:"
    )

    task_data = await pf_get_task(user_id, user_id)
    keyboard = build_keyboard([[btn_back("menu")]])

    if task_data.get("status") == "ok" and task_data.get("sponsors"):
        sponsor = task_data["sponsors"][0]
        user_current_task[user_id] = {
            "link": sponsor["link"],
            "price": sponsor.get("price", 5),
            "verify": True
        }
        keyboard = build_keyboard([
            [InlineKeyboardButton(text="🔗 Подписаться", url=sponsor["link"])],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="task_check")],
            [btn_back("menu")],
        ])
    else:
        # Нет заданий — пропускаем верификацию
        update_user_field(user_id, "is_verified", 1)
        await render_main_menu(target, is_callback)
        return

    await render(target, text, keyboard, is_callback)

# =============================================================================
# ========================= СТАРТ И ВЕРИФИКАЦИЯ =============================
# =============================================================================

@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Обработчик команды /start"""
    user_id = message.from_user.id

    # Проверка активности бота
    if not is_bot_active() and user_id != ADMIN_ID:
        return await message.answer("🔧 Бот временно недоступен. Попробуйте позже.")

    # Проверка режима обслуживания
    if is_maintenance() and user_id != ADMIN_ID:
        return await message.answer("🔧 Технические работы. Попробуйте позже.")

    user = get_user(user_id)

    # Проверка бана
    if user and user[8]:
        return await message.answer("❌ Вы заблокированы администратором.")

    # Регистрация нового пользователя
    if not user:
        args = message.text.split()
        referred_by = None
        verified = 1

        # Обработка реферальной ссылки
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                ref_id = int(args[1].replace("ref_", ""))
                if ref_id != user_id and get_user(ref_id):
                    referred_by = ref_id
                    # Требуется ли верификация
                    if get_setting("verification_required") == "1":
                        verified = 0
            except ValueError:
                pass

        create_user(
            user_id,
            message.from_user.username or "user",
            message.from_user.first_name or "User",
            f"ref_{user_id}",
            referred_by,
            verified
        )

        # Бонус рефереру (если верифицирован сразу)
        if referred_by and verified:
            bonus = int(get_setting("referral_bonus") or 5)
            update_balance(referred_by, stars=bonus, desc="Реферальный бонус")
            increment_referrals(referred_by)
            try:
                await bot.send_message(
                    referred_by,
                    f"🎉 <b>Друг зарегистрировался!</b>\n\nВам начислено <b>{bonus} ⭐️</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass

    user = get_user(user_id)

    # Если требуется верификация и она не пройдена
    if not user[15] and get_setting("verification_required") == "1":
        return await render_verify(message, is_callback=False)

    await render_main_menu(message, is_callback=False)

# =============================================================================
# ========================= ПРОФИЛЬ =========================================
# =============================================================================

@dp.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery) -> None:
    """Экран профиля пользователя"""
    await callback.answer()
    user = get_user(callback.from_user.id)
    if not user:
        return

    level_name, _ = get_level_info(user[16])
    achievements = get_user_achievements(callback.from_user.id)
    ach_text = "\n".join([f"  • {a}" for a in achievements[:5]]) or "  • Пока нет"

    text = (
        f"👤 <b>Ваш профиль</b>\n\n"
        f"🆔 ID: <code>{user[0]}</code>\n"
        f"📝 Username: @{user[1] or 'N/A'}\n"
        f"👤 Имя: {user[2]}\n"
        f"🎖 Уровень: {level_name} (Ур. {user[16]})\n\n"
        f"💰 <b>Баланс:</b>\n"
        f"⭐️ Звёзды: <code>{fmt_number(user[3])}</code>\n"
        f"🪙 T Coin: <code>{fmt_number(user[4])}</code>\n\n"
        f"📈 <b>Активность:</b>\n"
        f"✅ Заданий выполнено: {user[12]}\n"
        f"🎮 Игр сыграно: {user[17]}\n"
        f"🏆 Побед: {user[18]}\n"
        f"👥 Приглашено друзей: {user[13]}\n\n"
        f"🏅 <b>Достижения:</b>\n{ach_text}\n\n"
        f"📅 Регистрация: {user[14][:10]}"
    )

    keyboard = build_keyboard([
        [InlineKeyboardButton(text="🎁 Ежедневный бонус", callback_data="daily"),
         InlineKeyboardButton(text="🎟 Промокод", callback_data="promo_enter")],
        [InlineKeyboardButton(text="📊 История", callback_data="history"),
         InlineKeyboardButton(text="💸 Перевод", callback_data="transfer")],
        [InlineKeyboardButton(text="⭐ Пополнить", callback_data="deposit"),
         InlineKeyboardButton(text="💳 Вывести", callback_data="withdraw")],
        [btn_menu()],
    ])

    await render(callback.message, text, keyboard, is_callback=True)

# =============================================================================
# ========================= ЕЖЕДНЕВНЫЙ БОНУС ================================
# =============================================================================

@dp.callback_query(F.data == "daily")
async def cb_daily(callback: CallbackQuery) -> None:
    """Получение ежедневного бонуса"""
    await callback.answer()

    if can_claim_daily(callback.from_user.id):
        bonus_stars = int(get_setting("daily_bonus_stars") or 10)
        bonus_tcoin = int(get_setting("daily_bonus_tcoin") or 5)
        update_balance(
            callback.from_user.id,
            stars=bonus_stars,
            tcoin=bonus_tcoin,
            desc="Ежедневный бонус"
        )
        set_daily_claimed(callback.from_user.id)

        text = (
            f"🎁 <b>Ежедневный бонус получен!</b>\n\n"
            f"⭐️ +{bonus_stars} звёзд\n"
            f"🪙 +{bonus_tcoin} T Coin\n\n"
            f"Возвращайтесь завтра!"
        )
    else:
        user = get_user(callback.from_user.id)
        try:
            last = datetime.strptime(user[9], "%Y-%m-%d")
            next_time = last + timedelta(days=1)
            delta = next_time - datetime.now()
            hours = delta.seconds // 3600
            minutes = (delta.seconds % 3600) // 60
            text = (
                f"⏰ <b>Бонус уже получен!</b>\n\n"
                f"Следующий через: {hours}ч {minutes}мин"
            )
        except Exception:
            text = "⏰ Бонус уже получен. Возвращайтесь завтра!"

    keyboard = build_keyboard([[btn_profile()]])
    await render(callback.message, text, keyboard, is_callback=True)

# =============================================================================
# ========================= ПРОМОКОДЫ =======================================
# =============================================================================

@dp.callback_query(F.data == "promo_enter")
async def cb_promo_enter(callback: CallbackQuery, state: FSMContext) -> None:
    """Ввод промокода"""
    await callback.answer()
    text = (
        "🎟 <b>Ввод промокода</b>\n\n"
        "Отправьте промокод сообщением.\n"
        "Промокоды дают бонусы!"
    )
    keyboard = build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="profile")]])
    await render(callback.message, text, keyboard, is_callback=True)
    await state.set_state(UserStates.waiting_promo)

@dp.message(UserStates.waiting_promo)
async def process_promo(message: Message, state: FSMContext) -> None:
    """Обработка введённого промокода"""
    await state.clear()
    code = message.text.strip().upper()
    promo = get_promo(code)

    if not promo:
        return await message.answer("❌ Промокод не найден или неактивен.")

    if promo[4] >= promo[3]:  # current_uses >= max_uses
        return await message.answer("❌ Промокод исчерпан.")

    success, status = use_promo(message.from_user.id, code)
    if not success:
        if status == "already_used":
            return await message.answer("❌ Вы уже использовали этот промокод.")
        return

    stars_r = promo[1]
    tcoin_r = promo[2]
    if stars_r > 0 or tcoin_r > 0:
        update_balance(
            message.from_user.id,
            stars=stars_r,
            tcoin=tcoin_r,
            desc=f"Промокод: {code}"
        )

    text = f"✅ <b>Промокод активирован!</b>\n\n🎟 Код: <code>{code}</code>\n\n"
    if stars_r > 0:
        text += f"⭐️ +{stars_r} звёзд\n"
    if tcoin_r > 0:
        text += f"🪙 +{tcoin_r} T Coin\n"

    keyboard = build_keyboard([[btn_profile()]])
    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)

# =============================================================================
# ========================= ИСТОРИЯ ТРАНЗАКЦИЙ ==============================
# =============================================================================

@dp.callback_query(F.data == "history")
async def cb_history(callback: CallbackQuery) -> None:
    """История транзакций"""
    await callback.answer()
    txs = get_transactions(callback.from_user.id)

    if not txs:
        text = "📊 <b>История транзакций</b>\n\nУ вас пока нет операций."
    else:
        text = "📊 <b>Последние операции:</b>\n\n"
        for tx in txs:
            emoji = "🟢" if tx[1] > 0 else "🔴"
            currency = "⭐️" if tx[0] == "stars" else "🪙"
            sign = "+" if tx[1] > 0 else ""
            text += f"{emoji} {sign}{tx[1]} {currency} — <i>{tx[2]}</i>\n"
            text += f"   <code>{tx[3]}</code>\n\n"

    keyboard = build_keyboard([[btn_profile()]])
    await render(callback.message, text, keyboard, is_callback=True)

# =============================================================================
# ========================= ПЕРЕВОДЫ МЕЖДУ ИГРОКАМИ =========================
# =============================================================================

@dp.callback_query(F.data == "transfer")
async def cb_transfer(callback: CallbackQuery, state: FSMContext) -> None:
    """Экран перевода"""
    await callback.answer()
    if get_setting("transfer_enabled") != "1":
        return await callback.answer("❌ Переводы временно отключены", show_alert=True)

    text = (
        "💸 <b>Перевод T Coin</b>\n\n"
        "Отправьте в чат:\n"
        "<code>ID_ПОЛУЧАТЕЛЯ СУММА</code>\n\n"
        "Или ответьте на сообщение пользователя командой:\n"
        "<code>/перевод СУММА</code>\n\n"
        "Пример: <code>123456789 100</code>"
    )
    keyboard = build_keyboard([[btn_profile()]])
    await render(callback.message, text, keyboard, is_callback=True)
    await state.set_state(UserStates.waiting_transfer)

@dp.message(UserStates.waiting_transfer)
async def process_transfer(message: Message, state: FSMContext) -> None:
    """Обработка перевода"""
    await state.clear()
    args = message.text.split()
    if len(args) < 2:
        return await message.answer("❌ Формат: ID СУММА")

    try:
        target_id = await resolve_user_id(args[0], message.reply_to_message)
        amount = int(args[1])
    except (ValueError, TypeError):
        return await message.answer("❌ Неверный формат!")

    if not target_id:
        return await message.answer("❌ Пользователь не найден!")

    if target_id == message.from_user.id:
        return await message.answer("❌ Себе переводить нельзя!")

    if amount <= 0:
        return await message.answer("❌ Сумма должна быть больше 0!")

    user = get_user(message.from_user.id)
    if not user or user[4] < amount:
        return await message.answer("❌ Недостаточно T Coin!")

    target = get_user(target_id)
    if not target:
        return await message.answer("❌ Получатель не найден!")

    update_balance(message.from_user.id, tcoin=-amount, desc=f"Перевод → {target_id}")
    update_balance(target_id, tcoin=amount, desc=f"Перевод ← {message.from_user.id}")

    keyboard = build_keyboard([[btn_profile()]])
    await message.answer(
        f"✅ Переведено <b>{amount} 🪙</b> пользователю {target_id}",
        parse_mode="HTML",
        reply_markup=keyboard
    )
    try:
        await bot.send_message(
            target_id,
            f"💸 Вам перевели <b>{amount} 🪙</b> от @{message.from_user.username or message.from_user.id}!",
            parse_mode="HTML"
        )
    except Exception:
        pass

@dp.message(Command("перевод"))
async def cmd_transfer_reply(message: Message) -> None:
    """Перевод через reply"""
    if not message.reply_to_message:
        return await message.answer("❌ Ответьте на сообщение получателя")

    args = message.text.split()
    if len(args) < 2:
        return await message.answer("❌ Укажите сумму: /перевод 100")

    try:
        amount = int(args[1])
    except ValueError:
        return await message.answer("❌ Сумма — число!")

    target_id = message.reply_to_message.from_user.id
    if target_id == message.from_user.id:
        return await message.answer("❌ Себе нельзя!")

    if amount <= 0:
        return await message.answer("❌ Сумма > 0!")

    user = get_user(message.from_user.id)
    if not user or user[4] < amount:
        return await message.answer("❌ Недостаточно T Coin!")

    update_balance(message.from_user.id, tcoin=-amount, desc=f"Перевод → {target_id}")
    update_balance(target_id, tcoin=amount, desc=f"Перевод ← {message.from_user.id}")

    await message.answer(f"✅ Переведено <b>{amount} 🪙</b>", parse_mode="HTML")

# =============================================================================
# ========================= ЗАДАНИЯ =========================================
# =============================================================================

@dp.callback_query(F.data == "task_get")
async def cb_task_get(callback: CallbackQuery) -> None:
    """Получить задание"""
    await callback.answer()
    user_id = callback.from_user.id
    check_daily_task_reset(user_id)
    user = get_user(user_id)

    max_tasks = int(get_setting("max_tasks_per_day") or 10)
    if user[10] >= max_tasks:
        text = f"⏰ <b>Лимит заданий на сегодня исчерпан!</b>\n\nВыполнено: {max_tasks}/{max_tasks}\nВозвращайтесь завтра!"
        keyboard = build_keyboard([[btn_menu()]])
        return await render(callback.message, text, keyboard, is_callback=True)

    task_data = await pf_get_task(user_id, user_id)

    if task_data.get("status") == "ok" and task_data.get("sponsors"):
        sponsor = task_data["sponsors"][0]
        user_current_task[user_id] = {
            "link": sponsor["link"],
            "price": sponsor.get("price", 5),
            "verify": False
        }
        text = (
            f"📋 <b>Текущее задание:</b>\n\n"
            f"Подпишитесь на канал и получите <b>{sponsor.get('price', 5)} ⭐️</b>"
        )
        keyboard = build_keyboard([
            [InlineKeyboardButton(text="🔗 Подписаться", url=sponsor["link"])],
            [InlineKeyboardButton(text="✅ Проверить подписку", callback_data="task_check")],
            [btn_menu()],
        ])
    else:
        text = "🎉 <b>На данный момент заданий нет.</b>\n\nЗагляните позже!"
        keyboard = build_keyboard([[btn_menu()]])

    await render(callback.message, text, keyboard, is_callback=True)

@dp.callback_query(F.data == "task_check")
async def cb_task_check(callback: CallbackQuery) -> None:
    """Проверить выполнение задания"""
    await callback.answer()
    user_id = callback.from_user.id
    task = user_current_task.get(user_id)

    if not task:
        return await callback.answer("❌ Сначала возьмите задание!", show_alert=True)

    check_data = await pf_check_task(user_id, task["link"])

    if check_data.get("status") == "ok":
        completed = [s for s in check_data.get("sponsors", []) if s.get("status") == "subscribed"]
        if completed:
            reward = task["price"]
            update_balance(user_id, stars=reward, desc="Выполнение задания")

            # Если это верификация
            if task.get("verify"):
                update_user_field(user_id, "is_verified", 1)
                user = get_user(user_id)
                # Начислить бонус рефереру
                if user[6]:  # referred_by
                    bonus = int(get_setting("referral_bonus") or 5)
                    update_balance(user[6], stars=bonus, desc="Реферал верифицирован")
                    increment_referrals(user[6])
                    try:
                        await bot.send_message(
                            user[6],
                            f"🎉 <b>Реферал подтверждён!</b>\n+{bonus} ⭐️",
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
                user_current_task.pop(user_id, None)

                text = f"✅ <b>Верификация пройдена!</b>\n\n+{reward} ⭐️\nДобро пожаловать!"
                keyboard = build_keyboard([[btn_menu()]])
                await render(callback.message, text, keyboard, is_callback=True)
                return

            increment_tasks(user_id)
            user_current_task.pop(user_id, None)
            user = get_user(user_id)

            # Проверка повышения уровня
            new_level = check_level_up(user_id)
            level_text = f"\n🎉 <b>Повышение до уровня {new_level}!</b>" if new_level else ""

            max_tasks = int(get_setting("max_tasks_per_day") or 10)
            text = (
                f"✅ <b>Задание выполнено!</b>\n\n"
                f"⭐️ +{reward}\n\n"
                f"📊 Сегодня: {user[10]}/{max_tasks}\n"
                f"📈 Всего: {user[12]}{level_text}"
            )

            keyboard_rows = []
            if user[10] < max_tasks:
                keyboard_rows.append([InlineKeyboardButton(text="📋 Следующее задание", callback_data="task_get")])
            keyboard_rows.append([btn_menu()])
            keyboard = build_keyboard(keyboard_rows)

            await render(callback.message, text, keyboard, is_callback=True)
        else:
            await callback.answer("⏳ Вы ещё не подписались!", show_alert=True)
    else:
        await callback.answer("❌ Ошибка проверки. Попробуйте позже.", show_alert=True)

# =============================================================================
# ========================= ОБМЕН ВАЛЮТ =====================================
# =============================================================================

@dp.callback_query(F.data == "exchange")
async def cb_exchange(callback: CallbackQuery) -> None:
    """Экран обмена валют"""
    await callback.answer()
    user = get_user(callback.from_user.id)
    rate = int(get_setting("exchange_rate") or 10)
    available = user[3] // rate

    text = (
        f"💱 <b>Обмен валют</b>\n\n"
        f"💱 <b>Курс:</b> <code>{rate} ⭐️ = 1 🪙</code>\n\n"
        f"⭐️ Ваш баланс: <code>{fmt_number(user[3])}</code>\n"
        f"🪙 Доступно для обмена: <code>{fmt_number(available)}</code>"
    )

    keyboard_rows = []
    if available > 0:
        keyboard_rows.append([InlineKeyboardButton(
            text=f"🔄 Обменять всё ({available} 🪙)",
            callback_data=f"do_ex_{available}"
        )])
    keyboard_rows.append([btn_menu()])
    keyboard = build_keyboard(keyboard_rows)

    await render(callback.message, text, keyboard, is_callback=True)

@dp.callback_query(F.data.startswith("do_ex_"))
async def cb_do_exchange(callback: CallbackQuery) -> None:
    """Выполнить обмен"""
    await callback.answer()
    amount = int(callback.data.split("_")[-1])
    user = get_user(callback.from_user.id)
    rate = int(get_setting("exchange_rate") or 10)
    cost = amount * rate

    if user[3] >= cost:
        update_balance(
            callback.from_user.id,
            stars=-cost,
            tcoin=amount,
            desc=f"Обмен {cost}⭐ → {amount}🪙"
        )
        text = (
            f"✅ <b>Обмен выполнен!</b>\n\n"
            f"📉 Списано: {cost} ⭐️\n"
            f"📈 Начислено: {amount} 🪙\n\n"
            f"💰 Новый баланс:\n"
            f"⭐️ {user[3] - cost}\n"
            f"🪙 {user[4] + amount}"
        )
    else:
        text = "❌ Недостаточно звёзд!"

    keyboard = build_keyboard([[btn_menu()]])
    await render(callback.message, text, keyboard, is_callback=True)

# =============================================================================
# ========================= ПОПОЛНЕНИЕ ЧЕРЕЗ ИНВОЙС =========================
# =============================================================================

@dp.callback_query(F.data == "deposit")
async def cb_deposit(callback: CallbackQuery) -> None:
    """Экран пополнения"""
    await callback.answer()
    if get_setting("deposit_enabled") != "1":
        return await callback.answer("❌ Пополнение временно отключено", show_alert=True)

    text = (
        "⭐ <b>Пополнение звёзд</b>\n\n"
        "Выберите пакет или введите сумму:\n\n"
        "💎 100 ⭐️ — 100 звёзд\n"
        "💎 500 ⭐️ — 500 звёзд\n"
        "💎 1000 ⭐️ — 1000 звёзд\n\n"
        "Или отправьте сумму сообщением."
    )

    keyboard = build_keyboard([
        [InlineKeyboardButton(text="💎 100 ⭐️", callback_data="dep_100"),
         InlineKeyboardButton(text="💎 500 ⭐️", callback_data="dep_500")],
        [InlineKeyboardButton(text="💎 1000 ⭐️", callback_data="dep_1000")],
        [btn_profile()],
    ])

    await render(callback.message, text, keyboard, is_callback=True)

@dp.callback_query(F.data.startswith("dep_"))
async def cb_deposit_amount(callback: CallbackQuery) -> None:
    """Создать инвойс на пополнение"""
    await callback.answer()
    amount = int(callback.data.split("_")[-1])

    if amount <= 0 or amount > 100000:
        return await callback.answer("❌ Неверная сумма", show_alert=True)

    try:
        # Создаём инвойс звёзд
        # В Telegram Stars: 1 звезда = 100 единиц (копеек)
        invoice_link = await bot.create_invoice_link(
            title=f"Пополнение на {amount} ⭐️",
            description=f"Пополнение баланса на {amount} звёзд",
            payload=f"deposit_{callback.from_user.id}_{amount}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{amount} Stars", amount=amount * 100)]
        )

        # Сохраняем ожидающий депозит
        pending_deposits[callback.from_user.id] = amount

        text = (
            f"💳 <b>Оплата инвойса</b>\n\n"
            f"Сумма: <b>{amount} ⭐️</b>\n\n"
            f"Нажмите кнопку ниже для оплаты:"
        )
        keyboard = build_keyboard([
            [InlineKeyboardButton(text="💳 Оплатить", url=invoice_link)],
            [btn_profile()],
        ])
        await render(callback.message, text, keyboard, is_callback=True)
    except Exception as e:
        logging.error(f"Invoice creation error: {e}")
        await callback.answer("❌ Ошибка создания инвойса", show_alert=True)

@dp.pre_checkout_query()
async def process_pre_checkout(pre_checkout: PreCheckoutQuery) -> None:
    """Обработка pre-checkout запроса"""
    await pre_checkout.answer(ok=True)

@dp.message(F.successful_payment)
async def process_successful_payment(message: Message) -> None:
    """Обработка успешного платежа"""
    payment = message.successful_payment
    payload = payment.invoice_payload

    # Парсим payload: deposit_USERID_AMOUNT
    try:
        parts = payload.split("_")
        if parts[0] == "deposit" and len(parts) >= 3:
            user_id = int(parts[1])
            amount = int(parts[2])

            # Начисляем звёзды
            update_balance(user_id, stars=amount, desc=f"Пополнение через инвойс")

            # Создаём заявку для учёта
            create_request(user_id, "deposit", amount)
            update_request_status(create_request(user_id, "deposit", amount), "approved")

            await message.answer(
                f"✅ <b>Платёж успешен!</b>\n\n"
                f"⭐️ +{amount} звёзд зачислено на ваш баланс!\n\n"
                f"Спасибо за пополнение!",
                parse_mode="HTML"
            )

            # Уведомление админу
            try:
                await bot.send_message(
                    ADMIN_ID,
                    f"💰 <b>Новое пополнение!</b>\n\n"
                    f"👤 Пользователь: {user_id}\n"
                    f"💵 Сумма: {amount} ⭐️",
                    parse_mode="HTML"
                )
            except Exception:
                pass
    except Exception as e:
        logging.error(f"Payment processing error: {e}")
        await message.answer("❌ Ошибка обработки платежа. Свяжитесь с поддержкой.")

# =============================================================================
# ========================= ВЫВОД СРЕДСТВ ===================================
# =============================================================================

@dp.callback_query(F.data == "withdraw")
async def cb_withdraw(callback: CallbackQuery) -> None:
    """Экран вывода"""
    await callback.answer()
    if get_setting("withdraw_enabled") != "1":
        return await callback.answer("❌ Вывод временно отключён", show_alert=True)

    user = get_user(callback.from_user.id)
    text = (
        f"💳 <b>Вывод звёзд</b>\n\n"
        f"⭐️ Ваш баланс: <code>{user[3]}</code>\n\n"
        f"Отправьте сумму вывода сообщением.\n"
        f"Минимум: 50 ⭐️"
    )
    keyboard = build_keyboard([[btn_profile()]])
    await render(callback.message, text, keyboard, is_callback=True)
    await callback.message.answer(
        "💳 Введите сумму для вывода (минимум 50 ⭐️):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[btn_profile()]])
    )

# =============================================================================
# ========================= ИГРОВОЕ МЕНЮ ====================================
# =============================================================================

@dp.callback_query(F.data == "games_menu")
async def cb_games_menu(callback: CallbackQuery) -> None:
    """Меню игр"""
    await callback.answer()
    if get_setting("games_enabled") != "1":
        return await callback.answer("❌ Игры временно отключены", show_alert=True)

    min_bet = get_setting("min_bet") or "10"
    max_bet = get_setting("max_bet") or "50000"

    text = (
        "🎮 <b>Игровой зал</b>\n\n"
        "🎰 <code>/сл [сумма]</code> — Слоты (×10)\n"
        "🎲 <code>/кости [режим] [сумма] [параметр]</code>\n"
        "🎯 <code>/дротик [сумма]</code> / <code>/дротик промах [сумма]</code>\n"
        "🏀 <code>/баскет [сумма]</code> / <code>/баскет промах [сумма]</code>\n"
        "⚽ <code>/футбол [сумма]</code>\n"
        "🎡 <code>/рул [тип] [сумма] [параметр]</code>\n"
        "🪙 <code>/мон [сумма] [о/р]</code>\n"
        "📊 <code>/больше [сумма]</code> / <code>/меньше [сумма]</code>\n"
        "💣 <code>/мины [сумма] [1-5]</code>\n"
        "🚀 <code>/краш [сумма] [множитель]</code>\n\n"
        f"💵 Ставки: {min_bet}–{max_bet} 🪙"
    )

    keyboard = build_keyboard([[btn_menu()]])
    await render(callback.message, text, keyboard, is_callback=True)

# =============================================================================
# ========================= ИГРОВЫЕ УТИЛИТЫ =================================
# =============================================================================

def parse_bet(args: List[str], idx: int = 1) -> Tuple[Optional[int], Optional[str]]:
    """Извлечь ставку из аргументов. Возвращает (bet, error_msg)"""
    if len(args) <= idx:
        return None, "⚠️ Укажите ставку!"
    try:
        bet = int(args[idx])
    except ValueError:
        return None, "❌ Ставка должна быть числом!"

    min_bet = int(get_setting("min_bet") or 10)
    max_bet = int(get_setting("max_bet") or 50000)

    if bet < min_bet:
        return None, f"❌ Минимальная ставка: {min_bet} 🪙"
    if bet > max_bet:
        return None, f"❌ Максимальная ставка: {max_bet} 🪙"
    return bet, None

def check_balance(user_id: int, bet: int) -> bool:
    """Проверить баланс T Coin"""
    user = get_user(user_id)
    return bool(user and user[4] >= bet)

def get_dice_emoji_for_value(emoji: str, value: int) -> str:
    """
    Получить эмодзи-результат в зависимости от выпавшего значения.
    Эмодзи напрямую зависят от результата.
    """
    if emoji == "🎰":  # Слоты
        if value >= 60:
            return "🔥💎🔥 ДЖЕКПОТ!"
        elif value >= 40:
            return "🍒🍒🍒 Отличный выигрыш!"
        elif value >= 20:
            return "🍋🍒🍋 Почти!"
        else:
            return "🍋🍋🍋 Не повезло"

    elif emoji == "🎲":  # Кости
        symbols = {1: "⚀", 2: "⚁", 3: "⚂", 4: "⚃", 5: "⚄", 6: "⚅"}
        return f"{symbols.get(value, str(value))} ({value})"

    elif emoji == "🎯":  # Дротик
        if value == 6:
            return "🎯 ЯБЛОЧКО!"
        elif value == 5:
            return "🎯 Почти в центре!"
        elif value == 4:
            return "🎯 Попадание!"
        elif value == 3:
            return "🎯 Рядом!"
        elif value == 2:
            return "🎯 Промах"
        else:
            return "💨 Мимо мишени!"

    elif emoji == "🏀":  # Баскетбол
        if value == 5:
            return "🏀 СЛЭМ-ДАНК!"
        elif value == 4:
            return "🏀 Почти попал!"
        elif value == 3:
            return "🏀 Бросок"
        elif value == 2:
            return "🏀 Промах"
        else:
            return "🏀 Увы!"

    elif emoji == "⚽":  # Футбол
        if value == 6:
            return "⚽ ГООООЛ!"
        elif value == 5:
            return "⚽ Отличный удар!"
        elif value == 4:
            return "⚽ Попадание!"
        elif value == 3:
            return "⚽ В штангу!"
        elif value == 2:
            return "⚽ Вратарь спас!"
        else:
            return "⚽ Промах!"

    elif emoji == "🎳":  # Боулинг
        if value == 6:
            return "🎳 СТРАЙК!"
        elif value >= 4:
            return "🎳 Отлично!"
        else:
            return "🎳 Слабый бросок"

    return f"🎮 Результат: {value}"

async def send_game_result(message: Message, emoji: str, value: int,
                           bet: int, won: bool, multiplier: float,
                           game_name: str) -> None:
    """Отправить результат игры"""
    result_emoji = get_dice_emoji_for_value(emoji, value)

    if won:
        payout = int(bet * multiplier)
        update_balance(message.from_user.id, tcoin=payout, desc=f"Выигрыш в {game_name}")
        increment_games(message.from_user.id, won=True)

        await message.answer(
            f"🎮 <b>{game_name}</b>\n\n"
            f"{result_emoji}\n\n"
            f"🎉 <b>ПОБЕДА!</b>\n\n"
            f"💰 Ставка: {bet} 🪙\n"
            f"📈 Множитель: ×{multiplier}\n"
            f"✅ Выигрыш: <b>{payout} 🪙</b>",
            parse_mode="HTML"
        )
    else:
        increment_games(message.from_user.id, won=False)
        await message.answer(
            f"🎮 <b>{game_name}</b>\n\n"
            f"{result_emoji}\n\n"
            f"😔 <b>Проигрыш</b>\n\n"
            f"Потеряно: {bet} 🪙",
            parse_mode="HTML"
        )

async def check_game_ready(message: Message) -> bool:
    """Проверить готовность к игре"""
    user = get_user(message.from_user.id)
    if not user:
        return False
    if user[8]:  # забанен
        await message.answer("❌ Вы заблокированы.")
        return False
    if not is_verified(message.from_user.id):
        await message.answer("⚠️ Сначала пройдите верификацию (/start)")
        return False
    if get_setting("games_enabled") != "1":
        await message.answer("❌ Игры временно отключены.")
        return False
    return True

# =============================================================================
# ========================= ИГРА 1: СЛОТЫ ===================================
# =============================================================================

@dp.message(Command("сл", "слоты", "slot", "slots"))
async def game_slots(message: Message) -> None:
    """Игра: Слоты"""
    if not await check_game_ready(message):
        return

    bet, err = parse_bet(message.text.split())
    if err:
        return await message.answer(err)
    if not check_balance(message.from_user.id, bet):
        return await message.answer("❌ Недостаточно T Coin!")

    update_balance(message.from_user.id, tcoin=-bet, desc="Ставка: Слоты")
    dm = await message.answer_dice(emoji="🎰")
    value = dm.dice.value

    # Джекпот на 1, малый выигрыш на ≤10
    if value == 1:
        await send_game_result(message, "🎰", value, bet, True, 10, "Слоты")
    elif value <= 10:
        await send_game_result(message, "🎰", value, bet, True, 2, "Слоты")
    else:
        await send_game_result(message, "🎰", value, bet, False, 0, "Слоты")

# =============================================================================
# ========================= ИГРА 2: КОСТИ ===================================
# =============================================================================

@dp.message(Command("кости", "dice"))
async def game_dice(message: Message) -> None:
    """Игра: Кости (3 режима)"""
    if not await check_game_ready(message):
        return

    args = message.text.split()
    if len(args) < 3:
        return await message.answer(
            "🎲 <b>Режимы:</b>\n\n"
            "<code>/кости число 100 3</code> — угадать число (×6)\n"
            "<code>/кости чет 100 чет</code> — чёт/нечет (×2)\n"
            "<code>/кости больше 100 б</code> — больше/меньше (×2)",
            parse_mode="HTML"
        )

    mode = args[1].lower()

    # Режим: число
    if mode == "число":
        if len(args) < 4:
            return await message.answer("⚠️ Укажите число: /кости число 100 3")
        bet, err = parse_bet(args, 2)
        if err:
            return await message.answer(err)
        try:
            target = int(args[3])
        except ValueError:
            return await message.answer("❌ Число от 1 до 6!")
        if not 1 <= target <= 6:
            return await message.answer("❌ Число от 1 до 6!")
        if not check_balance(message.from_user.id, bet):
            return await message.answer("❌ Недостаточно T Coin!")

        update_balance(message.from_user.id, tcoin=-bet, desc="Ставка: Кости-число")
        dm = await message.answer_dice(emoji="🎲")
        value = dm.dice.value
        won = value == target
        await send_game_result(message, "🎲", value, bet, won, 6, f"Кости (число {target})")

    # Режим: чёт/нечет
    elif mode in ["чет", "чёт"]:
        if len(args) < 4:
            return await message.answer("⚠️ /кости чет 100 чет")
        bet, err = parse_bet(args, 2)
        if err:
            return await message.answer(err)
        choice = args[3].lower()
        if choice in ["чет", "чёт", "ч"]:
            want_even = True
        elif choice in ["нечет", "нечёт", "нч", "н"]:
            want_even = False
        else:
            return await message.answer("❌ Укажите: чет/нечет")

        if not check_balance(message.from_user.id, bet):
            return await message.answer("❌ Недостаточно T Coin!")

        update_balance(message.from_user.id, tcoin=-bet, desc="Ставка: Кости-чет")
        dm = await message.answer_dice(emoji="🎲")
        value = dm.dice.value
        is_even = value % 2 == 0
        won = is_even == want_even
        await send_game_result(message, "🎲", value, bet, won, 2,
                               f"Кости ({'чёт' if want_even else 'нечёт'})")

    # Режим: больше/меньше
    elif mode in ["больше", "меньше", "б", "м"]:
        if len(args) < 4:
            return await message.answer("⚠️ /кости больше 100 б")
        bet, err = parse_bet(args, 2)
        if err:
            return await message.answer(err)
        choice = args[3].lower()
        if choice in ["больше", "б"]:
            want_high = True
        elif choice in ["меньше", "м"]:
            want_high = False
        else:
            return await message.answer("❌ Укажите: б/м")

        if not check_balance(message.from_user.id, bet):
            return await message.answer("❌ Недостаточно T Coin!")

        update_balance(message.from_user.id, tcoin=-bet, desc="Ставка: Кости-больше")
        dm = await message.answer_dice(emoji="🎲")
        value = dm.dice.value
        is_high = value >= 4
        won = is_high == want_high
        await send_game_result(message, "🎲", value, bet, won, 2,
                               f"Кости ({'больше' if want_high else 'меньше'})")

    else:
        await message.answer("❌ Неизвестный режим. Доступны: число, чет, больше")

# =============================================================================
# ========================= ИГРА 3: ДРОТИК ==================================
# =============================================================================

@dp.message(Command("дротик", "darts"))
async def game_darts(message: Message) -> None:
    """Игра: Дротик"""
    if not await check_game_ready(message):
        return

    args = message.text.split()
    want_miss = False
    bet_idx = 1

    if len(args) > 1 and args[1].lower() == "промах":
        want_miss = True
        bet_idx = 2

    bet, err = parse_bet(args, bet_idx)
    if err:
        return await message.answer(err)
    if not check_balance(message.from_user.id, bet):
        return await message.answer("❌ Недостаточно T Coin!")

    update_balance(message.from_user.id, tcoin=-bet, desc="Ставка: Дротик")
    dm = await message.answer_dice(emoji="🎯")
    value = dm.dice.value
    hit = value >= 4
    won = (not hit) if want_miss else hit
    await send_game_result(message, "🎯", value, bet, won, 1.9,
                           f"Дротик ({'промах' if want_miss else 'попадание'})")

# =============================================================================
# ========================= ИГРА 4: БАСКЕТБОЛ ===============================
# =============================================================================

@dp.message(Command("баскет", "basket"))
async def game_basket(message: Message) -> None:
    """Игра: Баскетбол"""
    if not await check_game_ready(message):
        return

    args = message.text.split()
    want_miss = False
    bet_idx = 1

    if len(args) > 1 and args[1].lower() == "промах":
        want_miss = True
        bet_idx = 2

    bet, err = parse_bet(args, bet_idx)
    if err:
        return await message.answer(err)
    if not check_balance(message.from_user.id, bet):
        return await message.answer("❌ Недостаточно T Coin!")

    update_balance(message.from_user.id, tcoin=-bet, desc="Ставка: Баскетбол")
    dm = await message.answer_dice(emoji="🏀")
    value = dm.dice.value
    hit = value == 5
    won = (not hit) if want_miss else hit
    await send_game_result(message, "🏀", value, bet, won, 1.9,
                           f"Баскетбол ({'промах' if want_miss else 'попадание'})")

# =============================================================================
# ========================= ИГРА 5: ФУТБОЛ ==================================
# =============================================================================

@dp.message(Command("футбол", "foot"))
async def game_football(message: Message) -> None:
    """Игра: Футбол"""
    if not await check_game_ready(message):
        return

    bet, err = parse_bet(message.text.split())
    if err:
        return await message.answer(err)
    if not check_balance(message.from_user.id, bet):
        return await message.answer("❌ Недостаточно T Coin!")

    update_balance(message.from_user.id, tcoin=-bet, desc="Ставка: Футбол")
    dm = await message.answer_dice(emoji="⚽")
    value = dm.dice.value
    won = value >= 4
    await send_game_result(message, "⚽", value, bet, won, 2, "Футбол")

# =============================================================================
# ========================= ИГРА 6: РУЛЕТКА =================================
# =============================================================================

@dp.message(Command("рул", "roulette"))
async def game_roulette(message: Message) -> None:
    """Игра: Рулетка"""
    if not await check_game_ready(message):
        return

    args = message.text.split()
    if len(args) < 4:
        return await message.answer(
            "🎡 <b>Рулетка:</b>\n\n"
            "<code>/рул цвет 100 к</code> — красный/чёрный/зеро (×2/×14)\n"
            "<code>/рул чет 100 чет</code> — чёт/нечет (×2)\n"
            "<code>/рул половина 100 верх</code> — верх/низ (×2)\n"
            "<code>/рул число 100 17</code> — точное число (×36)\n"
            "<code>/рул дюжина 100 1</code> — дюжина (×3)",
            parse_mode="HTML"
        )

    mode = args[1].lower()
    bet, err = parse_bet(args, 2)
    if err:
        return await message.answer(err)
    if not check_balance(message.from_user.id, bet):
        return await message.answer("❌ Недостаточно T Coin!")

    update_balance(message.from_user.id, tcoin=-bet, desc=f"Ставка: Рулетка {mode}")
    num = random.randint(0, 36)

    # Красные числа в рулетке
    reds = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    param = args[3].lower()
    won = False
    mult = 0

    if mode == "цвет":
        if param in ["к", "красное", "красный"]:
            won = num in reds
            mult = 2
        elif param in ["ч", "черное", "чёрное", "черный"]:
            won = num != 0 and num not in reds
            mult = 2
        elif param in ["з", "зеро", "зеленое", "зелёное"]:
            won = num == 0
            mult = 14
        else:
            return await message.answer("❌ Укажите: к/ч/з")

    elif mode == "чет":
        if param in ["чет", "чёт", "ч"]:
            won = num != 0 and num % 2 == 0
            mult = 2
        elif param in ["нечет", "нечёт", "нч", "н"]:
            won = num != 0 and num % 2 != 0
            mult = 2
        else:
            return await message.answer("❌ Укажите: чет/нечет")

    elif mode == "половина":
        if param in ["низ", "н"]:
            won = 1 <= num <= 18
            mult = 2
        elif param in ["верх", "в"]:
            won = 19 <= num <= 36
            mult = 2
        else:
            return await message.answer("❌ Укажите: верх/низ")

    elif mode == "число":
        try:
            target = int(param)
        except ValueError:
            return await message.answer("❌ Число 0-36!")
        if not 0 <= target <= 36:
            return await message.answer("❌ Число 0-36!")
        won = num == target
        mult = 36

    elif mode == "дюжина":
        try:
            d = int(param)
        except ValueError:
            return await message.answer("❌ Дюжина 1/2/3!")
        if d == 1:
            won = 1 <= num <= 12
            mult = 3
        elif d == 2:
            won = 13 <= num <= 24
            mult = 3
        elif d == 3:
            won = 25 <= num <= 36
            mult = 3
        else:
            return await message.answer("❌ Дюжина 1/2/3!")
    else:
        return await message.answer("❌ Режимы: цвет, чет, половина, число, дюжина")

    # Определяем цвет и эмодзи
    if num == 0:
        color_emoji = "🟢"
        color_name = "Зеро"
    elif num in reds:
        color_emoji = "🔴"
        color_name = "Красное"
    else:
        color_emoji = "⚫"
        color_name = "Чёрное"

    if won:
        payout = int(bet * mult)
        update_balance(message.from_user.id, tcoin=payout, desc=f"Рулетка выигрыш {num}")
        increment_games(message.from_user.id, won=True)
        await message.answer(
            f"🎡 <b>Рулетка:</b> {color_emoji} <b>{num}</b> ({color_name})\n\n"
            f"🎉 <b>ПОБЕДА!</b>\n\n"
            f"💰 Ставка: {bet} 🪙\n"
            f"📈 Множитель: ×{mult}\n"
            f"✅ Выигрыш: <b>{payout} 🪙</b>",
            parse_mode="HTML"
        )
    else:
        increment_games(message.from_user.id, won=False)
        await message.answer(
            f"🎡 <b>Рулетка:</b> {color_emoji} <b>{num}</b> ({color_name})\n\n"
            f"😔 <b>Проигрыш</b>\n\n"
            f"Потеряно: {bet} 🪙",
            parse_mode="HTML"
        )

# =============================================================================
# ========================= ИГРА 7: МОНЕТКА =================================
# =============================================================================

@dp.message(Command("мон", "coin"))
async def game_coin(message: Message) -> None:
    """Игра: Монетка"""
    if not await check_game_ready(message):
        return

    args = message.text.split()
    if len(args) < 3:
        return await message.answer("⚠️ <code>/мон 100 о</code> (о/р)", parse_mode="HTML")

    bet, err = parse_bet(args, 1)
    if err:
        return await message.answer(err)

    choice = args[2].lower()
    if choice in ["о", "орел", "орёл", "heads"]:
        want_heads = True
    elif choice in ["р", "решка", "tails"]:
        want_heads = False
    else:
        return await message.answer("❌ Укажите: о (орёл) или р (решка)")

    if not check_balance(message.from_user.id, bet):
        return await message.answer("❌ Недостаточно T Coin!")

    update_balance(message.from_user.id, tcoin=-bet, desc="Ставка: Монетка")
    result = random.choice(["орёл", "решка"])
    won = (result == "орёл") == want_heads

    # Эмодзи зависит от результата
    if result == "орёл":
        emoji = "🦅"
        result_text = "Орёл!"
    else:
        emoji = "🪙"
        result_text = "Решка!"

    if won:
        payout = bet * 2
        update_balance(message.from_user.id, tcoin=payout, desc="Монетка выигрыш")
        increment_games(message.from_user.id, won=True)
        await message.answer(
            f"{emoji} <b>{result_text}</b>\n\n"
            f"🎉 <b>ПОБЕДА!</b>\n\n"
            f"💰 Ставка: {bet} 🪙\n"
            f"✅ Выигрыш: <b>{payout} 🪙</b>",
            parse_mode="HTML"
        )
    else:
        increment_games(message.from_user.id, won=False)
        await message.answer(
            f"{emoji} <b>{result_text}</b>\n\n"
            f"😔 <b>Проигрыш</b>\n\n"
            f"Потеряно: {bet} 🪙",
            parse_mode="HTML"
        )

# =============================================================================
# ========================= ИГРА 8: БОЛЬШЕ/МЕНЬШЕ ===========================
# =============================================================================

@dp.message(Command("больше", "меньше", "hilo"))
async def game_hilo(message: Message) -> None:
    """Игра: Больше/Меньше"""
    if not await check_game_ready(message):
        return

    args = message.text.split()
    cmd = args[0].replace("/", "").lower()

    bet, err = parse_bet(args)
    if err:
        return await message.answer(err)
    if not check_balance(message.from_user.id, bet):
        return await message.answer("❌ Недостаточно T Coin!")

    update_balance(message.from_user.id, tcoin=-bet, desc=f"Ставка: {cmd}")
    num = random.randint(1, 100)

    # Ничья на 50
    if num == 50:
        update_balance(message.from_user.id, tcoin=bet, desc="High/Low ничья")
        await message.answer(
            f"📊 <b>Число: {num}</b>\n\n"
            f"🤝 <b>Ничья!</b>\n\n"
            f"Ставка возвращена.",
            parse_mode="HTML"
        )
        return

    if cmd == "больше":
        won = num >= 51
        game_name = "Больше"
    else:
        won = num <= 49
        game_name = "Меньше"

    # Эмодзи зависит от результата
    if num >= 75:
        emoji = "🔥"
    elif num >= 51:
        emoji = "📈"
    elif num <= 25:
        emoji = "❄️"
    else:
        emoji = "📉"

    if won:
        payout = int(bet * 1.9)
        update_balance(message.from_user.id, tcoin=payout, desc=f"{game_name} выигрыш {num}")
        increment_games(message.from_user.id, won=True)
        await message.answer(
            f"{emoji} <b>Число: {num}</b>\n\n"
            f"🎉 <b>ПОБЕДА!</b>\n\n"
            f"💰 Ставка: {bet} 🪙\n"
            f"📈 ×1.9\n"
            f"✅ Выигрыш: <b>{payout} 🪙</b>",
            parse_mode="HTML"
        )
    else:
        increment_games(message.from_user.id, won=False)
        await message.answer(
            f"{emoji} <b>Число: {num}</b>\n\n"
            f"😔 <b>Проигрыш</b>\n\n"
            f"Потеряно: {bet} 🪙",
            parse_mode="HTML"
        )

# =============================================================================
# ========================= ИГРА 9: МИНЫ ====================================
# =============================================================================

@dp.message(Command("мины", "mines"))
async def game_mines(message: Message) -> None:
    """Игра: Мины"""
    if not await check_game_ready(message):
        return

    args = message.text.split()
    if len(args) < 3:
        return await message.answer("⚠️ <code>/мины 100 3</code> (мины 1-5)", parse_mode="HTML")

    bet, err = parse_bet(args, 1)
    if err:
        return await message.answer(err)

    try:
        mines_count = int(args[2])
    except ValueError:
        return await message.answer("❌ Мины: 1-5!")

    if not 1 <= mines_count <= 5:
        return await message.answer("❌ Мины: 1-5!")

    if not check_balance(message.from_user.id, bet):
        return await message.answer("❌ Недостаточно T Coin!")

    update_balance(message.from_user.id, tcoin=-bet, desc=f"Ставка: Мины ({mines_count})")

    # Генерируем позиции мин
    total_tiles = 6
    mine_positions = set(random.sample(range(1, total_tiles + 1), mines_count))

    multiplier = 1.0
    safe_opened = 0
    results = []

    # Открываем плитки по одной через кубики
    for i in range(total_tiles):
        if safe_opened == total_tiles - mines_count:
            break

        dm = await message.answer_dice(emoji="🎲")
        val = dm.dice.value
        results.append(val)

        if val in mine_positions:
            # Попали на мину
            await message.answer(
                f"💣 <b>МИНА!</b>\n\n"
                f"🎲 Выпало: {val}\n\n"
                f"😔 <b>Проигрыш!</b>\n\n"
                f"Открыто плиток: {safe_opened}\n"
                f"Потеряно: {bet} 🪙",
                parse_mode="HTML"
            )
            increment_games(message.from_user.id, won=False)
            return

        safe_opened += 1
        multiplier += mines_count * 0.4
        await asyncio.sleep(0.5)

    # Все мины обойдены
    payout = int(bet * multiplier)
    update_balance(message.from_user.id, tcoin=payout, desc=f"Мины выигрыш ×{multiplier:.1f}")
    increment_games(message.from_user.id, won=True)

    await message.answer(
        f"💎 <b>Все мины обойдены!</b>\n\n"
        f"🎉 <b>ПОБЕДА!</b>\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"📈 ×{multiplier:.1f}\n"
        f"✅ Выигрыш: <b>{payout} 🪙</b>",
        parse_mode="HTML"
    )

# =============================================================================
# ========================= ИГРА 10: КРАШ ===================================
# =============================================================================

@dp.message(Command("краш", "crash"))
async def game_crash(message: Message) -> None:
    """Игра: Краш"""
    if not await check_game_ready(message):
        return

    args = message.text.split()
    if len(args) < 3:
        return await message.answer("⚠️ <code>/краш 100 2.0</code> (авто-вывод)", parse_mode="HTML")

    bet, err = parse_bet(args, 1)
    if err:
        return await message.answer(err)

    try:
        cashout = float(args[2])
    except ValueError:
        return await message.answer("❌ Множитель — число (1.1-100)!")

    if not 1.1 <= cashout <= 100:
        return await message.answer("❌ Множитель от 1.1 до 100!")

    if not check_balance(message.from_user.id, bet):
        return await message.answer("❌ Недостаточно T Coin!")

    update_balance(message.from_user.id, tcoin=-bet, desc=f"Ставка: Краш ×{cashout}")

    # Точка краха (случайная, но с математическим ожиданием)
    crash_point = round(100 / random.randint(1, 100), 2)

    steps = [1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0]
    anim = "🚀 <b>Краш:</b>\n"

    for s in steps:
        if s > crash_point:
            break
        anim += f"  📈 ×{s}...\n"
        await asyncio.sleep(0.3)

    # Эмодзи зависит от результата
    if crash_point >= cashout:
        payout = int(bet * cashout)
        update_balance(message.from_user.id, tcoin=payout, desc=f"Краш выигрыш ×{cashout}")
        increment_games(message.from_user.id, won=True)
        anim += (
            f"\n💥 Краш на ×{crash_point}\n\n"
            f"🎉 <b>Успели вывести на ×{cashout}!</b>\n\n"
            f"✅ Выигрыш: <b>{payout} 🪙</b>"
        )
    else:
        increment_games(message.from_user.id, won=False)
        anim += (
            f"\n💥 <b>КРАШ на ×{crash_point}!</b>\n\n"
            f"😔 Не успели вывести.\n"
            f"Потеряно: {bet} 🪙"
        )

    await message.answer(anim, parse_mode="HTML")

# =============================================================================
# ========================= АДМИН-ПАНЕЛЬ (КНОПКИ) ===========================
# =============================================================================

@dp.callback_query(F.data == "admin")
async def cb_admin(callback: CallbackQuery) -> None:
    """Главное меню админки"""
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    await callback.answer()

    stats = get_bot_stats()
    text = (
        f"👑 <b>Админ-панель</b>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"👥 Пользователей: {stats['total_users']}\n"
        f"✅ Активных: {stats['active_users']}\n"
        f"🚫 Забанено: {stats['banned_users']}\n"
        f"🆕 Сегодня: {stats['new_today']}\n"
        f"💰 Всего звёзд: {fmt_number(stats['total_stars'])}\n"
        f"🪙 Всего T Coin: {fmt_number(stats['total_tcoin'])}\n"
        f"📝 Транзакций сегодня: {stats['tx_today']}\n"
        f"📋 Ожидающих заявок: {stats['pending_requests']}\n"
        f"🎟 Активных промокодов: {stats['active_promos']}"
    )

    keyboard = build_keyboard([
        [InlineKeyboardButton(text="⚙️ Настройки бота", callback_data="admin_settings"),
         InlineKeyboardButton(text="💱 Курсы и лимиты", callback_data="admin_rates")],
        [InlineKeyboardButton(text="👥 Управление юзерами", callback_data="admin_users"),
         InlineKeyboardButton(text="🎟 Промокоды", callback_data="admin_promos")],
        [InlineKeyboardButton(text="📋 Заявки", callback_data="admin_requests"),
         InlineKeyboardButton(text="📢 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="📊 Топ игроков", callback_data="admin_top"),
         InlineKeyboardButton(text="📝 Логи", callback_data="admin_logs")],
        [InlineKeyboardButton(text="🔧 Режим обслуживания", callback_data="admin_maintenance"),
         InlineKeyboardButton(text="🚫 Бан/Разбан", callback_data="admin_ban")],
        [btn_menu()],
    ])

    await render(callback.message, text, keyboard, is_callback=True)

# ==================== НАСТРОЙКИ БОТА ====================

@dp.callback_query(F.data == "admin_settings")
async def cb_admin_settings(callback: CallbackQuery) -> None:
    """Настройки бота"""
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    await callback.answer()

    settings = get_all_settings()
    text = (
        "⚙️ <b>Настройки бота</b>\n\n"
        f"🟢 Бот активен: <b>{'Да' if settings.get('bot_active') == '1' else 'Нет'}</b>\n"
        f"🔧 Обслуживание: <b>{'Вкл' if settings.get('maintenance_mode') == '1' else 'Выкл'}</b>\n"
        f"🎮 Игры: <b>{'Вкл' if settings.get('games_enabled') == '1' else 'Выкл'}</b>\n"
        f"💸 Переводы: <b>{'Вкл' if settings.get('transfer_enabled') == '1' else 'Выкл'}</b>\n"
        f"⭐ Пополнение: <b>{'Вкл' if settings.get('deposit_enabled') == '1' else 'Выкл'}</b>\n"
        f"💳 Вывод: <b>{'Вкл' if settings.get('withdraw_enabled') == '1' else 'Выкл'}</b>\n"
        f"✅ Верификация: <b>{'Да' if settings.get('verification_required') == '1' else 'Нет'}</b>"
    )

    keyboard = build_keyboard([
        [InlineKeyboardButton(
            text=f"{'🔴' if settings.get('bot_active') == '1' else '🟢'} Бот активен",
            callback_data="toggle_bot_active"
        )],
        [InlineKeyboardButton(
            text=f"{'🔧 Выкл' if settings.get('maintenance_mode') == '1' else '✅ Выкл'} обслуживание",
            callback_data="toggle_maintenance"
        )],
        [InlineKeyboardButton(
            text=f"🎮 Игры: {'Вкл' if settings.get('games_enabled') == '1' else 'Выкл'}",
            callback_data="toggle_games"
        )],
        [InlineKeyboardButton(
            text=f"💸 Переводы: {'Вкл' if settings.get('transfer_enabled') == '1' else 'Выкл'}",
            callback_data="toggle_transfer"
        )],
        [InlineKeyboardButton(
            text=f"⭐ Пополнение: {'Вкл' if settings.get('deposit_enabled') == '1' else 'Выкл'}",
            callback_data="toggle_deposit"
        )],
        [InlineKeyboardButton(
            text=f"💳 Вывод: {'Вкл' if settings.get('withdraw_enabled') == '1' else 'Выкл'}",
            callback_data="toggle_withdraw"
        )],
        [InlineKeyboardButton(
            text=f"✅ Верификация: {'Да' if settings.get('verification_required') == '1' else 'Нет'}",
            callback_data="toggle_verification"
        )],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin")],
    ])

    await render(callback.message, text, keyboard, is_callback=True)

# ==================== ПЕРЕКЛЮЧЕНИЕ НАСТРОЕК ====================

async def toggle_setting(callback: CallbackQuery, key: str) -> None:
    """Переключить настройку"""
    current = get_setting(key)
    new_val = "0" if current == "1" else "1"
    set_setting(key, new_val)
    log_admin_action(callback.from_user.id, f"toggle_{key}", details=f"{current} → {new_val}")
    # Возвращаемся в настройки
    callback.data = "admin_settings"
    await cb_admin_settings(callback)

@dp.callback_query(F.data == "toggle_bot_active")
async def cb_toggle_bot_active(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await toggle_setting(callback, "bot_active")

@dp.callback_query(F.data == "toggle_maintenance")
async def cb_toggle_maintenance(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await toggle_setting(callback, "maintenance_mode")

@dp.callback_query(F.data == "toggle_games")
async def cb_toggle_games(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await toggle_setting(callback, "games_enabled")

@dp.callback_query(F.data == "toggle_transfer")
async def cb_toggle_transfer(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await toggle_setting(callback, "transfer_enabled")

@dp.callback_query(F.data == "toggle_deposit")
async def cb_toggle_deposit(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await toggle_setting(callback, "deposit_enabled")

@dp.callback_query(F.data == "toggle_withdraw")
async def cb_toggle_withdraw(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await toggle_setting(callback, "withdraw_enabled")

@dp.callback_query(F.data == "toggle_verification")
async def cb_toggle_verification(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await toggle_setting(callback, "verification_required")

# ==================== КУРСЫ И ЛИМИТЫ ====================

@dp.callback_query(F.data == "admin_rates")
async def cb_admin_rates(callback: CallbackQuery) -> None:
    """Курсы и лимиты"""
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    await callback.answer()

    settings = get_all_settings()
    text = (
        "💱 <b>Курсы и лимиты</b>\n\n"
        f"💱 Курс обмена: <code>{settings.get('exchange_rate')}</code> ⭐️ = 1 🪙\n"
        f"💵 Мин. ставка: <code>{settings.get('min_bet')}</code> 🪙\n"
        f"💰 Макс. ставка: <code>{settings.get('max_bet')}</code> 🪙\n"
        f"🎁 Бонус/день (звёзды): <code>{settings.get('daily_bonus_stars')}</code>\n"
        f"🎁 Бонус/день (T Coin): <code>{settings.get('daily_bonus_tcoin')}</code>\n"
        f"👥 Бонус за реферала: <code>{settings.get('referral_bonus')}</code> ⭐️\n"
        f"📋 Лимит заданий/день: <code>{settings.get('max_tasks_per_day')}</code>"
    )

    keyboard = build_keyboard([
        [InlineKeyboardButton(text="💱 Изменить курс", callback_data="set_exchange_rate")],
        [InlineKeyboardButton(text="💵 Мин. ставка", callback_data="set_min_bet")],
        [InlineKeyboardButton(text="💰 Макс. ставка", callback_data="set_max_bet")],
        [InlineKeyboardButton(text="🎁 Бонус/день ⭐️", callback_data="set_daily_stars")],
        [InlineKeyboardButton(text="🎁 Бонус/день 🪙", callback_data="set_daily_tcoin")],
        [InlineKeyboardButton(text="👥 Бонус за реферала", callback_data="set_referral_bonus")],
        [InlineKeyboardButton(text="📋 Лимит заданий", callback_data="set_max_tasks")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin")],
    ])

    await render(callback.message, text, keyboard, is_callback=True)

# ==================== УСТАНОВКА ЗНАЧЕНИЙ ====================

SETTING_KEYS = {
    "set_exchange_rate": ("exchange_rate", "💱 Новый курс (⭐️ = 1 🪙):"),
    "set_min_bet": ("min_bet", "💵 Новая мин. ставка (🪙):"),
    "set_max_bet": ("max_bet", "💰 Новая макс. ставка (🪙):"),
    "set_daily_stars": ("daily_bonus_stars", "🎁 Бонус/день (⭐️):"),
    "set_daily_tcoin": ("daily_bonus_tcoin", "🎁 Бонус/день (🪙):"),
    "set_referral_bonus": ("referral_bonus", "👥 Бонус за реферала (⭐️):"),
    "set_max_tasks": ("max_tasks_per_day", "📋 Лимит заданий/день:"),
}

@dp.callback_query(F.data.startswith("set_"))
async def cb_set_value(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрос нового значения настройки"""
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    await callback.answer()

    key_data = SETTING_KEYS.get(callback.data)
    if not key_data:
        return

    key, prompt = key_data
    await state.update_data(setting_key=key)
    await state.set_state(AdminStates.waiting_setting_value)

    keyboard = build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_rates")]])
    await callback.message.edit_text(
        f"{prompt}\n\nТекущее значение: <code>{get_setting(key)}</code>",
        parse_mode="HTML",
        reply_markup=keyboard
    )

@dp.message(AdminStates.waiting_setting_value)
async def process_setting_value(message: Message, state: FSMContext) -> None:
    """Обработка нового значения настройки"""
    data = await state.get_data()
    key = data.get("setting_key")
    await state.clear()

    if not key or not is_admin(message.from_user.id):
        return

    try:
        value = int(message.text.strip())
        if value < 0:
            raise ValueError
    except ValueError:
        return await message.answer("❌ Введите положительное число!")

    set_setting(key, value)
    log_admin_action(message.from_user.id, f"set_{key}", details=str(value))

    keyboard = build_keyboard([[InlineKeyboardButton(text="🔙 К настройкам", callback_data="admin_rates")]])
    await message.answer(
        f"✅ Настройка <b>{key}</b> обновлена: <code>{value}</code>",
        parse_mode="HTML",
        reply_markup=keyboard
    )

# ==================== УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ ====================

@dp.callback_query(F.data == "admin_users")
async def cb_admin_users(callback: CallbackQuery, state: FSMContext) -> None:
    """Управление пользователями"""
    if not is_admin(callback.from_user.id):
        return await callback.answer("❌ Нет прав!", show_alert=True)
    await callback.answer()

    text = (
        "👥 <b>Управление пользователями</b>\n\n"
        "Отправьте ID или @username пользователя,\n"
        "или ответьте на его сообщение.\n\n"
        "Затем выберите действие."
    )

    keyboard = build_keyboard([
        [InlineKeyboardButton(text="💰 Выдать звёзды", callback_data="user_addstars")],
        [InlineKeyboardButton(text="🪙 Выдать T Coin", callback_data="user_addtcoin")],
        [InlineKeyboardButton(text="🔄 Сброс баланса", callback_data="user_reset")],
        [InlineKeyboardButton(text="🚫 Забанить", callback_data="user_ban")],
        [InlineKeyboardButton(text="✅ Разбанить", callback_data="user_unban")],
        [InlineKeyboardButton(text="👑 Сделать админом", callback_data="user_makeadmin")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="user_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin")],
    ])

    await render(callback.message, text, keyboard, is_callback=True)
    await state.set_state(AdminStates.waiting_user_id)

@dp.message(AdminStates.waiting_user_id)
async def process_user_id(message: Message, state: FSMContext) -> None:
    """Обработка ID/username пользователя"""
    target_id = await resolve_user_id(message.text.strip(), message.reply_to_message)
    if not target_id:
        return await message.answer("❌ Пользователь не найден!")

    await state.update_data(target_user_id=target_id)
    target = get_user(target_id)

    text = (
        f"👤 <b>Выбран пользователь:</b>\n\n"
        f"🆔 ID: <code>{target[0]}</code>\n"
        f"📝 @{target[1] or 'N/A'}\n"
        f"👤 {target[2]}\n"
        f"⭐️ {target[3]} | 🪙 {target[4]}\n\n"
        f"Теперь выберите действие через меню ниже."
    )

    keyboard = build_keyboard([
        [InlineKeyboardButton(text="💰 Выдать звёзды", callback_data="user_addstars")],
        [InlineKeyboardButton(text="🪙 Выдать T Coin", callback_data="user_addtcoin")],
        [InlineKeyboardButton(text="🔄 Сброс баланса", callback_data="user_reset")],
        [InlineKeyboardButton(text="🚫 Забанить", callback_data="user_ban")],
        [InlineKeyboardButton(text="✅ Разбанить", callback_data="user_unban")],
        [InlineKeyboardButton(text="👑 Сделать админом", callback_data="user_makeadmin")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="user_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin")],
    ])

    await message.answer(text, parse_mode="HTML", reply_markup=keyboard)
    await state.clear()
    await state.update_data(target_user_id=target_id)

# ==================== ДЕЙСТВИЯ НАД ПОЛЬЗОВАТЕЛЯМИ ====================

async def get_target_user(callback: CallbackQuery) -> Optional[int]:
    """Получить ID целевого пользователя из состояния"""
    state = dp.fsm.resolve_context(callback.from_user.id, callback.message.message_id)
    data = await state.get_data()
    return data.get("target_user_id")

@dp.callback_query(F.data == "user_addstars")
async def cb_user_addstars(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()
    data = await state.get_data()
    target_id = data.get("target_user_id")
    if not target_id:
        return await callback.answer("❌ Сначала выберите пользователя", show_alert=True)
    await state.update_data(action="addstars", target_user_id=target_id)
    await state.set_state(AdminStates.waiting_amount)
    await callback.message.edit_text(
        f"💰 Введите количество звёзд для пользователя <code>{target_id}</code>:",
        parse_mode="HTML",
        reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_users")]])
    )

@dp.callback_query(F.data == "user_addtcoin")
async def cb_user_addtcoin(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()
    data = await state.get_data()
    target_id = data.get("target_user_id")
    if not target_id:
        return await callback.answer("❌ Сначала выберите пользователя", show_alert=True)
    await state.update_data(action="addtcoin", target_user_id=target_id)
    await state.set_state(AdminStates.waiting_amount)
    await callback.message.edit_text(
        f"🪙 Введите количество T Coin для пользователя <code>{target_id}</code>:",
        parse_mode="HTML",
        reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_users")]])
    )

@dp.message(AdminStates.waiting_amount)
async def process_amount(message: Message, state: FSMContext) -> None:
    """Обработка суммы для действий над пользователем"""
    data = await state.get_data()
    action = data.get("action")
    target_id = data.get("target_user_id")
    await state.clear()

    if not action or not target_id or not is_admin(message.from_user.id):
        return

    try:
        amount = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Введите число!")

    if action == "addstars":
        update_balance(target_id, stars=amount, desc="Админ начисление")
        log_admin_action(message.from_user.id, "addstars", target_id, str(amount))
        await message.answer(f"✅ +{amount} ⭐️ → {target_id}")
    elif action == "addtcoin":
        update_balance(target_id, tcoin=amount, desc="Админ начисление")
        log_admin_action(message.from_user.id, "addtcoin", target_id, str(amount))
        await message.answer(f"✅ +{amount} 🪙 → {target_id}")

@dp.callback_query(F.data == "user_reset")
async def cb_user_reset(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()
    data = await state.get_data()
    target_id = data.get("target_user_id")
    if not target_id:
        return await callback.answer("❌ Сначала выберите пользователя", show_alert=True)

    conn = get_db()
    conn.execute("UPDATE users SET stars_balance=0, tcoin_balance=0 WHERE user_id=?", (target_id,))
    conn.commit()
    conn.close()
    log_admin_action(callback.from_user.id, "reset", target_id)
    await callback.message.edit_text(
        f"🔄 Баланс пользователя <code>{target_id}</code> сброшен.",
        parse_mode="HTML",
        reply_markup=build_keyboard([[InlineKeyboardButton(text="🔙 Назад", callback_data="admin")]])
    )

@dp.callback_query(F.data == "user_ban")
async def cb_user_ban(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()
    data = await state.get_data()
    target_id = data.get("target_user_id")
    if not target_id:
        return await callback.answer("❌ Сначала выберите пользователя", show_alert=True)

    update_user_field(target_id, "is_banned", 1)
    log_admin_action(callback.from_user.id, "ban", target_id)
    await callback.message.edit_text(
        f"🚫 Пользователь <code>{target_id}</code> заблокирован.",
        parse_mode="HTML",
        reply_markup=build_keyboard([[InlineKeyboardButton(text="🔙 Назад", callback_data="admin")]])
    )

@dp.callback_query(F.data == "user_unban")
async def cb_user_unban(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()
    data = await state.get_data()
    target_id = data.get("target_user_id")
    if not target_id:
        return await callback.answer("❌ Сначала выберите пользователя", show_alert=True)

    update_user_field(target_id, "is_banned", 0)
    log_admin_action(callback.from_user.id, "unban", target_id)
    await callback.message.edit_text(
        f"✅ Пользователь <code>{target_id}</code> разблокирован.",
        parse_mode="HTML",
        reply_markup=build_keyboard([[InlineKeyboardButton(text="🔙 Назад", callback_data="admin")]])
    )

@dp.callback_query(F.data == "user_makeadmin")
async def cb_user_makeadmin(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()
    data = await state.get_data()
    target_id = data.get("target_user_id")
    if not target_id:
        return await callback.answer("❌ Сначала выберите пользователя", show_alert=True)

    user = get_user(target_id)
    new_val = 0 if user[7] else 1
    update_user_field(target_id, "is_admin", new_val)
    log_admin_action(callback.from_user.id, "makeadmin", target_id, str(new_val))
    await callback.message.edit_text(
        f"👑 Пользователь <code>{target_id}</code> — {'админ' if new_val else 'обычный юзер'}.",
        parse_mode="HTML",
        reply_markup=build_keyboard([[InlineKeyboardButton(text="🔙 Назад", callback_data="admin")]])
    )

@dp.callback_query(F.data == "user_stats")
async def cb_user_stats(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()
    data = await state.get_data()
    target_id = data.get("target_user_id")
    if not target_id:
        return await callback.answer("❌ Сначала выберите пользователя", show_alert=True)

    user = get_user(target_id)
    if not user:
        return await callback.message.edit_text("❌ Пользователь не найден.")

    level_name, _ = get_level_info(user[16])
    text = (
        f"📊 <b>Статистика пользователя</b>\n\n"
        f"🆔 ID: <code>{user[0]}</code>\n"
        f"📝 @{user[1] or 'N/A'}\n"
        f"👤 {user[2]}\n"
        f"🎖 Уровень: {level_name} (Ур. {user[16]})\n\n"
        f"💰 Баланс:\n"
        f"⭐️ {user[3]} | 🪙 {user[4]}\n\n"
        f"📈 Активность:\n"
        f"✅ Заданий: {user[12]}\n"
        f"🎮 Игр: {user[17]} (побед: {user[18]})\n"
        f"👥 Рефералов: {user[13]}\n\n"
        f"🚫 Бан: {'Да' if user[8] else 'Нет'}\n"
        f"👑 Админ: {'Да' if user[7] else 'Нет'}\n"
        f"✅ Вериф: {'Да' if user[15] else 'Нет'}\n"
        f"📅 Регистрация: {user[14][:10]}"
    )

    await callback.message.edit_text(
        text, parse_mode="HTML",
        reply_markup=build_keyboard([[InlineKeyboardButton(text="🔙 Назад", callback_data="admin")]])
    )

# ==================== ПРОМОКОДЫ ====================

@dp.callback_query(F.data == "admin_promos")
async def cb_admin_promos(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()

    promos = list_promos()
    if not promos:
        text = "🎟 <b>Промокоды</b>\n\nПока нет промокодов."
    else:
        text = "🎟 <b>Промокоды:</b>\n\n"
        for p in promos:
            status = "✅" if p[5] else "❌"
            text += f"{status} <code>{p[0]}</code> — ⭐️{p[1]} 🪙{p[2]} ({p[4]}/{p[3]})\n"

    keyboard = build_keyboard([
        [InlineKeyboardButton(text="➕ Создать промокод", callback_data="promo_create")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin")],
    ])

    await render(callback.message, text, keyboard, is_callback=True)

@dp.callback_query(F.data == "promo_create")
async def cb_promo_create(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()
    await state.set_state(AdminStates.waiting_promo_code)
    await callback.message.edit_text(
        "🎟 Введите код промокода (латиница/цифры):",
        reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="admin_promos")]])
    )

@dp.message(AdminStates.waiting_promo_code)
async def process_promo_code_create(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id): return
    code = message.text.strip().upper()
    if not re.match(r'^[A-Z0-9_]{3,30}$', code):
        return await message.answer("❌ Код: 3-30 символов (A-Z, 0-9, _)")
    await state.update_data(promo_code=code)
    await state.set_state(AdminStates.waiting_promo_stars)
    await message.answer("⭐️ Сколько звёзд даёт промокод?")

@dp.message(AdminStates.waiting_promo_stars)
async def process_promo_stars(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id): return
    try:
        stars = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Число!")
    await state.update_data(promo_stars=stars)
    await state.set_state(AdminStates.waiting_promo_tcoin)
    await message.answer("🪙 Сколько T Coin даёт промокод?")

@dp.message(AdminStates.waiting_promo_tcoin)
async def process_promo_tcoin(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id): return
    try:
        tcoin = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Число!")
    await state.update_data(promo_tcoin=tcoin)
    await state.set_state(AdminStates.waiting_promo_limit)
    await message.answer("🔢 Максимум использований?")

@dp.message(AdminStates.waiting_promo_limit)
async def process_promo_limit(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id): return
    try:
        limit = int(message.text.strip())
    except ValueError:
        return await message.answer("❌ Число!")

    data = await state.get_data()
    code = data.get("promo_code")
    stars = data.get("promo_stars", 0)
    tcoin = data.get("promo_tcoin", 0)
    await state.clear()

    if create_promo(code, stars, tcoin, limit, message.from_user.id):
        log_admin_action(message.from_user.id, "create_promo", details=f"{code}: ⭐️{stars} 🪙{tcoin} x{limit}")
        await message.answer(
            f"✅ Промокод <code>{code}</code> создан!\n⭐️{stars} 🪙{tcoin} лимит {limit}",
            parse_mode="HTML",
            reply_markup=build_keyboard([[InlineKeyboardButton(text="🔙 К промокодам", callback_data="admin_promos")]])
        )
    else:
        await message.answer("❌ Промокод уже существует!")

# ==================== ЗАЯВКИ ====================

@dp.callback_query(F.data == "admin_requests")
async def cb_admin_requests(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()

    reqs = get_pending_requests()
    if not reqs:
        text = "📋 <b>Заявки</b>\n\nНет ожидающих заявок."
    else:
        text = "📋 <b>Ожидающие заявки:</b>\n\n"
        for r in reqs:
            icon = "📥" if r[2] == "deposit" else "📤"
            text += f"{icon} #{r[0]} — {r[3]} ⭐️ 👤{r[1]}\n"

    keyboard = build_keyboard([
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin")],
    ])

    await render(callback.message, text, keyboard, is_callback=True)

# ==================== РАССЫЛКА ====================

@dp.callback_query(F.data == "admin_broadcast")
async def cb_admin_broadcast(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()
    await state.set_state(AdminStates.waiting_broadcast)
    await callback.message.edit_text(
        "📢 Отправьте сообщение для рассылки всем пользователям:",
        reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="admin")]])
    )

@dp.message(AdminStates.waiting_broadcast)
async def process_broadcast(message: Message, state: FSMContext) -> None:
    if not is_admin(message.from_user.id): return
    await state.clear()

    conn = get_db()
    users = [r[0] for r in conn.execute("SELECT user_id FROM users WHERE is_banned = 0").fetchall()]
    conn.close()

    status_msg = await message.answer(f"📤 Рассылка для {len(users)} пользователей...")
    ok = fail = 0

    for uid in users:
        try:
            await bot.send_message(uid, message.text, parse_mode="HTML")
            ok += 1
            await asyncio.sleep(0.05)
        except Exception:
            fail += 1

    log_admin_action(message.from_user.id, "broadcast", details=f"ok={ok} fail={fail}")
    await status_msg.edit_text(
        f"✅ Рассылка завершена!\n📤 Успешно: {ok}\n❌ Ошибок: {fail}",
        reply_markup=build_keyboard([[InlineKeyboardButton(text="🔙 В админку", callback_data="admin")]])
    )

# ==================== ТОП ИГРОКОВ ====================

@dp.callback_query(F.data == "admin_top")
async def cb_admin_top(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()

    stats = get_bot_stats()
    text = "📊 <b>Топ игроков</b>\n\n"

    text += "<b>🎮 По играм:</b>\n"
    for i, row in enumerate(stats['top_games'], 1):
        text += f"{i}. <code>{row[0]}</code> — {row[1]} игр\n"

    text += "\n<b>✅ По заданиям:</b>\n"
    for i, row in enumerate(stats['top_tasks'], 1):
        text += f"{i}. <code>{row[0]}</code> — {row[1]} заданий\n"

    keyboard = build_keyboard([[InlineKeyboardButton(text="🔙 Назад", callback_data="admin")]])
    await render(callback.message, text, keyboard, is_callback=True)

# ==================== ЛОГИ ====================

@dp.callback_query(F.data == "admin_logs")
async def cb_admin_logs(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()

    conn = get_db()
    logs = conn.execute("""
        SELECT admin_id, action, target_id, details, created_at
        FROM admin_logs ORDER BY id DESC LIMIT 20
    """).fetchall()
    conn.close()

    if not logs:
        text = "📝 <b>Логи</b>\n\nПока нет записей."
    else:
        text = "📝 <b>Последние действия:</b>\n\n"
        for log in logs:
            text += f"👤 <code>{log[0]}</code> → {log[1]}"
            if log[2]:
                text += f" (цель: {log[2]})"
            if log[3]:
                text += f": {log[3]}"
            text += f"\n   <code>{log[4]}</code>\n\n"

    keyboard = build_keyboard([[InlineKeyboardButton(text="🔙 Назад", callback_data="admin")]])
    await render(callback.message, text, keyboard, is_callback=True)

# ==================== ОБСЛУЖИВАНИЕ И БАН ====================

@dp.callback_query(F.data == "admin_maintenance")
async def cb_admin_maintenance(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()
    current = get_setting("maintenance_mode")
    new_val = "0" if current == "1" else "1"
    set_setting("maintenance_mode", new_val)
    log_admin_action(callback.from_user.id, "maintenance", details=new_val)
    status = "🔧 ВКЛ" if new_val == "1" else "✅ ВЫКЛ"
    await callback.answer(f"Режим обслуживания: {status}", show_alert=True)
    callback.data = "admin_settings"
    await cb_admin_settings(callback)

@dp.callback_query(F.data == "admin_ban")
async def cb_admin_ban(callback: CallbackQuery, state: FSMContext) -> None:
    if not is_admin(callback.from_user.id): return
    await callback.answer()
    await state.set_state(AdminStates.waiting_user_id)
    await state.update_data(ban_action=True)
    await callback.message.edit_text(
        "🚫 Отправьте ID/username пользователя для бана/разбана\nили ответьте на его сообщение:",
        reply_markup=build_keyboard([[InlineKeyboardButton(text="❌ Отмена", callback_data="admin")]])
    )

# =============================================================================
# ========================= ТЕКСТОВЫЕ АДМИН-КОМАНДЫ =========================
# =============================================================================

@dp.message(Command("addstars", "addtcoin", "reset", "ban", "unban", "makeadmin",
                    "setrate", "setminbet", "setmaxbet", "userstats", "stats",
                    "createpromo", "approve", "reject", "requests"))
async def admin_text_commands(message: Message) -> None:
    """Текстовые админ-команды (поддержка ID, username, reply)"""
    if not is_admin(message.from_user.id):
        return

    args = message.text.split()
    cmd = args[0].replace("/", "").lower()

    # Команды без аргументов
    if cmd == "stats":
        stats = get_bot_stats()
        return await message.answer(
            f"📊 <b>Статистика:</b>\n\n"
            f"👥 Пользователей: {stats['total_users']}\n"
            f"✅ Активных: {stats['active_users']}\n"
            f"🚫 Забанено: {stats['banned_users']}\n"
            f"🆕 Сегодня: {stats['new_today']}\n"
            f"⭐️ Всего звёзд: {fmt_number(stats['total_stars'])}\n"
            f"🪙 Всего T Coin: {fmt_number(stats['total_tcoin'])}\n"
            f"📝 Транзакций сегодня: {stats['tx_today']}\n"
            f"📋 Ожидающих заявок: {stats['pending_requests']}",
            parse_mode="HTML"
        )

    if cmd == "requests":
        reqs = get_pending_requests()
        if not reqs:
            return await message.answer("📋 Нет ожидающих заявок.")
        text = "📋 <b>Ожидающие заявки:</b>\n\n"
        for r in reqs:
            icon = "📥" if r[2] == "deposit" else "📤"
            text += f"{icon} #{r[0]} — {r[3]} ⭐️ 👤{r[1]}\n"
        return await message.answer(text, parse_mode="HTML")

    # Команды с аргументами
    if cmd in ["addstars", "addtcoin", "reset", "ban", "unban", "makeadmin", "userstats"]:
        if len(args) < 2 and not message.reply_to_message:
            return await message.answer(f"⚠️ Использование: /{cmd} ID/username [значение]\nИли ответьте на сообщение.")

        target_id = await resolve_user_id(args[1] if len(args) > 1 else "", message.reply_to_message)
        if not target_id:
            return await message.answer("❌ Пользователь не найден!")

        if cmd == "addstars":
            if len(args) < 3:
                return await message.answer("⚠️ Укажите сумму: /addstars ID 100")
            try:
                val = int(args[2])
            except ValueError:
                return await message.answer("❌ Сумма — число!")
            update_balance(target_id, stars=val, desc="Админ начисление")
            log_admin_action(message.from_user.id, "addstars", target_id, str(val))
            return await message.answer(f"✅ +{val} ⭐️ → {target_id}")

        elif cmd == "addtcoin":
            if len(args) < 3:
                return await message.answer("⚠️ Укажите сумму: /addtcoin ID 100")
            try:
                val = int(args[2])
            except ValueError:
                return await message.answer("❌ Сумма — число!")
            update_balance(target_id, tcoin=val, desc="Админ начисление")
            log_admin_action(message.from_user.id, "addtcoin", target_id, str(val))
            return await message.answer(f"✅ +{val} 🪙 → {target_id}")

        elif cmd == "reset":
            conn = get_db()
            conn.execute("UPDATE users SET stars_balance=0, tcoin_balance=0 WHERE user_id=?", (target_id,))
            conn.commit()
            conn.close()
            log_admin_action(message.from_user.id, "reset", target_id)
            return await message.answer(f"🔄 Баланс {target_id} сброшен.")

        elif cmd == "ban":
            update_user_field(target_id, "is_banned", 1)
            log_admin_action(message.from_user.id, "ban", target_id)
            return await message.answer(f"🚫 {target_id} заблокирован.")

        elif cmd == "unban":
            update_user_field(target_id, "is_banned", 0)
            log_admin_action(message.from_user.id, "unban", target_id)
            return await message.answer(f"✅ {target_id} разблокирован.")

        elif cmd == "makeadmin":
            if len(args) < 3:
                return await message.answer("⚠️ Укажите 1 или 0: /makeadmin ID 1")
            try:
                val = int(args[2])
            except ValueError:
                return await message.answer("❌ 1 или 0!")
            if val not in [0, 1]:
                return await message.answer("❌ 1 или 0!")
            update_user_field(target_id, "is_admin", val)
            log_admin_action(message.from_user.id, "makeadmin", target_id, str(val))
            return await message.answer(f"👑 {target_id} → {'админ' if val else 'обычный'}")

        elif cmd == "userstats":
            user = get_user(target_id)
            if not user:
                return await message.answer("❌ Пользователь не найден.")
            level_name, _ = get_level_info(user[16])
            return await message.answer(
                f"📊 <b>Статистика {user[0]}</b>\n\n"
                f"📝 @{user[1] or 'N/A'} | {user[2]}\n"
                f"🎖 {level_name} (Ур. {user[16]})\n"
                f"⭐️ {user[3]} | 🪙 {user[4]}\n"
                f"✅ Заданий: {user[12]}\n"
                f"🎮 Игр: {user[17]} (побед: {user[18]})\n"
                f"👥 Рефералов: {user[13]}\n"
                f"🚫 Бан: {'Да' if user[8] else 'Нет'}\n"
                f"👑 Админ: {'Да' if user[7] else 'Нет'}\n"
                f"✅ Вериф: {'Да' if user[15] else 'Нет'}\n"
                f"📅 {user[14][:10]}",
                parse_mode="HTML"
            )

    # Команды изменения настроек
    elif cmd in ["setrate", "setminbet", "setmaxbet"]:
        if len(args) < 2:
            return await message.answer(f"⚠️ /{cmd} ЧИСЛО")
        try:
            val = int(args[1])
            if val < 0:
                raise ValueError
        except ValueError:
            return await message.answer("❌ Положительное число!")

        key_map = {
            "setrate": "exchange_rate",
            "setminbet": "min_bet",
            "setmaxbet": "max_bet"
        }
        set_setting(key_map[cmd], val)
        log_admin_action(message.from_user.id, cmd, details=str(val))
        return await message.answer(f"✅ {key_map[cmd]} = {val}")

    # Создание промокода
    elif cmd == "createpromo":
        if len(args) < 5:
            return await message.answer("⚠️ /createpromo КОД ЗВЁЗДЫ TCOIN ЛИМИТ")
        try:
            code = args[1].upper()
            stars = int(args[2])
            tcoin = int(args[3])
            limit = int(args[4])
        except ValueError:
            return await message.answer("❌ Формат!")

        if create_promo(code, stars, tcoin, limit, message.from_user.id):
            log_admin_action(message.from_user.id, "createpromo", details=f"{code}: ⭐️{stars} 🪙{tcoin} x{limit}")
            return await message.answer(
                f"✅ Промокод <code>{code}</code> создан!\n⭐️{stars} 🪙{tcoin} лимит {limit}",
                parse_mode="HTML"
            )
        return await message.answer("❌ Промокод уже существует!")

    # Одобрение/отклонение заявок
    elif cmd in ["approve", "reject"]:
        if len(args) < 2:
            return await message.answer(f"⚠️ /{cmd} ID_ЗАЯВКИ")
        try:
            req_id = int(args[1])
        except ValueError:
            return await message.answer("❌ Число!")

        req = get_request(req_id)
        if not req or req[4] != "pending":
            return await message.answer("❌ Заявка не найдена или уже обработана!")

        user_id = req[1]
        amount = req[3]

        if cmd == "approve":
            update_request_status(req_id, "approved")
            if req[2] == "deposit":
                update_balance(user_id, stars=amount, desc="Пополнение одобрено")
            await message.answer(f"✅ Заявка #{req_id} одобрена.")
            try:
                await bot.send_message(user_id, f"✅ Ваша заявка #{req_id} одобрена!")
            except Exception:
                pass
        else:
            update_request_status(req_id, "rejected")
            if req[2] == "withdraw":
                update_balance(user_id, stars=amount, desc="Возврат (заявка отклонена)")
            await message.answer(f"❌ Заявка #{req_id} отклонена.")
            try:
                await bot.send_message(user_id, f"❌ Ваша заявка #{req_id} отклонена.")
            except Exception:
                pass

# =============================================================================
# ========================= КНОПКИ "НАЗАД" (ИСПРАВЛЕНИЕ) ====================
# =============================================================================

@dp.callback_query(F.data.startswith("back_"))
async def cb_back(callback: CallbackQuery) -> None:
    """Универсальная кнопка назад"""
    await callback.answer()
    target = callback.data.replace("back_", "")

    user = get_user(callback.from_user.id)
    if not user:
        return

    # Если пользователь не верифицирован — показываем верификацию
    if not user[15] and get_setting("verification_required") == "1":
        return await render_verify(callback, is_callback=True)

    if target == "menu":
        await render_main_menu(callback, is_callback=True)
    elif target == "profile":
        callback.data = "profile"
        await cb_profile(callback)
    else:
        await render_main_menu(callback, is_callback=True)

# =============================================================================
# ========================= ЗАПУСК БОТА =====================================
# =============================================================================

async def main() -> None:
    """Запуск бота"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    logging.info("✅ Бот запускается...")
    logging.info(f"👑 Админ ID: {ADMIN_ID}")
    logging.info(f"💱 Курс: {get_setting('exchange_rate')} ⭐️ = 1 🪙")
    logging.info(f"🎮 Игры: {'Вкл' if get_setting('games_enabled') == '1' else 'Выкл'}")

    # Удаляем вебхук (на всякий случай)
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception as e:
        logging.warning(f"Webhook delete error: {e}")

    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("🛑 Бот остановлен")
    except Exception as e:
        logging.error(f"Critical error: {e}")
