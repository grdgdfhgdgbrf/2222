# =============================================================================
# TELEGRAM БОТ — ФИНАЛЬНАЯ ВЕРСИЯ (ИСПРАВЛЕНО)
# =============================================================================

import asyncio
import logging
import random
import sqlite3
import re
import html
import aiohttp
import string
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional, Any, List

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardButton,
    InlineKeyboardMarkup, LabeledPrice, PreCheckoutQuery
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

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
    "deposit_enabled": "1", "withdraw_enabled": "1",
    "games_enabled": "1", "transfer_enabled": "1",
    "verification_required": "1", "min_withdraw": "50",
    "sell_commission": "3",
    "task_reward": "5",
    "lose_chance_slots": "0", "lose_chance_dice": "0",
    "lose_chance_darts": "0", "lose_chance_basket": "0",
    "lose_chance_football": "0", "lose_chance_roulette": "0",
    "lose_chance_coin": "0", "lose_chance_hilo": "0",
    "lose_chance_mines": "0", "lose_chance_crash": "0",
}

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
user_current_task: Dict[int, Dict] = {}
api_cache: Dict[str, Tuple] = {}

NEAR_MISS = [
    "🔥 Почти! Ещё чуть-чуть...",
    "💫 Удача рядом! Попробуй ещё!",
    "🎯 Миллиметры до победы!",
    "✨ В следующий раз точно повезёт!",
    "🌟 Фортуна уже смотрит на тебя!",
]

# =============================================================================
# ========================= РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ ============================
# =============================================================================

# ✅ ИСПРАВЛЕНО: используем re.compile() с re.IGNORECASE
RE_TRANSFER = re.compile(r"^перевод\s+(\S+)\s+(\d+)$", re.IGNORECASE)
RE_SLOTS = re.compile(r"^слоты\s+\d+$", re.IGNORECASE)
RE_DICE = re.compile(r"^кости\s+(число|чет|чёт|больше|меньше|б|м)\s+\d+\s+\S+$", re.IGNORECASE)
RE_DARTS = re.compile(r"^дротик\s+(попадание|промах)\s+\d+$", re.IGNORECASE)
RE_BASKET = re.compile(r"^баскет\s+(попадание|промах)\s+\d+$", re.IGNORECASE)
RE_FOOTBALL = re.compile(r"^футбол\s+(попадание|промах)\s+\d+$", re.IGNORECASE)
RE_ROULETTE = re.compile(r"^рул\s+(цвет|чет|чёт|половина|число|дюжина)\s+\d+\s+\S+$", re.IGNORECASE)
RE_COIN = re.compile(r"^мон\s+\d+\s+(о|р)$", re.IGNORECASE)
RE_HILO = re.compile(r"^(больше|меньше)\s+\d+$", re.IGNORECASE)
RE_MINES = re.compile(r"^мины\s+\d+\s+\d+$", re.IGNORECASE)
RE_CRASH = re.compile(r"^краш\s+\d+\s+\d+(\.\d+)?$", re.IGNORECASE)
RE_ADMIN_CMD = re.compile(r"^(stats|requests|addstars|addtcoin|reset|ban|unban|makeadmin|setrate|setminbet|setmaxbet|userstats|createpromo|deletepromo|createcheck|deletecheck|approve|reject)\s*", re.IGNORECASE)

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
    waiting_setting_value = State()

class UserStates(StatesGroup):
    waiting_promo = State()
    waiting_withdraw_amount = State()
    waiting_exchange_sc = State()
    waiting_exchange_tc = State()
    waiting_deposit_amount = State()
    waiting_check_create_sc = State()
    waiting_check_create_tc = State()
    waiting_check_create_act = State()

class MinesStates(StatesGroup):
    playing = State()

# =============================================================================
# ========================= ЦВЕТНЫЕ КНОПКИ ==================================
# =============================================================================

def cbtn(text: str, callback_data: str = None, style: str = "primary", url: str = None) -> InlineKeyboardButton:
    """Цветная кнопка через model_validate"""
    data = {"text": text, "style": style}
    if url:
        data["url"] = url
    else:
        data["callback_data"] = callback_data
    return InlineKeyboardButton.model_validate(data)

def btn_menu(): return cbtn("🏠 Главное меню", "back_menu", "primary")
def btn_profile(): return cbtn("🔙 Профиль", "profile", "primary")
def btn_admin(): return cbtn("👑 Админ-панель", "admin", "danger")
def btn_games(): return cbtn("🎮 К играм", "games_menu", "success")
def btn_balance(): return cbtn("💰 Баланс", "balance_menu", "success")
def btn_cancel(target="back_menu"): return cbtn("❌ Отмена", target, "danger")

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
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, is_verified INTEGER DEFAULT 0)""")
    c.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
    c.execute("""CREATE TABLE IF NOT EXISTS completed_tasks (
        user_id INTEGER, task_link TEXT, completed_at TEXT DEFAULT CURRENT_TIMESTAMP,
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
        user_id INTEGER, check_code TEXT, activated_at TEXT DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (user_id, check_code))""")
    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, type TEXT,
        amount INTEGER, description TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, req_type TEXT,
        amount INTEGER, status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP, processed_at TEXT)""")
    for key, value in DEFAULT_SETTINGS.items():
        c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()

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
                 (uid, uname, fname, rcode, ref_by, 1 if uid == ADMIN_ID else 0, verified))
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
                     (uid, 'stars', stars, desc or ("⭐️ SC" if stars > 0 else "Списание SC")))
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

def get_check(code: str):
    conn = get_db()
    r = conn.execute("SELECT * FROM checks WHERE code=? AND activations_left > 0", (code,)).fetchone()
    conn.close()
    return r

def use_check(uid: int, code: str) -> Tuple[bool, str, Optional[dict]]:
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

def list_checks(limit=20):
    conn = get_db()
    rows = conn.execute("SELECT * FROM checks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return rows

def delete_check(code: str):
    conn = get_db()
    c = conn.execute("DELETE FROM checks WHERE code=?", (code,))
    conn.execute("DELETE FROM used_checks WHERE check_code=?", (code,))
    conn.commit()
    conn.close()
    return c.rowcount > 0

def list_user_checks(uid: int, limit=20):
    conn = get_db()
    rows = conn.execute("SELECT * FROM checks WHERE created_by=? ORDER BY created_at DESC LIMIT ?", (uid, limit)).fetchall()
    conn.close()
    return rows

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

init_db()

# =============================================================================
# ========================= PIARFLOW API ====================================
# =============================================================================

async def pf_get_task(uid, cid):
    ck = f"task_{uid}"
    if ck in api_cache and datetime.now().timestamp() - api_cache[ck][1] < 60:
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
    return int(round(n / 5) * 5)

def should_lose(game_key: str) -> bool:
    chance = int(float(get_setting(f"lose_chance_{game_key}") or 0))
    if chance <= 0: return False
    return random.randint(1, 100) <= chance

def parse_bet(parts: list, idx: int) -> Tuple[Optional[int], Optional[str]]:
    if len(parts) <= idx: return None, "⚠️ Укажите ставку!"
    try:
        bet = int(parts[idx])
    except ValueError:
        return None, "❌ Ставка — число!"
    mn, mx = int(get_setting("min_bet") or 10), int(get_setting("max_bet") or 50000)
    if bet < mn: return None, f"❌ Мин. ставка: {mn} 🪙"
    if bet > mx: return None, f"❌ Макс. ставка: {mx} 🪙"
    return bet, None

def check_bal(uid, bet):
    u = get_user(uid)
    return bool(u and u['tcoin_balance'] >= bet)

def dice_emoji(emoji, val):
    if emoji == "🎰":
        if val >= 60: return "⭐️⭐️⭐️ ДЖЕКПОТ!"
        if val >= 40: return "🍒🍒🍒 Отличный выигрыш!"
        if val >= 20: return "🍋🍒🍋 Почти!"
        return "🍋🍋🍋 Не повезло"
    if emoji == "🎲": return f"{({1:'⚀',2:'⚁',3:'⚂',4:'⚃',5:'⚄',6:'⚅'}).get(val, val)} ({val})"
    if emoji == "🎯":
        if val == 6: return "🎯 ЯБЛОЧКО!"
        if val >= 4: return "🎯 Попадание!"
        return "💨 Мимо!"
    if emoji == "🏀":
        if val == 5: return "🏀 СЛЭМ-ДАНК!"
        if val >= 3: return "🏀 Почти!"
        return "🏀 Промах"
    if emoji == "⚽":
        if val >= 4: return "⚽ ГООООЛ!"
        if val == 3: return "⚽ В штангу!"
        return "⚽ Вратарь спас!"
    return f"🎮 Результат: {val}"

async def game_result(msg, emoji, val, bet, won, mult, name):
    adm = is_admin(msg.from_user.id)
    kb = nav_kb(adm, [[btn_games()]])
    re = dice_emoji(emoji, val)
    if won:
        pay = int(bet * mult)
        update_balance(msg.from_user.id, tcoin=pay, desc=f"Выигрыш {name}")
        await msg.answer(f"🎮 <b>{name}</b>\n\n{re}\n\n🎉 <b>ПОБЕДА!</b>\n\n💰 Ставка: {bet} 🪙\n📈 ×{mult}\n✅ Выигрыш: <b>{pay} 🪙</b>", parse_mode="HTML", reply_markup=kb)
    else:
        near = random.choice(NEAR_MISS)
        await msg.answer(f"🎮 <b>{name}</b>\n\n{re}\n\n😔 <b>Проигрыш</b>\n\n{near}\nПотеряно: {bet} 🪙", parse_mode="HTML", reply_markup=kb)

async def game_lose(msg, name, bet):
    adm = is_admin(msg.from_user.id)
    kb = nav_kb(adm, [[btn_games()]])
    near = random.choice(NEAR_MISS)
    await msg.answer(f"🎮 <b>{name}</b>\n\n😔 <b>Проигрыш</b>\n\n{near}\nПотеряно: {bet} 🪙", parse_mode="HTML", reply_markup=kb)

async def game_ready(msg):
    u = get_user(msg.from_user.id)
    if not u:
        create_user(msg.from_user.id, msg.from_user.username or "user", msg.from_user.first_name or "User", f"ref_{msg.from_user.id}", None, 1)
        u = get_user(msg.from_user.id)
    kb = nav_kb()
    if u['is_banned']: await msg.answer("❌ Заблокированы.", reply_markup=kb); return False
    if not is_verified(msg.from_user.id): await msg.answer("⚠️ Верификация: start", reply_markup=kb); return False
    if get_setting("games_enabled") != "1": await msg.answer("❌ Игры отключены.", reply_markup=kb); return False
    return True

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
    uid = target.from_user.id if hasattr(target, 'from_user') else target.message.from_user.id
    u = get_user(uid)
    if not u: return
    fn = target.from_user.first_name if hasattr(target, 'from_user') else target.message.from_user.first_name
    text = (f"👋 <b>Добро пожаловать, {fn}!</b>\n\n"
            f"⭐️ SC: <code>{fmt(u['stars_balance'])}</code>\n"
            f"🪙 TC: <code>{fmt(u['tcoin_balance'])}</code>")
    kb = build_keyboard([
        [cbtn("💰 Баланс", "balance_menu", "success"),
         cbtn("💎 Заработать", "task_get", "success")],
        [cbtn("🎮 Игры", "games_menu", "primary"),
         cbtn("🎫 Мои чеки", "my_checks", "primary")],
        [cbtn("👤 Профиль", "profile", "primary"),
         cbtn("❓ Помощь", "help", "primary")]])
    if u['is_admin']:
        kb = build_keyboard([
            [cbtn("💰 Баланс", "balance_menu", "success"),
             cbtn("💎 Заработать", "task_get", "success")],
            [cbtn("🎮 Игры", "games_menu", "primary"),
             cbtn("🎫 Мои чеки", "my_checks", "primary")],
            [cbtn("👤 Профиль", "profile", "primary"),
             cbtn("❓ Помощь", "help", "primary")],
            [cbtn("👑 Админ-панель", "admin", "danger")]])
    await render(target, text, kb, is_cb)

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
            [cbtn("🔗 Подписаться", style="success", url=sp["link"])],
            [cbtn("✅ Проверить подписку", "task_check", "success")],
            [btn_menu()]])
    else:
        update_user_field(uid, "is_verified", 1)
        await render_main_menu(target, is_cb)
        return
    await render(target, text, kb, is_cb)

# =============================================================================
# ========================= СТАРТ ===========================================
# =============================================================================

@dp.message(Command("start"))
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
        if chk['sc_amount'] > 0: update_balance(uid, stars=chk['sc_amount'], desc=f"Чек: {code}")
        if chk['tc_amount'] > 0: update_balance(uid, tcoin=chk['tc_amount'], desc=f"Чек: {code}")
        text = f"✅ <b>Чек активирован!</b>\n\n🎫 Код: <code>{code}</code>\n\n"
        if chk['sc_amount'] > 0: text += f"⭐️ +{chk['sc_amount']} SC\n"
        if chk['tc_amount'] > 0: text += f"🪙 +{chk['tc_amount']} TC\n"
        return await msg.answer(text, parse_mode="HTML", reply_markup=nav_kb(is_admin(uid)))

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
            try: await bot.send_message(ref_by, f"🎉 <b>Друг зарегистрировался!</b>\n+{bonus} ⭐️ SC", parse_mode="HTML")
            except: pass
    u = get_user(uid)
    if not u['is_verified'] and get_setting("verification_required") == "1":
        return await render_verify(msg, is_cb=False)
    await render_main_menu(msg, is_cb=False)

# =============================================================================
# ========================= ПОМОЩЬ ==========================================
# =============================================================================

@dp.callback_query(F.data == "help")
async def cb_help(cb: CallbackQuery):
    await cb.answer()
    bi = await bot.get_me()
    text = (f"❓ <b>Помощь</b>\n\n"
            f"🤖 <b>{bi.first_name}</b> — реферальный бот с играми.\n\n"
            f"💫 <b>Starts Coin (SC)</b> — основная валюта\n"
            f"🪙 <b>T Coin (TC)</b> — игровая валюта\n\n"
            f"💱 <b>Курс:</b> 1 ⭐️ SC = {get_setting('exchange_rate')} 🪙 TC\n\n"
            f"Выберите раздел:")
    kb = build_keyboard([
        [cbtn("📖 О боте", "help_about", "primary")],
        [cbtn("💰 Валюты и обмен", "help_currency", "primary")],
        [cbtn("🎮 Гайд по играм", "help_games", "success")],
        [cbtn("💎 Как заработать", "help_earn", "success")],
        [cbtn("🎫 Чеки", "help_checks", "primary")],
        [cbtn("👥 Рефералы", "help_ref", "primary")],
        [cbtn("🛡 Правила", "help_rules", "danger")],
        [btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data.startswith("help_"))
async def cb_help_section(cb: CallbackQuery):
    await cb.answer()
    section = cb.data.replace("help_", "")
    rate = get_setting("exchange_rate") or "10"
    task_reward = get_setting("task_reward") or "5"
    commission = get_setting("sell_commission") or "3"
    bi = await bot.get_me()

    texts = {
        "about": (f"📖 <b>О боте</b>\n\n"
                  f"🤖 <b>{bi.first_name}</b> — реферальный бот с играми.\n\n"
                  f"<b>Возможности:</b>\n"
                  f"💎 Заработок — задания\n"
                  f"🎮 Игры — 10 видов\n"
                  f"💱 Обмен — SC ↔ TC\n"
                  f"💳 Покупка SC — за ⭐️ Stars\n"
                  f"💰 Продажа SC — за ⭐️ Stars\n"
                  f"🎫 Чеки — подарочные коды\n"
                  f"👥 Рефералы — бонусы за друзей\n\n"
                  f"<b>Команды (без /):</b>\n"
                  f"• <code>баланс</code> — баланс\n"
                  f"• <code>топ</code> — топ игроков\n"
                  f"• <code>профиль</code> — профиль\n"
                  f"• <code>помощь</code> — справка\n"
                  f"• <code>обмен</code> — обмен\n"
                  f"• <code>заработать</code> — задания\n"
                  f"• <code>игры</code> — список игр"),
        "currency": (f"💰 <b>Валюты и обмен</b>\n\n"
                     f"⭐️ <b>Starts Coin (SC)</b>\n"
                     f"• Покупка: 1 SC = 1 ⭐️ Star\n"
                     f"• Продажа: 1 SC = 1 ⭐️ (комиссия {commission}%)\n"
                     f"• Округление до 5 ⭐️\n\n"
                     f"🪙 <b>T Coin (TC)</b>\n"
                     f"• Игровая валюта\n"
                     f"• Получается обменом SC → TC\n\n"
                     f"💱 <b>Обмен:</b>\n"
                     f"• 1 ⭐️ SC = {rate} 🪙 TC\n"
                     f"• {rate} 🪙 TC = 1 ⭐️ SC\n\n"
                     f"<b>Как обменять:</b>\n"
                     f"1️⃣ <code>баланс</code> → 🔄 Обмен\n"
                     f"2️⃣ Выберите направление\n"
                     f"3️⃣ Введите количество"),
        "games": (f"🎮 <b>Гайд по играм</b>\n\n"
                  f"<b>Все игры на 🪙 TC. Команды БЕЗ /</b>\n\n"
                  f"🎰 <b>слоты [сумма]</b> — ×10, ×2\n\n"
                  f"🎲 <b>кости [режим] [сумма] [параметр]</b>\n"
                  f"• <code>кости число 100 3</code> — ×6\n"
                  f"• <code>кости чет 100 чет</code> — ×2\n"
                  f"• <code>кости больше 100 б</code> — ×2\n\n"
                  f"🎯 <b>дротик [событие] [сумма]</b>\n"
                  f"• <code>дротик попадание 100</code> — ×1.9\n"
                  f"• <code>дротик промах 100</code> — ×1.9\n\n"
                  f"🏀 <b>баскет [событие] [сумма]</b>\n"
                  f"• <code>баскет попадание 100</code> — ×1.9\n"
                  f"• <code>баскет промах 100</code> — ×1.9\n\n"
                  f"⚽ <b>футбол [событие] [сумма]</b>\n"
                  f"• <code>футбол попадание 100</code> — ×1.9\n"
                  f"• <code>футбол промах 100</code> — ×1.9\n\n"
                  f"🎡 <b>рул [тип] [сумма] [параметр]</b>\n"
                  f"• <code>рул цвет 100 к</code> — ×2\n"
                  f"• <code>рул число 100 17</code> — ×36\n\n"
                  f"🪙 <b>мон [сумма] [о/р]</b> — ×2\n\n"
                  f"📊 <b>больше/меньше [сумма]</b> — ×1.9\n\n"
                  f"💣 <b>мины [сумма] [1-5]</b> — сетка 5×5\n"
                  f"🚀 <b>краш [сумма] [множитель]</b> — авто-вывод\n\n"
                  f"💡 Начинайте с малых ставок!"),
        "earn": (f"💎 <b>Как заработать</b>\n\n"
                 f"<b>Способы получения ⭐️ SC:</b>\n\n"
                 f"1️⃣ <b>Задания</b>\n"
                 f"• <b>💎 Заработать</b>\n"
                 f"• Подпишитесь на канал\n"
                 f"• <b>✅ Проверить</b>\n"
                 f"• Получите <b>{task_reward} ⭐️ SC</b>\n"
                 f"• Задания не повторяются!\n\n"
                 f"2️⃣ <b>Ежедневный бонус</b>\n"
                 f"• В профиле <b>🎁 Бонус</b>\n\n"
                 f"3️⃣ <b>Промокоды</b>\n"
                 f"• В профиле <b>🎟 Промокод</b>\n\n"
                 f"4️⃣ <b>Чеки</b>\n"
                 f"• Активируйте по ссылке\n\n"
                 f"5️⃣ <b>Рефералы</b>\n"
                 f"• Поделитесь ссылкой\n"
                 f"• Получите {get_setting('referral_bonus')} ⭐️ SC\n\n"
                 f"6️⃣ <b>Покупка</b>\n"
                 f"• <code>баланс</code> → 💎 Купить SC\n"
                 f"• 1 SC = 1 ⭐️ Star"),
        "checks": (f"🎫 <b>Чеки</b>\n\n"
                   f"Чеки — подарочные коды.\n\n"
                   f"<b>Создание:</b>\n"
                   f"1️⃣ <code>баланс</code> → 🎫 Создать чек\n"
                   f"2️⃣ Укажите ⭐️ SC\n"
                   f"3️⃣ Укажите 🪙 TC\n"
                   f"4️⃣ Укажите активаций\n"
                   f"5️⃣ Средства заморозятся\n"
                   f"6️⃣ Получите ссылку\n\n"
                   f"<b>Активация:</b>\n"
                   f"• ТОЛЬКО по ссылке\n"
                   f"• Формат: <code>t.me/bot?start=check_КОД</code>\n"
                   f"• Один чек = одна активация\n\n"
                   f"<b>Мои чеки:</b>\n"
                   f"• <code>баланс</code> → 🎫 Мои чеки"),
        "ref": (f"👥 <b>Рефералы</b>\n\n"
                f"Ваша ссылка в <b>👤 Профиль</b>\n\n"
                f"💰 <b>Бонус:</b> {get_setting('referral_bonus')} ⭐️ SC\n\n"
                f"<b>Как работает:</b>\n"
                f"1️⃣ Друг переходит по ссылке\n"
                f"2️⃣ Подписывается на спонсора\n"
                f"3️⃣ Вы получаете бонус\n\n"
                f"📊 Статистика в профиле"),
        "rules": (f"🛡 <b>Правила</b>\n\n"
                  f"⚠️ <b>Запрещено:</b>\n"
                  f"• Боты\n"
                  f"• Накрутка рефералов\n"
                  f"• Мультиаккаунты\n"
                  f"• Нарушение = бан\n\n"
                  f"💰 <b>Финансы:</b>\n"
                  f"• Мин. ставка: {get_setting('min_bet')} 🪙\n"
                  f"• Макс. ставка: {get_setting('max_bet')} 🪙\n"
                  f"• Мин. продажа: {get_setting('min_withdraw')} ⭐️\n"
                  f"• Комиссия: {commission}%\n\n"
                  f"🎮 <b>Игры:</b>\n"
                  f"• Результаты честные\n"
                  f"• Кубики — нативные Telegram\n\n"
                  f"📞 <b>Поддержка:</b>\n"
                  f"• По вопросам — к админу"),
    }
    text = texts.get(section, "Раздел не найден")
    kb = build_keyboard([
        [cbtn("🔙 К разделам", "help", "primary")],
        [btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

@dp.message(F.text.lower().in_(["помощь", "помогите", "help", "гайд", "справка"]))
async def cmd_help_text(msg: Message):
    kb = build_keyboard([
        [cbtn("📖 О боте", "help_about", "primary")],
        [cbtn("💰 Валюты и обмен", "help_currency", "primary")],
        [cbtn("🎮 Гайд по играм", "help_games", "success")],
        [cbtn("💎 Как заработать", "help_earn", "success")],
        [cbtn("🎫 Чеки", "help_checks", "primary")],
        [cbtn("👥 Рефералы", "help_ref", "primary")],
        [cbtn("🛡 Правила", "help_rules", "danger")],
        [btn_menu()]])
    await msg.answer("❓ <b>Помощь</b>\n\nВыберите раздел:", parse_mode="HTML", reply_markup=kb)

# =============================================================================
# ========================= БАЛАНС ==========================================
# =============================================================================

@dp.callback_query(F.data == "balance_menu")
async def cb_balance_menu(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    text = (f"💰 <b>Ваш баланс</b>\n\n"
            f"⭐️ Starts Coin: <code>{fmt(u['stars_balance'])}</code>\n"
            f"🪙 T Coin: <code>{fmt(u['tcoin_balance'])}</code>\n\n"
            f"💱 Курс: 1 ⭐️ SC = {get_setting('exchange_rate')} 🪙 TC")
    kb = build_keyboard([
        [cbtn("💎 Купить SC", "deposit", "success"),
         cbtn("💰 Продать SC", "sell_starts", "success")],
        [cbtn("🔄 Обмен валют", "exchange", "primary")],
        [cbtn("🎫 Создать чек", "check_create_user", "primary"),
         cbtn("🎫 Мои чеки", "my_checks", "primary")],
        [cbtn("🏆 Топ по балансу", "top_balance", "primary")],
        [btn_profile()], [btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

@dp.message(F.text.lower().in_(["баланс", "balance"]))
async def cmd_balance_text(msg: Message):
    u = get_user(msg.from_user.id)
    if not u: return
    text = (f"💰 <b>Ваш баланс</b>\n\n"
            f"⭐️ Starts Coin: <code>{fmt(u['stars_balance'])}</code>\n"
            f"🪙 T Coin: <code>{fmt(u['tcoin_balance'])}</code>\n\n"
            f"💱 Курс: 1 ⭐️ SC = {get_setting('exchange_rate')} 🪙 TC")
    kb = build_keyboard([
        [cbtn("💎 Купить SC", "deposit", "success"),
         cbtn("💰 Продать SC", "sell_starts", "success")],
        [cbtn("🔄 Обмен валют", "exchange", "primary")],
        [cbtn("🎫 Создать чек", "check_create_user", "primary"),
         cbtn("🎫 Мои чеки", "my_checks", "primary")],
        [cbtn("🏆 Топ по балансу", "top_balance", "primary")],
        [btn_profile()], [btn_menu()]])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

# =============================================================================
# ========================= ТОП =============================================
# =============================================================================

@dp.callback_query(F.data == "top_balance")
async def cb_top_balance(cb: CallbackQuery):
    await cb.answer()
    top = get_top_balance(10)
    if not top:
        text = "🏆 <b>Топ по балансу</b>\n\nПока нет пользователей."
    else:
        text = "🏆 <b>Топ-10 по балансу:</b>\n\n"
        for i, u in enumerate(top, 1):
            total = u['stars_balance'] + u['tcoin_balance']
            name = f"@{u['username']}" if u['username'] else u['first_name']
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            text += f"{medal} {name}\n   ⭐️ {fmt(u['stars_balance'])} SC | 🪙 {fmt(u['tcoin_balance'])} TC\n   💰 Всего: {fmt(total)}\n\n"
    kb = build_keyboard([[btn_balance()], [btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

@dp.message(F.text.lower().in_(["топ", "top", "топ баланс"]))
async def cmd_top_text(msg: Message):
    top = get_top_balance(10)
    if not top:
        text = "🏆 <b>Топ по балансу</b>\n\nПока нет пользователей."
    else:
        text = "🏆 <b>Топ-10 по балансу:</b>\n\n"
        for i, u in enumerate(top, 1):
            total = u['stars_balance'] + u['tcoin_balance']
            name = f"@{u['username']}" if u['username'] else u['first_name']
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f"{i}.")
            text += f"{medal} {name}\n   ⭐️ {fmt(u['stars_balance'])} SC | 🪙 {fmt(u['tcoin_balance'])} TC\n   💰 Всего: {fmt(total)}\n\n"
    await msg.answer(text, parse_mode="HTML", reply_markup=nav_kb(is_admin(msg.from_user.id)))

# =============================================================================
# ========================= ПРОФИЛЬ =========================================
# =============================================================================

@dp.callback_query(F.data == "profile")
async def cb_profile(cb: CallbackQuery):
    await cb.answer()
    u = get_user(cb.from_user.id)
    if not u: return
    bi = await bot.get_me()
    rl = f"https://t.me/{bi.username}?start=ref_{u['referral_code']}"
    text = (f"👤 <b>Ваш профиль</b>\n\n"
            f"🆔 ID: <code>{u['user_id']}</code>\n"
            f"📝 @{u['username'] or 'N/A'}\n"
            f"👤 {u['first_name']}\n\n"
            f"💰 <b>Баланс:</b>\n"
            f"⭐️ Starts Coin: <code>{fmt(u['stars_balance'])}</code>\n"
            f"🪙 T Coin: <code>{fmt(u['tcoin_balance'])}</code>\n\n"
            f"📈 Заданий: {u['total_tasks_completed']}\n"
            f"👥 Приглашено: {u['total_referrals']}\n"
            f"📅 Регистрация: {u['created_at'][:10]}\n\n"
            f"🔗 <b>Реферальная ссылка:</b>\n<code>{rl}</code>\n"
            f"<i>+{get_setting('referral_bonus')} ⭐️ SC за друга</i>")
    kb = build_keyboard([
        [cbtn("🎁 Бонус", "daily", "success"),
         cbtn("🎟 Промокод", "promo_enter", "success")],
        [cbtn("📊 История", "history", "primary")],
        [btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

@dp.message(F.text.lower().in_(["профиль", "проф", "profile"]))
async def cmd_profile_text(msg: Message):
    u = get_user(msg.from_user.id)
    if not u: return
    bi = await bot.get_me()
    rl = f"https://t.me/{bi.username}?start=ref_{u['referral_code']}"
    text = (f"👤 <b>Ваш профиль</b>\n\n"
            f"🆔 ID: <code>{u['user_id']}</code>\n"
            f"📝 @{u['username'] or 'N/A'}\n"
            f"👤 {u['first_name']}\n\n"
            f"💰 <b>Баланс:</b>\n"
            f"⭐️ Starts Coin: <code>{fmt(u['stars_balance'])}</code>\n"
            f"🪙 T Coin: <code>{fmt(u['tcoin_balance'])}</code>\n\n"
            f"📈 Заданий: {u['total_tasks_completed']}\n"
            f"👥 Приглашено: {u['total_referrals']}\n\n"
            f"🔗 <b>Реферальная ссылка:</b>\n<code>{rl}</code>")
    kb = build_keyboard([
        [cbtn("🎁 Бонус", "daily", "success"),
         cbtn("🎟 Промокод", "promo_enter", "success")],
        [cbtn("📊 История", "history", "primary")],
        [btn_menu()]])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

# =============================================================================
# ========================= БОНУС ===========================================
# =============================================================================

@dp.callback_query(F.data == "daily")
async def cb_daily(cb: CallbackQuery):
    await cb.answer()
    if can_claim_daily(cb.from_user.id):
        bs = int(get_setting("daily_bonus_sc") or 10)
        bt = int(get_setting("daily_bonus_tc") or 5)
        update_balance(cb.from_user.id, stars=bs, tcoin=bt, desc="Ежедневный бонус")
        set_daily_claimed(cb.from_user.id)
        text = f"🎁 <b>Бонус получен!</b>\n\n⭐️ +{bs} SC\n🪙 +{bt} TC\n\nВозвращайтесь завтра!"
    else:
        u = get_user(cb.from_user.id)
        try:
            d = datetime.strptime(u['last_daily_bonus'], "%Y-%m-%d") + timedelta(days=1) - datetime.now()
            text = f"⏰ <b>Бонус уже получен!</b>\n\nСледующий через: {d.seconds//3600}ч {(d.seconds%3600)//60}мин"
        except: text = "⏰ Бонус уже получен."
    await render(cb.message, text, build_keyboard([[btn_profile()], [btn_menu()]]), is_cb=True)

# =============================================================================
# ========================= ПРОМОКОДЫ =======================================
# =============================================================================

@dp.callback_query(F.data == "promo_enter")
async def cb_promo_enter(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    await render(cb.message, "🎟 <b>Ввод промокода</b>\n\nОтправьте промокод сообщением.",
                 build_keyboard([[btn_cancel("cancel_promo")]]), is_cb=True)
    await state.set_state(UserStates.waiting_promo)

@dp.callback_query(F.data == "cancel_promo")
async def cb_cancel_promo(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    cb.data = "profile"
    await cb_profile(cb)

@dp.message(UserStates.waiting_promo)
async def process_promo(msg: Message, state: FSMContext):
    await state.clear()
    code = msg.text.strip().upper()
    promo = get_promo(code)
    kb_back = nav_kb(False, [btn_profile()])
    if not promo: return await msg.answer("❌ Промокод не найден.", reply_markup=kb_back)
    if promo['current_uses'] >= promo['max_uses']: return await msg.answer("❌ Промокод исчерпан.", reply_markup=kb_back)
    ok, st = use_promo(msg.from_user.id, code)
    if not ok:
        if st == "already_used": return await msg.answer("❌ Уже использован.", reply_markup=kb_back)
        return
    sr, tr = promo['stars_reward'], promo['tcoin_reward']
    if sr > 0 or tr > 0: update_balance(msg.from_user.id, stars=sr, tcoin=tr, desc=f"Промокод: {code}")
    text = f"✅ <b>Промокод активирован!</b>\n\n🎟 <code>{code}</code>\n\n"
    if sr > 0: text += f"⭐️ +{sr} SC\n"
    if tr > 0: text += f"🪙 +{tr} TC\n"
    await msg.answer(text, parse_mode="HTML", reply_markup=build_keyboard([[cbtn("🎟 Ввести ещё", "promo_enter", "success")], [btn_profile()], [btn_menu()]]))

# =============================================================================
# ========================= ИСТОРИЯ =========================================
# =============================================================================

@dp.callback_query(F.data == "history")
async def cb_history(cb: CallbackQuery):
    await cb.answer()
    txs = get_transactions(cb.from_user.id)
    if not txs: text = "📊 <b>История</b>\n\nПока нет операций."
    else:
        text = "📊 <b>Последние операции:</b>\n\n"
        for tx in txs:
            e = "🟢" if tx['amount'] > 0 else "🔴"
            c = "⭐️" if tx['type'] == "stars" else "🪙"
            s = "+" if tx['amount'] > 0 else ""
            text += f"{e} {s}{tx['amount']} {c} — <i>{tx['description']}</i>\n   <code>{tx['created_at']}</code>\n\n"
    await render(cb.message, text, build_keyboard([[btn_profile()], [btn_menu()]]), is_cb=True)

# =============================================================================
# ========================= ПЕРЕВОДЫ ========================================
# =============================================================================

# ✅ ИСПРАВЛЕНО: используем RE_TRANSFER
@dp.message(F.text.regexp(RE_TRANSFER))
async def cmd_transfer_text(msg: Message):
    if get_setting("transfer_enabled") != "1":
        return await msg.answer("❌ Переводы отключены.", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    match = RE_TRANSFER.match(msg.text)
    if not match: return
    arg, amount_str = match.group(1), match.group(2)
    tid = await resolve_user_id(arg)
    if not tid: return await msg.answer("❌ Пользователь не найден!\nФормат: <code>перевод @username 100</code>", parse_mode="HTML", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    try: amount = int(amount_str)
    except: return await msg.answer("❌ Сумма — число!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    if tid == msg.from_user.id: return await msg.answer("❌ Себе нельзя!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    if amount <= 0: return await msg.answer("❌ Сумма > 0!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    u = get_user(msg.from_user.id)
    if not u or u['tcoin_balance'] < amount: return await msg.answer("❌ Недостаточно TC!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    t = get_user(tid)
    if not t: return await msg.answer("❌ Получатель не найден!", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    update_balance(msg.from_user.id, tcoin=-amount, desc=f"Перевод → {tid}")
    update_balance(tid, tcoin=amount, desc=f"Перевод ← {msg.from_user.id}")
    await msg.answer(f"✅ Переведено <b>{amount} 🪙</b> → {tid}", parse_mode="HTML", reply_markup=nav_kb(is_admin(msg.from_user.id)))
    try: await bot.send_message(tid, f"💸 Вам перевели <b>{amount} 🪙</b> от @{msg.from_user.username or msg.from_user.id}!", parse_mode="HTML")
    except: pass

@dp.message(F.text.lower() == "перевод")
async def cmd_transfer_help(msg: Message):
    await msg.answer("💸 <b>Перевод T Coin</b>\n\nФормат:\n<code>перевод @username 100</code>\n<code>перевод 123456789 100</code>", parse_mode="HTML", reply_markup=nav_kb(is_admin(msg.from_user.id)))

# =============================================================================
# ========================= ЗАДАНИЯ =========================================
# =============================================================================

@dp.callback_query(F.data == "task_get")
async def cb_task_get(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    td = await pf_get_task(uid, uid)
    if td.get("status") == "ok" and td.get("sponsors"):
        sponsors = td["sponsors"]
        available = [s for s in sponsors if not is_task_completed(uid, s["link"])]
        if not available:
            await render(cb.message, "🎉 <b>Все задания выполнены!</b>\n\nЗагляните позже.",
                         build_keyboard([[btn_profile()], [btn_menu()]]), is_cb=True)
            return
        sp = available[0]
        reward = int(float(get_setting("task_reward") or sp.get("price", 5)))
        user_current_task[uid] = {"link": sp["link"], "price": reward, "verify": False}
        kb = build_keyboard([[cbtn("🔗 Подписаться", style="success", url=sp["link"])],
                             [cbtn("✅ Проверить", "task_check", "success")],
                             [btn_menu()]])
        await render(cb.message, f"💎 <b>Заработать</b>\n\nПодпишитесь и получите <b>{reward} ⭐️ SC</b>", kb, is_cb=True)
    else:
        await render(cb.message, "🎉 <b>Заданий пока нет.</b>", build_keyboard([[btn_profile()], [btn_menu()]]), is_cb=True)

@dp.callback_query(F.data == "task_check")
async def cb_task_check(cb: CallbackQuery):
    await cb.answer()
    uid = cb.from_user.id
    task = user_current_task.get(uid)
    if not task: return await cb.answer("❌ Сначала возьмите задание!", show_alert=True)
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
                return await render(cb.message, f"✅ <b>Верификация пройдена!</b>\n+{reward} ⭐️ SC",
                                    build_keyboard([[btn_menu()]]), is_cb=True)
            increment_tasks(uid)
            user_current_task.pop(uid, None)
            u = get_user(uid)
            await render(cb.message, f"✅ <b>Выполнено!</b> +{reward} ⭐️ SC\n📈 Всего заданий: {u['total_tasks_completed']}",
                         build_keyboard([[cbtn("💎 Ещё задание", "task_get", "success")], [btn_profile()], [btn_menu()]]), is_cb=True)
        else: await cb.answer("⏳ Не подписаны!", show_alert=True)
    else: await cb.answer("❌ Ошибка проверки.", show_alert=True)

@dp.message(F.text.lower().in_(["заработать", "задания", "задание"]))
async def cmd_task_text(msg: Message):
    u = get_user(msg.from_user.id)
    if not u: return
    td = await pf_get_task(msg.from_user.id, msg.from_user.id)
    if td.get("status") == "ok" and td.get("sponsors"):
        sponsors = td["sponsors"]
        available = [s for s in sponsors if not is_task_completed(msg.from_user.id, s["link"])]
        if not available:
            return await msg.answer("🎉 <b>Все задания выполнены!</b>", parse_mode="HTML", reply_markup=nav_kb(is_admin(msg.from_user.id)))
        sp = available[0]
        reward = int(float(get_setting("task_reward") or sp.get("price", 5)))
        user_current_task[msg.from_user.id] = {"link": sp["link"], "price": reward, "verify": False}
        kb = build_keyboard([[cbtn("🔗 Подписаться", style="success", url=sp["link"])],
                             [cbtn("✅ Проверить", "task_check", "success")],
                             [btn_menu()]])
        await msg.answer(f"💎 <b>Заработать</b>\n\nПодпишитесь и получите <b>{reward} ⭐️ SC</b>", parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer("🎉 <b>Заданий пока нет.</b>", parse_mode="HTML", reply_markup=nav_kb(is_admin(msg.from_user.id)))

# =============================================================================
# ========================= ОБМЕН ===========================================
# =============================================================================

@dp.callback_query(F.data == "exchange")
async def cb_exchange(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    u = get_user(cb.from_user.id)
    rate = int(float(get_setting("exchange_rate") or 10))
    text = (f"💱 <b>Обмен валют</b>\n\n💱 Курс: <code>1 ⭐️ SC = {rate} 🪙 TC</code>\n\n"
            f"⭐️ SC: <code>{fmt(u['stars_balance'])}</code>\n"
            f"🪙 TC: <code>{fmt(u['tcoin_balance'])}</code>\n\n"
            f"Выберите направление:")
    kb = build_keyboard([
        [cbtn("⭐️ SC → 🪙 TC", "ex_sc_to_tc", "success")],
        [cbtn("🪙 TC → ⭐️ SC", "ex_tc_to_sc", "success")],
        [btn_profile()], [btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data == "ex_sc_to_tc")
async def cb_ex_sc_to_tc(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    u = get_user(cb.from_user.id)
    rate = int(float(get_setting("exchange_rate") or 10))
    max_tc = u['stars_balance'] // rate if rate > 0 else 0
    text = f"💱 <b>SC → TC</b>\n\n⭐️ У вас: <code>{u['stars_balance']}</code> SC\n🪙 Можно получить: <code>{max_tc}</code> TC\n\nВведите количество SC для обмена:"
    kb = build_keyboard([[btn_cancel("cancel_ex")]])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await state.set_state(UserStates.waiting_exchange_sc)

@dp.callback_query(F.data == "ex_tc_to_sc")
async def cb_ex_tc_to_sc(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    u = get_user(cb.from_user.id)
    rate = int(float(get_setting("exchange_rate") or 10))
    max_sc = u['tcoin_balance'] // rate if rate > 0 else 0
    text = f"💱 <b>TC → SC</b>\n\n🪙 У вас: <code>{u['tcoin_balance']}</code> TC\n⭐️ Можно получить: <code>{max_sc}</code> SC\n\nВведите количество TC для обмена:"
    kb = build_keyboard([[btn_cancel("cancel_ex")]])
    await cb.message.edit_text(text, parse_mode="HTML", reply_markup=kb)
    await state.set_state(UserStates.waiting_exchange_tc)

@dp.callback_query(F.data == "cancel_ex")
async def cb_cancel_ex(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    cb.data = "exchange"
    await cb_exchange(cb, state)

@dp.message(UserStates.waiting_exchange_sc)
async def proc_ex_sc(msg: Message, state: FSMContext):
    await state.clear()
    kb_back = build_keyboard([[btn_balance()], [btn_menu()]])
    try: sc = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Введите число!", reply_markup=kb_back)
    if sc <= 0: return await msg.answer("❌ Количество > 0!", reply_markup=kb_back)
    u = get_user(msg.from_user.id)
    rate = int(float(get_setting("exchange_rate") or 10))
    cost = sc * rate
    if u['stars_balance'] < cost: return await msg.answer(f"❌ Недостаточно SC! Нужно {sc} SC.", reply_markup=kb_back)
    update_balance(msg.from_user.id, stars=-cost, tcoin=sc, desc=f"Обмен {cost} SC → {sc} TC")
    u = get_user(msg.from_user.id)
    await msg.answer(f"✅ <b>Обмен выполнен!</b>\n\n📉 -{cost} ⭐️ SC\n📈 +{sc} 🪙 TC\n\n⭐️ {u['stars_balance']}\n🪙 {u['tcoin_balance']}",
                     parse_mode="HTML", reply_markup=build_keyboard([[cbtn("💱 Ещё обмен", "exchange", "success")], [btn_balance()], [btn_menu()]]))

@dp.message(UserStates.waiting_exchange_tc)
async def proc_ex_tc(msg: Message, state: FSMContext):
    await state.clear()
    kb_back = build_keyboard([[btn_balance()], [btn_menu()]])
    try: tc = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Введите число!", reply_markup=kb_back)
    if tc <= 0: return await msg.answer("❌ Количество > 0!", reply_markup=kb_back)
    u = get_user(msg.from_user.id)
    rate = int(float(get_setting("exchange_rate") or 10))
    if u['tcoin_balance'] < tc: return await msg.answer(f"❌ Недостаточно TC!", reply_markup=kb_back)
    if rate == 0: return await msg.answer("❌ Курс не установлен!", reply_markup=kb_back)
    sc_got = tc // rate
    if sc_got == 0: return await msg.answer(f"❌ Слишком мало TC! Минимум {rate} TC.", reply_markup=kb_back)
    tc_used = sc_got * rate
    update_balance(msg.from_user.id, stars=sc_got, tcoin=-tc_used, desc=f"Обмен {tc_used} TC → {sc_got} SC")
    u = get_user(msg.from_user.id)
    await msg.answer(f"✅ <b>Обмен выполнен!</b>\n\n📉 -{tc_used} 🪙 TC\n📈 +{sc_got} ⭐️ SC\n\n⭐️ {u['stars_balance']}\n🪙 {u['tcoin_balance']}",
                     parse_mode="HTML", reply_markup=build_keyboard([[cbtn("💱 Ещё обмен", "exchange", "success")], [btn_balance()], [btn_menu()]]))

@dp.message(F.text.lower().in_(["обмен", "обменять", "exchange"]))
async def cmd_exchange_text(msg: Message):
    u = get_user(msg.from_user.id)
    if not u: return
    rate = int(float(get_setting("exchange_rate") or 10))
    text = (f"💱 <b>Обмен валют</b>\n\n💱 Курс: <code>1 ⭐️ SC = {rate} 🪙 TC</code>\n\n"
            f"⭐️ SC: <code>{fmt(u['stars_balance'])}</code>\n"
            f"🪙 TC: <code>{fmt(u['tcoin_balance'])}</code>")
    kb = build_keyboard([
        [cbtn("⭐️ SC → 🪙 TC", "ex_sc_to_tc", "success")],
        [cbtn("🪙 TC → ⭐️ SC", "ex_tc_to_sc", "success")],
        [btn_profile()], [btn_menu()]])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

# =============================================================================
# ========================= ПОКУПКА SC ======================================
# =============================================================================

@dp.callback_query(F.data == "deposit")
async def cb_deposit(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    if get_setting("deposit_enabled") != "1": return await cb.answer("❌ Покупка отключена", show_alert=True)
    u = get_user(cb.from_user.id)
    text = (f"💎 <b>Покупка Starts Coin</b>\n\n"
            f"💱 1 ⭐️ SC = 1 ⭐️ Telegram Star\n\n"
            f"⭐️ Ваш баланс: <code>{u['stars_balance']}</code> SC\n\n"
            f"Введите количество SC для покупки:")
    kb = build_keyboard([[btn_cancel("cancel_deposit")]])
    await render(cb.message, text, kb, is_cb=True)
    await state.set_state(UserStates.waiting_deposit_amount)

@dp.callback_query(F.data == "cancel_deposit")
async def cb_cancel_deposit(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    cb.data = "balance_menu"
    await cb_balance_menu(cb)

@dp.message(UserStates.waiting_deposit_amount)
async def proc_deposit_amount(msg: Message, state: FSMContext):
    await state.clear()
    kb_back = build_keyboard([[btn_balance()], [btn_menu()]])
    try: amt = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Введите число!", reply_markup=kb_back)
    if amt <= 0 or amt > 100000: return await msg.answer("❌ Сумма от 1 до 100000!", reply_markup=kb_back)
    try:
        link = await bot.create_invoice_link(title=f"Покупка {amt} SC", description=f"{amt} Starts Coin",
            payload=f"deposit_{msg.from_user.id}_{amt}", provider_token="", currency="XTR",
            prices=[LabeledPrice(label=f"{amt} Stars", amount=amt)])
        kb = build_keyboard([[cbtn("💳 Оплатить", style="success", url=link)], [btn_balance()], [btn_menu()]])
        await msg.answer(f"💳 <b>Оплата</b>\n\n⭐️ {amt} SC\n💰 Цена: <b>{amt} ⭐️</b> (1:1)", parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logging.error(f"Invoice error: {e}")
        await msg.answer("❌ Ошибка создания инвойса.", reply_markup=kb_back)

@dp.pre_checkout_query()
async def pre_checkout(pq: PreCheckoutQuery): await pq.answer(ok=True)

@dp.message(F.successful_payment)
async def process_payment(msg: Message):
    try:
        parts = msg.successful_payment.invoice_payload.split("_")
        if parts[0] == "deposit" and len(parts) >= 3:
            uid, amt = int(parts[1]), int(parts[2])
            update_balance(uid, stars=amt, desc="Покупка SC")
            rid = create_request(uid, "deposit", amt)
            update_request_status(rid, "approved")
            await msg.answer(f"✅ <b>Покупка успешна!</b>\n⭐️ +{amt} SC зачислено!", parse_mode="HTML",
                             reply_markup=nav_kb(is_admin(uid), [cbtn("💎 Ещё купить", "deposit", "success")]))
            try: await bot.send_message(ADMIN_ID, f"💰 Покупка: {uid} → {amt} SC", parse_mode="HTML")
            except: pass
    except Exception as e:
        logging.error(f"Payment error: {e}")
        await msg.answer("❌ Ошибка.", reply_markup=nav_kb(is_admin(msg.from_user.id)))

# =============================================================================
# ========================= ПРОДАЖА SC ======================================
# =============================================================================

@dp.callback_query(F.data == "sell_starts")
async def cb_sell_starts(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    if get_setting("withdraw_enabled") != "1": return await cb.answer("❌ Продажа отключена", show_alert=True)
    u = get_user(cb.from_user.id)
    commission = int(get_setting("sell_commission") or 3)
    mw = int(get_setting("min_withdraw") or 50)
    text = (f"💰 <b>Продажа Starts Coin</b>\n\n"
            f"⭐️ Ваш баланс: <code>{u['stars_balance']}</code> SC\n"
            f"💵 Минимум: {mw} SC\n"
            f"💸 Комиссия: {commission}%\n"
            f"💱 Курс: 1 SC = 1 ⭐️\n"
            f"🔢 Округление: до 5 ⭐️\n\n"
            f"Отправьте сумму продажи:")
    await render(cb.message, text, build_keyboard([[btn_cancel("cancel_sell")]]), is_cb=True)
    await state.set_state(UserStates.waiting_withdraw_amount)

@dp.callback_query(F.data == "cancel_sell")
async def cb_cancel_sell(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    cb.data = "balance_menu"
    await cb_balance_menu(cb)

@dp.message(UserStates.waiting_withdraw_amount)
async def process_sell_amount(msg: Message, state: FSMContext):
    await state.clear()
    retry_kb = build_keyboard([[cbtn("💰 Попробовать ещё", "sell_starts", "success")], [btn_profile()], [btn_menu()]])
    try: amount = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!", reply_markup=retry_kb)
    mw = int(get_setting("min_withdraw") or 50)
    if amount < mw: return await msg.answer(f"❌ Минимум: {mw} SC", reply_markup=retry_kb)
    u = get_user(msg.from_user.id)
    if not u or u['stars_balance'] < amount: return await msg.answer("❌ Недостаточно SC!", reply_markup=retry_kb)
    update_balance(msg.from_user.id, stars=-amount, desc="Заявка на продажу SC (заморозка)")
    rid = create_request(msg.from_user.id, "sell_starts", amount)
    commission = int(get_setting("sell_commission") or 3)
    payout_raw = int(amount * (100 - commission) / 100)
    payout = round_to_5(payout_raw)
    await msg.answer(f"✅ Заявка #{rid} на продажу {amount} SC создана.\n💵 Вы получите: <b>{payout} ⭐️</b>\n💸 Комиссия: {commission}%",
                     parse_mode="HTML", reply_markup=nav_kb(False, [btn_profile()]))
    try:
        await bot.send_message(ADMIN_ID,
            f"📤 Заявка на продажу #{rid}\n👤 {msg.from_user.id}\n⭐️ {amount} SC → ⭐️ {payout}\n<code>approve {rid}</code> / <code>reject {rid}</code>",
            parse_mode="HTML")
    except: pass

# =============================================================================
# ========================= ЧЕКИ ============================================
# =============================================================================

@dp.callback_query(F.data == "check_create_user")
async def cb_check_create_user(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.clear()
    u = get_user(cb.from_user.id)
    text = (f"🎫 <b>Создание чека</b>\n\n"
            f"⭐️ Ваш баланс: <code>{u['stars_balance']}</code> SC\n"
            f"🪙 Ваш баланс: <code>{u['tcoin_balance']}</code> TC\n\n"
            f"Введите количество ⭐️ SC для чека (0 если не нужно):")
    kb = build_keyboard([[btn_cancel("cancel_ck_user")]])
    await render(cb.message, text, kb, is_cb=True)
    await state.set_state(UserStates.waiting_check_create_sc)
    await state.update_data(check_creator="user")

@dp.callback_query(F.data == "cancel_ck_user")
async def cb_cancel_ck_user(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    cb.data = "balance_menu"
    await cb_balance_menu(cb)

@dp.message(UserStates.waiting_check_create_sc)
async def proc_ck_user_sc(msg: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("check_creator") != "user": return
    try: sc = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!")
    if sc < 0: return await msg.answer("❌ >= 0!")
    u = get_user(msg.from_user.id)
    if u['stars_balance'] < sc: return await msg.answer("❌ Недостаточно SC!")
    await state.update_data(check_sc=sc)
    await msg.answer("🪙 Сколько TC в чеке? (0 если не нужно)")
    await state.set_state(UserStates.waiting_check_create_tc)

@dp.message(UserStates.waiting_check_create_tc)
async def proc_ck_user_tc(msg: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("check_creator") != "user": return
    try: tc = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!")
    if tc < 0: return await msg.answer("❌ >= 0!")
    u = get_user(msg.from_user.id)
    if u['tcoin_balance'] < tc: return await msg.answer("❌ Недостаточно TC!")
    await state.update_data(check_tc=tc)
    await msg.answer("🔢 Сколько активаций?")
    await state.set_state(UserStates.waiting_check_create_act)

@dp.message(UserStates.waiting_check_create_act)
async def proc_ck_user_act(msg: Message, state: FSMContext):
    data = await state.get_data()
    if data.get("check_creator") != "user": return
    try: act = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!")
    if act <= 0 or act > 1000: return await msg.answer("❌ От 1 до 1000!")
    sc = data.get("check_sc", 0)
    tc = data.get("check_tc", 0)
    if sc == 0 and tc == 0: return await msg.answer("❌ Укажите хотя бы одну валюту!")
    await state.clear()
    u = get_user(msg.from_user.id)
    if sc > 0: update_balance(msg.from_user.id, stars=-sc * act, desc=f"Создание чека (SC ×{act})")
    if tc > 0: update_balance(msg.from_user.id, tcoin=-tc * act, desc=f"Создание чека (TC ×{act})")
    code = generate_code()
    if create_check(code, sc * act, tc * act, act, msg.from_user.id):
        bi = await bot.get_me()
        await msg.answer(
            f"✅ <b>Чек создан!</b>\n\n🎫 Код: <code>{code}</code>\n⭐️ {sc * act} SC | 🪙 {tc * act} TC\n🔢 Активаций: {act}\n💵 За каждую: ⭐️{sc} 🪙{tc}\n\n"
            f"<b>Ссылка для активации:</b>\n<code>https://t.me/{bi.username}?start=check_{code}</code>",
            parse_mode="HTML",
            reply_markup=build_keyboard([[cbtn("➕ Ещё чек", "check_create_user", "success")], [btn_balance()], [btn_menu()]])
        )
    else:
        await msg.answer("❌ Ошибка создания чека!", reply_markup=build_keyboard([[btn_balance()], [btn_menu()]]))

@dp.callback_query(F.data == "my_checks")
async def cb_my_checks(cb: CallbackQuery):
    await cb.answer()
    cs = list_user_checks(cb.from_user.id)
    if not cs:
        text = "🎫 <b>Мои чеки</b>\n\nУ вас нет созданных чеков."
    else:
        text = "🎫 <b>Ваши чеки:</b>\n\n"
        bi = await bot.get_me()
        for c in cs:
            text += f"🎫 <code>{c['code']}</code>\n   ⭐️ {c['sc_amount']} SC | 🪙 {c['tc_amount']} TC\n   🔢 Осталось: {c['activations_left']}\n"
            text += f"   🔗 <code>t.me/{bi.username}?start=check_{c['code']}</code>\n\n"
    kb = build_keyboard([
        [cbtn("➕ Создать чек", "check_create_user", "success")],
        [btn_balance()], [btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

# =============================================================================
# ========================= ИГРЫ МЕНЮ =======================================
# =============================================================================

@dp.callback_query(F.data == "games_menu")
async def cb_games_menu(cb: CallbackQuery):
    await cb.answer()
    if get_setting("games_enabled") != "1": return await cb.answer("❌ Игры отключены", show_alert=True)
    text = (f"🎮 <b>Игровой зал</b>\n\n"
            f"<b>🎲 Команды в чате (БЕЗ /):</b>\n"
            f"• <code>слоты 100</code>\n"
            f"• <code>кости число 100 3</code>\n"
            f"• <code>дротик попадание 100</code>\n"
            f"• <code>дротик промах 100</code>\n"
            f"• <code>баскет попадание 100</code>\n"
            f"• <code>баскет промах 100</code>\n"
            f"• <code>футбол попадание 100</code>\n"
            f"• <code>футбол промах 100</code>\n"
            f"• <code>мины 100 3</code>\n"
            f"• <code>краш 100 2.0</code>\n\n"
            f"💵 Ставки: {get_setting('min_bet') or '10'}–{get_setting('max_bet') or '50000'} 🪙\n\n"
            f"💡 Подробный гайд: <b>❓ Помощь → 🎮 Гайд по играм</b>")
    await render(cb.message, text, build_keyboard([[btn_profile()], [btn_menu()]]), is_cb=True)

@dp.message(F.text.lower().in_(["игры", "игры меню", "games"]))
async def cmd_games_text(msg: Message):
    text = (f"🎮 <b>Игровой зал</b>\n\n"
            f"<b>🎲 Команды в чате (БЕЗ /):</b>\n"
            f"• <code>слоты 100</code>\n"
            f"• <code>дротик попадание 100</code>\n"
            f"• <code>дротик промах 100</code>\n"
            f"• <code>баскет попадание 100</code>\n"
            f"• <code>баскет промах 100</code>\n"
            f"• <code>футбол попадание 100</code>\n"
            f"• <code>футбол промах 100</code>\n"
            f"• <code>мины 100 3</code>\n"
            f"• <code>краш 100 2.0</code>\n\n"
            f"💵 Ставки: {get_setting('min_bet') or '10'}–{get_setting('max_bet') or '50000'} 🪙")
    await msg.answer(text, parse_mode="HTML", reply_markup=nav_kb(is_admin(msg.from_user.id)))

# =============================================================================
# ========================= ИГРЫ ============================================
# =============================================================================

# ✅ ИСПРАВЛЕНО: используем RE_SLOTS вместо F.text.regexp(..., ignore_case=True)
@dp.message(F.text.regexp(RE_SLOTS))
async def g_slots(msg: Message):
    if not await game_ready(msg): return
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    parts = msg.text.split()
    bet, err = parse_bet(parts, 1)
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно TC!", reply_markup=ke)
    if should_lose("slots"):
        update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Слоты")
        return await game_lose(msg, "Слоты", bet)
    update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Слоты")
    dm = await msg.answer_dice(emoji="🎰")
    v = dm.dice.value
    if v == 1: await game_result(msg, "🎰", v, bet, True, 10, "Слоты")
    elif v <= 10: await game_result(msg, "🎰", v, bet, True, 2, "Слоты")
    else: await game_result(msg, "🎰", v, bet, False, 0, "Слоты")

@dp.message(F.text.regexp(RE_DICE))
async def g_dice(msg: Message):
    if not await game_ready(msg): return
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    parts = msg.text.split()
    if len(parts) < 4:
        return await msg.answer("🎲 <b>Режимы:</b>\n<code>кости число 100 3</code> (×6)\n<code>кости чет 100 чет</code> (×2)\n<code>кости больше 100 б</code> (×2)", parse_mode="HTML", reply_markup=ke)
    mode = parts[1].lower()
    bet, err = parse_bet(parts, 2)
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    if should_lose("dice"):
        update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Кости")
        return await game_lose(msg, f"Кости ({mode})", bet)
    update_balance(msg.from_user.id, tcoin=-bet, desc="Кости")
    dm = await msg.answer_dice(emoji="🎲")
    v = dm.dice.value
    param = parts[3].lower()
    if mode == "число":
        try: tgt = int(param)
        except: return await msg.answer("❌ Число 1-6!", reply_markup=ke)
        if not 1 <= tgt <= 6: return await msg.answer("❌ Число 1-6!", reply_markup=ke)
        await game_result(msg, "🎲", v, bet, v == tgt, 6, f"Кости ({tgt})")
    elif mode in ["чет", "чёт"]:
        if param in ["чет", "чёт", "ч"]: we = True
        elif param in ["нечет", "нечёт", "нч", "н"]: we = False
        else: return await msg.answer("❌ чет/нечет", reply_markup=ke)
        await game_result(msg, "🎲", v, bet, (v % 2 == 0) == we, 2, f"Кости ({'чёт' if we else 'нечёт'})")
    elif mode in ["больше", "меньше", "б", "м"]:
        if param in ["больше", "б"]: wh = True
        elif param in ["меньше", "м"]: wh = False
        else: return await msg.answer("❌ б/м", reply_markup=ke)
        await game_result(msg, "🎲", v, bet, (v >= 4) == wh, 2, f"Кости ({'больше' if wh else 'меньше'})")

@dp.message(F.text.regexp(RE_DARTS))
async def g_darts(msg: Message):
    if not await game_ready(msg): return
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    parts = msg.text.split()
    if len(parts) < 3: return await msg.answer("⚠️ Формат: <code>дротик попадание 100</code> или <code>дротик промах 100</code>", parse_mode="HTML", reply_markup=ke)
    event = parts[1].lower()
    bet, err = parse_bet(parts, 2)
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    if should_lose("darts"):
        update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Дротик")
        return await game_lose(msg, f"Дротик ({event})", bet)
    update_balance(msg.from_user.id, tcoin=-bet, desc="Дротик")
    dm = await msg.answer_dice(emoji="🎯")
    v = dm.dice.value
    hit = v >= 4
    if event == "попадание": won = hit
    else: won = not hit
    await game_result(msg, "🎯", v, bet, won, 1.9, f"Дротик ({event})")

@dp.message(F.text.regexp(RE_BASKET))
async def g_basket(msg: Message):
    if not await game_ready(msg): return
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    parts = msg.text.split()
    if len(parts) < 3: return await msg.answer("⚠️ Формат: <code>баскет попадание 100</code> или <code>баскет промах 100</code>", parse_mode="HTML", reply_markup=ke)
    event = parts[1].lower()
    bet, err = parse_bet(parts, 2)
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    if should_lose("basket"):
        update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Баскет")
        return await game_lose(msg, f"Баскет ({event})", bet)
    update_balance(msg.from_user.id, tcoin=-bet, desc="Баскет")
    dm = await msg.answer_dice(emoji="🏀")
    v = dm.dice.value
    hit = v == 5
    if event == "попадание": won = hit
    else: won = not hit
    await game_result(msg, "🏀", v, bet, won, 1.9, f"Баскет ({event})")

@dp.message(F.text.regexp(RE_FOOTBALL))
async def g_foot(msg: Message):
    if not await game_ready(msg): return
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    parts = msg.text.split()
    if len(parts) < 3: return await msg.answer("⚠️ Формат: <code>футбол попадание 100</code> или <code>футбол промах 100</code>", parse_mode="HTML", reply_markup=ke)
    event = parts[1].lower()
    bet, err = parse_bet(parts, 2)
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    if should_lose("football"):
        update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Футбол")
        return await game_lose(msg, f"Футбол ({event})", bet)
    update_balance(msg.from_user.id, tcoin=-bet, desc="Футбол")
    dm = await msg.answer_dice(emoji="⚽")
    v = dm.dice.value
    hit = v >= 4
    if event == "попадание": won = hit
    else: won = not hit
    await game_result(msg, "⚽", v, bet, won, 1.9, f"Футбол ({event})")

@dp.message(F.text.regexp(RE_ROULETTE))
async def g_roulette(msg: Message):
    if not await game_ready(msg): return
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    parts = msg.text.split()
    if len(parts) < 4:
        return await msg.answer("🎡 <b>Рулетка:</b>\n<code>рул цвет 100 к</code>\n<code>рул число 100 17</code>", parse_mode="HTML", reply_markup=ke)
    mode = parts[1].lower()
    bet, err = parse_bet(parts, 2)
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    if should_lose("roulette"):
        update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Рулетка")
        return await game_lose(msg, f"Рулетка ({mode})", bet)
    update_balance(msg.from_user.id, tcoin=-bet, desc=f"Рулетка {mode}")
    num = random.randint(0, 36)
    reds = {1,3,5,7,9,12,14,16,18,19,21,23,25,27,30,32,34,36}
    p = parts[3].lower()
    won, mult = False, 0
    if mode == "цвет":
        if p in ["к","красное"]: won, mult = num in reds, 2
        elif p in ["ч","черное","чёрное"]: won, mult = num != 0 and num not in reds, 2
        elif p in ["з","зеро"]: won, mult = num == 0, 14
        else: return await msg.answer("❌ к/ч/з", reply_markup=ke)
    elif mode in ["чет", "чёт"]:
        if p in ["чет","чёт","ч"]: won, mult = num != 0 and num % 2 == 0, 2
        elif p in ["нечет","нечёт","нч","н"]: won, mult = num != 0 and num % 2 != 0, 2
        else: return await msg.answer("❌ чет/нечет", reply_markup=ke)
    elif mode == "половина":
        if p in ["низ","н"]: won, mult = 1 <= num <= 18, 2
        elif p in ["верх","в"]: won, mult = 19 <= num <= 36, 2
        else: return await msg.answer("❌ верх/низ", reply_markup=ke)
    elif mode == "число":
        try: tgt = int(p)
        except: return await msg.answer("❌ 0-36!", reply_markup=ke)
        if not 0 <= tgt <= 36: return await msg.answer("❌ 0-36!", reply_markup=ke)
        won, mult = num == tgt, 36
    elif mode == "дюжина":
        try: d = int(p)
        except: return await msg.answer("❌ 1/2/3!", reply_markup=ke)
        if d == 1: won, mult = 1 <= num <= 12, 3
        elif d == 2: won, mult = 13 <= num <= 24, 3
        elif d == 3: won, mult = 25 <= num <= 36, 3
        else: return await msg.answer("❌ 1/2/3!", reply_markup=ke)
    else: return await msg.answer("❌ Режимы: цвет, чет, половина, число, дюжина", reply_markup=ke)
    ce = "🟢" if num == 0 else ("🔴" if num in reds else "⚫")
    cn = "Зеро" if num == 0 else ("Красное" if num in reds else "Чёрное")
    kb = nav_kb(adm, [btn_games()])
    if won:
        pay = int(bet * mult)
        update_balance(msg.from_user.id, tcoin=pay, desc=f"Рулетка {num}")
        await msg.answer(f"🎡 <b>Рулетка:</b> {ce} <b>{num}</b> ({cn})\n\n🎉 <b>ПОБЕДА!</b>\n💰 {bet} 🪙 ×{mult}\n✅ <b>{pay} 🪙</b>", parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(f"🎡 <b>Рулетка:</b> {ce} <b>{num}</b> ({cn})\n\n😔 <b>Проигрыш</b>\n\n{random.choice(NEAR_MISS)}\n-{bet} 🪙", parse_mode="HTML", reply_markup=kb)

@dp.message(F.text.regexp(RE_COIN))
async def g_coin(msg: Message):
    if not await game_ready(msg): return
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    parts = msg.text.split()
    if len(parts) < 3: return await msg.answer("⚠️ <code>мон 100 о</code> (о/р)", parse_mode="HTML", reply_markup=ke)
    bet, err = parse_bet(parts, 1)
    if err: return await msg.answer(err, reply_markup=ke)
    c = parts[2].lower()
    if c in ["о","орел","орёл"]: wh = True
    elif c in ["р","решка"]: wh = False
    else: return await msg.answer("❌ о/р", reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    if should_lose("coin"):
        update_balance(msg.from_user.id, tcoin=-bet, desc="Ставка: Монетка")
        return await game_lose(msg, "Монетка", bet)
    update_balance(msg.from_user.id, tcoin=-bet, desc="Монетка")
    res = random.choice(["орёл", "решка"])
    won = (res == "орёл") == wh
    em = "🦅" if res == "орёл" else "🪙"
    kb = nav_kb(adm, [btn_games()])
    if won:
        pay = bet * 2
        update_balance(msg.from_user.id, tcoin=pay, desc="Монетка выигрыш")
        await msg.answer(f"{em} <b>{res.capitalize()}!</b>\n\n🎉 <b>ПОБЕДА!</b>\n💰 {bet} 🪙\n✅ <b>{pay} 🪙</b>", parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(f"{em} <b>{res.capitalize()}!</b>\n\n😔 <b>Проигрыш</b>\n\n{random.choice(NEAR_MISS)}\n-{bet} 🪙", parse_mode="HTML", reply_markup=kb)

@dp.message(F.text.regexp(RE_HILO))
async def g_hilo(msg: Message):
    if not await game_ready(msg): return
    parts = msg.text.split()
    cmd = parts[0].lower()
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    bet, err = parse_bet(parts, 1)
    if err: return await msg.answer(err, reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    if should_lose("hilo"):
        update_balance(msg.from_user.id, tcoin=-bet, desc=f"Ставка: {cmd}")
        return await game_lose(msg, cmd.capitalize(), bet)
    update_balance(msg.from_user.id, tcoin=-bet, desc=cmd)
    num = random.randint(1, 100)
    kb = nav_kb(adm, [btn_games()])
    if num == 50:
        update_balance(msg.from_user.id, tcoin=bet, desc="Hilo ничья")
        return await msg.answer(f"📊 <b>Число: {num}</b>\n\n🤝 <b>Ничья!</b> Ставка возвращена.", parse_mode="HTML", reply_markup=kb)
    won = num >= 51 if cmd == "больше" else num <= 49
    gn = cmd.capitalize()
    em = "🔥" if num >= 75 else ("📈" if num >= 51 else ("❄️" if num <= 25 else "📉"))
    if won:
        pay = int(bet * 1.9)
        update_balance(msg.from_user.id, tcoin=pay, desc=f"{gn} {num}")
        await msg.answer(f"{em} <b>Число: {num}</b>\n\n🎉 <b>ПОБЕДА!</b>\n💰 {bet} 🪙 ×1.9\n✅ <b>{pay} 🪙</b>", parse_mode="HTML", reply_markup=kb)
    else:
        await msg.answer(f"{em} <b>Число: {num}</b>\n\n😔 <b>Проигрыш</b>\n\n{random.choice(NEAR_MISS)}\n-{bet} 🪙", parse_mode="HTML", reply_markup=kb)

@dp.message(F.text.regexp(RE_MINES))
async def g_mines(msg: Message, state: FSMContext):
    if not await game_ready(msg): return
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    current_state = await state.get_state()
    if current_state == MinesStates.playing.state:
        return await msg.answer("⏳ У вас уже активна игра!", reply_markup=ke)
    parts = msg.text.split()
    if len(parts) < 3:
        return await msg.answer("⚠️ <code>мины 100 3</code>\nСтавка и кол-во мин (1-5)", parse_mode="HTML", reply_markup=ke)
    bet, err = parse_bet(parts, 1)
    if err: return await msg.answer(err, reply_markup=ke)
    try: mc = int(parts[2])
    except: return await msg.answer("❌ Мины: 1-5!", reply_markup=ke)
    if not 1 <= mc <= 5: return await msg.answer("❌ Мины: 1-5!", reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно TC!", reply_markup=ke)
    if should_lose("mines"):
        update_balance(msg.from_user.id, tcoin=-bet, desc=f"Ставка: Мины ({mc})")
        mines = [0] + random.sample(range(1, 25), mc - 1) if mc > 1 else [0]
    else:
        mines = random.sample(range(25), mc)
    update_balance(msg.from_user.id, tcoin=-bet, desc=f"Ставка: Мины ({mc})")
    await state.update_data(bet=bet, mines_count=mc, opened=[], mines=mines, multiplier=1.0)
    await state.set_state(MinesStates.playing)
    initial_msg = await msg.answer("💣 Загрузка...", reply_markup=build_keyboard([[btn_games()]]))
    await state.update_data(message_id=initial_msg.message_id, chat_id=initial_msg.chat.id)
    await render_mines_grid(initial_msg, state)

def calc_mines_multiplier(opened_count: int, mines_count: int) -> float:
    if opened_count == 0: return 1.0
    base = 25 / (25 - mines_count)
    return round(base ** opened_count, 2)

async def render_mines_grid(target, state, new_opened: int = None, game_over: bool = False, lost: bool = False):
    data = await state.get_data()
    bet = data['bet']
    mines_count = data['mines_count']
    opened = list(data['opened'])
    mines = data['mines']
    if new_opened is not None and new_opened not in opened:
        opened.append(new_opened)
        await state.update_data(opened=opened)
    mult = calc_mines_multiplier(len(opened), mines_count)
    await state.update_data(multiplier=mult)
    buttons = []
    for i in range(25):
        if game_over:
            if i in mines: text = "💣"
            elif i in opened: text = "⭐️"
            else: text = "⬜"
            cd = f"mine_disabled_{i}"
        elif i in opened:
            text = "⭐️"
            cd = f"mine_disabled_{i}"
        else:
            text = "⬜"
            cd = f"mine_{i}"
        buttons.append(InlineKeyboardButton(text=text, callback_data=cd))
    rows = [buttons[i:i+5] for i in range(0, 25, 5)]
    payout = int(bet * mult)
    if game_over:
        if lost:
            text = f"💣 <b>МИНА!</b>\n\n💰 Ставка: {bet} 🪙\n💣 Мин: {mines_count}\n⭐️ Открыто: {len(opened) - 1}\n\n😔 <b>Проигрыш!</b>\n{random.choice(NEAR_MISS)}\n-{bet} 🪙"
        else:
            text = f"⭐️ <b>Вы забрали выигрыш!</b>\n\n💰 Ставка: {bet} 🪙\n💣 Мин: {mines_count}\n⭐️ Открыто: {len(opened)}\n📈 ×{mult:.2f}\n\n✅ <b>Выигрыш: {payout} 🪙</b>"
        rows.append([btn_games()])
        rows.append([btn_menu()])
    else:
        text = (f"💣 <b>Мины</b>\n\n💰 Ставка: {bet} 🪙\n💣 Мин: {mines_count}\n"
                f"⭐️ Открыто: {len(opened)}/25\n📈 Множитель: ×{mult:.2f}\n💵 Выигрыш: {payout} 🪙\n\n"
                f"Нажмите на клетку или заберите выигрыш.")
        rows.append([cbtn(f"💰 Забрать {payout} 🪙 (×{mult:.2f})", "mine_cashout", "success")])
    kb = build_keyboard(rows)
    msg = target.message if hasattr(target, 'message') else target
    try:
        await msg.edit_text(text, parse_mode="HTML", reply_markup=kb)
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            logging.error(f"Mines render error: {e}")

@dp.callback_query(F.data.startswith("mine_"))
async def mine_click(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    current_state = await state.get_state()
    if current_state != MinesStates.playing.state:
        return await cb.answer("❌ Игра не активна", show_alert=True)
    data = await state.get_data()
    cell = int(cb.data.split("_")[1])
    mines = data['mines']
    opened = data['opened']
    if cell in opened:
        return await cb.answer("⬜ Уже открыта!", show_alert=True)
    if cell in mines:
        await render_mines_grid(cb, state, new_opened=cell, game_over=True, lost=True)
        await state.clear()
        return
    await render_mines_grid(cb, state, new_opened=cell)
    if len(opened) + 1 >= 25 - data['mines_count']:
        bet = data['bet']
        mult = calc_mines_multiplier(len(opened) + 1, data['mines_count'])
        payout = int(bet * mult)
        update_balance(cb.from_user.id, tcoin=payout, desc=f"Мины ×{mult:.2f}")
        await render_mines_grid(cb, state, game_over=True, lost=False)
        await state.clear()

@dp.callback_query(F.data == "mine_cashout")
async def mine_cashout(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    current_state = await state.get_state()
    if current_state != MinesStates.playing.state:
        return await cb.answer("❌ Игра не активна", show_alert=True)
    data = await state.get_data()
    bet = data['bet']
    mult = data['multiplier']
    payout = int(bet * mult)
    update_balance(cb.from_user.id, tcoin=payout, desc=f"Мины ×{mult:.2f}")
    await render_mines_grid(cb, state, game_over=True, lost=False)
    await state.clear()

@dp.callback_query(F.data.startswith("mine_disabled_"))
async def mine_disabled(cb: CallbackQuery):
    await cb.answer("⬜", show_alert=True)

@dp.message(F.text.regexp(RE_CRASH))
async def g_crash(msg: Message):
    if not await game_ready(msg): return
    adm = is_admin(msg.from_user.id)
    ke = nav_kb(adm, [btn_games()])
    parts = msg.text.split()
    if len(parts) < 3: return await msg.answer("⚠️ <code>краш 100 2.0</code>", parse_mode="HTML", reply_markup=ke)
    bet, err = parse_bet(parts, 1)
    if err: return await msg.answer(err, reply_markup=ke)
    try: co = float(parts[2])
    except: return await msg.answer("❌ Множитель 1.1-100!", reply_markup=ke)
    if not 1.1 <= co <= 100: return await msg.answer("❌ 1.1-100!", reply_markup=ke)
    if not check_bal(msg.from_user.id, bet): return await msg.answer("❌ Недостаточно!", reply_markup=ke)
    if should_lose("crash"):
        update_balance(msg.from_user.id, tcoin=-bet, desc=f"Ставка: Краш ×{co}")
        anim = "🚀 <b>Краш:</b>\n  💥 <b>КРАШ на ×1.0!</b>\n\n😔 Не успели.\n" + random.choice(NEAR_MISS) + f"\n-{bet} 🪙"
        return await msg.answer(anim, parse_mode="HTML", reply_markup=ke)
    update_balance(msg.from_user.id, tcoin=-bet, desc=f"Краш ×{co}")
    cp = round(100 / random.randint(1, 100), 2)
    anim = "🚀 <b>Краш:</b>\n"
    for s in [1.0, 1.5, 2.0, 3.0, 5.0, 10.0, 20.0, 50.0]:
        if s > cp: break
        anim += f"  📈 ×{s}...\n"
        await asyncio.sleep(0.3)
    kb = nav_kb(adm, [btn_games()])
    if cp >= co:
        pay = int(bet * co)
        update_balance(msg.from_user.id, tcoin=pay, desc=f"Краш ×{co}")
        anim += f"\n💥 Краш на ×{cp}\n\n🎉 <b>Успели на ×{co}!</b>\n✅ <b>{pay} 🪙</b>"
    else:
        anim += f"\n💥 <b>КРАШ на ×{cp}!</b>\n\n😔 Не успели.\n{random.choice(NEAR_MISS)}\n-{bet} 🪙"
    await msg.answer(anim, parse_mode="HTML", reply_markup=kb)

# =============================================================================
# ========================= АДМИН-ПАНЕЛЬ ====================================
# =============================================================================

@dp.callback_query(F.data == "admin")
async def cb_admin(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    await state.clear()
    s = get_bot_stats()
    text = (f"👑 <b>Админ-панель</b>\n\n📊 <b>Статистика:</b>\n"
            f"👥 Пользователей: {s['total_users']}\n✅ Активных: {s['active_users']}\n🚫 Забанено: {s['banned_users']}\n"
            f"🆕 Сегодня: {s['new_today']}\n⭐️ SC: {fmt(s['total_sc'])}\n🪙 TC: {fmt(s['total_tc'])}\n"
            f"📝 TX сегодня: {s['tx_today']}\n📋 Заявок: {s['pending_requests']}\n"
            f"🎟 Промокодов: {s['active_promos']}\n🎫 Чеков: {s['active_checks']}")
    kb = build_keyboard([
        [cbtn("⚙️ Настройки", "admin_settings", "primary"), cbtn("💱 Курсы", "admin_rates", "primary")],
        [cbtn("👥 Юзеры", "admin_users", "primary"), cbtn("🎟 Промокоды", "admin_promos", "primary")],
        [cbtn("🎫 Все чеки", "admin_checks", "primary"), cbtn("📋 Заявки", "admin_requests", "primary")],
        [cbtn("📢 Рассылка", "admin_broadcast", "danger")],
        [btn_menu()]])
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data == "admin_settings")
async def cb_admin_settings(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    s = get_all_settings()
    text = "⚙️ <b>Настройки бота</b>\n\n"
    toggles = [("bot_active","🟢 Бот"),("maintenance_mode","🔧 Обслуж."),("games_enabled","🎮 Игры"),
               ("transfer_enabled","💸 Переводы"),("deposit_enabled","💎 Покупка SC"),
               ("withdraw_enabled","💰 Продажа SC"),("verification_required","✅ Вериф.")]
    for k, l in toggles:
        text += f"{'✅' if s.get(k)=='1' else '❌'} {l}: <b>{'Вкл' if s.get(k)=='1' else 'Выкл'}</b>\n"
    rows = [[cbtn(f"{'✅' if s.get(k)=='1' else '❌'} {l}", f"toggle_{k}", "success" if s.get(k)=='1' else "danger")] for k, l in toggles]
    rows.append([cbtn("🔙 Назад", "admin", "primary")])
    await render(cb.message, text, build_keyboard(rows), is_cb=True)

@dp.callback_query(F.data.startswith("toggle_"))
async def cb_toggle(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    key = cb.data.replace("toggle_", "")
    cur = get_setting(key)
    set_setting(key, "0" if cur == "1" else "1")
    cb.data = "admin_settings"
    await cb_admin_settings(cb)

@dp.callback_query(F.data == "admin_rates")
async def cb_admin_rates(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    s = get_all_settings()
    text = (f"💱 <b>Курсы и лимиты</b>\n\n💱 Курс: <code>{s.get('exchange_rate')}</code> TC=1SC\n"
            f"💵 Мин. ставка: <code>{s.get('min_bet')}</code>\n💰 Макс. ставка: <code>{s.get('max_bet')}</code>\n"
            f"🎁 Бонус ⭐️: <code>{s.get('daily_bonus_sc')}</code>\n🎁 Бонус 🪙: <code>{s.get('daily_bonus_tc')}</code>\n"
            f"👥 Реф. бонус: <code>{s.get('referral_bonus')}</code>\n💳 Мин. продажа: <code>{s.get('min_withdraw')}</code>\n"
            f"💸 Комиссия продажи: <code>{s.get('sell_commission')}</code>%\n"
            f"💎 Оплата за задание: <code>{s.get('task_reward')}</code> ⭐️ SC\n\n"
            f"<b>🎲 Скрытый шанс проигрыша (%):</b>\n"
            f"• Слоты: <code>{s.get('lose_chance_slots')}</code>%\n"
            f"• Кости: <code>{s.get('lose_chance_dice')}</code>%\n"
            f"• Дротик: <code>{s.get('lose_chance_darts')}</code>%\n"
            f"• Баскет: <code>{s.get('lose_chance_basket')}</code>%\n"
            f"• Футбол: <code>{s.get('lose_chance_football')}</code>%\n"
            f"• Рулетка: <code>{s.get('lose_chance_roulette')}</code>%\n"
            f"• Монетка: <code>{s.get('lose_chance_coin')}</code>%\n"
            f"• Hilo: <code>{s.get('lose_chance_hilo')}</code>%\n"
            f"• Мины: <code>{s.get('lose_chance_mines')}</code>%\n"
            f"• Краш: <code>{s.get('lose_chance_crash')}</code>%")
    keys = [("set_exchange_rate","💱 Курс TC/SC"),("set_min_bet","💵 Мин. ставка"),("set_max_bet","💰 Макс. ставка"),
            ("set_daily_sc","🎁 Бонус ⭐️"),("set_daily_tc","🎁 Бонус 🪙"),("set_referral_bonus","👥 Реф. бонус"),
            ("set_min_withdraw","💳 Мин. продажа"),("set_sell_commission","💸 Комиссия %"),
            ("set_task_reward","💎 Оплата за задание"),
            ("set_lose_slots","🎰 Шанс слоты"),("set_lose_dice","🎲 Шанс кости"),
            ("set_lose_darts","🎯 Шанс дротик"),("set_lose_basket","🏀 Шанс баскет"),
            ("set_lose_football","⚽ Шанс футбол"),("set_lose_roulette","🎡 Шанс рулетка"),
            ("set_lose_coin","🪙 Шанс монетка"),("set_lose_hilo","📊 Шанс hilo"),
            ("set_lose_mines","💣 Шанс мины"),("set_lose_crash","🚀 Шанс краш")]
    rows = [[cbtn(l, d, "primary")] for d, l in keys]
    rows.append([cbtn("🔙 Назад", "admin", "primary")])
    await render(cb.message, text, build_keyboard(rows), is_cb=True)

SK = {"set_exchange_rate":("exchange_rate","💱 Курс TC/SC:"),"set_min_bet":("min_bet","💵 Мин. ставка:"),
      "set_max_bet":("max_bet","💰 Макс. ставка:"),"set_daily_sc":("daily_bonus_sc","🎁 Бонус ⭐️:"),
      "set_daily_tc":("daily_bonus_tc","🎁 Бонус 🪙:"),"set_referral_bonus":("referral_bonus","👥 Реф. бонус:"),
      "set_min_withdraw":("min_withdraw","💳 Мин. продажа:"),"set_sell_commission":("sell_commission","💸 Комиссия %:"),
      "set_task_reward":("task_reward","💎 Оплата за задание:"),
      "set_lose_slots":("lose_chance_slots","🎰 Шанс слоты %:"),"set_lose_dice":("lose_chance_dice","🎲 Шанс кости %:"),
      "set_lose_darts":("lose_chance_darts","🎯 Шанс дротик %:"),"set_lose_basket":("lose_chance_basket","🏀 Шанс баскет %:"),
      "set_lose_football":("lose_chance_football","⚽ Шанс футбол %:"),"set_lose_roulette":("lose_chance_roulette","🎡 Шанс рулетка %:"),
      "set_lose_coin":("lose_chance_coin","🪙 Шанс монетка %:"),"set_lose_hilo":("lose_chance_hilo","📊 Шанс hilo %:"),
      "set_lose_mines":("lose_chance_mines","💣 Шанс мины %:"),"set_lose_crash":("lose_chance_crash","🚀 Шанс краш %:")}

@dp.callback_query(F.data.startswith("set_"))
async def cb_set_val(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    await state.clear()
    kd = SK.get(cb.data)
    if not kd: return
    key, prompt = kd
    await state.update_data(setting_key=key)
    await state.set_state(AdminStates.waiting_setting_value)
    await cb.message.edit_text(f"{prompt}\nТекущее: <code>{get_setting(key)}</code>\n\n<i>Можно ввести дробное число</i>", parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("cancel_setting")]]))

@dp.callback_query(F.data == "cancel_setting")
async def cb_cancel_setting(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    cb.data = "admin_rates"
    await cb_admin_rates(cb)

@dp.message(AdminStates.waiting_setting_value)
async def proc_setting(msg: Message, state: FSMContext):
    data = await state.get_data()
    key = data.get("setting_key")
    await state.clear()
    if not key or not is_admin(msg.from_user.id): return
    try:
        v = float(msg.text.strip())
        if v < 0: raise ValueError
    except ValueError:
        return await msg.answer("❌ Положительное число!", reply_markup=build_keyboard([[cbtn("🔙 К курсам", "admin_rates", "primary")], [btn_admin()], [btn_menu()]]))
    set_setting(key, v)
    await msg.answer(f"✅ <b>{key}</b> = <code>{v}</code>", parse_mode="HTML",
                     reply_markup=build_keyboard([[cbtn("🔧 Ещё изменить", "admin_rates", "success")], [btn_admin()], [btn_menu()]]))

# ==================== ЮЗЕРЫ ====================

@dp.callback_query(F.data == "admin_users")
async def cb_admin_users(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    await state.clear()
    await render(cb.message, "👥 <b>Управление юзерами</b>\n\nОтправьте ID или @username:",
                 build_keyboard([[btn_cancel("cancel_ua")], [cbtn("🔙 Назад", "admin", "primary")]]), is_cb=True)
    await state.set_state(AdminStates.waiting_user_id)

@dp.callback_query(F.data == "cancel_ua")
async def cb_cancel_ua(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    cb.data = "admin"
    await cb_admin(cb, state)

@dp.message(AdminStates.waiting_user_id)
async def proc_uid(msg: Message, state: FSMContext):
    await state.clear()
    tid = await resolve_user_id(msg.text.strip(), msg.reply_to_message)
    retry_kb = build_keyboard([[cbtn("🔍 Ещё поиск", "admin_users_search", "success")], [btn_admin()], [btn_menu()]])
    if not tid: return await msg.answer("❌ Не найден!", reply_markup=retry_kb)
    t = get_user(tid)
    if not t: return await msg.answer("❌ Не найден в БД!", reply_markup=retry_kb)
    text = f"👤 <b>Юзер:</b>\n🆔 <code>{t['user_id']}</code>\n📝 @{t['username'] or 'N/A'}\n👤 {t['first_name']}\n⭐️ {t['stars_balance']} SC | 🪙 {t['tcoin_balance']} TC"
    kb = build_keyboard([
        [cbtn("⭐️ +SC", f"ua_as_{tid}", "success"), cbtn("🪙 +TC", f"ua_at_{tid}", "success")],
        [cbtn("🔄 Сброс", f"ua_rst_{tid}", "danger"), cbtn("🚫 Бан", f"ua_ban_{tid}", "danger")],
        [cbtn("✅ Разбан", f"ua_ub_{tid}", "success"), cbtn("👑 Админ", f"ua_adm_{tid}", "primary")],
        [cbtn("🔍 Другой", "admin_users_search", "primary")], [btn_admin()], [btn_menu()]])
    await msg.answer(text, parse_mode="HTML", reply_markup=kb)

@dp.callback_query(F.data == "admin_users_search")
async def cb_ua_search(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    await state.set_state(AdminStates.waiting_user_id)
    await cb.message.edit_text("🔍 Отправьте ID или @username:",
                               reply_markup=build_keyboard([[btn_cancel("cancel_ua")]]))

@dp.callback_query(F.data.startswith("ua_as_"))
async def cb_ua_as(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    tid = int(cb.data.split("_")[-1])
    await state.update_data(action="addstars", target_user_id=tid)
    await state.set_state(AdminStates.waiting_amount)
    await cb.message.edit_text(f"⭐️ Кол-во SC для <code>{tid}</code>:", parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("cancel_amt")]]))

@dp.callback_query(F.data.startswith("ua_at_"))
async def cb_ua_at(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    tid = int(cb.data.split("_")[-1])
    await state.update_data(action="addtcoin", target_user_id=tid)
    await state.set_state(AdminStates.waiting_amount)
    await cb.message.edit_text(f"🪙 Кол-во TC для <code>{tid}</code>:", parse_mode="HTML",
                               reply_markup=build_keyboard([[btn_cancel("cancel_amt")]]))

@dp.callback_query(F.data == "cancel_amt")
async def cb_cancel_amt(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    cb.data = "admin"
    await cb_admin(cb, state)

@dp.message(AdminStates.waiting_amount)
async def proc_amt(msg: Message, state: FSMContext):
    data = await state.get_data()
    act, tid = data.get("action"), data.get("target_user_id")
    await state.clear()
    if not act or not tid or not is_admin(msg.from_user.id): return
    try: amt = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!", reply_markup=nav_kb(True))
    if act == "addstars":
        update_balance(tid, stars=amt, desc="Админ")
        await msg.answer(f"✅ +{amt} ⭐️ SC → {tid}", reply_markup=build_keyboard([[cbtn("👥 К юзерам", "admin_users", "primary")], [btn_admin()], [btn_menu()]]))
    elif act == "addtcoin":
        update_balance(tid, tcoin=amt, desc="Админ")
        await msg.answer(f"✅ +{amt} 🪙 TC → {tid}", reply_markup=build_keyboard([[cbtn("👥 К юзерам", "admin_users", "primary")], [btn_admin()], [btn_menu()]]))

@dp.callback_query(F.data.startswith("ua_rst_"))
async def cb_ua_rst(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    tid = int(cb.data.split("_")[-1])
    conn = get_db()
    conn.execute("UPDATE users SET stars_balance=0, tcoin_balance=0 WHERE user_id=?", (tid,))
    conn.commit()
    conn.close()
    await cb.message.edit_text(f"🔄 Баланс <code>{tid}</code> сброшен.", parse_mode="HTML",
                               reply_markup=build_keyboard([[cbtn("👥 К юзерам", "admin_users", "primary")], [btn_admin()], [btn_menu()]]))

@dp.callback_query(F.data.startswith("ua_ban_"))
async def cb_ua_ban(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    tid = int(cb.data.split("_")[-1])
    update_user_field(tid, "is_banned", 1)
    await cb.message.edit_text(f"🚫 <code>{tid}</code> забанен.", parse_mode="HTML",
                               reply_markup=build_keyboard([[cbtn("👥 К юзерам", "admin_users", "primary")], [btn_admin()], [btn_menu()]]))

@dp.callback_query(F.data.startswith("ua_ub_"))
async def cb_ua_ub(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    tid = int(cb.data.split("_")[-1])
    update_user_field(tid, "is_banned", 0)
    await cb.message.edit_text(f"✅ <code>{tid}</code> разбанен.", parse_mode="HTML",
                               reply_markup=build_keyboard([[cbtn("👥 К юзерам", "admin_users", "primary")], [btn_admin()], [btn_menu()]]))

@dp.callback_query(F.data.startswith("ua_adm_"))
async def cb_ua_adm(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    tid = int(cb.data.split("_")[-1])
    u = get_user(tid)
    nv = 0 if u['is_admin'] else 1
    update_user_field(tid, "is_admin", nv)
    await cb.message.edit_text(f"👑 <code>{tid}</code> → {'админ' if nv else 'юзер'}.", parse_mode="HTML",
                               reply_markup=build_keyboard([[cbtn("👥 К юзерам", "admin_users", "primary")], [btn_admin()], [btn_menu()]]))

# ==================== ПРОМОКОДЫ АДМИН ====================

@dp.callback_query(F.data == "admin_promos")
async def cb_admin_promos(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    ps = list_promos()
    if not ps: text = "🎟 <b>Промокоды</b>\n\nНет промокодов."
    else:
        text = "🎟 <b>Промокоды:</b>\n\n"
        for p in ps: text += f"{'✅' if p['is_active'] else '❌'} <code>{p['code']}</code> ⭐️{p['stars_reward']} 🪙{p['tcoin_reward']} ({p['current_uses']}/{p['max_uses']})\n"
    kb = build_keyboard([[cbtn("➕ Создать", "promo_create", "success")], [cbtn("🗑 Удалить", "promo_delete", "danger")], [cbtn("🔙 Назад", "admin", "primary")]])
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data == "promo_create")
async def cb_pc(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    await state.set_state(AdminStates.waiting_promo_code)
    await cb.message.edit_text("🎟 Код промокода (A-Z, 0-9):", reply_markup=build_keyboard([[btn_cancel("cancel_pa")]]))

@dp.callback_query(F.data == "cancel_pa")
async def cb_cancel_pa(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    cb.data = "admin_promos"
    await cb_admin_promos(cb)

@dp.message(AdminStates.waiting_promo_code)
async def proc_pc(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    code = msg.text.strip().upper()
    if not re.match(r'^[A-Z0-9_]{3,30}$', code):
        return await msg.answer("❌ 3-30 символов A-Z 0-9 _", reply_markup=build_keyboard([[cbtn("🎟 К промокодам", "admin_promos", "primary")], [btn_admin()], [btn_menu()]]))
    await state.update_data(promo_code=code)
    await state.set_state(AdminStates.waiting_promo_sc)
    await msg.answer("⭐️ Сколько SC?")

@dp.message(AdminStates.waiting_promo_sc)
async def proc_ps(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: sc = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!", reply_markup=build_keyboard([[cbtn("🎟 К промокодам", "admin_promos", "primary")], [btn_admin()], [btn_menu()]]))
    await state.update_data(promo_sc=sc)
    await state.set_state(AdminStates.waiting_promo_tc)
    await msg.answer("🪙 Сколько TC?")

@dp.message(AdminStates.waiting_promo_tc)
async def proc_pt(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: tc = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!", reply_markup=build_keyboard([[cbtn("🎟 К промокодам", "admin_promos", "primary")], [btn_admin()], [btn_menu()]]))
    await state.update_data(promo_tc=tc)
    await state.set_state(AdminStates.waiting_promo_limit)
    await msg.answer("🔢 Макс. использований?")

@dp.message(AdminStates.waiting_promo_limit)
async def proc_pl(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    try: lim = int(msg.text.strip())
    except ValueError: return await msg.answer("❌ Число!", reply_markup=build_keyboard([[cbtn("🎟 К промокодам", "admin_promos", "primary")], [btn_admin()], [btn_menu()]]))
    d = await state.get_data()
    await state.clear()
    code, sc, tc = d['promo_code'], d.get('promo_sc', 0), d.get('promo_tc', 0)
    if create_promo(code, sc, tc, lim):
        await msg.answer(f"✅ <code>{code}</code> создан! ⭐️{sc} 🪙{tc} x{lim}", parse_mode="HTML",
                         reply_markup=build_keyboard([[cbtn("➕ Ещё", "promo_create", "success")], [cbtn("🎟 К промокодам", "admin_promos", "primary")], [btn_admin()], [btn_menu()]]))
    else:
        await msg.answer("❌ Уже существует!", reply_markup=build_keyboard([[cbtn("🎟 К промокодам", "admin_promos", "primary")], [btn_admin()], [btn_menu()]]))

@dp.callback_query(F.data == "promo_delete")
async def cb_pd(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    await state.set_state(AdminStates.waiting_promo_delete)
    await cb.message.edit_text("🗑 Код промокода для удаления:", reply_markup=build_keyboard([[btn_cancel("cancel_pa")]]))

@dp.message(AdminStates.waiting_promo_delete)
async def proc_pd(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    await state.clear()
    code = msg.text.strip().upper()
    kb = build_keyboard([[cbtn("🎟 К промокодам", "admin_promos", "primary")], [btn_admin()], [btn_menu()]])
    if delete_promo(code): await msg.answer(f"✅ <code>{code}</code> удалён!", parse_mode="HTML", reply_markup=kb)
    else: await msg.answer(f"❌ <code>{code}</code> не найден!", parse_mode="HTML", reply_markup=kb)

# ==================== ЧЕКИ АДМИН ====================

@dp.callback_query(F.data == "admin_checks")
async def cb_admin_checks(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    cs = list_checks()
    if not cs: text = "🎫 <b>Все чеки</b>\n\nНет активных чеков."
    else:
        text = "🎫 <b>Все чеки:</b>\n\n"
        bi = await bot.get_me()
        for c in cs:
            creator = get_user(c['created_by'])
            cr_name = f"@{creator['username']}" if creator and creator['username'] else c['created_by']
            text += f"🎫 <code>{c['code']}</code>\n   ⭐️ {c['sc_amount']} SC | 🪙 {c['tc_amount']} TC\n   🔢 Активаций: {c['activations_left']}\n   👤 Создатель: {cr_name}\n\n"
    kb = build_keyboard([[cbtn("➕ Создать чек", "check_create_admin", "success")], [cbtn("🗑 Удалить чек", "check_delete_admin", "danger")], [cbtn("🔙 Назад", "admin", "primary")]])
    await render(cb.message, text, kb, is_cb=True)

@dp.callback_query(F.data == "check_create_admin")
async def cb_check_create_admin(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    code = generate_code()
    await state.update_data(check_code=code, check_creator="admin")
    await state.set_state(UserStates.waiting_check_create_sc)
    await cb.message.edit_text(
        f"🎫 <b>Создание чека</b>\n\nКод: <code>{code}</code>\n\n⭐️ Сколько SC даёт чек?",
        parse_mode="HTML",
        reply_markup=build_keyboard([[btn_cancel("cancel_ck_admin")]])
    )

@dp.callback_query(F.data == "cancel_ck_admin")
async def cb_cancel_ck_admin(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    cb.data = "admin_checks"
    await cb_admin_checks(cb)

@dp.callback_query(F.data == "check_delete_admin")
async def cb_check_delete_admin(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    await state.set_state(AdminStates.waiting_promo_delete)
    await state.update_data(delete_type="check")
    await cb.message.edit_text("🗑 Код чека для удаления:", reply_markup=build_keyboard([[btn_cancel("cancel_ck_admin")]]))

# ==================== ЗАЯВКИ ====================

@dp.callback_query(F.data == "admin_requests")
async def cb_admin_reqs(cb: CallbackQuery):
    if not is_admin(cb.from_user.id): return await cb.answer("❌ Нет прав!", show_alert=True)
    await cb.answer()
    rs = get_pending_requests()
    if not rs: text = "📋 <b>Заявки</b>\n\nНет ожидающих."
    else:
        text = "📋 <b>Заявки:</b>\n\n"
        for r in rs:
            icon = "💎" if r['req_type']=='deposit' else ("💰" if r['req_type']=='sell_starts' else "📤")
            text += f"{icon} #{r['id']} {r['amount']} 👤{r['user_id']} ({r['req_type']}) {r['created_at'][:16]}\n"
    await render(cb.message, text, build_keyboard([[cbtn("🔙 Назад", "admin", "primary")]]), is_cb=True)

# ==================== РАССЫЛКА ====================

@dp.callback_query(F.data == "admin_broadcast")
async def cb_ab(cb: CallbackQuery, state: FSMContext):
    if not is_admin(cb.from_user.id): return
    await cb.answer()
    await state.clear()
    await state.set_state(AdminStates.waiting_broadcast)
    await cb.message.edit_text("📢 Сообщение для рассылки:", reply_markup=build_keyboard([[btn_cancel("cancel_bc")]]))

@dp.callback_query(F.data == "cancel_bc")
async def cb_cancel_bc(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer("❌ Отменено")
    cb.data = "admin"
    await cb_admin(cb, state)

@dp.message(AdminStates.waiting_broadcast)
async def proc_bc(msg: Message, state: FSMContext):
    if not is_admin(msg.from_user.id): return
    await state.clear()
    conn = get_db()
    users = [r['user_id'] for r in conn.execute("SELECT user_id FROM users WHERE is_banned=0").fetchall()]
    conn.close()
    st = safe_html(msg.text)
    sm = await msg.answer(f"📤 Рассылка {len(users)} юзерам...")
    ok = fail = 0
    for uid in users:
        try: await bot.send_message(uid, st); ok += 1; await asyncio.sleep(0.05)
        except: fail += 1
    await sm.edit_text(f"✅ Рассылка: {ok} ок, {fail} ошибок",
                       reply_markup=build_keyboard([[cbtn("📢 Ещё рассылка", "admin_broadcast", "success")], [btn_admin()], [btn_menu()]]))

# =============================================================================
# ========================= ТЕКСТОВЫЕ АДМИН-КОМАНДЫ =========================
# =============================================================================

# ✅ ИСПРАВЛЕНО: используем RE_ADMIN_CMD
@dp.message(F.text.regexp(RE_ADMIN_CMD))
async def admin_cmds_text(msg: Message):
    if not is_admin(msg.from_user.id): return
    parts = msg.text.split()
    cmd = parts[0].lower()
    kb = build_keyboard([[btn_admin()], [btn_menu()]])

    if cmd == "stats":
        s = get_bot_stats()
        return await msg.answer(f"📊 <b>Статистика:</b>\n👥 {s['total_users']} | ✅ {s['active_users']} | 🚫 {s['banned_users']}\n🆕 {s['new_today']} | ⭐️ {fmt(s['total_sc'])} SC | 🪙 {fmt(s['total_tc'])} TC\n📝 TX: {s['tx_today']} | 📋 Заявок: {s['pending_requests']}\n🎟 Промо: {s['active_promos']} | 🎫 Чеков: {s['active_checks']}", parse_mode="HTML", reply_markup=kb)
    if cmd == "requests":
        rs = get_pending_requests()
        if not rs: return await msg.answer("📋 Нет заявок.", reply_markup=kb)
        t = "📋 <b>Заявки:</b>\n\n"
        for r in rs:
            icon = "💎" if r['req_type']=='deposit' else ("💰" if r['req_type']=='sell_starts' else "📤")
            t += f"{icon} #{r['id']} {r['amount']} 👤{r['user_id']} ({r['req_type']})\n"
        return await msg.answer(t, parse_mode="HTML", reply_markup=kb)
    if cmd in ["addstars","addtcoin","reset","ban","unban","makeadmin","userstats"]:
        if len(parts) < 2 and not msg.reply_to_message: return await msg.answer(f"⚠️ {cmd} ID [значение]", reply_markup=kb)
        tid = await resolve_user_id(parts[1] if len(parts) > 1 else "", msg.reply_to_message)
        if not tid: return await msg.answer("❌ Не найден!", reply_markup=kb)
        if cmd == "addstars":
            if len(parts) < 3: return await msg.answer("⚠️ addstars ID 100", reply_markup=kb)
            try: v = int(parts[2])
            except: return await msg.answer("❌ Число!", reply_markup=kb)
            update_balance(tid, stars=v, desc="Админ")
            return await msg.answer(f"✅ +{v} ⭐️ SC → {tid}", reply_markup=kb)
        if cmd == "addtcoin":
            if len(parts) < 3: return await msg.answer("⚠️ addtcoin ID 100", reply_markup=kb)
            try: v = int(parts[2])
            except: return await msg.answer("❌ Число!", reply_markup=kb)
            update_balance(tid, tcoin=v, desc="Админ")
            return await msg.answer(f"✅ +{v} 🪙 TC → {tid}", reply_markup=kb)
        if cmd == "reset":
            conn = get_db(); conn.execute("UPDATE users SET stars_balance=0, tcoin_balance=0 WHERE user_id=?", (tid,)); conn.commit(); conn.close()
            return await msg.answer(f"🔄 Баланс {tid} сброшен.", reply_markup=kb)
        if cmd == "ban":
            update_user_field(tid, "is_banned", 1)
            return await msg.answer(f"🚫 {tid} забанен.", reply_markup=kb)
        if cmd == "unban":
            update_user_field(tid, "is_banned", 0)
            return await msg.answer(f"✅ {tid} разбанен.", reply_markup=kb)
        if cmd == "makeadmin":
            if len(parts) < 3: return await msg.answer("⚠️ makeadmin ID 1/0", reply_markup=kb)
            try: v = int(parts[2])
            except: return await msg.answer("❌ 1 или 0!", reply_markup=kb)
            if v not in [0,1]: return await msg.answer("❌ 1 или 0!", reply_markup=kb)
            update_user_field(tid, "is_admin", v)
            return await msg.answer(f"👑 {tid} → {'админ' if v else 'юзер'}", reply_markup=kb)
        if cmd == "userstats":
            u = get_user(tid)
            if not u: return await msg.answer("❌ Не найден.", reply_markup=kb)
            return await msg.answer(f"📊 <b>{u['user_id']}</b>\n@{u['username'] or 'N/A'} | {u['first_name']}\n⭐️ {u['stars_balance']} SC | 🪙 {u['tcoin_balance']} TC\n✅ {u['total_tasks_completed']} | 👥 {u['total_referrals']}\n🚫 {'Да' if u['is_banned'] else 'Нет'} | 👑 {'Да' if u['is_admin'] else 'Нет'}\n✅ Вериф: {'Да' if u['is_verified'] else 'Нет'}", parse_mode="HTML", reply_markup=kb)
    if cmd in ["setrate","setminbet","setmaxbet"]:
        if len(parts) < 2: return await msg.answer(f"⚠️ {cmd} ЧИСЛО", reply_markup=kb)
        try:
            v = float(parts[1])
            if v < 0: raise ValueError
        except: return await msg.answer("❌ Число > 0!", reply_markup=kb)
        km = {"setrate":"exchange_rate","setminbet":"min_bet","setmaxbet":"max_bet"}
        set_setting(km[cmd], v)
        return await msg.answer(f"✅ {km[cmd]} = {v}", reply_markup=kb)
    if cmd == "createpromo":
        if len(parts) < 5: return await msg.answer("⚠️ createpromo КОД SC TC ЛИМИТ", reply_markup=kb)
        try: code, sc, tc, lim = parts[1].upper(), int(parts[2]), int(parts[3]), int(parts[4])
        except: return await msg.answer("❌ Формат!", reply_markup=kb)
        if create_promo(code, sc, tc, lim): return await msg.answer(f"✅ <code>{code}</code> создан! ⭐️{sc} 🪙{tc} x{lim}", parse_mode="HTML", reply_markup=kb)
        return await msg.answer("❌ Уже существует!", reply_markup=kb)
    if cmd == "deletepromo":
        if len(parts) < 2: return await msg.answer("⚠️ deletepromo КОД", reply_markup=kb)
        code = parts[1].upper()
        if delete_promo(code): return await msg.answer(f"✅ <code>{code}</code> удалён!", parse_mode="HTML", reply_markup=kb)
        return await msg.answer(f"❌ Не найден!", parse_mode="HTML", reply_markup=kb)
    if cmd == "createcheck":
        if len(parts) < 5: return await msg.answer("⚠️ createcheck КОД SC TC АКТИВАЦИЙ", reply_markup=kb)
        try: code, sc, tc, act = parts[1].upper(), int(parts[2]), int(parts[3]), int(parts[4])
        except: return await msg.answer("❌ Формат!", reply_markup=kb)
        if create_check(code, sc, tc, act, msg.from_user.id):
            bi = await bot.get_me()
            return await msg.answer(f"✅ Чек <code>{code}</code> создан!\n⭐️{sc} 🪙{tc} x{act}\n\n🔗 <code>https://t.me/{bi.username}?start=check_{code}</code>", parse_mode="HTML", reply_markup=kb)
        return await msg.answer("❌ Уже существует!", reply_markup=kb)
    if cmd == "deletecheck":
        if len(parts) < 2: return await msg.answer("⚠️ deletecheck КОД", reply_markup=kb)
        code = parts[1].upper()
        if delete_check(code): return await msg.answer(f"✅ Чек <code>{code}</code> удалён!", parse_mode="HTML", reply_markup=kb)
        return await msg.answer(f"❌ Не найден!", parse_mode="HTML", reply_markup=kb)
    if cmd in ["approve","reject"]:
        if len(parts) < 2: return await msg.answer(f"⚠️ {cmd} ID", reply_markup=kb)
        try: rid = int(parts[1])
        except: return await msg.answer("❌ Число!", reply_markup=kb)
        req = get_request(rid)
        if not req or req['status'] != "pending": return await msg.answer("❌ Заявка не найдена!", reply_markup=kb)
        if cmd == "approve":
            update_request_status(rid, "approved")
            await msg.answer(f"✅ #{rid} одобрена.", reply_markup=kb)
            try: await bot.send_message(req['user_id'], f"✅ Заявка #{rid} одобрена!")
            except: pass
        else:
            update_request_status(rid, "rejected")
            if req['req_type'] == "sell_starts":
                update_balance(req['user_id'], stars=req['amount'], desc="Возврат SC (заявка отклонена)")
            await msg.answer(f"❌ #{rid} отклонена.", reply_markup=kb)
            try: await bot.send_message(req['user_id'], f"❌ Заявка #{rid} отклонена.")
            except: pass

# =============================================================================
# ========================= НАЗАД ===========================================
# =============================================================================

@dp.callback_query(F.data.startswith("back_"))
async def cb_back(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.answer()
    tgt = cb.data.replace("back_", "")
    u = get_user(cb.from_user.id)
    if not u: return
    if not u['is_verified'] and get_setting("verification_required") == "1": return await render_verify(cb, is_cb=True)
    if tgt == "profile":
        cb.data = "profile"
        await cb_profile(cb)
    else:
        await render_main_menu(cb, is_cb=True)

@dp.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()

# =============================================================================
# ========================= ЗАПУСК ==========================================
# =============================================================================

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.info("✅ Бот запущен!")
    logging.info(f"👑 Админ ID: {ADMIN_ID}")
    logging.info(f"💱 Курс: 1 SC = {get_setting('exchange_rate')} TC")
    try: await bot.delete_webhook(drop_pending_updates=True)
    except: pass
    await dp.start_polling(bot)

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt: logging.info("🛑 Остановлен")
    except Exception as e: logging.error(f"Error: {e}")
