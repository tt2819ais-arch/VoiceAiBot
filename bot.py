import os
import logging
from typing import Dict, Optional
from pathlib import Path

import requests
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters
)
from pydub import AudioSegment
import ffmpeg

# Загрузка переменных окружения
load_dotenv()

# Конфигурация
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '7568864397:AAEI4RwDx7Gk_HMnmeCCYMaLkVJTMqKOfMw')
MINIMAX_API_KEY = os.getenv('MINIMAX_API_KEY', 'sk-api-4zpied8wxig2ih39-Gmu02eiJ68sLYQjLaxGRRDRTo4kvPt0hU_vfi5YtmFXxcjxCahW9IPJH2qN-8MAHvAWqOnSy4kLF2yywYOwmgQWPvL0ph_t5vBlw2A')
MINIMAX_VOICE_API_URL = "https://api.minimax.chat/v1/voice"

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Хранилище состояний пользователей
user_data: Dict[int, Dict] = {}

class VoiceBot:
    def __init__(self):
        self.supported_voice_formats = ['ogg', 'mp3', 'm4a', 'wav']
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик команды /start"""
        keyboard = [
            [InlineKeyboardButton("🎤 Отправить голосовое", callback_data='send_voice')],
            [InlineKeyboardButton("📝 Отправить текст", callback_data='send_text')],
            [InlineKeyboardButton("ℹ️ Помощь", callback_data='help')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        welcome_text = (
            "👋 Привет! Я бот для генерации голосовых сообщений.\n\n"
            "Вы можете:\n"
            "1. Отправить голосовое сообщение (OGG/MP3/M4A/WAV)\n"
            "2. Ввести текст для преобразования в голос\n"
            "3. Выбрать голос для генерации\n\n"
            "Нажмите кнопку ниже или просто отправьте голосовое/текст!"
        )
        
        await update.message.reply_text(welcome_text, reply_markup=reply_markup)
    
    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик inline кнопок"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        if query.data == 'send_voice':
            await query.edit_message_text(
                "🎤 Пожалуйста, отправьте голосовое сообщение или аудиофайл (OGG/MP3/M4A/WAV)"
            )
            user_data[user_id] = {'mode': 'voice_input'}
            
        elif query.data == 'send_text':
            await query.edit_message_text(
                "📝 Пожалуйста, введите текст для преобразования в голос:"
            )
            user_data[user_id] = {'mode': 'text_input'}
            
        elif query.data == 'help':
            help_text = (
                "ℹ️ *Помощь*\n\n"
                "1. *Отправка голосового*: просто запишите или отправьте аудиофайл\n"
                "2. *Отправка текста*: введите текст, который нужно преобразовать\n"
                "3. *Поддерживаемые форматы*: OGG, MP3, M4A, WAV\n"
                "4. *Лимиты*: до 60 секунд аудио, до 1000 символов текста\n\n"
                "После обработки вы получите сгенерированное голосовое сообщение!"
            )
            await query.edit_message_text(help_text, parse_mode='Markdown')
            
        elif query.data.startswith('voice_'):
            # Выбор голоса
            voice_id = query.data.split('_')[1]
            if user_id in user_data and 'text' in user_data[user_id]:
                user_data[user_id]['voice_id'] = voice_id
                await self.generate_and_send_voice(user_id, query.message, context)
    
    async def handle_voice(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик голосовых сообщений"""
        user_id = update.message.from_user.id
        
        try:
            # Получаем файл голосового сообщения
            voice_file = await update.message.voice.get_file()
            file_path = f"temp_voice_{user_id}.ogg"
            
            # Скачиваем файл
            await voice_file.download_to_drive(file_path)
            
            # Конвертируем в MP3 если нужно
            converted_file = await self.convert_audio(file_path)
            
            # Транскрибируем аудио
            text = await self.transcribe_audio(converted_file)
            
            if text:
                user_data[user_id] = {
                    'text': text,
                    'mode': 'voice_processed'
                }
                
                # Предлагаем выбрать голос
                await self.show_voice_selection(update.message, text)
            else:
                await update.message.reply_text("❌ Не удалось распознать речь. Попробуйте еще раз.")
            
            # Удаляем временные файлы
            os.remove(file_path)
            if converted_file != file_path:
                os.remove(converted_file)
                
        except Exception as e:
            logger.error(f"Error processing voice: {e}")
            await update.message.reply_text("❌ Ошибка обработки голосового сообщения")
    
    async def handle_audio(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик аудиофайлов"""
        user_id = update.message.from_user.id
        
        try:
            audio_file = await update.message.audio.get_file()
            file_ext = update.message.audio.file_name.split('.')[-1].lower()
            file_path = f"temp_audio_{user_id}.{file_ext}"
            
            await audio_file.download_to_drive(file_path)
            
            # Конвертируем если нужно
            if file_ext not in ['mp3', 'wav']:
                converted_file = await self.convert_audio(file_path)
            else:
                converted_file = file_path
            
            # Транскрибируем
            text = await self.transcribe_audio(converted_file)
            
            if text:
                user_data[user_id] = {
                    'text': text,
                    'mode': 'voice_processed'
                }
                await self.show_voice_selection(update.message, text)
            else:
                await update.message.reply_text("❌ Не удалось распознать речь")
            
            # Очистка
            os.remove(file_path)
            if converted_file != file_path:
                os.remove(converted_file)
                
        except Exception as e:
            logger.error(f"Error processing audio: {e}")
            await update.message.reply_text("❌ Ошибка обработки аудиофайла")
    
    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик текстовых сообщений"""
        user_id = update.message.from_user.id
        text = update.message.text
        
        if user_id in user_data and user_data[user_id].get('mode') == 'text_input':
            if len(text) > 1000:
                await update.message.reply_text("❌ Текст слишком длинный (максимум 1000 символов)")
                return
            
            user_data[user_id] = {
                'text': text,
                'mode': 'text_processed'
            }
            await self.show_voice_selection(update.message, text)
        else:
            # Если просто текст без контекста
            keyboard = [
                [InlineKeyboardButton("🔊 Преобразовать в голос", callback_data=f'text_to_voice_{hash(text) % 10000}')]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                f"📝 Текст получен: {text[:100]}...\n\nПреобразовать в голос?",
                reply_markup=reply_markup
            )
            user_data[user_id] = {'text': text, 'mode': 'text_ready'}
    
    async def show_voice_selection(self, message, text: str):
        """Показать выбор голоса"""
        voices_keyboard = [
            [
                InlineKeyboardButton("👩 Женский 1", callback_data='voice_female1'),
                InlineKeyboardButton("👨 Мужской 1", callback_data='voice_male1')
            ],
            [
                InlineKeyboardButton("👧 Женский 2", callback_data='voice_female2'),
                InlineKeyboardButton("👦 Мужской 2", callback_data='voice_male2')
            ],
            [InlineKeyboardButton("🎭 Другой голос", callback_data='voice_other')]
        ]
        
        reply_markup = InlineKeyboardMarkup(voices_keyboard)
        
        preview_text = text[:100] + "..." if len(text) > 100 else text
        await message.reply_text(
            f"🎯 Выберите голос для текста:\n\n*{preview_text}*\n\n"
            "Доступные голоса:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def generate_and_send_voice(self, user_id: int, message, context: ContextTypes.DEFAULT_TYPE):
        """Генерация и отправка голосового сообщения"""
        if user_id not in user_data or 'text' not in user_data[user_id]:
            await message.reply_text("❌ Текст не найден. Попробуйте еще раз.")
            return
        
        text = user_data[user_id]['text']
        voice_id = user_data[user_id].get('voice_id', 'female1')
        
        try:
            await message.reply_text("🔄 Генерирую голосовое сообщение...")
            
            # Генерация голоса через Minimax API
            audio_data = await self.generate_voice_minimax(text, voice_id)
            
            if audio_data:
                # Сохраняем временный файл
                output_file = f"output_{user_id}.mp3"
                with open(output_file, 'wb') as f:
                    f.write(audio_data)
                
                # Отправляем голосовое сообщение
                with open(output_file, 'rb') as audio:
                    await message.reply_voice(
                        voice=audio,
                        caption="🔊 Сгенерированное голосовое сообщение"
                    )
                
                # Удаляем временный файл
                os.remove(output_file)
                
                # Предлагаем новые действия
                keyboard = [
                    [InlineKeyboardButton("🎤 Новое голосовое", callback_data='send_voice')],
                    [InlineKeyboardButton("📝 Новый текст", callback_data='send_text')]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await message.reply_text(
                    "✅ Готово! Что хотите сделать дальше?",
                    reply_markup=reply_markup
                )
            else:
                await message.reply_text("❌ Ошибка генерации голоса")
                
        except Exception as e:
            logger.error(f"Error generating voice: {e}")
            await message.reply_text("❌ Ошибка при генерации голосового сообщения")
    
    async def convert_audio(self, input_path: str) -> str:
        """Конвертация аудио в MP3"""
        if input_path.endswith('.mp3'):
            return input_path
        
        output_path = input_path.rsplit('.', 1)[0] + '.mp3'
        
        try:
            audio = AudioSegment.from_file(input_path)
            audio.export(output_path, format="mp3")
            return output_path
        except:
            # Используем ffmpeg как fallback
            ffmpeg.input(input_path).output(output_path).run(quiet=True)
            return output_path
    
    async def transcribe_audio(self, audio_path: str) -> Optional[str]:
        """
        Транскрипция аудио через Minimax API
        Внимание: Minimax может не иметь транскрипции, используем заглушку
        """
        # Это заглушка - в реальности нужно использовать API транскрипции
        # Minimax пока не предоставляет транскрипцию, так что возвращаем тестовый текст
        return "Это пример транскрибированного текста. В реальном приложении нужно интегрировать сервис транскрипции."
    
    async def generate_voice_minimax(self, text: str, voice_id: str = "female1") -> Optional[bytes]:
        """Генерация голоса через Minimax API"""
        
        # Маппинг голосов (нужно уточнить в документации Minimax)
        voice_map = {
            'female1': 'female_zh-CN-XiaoxiaoNeural',
            'male1': 'male_zh-CN-YunxiNeural',
            'female2': 'female_zh-CN-XiaoyiNeural',
            'male2': 'male_zh-CN-YunjianNeural',
            'other': 'female_zh-CN-XiaochenNeural'
        }
        
        voice_to_use = voice_map.get(voice_id, voice_map['female1'])
        
        headers = {
            "Authorization": f"Bearer {MINIMAX_API_KEY}",
            "Content-Type": "application/json"
        }
        
        # Уточните параметры в документации Minimax Voice API
        payload = {
            "text": text,
            "voice": voice_to_use,
            "speed": 1.0,
            "volume": 1.0,
            "pitch": 1.0,
            "emotion": "neutral",
            "language": "ru"  # Или другой язык
        }
        
        try:
            response = requests.post(
                MINIMAX_VOICE_API_URL,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                return response.content
            else:
                logger.error(f"Minimax API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Request error: {e}")
            return None
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда помощи"""
        help_text = (
            "🎤 *Voice Bot Help*\n\n"
            "*Команды:*\n"
            "/start - Начать работу с ботом\n"
            "/help - Показать это сообщение\n"
            "/mode - Выбрать режим работы\n\n"
            "*Как использовать:*\n"
            "1. Отправьте голосовое сообщение\n"
            "2. Или отправьте аудиофайл\n"
            "3. Или введите текст\n"
            "4. Выберите голос для генерации\n"
            "5. Получите результат!\n\n"
            "*Поддержка:*\n"
            "Форматы: OGG, MP3, M4A, WAV\n"
            "Лимит текста: 1000 символов\n"
            "Лимит аудио: 60 секунд"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def error_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработчик ошибок"""
        logger.error(f"Update {update} caused error {context.error}")
        
        try:
            await update.message.reply_text(
                "❌ Произошла ошибка. Пожалуйста, попробуйте еще раз или используйте /start"
            )
        except:
            pass

def main():
    """Запуск бота"""
    # Создание приложения
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    bot = VoiceBot()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CallbackQueryHandler(bot.handle_button))
    application.add_handler(MessageHandler(filters.VOICE, bot.handle_voice))
    application.add_handler(MessageHandler(filters.AUDIO, bot.handle_audio))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_text))
    
    # Обработчик ошибок
    application.add_error_handler(bot.error_handler)
    
    # Запуск бота
    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
