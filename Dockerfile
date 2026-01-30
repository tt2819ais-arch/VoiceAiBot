# Используем официальный Python 3.11
FROM python:3.11-slim

# Рабочая директория внутри контейнера
WORKDIR /app

# Копируем файлы проекта
COPY requirements.txt .
COPY bot.py .

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Прописываем переменные окружения (можно переопределить при запуске)
ENV BOT_TOKEN=7568864397:AAEI4RwDx7Gk_HMnmeCCYMaLkVJTMqKOfMw
ENV MINIMAX_API_KEY=sk-api-4zpied8wxig2ih39-Gmu02eiJ68sLYQjLaxGRRDRTo4kvPt0hU_vfi5YtmFXxcjxCahW9IPJH2qN-8MAHvAWqOnSy4kLF2yywYOwmgQWPvL0ph_t5vBlw2A

# Запуск бота
CMD ["python", "bot.py"]
