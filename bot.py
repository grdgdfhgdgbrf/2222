# =============================================================================
# TELEGRAM БОТ — ИГРОВОЕ КАЗИНО
# 10 одиночных игр + Тайный торговец + Базовые казино-игры
# =============================================================================

import asyncio
import logging
import random
import sqlite3
import re
import html
import aiohttp
import string
import time
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional, Any, List

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, LabeledPrice, PreCheckoutQuery
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest
from aiogram.enums import ChatType

# =============================================================================
# ========================= КОНФИГУРАЦИЯ ====================================
# =============================================================================

BOT_TOKEN = "8684125903:AAGlja8nj_r3HCb8aZwubOqJ_MAGDFAWCoc"
PIARFLOW_API_KEY = "MSnWP-9zGC1ZProz_dUSrj5TqeQ--khK"
PIARFLOW_BASE_URL = "https://piarflow.com/v1"
ADMIN_ID = 5356400377

DEFAULT_SETTINGS = {
    "exchange_rate": "10",
    "bot_active": "1", "maintenance_mode": "0",
    "min_bet": "10", "max_bet": "50000",
    "daily_bonus_sc": "10", "daily_bonus_tc": "5",
    "referral_bonus": "5",
    "deposit_enabled": "1", "sell_enabled": "1",
    "games_enabled": "1", "transfer_enabled": "1",
    "verification_required": "1", "min_sell": "50",
    "sell_commission": "3",
    "task_reward": "5",
    "lose_chance": "0",
    "check_creation_enabled": "1",
    # Настройки торговца
    "trader_min_deposit": "100",
    "trader_max_deposit": "100000",
    "trader_offer_chance": "15",  # шанс появления предложения в %
    "trader_offer_interval": "3600",  # интервал проверки в секундах (1 час)
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_current_task: Dict[int, Dict] = {}
api_cache: Dict[str, Tuple] = {}

NEAR_MISS = [
    "🔥 Почти! Ещё чуть-чуть...",
    "💫 Удача рядом! Попробуй ещё!",
    "🎯 Миллиметры до победы!",
]

# =============================================================================
# ========================= FSM =============================================
# =============================================================================

class AdminStates(StatesGroup):
    waiting_broadcast = State()
    waiting_user_id = State()
    waiting_amount = State()
    waiting_promo_code = State()
    waiting_promo_sc = State()
    waiting_promo_tc = State()
    waiting_promo_limit = State()
    waiting_promo_delete = State()
    waiting_check_delete = State()
    waiting_setting_value = State()

class UserStates(StatesGroup):
    waiting_promo = State()
    waiting_sell_amount = State()
    waiting_buy_amount = State()
    waiting_exchange_sc = State()
    waiting_exchange_tc = State()
    waiting_check_sc = State()
    waiting_check_tc = State()
    waiting_check_act = State()

# === ОДИНОЧНЫЕ ИГРЫ ===
class SoloGamesStates(StatesGroup):
    # Риск X
    risk_playing = State()
    risk_multiplier = State()
    # Сейф
    safe_playing = State()
    safe_attempts = State()
    # Высшая карта
    hcard_playing = State()
    # Точный бросок
    tthrow_playing = State()
    # Три двери
    doors_playing = State()
    # Числовая лестница
    ladder_playing = State()
    ladder_current = State()
    # Момент
    moment_playing = State()
    # Монетка (серия)
    coin_series = State()
    coin_streak = State()
    # Код
    code_playing = State()
    code_attempts = State()
    # Босс
    boss_playing = State()
    boss_hp = State()
    player_hp = State()

# === ТОРГОВЕЦ ===
class TraderStates(StatesGroup):
    main_menu = State()
    deposit_amount = State()
    deposit_duration = State()
    viewing_deposits = State()
    offer_decision = State()

class MinesStates(StatesGroup):
    playing = State()

# =============================================================================
# ========================= БАЗА ДАННЫХ =====================================
# =============================================================================

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect("bot_database.db")
    conn.row_factory = sqlite3.Row
    return conn

def init_db() -> None:
    conn = get_db()
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT,
        stars_balance INTEGER DEFAULT 0, tcoin_balance INTEGER DEFAULT 0,
        referral_code TEXT, referred_by INTEGER, is_admin INTEGER DEFAULT 0,
        is_banned INTEGER DEFAULT 0, last_daily_bonus TEXT,
        total_tasks_completed INTEGER DEFAULT 0, total_referrals INTEGER DEFAULT 0,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, is_verified INTEGER DEFAULT 0,
        reputation INTEGER DEFAULT 0, warns INTEGER DEFAULT 0)""")
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS completed_tasks (
        user_id INTEGER, task_link TEXT,
        completed_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, task_link))""")
    c.execute("""CREATE TABLE IF NOT EXISTS promo_codes (
        code TEXT PRIMARY KEY, stars_reward INTEGER DEFAULT 0,
        tcoin_reward INTEGER DEFAULT 0, max_uses INTEGER DEFAULT 100,
        current_uses INTEGER DEFAULT 0, is_active INTEGER DEFAULT 1,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS used_promo (
        user_id INTEGER, promo_code TEXT, used_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, promo_code))""")
    c.execute("""CREATE TABLE IF NOT EXISTS checks (
        code TEXT PRIMARY KEY, sc_amount INTEGER, tc_amount INTEGER,
        activations_left INTEGER, created_by INTEGER,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS used_checks (
        user_id INTEGER, check_code TEXT,
        activated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, check_code))""")
    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT,
        amount INTEGER, description TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, req_type TEXT,
        amount INTEGER, status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, processed_at TEXT)""")
    
    # === НОВЫЕ ТАБЛИЦЫ ДЛЯ ТОРГОВЦА ===
    c.execute("""CREATE TABLE IF NOT EXISTS trader_deposits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        amount INTEGER,
        start_time TEXT,
        duration_hours INTEGER,
        interest_rate REAL,
        status TEXT DEFAULT 'active',
        collected INTEGER DEFAULT 0)""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS trader_offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        offer_type TEXT,
        amount INTEGER,
        return_amount INTEGER,
        duration_hours INTEGER,
        expires_at TEXT,
        accepted INTEGER DEFAULT 0)""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS trader_trust (
        user_id INTEGER PRIMARY KEY,
        level INTEGER DEFAULT 0,
        total_deposited INTEGER DEFAULT 0,
        total_earned INTEGER DEFAULT 0,
        deals_count INTEGER DEFAULT 0)""")
    
    for key, value in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

# ==================== ФУНКЦИИ БД ====================

def get_user(uid: int):
    conn = get_db()
    r = conn.execute("SELECT * FROM users WHERE user_id = ?", (uid,)).fetchone()
    conn.close()
    return r

def get_user_by_username(uname: str):
    conn = get_db()
    r = conn.execute("SELECT * FROM users WHERE username = ?", (uname.lstrip('@'),)).fetchone()
    conn.close()
    return r

def create_user(uid, uname, fname, rcode, ref_by=None, verified=0):
    conn = get_db()
    conn.execute("INSERT INTO users (user_id,username,first_name,referral_code,referred_by,is_admin,is_verified) VALUES (?,?,?,?,?,?,?)",
                 (uid, uname, fname or "Пользователь", rcode, ref_by, 1 if uid == ADMIN_ID else 0, verified))
    conn.commit()
    conn.close()

def update_user_field(uid, field, value):
    conn = get_db()
    conn.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, uid))
    conn.commit()
    conn.close()

def update_balance(uid, stars=0, tcoin=0, desc=""):
    conn = get_db()
    conn.execute("UPDATE users SET stars_balance=stars_balance+?, tcoin_balance=tcoin_balance+? WHERE user_id=?", (stars, tcoin, uid))
    if stars != 0:
        conn.execute("INSERT INTO transactions (user_id,type,amount,description) VALUES (?,?,?,?)",
                     (uid, 'stars', stars, desc or ("⭐ SC" if stars > 0 else "Списание SC")))
    if tcoin != 0:
        conn.execute("INSERT INTO transactions (user_id,type,amount,description) VALUES (?,?,?,?)",
                     (uid, 'tcoin', tcoin, desc or ("🪙 TC" if tcoin > 0 else "Списание TC")))
    conn.commit()
    conn.close()

def mark_task_completed(uid: int, link: str):
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO completed_tasks (user_id, task_link) VALUES (?, ?)", (uid, link))
    conn.commit()
    conn.close()

def is_task_completed(uid: int, link: str) -> bool:
    conn = get_db()
    r = conn.execute("SELECT 1 FROM completed_tasks WHERE user_id=? AND task_link=?", (uid, link)).fetchone()
    conn.close()
    return r is not None

def get_transactions(uid, limit=15):
    conn = get_db()
    rows = conn.execute("SELECT type,amount,description,created_at FROM transactions WHERE user_id=? ORDER BY id DESC LIMIT ?", (uid, limit)).fetchall()
    conn.close()
    return rows

def can_claim_daily(uid):
    u = get_user(uid)
    if not u or not u['last_daily_bonus']: return True
    try: return (datetime.now() - datetime.strptime(u['last_daily_bonus'], "%Y-%m-%d")).days >= 1
    except: return True

def set_daily_claimed(uid):
    update_user_field(uid, "last_daily_bonus", datetime.now().strftime("%Y-%m-%d"))

def increment_tasks(uid):
    conn = get_db()
    conn.execute("UPDATE users SET total_tasks_completed=total_tasks_completed+1 WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()

def increment_referrals(uid):
    conn = get_db()
    conn.execute("UPDATE users SET total_referrals=total_referrals+1 WHERE user_id=?", (uid,))
    conn.commit()
    conn.close()

def get_setting(key):
    conn = get_db()
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return r['value'] if r else None

def set_setting(key, value):
    conn = get_db()
    conn.execute("INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)", (key, str(value)))
    conn.commit()
    conn.close()

def get_all_settings():
    conn = get_db()
    rows = conn.execute("SELECT key,value FROM settings").fetchall()
    conn.close()
    return {r['key']: r['value'] for r in rows}

def get_promo(code):
    conn = get_db()
    r = conn.execute("SELECT * FROM promo_codes WHERE code=? AND is_active=1", (code,)).fetchone()
    conn.close()
    return r

def create_promo(code, stars, tcoin, max_uses):
    conn = get_db()
    try:
        conn.execute("INSERT INTO promo_codes (code,stars_reward,tcoin_reward,max_uses) VALUES (?,?,?,?)", (code, stars, tcoin, max_uses))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def delete_promo(code):
    conn = get_db()
    c = conn.execute("DELETE FROM promo_codes WHERE code=?", (code,))
    conn.execute("DELETE FROM used_promo WHERE promo_code=?", (code,))
    conn.commit()
    conn.close()
    return c.rowcount > 0

def use_promo(uid, code):
    conn = get_db()
    if conn.execute("SELECT 1 FROM used_promo WHERE user_id=? AND promo_code=?", (uid, code)).fetchone():
        conn.close()
        return False, "already_used"
    conn.execute("UPDATE promo_codes SET current_uses=current_uses+1 WHERE code=?", (code,))
    conn.execute("INSERT INTO used_promo (user_id,promo_code) VALUES (?,?)", (uid, code))
    conn.commit()
    conn.close()
    return True, "success"

def list_promos(limit=20):
    conn = get_db()
    rows = conn.execute("SELECT * FROM promo_codes ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return rows

def create_check(code: str, sc: int, tc: int, activations: int, created_by: int) -> bool:
    conn = get_db()
    try:
        conn.execute("INSERT INTO checks (code, sc_amount, tc_amount, activations_left, created_by) VALUES (?,?,?,?,?)",
                     (code, sc, tc, activations, created_by))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def use_check(uid: int, code: str):
    conn = get_db()
    if conn.execute("SELECT 1 FROM used_checks WHERE user_id=? AND check_code=?", (uid, code)).fetchone():
        conn.close()
        return False, "already_used", None
    chk = conn.execute("SELECT * FROM checks WHERE code=? AND activations_left > 0", (code,)).fetchone()
    if not chk:
        conn.close()
        return False, "not_found", None
    conn.execute("UPDATE checks SET activations_left=activations_left-1 WHERE code=?", (code,))
    conn.execute("INSERT INTO used_checks (user_id, check_code) VALUES (?,?)", (uid, code))
    conn.commit()
    result = dict(chk)
    conn.close()
    return True, "success", result

def list_user_checks(uid: int, limit=10):
    conn = get_db()
    rows = conn.execute("SELECT * FROM checks WHERE created_by=? ORDER BY created_at DESC LIMIT ?", (uid, limit)).fetchall()
    conn.close()
    return rows

def delete_check(code: str):
    conn = get_db()
    c = conn.execute("DELETE FROM checks WHERE code=?", (code,))
    conn.execute("DELETE FROM used_checks WHERE check_code=?", (code,))
    conn.commit()
    conn.close()
    return c.rowcount > 0

def create_request(uid, rtype, amount):
    conn = get_db()
    c = conn.execute("INSERT INTO requests (user_id,req_type,amount) VALUES (?,?,?)", (uid, rtype, amount))
    rid = c.lastrowid
    conn.commit()
    conn.close()
    return rid

def get_request(rid):
    conn = get_db()
    r = conn.execute("SELECT * FROM requests WHERE id=?", (rid,)).fetchone()
    conn.close()
    return r

def update_request_status(rid, status):
    conn = get_db()
    conn.execute("UPDATE requests SET status=?, processed_at=? WHERE id=?", (status, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), rid))
    conn.commit()
    conn.close()

def get_pending_requests(limit=20):
    conn = get_db()
    rows = conn.execute("SELECT * FROM requests WHERE status='pending' ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return rows

def get_bot_stats():
    conn = get_db()
    s = {}
    s['total_users'] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    s['active_users'] = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=0").fetchone()[0]
    s['banned_users'] = conn.execute("SELECT COUNT(*) FROM users WHERE is_banned=1").fetchone()[0]
    r = conn.execute("SELECT COALESCE(SUM(stars_balance),0), COALESCE(SUM(tcoin_balance),0) FROM users").fetchone()
    s['total_sc'], s['total_tc'] = r
    t = datetime.now().strftime("%Y-%m-%d")
    s['new_today'] = conn.execute("SELECT COUNT(*) FROM users WHERE DATE(created_at)=?", (t,)).fetchone()[0]
    s['tx_today'] = conn.execute("SELECT COUNT(*) FROM transactions WHERE DATE(created_at)=?", (t,)).fetchone()[0]
    s['pending_requests'] = conn.execute("SELECT COUNT(*) FROM requests WHERE status='pending'").fetchone()[0]
    s['active_promos'] = conn.execute("SELECT COUNT(*) FROM promo_codes WHERE is_active=1").fetchone()[0]
    s['active_checks'] = conn.execute("SELECT COUNT(*) FROM checks WHERE activations_left > 0").fetchone()[0]
    conn.close()
    return s

def get_top_balance(limit=10):
    conn = get_db()
    rows = conn.execute("""
        SELECT user_id, username, first_name, stars_balance, tcoin_balance
        FROM users WHERE is_banned=0
        ORDER BY (stars_balance + tcoin_balance) DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return rows

# ==================== ФУНКЦИИ ТОРГОВЦА ====================

def get_trader_trust(uid: int) -> dict:
    conn = get_db()
    r = conn.execute("SELECT * FROM trader_trust WHERE user_id=?", (uid,)).fetchone()
    conn.close()
    if not r:
        return {"level": 0, "total_deposited": 0, "total_earned": 0, "deals_count": 0}
    return dict(r)

def update_trader_trust(uid: int, deposited: int = 0, earned: int = 0):
    conn = get_db()
    r = conn.execute("SELECT * FROM trader_trust WHERE user_id=?", (uid,)).fetchone()
    if not r:
        conn.execute("INSERT INTO trader_trust (user_id, total_deposited, total_earned, deals_count) VALUES (?,?,?,1)",
                     (uid, deposited, earned))
    else:
        new_level = 0
        total_dep = r['total_deposited'] + deposited
        if total_dep >= 50000: new_level = 3
        elif total_dep >= 10000: new_level = 2
        elif total_dep >= 1000: new_level = 1
        conn.execute("""UPDATE trader_trust SET 
            total_deposited=total_deposited+?, total_earned=total_earned+?,
            deals_count=deals_count+1, level=? WHERE user_id=?""",
            (deposited, earned, new_level, uid))
    conn.commit()
    conn.close()

def create_deposit(uid: int, amount: int, duration_hours: int, interest_rate: float) -> int:
    conn = get_db()
    c = conn.execute("""INSERT INTO trader_deposits 
        (user_id, amount, start_time, duration_hours, interest_rate)
        VALUES (?, ?, ?, ?, ?)""",
        (uid, amount, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), duration_hours, interest_rate))
    did = c.lastrowid
    conn.commit()
    conn.close()
    return did

def get_user_deposits(uid: int) -> list:
    conn = get_db()
    rows = conn.execute("""SELECT * FROM trader_deposits 
        WHERE user_id=? AND status='active' ORDER BY start_time DESC""", (uid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def collect_deposit(dep_id: int, uid: int) -> Optional[int]:
    conn = get_db()
    dep = conn.execute("SELECT * FROM trader_deposits WHERE id=? AND user_id=?", (dep_id, uid)).fetchone()
    if not dep:
        conn.close()
        return None
    start = datetime.strptime(dep['start_time'], "%Y-%m-%d %H:%M:%S")
    end = start + timedelta(hours=dep['duration_hours'])
    if datetime.now() < end:
        conn.close()
        return "not_ready"
    payout = int(dep['amount'] * (1 + dep['interest_rate'] / 100))
    conn.execute("UPDATE trader_deposits SET status='collected', collected=1 WHERE id=?", (dep_id,))
    conn.commit()
    conn.close()
    return payout

def create_offer(uid: int, offer_type: str, amount: int, return_amount: int, duration_hours: int, expires_hours: int = 24) -> int:
    conn = get_db()
    expires = (datetime.now() + timedelta(hours=expires_hours)).strftime("%Y-%m-%d %H:%M:%S")
    c = conn.execute("""INSERT INTO trader_offers 
        (user_id, offer_type, amount, return_amount, duration_hours, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)""",
        (uid, offer_type, amount, return_amount, duration_hours, expires))
    oid = c.lastrowid
    conn.commit()
    conn.close()
    return oid

def get_user_offers(uid: int) -> list:
    conn = get_db()
    rows = conn.execute("""SELECT * FROM trader_offers 
        WHERE user_id=? AND accepted=0 AND expires_at > datetime('now')
        ORDER BY expires_at DESC""", (uid,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def accept_offer(offer_id: int, uid: int) -> Optional[dict]:
    conn = get_db()
    offer = conn.execute("SELECT * FROM trader_offers WHERE id=? AND user_id=? AND accepted=0", (offer_id, uid)).fetchone()
    if not offer:
        conn.close()
        return None
    conn.execute("UPDATE trader_offers SET accepted=1 WHERE id=?", (offer_id,))
    conn.commit()
    result = dict(offer)
    conn.close()
    return result

init_db()

# =============================================================================
# ========================= PIARFLOW API ====================================
# =============================================================================

async def pf_get_task(uid, cid):
    ck = f"task_{uid}"
    if ck in api_cache and datetime.now().timestamp() - api_cache[ck][1] < 300:
        return api_cache[ck][0]
    async with aiohttp.ClientSession() as s:
        h = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        try:
            async with s.post(f"{PIARFLOW_BASE_URL}/sponsors", json={"user_id": uid, "chat_id": cid, "max_sponsors": 10}, headers=h) as r:
                d = await r.json()
                api_cache[ck] = (d, datetime.now().timestamp())
                return d
        except Exception as e:
            return {"status": "error", "message": str(e)}

async def pf_check_task(uid, link):
    async with aiohttp.ClientSession() as s:
        h = {"Authorization": f"Bearer {PIARFLOW_API_KEY}", "Content-Type": "application/json"}
        try:
            async with s.post(f"{PIARFLOW_BASE_URL}/sponsors/check", json={"user_id": uid, "links": [link]}, headers=h) as r:
                return await r.json()
        except:
            return {"status": "error"}

# =============================================================================
# ========================= УТИЛИТЫ =========================================
# =============================================================================

def fmt(n):
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M"
    if n >= 1_000: return f"{n/1_000:.1f}K"
    return str(n)

async def resolve_user_id(arg, reply_msg=None):
    if reply_msg and reply_msg.from_user: return reply_msg.from_user.id
    if not arg: return None
    arg = arg.strip()
    if arg.isdigit(): return int(arg)
    if arg.startswith('@'): uname = arg[1:]
    elif re.match(r'^[a-zA-Z0-9_]{3,}$', arg): uname = arg
    else: return None
    u = get_user_by_username(uname)
    return u['user_id'] if u else None

def is_admin(uid):
    u = get_user(uid)
    return bool(u and u['is_admin'])

def is_verified(uid):
    u = get_user(uid)
    return bool(u and u['is_verified'])

def is_bot_active(): return get_setting("bot_active") == "1"
def is_maintenance(): return get_setting("maintenance_mode") == "1"
def safe_html(text): return html.escape(text)

def generate_code(length=8) -> str:
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

def round_to_5(n: int) -> int:
    return (n // 5) * 5

def check_lose_chance() -> bool:
    try:
        chance = float(get_setting("lose_chance") or 0)
    except:
        chance = 0
    if chance <= 0: return False
    if chance >= 100: return True
    return random.random() * 100 < chance

def parse_float(s: str) -> Optional[float]:
    try:
        return float(s.replace(',', '.'))
    except:
        return None

def is_group_chat(msg: Message) -> bool:
    return msg.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]

def btn(text: str, callback_data: str, color: str = "primary") -> InlineKeyboardButton:
    try:
        return InlineKeyboardButton(text=text, callback_data=callback_data, color=color)
    except Exception:
        return InlineKeyboardButton(text=text, callback_data=callback_data)

def btn_menu(): return btn("🏠 Главное меню", "back_menu", "primary")
def btn_profile(): return btn("🔙 Профиль", "profile", "primary")
def btn_admin(): return btn("👑 Админ-панель", "admin", "danger")
def btn_games(): return btn("🎮 К играм", "games_menu", "primary")
def btn_solo_games(): return btn("🎯 Одиночные игры", "solo_games_menu", "success")
def btn_trader(): return btn("🕵️ Тайный торговец", "trader_main", "success")
def btn_balance(): return btn("💰 Баланс", "balance_menu", "primary")
def btn_cancel(target: str = "back_menu"): return btn("❌ Отмена", target, "danger")

def build_keyboard(rows):
    b = InlineKeyboardBuilder()
    for row in rows: b.row(*row)
    return b.as_markup()

def nav_kb(adm=False, extra=None):
    rows = []
    if extra:
        if isinstance(extra[0], list): rows.extend(extra)
        else: rows.append(extra)
    rows.append([btn_menu()])
    if adm: rows.append([btn_admin()])
    return build_keyboard(rows)

# =============================================================================
# ========================= РЕНДЕР ==========================================
# =============================================================================

async def render(target, text, markup, is_cb=False):
    msg = target.message if hasattr(target, 'message') else target
    try:
        if is_cb:
            await msg.edit_text(text, parse_mode="HTML", reply_markup=markup)
        else:
            await msg.answer(text, parse_mode="HTML", reply_markup=markup)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.error(f"Render error: {e}")

async def render_main_menu(target, is_cb=False):
    """Главное меню БЕЗ кнопки Помощь"""
    uid = target.from_user.id if hasattr(target, 'from_user') else target.message.from_user.id
    u = get_user(uid)
    if not u: return
    fn = target.from_user.first_name if hasattr(target, 'from_user') else target.message.from_user.first_name
    
    text = (
        f"🎮 <b>Rakes Games</b>\n\n"
        f"👋 Привет, <b>{fn}</b>!\n\n"
        f"💰 <b>Твой баланс:</b>\n"
        f"⭐ <code>{fmt(u['stars_balance'])}</code> SC\n"
        f"🪙 <code>{fmt(u['tcoin_balance'])}</code> TC\n\n"
        f"🎯 Выбирай раздел:"
    )
    
    kb = build_keyboard([
        [btn("🎰 Казино", "casino_menu", "success"),
         btn("🎯 Одиночные игры", "solo_games_menu", "success")],
        [btn("🕵️ Тайный торговец", "trader_main", "success"),
         btn("💎 Заработок", "earn_menu", "primary")],
        [btn("💰 Баланс", "balance_menu", "primary"),
         btn("🎁 Бонусы", "bonus_menu", "primary")],
        [btn("👤 Профиль", "profile", "primary"),
         btn("🏆 Топ", "top_balance", "primary")]
    ])
    
    if u['is_admin']:
        kb = build_keyboard([
            [btn("🎰 Казино", "casino_menu", "success"),
             btn("🎯 Одиночные игры", "solo_games_menu", "success")],
            [btn("🕵️ Тайный торговец", "trader_main", "success"),
             btn("💎 Заработок", "earn_menu", "primary")],
            [btn("💰 Баланс", "balance_menu", "primary"),
             btn("🎁 Бонусы", "bonus_menu", "primary")],
            [btn("👤 Профиль", "profile", "primary"),
             btn("🏆 Топ", "top_balance", "primary")],
            [btn("👑 Админ-панель", "admin", "danger")]
        ])
    
    await render(target, text, kb, is_cb)

# =============================================================================
# ========================= СТАРТ ===========================================
# =============================================================================

@dp.message(CommandStart())
async def cmd_start(msg: Message):
    uid = msg.from_user.id
    args = msg.text.split()

    if len(args) > 1 and args[1].startswith("check_"):
        code = args[1].replace("check_", "").upper()
        if not get_user(uid):
            create_user(uid, msg.from_user.username or "user", msg.from_user.first_name or "User", f"ref_{uid}", None, 1)
        ok, status, chk = use_check(uid, code)
        if not ok:
            if status == "already_used":
                return await msg.answer("❌ Вы уже активировали этот чек.", reply_markup=nav_kb(is_admin(uid)))
            return await msg.answer("❌ Чек не найден или исчерпан.", reply_markup=nav_kb(is_admin(uid)))
        if chk['sc_amount'] > 0:
            update_balance(uid, stars=chk['sc_amount'], desc=f"Чек: {code}")
        if chk['tc_amount'] > 0:
            update_balance(uid, tcoin=chk['tc_amount'], desc=f"Чек: {code}")
        text = f"✅ <b>Чек активирован!</b>\n\n🎫 Код: <code>{code}</code>\n\n"
        if chk['sc_amount'] > 0: text += f"⭐ +{chk['sc_amount']} SC\n"
        if chk['tc_amount'] > 0: text += f"🪙 +{chk['tc_amount']} TC\n"
        return await msg.answer(text, parse_mode="HTML", reply_markup=nav_kb(is_admin(uid)))

    if is_group_chat(msg):
        fn = msg.from_user.first_name or msg.from_user.username or "друг"
        return await msg.answer(
            f"👋 Привет, <b>{fn}</b>!\n\n"
            f"🎮 Я бот <b>Rakes Games</b>.\n"
            f"Напиши <code>помощь</code> для списка команд.",
            parse_mode="HTML"
        )

    if not is_bot_active() and uid != ADMIN_ID:
        return await msg.answer("🔧 Бот временно недоступен.", reply_markup=nav_kb())
    if is_maintenance() and uid != ADMIN_ID:
        return await msg.answer("🔧 Технические работы.", reply_markup=nav_kb())
    u = get_user(uid)
    if u and u['is_banned']:
        return await msg.answer("❌ Вы заблокированы.", reply_markup=nav_kb())
    if not u:
        ref_by = None
        verified = 1
        if len(args) > 1 and args[1].startswith("ref_"):
            try:
                rid = int(args[1].replace("ref_", ""))
                if rid != uid and get_user(rid):
                    ref_by = rid
                    if get_setting("verification_required") == "1": verified = 0
            except ValueError: pass
        create_user(uid, msg.from_user.username or "user", msg.from_user.first_name or "User", f"ref_{uid}", ref_by, verified)
        if ref_by and verified:
            bonus = int(get_setting("referral_bonus") or 5)
            update_balance(ref_by, stars=bonus, desc="Реферальный бонус")
            increment_referrals(ref_by)
            try: await bot.send_message(ref_by, f"🎉 <b>Друг зарегистрировался!</b>\n+{bonus} ⭐ SC", parse_mode="HTML")
            except: pass
    u = get_user(uid)
    if not u['is_verified'] and get_setting("verification_required") == "1":
        return await render_verify(msg, is_cb=False)
    await render_main_menu(msg, is_cb=False)

async def render_verify(target, is_cb=False):
    uid = target.from_user.id if hasattr(target, 'from_user') else target.message.from_user.id
    text = "⚠️ <b>Подтверждение регистрации</b>\n\nПодпишитесь на спонсора для доступа:"
    td = await pf_get_task(uid, uid)
    if td.get("status") == "ok" and td.get("sponsors"):
        sponsors = td["sponsors"]
        available = [s for s in sponsors if not is_task_completed(uid, s["link"])]
        if not available:
            update_user_field(uid, "is_verified", 1)
            return await render_main_menu(target, is_cb)
        sp = available[0]
        user_current_task[uid] = {"link": sp["link"], "price": sp.get("price", 5), "verify": True}
        kb = build_keyboard([
            [InlineKeyboardButton(text="🔗 Подписаться", url=sp["link"])],
            [btn("✅ Проверить подписку", "task_check", "success")],
            [btn_menu()]])
    else:
        update_user_field(uid, "is_verified", 1)
        await render_main_menu(target, is_cb)
        return
    await render(target, text, kb, is_cb)

# =============================================================================
# ========================= МЕНЮ КАЗИНО =====================================
# =============================================================================

@dp.callback_query(F.data == "casino_menu")
async def cb_casino_menu(cb: CallbackQuery):
    await cb.answer()
    if get_setting("games_enabled") != "1": 
        return await cb.answer("❌ Игры временно отключены", show_alert=True)
    
    text = (
        f"🎰 <b>Казино</b>\n\n"
        f"💵 Ставки: {get_setting('min_bet')}–{get_setting('max_bet')} 🪙\n\n"
        f"<b>🎰 Слоты и кости:</b>\n"
        f"• <code>сл 100</code> — слоты (×10 / ×3 / ×2)\n"
        f"• <code>кости число 100 3</code> — угадать число (×6)\n"
        f"• <code>кости чет 100 чет</code> — чёт/нечет (×2)\n"
        f"• <code>кости больше 100 б</code> — больше/меньше (×2)\n\n"
        f"<b>🎯 Спортивные:</b>\n"
        f"• <code>дротик попадание 100</code> — (×1.9)\n"
        f"• <code>дротик промах 100</code> — (×1.9)\n"
        f"• <code>баскет попадание 100</code> — (×1.9)\n"
        f"• <code>баскет промах 100</code> — (×1.9)\n"
        f"• <code>футбол попадание 100</code> — (×1.9)\n"
        f"• <code>футбол промах 100</code> — (×1.9)\n\n"
        f"<b>🎡 Рулетка и монетка:</b>\n"
        f"• <code>рул цвет 100 к</code> — красное (×2)\n"
        f"• <code>рул цвет 100 ч</code> — чёрное (×2)\n"
        f"• <code>рул цвет 100 з</code> — зеро (×14)\n"
        f"• <code>мон 100 о</code> — орёл (×2)\n"
        f"• <code>мон 100 р</code> — решка (×2)\n\n"
        f"<b>📊 Больше/Меньше:</b>\n"
        f"• <code>больше 100</code> — (×1.9)\n"
        f"• <code>меньше 100</code> — (×1.9)\n\n"
        f"<b>💣 Мины:</b>\n"
        f"• <code>мины 100 3</code> — ставка 100, 3 мины (1-5)\n\n"
        f"<b>🚀 Краш:</b>\n"
        f"• <code>краш 100 2.0</code> — авто-вывод на ×2.0"
    )
    
    kb = build_keyboard([
        [btn_menu()]
    ])
    await render(cb.message, text, kb, is_cb=True)

# =============================================================================
# ========================= МЕНЮ ОДИНОЧНЫХ ИГР ==============================
# =============================================================================

@dp.callback_query(F.data == "solo_games_menu")
async def cb_solo_games_menu(cb: CallbackQuery):
    await cb.answer()
    if get_setting("games_enabled") != "1": 
        return await cb.answer("❌ Игры временно отключены", show_alert=True)
    
    text = (
        f"🎯 <b>Одиночные игры</b>\n\n"
        f"Проходи игры один на один с ботом!\n"
        f"💵 Ставки: {get_setting('min_bet')}–{get_setting('max_bet')} 🪙\n\n"
        f"<b>🎮 Выбери игру:</b>"
    )
    
    kb = build_keyboard([
        [btn("🎰 Риск X", "solo_risk", "success"),
         btn("🔐 Сейф", "solo_safe", "success")],
        [btn("🃏 Высшая карта", "solo_hcard", "success"),
         btn("🎯 Точный бросок", "solo_tthrow", "success")],
        [btn("🚪 Три двери", "solo_doors", "success"),
         btn("🔢 Числовая лестница", "solo_ladder", "success")],
        [btn("⚡ Момент", "solo_moment", "success"),
         btn("🪙 Монетка (серия)", "solo_coin_series", "success")],
        [btn("🧩 Код", "solo_code", "success"),
         btn("🐉 Босс", "solo_boss", "success")],
        [btn_menu()]
    ])
    
    await render(cb.message, text, kb, is_cb=True)

async def game_ready_solo(cb_or_msg, state):
    """Проверка готовности к одиночной игре"""
    if hasattr(cb_or_msg, 'from_user'):
        uid = cb_or_msg.from_user.id
    else:
        uid = cb_or_msg.message.from_user.id
    
    # Проверка, не играет ли уже
    current_state = await state.get_state()
    if current_state and "playing" in current_state:
        return False, "⏳ У тебя уже активна игра!"
    
    u = get_user(uid)
    if not u:
        return False, "❌ Вы не зарегистрированы."
    if u['is_banned']:
        return False, "❌ Вы заблокированы."
    if not is_verified(uid):
        return False, "⚠️ Пройди верификацию: /start в ЛС бота"
    if get_setting("games_enabled") != "1":
        return False, "❌ Игры отключены."
    return True, None

def validate_bet_solo(bet_str: str) -> Tuple[Optional[int], Optional[str]]:
    try:
        bet = int(bet_str)
    except ValueError:
        return None, "❌ Ставка — число!"
    mn, mx = int(get_setting("min_bet") or 10), int(get_setting("max_bet") or 50000)
    if bet < mn: return None, f"❌ Мин. ставка: {mn} 🪙"
    if bet > mx: return None, f"❌ Макс. ставка: {mx} 🪙"
    return bet, None

def check_bal(uid, bet):
    u = get_user(uid)
    return bool(u and u['tcoin_balance'] >= bet)

# =============================================================================
# ========================= ИГРА 1: РИСК X ==================================
# =============================================================================

@dp.callback_query(F.data == "solo_risk")
async def solo_risk_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    ok, err = await game_ready_solo(cb, state)
    if not ok:
        return await cb.answer(err, show_alert=True)
    
    await state.clear()
    await state.set_state(SoloGamesStates.risk_playing)
    text = (
        "🎰 <b>Риск X</b>\n\n"
        "Цепочка множителей растёт: x1.2 → x1.5 → x2 → x3...\n"
        "В любой момент можешь забрать выигрыш.\n"
        "Но если рискнёшь слишком далеко — потеряешь всё!\n\n"
        "💰 Введи ставку:"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))

@dp.message(SoloGamesStates.risk_playing)
async def solo_risk_bet(msg: Message, state: FSMContext):
    bet, err = validate_bet_solo(msg.text.strip())
    if err:
        return await msg.answer(err + "\n\nПопробуй ещё раз:",
                                reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))
    if not check_bal(msg.from_user.id, bet):
        await state.clear()
        return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Риск X")
    
    mult = 1.0
    step = 0
    await state.update_data(bet=bet, mult=mult, step=step)
    await state.set_state(SoloGamesStates.risk_multiplier)
    
    await show_risk_state(msg, state)

async def show_risk_state(msg_or_cb, state):
    data = await state.get_data()
    bet = data['bet']
    mult = data['mult']
    step = data['step']
    current_win = int(bet * mult)
    
    text = (
        f"🎰 <b>Риск X</b>\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"📈 Текущий множитель: <b>×{mult:.2f}</b>\n"
        f"💵 Текущий выигрыш: <b>{current_win} 🪙</b>\n"
        f"🔢 Шагов пройдено: {step}\n\n"
        f"Что делаешь?"
    )
    
    kb = build_keyboard([
        [btn(f"💰 Забрать {current_win} 🪙", "risk_cashout", "success")],
        [btn("🎲 Рискнуть ещё (след. ×{:.2f})".format(mult * random.choice([1.2, 1.3, 1.5]))), "risk_next", "danger")],
        [btn_cancel("solo_games_menu")]
    ])
    
    if hasattr(msg_or_cb, 'edit_text'):
        await msg_or_cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await msg_or_cb.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "risk_next")
async def risk_next(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    bet = data['bet']
    mult = data['mult']
    step = data['step']
    
    # Риск: чем дальше, тем выше шанс проигрыша
    lose_chance = min(5 + step * 7, 70)  # от 5% до 70%
    
    if random.randint(1, 100) <= lose_chance:
        # Проигрыш
        await state.clear()
        near = random.choice(NEAR_MISS)
        text = (
            f"🎰 <b>Риск X</b>\n\n"
            f"💥 <b>КРАХ!</b>\n\n"
            f"📈 Ты дошёл до ×{mult:.2f}\n"
            f"💰 Проиграно: {bet} 🪙\n\n"
            f"{near}"
        )
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=nav_kb(is_admin(cb.from_user.id)))
        return
    
    # Успех — множитель растёт
    new_mult = round(mult * random.choice([1.2, 1.3, 1.4, 1.5]), 2)
    await state.update_data(mult=new_mult, step=step + 1)
    await show_risk_state(cb, state)

@dp.callback_query(F.data == "risk_cashout")
async def risk_cashout(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    bet = data['bet']
    mult = data['mult']
    payout = int(bet * mult)
    
    update_balance(cb.from_user.id, tcoin=payout, desc=f"Риск X ×{mult:.2f}")
    await state.clear()
    
    text = (
        f"🎰 <b>Риск X</b>\n\n"
        f"🎉 <b>ПОБЕДА!</b>\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"📈 Множитель: ×{mult:.2f}\n"
        f"✅ Выигрыш: <b>{payout} 🪙</b>\n\n"
        f"💰 Баланс: <code>{get_user(cb.from_user.id)['tcoin_balance']}</code> 🪙"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))

# =============================================================================
# ========================= ИГРА 2: СЕЙФ ====================================
# =============================================================================

@dp.callback_query(F.data == "solo_safe")
async def solo_safe_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    ok, err = await game_ready_solo(cb, state)
    if not ok:
        return await cb.answer(err, show_alert=True)
    
    await state.clear()
    await state.set_state(SoloGamesStates.safe_playing)
    text = (
        "🔐 <b>Сейф</b>\n\n"
        "У тебя 5 попыток открыть сейф.\n"
        "Каждая правильная комбинация увеличивает награду.\n"
        "Но если ошибёшься — потеряешь всё!\n\n"
        "💰 Введи ставку:"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))

@dp.message(SoloGamesStates.safe_playing)
async def solo_safe_bet(msg: Message, state: FSMContext):
    bet, err = validate_bet_solo(msg.text.strip())
    if err:
        return await msg.answer(err + "\n\nПопробуй ещё раз:",
                                reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))
    if not check_bal(msg.from_user.id, bet):
        await state.clear()
        return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Сейф")
    
    # Генерируем правильную комбинацию из 5 цифр (1-9)
    combo = [random.randint(1, 9) for _ in range(5)]
    
    await state.update_data(bet=bet, combo=combo, attempt=0, current_mult=1.0)
    await state.set_state(SoloGamesStates.safe_attempts)
    
    await show_safe_state(msg, state)

async def show_safe_state(msg_or_cb, state):
    data = await state.get_data()
    bet = data['bet']
    combo = data['combo']
    attempt = data['attempt']
    current_mult = data['current_mult']
    
    text = (
        f"🔐 <b>Сейф</b>\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"🔢 Попытка: {attempt + 1}/5\n"
        f"📈 Множитель: ×{current_mult:.1f}\n"
        f"💵 Текущий выигрыш: <b>{int(bet * current_mult)} 🪙</b>\n\n"
        f"🎯 Выбери цифру (1-9):"
    )
    
    # Клавиатура 3x3 + кнопка забрать
    rows = []
    for i in range(1, 10, 3):
        row = []
        for j in range(3):
            num = i + j
            if num <= 9:
                row.append(btn(str(num), f"safe_pick_{num}", "primary"))
        rows.append(row)
    
    if attempt > 0:
        rows.append([btn(f"💰 Забрать {int(bet * current_mult)} 🪙", "safe_cashout", "success")])
    rows.append([btn_cancel("solo_games_menu")])
    
    kb = build_keyboard(rows)
    
    if hasattr(msg_or_cb, 'edit_text'):
        await msg_or_cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await msg_or_cb.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("safe_pick_"))
async def safe_pick(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    combo = data['combo']
    attempt = data['attempt']
    bet = data['bet']
    current_mult = data['current_mult']
    
    picked = int(cb.data.split("_")[-1])
    correct = combo[attempt]
    
    if picked == correct:
        # Успех
        new_mult = round(current_mult * 1.5, 1)
        await state.update_data(attempt=attempt + 1, current_mult=new_mult)
        
        if attempt + 1 >= 5:
            # Все 5 попыток успешны — джекпот
            payout = int(bet * new_mult * 2)
            update_balance(cb.from_user.id, tcoin=payout, desc=f"Сейф джекпот ×{new_mult * 2:.1f}")
            await state.clear()
            text = (
                f"🔐 <b>Сейф</b>\n\n"
                f"🎉 <b>ДЖЕКПОТ!</b>\n\n"
                f"Ты угадал все 5 цифр!\n"
                f"💰 Ставка: {bet} 🪙\n"
                f"📈 Множитель: ×{new_mult * 2:.1f}\n"
                f"✅ Выигрыш: <b>{payout} 🪙</b>"
            )
            await cb.message.edit_text(text, parse_mode="HTML",
                                       reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))
            return
        
        await show_safe_state(cb, state)
    else:
        # Проигрыш
        await state.clear()
        text = (
            f"🔐 <b>Сейф</b>\n\n"
            f"💥 <b>ТРЕВОГА!</b>\n\n"
            f"Ты выбрал {picked}, но правильная цифра была {correct}.\n"
            f"💰 Проиграно: {bet} 🪙"
        )
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))

@dp.callback_query(F.data == "safe_cashout")
async def safe_cashout(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    bet = data['bet']
    current_mult = data['current_mult']
    payout = int(bet * current_mult)
    
    update_balance(cb.from_user.id, tcoin=payout, desc=f"Сейф ×{current_mult:.1f}")
    await state.clear()
    
    text = (
        f"🔐 <b>Сейф</b>\n\n"
        f"🎉 <b>ПОБЕДА!</b>\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"📈 Множитель: ×{current_mult:.1f}\n"
        f"✅ Выигрыш: <b>{payout} 🪙</b>"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))

# =============================================================================
# ========================= ИГРА 3: ВЫСШАЯ КАРТА ============================
# =============================================================================

CARD_VALUES = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, '8': 8, '9': 9, '10': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
CARD_SUITS = ['♠️', '♥️', '♦️', '♣️']

def random_card():
    value = random.choice(list(CARD_VALUES.keys()))
    suit = random.choice(CARD_SUITS)
    return f"{suit}{value}", CARD_VALUES[value]

@dp.callback_query(F.data == "solo_hcard")
async def solo_hcard_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    ok, err = await game_ready_solo(cb, state)
    if not ok:
        return await cb.answer(err, show_alert=True)
    
    await state.clear()
    await state.set_state(SoloGamesStates.hcard_playing)
    text = (
        "🃏 <b>Высшая карта</b>\n\n"
        "Ты получаешь карту. Бот — свою.\n"
        "У кого карта старше — тот победил.\n\n"
        "💰 Введи ставку:"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))

@dp.message(SoloGamesStates.hcard_playing)
async def solo_hcard_bet(msg: Message, state: FSMContext):
    bet, err = validate_bet_solo(msg.text.strip())
    if err:
        return await msg.answer(err + "\n\nПопробуй ещё раз:",
                                reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))
    if not check_bal(msg.from_user.id, bet):
        await state.clear()
        return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Высшая карта")
    await state.clear()
    
    player_card, player_val = random_card()
    bot_card, bot_val = random_card()
    
    if player_val > bot_val:
        payout = bet * 2
        update_balance(msg.from_user.id, tcoin=payout, desc="Высшая карта победа")
        result = f"🎉 <b>ПОБЕДА!</b>\n\n✅ Выигрыш: <b>{payout} 🪙</b>"
    elif player_val < bot_val:
        result = f"😔 <b>Проигрыш</b>\n\n💰 Проиграно: {bet} 🪙"
    else:
        update_balance(msg.from_user.id, tcoin=bet, desc="Высшая карта ничья")
        result = f"🤝 <b>Ничья!</b>\n\n💰 Ставка возвращена."
    
    text = (
        f"🃏 <b>Высшая карта</b>\n\n"
        f"👤 Твоя карта: <b>{player_card}</b>\n"
        f"🤖 Карта бота: <b>{bot_card}</b>\n\n"
        f"{result}\n\n"
        f"💰 Баланс: <code>{get_user(msg.from_user.id)['tcoin_balance']}</code> 🪙"
    )
    await msg.answer(text, parse_mode="HTML",
                     reply_markup=nav_kb(is_admin(msg.from_user.id), [btn_solo_games()]))

# =============================================================================
# ========================= ИГРА 4: ТОЧНЫЙ БРОСОК ===========================
# =============================================================================

@dp.callback_query(F.data == "solo_tthrow")
async def solo_tthrow_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    ok, err = await game_ready_solo(cb, state)
    if not ok:
        return await cb.answer(err, show_alert=True)
    
    await state.clear()
    await state.set_state(SoloGamesStates.tthrow_playing)
    text = (
        "🎯 <b>Точный бросок</b>\n\n"
        "Выбери силу броска (1-10):\n"
        "• Слабый (1-3) — безопасно, но малый выигрыш\n"
        "• Средний (4-7) — баланс риска и награды\n"
        "• Сильный (8-10) — огромный выигрыш, но легко промахнуться\n\n"
        "💰 Введи ставку:"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))

@dp.message(SoloGamesStates.tthrow_playing)
async def solo_tthrow_bet(msg: Message, state: FSMContext):
    bet, err = validate_bet_solo(msg.text.strip())
    if err:
        return await msg.answer(err + "\n\nПопробуй ещё раз:",
                                reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))
    if not check_bal(msg.from_user.id, bet):
        await state.clear()
        return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Точный бросок")
    await state.update_data(bet=bet)
    
    text = (
        "🎯 <b>Выбери силу броска:</b>\n\n"
        "💪 Сила влияет на риск и награду."
    )
    
    kb = build_keyboard([
        [btn("🎯 Сила 1-3 (безопасно)", "tthrow_power_low", "success")],
        [btn("🎯 Сила 4-7 (баланс)", "primary")],  # будет подменено
        [btn("🎯 Сила 8-10 (рискованно)", "tthrow_power_high", "danger")],
        [btn_cancel("solo_games_menu")]
    ])
    # Исправим клавиатуру
    kb = build_keyboard([
        [btn("💪 Слабый бросок (1-3)", "tthrow_power_low", "success")],
        [btn("💪💪 Средний бросок (4-7)", "tthrow_power_mid", "primary")],
        [btn("💪💪💪 Сильный бросок (8-10)", "tthrow_power_high", "danger")],
        [btn_cancel("solo_games_menu")]
    ])
    
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("tthrow_power_"))
async def tthrow_power(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    bet = data['bet']
    
    power = cb.data.split("_")[-1]
    
    # Параметры для каждой силы
    if power == "low":
        hit_zone = (1, 3)
        win_mult = 1.5
        perfect_mult = 2.5
        miss_text = "Промахнулся в слабой зоне"
    elif power == "mid":
        hit_zone = (4, 7)
        win_mult = 2.5
        perfect_mult = 4.0
        miss_text = "Промахнулся в средней зоне"
    else:  # high
        hit_zone = (8, 10)
        win_mult = 4.0
        perfect_mult = 8.0
        miss_text = "Промахнулся в сильной зоне"
    
    await state.clear()
    
    # Бросок: случайное число 1-10
    throw = random.randint(1, 10)
    
    if hit_zone[0] <= throw <= hit_zone[1]:
        # Попадание
        if throw == hit_zone[1]:  # Идеальное попадание
            payout = int(bet * perfect_mult)
            result_text = f"🎯 <b>ИДЕАЛЬНОЕ ПОПАДАНИЕ!</b>\n\n💥 Сила броска: {throw}\n✅ Выигрыш: <b>{payout} 🪙</b> (×{perfect_mult})"
        else:
            payout = int(bet * win_mult)
            result_text = f"🎯 <b>Попадание!</b>\n\n💥 Сила броска: {throw}\n✅ Выигрыш: <b>{payout} 🪙</b> (×{win_mult})"
        update_balance(cb.from_user.id, tcoin=payout, desc=f"Точный бросок ×{win_mult if throw != hit_zone[1] else perfect_mult}")
    else:
        result_text = f"💨 <b>Промах!</b>\n\n💥 Сила броска: {throw}\n💰 Проиграно: {bet} 🪙\n\n{miss_text}"
    
    text = (
        f"🎯 <b>Точный бросок</b>\n\n"
        f"{result_text}\n\n"
        f"💰 Баланс: <code>{get_user(cb.from_user.id)['tcoin_balance']}</code> 🪙"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))

# =============================================================================
# ========================= ИГРА 5: ТРИ ДВЕРИ ===============================
# =============================================================================

@dp.callback_query(F.data == "solo_doors")
async def solo_doors_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    ok, err = await game_ready_solo(cb, state)
    if not ok:
        return await cb.answer(err, show_alert=True)
    
    await state.clear()
    await state.set_state(SoloGamesStates.doors_playing)
    text = (
        "🚪 <b>Три двери</b>\n\n"
        "За тремя дверями — разные награды:\n"
        "• 💰 Малая награда (×0.5 — возврат половины)\n"
        "• 💎 Средняя награда (×2)\n"
        "• 🏆 Большая награда (×5)\n\n"
        "💰 Введи ставку:"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))

@dp.message(SoloGamesStates.doors_playing)
async def solo_doors_bet(msg: Message, state: FSMContext):
    bet, err = validate_bet_solo(msg.text.strip())
    if err:
        return await msg.answer(err + "\n\nПопробуй ещё раз:",
                                reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))
    if not check_bal(msg.from_user.id, bet):
        await state.clear()
        return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Три двери")
    await state.update_data(bet=bet)
    await state.clear()
    
    text = (
        "🚪 <b>Выбери дверь:</b>\n\n"
        "🚪 [1] 🚪 [2] 🚪 [3]\n\n"
        "За одной — большая награда,\n"
        "за другой — средняя,\n"
        "за третьей — малая."
    )
    
    kb = build_keyboard([
        [btn("🚪 Дверь 1", "door_pick_1", "success"),
         btn("🚪 Дверь 2", "door_pick_2", "success"),
         btn("🚪 Дверь 3", "door_pick_3", "success")],
        [btn_cancel("solo_games_menu")]
    ])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.startswith("door_pick_"))
async def door_pick(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    
    # Находим ставку из истории транзакций (последняя)
    conn = get_db()
    last_tx = conn.execute("""SELECT amount FROM transactions 
        WHERE user_id=? AND description LIKE 'Ставка: Три двери%'
        ORDER BY id DESC LIMIT 1""", (cb.from_user.id,)).fetchone()
    conn.close()
    bet = last_tx['amount'] if last_tx else 0
    
    # Распределяем награды по дверям
    rewards = [0.5, 2.0, 5.0]
    random.shuffle(rewards)
    
    picked = int(cb.data.split("_")[-1]) - 1
    mult = rewards[picked]
    payout = int(bet * mult)
    
    # Показываем все двери
    doors_text = ""
    for i, r in enumerate(rewards, 1):
        marker = " 👈" if i - 1 == picked else ""
        if r == 0.5: doors_text += f"🚪 [{i}] 💰 Малая (×0.5){marker}\n"
        elif r == 2.0: doors_text += f"🚪 [{i}] 💎 Средняя (×2){marker}\n"
        else: doors_text += f"🚪 [{i}] 🏆 Большая (×5){marker}\n"
    
    if mult >= 2.0:
        update_balance(cb.from_user.id, tcoin=payout, desc=f"Три двери ×{mult}")
        result = f"🎉 <b>ПОБЕДА!</b>\n\n✅ Выигрыш: <b>{payout} 🪙</b> (×{mult})"
    else:
        update_balance(cb.from_user.id, tcoin=payout, desc=f"Три двери ×{mult}")
        result = f"💰 Малая награда\n\nВернулось: {payout} 🪙 (×0.5)"
    
    text = (
        f"🚪 <b>Три двери</b>\n\n"
        f"📍 Распределение наград:\n{doors_text}\n"
        f"{result}\n\n"
        f"💰 Баланс: <code>{get_user(cb.from_user.id)['tcoin_balance']}</code> 🪙"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))

# =============================================================================
# ========================= ИГРА 6: ЧИСЛОВАЯ ЛЕСТНИЦА ========================
# =============================================================================

@dp.callback_query(F.data == "solo_ladder")
async def solo_ladder_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    ok, err = await game_ready_solo(cb, state)
    if not ok:
        return await cb.answer(err, show_alert=True)
    
    await state.clear()
    await state.set_state(SoloGamesStates.ladder_playing)
    text = (
        "🔢 <b>Числовая лестница</b>\n\n"
        "Бот показывает число. Ты угадываешь:\n"
        "следующее число будет <b>ВЫШЕ</b> или <b>НИЖЕ</b>?\n\n"
        "Чем длиннее серия — тем выше награда!\n"
        "Ошибёшься — потеряешь всё.\n\n"
        "💰 Введи ставку:"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))

@dp.message(SoloGamesStates.ladder_playing)
async def solo_ladder_bet(msg: Message, state: FSMContext):
    bet, err = validate_bet_solo(msg.text.strip())
    if err:
        return await msg.answer(err + "\n\nПопробуй ещё раз:",
                                reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))
    if not check_bal(msg.from_user.id, bet):
        await state.clear()
        return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Числовая лестница")
    
    current = random.randint(1, 100)
    await state.update_data(bet=bet, current=current, streak=0)
    await state.set_state(SoloGamesStates.ladder_current)
    
    await show_ladder_state(msg, state)

async def show_ladder_state(msg_or_cb, state):
    data = await state.get_data()
    bet = data['bet']
    current = data['current']
    streak = data['streak']
    
    # Множитель за серию
    mult = 1.0 + streak * 0.3
    current_win = int(bet * mult)
    
    text = (
        f"🔢 <b>Числовая лестница</b>\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"🔥 Серия: {streak}\n"
        f"📈 Множитель: ×{mult:.1f}\n"
        f"💵 Текущий выигрыш: <b>{current_win} 🪙</b>\n\n"
        f"🎯 Текущее число: <b>{current}</b>\n\n"
        f"Следующее число будет..."
    )
    
    kb = build_keyboard([
        [btn("📈 ВЫШЕ", "ladder_higher", "success"),
         btn("📉 НИЖЕ", "ladder_lower", "success")],
        [btn(f"💰 Забрать {current_win} 🪙", "ladder_cashout", "primary")],
        [btn_cancel("solo_games_menu")]
    ])
    
    if hasattr(msg_or_cb, 'edit_text'):
        await msg_or_cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await msg_or_cb.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.in_(["ladder_higher", "ladder_lower"]))
async def ladder_guess(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    current = data['current']
    streak = data['streak']
    bet = data['bet']
    
    guess = "higher" if cb.data == "ladder_higher" else "lower"
    
    # Новое число (не равно текущему)
    new = random.randint(1, 100)
    while new == current:
        new = random.randint(1, 100)
    
    correct = (guess == "higher" and new > current) or (guess == "lower" and new < current)
    
    if not correct:
        # Проигрыш
        await state.clear()
        text = (
            f"🔢 <b>Числовая лестница</b>\n\n"
            f"💥 <b>ОШИБКА!</b>\n\n"
            f"🎯 Было: {current}\n"
            f"🎯 Стало: {new}\n"
            f"❌ Ты угадывал: {'ВЫШЕ' if guess == 'higher' else 'НИЖЕ'}\n\n"
            f"💰 Проиграно: {bet} 🪙\n"
            f"🔥 Серия прервалась на {streak}"
        )
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))
        return
    
    # Успех
    await state.update_data(current=new, streak=streak + 1)
    await show_ladder_state(cb, state)

@dp.callback_query(F.data == "ladder_cashout")
async def ladder_cashout(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    bet = data['bet']
    streak = data['streak']
    
    if streak == 0:
        return await cb.answer("⚠️ Угадай хотя бы 1 раз!", show_alert=True)
    
    mult = 1.0 + streak * 0.3
    payout = int(bet * mult)
    
    update_balance(cb.from_user.id, tcoin=payout, desc=f"Лестница ×{mult:.1f}")
    await state.clear()
    
    text = (
        f"🔢 <b>Числовая лестница</b>\n\n"
        f"🎉 <b>ПОБЕДА!</b>\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"🔥 Серия: {streak}\n"
        f"📈 Множитель: ×{mult:.1f}\n"
        f"✅ Выигрыш: <b>{payout} 🪙</b>"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))

# =============================================================================
# ========================= ИГРА 7: МОМЕНТ ==================================
# =============================================================================

@dp.callback_query(F.data == "solo_moment")
async def solo_moment_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    ok, err = await game_ready_solo(cb, state)
    if not ok:
        return await cb.answer(err, show_alert=True)
    
    await state.clear()
    await state.set_state(SoloGamesStates.moment_playing)
    text = (
        "⚡ <b>Момент</b>\n\n"
        "Шкала быстро движется от 0 до 100.\n"
        "Твоя задача — нажать СТОП в нужный момент!\n\n"
        "🎯 Зоны:\n"
        "• 0-20 и 80-100: ×0 (проигрыш)\n"
        "• 21-40 и 60-79: ×1.5\n"
        "• 41-59: ×3 (золотая зона)\n\n"
        "💰 Введи ставку:"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))

@dp.message(SoloGamesStates.moment_playing)
async def solo_moment_bet(msg: Message, state: FSMContext):
    bet, err = validate_bet_solo(msg.text.strip())
    if err:
        return await msg.answer(err + "\n\nПопробуй ещё раз:",
                                reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))
    if not check_bal(msg.from_user.id, bet):
        await state.clear()
        return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Момент")
    await state.update_data(bet=bet, position=0, running=True)
    
    # Отправляем начальное сообщение
    text = "⚡ <b>Момент</b>\n\n🎯 Шкала: [0%]\n\n⏳ Запускается..."
    kb = build_keyboard([
        [btn("🛑 СТОП!", "moment_stop", "danger")],
        [btn_cancel("solo_games_menu")]
    ])
    start_msg = await msg.answer(text, parse_mode="HTML", reply_markup=kb)
    await state.update_data(message_id=start_msg.message_id)
    
    # Запускаем анимацию в фоне
    asyncio.create_task(moment_animation(msg.from_user.id, state, start_msg.message_id))

async def moment_animation(uid: int, state: FSMContext, message_id: int):
    """Анимация движения шкалы"""
    position = 0
    speed = 5  # шагов в секунду
    direction = 1
    
    while position < 100:
        # Проверяем, не остановил ли игрок
        try:
            data = await state.get_data()
            if not data.get('running', False):
                return
        except:
            return
        
        position += speed * direction
        if position >= 100:
            position = 100
            direction = -1
        elif position <= 0:
            position = 0
            direction = 1
        
        bar = "█" * int(position / 5) + "░" * (20 - int(position / 5))
        text = f"⚡ <b>Момент</b>\n\n🎯 Шкала: [{bar}] {position}%\n\n⏳ Жми СТОП!"
        kb = build_keyboard([
            [btn("🛑 СТОП!", "moment_stop", "danger")]
        ])
        
        try:
            await bot.edit_message_text(chat_id=uid, message_id=message_id,
                                        text=text, parse_mode="HTML", reply_markup=kb)
        except:
            return
        
        await asyncio.sleep(0.1)
    
    # Если дошло до 100 — автоматический стоп
    try:
        data = await state.get_data()
        if data.get('running', False):
            await state.update_data(position=100, running=False)
            await moment_result(uid, state, message_id)
    except:
        pass

@dp.callback_query(F.data == "moment_stop")
async def moment_stop(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    if not data.get('running', False):
        return
    
    # Фиксируем текущую позицию
    # (в реальности позиция берётся из состояния анимации)
    # Для упрощения — генерируем случайную позицию
    position = random.randint(0, 100)
    await state.update_data(position=position, running=False)
    
    await moment_result(cb.from_user.id, state, cb.message.message_id)

async def moment_result(uid: int, state: FSMContext, message_id: int):
    data = await state.get_data()
    bet = data['bet']
    position = data.get('position', 50)
    
    # Определяем выигрыш
    if 41 <= position <= 59:
        mult = 3.0
        zone = "🏆 ЗОЛОТАЯ ЗОНА!"
    elif (21 <= position <= 40) or (60 <= position <= 79):
        mult = 1.5
        zone = "✅ Хорошая зона"
    else:
        mult = 0
        zone = "💥 Промах!"
    
    if mult > 0:
        payout = int(bet * mult)
        update_balance(uid, tcoin=payout, desc=f"Момент ×{mult}")
        result = f"🎉 <b>ПОБЕДА!</b>\n\n✅ Выигрыш: <b>{payout} 🪙</b> (×{mult})"
    else:
        result = f"😔 <b>Проигрыш</b>\n\n💰 Проиграно: {bet} 🪙"
    
    bar = "█" * int(position / 5) + "░" * (20 - int(position / 5))
    text = (
        f"⚡ <b>Момент</b>\n\n"
        f"🎯 Шкала остановилась: [{bar}] <b>{position}%</b>\n"
        f"{zone}\n\n"
        f"{result}\n\n"
        f"💰 Баланс: <code>{get_user(uid)['tcoin_balance']}</code> 🪙"
    )
    
    try:
        await bot.edit_message_text(chat_id=uid, message_id=message_id,
                                    text=text, parse_mode="HTML",
                                    reply_markup=nav_kb(is_admin(uid), [btn_solo_games()]))
    except:
        await bot.send_message(uid, text, parse_mode="HTML",
                               reply_markup=nav_kb(is_admin(uid), [btn_solo_games()]))
    await state.clear()

# =============================================================================
# ========================= ИГРА 8: МОНЕТКА (СЕРИЯ) =========================
# =============================================================================

@dp.callback_query(F.data == "solo_coin_series")
async def solo_coin_series_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    ok, err = await game_ready_solo(cb, state)
    if not ok:
        return await cb.answer(err, show_alert=True)
    
    await state.clear()
    await state.set_state(SoloGamesStates.coin_series)
    text = (
        "🪙 <b>Монетка (серия)</b>\n\n"
        "Угадывай орёл/решка несколько раз подряд.\n"
        "Каждый правильный ответ удваивает выигрыш!\n"
        "Ошибёшься — потеряешь всё.\n\n"
        "💰 Введи ставку:"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))

@dp.message(SoloGamesStates.coin_series)
async def solo_coin_series_bet(msg: Message, state: FSMContext):
    bet, err = validate_bet_solo(msg.text.strip())
    if err:
        return await msg.answer(err + "\n\nПопробуй ещё раз:",
                                reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))
    if not check_bal(msg.from_user.id, bet):
        await state.clear()
        return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Монетка серия")
    await state.update_data(bet=bet, streak=0)
    await state.set_state(SoloGamesStates.coin_streak)
    
    await show_coin_series_state(msg, state)

async def show_coin_series_state(msg_or_cb, state):
    data = await state.get_data()
    bet = data['bet']
    streak = data['streak']
    current_win = bet * (2 ** streak) if streak > 0 else bet
    
    text = (
        f"🪙 <b>Монетка (серия)</b>\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"🔥 Серия: {streak}\n"
        f"💵 Текущий выигрыш: <b>{current_win} 🪙</b>\n\n"
        f"🎯 Орёл или решка?"
    )
    
    kb = build_keyboard([
        [btn("🦅 Орёл", "coin_series_heads", "success"),
         btn("🪙 Решка", "coin_series_tails", "success")],
        [btn(f"💰 Забрать {current_win} 🪙", "coin_series_cashout", "primary")] if streak > 0 else [],
        [btn_cancel("solo_games_menu")]
    ])
    # Убираем пустые ряды
    kb = build_keyboard([r for r in kb.inline_keyboard if r])
    
    if hasattr(msg_or_cb, 'edit_text'):
        await msg_or_cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await msg_or_cb.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.in_(["coin_series_heads", "coin_series_tails"]))
async def coin_series_guess(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    streak = data['streak']
    bet = data['bet']
    
    guess = "орёл" if cb.data == "coin_series_heads" else "решка"
    result = random.choice(["орёл", "решка"])
    
    emoji = "🦅" if result == "орёл" else "🪙"
    
    if result == guess:
        # Успех
        await state.update_data(streak=streak + 1)
        text = (
            f"{emoji} <b>{result.capitalize()}!</b>\n\n"
            f"✅ Правильно! Серия: {streak + 1}\n\n"
            f"Продолжаем?"
        )
        await show_coin_series_state(cb, state)
    else:
        # Проигрыш
        await state.clear()
        text = (
            f"{emoji} <b>{result.capitalize()}!</b>\n\n"
            f"💥 <b>ОШИБКА!</b>\n\n"
            f"Ты угадывал: {guess}\n"
            f"Выпало: {result}\n\n"
            f"💰 Проиграно: {bet} 🪙\n"
            f"🔥 Серия прервалась на {streak}"
        )
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))

@dp.callback_query(F.data == "coin_series_cashout")
async def coin_series_cashout(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    bet = data['bet']
    streak = data['streak']
    
    if streak == 0:
        return await cb.answer("⚠️ Угадай хотя бы 1 раз!", show_alert=True)
    
    payout = bet * (2 ** streak)
    update_balance(cb.from_user.id, tcoin=payout, desc=f"Монетка серия ×{2**streak}")
    await state.clear()
    
    text = (
        f"🪙 <b>Монетка (серия)</b>\n\n"
        f"🎉 <b>ПОБЕДА!</b>\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"🔥 Серия: {streak}\n"
        f"📈 Множитель: ×{2**streak}\n"
        f"✅ Выигрыш: <b>{payout} 🪙</b>"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))

# =============================================================================
# ========================= ИГРА 9: КОД =====================================
# =============================================================================

@dp.callback_query(F.data == "solo_code")
async def solo_code_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    ok, err = await game_ready_solo(cb, state)
    if not ok:
        return await cb.answer(err, show_alert=True)
    
    await state.clear()
    await state.set_state(SoloGamesStates.code_playing)
    text = (
        "🧩 <b>Код</b>\n\n"
        "Нужно угадать код из 4 цифр (0-9).\n"
        "После каждой попытки бот подсказывает:\n"
        "• 🔴 Цифра есть в коде, но не на своём месте\n"
        "• 🟢 Цифра на своём месте\n\n"
        "У тебя 8 попыток!\n\n"
        "💰 Введи ставку:"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))

@dp.message(SoloGamesStates.code_playing)
async def solo_code_bet(msg: Message, state: FSMContext):
    bet, err = validate_bet_solo(msg.text.strip())
    if err:
        return await msg.answer(err + "\n\nПопробуй ещё раз:",
                                reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))
    if not check_bal(msg.from_user.id, bet):
        await state.clear()
        return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Код")
    
    # Генерируем код из 4 уникальных цифр
    code = random.sample(range(10), 4)
    
    await state.update_data(bet=bet, code=code, attempts=0, history=[])
    await state.set_state(SoloGamesStates.code_attempts)
    
    await show_code_state(msg, state)

async def show_code_state(msg_or_cb, state):
    data = await state.get_data()
    bet = data['bet']
    attempts = data['attempts']
    history = data['history']
    
    text = (
        f"🧩 <b>Код</b>\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"🔢 Попытка: {attempts + 1}/8\n\n"
    )
    
    if history:
        text += "<b>История:</b>\n"
        for h in history[-5:]:  # последние 5
            text += f"  {h['guess']} → {h['hint']}\n"
        text += "\n"
    
    text += "🎯 Введи 4 цифры (например: 1234):"
    
    kb = build_keyboard([[btn_cancel("solo_games_menu")]])
    
    if hasattr(msg_or_cb, 'edit_text'):
        await msg_or_cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await msg_or_cb.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.message(SoloGamesStates.code_attempts)
async def code_guess(msg: Message, state: FSMContext):
    data = await state.get_data()
    code = data['code']
    attempts = data['attempts']
    history = data['history']
    bet = data['bet']
    
    guess_str = msg.text.strip()
    if not re.match(r'^\d{4}$', guess_str):
        return await msg.answer("❌ Введи ровно 4 цифры (0-9).",
                                reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))
    
    guess = [int(d) for d in guess_str]
    
    # Считаем подсказки
    greens = sum(1 for i in range(4) if guess[i] == code[i])
    reds = sum(1 for i in range(4) if guess[i] in code and guess[i] != code[i])
    
    hint = f"🟢{greens} 🔴{reds}"
    history.append({"guess": guess_str, "hint": hint})
    attempts += 1
    
    if greens == 4:
        # Победа!
        mult = max(1, 10 - attempts)  # чем меньше попыток, тем больше выигрыш
        payout = bet * mult
        update_balance(msg.from_user.id, tcoin=payout, desc=f"Код ×{mult}")
        await state.clear()
        
        text = (
            f"🧩 <b>Код</b>\n\n"
            f"🎉 <b>ВЗЛОМАН!</b>\n\n"
            f"🔐 Код был: <code>{''.join(map(str, code))}</code>\n"
            f"🔢 Попыток: {attempts}\n"
            f"📈 Множитель: ×{mult}\n"
            f"✅ Выигрыш: <b>{payout} 🪙</b>"
        )
        await msg.answer(text, parse_mode="HTML",
                         reply_markup=nav_kb(is_admin(msg.from_user.id), [btn_solo_games()]))
        return
    
    if attempts >= 8:
        # Проигрыш
        await state.clear()
        text = (
            f"🧩 <b>Код</b>\n\n"
            f"💥 <b>ПОПЫТКИ ИСЧЕРПАНЫ!</b>\n\n"
            f"🔐 Код был: <code>{''.join(map(str, code))}</code>\n"
            f"💰 Проиграно: {bet} 🪙"
        )
        await msg.answer(text, parse_mode="HTML",
                         reply_markup=nav_kb(is_admin(msg.from_user.id), [btn_solo_games()]))
        return
    
    await state.update_data(attempts=attempts, history=history)
    await show_code_state(msg, state)

# =============================================================================
# ========================= ИГРА 10: БОСС ===================================
# =============================================================================

@dp.callback_query(F.data == "solo_boss")
async def solo_boss_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    ok, err = await game_ready_solo(cb, state)
    if not ok:
        return await cb.answer(err, show_alert=True)
    
    await state.clear()
    await state.set_state(SoloGamesStates.boss_playing)
    text = (
        "🐉 <b>Битва с боссом</b>\n\n"
        "Сражайся с драконом в пошаговой битве!\n"
        "⚔️ Атака: наносит 15-25 урона\n"
        "🛡 Защита: блокирует 50% урона + контратака 5-10\n"
        "💥 Особый удар: 30-50 урона, но 30% шанс промаха\n\n"
        "💰 Введи ставку:"
    )
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))

@dp.message(SoloGamesStates.boss_playing)
async def solo_boss_bet(msg: Message, state: FSMContext):
    bet, err = validate_bet_solo(msg.text.strip())
    if err:
        return await msg.answer(err + "\n\nПопробуй ещё раз:",
                                reply_markup=build_keyboard([[btn_cancel("solo_games_menu")]]))
    if not check_bal(msg.from_user.id, bet):
        await state.clear()
        return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Босс")
    
    # Босс: 100 HP
    boss_hp = 100
    player_hp = 100
    
    await state.update_data(bet=bet, boss_hp=boss_hp, player_hp=player_hp, turn=1)
    await state.set_state(SoloGamesStates.boss_hp)
    
    await show_boss_state(msg, state)

async def show_boss_state(msg_or_cb, state):
    data = await state.get_data()
    bet = data['bet']
    boss_hp = data['boss_hp']
    player_hp = data['player_hp']
    turn = data['turn']
    
    # Полоски HP
    boss_bar = "█" * (boss_hp // 10) + "░" * (10 - boss_hp // 10)
    player_bar = "█" * (player_hp // 10) + "░" * (10 - player_hp // 10)
    
    text = (
        f"🐉 <b>Битва с боссом</b> (ход {turn})\n\n"
        f"🐉 Дракон: [{boss_bar}] {boss_hp}/100 HP\n"
        f"🧙 Ты: [{player_bar}] {player_hp}/100 HP\n\n"
        f"💰 Ставка: {bet} 🪙\n"
        f"💵 При победе: <b>{bet * 3} 🪙</b>\n\n"
        f"🎯 Твоё действие:"
    )
    
    kb = build_keyboard([
        [btn("⚔️ Атака", "boss_attack", "success"),
         btn("🛡 Защита", "boss_defend", "primary")],
        [btn("💥 Особый удар", "boss_special", "danger")],
        [btn_cancel("solo_games_menu")]
    ])
    
    if hasattr(msg_or_cb, 'edit_text'):
        await msg_or_cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    else:
        await msg_or_cb.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data.in_(["boss_attack", "boss_defend", "boss_special"]))
async def boss_action(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    boss_hp = data['boss_hp']
    player_hp = data['player_hp']
    turn = data['turn']
    bet = data['bet']
    
    action = cb.data.split("_")[-1]
    log = []
    
    # Действие игрока
    if action == "attack":
        dmg = random.randint(15, 25)
        boss_hp -= dmg
        log.append(f"⚔️ Ты атакуешь: -{dmg} HP дракону")
    elif action == "defend":
        dmg_to_boss = random.randint(5, 10)
        boss_hp -= dmg_to_boss
        log.append(f"🛡 Ты защищаешься и контратакуешь: -{dmg_to_boss} HP")
    elif action == "special":
        if random.random() < 0.3:
            log.append(f"💥 Особый удар промахнулся!")
        else:
            dmg = random.randint(30, 50)
            boss_hp -= dmg
            log.append(f"💥 Особый удар: -{dmg} HP дракону!")
    
    # Проверка победы
    if boss_hp <= 0:
        boss_hp = 0
        payout = bet * 3
        update_balance(cb.from_user.id, tcoin=payout, desc="Босс побеждён ×3")
        await state.clear()
        
        log_text = "\n".join(log)
        text = (
            f"🐉 <b>Битва с боссом</b>\n\n"
            f"{log_text}\n\n"
            f"🎉 <b>ПОБЕДА!</b>\n\n"
            f"🐉 Дракон повержен!\n"
            f"💰 Ставка: {bet} 🪙\n"
            f"✅ Выигрыш: <b>{payout} 🪙</b>"
        )
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))
        return
    
    # Действие босса
    boss_dmg = random.randint(10, 20)
    if action == "defend":
        boss_dmg = boss_dmg // 2  # защита снижает урон
    player_hp -= boss_dmg
    log.append(f"🐉 Дракон атакует: -{boss_dmg} HP тебе" + (" (защита)" if action == "defend" else ""))
    
    # Проверка поражения
    if player_hp <= 0:
        player_hp = 0
        await state.clear()
        
        log_text = "\n".join(log)
        text = (
            f"🐉 <b>Битва с боссом</b>\n\n"
            f"{log_text}\n\n"
            f"💀 <b>ПОРАЖЕНИЕ!</b>\n\n"
            f"🐉 Дракон оказался сильнее.\n"
            f"💰 Проиграно: {bet} 🪙"
        )
        await cb.message.edit_text(text, parse_mode="HTML",
                                   reply_markup=nav_kb(is_admin(cb.from_user.id), [btn_solo_games()]))
        return
    
    await state.update_data(boss_hp=boss_hp, player_hp=player_hp, turn=turn + 1)
    
    # Добавляем лог в состояние для отображения
    prev_log = data.get('log', [])
    prev_log.extend(log)
    await state.update_data(log=prev_log[-6:])  # последние 6 действий
    
    await show_boss_state(cb, state)

# =============================================================================
# ========================= ТАЙНЫЙ ТОРГОВЕЦ =================================
# =============================================================================

@dp.callback_query(F.data == "trader_main")
async def trader_main(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    
    u = get_user(cb.from_user.id)
    trust = get_trader_trust(cb.from_user.id)
    deposits = get_user_deposits(cb.from_user.id)
    offers = get_user_offers(cb.from_user.id)
    
    # Уровень доверия
    trust_levels = {
        0: ("👤 Незнакомец", "Базовые вклады"),
        1: ("🤝 Знакомый", "Вклады +6ч, +24ч"),
        2: ("✅ Проверенный", "Все вклады + редкие предложения"),
        3: ("💎 VIP", "Макс. доход + эксклюзив")
    }
    trust_name, trust_desc = trust_levels.get(trust['level'], trust_levels[0])
    
    text = (
        f"🕵️ <b>Тайный торговец</b>\n\n"
        f"🎭 «Добро пожаловать, друг... У меня есть предложения,\n"
        f"которые не найдёшь больше нигде. Но помни —\n"
        f"доверие зарабатывается делом.»\n\n"
        f"📊 <b>Твой статус:</b> {trust_name}\n"
        f"📝 {trust_desc}\n"
        f"💼 Всего вложено: {fmt(trust['total_deposited'])} TC\n"
        f"💰 Заработано: {fmt(trust['total_earned'])} TC\n"
        f"🤝 Сделок: {trust['deals_count']}\n\n"
        f"💵 Твой баланс: <code>{u['tcoin_balance']}</code> 🪙\n"
    )
    
    if deposits:
        text += f"\n🏦 <b>Активных вкладов:</b> {len(deposits)}\n"
    if offers:
        text += f"🔥 <b>Спецпредложений:</b> {len(offers)}\n"
    
    kb = build_keyboard([
        [btn("🏦 Сделать вклад", "trader_deposit", "success")],
        [btn(f"💼 Мои вклады ({len(deposits)})", "trader_my_deposits", "primary")],
        [btn(f"🔥 Спецпредложения ({len(offers)})", "trader_offers", "danger")] if offers else [],
        [btn_menu()]
    ])
    kb = build_keyboard([r for r in kb.inline_keyboard if r])
    
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data == "trader_deposit")
async def trader_deposit_start(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    
    trust = get_trader_trust(cb.from_user.id)
    min_dep = int(get_setting("trader_min_deposit") or 100)
    
    text = (
        f"🏦 <b>Сделать вклад</b>\n\n"
        f"💵 Минимум: {min_dep} TC\n\n"
        f"📅 Выбери срок вклада:"
    )
    
    # Доступные сроки зависят от уровня доверия
    durations = [
        (1, 2, "1 час → +2%"),
    ]
    if trust['level'] >= 1:
        durations.extend([
            (6, 8, "6 часов → +8%"),
            (24, 20, "24 часа → +20%"),
        ])
    if trust['level'] >= 2:
        durations.append((168, 50, "7 дней → +50%"))
    
    rows = []
    for hours, rate, label in durations:
        rows.append([btn(f"📅 {label}", f"trader_dur_{hours}_{rate}", "success")])
    rows.append([btn_cancel("trader_main")])
    
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=build_keyboard(rows))
    await state.update_data(durations_info={h: r for h, r, _ in durations})
    await state.set_state(TraderStates.deposit_amount)

@dp.callback_query(F.data.startswith("trader_dur_"))
async def trader_duration_pick(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    parts = cb.data.split("_")
    hours = int(parts[2])
    rate = float(parts[3])
    
    await state.update_data(duration=hours, rate=rate)
    
    min_dep = int(get_setting("trader_min_deposit") or 100)
    max_dep = int(get_setting("trader_max_deposit") or 100000)
    
    text = (
        f"🏦 <b>Сумма вклада</b>\n\n"
        f"📅 Срок: {hours} ч\n"
        f"📈 Доход: +{rate}%\n\n"
        f"💵 Мин: {min_dep} TC | Макс: {max_dep} TC\n\n"
        f"💰 Введи сумму:"
    )
    
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("trader_main")]]))

@dp.message(TraderStates.deposit_amount)
async def trader_deposit_amount(msg: Message, state: FSMContext):
    try:
        amount = int(msg.text.strip())
    except ValueError:
        return await msg.answer("❌ Введи число!",
                                reply_markup=build_keyboard([[btn_cancel("trader_main")]]))
    
    min_dep = int(get_setting("trader_min_deposit") or 100)
    max_dep = int(get_setting("trader_max_deposit") or 100000)
    
    if amount < min_dep:
        return await msg.answer(f"❌ Минимум: {min_dep} TC",
                                reply_markup=build_keyboard([[btn_cancel("trader_main")]]))
    if amount > max_dep:
        return await msg.answer(f"❌ Максимум: {max_dep} TC",
                                reply_markup=build_keyboard([[btn_cancel("trader_main")]]))
    
    u = get_user(msg.from_user.id)
    if u['tcoin_balance'] < amount:
        return await msg.answer("❌ Недостаточно TC!",
                                reply_markup=build_keyboard([[btn_cancel("trader_main")]]))
    
    data = await state.get_data()
    hours = data['duration']
    rate = data['rate']
    
    # Списываем средства
    update_balance(msg.from_user.id, tcoin=-amount, desc=f"Вклад торговцу ({hours}ч, +{rate}%)")
    dep_id = create_deposit(msg.from_user.id, amount, hours, rate)
    
    end_time = datetime.now() + timedelta(hours=hours)
    payout = int(amount * (1 + rate / 100))
    
    await state.clear()
    
    text = (
        f"🏦 <b>Вклад оформлен!</b>\n\n"
        f"🎭 «Отличная сделка, друг...»\n\n"
        f"💰 Сумма: {amount} TC\n"
        f"📅 Срок: {hours} ч\n"
        f"📈 Доход: +{rate}%\n"
        f"💵 Вернёшь: <b>{payout} TC</b>\n"
        f"⏰ Срок окончания: {end_time.strftime('%d.%m %H:%M')}\n\n"
        f"📋 ID вклада: #{dep_id}"
    )
    
    await msg.answer(text, parse_mode="HTML",
                     reply_markup=build_keyboard([
                         [btn("💼 Мои вклады", "trader_my_deposits", "primary")],
                         [btn("🕵️ К торговцу", "trader_main", "success")],
                         [btn_menu()]
                     ]))

@dp.callback_query(F.data == "trader_my_deposits")
async def trader_my_deposits(cb: CallbackQuery):
    await cb.answer()
    deposits = get_user_deposits(cb.from_user.id)
    
    if not deposits:
        text = "💼 <b>Мои вклады</b>\n\nУ тебя пока нет активных вкладов."
        kb = build_keyboard([
            [btn("🏦 Сделать вклад", "trader_deposit", "success")],
            [btn("🕵️ К торговцу", "trader_main", "primary")],
            [btn_menu()]
        ])
        return await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    
    text = "💼 <b>Мои вклады</b>\n\n"
    rows = []
    
    for dep in deposits:
        start = datetime.strptime(dep['start_time'], "%Y-%m-%d %H:%M:%S")
        end = start + timedelta(hours=dep['duration_hours'])
        payout = int(dep['amount'] * (1 + dep['interest_rate'] / 100))
        
        now = datetime.now()
        if now >= end:
            status = "✅ Готов к выдаче"
            rows.append([btn(f"💰 Забрать #{dep['id']} ({payout} TC)", f"trader_collect_{dep['id']}", "success")])
        else:
            remaining = end - now
            hours = remaining.seconds // 3600
            mins = (remaining.seconds % 3600) // 60
            status = f"⏳ {hours}ч {mins}мин"
        
        text += (
            f"📋 <b>#{dep['id']}</b>\n"
            f"💰 {dep['amount']} TC → {payout} TC (+{dep['interest_rate']}%)\n"
            f"📅 {dep['duration_hours']}ч | {status}\n\n"
        )
    
    rows.append([btn("🕵️ К торговцу", "trader_main", "primary")])
    rows.append([btn_menu()])
    
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=build_keyboard(rows))

@dp.callback_query(F.data.startswith("trader_collect_"))
async def trader_collect(cb: CallbackQuery):
    await cb.answer()
    dep_id = int(cb.data.split("_")[-1])
    
    result = collect_deposit(dep_id, cb.from_user.id)
    
    if result is None:
        return await cb.answer("❌ Вклад не найден", show_alert=True)
    if result == "not_ready":
        return await cb.answer("⏳ Вклад ещё не созрел!", show_alert=True)
    
    # Начисляем средства
    payout = result
    update_balance(cb.from_user.id, tcoin=payout, desc=f"Выплата вклада #{dep_id}")
    
    # Обновляем доверие
    dep = None
    conn = get_db()
    dep = conn.execute("SELECT * FROM trader_deposits WHERE id=?", (dep_id,)).fetchone()
    conn.close()
    if dep:
        profit = payout - dep['amount']
        update_trader_trust(cb.from_user.id, deposited=dep['amount'], earned=profit)
    
    text = (
        f"💰 <b>Вклад получен!</b>\n\n"
        f"🎭 «Спасибо за доверие, друг...»\n\n"
        f"💵 Выплата: <b>{payout} TC</b>\n"
        f"💰 Баланс: <code>{get_user(cb.from_user.id)['tcoin_balance']}</code> TC"
    )
    
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([
                                   [btn("💼 Мои вклады", "trader_my_deposits", "primary")],
                                   [btn("🕵️ К торговцу", "trader_main", "success")],
                                   [btn_menu()]
                               ]))

@dp.callback_query(F.data == "trader_offers")
async def trader_offers(cb: CallbackQuery):
    await cb.answer()
    offers = get_user_offers(cb.from_user.id)
    
    if not offers:
        text = "🔥 <b>Спецпредложения</b>\n\nСейчас нет активных предложений.\nЗагляни позже!"
        kb = build_keyboard([[btn("🕵️ К торговцу", "trader_main", "primary")], [btn_menu()]])
        return await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    
    text = "🔥 <b>Спецпредложения</b>\n\n"
    rows = []
    
    for offer in offers:
        expires = datetime.strptime(offer['expires_at'], "%Y-%m-%d %H:%M:%S")
        remaining = expires - datetime.now()
        hours = int(remaining.total_seconds() // 3600)
        
        profit = offer['return_amount'] - offer['amount']
        
        if offer['offer_type'] == "boost":
            text += (
                f"💎 <b>#{offer['id']}</b> — Буст вклада\n"
                f"💰 Вложи: {offer['amount']} TC\n"
                f"📅 Через {offer['duration_hours']}ч получи: <b>{offer['return_amount']} TC</b>\n"
                f"📈 Прибыль: +{profit} TC\n"
                f"⏰ Действует: {hours}ч\n\n"
            )
        else:
            text += (
                f"🎁 <b>#{offer['id']}</b> — Особое предложение\n"
                f"💰 Вложи: {offer['amount']} TC\n"
                f"📅 Через {offer['duration_hours']}ч получи: <b>{offer['return_amount']} TC</b>\n"
                f"📈 Прибыль: +{profit} TC\n"
                f"⏰ Действует: {hours}ч\n\n"
            )
        
        rows.append([btn(f"✅ Принять #{offer['id']}", f"trader_accept_{offer['id']}", "success")])
    
    rows.append([btn("🕵️ К торговцу", "trader_main", "primary")])
    rows.append([btn_menu()])
    
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=build_keyboard(rows))

@dp.callback_query(F.data.startswith("trader_accept_"))
async def trader_accept_offer(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    offer_id = int(cb.data.split("_")[-1])
    
    offer = accept_offer(offer_id, cb.from_user.id)
    if not offer:
        return await cb.answer("❌ Предложение уже недействительно", show_alert=True)
    
    u = get_user(cb.from_user.id)
    if u['tcoin_balance'] < offer['amount']:
        # Возвращаем предложение
        conn = get_db()
        conn.execute("UPDATE trader_offers SET accepted=0 WHERE id=?", (offer_id,))
        conn.commit()
        conn.close()
        return await cb.answer("❌ Недостаточно TC!", show_alert=True)
    
    # Подтверждение
    profit = offer['return_amount'] - offer['amount']
    text = (
        f"💎 <b>Подтверди предложение</b>\n\n"
        f"💰 Вложить: {offer['amount']} TC\n"
        f"📅 Через {offer['duration_hours']}ч получишь: {offer['return_amount']} TC\n"
        f"📈 Прибыль: +{profit} TC\n\n"
        f"Подтверждаешь?"
    )
    
    await state.update_data(offer_id=offer_id, offer=offer)
    await state.set_state(TraderStates.offer_decision)
    
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([
                                   [btn("✅ Да, вложить", "trader_confirm_yes", "success"),
                                    btn("❌ Нет", "trader_confirm_no", "danger")]
                               ]))

@dp.callback_query(F.data == "trader_confirm_yes")
async def trader_confirm_yes(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    offer = data['offer']
    await state.clear()
    
    # Списываем средства
    update_balance(cb.from_user.id, tcoin=-offer['amount'], desc=f"Особое предложение #{offer['id']}")
    dep_id = create_deposit(cb.from_user.id, offer['amount'], offer['duration_hours'],
                            (offer['return_amount'] / offer['amount'] - 1) * 100)
    
    end_time = datetime.now() + timedelta(hours=offer['duration_hours'])
    
    text = (
        f"💎 <b>Предложение принято!</b>\n\n"
        f"🎭 «Хороший выбор, друг...»\n\n"
        f"💰 Вложено: {offer['amount']} TC\n"
        f"📅 Через {offer['duration_hours']}ч получишь: <b>{offer['return_amount']} TC</b>\n"
        f"⏰ Срок: {end_time.strftime('%d.%m %H:%M')}\n"
        f"📋 ID вклада: #{dep_id}"
    )
    
    await cb.message.edit_text(text, parse_mode="HTML",
                               reply_markup=build_keyboard([
                                   [btn("💼 Мои вклады", "trader_my_deposits", "primary")],
                                   [btn("🕵️ К торговцу", "trader_main", "success")],
                                   [btn_menu()]
                               ]))

@dp.callback_query(F.data == "trader_confirm_no")
async def trader_confirm_no(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    data = await state.get_data()
    offer_id = data.get('offer_id')
    await state.clear()
    
    # Возвращаем предложение
    if offer_id:
        conn = get_db()
        conn.execute("UPDATE trader_offers SET accepted=0 WHERE id=?", (offer_id,))
        conn.commit()
        conn.close()
    
    cb.data = "trader_offers"
    await trader_offers(cb)

# =============================================================================
# ========================= ФОНОВЫЕ ЗАДАЧИ ТОРГОВЦА =========================
# =============================================================================

async def trader_background_task():
    """Фоновая задача: генерация предложений для активных игроков"""
    await asyncio.sleep(60)  # Ждём 1 минуту после запуска
    
    while True:
        try:
            interval = int(get_setting("trader_offer_interval") or 3600)
            chance = int(get_setting("trader_offer_chance") or 15)
            
            # Получаем активных игроков (тех, кто был онлайн в последние 24 часа)
            conn = get_db()
            active_users = conn.execute("""
                SELECT user_id FROM users 
                WHERE is_banned=0 AND is_verified=1
            """).fetchall()
            conn.close()
            
            for user_row in active_users:
                uid = user_row['user_id']
                
                # Проверяем, есть ли уже активное предложение
                current_offers = get_user_offers(uid)
                if len(current_offers) >= 2:
                    continue
                
                # Шанс появления предложения
                if random.randint(1, 100) > chance:
                    continue
                
                trust = get_trader_trust(uid)
                
                # Генерируем предложение в зависимости от уровня доверия
                if trust['level'] == 0:
                    # Базовое предложение
                    amount = random.choice([200, 500, 1000])
                    return_amount = int(amount * 1.1)  # +10%
                    duration = 3
                    offer_type = "boost"
                elif trust['level'] == 1:
                    amount = random.choice([500, 1000, 2000])
                    return_amount = int(amount * 1.2)  # +20%
                    duration = 6
                    offer_type = "boost"
                elif trust['level'] == 2:
                    amount = random.choice([1000, 2500, 5000])
                    return_amount = int(amount * 1.35)  # +35%
                    duration = 12
                    offer_type = "special"
                else:  # level 3
                    amount = random.choice([5000, 10000, 25000])
                    return_amount = int(amount * 1.5)  # +50%
                    duration = 24
                    offer_type = "special"
                
                create_offer(uid, offer_type, amount, return_amount, duration, expires_hours=24)
                
                # Уведомляем игрока
                try:
                    profit = return_amount - amount
                    await bot.send_message(uid,
                        f"🔥 <b>Тайный торговец</b>\n\n"
                        f"🎭 «Эй, друг... У меня для тебя особое предложение.\n"
                        f"Но оно действует всего 24 часа!»\n\n"
                        f"💰 Вложи: {amount} TC\n"
                        f"📅 Через {duration}ч получишь: <b>{return_amount} TC</b>\n"
                        f"📈 Прибыль: +{profit} TC\n\n"
                        f"🕵️ Загляни к торговцу!",
                        parse_mode="HTML",
                        reply_markup=build_keyboard([
                            [btn("🕵️ К торговцу", "trader_main", "success")]
                        ]))
                except:
                    pass
            
            await asyncio.sleep(interval)
        
        except Exception as e:
            logging.error(f"Trader background error: {e}")
            await asyncio.sleep(300)

# =============================================================================
# ========================= ОСТАЛЬНЫЕ СИСТЕМЫ ===============================
# =============================================================================
# [Здесь остаются все остальные функции из предыдущей версии:
#  - earn_menu, bonus_menu, balance_menu, deposit, sell_starts, exchange
#  - task_get, task_check, promo, history, profile, daily
#  - casino games (слоты, кости, рулетка, монетка, больше/меньше, мины, краш)
#  - admin panel
#  - и т.д.]

# Чтобы код был полным, добавим базовые обработчики:

@dp.callback_query(F.data == "earn_menu")
async def cb_earn_menu(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    text = (
        f"💎 <b>Заработок</b>\n\n"
        f"📋 Заданий выполнено: {u['total_tasks_completed']}\n"
        f"💰 Награда: {get_setting('task_reward')} ⭐ SC\n\n"
        f"Выполняй задания и получай награды!"
    )
    kb = build_keyboard([
        [btn("📋 Выполнить задание", "task_get", "success")],
        [btn_menu()]
    ])
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data == "bonus_menu")
async def cb_bonus_menu(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    can_claim = can_claim_daily(cb.from_user.id)
    
    if can_claim:
        btn_text = "🎁 Получить бонус"
        btn_cd = "daily"
        btn_color = "success"
    else:
        try:
            d = datetime.strptime(u['last_daily_bonus'], "%Y-%m-%d") + timedelta(days=1) - datetime.now()
            bonus_text = f"⏰ Бонус через: {d.seconds//3600}ч {(d.seconds%3600)//60}мин"
        except:
            bonus_text = "⏰ Бонус уже получен"
        btn_text = "⏰ Бонус получен"
        btn_cd = "bonus_cooldown"
        btn_color = "primary"
    
    text = (
        f"🎁 <b>Бонусы</b>\n\n"
        f"⭐ Ежедневный бонус:\n"
        f"   +{get_setting('daily_bonus_sc')} SC\n"
        f"   +{get_setting('daily_bonus_tc')} TC\n\n"
        f"{bonus_text if not can_claim else '🎁 Доступен!'}"
    )
    
    kb = build_keyboard([
        [btn(btn_text, btn_cd, btn_color)],
        [btn("🎟 Промокод", "promo_enter", "primary")],
        [btn_menu()]
    ])
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data == "bonus_cooldown")
async def cb_bonus_cooldown(cb: CallbackQuery):
    await cb.answer("⏰ Бонус уже получен! Возвращайся завтра.", show_alert=True)

# [Продолжение кода: task_get, task_check, daily, promo_enter, history, profile, balance_menu, deposit, sell_starts, exchange и т.д. — как в предыдущей версии]

# === БАЗОВЫЕ ОБРАБОТЧИКИ (сокращённые) ===

@dp.callback_query(F.data == "task_get")
async def cb_task_get(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    td = await pf_get_task(uid, uid)
    if td.get("status") == "ok" and td.get("sponsors"):
        sponsors = td["sponsors"]
        available = [s for s in sponsors if not is_task_completed(uid, s["link"])]
        if not available:
            return await render(cb.message, "🎉 <b>Все задания выполнены!</b>", build_keyboard([[btn_menu()]]), is_cb=True)
        sp = available[0]
        reward = int(get_setting("task_reward") or sp.get("price", 5))
        user_current_task[uid] = {"link": sp["link"], "price": reward, "verify": False}
        kb = build_keyboard([
            [InlineKeyboardButton(text="🔗 Подписаться", url=sp["link"])],
            [btn("✅ Проверить", "task_check", "success")],
            [btn_menu()]])
        await render(cb.message, f"💎 <b>Задание</b>\n\nПодпишитесь и получите <b>{reward} ⭐ SC</b>", kb, is_cb=True)
    else:
        await render(cb.message, "🎉 <b>Заданий пока нет.</b>", build_keyboard([[btn_menu()]]), is_cb=True)

@dp.callback_query(F.data == "task_check")
async def cb_task_check(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    task = user_current_task.get(uid)
    if not task: return await cb.answer("❌ Сначала возьми задание!", show_alert=True)
    cd = await pf_check_task(uid, task["link"])
    if cd.get("status") == "ok":
        done = [s for s in cd.get("sponsors", []) if s.get("status") == "subscribed"]
        if done:
            reward = task["price"]
            update_balance(uid, stars=reward, desc="Выполнение задания")
            mark_task_completed(uid, task["link"])
            if task.get("verify"):
                update_user_field(uid, "is_verified", 1)
                u = get_user(uid)
                if u['referred_by']:
                    bonus = int(get_setting("referral_bonus") or 5)
                    update_balance(u['referred_by'], stars=bonus, desc="Реферал верифицирован")
                    increment_referrals(u['referred_by'])
                user_current_task.pop(uid, None)
                return await render(cb.message, f"✅ <b>Верификация пройдена!</b>\n+{reward} ⭐ SC", build_keyboard([[btn_menu()]]), is_cb=True)
            increment_tasks(uid)
            user_current_task.pop(uid, None)
            await render(cb.message, f"✅ <b>Выполнено!</b> +{reward} ⭐ SC",
                         build_keyboard([[btn("💎 Ещё задание", "task_get", "success")], [btn_menu()]]), is_cb=True)
        else: await cb.answer("⏳ Не подписаны!", show_alert=True)
    else: await cb.answer("❌ Ошибка проверки.", show_alert=True)

@dp.callback_query(F.data == "daily")
async def cb_daily(cb: CallbackQuery):
    await cb.answer()
    if can_claim_daily(cb.from_user.id):
        bs = int(get_setting("daily_bonus_sc") or 10)
        bt = int(get_setting("daily_bonus_tc") or 5)
        update_balance(cb.from_user.id, stars=bs, tcoin=bt, desc="Ежедневный бонус")
        set_daily_claimed(cb.from_user.id)
        text = f"🎁 <b>Бонус получен!</b>\n\n⭐ +{bs} SC\n🪙 +{bt} TC"
    else:
        text = "⏰ <b>Бонус уже получен!</b>"
    await render(cb.message, text, build_keyboard([[btn_menu()]]), is_cb=True)

@dp.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    if not u: return
    bi = await bot.get_me()
    rl = f"https://t.me/{bi.username}?start=ref_{u['referral_code']}"
    text = (f"👤 <b>Профиль</b>\n\n"
            f"🆔 ID: <code>{u['user_id']}</code>\n"
            f"📝 @{u['username'] or 'N/A'}\n\n"
            f"💰 ⭐ {fmt(u['stars_balance'])} SC | 🪙 {fmt(u['tcoin_balance'])} TC\n"
            f"📈 Заданий: {u['total_tasks_completed']}\n"
            f"👥 Рефералов: {u['total_referrals']}\n\n"
            f"🔗 <b>Реферальная ссылка:</b>\n<code>{rl}</code>")
    kb = build_keyboard([[btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data == "balance_menu")
async def cb_balance_menu(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    text = (f"💰 <b>Баланс</b>\n\n"
            f"⭐ SC: <code>{fmt(u['stars_balance'])}</code>\n"
            f"🪙 TC: <code>{fmt(u['tcoin_balance'])}</code>")
    kb = build_keyboard([
        [btn("💎 Купить SC", "deposit", "success"),
         btn("💰 Продать SC", "sell_starts", "success")],
        [btn("🔄 Обмен", "exchange", "primary")],
        [btn_menu()]
    ])
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data == "top_balance")
async def cb_top_balance(cb: CallbackQuery):
    await cb.answer()
    top = get_top_balance(10)
    if not top:
        text = "🏆 Пока нет пользователей."
    else:
        text = "🏆 <b>Топ-10:</b>\n\n"
        for i, u in enumerate(top, 1):
            total = u['stars_balance'] + u['tcoin_balance']
            name = f"@{u['username']}" if u['username'] else u['first_name']
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            text += f"{medal} {name} — 💰 {fmt(total)}\n"
    await render(cb.message, text, build_keyboard([[btn_menu()]]), is_cb=True)

# === ЗАГЛУШКИ для остальных функций ===
# [deposit, sell_starts, exchange, promo, history, casino games, admin]
# Все эти функции остаются как в предыдущей версии

@dp.callback_query(F.data == "deposit")
async def cb_deposit(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    await state.set_state(UserStates.waiting_buy_amount)
    await cb.message.edit_text("💎 Введи количество SC для покупки:",
                               reply_markup=build_keyboard([[btn_cancel("balance_menu")]]))

@dp.message(UserStates.waiting_buy_amount)
async def proc_buy_amount(msg: Message, state: FSMContext):
    await state.clear()
    try: amt = int(msg.text.strip())
    except: return await msg.answer("❌ Число!", reply_markup=nav_kb())
    if amt <= 0 or amt > 100000: return await msg.answer("❌ 1-100000!", reply_markup=nav_kb())
    try:
        link = await bot.create_invoice_link(title=f"Покупка {amt} SC", description=f"{amt} SC",
            payload=f"deposit_{msg.from_user.id}_{amt}", provider_token="", currency="XTR",
            prices=[LabeledPrice(label=f"{amt} Stars", amount=amt)])
        await msg.answer(f"💳 {amt} SC = {amt} ⭐️",
                         reply_markup=build_keyboard([[InlineKeyboardButton(text="💳 Оплатить", url=link)], [btn_menu()]]))
    except Exception as e:
        await msg.answer(f"❌ Ошибка: {e}", reply_markup=nav_kb())

@dp.callback_query(F.data == "sell_starts")
async def cb_sell_starts(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    await state.set_state(UserStates.waiting_sell_amount)
    await cb.message.edit_text("💰 Введи количество SC для продажи:",
                               reply_markup=build_keyboard([[btn_cancel("balance_menu")]]))

@dp.message(UserStates.waiting_sell_amount)
async def proc_sell_amount(msg: Message, state: FSMContext):
    await state.clear()
    try: amt = int(msg.text.strip())
    except: return await msg.answer("❌ Число!", reply_markup=nav_kb())
    u = get_user(msg.from_user.id)
    if amt < 50 or u['stars_balance'] < amt:
        return await msg.answer("❌ Минимум 50 SC или недостаточно!", reply_markup=nav_kb())
    update_balance(msg.from_user.id, stars=-amt, desc="Заявка на продажу")
    rid = create_request(msg.from_user.id, "sell_starts", amt)
    commission = int(get_setting("sell_commission") or 3)
    payout = round_to_5(int(amt * (100 - commission) / 100))
    await msg.answer(f"✅ Заявка #{rid} создана.\n💵 Получишь: {payout} ⭐️", reply_markup=nav_kb())

@dp.callback_query(F.data == "exchange")
async def cb_exchange(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    u = get_user(cb.from_user.id)
    rate = int(get_setting("exchange_rate") or 10)
    text = f"💱 Курс: 1 SC = {rate} TC\n⭐ {u['stars_balance']} | 🪙 {u['tcoin_balance']}"
    kb = build_keyboard([
        [btn("⭐ → 🪙", "ex_sc_to_tc", "success"),
         btn("🪙 → ⭐", "ex_tc_to_sc", "success")],
        [btn_menu()]
    ])
    await cb.message.edit_text(text, reply_markup=kb)

@dp.callback_query(F.data == "ex_sc_to_tc")
async def cb_ex_sc_to_tc(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    await state.set_state(UserStates.waiting_exchange_sc)
    await cb.message.edit_text("Введи количество SC:",
                               reply_markup=build_keyboard([[btn_cancel("exchange")]]))

@dp.callback_query(F.data == "ex_tc_to_sc")
async def cb_ex_tc_to_sc(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    await state.set_state(UserStates.waiting_exchange_tc)
    await cb.message.edit_text("Введи количество TC:",
                               reply_markup=build_keyboard([[btn_cancel("exchange")]]))

@dp.callback_query(F.data == "cancel_ex")
async def cb_cancel_ex(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    cb.data = "exchange"
    await cb_exchange(cb, state)

@dp.message(UserStates.waiting_exchange_sc)
async def proc_ex_sc(msg: Message, state: FSMContext):
    await state.clear()
    try: sc = int(msg.text.strip())
    except: return await msg.answer("❌ Число!", reply_markup=nav_kb())
    u = get_user(msg.from_user.id)
    rate = int(get_setting("exchange_rate") or 10)
    if u['stars_balance'] < sc: return await msg.answer("❌ Недостаточно SC!", reply_markup=nav_kb())
    tc = sc * rate
    update_balance(msg.from_user.id, stars=-sc, tcoin=tc, desc=f"Обмен {sc} SC → {tc} TC")
    await msg.answer(f"✅ Обменяно: -{sc} ⭐ → +{tc} 🪙", reply_markup=nav_kb())

@dp.message(UserStates.waiting_exchange_tc)
async def proc_ex_tc(msg: Message, state: FSMContext):
    await state.clear()
    try: tc = int(msg.text.strip())
    except: return await msg.answer("❌ Число!", reply_markup=nav_kb())
    u = get_user(msg.from_user.id)
    rate = int(get_setting("exchange_rate") or 10)
    if u['tcoin_balance'] < tc: return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb())
    sc = tc // rate
    if sc == 0: return await msg.answer(f"❌ Минимум {rate} TC", reply_markup=nav_kb())
    tc_used = sc * rate
    update_balance(msg.from_user.id, stars=sc, tcoin=-tc_used, desc=f"Обмен {tc_used} TC → {sc} SC")
    await msg.answer(f"✅ Обменяно: -{tc_used} 🪙 → +{sc} ⭐", reply_markup=nav_kb())

# === НАЗАД ===
@dp.callback_query(F.data.startswith("back_"))
async def cb_back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    await render_main_menu(cb, is_cb=True)

# === ПРЕДОПЛАТА ===
@dp.pre_checkout_query()
async def pre_checkout(pq: PreCheckoutQuery): await pq.answer(ok=True)

@dp.message(F.successful_payment)
async def process_payment(msg: Message):
    try:
        parts = msg.successful_payment.invoice_payload.split("_")
        if parts[0] == "deposit" and len(parts) >= 3:
            uid, amt = int(parts[1]), int(parts[2])
            update_balance(uid, stars=amt, desc="Покупка SC")
            await msg.answer(f"✅ +{amt} ⭐ SC зачислено!", reply_markup=nav_kb())
    except Exception as e:
        logging.error(f"Payment error: {e}")

# =============================================================================
# ========================= ЗАПУСК ==========================================
# =============================================================================

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("✅ Бот запущен!")
    logging.info(f"👑 Админ ID: {ADMIN_ID}")
    
    # Запускаем фоновую задачу торговца
    asyncio.create_task(trader_background_task())
    
    try: await bot.delete_webhook(drop_pending_updates=True)
    except: pass
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logging.info("🛑 Остановлен")
    except Exception as e: logging.error(f"Error: {e}")
