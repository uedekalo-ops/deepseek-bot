import os
import time
import sqlite3
import threading
import telebot
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime, timedelta

# ============================================================
# ЗАГРУЗКА НАСТРОЕК
# ============================================================
load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

MAX_HISTORY = 10
RATE_LIMIT = 2
DB_FILE = 'bot_memory.db'
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
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        role TEXT, content TEXT, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT,
        first_seen REAL, last_seen REAL, message_count INTEGER DEFAULT 0,
        bot_name TEXT DEFAULT 'Наставник', tone TEXT DEFAULT 'soft',
        gender TEXT DEFAULT 'neutral', lang TEXT DEFAULT 'ru')''')
    c.execute('''CREATE TABLE IF NOT EXISTS moods (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        mood TEXT, note TEXT, timestamp REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        text TEXT, remind_at REAL, created_at REAL, active INTEGER DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        message_id INTEGER, rating TEXT, timestamp REAL)''')
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

def get_history(uid, limit=MAX_HISTORY):
    rows = db_exec('SELECT role, content FROM history WHERE user_id=? ORDER BY id DESC LIMIT ?',
                   (uid, limit), fetch=True)
    return [{"role": r, "content": c} for r, c in reversed(rows)]

def clear_history(uid):
    db_exec('DELETE FROM history WHERE user_id=?', (uid,))

def register_user(uid, username):
    now = time.time()
    db_exec('''INSERT INTO users (user_id, username, first_seen, last_seen, message_count)
        VALUES (?,?,?,?,1) ON CONFLICT(user_id) DO UPDATE SET
        last_seen=?, message_count=message_count+1''',
        (uid, username, now, now, now))

def get_user(uid):
    rows = db_exec('SELECT * FROM users WHERE user_id=?', (uid,), fetch=True)
    return rows[0] if rows else None

def update_user_setting(uid, field, value):
    db_exec(f'UPDATE users SET {field}=? WHERE user_id=?', (value, uid))

# ============================================================
# RATE LIMITING
# ============================================================
user_last = {}
def is_limited(uid):
    now = time.time()
    if uid in user_last and now - user_last[uid] < RATE_LIMIT:
        return True
    user_last[uid] = now
    return False

# ============================================================
# КЛАВИАТУРЫ
# ============================================================
def main_kb():
    kb = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        telebot.types.KeyboardButton("💬 Поговорить"),
        telebot.types.KeyboardButton("🧘 Практика"),
        telebot.types.KeyboardButton("📔 Дневник"),
        telebot.types.KeyboardButton("📊 Прогресс"),
        telebot.types.KeyboardButton("🧪 Тест"),
        telebot.types.KeyboardButton("⚙️ Настройки"),
        telebot.types.KeyboardButton("🆘 Мне плохо"),
        telebot.types.KeyboardButton("❓ Помощь")
    )
    return kb

def settings_kb():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("✏️ Имя бота", callback_data="set_name"),
        telebot.types.InlineKeyboardButton("🎭 Тон", callback_data="set_tone"),
        telebot.types.InlineKeyboardButton("🌍 Язык", callback_data="set_lang"),
        telebot.types.InlineKeyboardButton("🔔 Напоминания", callback_data="reminders"),
        telebot.types.InlineKeyboardButton("🧹 Сброс памяти", callback_data="reset_mem"),
        telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data="back_main")
    )
    return kb

def feedback_kb():
    kb = telebot.types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        telebot.types.InlineKeyboardButton("👍 Полезно", callback_data="fb_useful"),
        telebot.types.InlineKeyboardButton("😐 Нейтрально", callback_data="fb_neutral"),
        telebot.types.InlineKeyboardButton("👎 Не помогло", callback_data="fb_bad")
    )
    return kb

def practice_kb():
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("🫁 Дыхание 4-7-8", callback_data="breath_478"),
        telebot.types.InlineKeyboardButton("🌊 Квадратное", callback_data="breath_box"),
        telebot.types.InlineKeyboardButton("🧘 Сканирование тела", callback_data="body_scan"),
        telebot.types.InlineKeyboardButton("⬅️ Назад", callback_data="back_main")
    )
    return kb

def moods_kb():
    kb = telebot.types.InlineKeyboardMarkup(row_width=5)
    kb.add(
        telebot.types.InlineKeyboardButton("😊", callback_data="mood_😊"),
        telebot.types.InlineKeyboardButton("😌", callback_data="mood_😌"),
        telebot.types.InlineKeyboardButton("😐", callback_data="mood_😐"),
        telebot.types.InlineKeyboardButton("😔", callback_data="mood_😔"),
        telebot.types.InlineKeyboardButton("😡", callback_data="mood_😡"),
        telebot.types.InlineKeyboardButton("😰", callback_data="mood_😰"),
        telebot.types.InlineKeyboardButton("🥰", callback_data="mood_🥰"),
        telebot.types.InlineKeyboardButton("😴", callback_data="mood_😴"),
        telebot.types.InlineKeyboardButton("🤔", callback_data="mood_🤔"),
        telebot.types.InlineKeyboardButton("💪", callback_data="mood_💪")
    )
    return kb

# ============================================================
# КОМАНДЫ
# ============================================================
@bot.message_handler(commands=['start'])
def cmd_start(m):
    uid = m.from_user.id
    name = m.from_user.first_name or "друг"
    register_user(uid, m.from_user.username or name)
    user = get_user(uid)
    bot_name = user[5] if user else "Наставник"
    bot.send_message(m.chat.id,
        f"Здравствуйте, {name}! 🌿\n\n"
        f"Я — {bot_name}. Я здесь, чтобы бережно поддержать вас.\n\n"
        "Меню внизу экрана. Выбирайте, с чего начать 💚",
        reply_markup=main_kb())

@bot.message_handler(commands=['help'])
def cmd_help(m):
    bot.send_message(m.chat.id,
        "📚 *Что я умею:*\n\n"
        "💬 Поговорить — бережный диалог\n"
        "🧘 Практика — дыхание и релаксация\n"
        "📔 Дневник — запись настроения\n"
        "📊 Прогресс — статистика\n"
        "🧪 Тест — оценка состояния\n"
        "⚙️ Настройки — имя, тон, язык\n"
        "🆘 Мне плохо — быстрая помощь\n\n"
        "Команды: /start /help /reset /stats",
        parse_mode='Markdown')

@bot.message_handler(commands=['reset'])
def cmd_reset(m):
    clear_history(m.from_user.id)
    bot.send_message(m.chat.id, "🧹 Память очищена. Начнём заново?", reply_markup=main_kb())

@bot.message_handler(commands=['stats'])
def cmd_stats(m):
    uid = m.from_user.id
    user = get_user(uid)
    if user:
        count, first = user[4], user[3]
        days = int((time.time() - first) / 86400) + 1
        moods = db_exec('SELECT COUNT(*) FROM moods WHERE user_id=?', (uid,), fetch=True)
        bot.send_message(m.chat.id,
            f"📊 *Ваш прогресс:*\n\n"
            f"💬 Сообщений: {count}\n"
            f"📅 Дней со мной: {days}\n"
            f"📔 Записей настроения: {moods[0][0] if moods else 0}",
            parse_mode='Markdown')

# ============================================================
# КНОПКИ ГЛАВНОГО МЕНЮ
# ============================================================
@bot.message_handler(func=lambda m: m.text == "💬 Поговорить")
def btn_talk(m):
    bot.send_message(m.chat.id, "Я слушаю. Расскажите, что вас беспокоит? 💚")

@bot.message_handler(func=lambda m: m.text == "🧘 Практика")
def btn_practice(m):
    bot.send_message(m.chat.id, "Выберите практику:", reply_markup=practice_kb())

@bot.message_handler(func=lambda m: m.text == "📔 Дневник")
def btn_diary(m):
    bot.send_message(m.chat.id,
        "Как вы себя чувствуете прямо сейчас? Выберите эмодзи:",
        reply_markup=moods_kb())

@bot.message_handler(func=lambda m: m.text == "📊 Прогресс")
def btn_progress(m):
    cmd_stats(m)

@bot.message_handler(func=lambda m: m.text == "⚙️ Настройки")
def btn_settings(m):
    bot.send_message(m.chat.id, "⚙️ Настройки бота:", reply_markup=settings_kb())

@bot.message_handler(func=lambda m: m.text == "🆘 Мне плохо")
def btn_sos(m):
    sos = (
        "🆘 *Я рядом. Давайте подышим вместе.*\n\n"
        "1. Сядьте удобно, поставьте ноги на пол.\n"
        "2. Вдох через нос — 4 секунды.\n"
        "3. Задержка — 7 секунд.\n"
        "4. Выдох через рот — 8 секунд.\n"
        "5. Повторите 4 раза.\n\n"
        "💚 Если совсем тяжело — позвоните на телефон доверия:\n"
        "🇷🇺 8-800-2000-122 (бесплатно, 24/7)"
    )
    bot.send_message(m.chat.id, sos, parse_mode='Markdown')

@bot.message_handler(func=lambda m: m.text == "❓ Помощь")
def btn_help(m):
    cmd_help(m)

@bot.message_handler(func=lambda m: m.text == "🧪 Тест")
def btn_test(m):
    uid = m.from_user.id
    user_states[uid] = {'test': 'anxiety', 'step': 0, 'score': 0}
    bot.send_message(m.chat.id,
        "🧪 *Тест на уровень тревожности*\n\n"
        "Отвечайте «да» или «нет».\n\n"
        "1/7: Часто ли вы чувствуете напряжение без причины?")

# ============================================================
# INLINE CALLBACKS
# ============================================================
@bot.callback_query_handler(func=lambda c: True)
def handle_callback(c):
    uid = c.from_user.id
    data = c.data

    if data.startswith("fb_"):
        db_exec('INSERT INTO feedback (user_id, rating, timestamp) VALUES (?,?,?)',
                (uid, data, time.time()))
        bot.answer_callback_query(c.id, "Спасибо за отзыв! 💚")
        try:
            bot.edit_message_reply_markup(c.message.chat.id, c.message.message_id, reply_markup=None)
        except Exception:
            pass
        return

    if data.startswith("mood_"):
        mood = data.replace("mood_", "")
        db_exec('INSERT INTO moods (user_id, mood, timestamp) VALUES (?,?,?)',
                (uid, mood, time.time()))
        bot.answer_callback_query(c.id, "Записано!")
        try:
            bot.edit_message_text(f"📔 Настроение записано: {mood}\n\nХотите добавить заметку? Напишите текст или /skip.",
                                  c.message.chat.id, c.message.message_id)
        except Exception:
            pass
        user_states[uid] = {'awaiting': 'mood_note'}
        return

    if data == "breath_478":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
            "🫁 *Дыхание 4-7-8*\n\nВдох 4 сек → Задержка 7 сек → Выдох 8 сек.\n\nСделайте 4 цикла.")
        return
    if data == "breath_box":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
            "🌊 *Квадратное дыхание*\n\nВдох 4 → Задержка 4 → Выдох 4 → Задержка 4.\n\nПовторите 4 раза.")
        return
    if data == "body_scan":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
            "🧘 *Сканирование тела*\n\n"
            "Сядьте удобно. Закройте глаза.\n"
            "Пройдитесь вниманием: стопы → голени → колени → бёдра → живот → грудь → плечи → шея → лицо.\n"
            "Задержитесь на 10 секунд в каждой зоне. Что чувствуете?")
        return

    if data == "set_name":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id, "Как вы хотите меня называть? Напишите имя.")
        user_states[uid] = {'awaiting': 'bot_name'}
        return
    if data == "set_tone":
        kb = telebot.types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            telebot.types.InlineKeyboardButton("🌸 Мягкий", callback_data="tone_soft"),
            telebot.types.InlineKeyboardButton("⚡ Прямой", callback_data="tone_direct"),
            telebot.types.InlineKeyboardButton("🎓 Наставник", callback_data="tone_mentor"),
            telebot.types.InlineKeyboardButton("😊 Друг", callback_data="tone_friend")
        )
        try:
            bot.edit_message_text("Выберите тон общения:", c.message.chat.id, c.message.message_id, reply_markup=kb)
        except Exception:
            pass
        return
    if data.startswith("tone_"):
        tone = data.replace("tone_", "")
        update_user_setting(uid, "tone", tone)
        bot.answer_callback_query(c.id, f"Тон: {tone}")
        try:
            bot.edit_message_text(f"✅ Тон общения изменён: {tone}", c.message.chat.id, c.message.message_id)
        except Exception:
            pass
        return
    if data == "set_lang":
        kb = telebot.types.InlineKeyboardMarkup(row_width=2)
        kb.add(
            telebot.types.InlineKeyboardButton("🇷🇺 Русский", callback_data="lang_ru"),
            telebot.types.InlineKeyboardButton("🇬🇧 English", callback_data="lang_en")
        )
        try:
            bot.edit_message_text("Выберите язык:", c.message.chat.id, c.message.message_id, reply_markup=kb)
        except Exception:
            pass
        return
    if data.startswith("lang_"):
        lang = data.replace("lang_", "")
        update_user_setting(uid, "lang", lang)
        bot.answer_callback_query(c.id, f"Язык: {lang}")
        try:
            bot.edit_message_text(f"✅ Язык изменён: {lang}", c.message.chat.id, c.message.message_id)
        except Exception:
            pass
        return
    if data == "reminders":
        bot.answer_callback_query(c.id)
        bot.send_message(c.message.chat.id,
            "🔔 *Напоминания*\n\n"
            "Напишите в формате:\n"
            "`Напоминание | ЧЧ:ММ`\n\n"
            "Например: `Выпить таблетку | 09:00`")
        user_states[uid] = {'awaiting': 'reminder'}
        return
    if data == "reset_mem":
        clear_history(uid)
        bot.answer_callback_query(c.id, "Память очищена!")
        try:
            bot.edit_message_text("🧹 Память очищена.", c.message.chat.id, c.message.message_id)
        except Exception:
            pass
        return
    if data == "back_main":
        try:
            bot.edit_message_text("Главное меню — используйте кнопки внизу 👇",
                                  c.message.chat.id, c.message.message_id)
        except Exception:
            pass

# ============================================================
# ОТПРАВКА ДЛИННЫХ СООБЩЕНИЙ (С РАЗБИВКОЙ)
# ============================================================
def send_long_message(chat_id, text, with_feedback=False):
    """Отправляет сообщение, разбивая на части, если оно длиннее 4000 символов."""
    LIMIT = 4000
    if len(text) <= LIMIT:
        if with_feedback:
            bot.send_message(chat_id, text, reply_markup=feedback_kb())
        else:
            bot.send_message(chat_id, text)
        return

    # Разбиваем текст на части
    parts = []
    for i in range(0, len(text), LIMIT):
        parts.append(text[i:i+LIMIT])

    # Отправляем все части, кнопки — к последней
    for idx, part in enumerate(parts):
        is_last = (idx == len(parts) - 1)
        if is_last and with_feedback:
            bot.send_message(chat_id, part, reply_markup=feedback_kb())
        else:
            bot.send_message(chat_id, part)
        time.sleep(0.3)  # небольшая пауза, чтобы не словить лимиты Telegram

# ============================================================
# ОБРАБОТКА ТЕКСТА (в т.ч. состояния)
# ============================================================
@bot.message_handler(func=lambda m: True)
def handle_all(m):
    uid = m.from_user.id
    text = m.text.strip() if m.text else ""

    # --- Состояния ---
    if uid in user_states:
        state = user_states[uid]

        if state.get('awaiting') == 'mood_note':
            if text.lower() != '/skip':
                db_exec('UPDATE moods SET note=? WHERE user_id=? ORDER BY id DESC LIMIT 1', (text, uid))
                bot.send_message(m.chat.id, "📝 Заметка сохранена. Спасибо, что делитесь 💚", reply_markup=main_kb())
            else:
                bot.send_message(m.chat.id, "Ок, без заметки.", reply_markup=main_kb())
            del user_states[uid]
            return

        if state.get('awaiting') == 'bot_name':
            update_user_setting(uid, "bot_name", text[:30])
            bot.send_message(m.chat.id, f"✅ Теперь меня зовут {text[:30]}. Приятно познакомиться!", reply_markup=main_kb())
            del user_states[uid]
            return

        if state.get('awaiting') == 'reminder':
            try:
                parts = text.split('|')
                remind_text = parts[0].strip()
                remind_time = parts[1].strip()
                h, mi = map(int, remind_time.split(':'))
                now = datetime.now()
                target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
                if target < now:
                    target += timedelta(days=1)
                db_exec('INSERT INTO reminders (user_id, text, remind_at, created_at) VALUES (?,?,?,?)',
                        (uid, remind_text, target.timestamp(), time.time()))
                bot.send_message(m.chat.id,
                    f"🔔 Напоминание сохранено:\n*{remind_text}*\nВ {h:02d}:{mi:02d}",
                    parse_mode='Markdown', reply_markup=main_kb())
            except Exception:
                bot.send_message(m.chat.id, "❌ Не понял формат. Пример: `Выпить таблетку | 09:00`", parse_mode='Markdown')
            del user_states[uid]
            return

        if state.get('test') == 'anxiety':
            answer = text.lower()
            if answer in ['да', 'yes', 'y', '1']:
                state['score'] += 1
            state['step'] += 1
            questions = [
                "2/7: Трудно ли вам расслабиться?",
                "3/7: Часто ли вы прокручиваете мысли по кругу?",
                "4/7: Бывает ли, что сердце бьётся чаще без причины?",
                "5/7: Сложно ли засыпать из-за мыслей?",
                "6/7: Чувствуете ли вы раздражение по мелочам?",
                "7/7: Ощущаете ли вы усталость даже после отдыха?"
            ]
            if state['step'] < 7:
                bot.send_message(m.chat.id, questions[state['step'] - 1])
            else:
                score = state['score']
                if score <= 2:
                    result = "🟢 *Низкий уровень тревожности.* Вы справляетесь хорошо."
                elif score <= 4:
                    result = "🟡 *Средний уровень.* Стоит уделить время практикам расслабления."
                else:
                    result = "🔴 *Высокий уровень.* Рекомендую обратиться к специалисту и попробовать практики в разделе 🧘."
                bot.send_message(m.chat.id,
                                 f"📊 *Результат теста:*\n\n{result}\n\n_Это не диагноз, а лишь ориентир._",
                                 parse_mode='Markdown', reply_markup=main_kb())
                del user_states[uid]
            return

    # --- Основной диалог с DeepSeek ---
    if not text:
        return

    if is_limited(uid):
        bot.reply_to(m, "⏳ Подождите пару секунд.")
        return

    register_user(uid, m.from_user.username or m.from_user.first_name or "user")
    add_message(uid, "user", text)
    bot.send_chat_action(m.chat.id, 'typing')

    user = get_user(uid)
    bot_name = user[5] if user else "Наставник"
    tone = user[6] if user else "soft"

    tone_map = {
        "soft": "Говори мягко, бережно, с эмпатией.",
        "direct": "Говори прямо, чётко, без лишних слов.",
        "mentor": "Говори как мудрый наставник, с примерами и метафорами.",
        "friend": "Говори как близкий друг, тепло и неформально."
    }
    personal_prompt = SYSTEM_PROMPT + f"\n\n[Твоё имя: {bot_name}. {tone_map.get(tone, '')}]"

    try:
        history = get_history(uid)
        messages = [{"role": "system", "content": personal_prompt}] + history
        response = client.chat.completions.create(
            model="deepseek-chat", messages=messages,
            stream=False, temperature=0.7, max_tokens=2000
        )
        answer = response.choices[0].message.content
        add_message(uid, "assistant", answer)

        # Отправляем с разбивкой на части (кнопки — к последней)
        send_long_message(m.chat.id, answer, with_feedback=True)

    except Exception as e:
        err = str(e)
        if "402" in err or "Insufficient" in err:
            bot.reply_to(m, "💳 Средства закончились. Скоро пополним.")
        elif "Connection" in err or "Timeout" in err:
            bot.reply_to(m, "🌐 Связь нестабильна. Попробуйте через минуту.")
        else:
            bot.reply_to(m, "😔 Небольшая заминка. Попробуйте ещё раз.")
            print(f"[ERR] {err}")

# ============================================================
# ФОНОВАЯ ПРОВЕРКА НАПОМИНАНИЙ
# ============================================================
def reminder_worker():
    while True:
        try:
            now = time.time()
            rows = db_exec('SELECT id, user_id, text FROM reminders WHERE active=1 AND remind_at<=?',
                           (now,), fetch=True)
            for rid, uid, txt in rows:
                try:
                    bot.send_message(uid, f"🔔 *Напоминание:*\n\n{txt}", parse_mode='Markdown')
                except Exception:
                    pass
                db_exec('UPDATE reminders SET active=0 WHERE id=?', (rid,))
        except Exception as e:--
            print(f"[REMINDER] {e}")
        time.sleep(30)

# ============================================================
# ЗАПУСК
# ============================================================
if __name__ == '__main__':
    init_db()
    print("✅ БД инициализирована")
    threading.Thread(target=reminder_worker, daemon=True).start()
    print("🚀 Бот запущен...")
    bot.polling(none_stop=True)
