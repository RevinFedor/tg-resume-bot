# Контекст проекта для AI-ассистента

> Этот файл содержит информацию, которую НЕЛЬЗЯ получить из анализа кода.
> Читай этот файл ПЕРВЫМ перед работой с проектом.

---

## Цель проекта

Telegram-бот для автоматического резюмирования постов из публичных каналов.

**Пользовательский сценарий:**
1. Пользователь пересылает сообщение из любого публичного канала
2. Бот автоматически добавляет этот канал в список отслеживаемых
3. Бот периодически проверяет каналы на новые посты (каждые 30 сек)
4. При появлении нового поста — генерирует резюме через Gemini и отправляет пользователю

**Дополнительно:**
- Голосовые/кружки отправленные напрямую боту → Whisper транскрипция → резюме

**Telegram бот:** @chanresume_bot
**GitHub:** https://github.com/RevinFedor/tg-resume-bot

---

## КРИТИЧЕСКОЕ ОГРАНИЧЕНИЕ: Парсинг каналов

| Тип контента | Парсинг t.me/s/ | Пересылка боту |
|--------------|-----------------|----------------|
| Текст | ✅ | ✅ |
| Фото | ✅ | ✅ |
| **Голосовые** | ❌ | ✅ |
| **Кружки** | ❌ | ✅ |
| **Видео** | ❌ | ✅ |

**Почему:** `t.me/s/channel` — веб-превью, там только текст и картинки. Аудио/видео недоступны.

**Решение для голосовых из каналов:**
1. Пользователь пересылает голосовое вручную → бот обрабатывает ✅
2. **ИЛИ** Userbot через MTProto (Pyrogram/Telethon) — видит ВСЁ

### Следующий шаг: Userbot

Для полноценного мониторинга каналов (включая голосовые/видео) нужен userbot:
1. Создать отдельный Telegram аккаунт (нужна симка)
2. Авторизовать через Pyrogram на сервере
3. Userbot подписывается на каналы и получает ВСЕ сообщения
4. Пересылает медиа боту для обработки

**Риски:** Telegram может забанить аккаунт за автоматизацию. Использовать осторожно.

---

## Структура проекта (МОНОРЕПО)

```
tg-resume-bot/
├── app/                    # Python бэкенд (FastAPI + aiogram)
│   ├── main.py            # Точка входа, Webhook handler
│   ├── bot/handlers.py    # Telegram хендлеры
│   ├── services/
│   │   ├── parser.py      # Парсинг t.me/s/
│   │   ├── summarizer.py  # Gemini API
│   │   ├── scheduler.py   # Фоновая проверка каналов
│   │   └── transcription.py # Whisper API
│   ├── db/                # SQLAlchemy модели
│   ├── api/               # REST API для админки
│   └── admin/             # SQLAdmin (устаревшее, не используй)
├── admin/                  # React админка (отдельный сервис)
│   ├── src/
│   └── railway.toml
├── CONTEXT.md             # ЭТО ТЫ ЧИТАЕШЬ
├── requirements.txt
└── Procfile
```

---

## Railway: Деплой

### Два сервиса в одном проекте

| Сервис | Root Directory | Что делает |
|--------|----------------|------------|
| `resume-bot` | `/` (корень) | Python бэкенд + бот |
| `admin-web` | `/admin` | React админка |

### Команды деплоя

```bash
# Деплой бэкенда
cd /path/to/tg-resume-bot
railway service link resume-bot && railway up

# Деплой админки
cd /path/to/tg-resume-bot/admin
railway service link admin-web && railway up
```

### Переменные окружения resume-bot

| Переменная | Описание |
|------------|----------|
| `BOT_TOKEN` | От @BotFather |
| `GEMINI_API_KEY` | От Google AI Studio |
| `OPENAI_API_KEY` | Для Whisper транскрипции |
| `DATABASE_URL` | PostgreSQL connection string |
| `WEBHOOK_URL` | `https://resume-bot-production.up.railway.app` |
| `CHECK_INTERVAL_SECONDS` | `30` (по умолчанию) |
| `SECRET_KEY` | Для сессий |

### Переменные admin-web

| Переменная | Описание |
|------------|----------|
| `VITE_API_URL` | URL бэкенда |

---

## Webhook vs Polling

**Текущая реализация: Webhook** ✅

Преимущества:
- Сообщения не теряются при редеплое
- Telegram повторяет попытки если сервер недоступен
- Меньше нагрузка (нет постоянных запросов)

Webhook endpoint: `POST /webhook`

```python
# В app/main.py
@app.post("/webhook")
async def webhook_handler(request: Request):
    data = await request.json()
    update = Update(**data)
    await dp.feed_update(bot, update)
```

---

## API ключи

### Gemini
- Модель: `gemini-3-flash-preview`
- Free tier: 15 RPM, 1500 RPD
- Получить: https://aistudio.google.com/apikey

### OpenAI (Whisper)
- Модель: `whisper-1`
- Используется для транскрипции голосовых и кружков
- Получить: https://platform.openai.com/api-keys

---

## Известные проблемы

### 1. Голосовые из каналов не обрабатываются
**Причина:** Ограничение парсинга t.me/s/ (см. выше)
**Решение:** Userbot или ручная пересылка

### 2. Переменные не видны при старте
**Решение:** Ленивая инициализация сервисов (get_summarizer(), get_transcriber())

### 3. TypeScript ошибки в админке
**Решение:** `import type { User }` вместо `import { User }`

### 4. SQLAdmin без стилей
**Решение:** Использовать React админку, не SQLAdmin

---

## URLs проекта

| Что | URL |
|-----|-----|
| Бот | https://t.me/chanresume_bot |
| API | https://resume-bot-production.up.railway.app |
| React админка | https://admin-web-production-*.up.railway.app |
| GitHub | https://github.com/RevinFedor/tg-resume-bot |
| Railway Dashboard | https://railway.com/project/2edfccab-0f63-41ad-bc3b-e870b14b7fc9 |

---

## Что работает сейчас

✅ Бот принимает сообщения через Webhook
✅ Пересылка из канала → добавление в дайджест
✅ Парсинг текстовых постов каждые 30 сек
✅ Резюме через Gemini
✅ Голосовые напрямую боту → Whisper → резюме
✅ Кружки напрямую боту → Whisper → резюме
✅ React админка с статистикой

## Что НЕ работает

❌ Голосовые/видео из каналов (нужен userbot)
❌ Приватные каналы (нужен userbot)

---

## Следующие шаги (TODO)

1. **Userbot через Pyrogram** — для мониторинга голосовых/видео из каналов
2. Авторизация в админке
3. Настройки пользователя (язык, формат резюме)
4. Дайджест по расписанию (ежедневный/еженедельный)
