import asyncio
import logging
import os
import sys
import json
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message
import httpx

# Загрузка переменных из .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
LOG_LEVEL = os.getenv("LOG_LEVEL", "DEBUG").upper()

if not TELEGRAM_TOKEN or not OPENROUTER_API_KEY:
    raise ValueError("TELEGRAM_TOKEN и OPENROUTER_API_KEY обязательны в .env")

# ---------- Настройки OpenRouter ----------
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
MODEL = "openrouter/free"      # автоматически подбирает любую бесплатную модель

# Прокси (опционально)
TELEGRAM_PROXY = os.getenv("TELEGRAM_PROXY")        # socks5://user:pass@host:port
OPENROUTER_PROXY = os.getenv("OPENROUTER_PROXY")    # http://host:port

# Системный промпт юриста
SYSTEM_PROMPT = (
    "Ты — юридический помощник, специализирующийся на законодательстве Российской Федерации. "
    "Твои задачи:\n"
    "- Отвечать строго по существу, основываясь на действующих законах РФ.\n"
    "- В ответе обязательно указывать конкретные статьи (с номером и названием закона: УК РФ, КоАП РФ, ГК РФ и т.д.).\n"
    "- Описывать возможные наказания, штрафы, сроки и другие правовые последствия.\n"
    "- Если вопрос не относится к праву РФ или данных недостаточно — вежливо объясни, что работаешь только с российским законодательством.\n"
    "- Отвечай на русском языке, чётко и без лишних отступлений."
)

# ---------- Логирование ----------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.DEBUG),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ---------- HTTP-клиент для OpenRouter ----------
http_kwargs = {"timeout": httpx.Timeout(60.0)}
if OPENROUTER_PROXY:
    http_kwargs["proxy"] = OPENROUTER_PROXY
http_client = httpx.AsyncClient(**http_kwargs)

# ---------- Telegram-бот ----------
bot_kwargs = {"token": TELEGRAM_TOKEN}
if TELEGRAM_PROXY:
    bot_kwargs["proxy"] = TELEGRAM_PROXY
bot = Bot(**bot_kwargs)
dp = Dispatcher()

async def ask_openrouter(user_text: str) -> str:
    """Отправляет запрос к OpenRouter и возвращает ответ модели."""
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": MODEL,               # openrouter/free – автоматический выбор
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ],
        "temperature": 0.3,
        "max_tokens": 1500,
    }

    logging.debug(f"Отправка POST-запроса к {OPENROUTER_URL}")
    response = await http_client.post(OPENROUTER_URL, json=payload, headers=headers)
    response.raise_for_status()  # выбросит исключение при ошибке HTTP
    data = response.json()

    # Извлекаем ответ (формат совместим с OpenAI)
    reply = data["choices"][0]["message"]["content"].strip()
    logging.debug(f"Получен ответ длиной {len(reply)} символов")
    return reply

# ---------- Обработчики команд ----------
@dp.message(Command("start"))
async def start_command(message: Message):
    logging.info(f"Пользователь {message.from_user.id} запустил бота")
    await message.answer(
        "👋 Здравствуйте! Я юридический помощник по законам РФ.\n"
        "Опишите ситуацию или задайте вопрос — я назову статьи и возможные последствия.\n"
        "⚡ Работаю на автоматической бесплатной модели OpenRouter."
    )

@dp.message()
async def handle_legal_question(message: Message):
    user_text = message.text
    user_id = message.from_user.id
    logging.info(f"Вопрос от {user_id}: {user_text}")

    await bot.send_chat_action(message.chat.id, "typing")

    try:
        reply = await ask_openrouter(user_text)
        logging.info(f"Ответ бота для {user_id}: {reply[:200]}...")

        # Telegram допускает сообщения длиной до 4096 символов
        if len(reply) > 4096:
            for i in range(0, len(reply), 4096):
                await message.answer(reply[i:i+4096])
        else:
            await message.answer(reply)

    except Exception as e:
        logging.exception("Ошибка при запросе к OpenRouter")
        await message.answer("⚠️ Произошла ошибка при обработке запроса. Попробуйте позже.")

# ---------- Запуск ----------
async def main():
    logging.info("Бот запускается...")
    try:
        await dp.start_polling(bot)
    finally:
        await http_client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
