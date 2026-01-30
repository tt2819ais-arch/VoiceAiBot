import os
import logging
import base64
from typing import Dict, Optional
import tempfile

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

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
MINIMAX_API_KEY = os.getenv('MINIMAX_API_KEY')
MINIMAX_VOICE_CLONE_API = "https://api.minimax.chat/v1/voice_clone"  # Проверьте точный endpoint
MINIMAX_TTS_API = "https://api.minimax.chat/v1/t2a_v2"

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

user_sessions: Dict[int, Dict] = {}

class VoiceCloneBot:
    def __init__(self):
        self.steps = {
            'start': self.handle_start,
            'waiting_voice_sample': self.handle_voice_sample,
            'waiting_text': self.handle_user_text,
            'generating': self.handle_generation
        }
    
    async def handle_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Начало работы - просим отправить голосовой образец"""
        user_id = update.effective_user.id
        user_sessions[user_id] = {'step': 'waiting_voice_sample'}
        
        instruction = (
            "🎤 *Шаг 1/2: Отправьте голосовой образец*\n\n"
            "Пожалуйста, отправьте голосовое сообщение или аудиофайл (MP3, WAV, OGG), "
            "который будет использоваться как образец для создания нового голоса.\n\n"
            "Рекомендации:\n"
            "• Длительность 5-30 секунд\n"
            "• Чистая речь без фонового шума\n"
            "• Один говорящий\n"
            "• Поддерживаемые форматы: MP3, WAV, OGG, M4A"
        )
        
        await update.message.reply_text(instruction, parse_mode='Markdown')
    
    async def handle_voice_sample(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка голосового образца"""
        user_id = update.effective_user.id
        
        try:
            # Получаем файл
            if update.message.voice:
                file = await update.message.voice.get_file()
                file_ext = 'ogg'
            elif update.message.audio:
                file = await update.message.audio.get_file()
                file_ext = update.message.audio.file_name.split('.')[-1].lower()
            else:
                await update.message.reply_text("❌ Пожалуйста, отправьте голосовое сообщение или аудиофайл")
                return
            
            # Скачиваем во временный файл
            with tempfile.NamedTemporaryFile(suffix=f'.{file_ext}', delete=False) as tmp:
                await file.download_to_drive(tmp.name)
                audio_path = tmp.name
            
            # Отправляем в Minimax для клонирования голоса
            await update.message.reply_text("🔄 Обрабатываю голосовой образец...")
            
            # 1. Создаем голосовой профиль
            voice_id = await self.create_voice_profile(audio_path, user_id)
            
            if voice_id:
                user_sessions[user_id] = {
                    'step': 'waiting_text',
                    'voice_id': voice_id,
                    'audio_sample_path': audio_path
                }
                
                await update.message.reply_text(
                    "✅ Голосовой образец успешно обработан!\n\n"
                    "📝 *Шаг 2/2: Введите текст для генерации*\n\n"
                    "Теперь введите текст, который вы хотите преобразовать в голос "
                    "с использованием вашего голосового образца.\n\n"
                    "Максимальная длина: 1000 символов",
                    parse_mode='Markdown'
                )
            else:
                await update.message.reply_text(
                    "❌ Не удалось создать голосовой профиль. "
                    "Попробуйте другой образец или обратитесь в поддержку."
                )
            
            # Очистка временного файла
            os.unlink(audio_path)
            
        except Exception as e:
            logger.error(f"Error processing voice sample: {e}")
            await update.message.reply_text("❌ Ошибка при обработке голосового образца")
    
    async def create_voice_profile(self, audio_path: str, user_id: int) -> Optional[str]:
        """Создание голосового профиля в Minimax"""
        try:
            # Читаем аудио файл в base64
            with open(audio_path, 'rb') as audio_file:
                audio_bytes = audio_file.read()
                audio_base64 = base64.b64encode(audio_bytes).decode('utf-8')
            
            # Определяем MIME type по расширению
            ext = audio_path.split('.')[-1].lower()
            mime_types = {
                'mp3': 'audio/mpeg',
                'wav': 'audio/wav',
                'ogg': 'audio/ogg',
                'm4a': 'audio/mp4'
            }
            mime_type = mime_types.get(ext, 'audio/mpeg')
            
            # Создаем запрос для клонирования голоса
            headers = {
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
                "Content-Type": "application/json"
            }
            
            # Проверьте точную структуру запроса в документации Minimax
            payload = {
                "voice_name": f"user_{user_id}_voice",
                "audio_data": audio_base64,
                "audio_format": mime_type,
                "description": f"Voice clone for user {user_id}",
                # Дополнительные параметры, если нужны
                "language": "auto",  # Автоопределение языка
                "gender": "auto"     # Автоопределение пола
            }
            
            response = requests.post(
                MINIMAX_VOICE_CLONE_API,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                # Предполагаемая структура ответа - уточните в документации
                return data.get("voice_id") or data.get("id") or f"user_{user_id}_voice"
            else:
                logger.error(f"Voice clone API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating voice profile: {e}")
            return None
    
    async def handle_user_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка текста от пользователя"""
        user_id = update.effective_user.id
        
        if user_id not in user_sessions or 'voice_id' not in user_sessions[user_id]:
            await update.message.reply_text("❌ Сначала отправьте голосовой образец")
            await self.handle_start(update, context)
            return
        
        text = update.message.text.strip()
        
        if not text:
            await update.message.reply_text("❌ Пожалуйста, введите текст")
            return
        
        if len(text) > 1000:
            await update.message.reply_text("❌ Текст слишком длинный (максимум 1000 символов)")
            return
        
        user_sessions[user_id]['text'] = text
        user_sessions[user_id]['step'] = 'generating'
        
        # Показываем кнопки для выбора эмоции/тона
        keyboard = [
            [
                InlineKeyboardButton("😊 Обычный", callback_data='style_neutral'),
                InlineKeyboardButton("😄 Радостный", callback_data='style_happy')
            ],
            [
                InlineKeyboardButton("😢 Грустный", callback_data='style_sad'),
                InlineKeyboardButton("😠 Сердитый", callback_data='style_angry')
            ],
            [
                InlineKeyboardButton("🗣 Без эмоций", callback_data='style_none'),
                InlineKeyboardButton("⚡ Быстро", callback_data='speed_fast')
            ]
        ]
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            f"📝 Текст получен: *{text[:100]}...*\n\n"
            "Выберите стиль или параметры генерации:",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка inline кнопок"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        if user_id not in user_sessions or 'text' not in user_sessions[user_id]:
            await query.edit_message_text("❌ Сессия устарела. Начните заново с /start")
            return
        
        # Определяем параметры генерации
        style_map = {
            'style_neutral': {'emotion': 'neutral', 'speed': 1.0},
            'style_happy': {'emotion': 'happy', 'speed': 1.1},
            'style_sad': {'emotion': 'sad', 'speed': 0.9},
            'style_angry': {'emotion': 'angry', 'speed': 1.2},
            'style_none': {'emotion': 'neutral', 'speed': 1.0},
            'speed_fast': {'emotion': 'neutral', 'speed': 1.5}
        }
        
        params = style_map.get(query.data, {'emotion': 'neutral', 'speed': 1.0})
        
        await query.edit_message_text("🔄 Генерирую голосовое сообщение...")
        
        # Генерация голоса
        try:
            audio_data = await self.generate_cloned_voice(
                user_sessions[user_id]['text'],
                user_sessions[user_id]['voice_id'],
                params['emotion'],
                params['speed']
            )
            
            if audio_data:
                # Сохраняем во временный файл
                with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
                    tmp.write(audio_data)
                    tmp_path = tmp.name
                
                # Отправляем голосовое
                with open(tmp_path, 'rb') as audio_file:
                    await query.message.reply_voice(
                        voice=audio_file,
                        caption=f"🔊 Ваш текст, озвученный вашим голосом"
                    )
                
                # Предлагаем новые действия
                keyboard = [
                    [
                        InlineKeyboardButton("📝 Новый текст", callback_data='new_text'),
                        InlineKeyboardButton("🔄 Новый образец", callback_data='new_sample')
                    ]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                await query.message.reply_text(
                    "✅ Готово! Что хотите сделать дальше?",
                    reply_markup=reply_markup
                )
                
                # Обновляем сессию
                user_sessions[user_id]['step'] = 'waiting_text'
                
                # Очистка
                os.unlink(tmp_path)
            else:
                await query.message.reply_text("❌ Ошибка генерации голоса")
                
        except Exception as e:
            logger.error(f"Error generating voice: {e}")
            await query.message.reply_text("❌ Ошибка при генерации голоса")
    
    async def generate_cloned_voice(self, text: str, voice_id: str, emotion: str = "neutral", speed: float = 1.0) -> Optional[bytes]:
        """Генерация голоса с клонированным голосом"""
        try:
            headers = {
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
                "Content-Type": "application/json"
            }
            
            # Формируем запрос для TTS с клонированным голосом
            # Уточните точную структуру в документации Minimax
            payload = {
                "text": text,
                "model": "speech-02-turbo",  # Или другой доступный модель
                "voice_id": voice_id,  # ID клонированного голоса
                "speed": speed,
                "emotion": emotion,
                "audio_format": "mp3",
                "sample_rate": 24000,
                # Дополнительные параметры, если поддерживаются
                "language": "auto",
                "volume": 1.0,
                "pitch": 1.0
            }
            
            response = requests.post(
                MINIMAX_TTS_API,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                # Проверьте формат ответа - может быть base64 или бинарные данные
                if 'application/json' in response.headers.get('Content-Type', ''):
                    data = response.json()
                    # Если аудио в base64
                    if 'audio_data' in data:
                        return base64.b64decode(data['audio_data'])
                    # Если есть URL до аудио
                    elif 'audio_url' in data:
                        audio_response = requests.get(data['audio_url'])
                        return audio_response.content
                else:
                    # Бинарные данные
                    return response.content
            else:
                logger.error(f"TTS API error: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            logger.error(f"Error in TTS generation: {e}")
            return None
    
    async def handle_new_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка запроса на новый текст"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        
        if user_id in user_sessions and 'voice_id' in user_sessions[user_id]:
            user_sessions[user_id]['step'] = 'waiting_text'
            await query.edit_message_text(
                "📝 Введите новый текст для генерации голосом:\n\n"
                "Максимальная длина: 1000 символов"
            )
        else:
            await query.edit_message_text("❌ Голосовой профиль не найден. Начните заново с /start")
    
    async def handle_new_sample(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Обработка запроса на новый образец"""
        query = update.callback_query
        await query.answer()
        
        user_id = query.from_user.id
        user_sessions[user_id] = {'step': 'waiting_voice_sample'}
        
        await query.edit_message_text(
            "🎤 Отправьте новый голосовой образец:\n\n"
            "Длительность: 5-30 секунд\n"
            "Форматы: MP3, WAV, OGG, M4A"
        )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Основной обработчик сообщений"""
        user_id = update.effective_user.id
        
        # Определяем текущий шаг пользователя
        current_step = user_sessions.get(user_id, {}).get('step', 'start')
        
        # Вызываем соответствующий обработчик
        handler = self.steps.get(current_step)
        if handler:
            await handler(update, context)
        else:
            await self.handle_start(update, context)
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Команда помощи"""
        help_text = (
            "🎤 *Voice Clone Bot Help*\n\n"
            "*Как использовать:*\n"
            "1. Отправьте голосовое сообщение или аудиофайл как образец\n"
            "2. Введите текст, который нужно озвучить\n"
            "3. Выберите стиль генерации\n"
            "4. Получите результат!\n\n"
            "*Команды:*\n"
            "/start - Начать заново\n"
            "/help - Эта справка\n"
            "/cancel - Отменить текущую операцию\n\n"
            "*Требования к образцу:*\n"
            "• 5-30 секунд чистой речи\n"
            "• Один говорящий\n"
            "• Без фонового шума\n"
            "• Форматы: MP3, WAV, OGG, M4A"
        )
        await update.message.reply_text(help_text, parse_mode='Markdown')
    
    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Отмена текущей операции"""
        user_id = update.effective_user.id
        if user_id in user_sessions:
            del user_sessions[user_id]
        await update.message.reply_text("✅ Текущая операция отменена. Начните заново с /start")

def main():
    """Запуск бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    bot = VoiceCloneBot()
    
    # Регистрация обработчиков
    application.add_handler(CommandHandler("start", bot.handle_start))
    application.add_handler(CommandHandler("help", bot.help_command))
    application.add_handler(CommandHandler("cancel", bot.cancel_command))
    
    # Обработчики кнопок
    application.add_handler(CallbackQueryHandler(bot.handle_button, pattern='^style_|^speed_'))
    application.add_handler(CallbackQueryHandler(bot.handle_new_text, pattern='^new_text$'))
    application.add_handler(CallbackQueryHandler(bot.handle_new_sample, pattern='^new_sample$'))
    
    # Обработчики сообщений
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, bot.handle_message))
    
    # Запуск бота
    logger.info("Бот запущен...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
