# Контекст проекта для AI-ассистента

> Этот файл содержит информацию, которую НЕЛЬЗЯ получить из анализа кода.
> Читай этот файл ПЕРВЫМ перед работой с проектом.

---

## Цель проекта

Telegram-бот для автоматического резюмирования постов из публичных каналов.

**Пользовательский сценарий:**
1. Пользователь пересылает сообщение из любого публичного канала
2. Бот автоматически добавляет этот канал в список отслеживаемых
3. Бот периодически проверяет каналы на новые посты
4. При появлении нового поста — генерирует резюме через Gemini и отправляет пользователю

**Telegram бот:** @chanresume_bot

---

## Структура проекта (МОНОРЕПО)

```
tg-resume-bot/
├── app/                    # Python бэкенд (FastAPI + aiogram)
│   ├── main.py            # Точка входа
│   ├── bot/handlers.py    # Telegram хендлеры
│   ├── services/          # Парсер, Summarizer, Scheduler
│   ├── db/                # SQLAlchemy модели
│   ├── api/               # REST API для админки
│   └── admin/             # SQLAdmin (устаревшее)
├── admin/                  # React админка (отдельный сервис)
│   ├── src/
│   └── Dockerfile
├── CONTEXT.md             # ЭТО ТЫ ЧИТАЕШЬ
├── requirements.txt
└── Procfile
```

---

## Railway: КРИТИЧЕСКИ ВАЖНО

### Два сервиса в одном проекте

| Сервис | Root Directory | Что делает |
|--------|----------------|------------|
| `resume-bot` | `/` (корень) | Python бэкенд + бот |
| `admin-web` | `/admin` | React админка |

### Настройка Root Directory

**ПРОБЛЕМА:** Railway по умолчанию деплоит весь репозиторий. Для монорепо нужно указать root directory.

**РЕШЕНИЕ:** В Railway Dashboard → Service → Settings → **Root Directory**
- Для `resume-bot`: оставить пустым или `/`
- Для `admin-web`: установить `/admin`

### Команды деплоя

```bash
# Деплой бэкенда
cd /path/to/tg-resume-bot
railway service link resume-bot
railway up

# Деплой админки
cd /path/to/tg-resume-bot/admin
railway service link admin-web
railway up

# Или одной командой для админки
railway service link admin-web && railway up
```

### Переменные окружения

#### Для resume-bot:
| Переменная | Значение | Описание |
|------------|----------|----------|
| `BOT_TOKEN` | `8275927969:AAHl...` | От @BotFather |
| `GEMINI_API_KEY` | `AIzaSy...` | От Google AI Studio |
| `DATABASE_URL` | `postgresql://...` | Копировать из Postgres сервиса |
| `ADMIN_PASSWORD` | `chanresume2024` | Для SQLAdmin (устаревшее) |
| `SECRET_KEY` | любая строка | Для сессий |
| `CHECK_INTERVAL_MINUTES` | `1` | Интервал проверки каналов |

#### Для admin-web:
| Переменная | Значение | Описание |
|------------|----------|----------|
| `VITE_API_URL` | `https://resume-bot-production.up.railway.app` | URL бэкенда |

### Полезные команды Railway

```bash
railway whoami                    # Проверить авторизацию
railway list                      # Список проектов
railway status                    # Статус текущего проекта
railway service link <name>       # Переключить сервис
railway variables                 # Показать переменные
railway variables --set "K=V"     # Установить переменную
railway logs                      # Логи
railway up                        # Деплой
railway domain                    # Создать публичный URL
```

---

## Gemini API: ВАЖНО

### Правильное название модели

**ИСПОЛЬЗУЙ:** `gemini-3-flash-preview`

```python
# ПРАВИЛЬНО
self.model = genai.GenerativeModel("gemini-3-flash-preview")

# НЕПРАВИЛЬНО (устаревшие)
# "gemini-2.0-flash"
# "gemini-2.5-flash-preview-05-20"
# "gemini-pro"
```

### Rate Limits (Free Tier)

| Лимит | Значение |
|-------|----------|
| Запросов в минуту | 15 RPM |
| Запросов в день | 1500 RPD |
| Токенов в минуту | ~1M TPM |

### Обработка Rate Limits

В `app/services/summarizer.py` реализован retry с exponential backoff:
- При 429 ошибке — ждёт время из `retry_delay` + 5 сек
- До 3 попыток
- Если все попытки провалились — пропускает пост

**ЕСЛИ ЛИМИТЫ БЬЮТСЯ ЧАСТО:**
1. Увеличить `CHECK_INTERVAL_MINUTES` до 5-10
2. Или перейти на платный план Gemini

---

## TypeScript: Ошибки сборки админки

### Проблема: `verbatimModuleSyntax`

```
error TS1484: 'User' is a type and must be imported using a type-only import
```

### Решение

```typescript
// НЕПРАВИЛЬНО
import { getUsers, User } from '../api/client';

// ПРАВИЛЬНО
import { getUsers } from '../api/client';
import type { User } from '../api/client';
```

---

## База данных

### PostgreSQL на Railway

1. Railway автоматически создаёт переменные `DATABASE_URL`, `PGHOST`, etc.
2. **ВАЖНО:** Скопировать `DATABASE_URL` из Postgres сервиса в resume-bot сервис
3. Формат: `postgresql://user:pass@host:5432/dbname`

### Миграции

Таблицы создаются автоматически при старте через SQLAlchemy:
```python
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
```

---

## Известные проблемы и решения

### 1. Переменные окружения не видны при старте

**Симптом:** `ValueError: BOT_TOKEN not set` хотя переменная добавлена

**Причина:** Сервисы инициализируются при импорте, до загрузки env

**Решение:** Ленивая инициализация (см. `app/bot/handlers.py`):
```python
_summarizer = None

def get_summarizer():
    global _summarizer
    if _summarizer is None:
        _summarizer = Summarizer()
    return _summarizer
```

### 2. Markdown ломает Telegram сообщения

**Решение:** Библиотека `telegramify-markdown`
```python
import telegramify_markdown
from telegramify_markdown import customize
customize.strict_markdown = False

formatted = telegramify_markdown.markdownify(llm_response)
await message.answer(formatted, parse_mode=ParseMode.MARKDOWN_V2)
```

### 3. Парсер не видит новые посты

**Причина:** Telegram кэширует `t.me/s/`

**Решение:** Добавить timestamp в URL:
```python
url = f"https://t.me/s/{channel}?_={int(time.time())}"
```

### 4. SQLAdmin без стилей

**Причина:** CDN со стилями не загружается

**Решение:** Использовать React админку (`/admin` сервис) вместо SQLAdmin

### 5. Railway деплоит не тот сервис

**Причина:** Не переключен активный сервис

**Решение:**
```bash
railway service link resume-bot  # или admin-web
railway up
```

---

## URLs проекта

| Что | URL |
|-----|-----|
| Бот | https://t.me/chanresume_bot |
| API | https://resume-bot-production.up.railway.app |
| React админка | https://admin-web-production-*.up.railway.app |
| SQLAdmin (устар.) | https://resume-bot-production.up.railway.app/admin |
| Railway Dashboard | https://railway.com/project/2edfccab-0f63-41ad-bc3b-e870b14b7fc9 |

---

## Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                     Railway Project                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │  Postgres   │    │ resume-bot  │    │  admin-web  │         │
│  │             │◄───│  (Python)   │◄───│   (React)   │         │
│  │  DATABASE   │    │             │    │             │         │
│  └─────────────┘    └──────┬──────┘    └─────────────┘         │
│                            │                                    │
│                     ┌──────┴──────┐                             │
│                     │             │                             │
│               ┌─────▼─────┐ ┌─────▼─────┐                      │
│               │  Telegram │ │  Gemini   │                      │
│               │  Bot API  │ │  3 Flash  │                      │
│               └───────────┘ └───────────┘                      │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Поток данных

1. **Пользователь** пересылает пост → **Bot Handler**
2. **Bot Handler** парсит `forward_from_chat` → добавляет канал в БД
3. **Scheduler** (каждые N минут) → проверяет каналы
4. **Parser** → `t.me/s/{channel}` → новые посты
5. **Summarizer** → Gemini API → резюме
6. **Bot** → отправляет резюме подписчикам

---

## Что НЕ надо делать

1. **НЕ** использовать `gemini-2.0-flash` — устаревшее
2. **НЕ** деплоить без `railway service link` — попадёт не туда
3. **НЕ** забывать про Root Directory в настройках Railway
4. **НЕ** хардкодить API ключи — только через env
5. **НЕ** игнорировать rate limits Gemini — добавлять retry

---

## Источники

- [Gemini 3 Flash Preview](https://ai.google.dev/gemini-api/docs/gemini-3) — документация модели
- [telegramify-markdown](https://github.com/sudoskys/telegramify-markdown) — конвертер Markdown
- [Railway Docs](https://docs.railway.app/) — документация Railway
- [aiogram 3.x](https://docs.aiogram.dev/) — Telegram бот фреймворк
