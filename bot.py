import os
import httpx
from aiogram import Bot, Dispatcher, types
from aiogram.types import InputFile
from aiogram.filters import Command

BOT_TOKEN = os.getenv("7568864397:AAEI4RwDx7Gk_HMnmeCCYMaLkVJTMqKOfMw")
MINIMAX_API_KEY = os.getenv("sk-api-4zpied8wxig2ih39-Gmu02eiJ68sLYQjLaxGRRDRTo4kvPt0hU_vfi5YtmFXxcjxCahW9IPJH2qN-8MAHvAWqOnSy4kLF2yywYOwmgQWPvL0ph_t5vBlw2A")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Храним временный mp3 по пользователю
user_voice = {}

@dp.message_handler(content_types=['voice', 'audio'])
async def save_voice(message: types.Message):
    file_id = message.voice.file_id if message.voice else message.audio.file_id
    file = await bot.get_file(file_id)
    local_path = f"{message.from_user.id}_sample.mp3"
    await bot.download_file(file.file_path, local_path)
    user_voice[message.from_user.id] = local_path
    await message.reply("Голос сохранён! Отправьте текст, который нужно озвучить этим голосом.")

@dp.message_handler(content_types=[types.ContentType.TEXT])
async def handle_text(message: types.Message):
    user_id = message.from_user.id
    if user_id not in user_voice:
        await message.reply("Сначала пришлите голосовое сообщение или mp3.")
        return

    text = message.text
    sample_path = user_voice[user_id]

    # Запрос к API Minimax
    url = "https://api.minimax.example.com/v1/clone"  # подставь актуальный
    headers = {
        "Authorization": f"Bearer {MINIMAX_API_KEY}"
    }
    files = {
        "voice_sample": open(sample_path, "rb")
    }
    data = {"text": text}

    async with httpx.AsyncClient() as client:
        resp = await client.post(url, headers=headers, files=files, data=data)

    if resp.status_code == 200:
        output_path = f"{user_id}_out.mp3"
        with open(output_path, "wb") as f:
            f.write(resp.content)
        await bot.send_audio(message.chat.id, InputFile(output_path))
    else:
        await message.reply("Ошибка при генерации голоса.")

if __name__ == "__main__":
    from aiogram import executor
    executor.start_polling(dp)
