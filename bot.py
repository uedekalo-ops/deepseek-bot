import os
import telebot
from openai import OpenAI
from dotenv import load_dotenv

# Загружаем переменные из файла .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

# --- ЗДЕСЬ ЧИТАЕТСЯ ВАШ ПРОМТ ИЗ ФАЙЛА ---
with open('promtnastavnik.txt', 'r', encoding='utf-8') as f:
    SYSTEM_PROMPT = f.read()

# Инициализация бота
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url="https://api.deepseek.com")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я бот с твоим промтом. Напиши мне что-нибудь.")

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    try:
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT}, # Сюда подставляется ваш промт
                {"role": "user", "content": message.text}
            ],
            stream=False
        )
        bot.reply_to(message, response.choices[0].message.content)
    except Exception as e:
        bot.reply_to(message, f"Ошибка: {e}")

print("Бот запущен...")
bot.polling(none_stop=True)