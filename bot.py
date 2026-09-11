import os
import time
import sqlite3
import threading
import telebot
from telebot import types
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta

# ============================================================
# ЗАГРУЗКА НАСТРОЕК
# ============================================================
load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
# Токен провайдера ЮKassa (получить в @BotFather)
YOOKASSA_PROVIDER_TOKEN = os.getenv('YOOKASSA_PROVIDER_TOKEN', '')

# --- Настройки монетизации ---
SUBSCRIPTION_PRICE_STARS = 150
SUBSCRIPTION_DAYS = 30
FREE_MESSAGES_PER_DAY = 10
# Ссылка для оплаты через СБП (если используете внешний сервис)
PAYMENT_LINK_SBP = "https://example.com/sbp"

DB_FILE = '/data/bot_memory.db'
PROMPT_FILE = 'promtnastavnik.txt'

# ============================================================
# ЗАГРУЗКА ПРОМТА
# ============================================================
try:
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        SYSTEM_PROMPT = f.read()
    print("✅ Промт загружен")
except Exception as e:
    SYSTEM_PROMPT = "Ты полезный и дружелюбный ассистент."
    print(f"⚠️ Ошибка промта: {e}")

# ============================================================
# ИНИЦИАЛИЗАЦИЯ
# ============================================================
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")
user_states = {}

# ============================================================
# БАЗА ДАННЫХ
# ============================================================
def init_db():
    try:
        os.makedirs('/data', exist_ok=True)
    except Exception as e:
        print(f"⚠️ Не удалось создать /data: {e}")
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        role TEXT, content TEXT, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_seen REAL, last_seen REAL,
        message_count INTEGER DEFAULT 0, messages_today INTEGER DEFAULT 0,
        last_message_date TEXT, bot_name TEXT DEFAULT 'Наставник',
        tone TEXT DEFAULT 'soft', lang TEXT DEFAULT 'ru',
        subscription_until REAL, stars_balance INTEGER DEFAULT 0)''')
    c.execute('''CREATE TABLE IF NOT EXISTS moods (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        mood TEXT, note TEXT, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        text TEXT, remind_at REAL, created_at REAL, active INTEGER DEFAULT 1)''')
    conn.commit()
    conn.close()

def db_exec(query, params=(), fetch=False):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(query, params)
    result = c.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return result

def add_message(uid, role, content):
    db_exec('INSERT INTO history (user_id, role, content, timestamp) VALUES (?,?,?,?)',
            (uid, role, content, time.time()))

def get_history(uid, limit=10):
    rows = db_exec('SELECT role, content FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?',
                   (uid, limit), fetch=True)
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def clear_history(uid):
    db_exec('DELETE FROM history WHERE user_id=?', (uid,))

def register_user(uid, username):
    now = time.time()
    today = datetime.now().strftime('%Y-%m-%d')
    db_exec('''INSERT INTO users (user_id, username, first_seen, last_seen, message_count, last_message_date)
        VALUES (?,?,?,?,1,?) ON CONFLICT(user_id) DO UPDATE SET
        last_seen=?, message_count=message_count+1,
        messages_today = CASE WHEN last_message_date = ? THEN messages_today + 1 ELSE 1 END,
        last_message_date = ?''',
        (uid, username, now, now, today, now, today, today))

def get_user(uid):
    rows = db_exec('SELECT * FROM users WHERE user_id=?', (uid,), fetch=True)
    return rows[0] if rows else None

def update_user_setting(uid, field, value):
    db_exec(f'UPDATE users SET {field}=? WHERE user_id=?', (value, uid))

def has_active_subscription(uid):
    user = get_user(uid)
    if not user or not user[11]:
        return False
    return user[11] > time.time()

def check_message_limit(uid):
    if has_active_subscription(uid):
        return True
    user = get_user(uid)
    if not user:
        return True
    today = datetime.now().strftime('%Y-%m-%d')
    if user[8] != today:
        return True
    return user[7] < FREE_MESSAGES_PER_DAY

# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def main_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        types.KeyboardButton("💬 Поговорить"),
        types.KeyboardButton("🧘 Практика"),
        types.KeyboardButton("📔 Дневник"),
        types.KeyboardButton("📊 Прогресс"),
        types.KeyboardButton("🧪 Тест"),
        types.KeyboardButton("⚙️ Настройки"),
        types.KeyboardButton("💎 Подписка"),
        types.KeyboardButton("🆘 Мне плохо"),
        types.KeyboardButton("❓ Помощь")
    )
    return kb

def settings_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("✏️ Имя бота", callback_data="set_name"),
        types.InlineKeyboardButton("🎭 Тон", callback_data="set_tone"),
        types.InlineKeyboardButton("🌍 Язык", callback_data="set_lang"),
        types.InlineKeyboardButton("🔔 Напоминания", callback_data="reminders"),
        types.InlineKeyboardButton("🧹 Сброс памяти", callback_data="reset_mem"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="back_main")
    )
    return kb

def feedback_kb():
    kb = types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        types.InlineKeyboardButton("👍 Полезно", callback_data="fb_useful"),
        types.InlineKeyboardButton("😐 Нейтрально", callback_data="fb_neutral"),
        types.InlineKeyboardButton("👎 Не помогло", callback_data="fb_bad")
    )
    return kb

def practice_kb():
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🫁 Дыхание 4-7-8", callback_data="breath_478"),
        types.InlineKeyboardButton("🌊 Квадратное", callback_data="breath_box"),
        types.InlineKeyboardButton("🧘 Сканирование тела", callback_data="body_scan"),
        types.InlineKeyboardButton("⬅️ Назад", callback_data="back_main")
    )
    return kb

def moods_kb():
    kb = types.InlineKeyboardMarkup(row_width=5)
    kb.add(
        types.InlineKeyboardButton("😊", callback_data="mood_😊"),
        types.InlineKeyboardButton("😌", callback_data="mood_😌"),
        types.InlineKeyboardButton("😐", callback_data="mood_😐"),
        types.InlineKeyboardButton("😔", callback_data="mood_😔"),
        types.InlineKeyboardButton("😡", callback_data="mood_😡"),
        types.InlineKeyboardButton("😰", callback_data="mood_😰"),
        types.InlineKeyboardButton("🥰", callback_data="mood_🥰"),
        types.InlineKeyboardButton("😴", callback_data="mood_😴"),
        types.InlineKeyboardButton("🤔", callback_data="mood_🤔"),
        types.InlineKeyboardButton("💪", callback_data="mood_💪")
    )
    return kb

# ============================================================
# ОПЛАТА (ОБРАБОТЧИКИ)
# ============================================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    uid = m.from_user.id
    name = m.from_user.first_name or "друг"
    register_user(uid, m.from_user.username or name)
    user = get_user(uid)
    bot_name = user[9] if user else "Наставник"
    bot.send_message(m.chat.id,
        f"Здравствуйте, {name}! 🌿\n\n"
        f"Я — {bot_name}. Я здесь, чтобы бережно поддержать вас.\n\n"
        "Меню внизу экрана. Выбирайте, с чего начать 💚",
        reply_markup=main_kb())

@bot.message_handler(commands=['subscribe'])
def cmd_subscribe(m):
    uid = m.from_user.id
    send_payment_options(uid)

@bot.message_handler(func=lambda m: m.text == "💎 Подписка")
def btn_subscription(m):
    uid = m.from_user.id
    if has_active_subscription(uid):
        user = get_user(uid)
        until = datetime.fromtimestamp(user[11]).strftime('%d.%m.%Y')
        bot.send_message(m.chat.id, f"✅ У вас уже есть активная подписка до {until}. Спасибо за поддержку! 💚")
    else:
        send_payment_options(uid)

def send_payment_options(chat_id):
    """Показывает пользователю варианты оплаты."""
    text = "Выберите удобный способ оплаты подписки:"
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        types.InlineKeyboardButton("⭐ Telegram Stars", callback_data="pay_stars"),
        types.InlineKeyboardButton("💳 Банковская карта (ЮKassa)", callback_data="pay_yookassa"),
        types.InlineKeyboardButton("⚡ СБП (по ссылке)", callback_data="pay_sbp")
    )
    bot.send_message(chat_id, text, reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith('pay_'))
def handle_payment_choice(c):
    uid = c.from_user.id
    choice = c.data
    
    if choice == "pay_stars":
        send_stars_invoice(uid)
    elif choice == "pay_yookassa":
        send_yookassa_invoice(uid)
    elif choice == "pay_sbp":
        bot.send_message(uid, f"Для оплаты через СБП перейдите по ссылке:\n{PAYMENT_LINK_SBP}")
    
    bot.answer_callback_query(c.id)

def send_stars_invoice(chat_id):
    try:
        prices = [types.LabeledPrice(label=f"Подписка на {SUBSCRIPTION_DAYS} дней", amount=SUBSCRIPTION_PRICE_STARS)]
        bot.send_invoice(
            chat_id=chat_id,
            title=f"Подписка «Наставник» на {SUBSCRIPTION_DAYS} дней",
            description=f"Неограниченный доступ ко всем функциям на {SUBSCRIPTION_DAYS} дней.",
            invoice_payload=f"subscription_{SUBSCRIPTION_DAYS}days",
            provider_token="",
            currency="XTR",
            prices=prices,
            start_parameter="subscription"
        )
    except Exception as e:
        bot.send_message(chat_id, "😔 Не удалось создать счёт для оплаты. Попробуйте позже.")
        print(f"[INVOICE ERROR] {e}")

def send_yookassa_invoice(chat_id):
    """Пример отправки счета через ЮKassa."""
    if not YOOKASSA_PROVIDER_TOKEN:
        bot.send_message(chat_id, "Оплата картой временно недоступна.")
        return
    try:
        # Здесь нужно использовать API ЮKassa для создания платежа
        # Это упрощенный пример, реальная реализация требует больше кода
        price_rub = SUBSCRIPTION_PRICE_STARS * 2  # Примерный курс
        bot.send_message(chat_id, f"Для оплаты картой перейдите по ссылке: [ссылка на оплату]")
        # В реальном коде: создать платеж через API ЮKassa и получить confirmation_url
    except Exception as e:
        bot.send_message(chat_id, "😔 Не удалось создать счёт. Попробуйте позже.")

@bot.pre_checkout_query_handler(func=lambda query: True)
def process_pre_checkout(pre_checkout_query):
    bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@bot.message_handler(content_types=['successful_payment'])
def process_successful_payment(message):
    uid = message.from_user.id
    new_subscription_until = time.time() + (SUBSCRIPTION_DAYS * 24 * 60 * 60)
    db_exec('UPDATE users SET subscription_until=? WHERE user_id=?', (new_subscription_until, uid))
    until_date = datetime.fromtimestamp(new_subscription_until).strftime('%d.%m.%Y')
    bot.send_message(
        message.chat.id,
        f"🎉 *Оплата прошла успешно!*\n\n"
        f"Ваша подписка активирована до *{until_date}*.\n\n"
        f"Теперь вам доступны все функции без ограничений. Спасибо за доверие! 💚",
        parse_mode='Markdown',
        reply_markup=main_kb()
    )

# ============================================================
# ОСТАЛЬНАЯ ЛОГИКА (команды, кнопки, диалог)
# ============================================================
# ... (Здесь должен быть весь остальной код из вашего прошлого файла bot.py)
# ============================================================

if __name__ == '__main__':
    init_db()
    print("✅ БД инициализирована")
    threading.Thread(target=reminder_worker, daemon=True).start()
    print("🚀 Бот запущен...")
    bot.polling(none_stop=True)
