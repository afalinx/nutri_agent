# NutriAgent

Интеллектуальная система генерации персонализированных планов питания с верификацией КБЖУ.

AI-агент составляет недельный рацион под цели пользователя, проверяет каждую цифру по справочникам через цикл рефлексии (Actor-Critic) и выдаёт готовый список покупок.

> **Дипломный проект.** Научная ценность — пайплайн контролируемой генерации в критическом домене (диетология), исключающий галлюцинации LLM.

---

## Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                    Agent (Claude / LLM)                         │
│  ┌───────────────────────────────────────────────────────┐      │
│  │  SKILL.md — инструкции для агента                     │      │
│  │                                                       │      │
│  │  1. cli.py context  → рецепты + профиль              │      │
│  │  2. AI генерирует JSON план                          │      │
│  │  3. cli.py validate → проверка КБЖУ                  │      │
│  │  4. Если ошибка → исправить → повторить              │      │
│  │  5. cli.py save     → сохранение в БД               │      │
│  └───────────────────────────────────────────────────────┘      │
│                           │                                     │
│                    CLI (cli.py)                                  │
│              ┌────────────┼───────────────┐                     │
│              ▼            ▼               ▼                     │
│  ┌──────────────┐ ┌─────────────┐ ┌────────────────┐           │
│  │ RAG Retriever│ │  Calculator │ │   Validator     │           │
│  │ (recipes DB) │ │  (КБЖУ)    │ │  (±5% target)   │           │
│  └──────┬───────┘ └─────────────┘ └────────────────┘           │
│         │                                                       │
│         ▼                                                       │
│  ┌────────────────────────┐  ┌──────────┐                      │
│  │ PostgreSQL + pgvector  │  │  Redis   │                      │
│  │ (users, recipes,       │  │  (кэш)  │                      │
│  │  meal_plans, vectors)  │  └──────────┘                      │
│  └────────────────────────┘                                    │
└─────────────────────────────────────────────────────────────────┘
```

**Два режима работы:**

| Режим | Описание | LLM |
|-------|----------|-----|
| **Agent Skills** (основной) | Агент читает SKILL.md и выполняет план через CLI | Claude / любой совместимый агент |
| **API** (опционально) | REST API + Celery worker | OpenRouter (GPT-4o и др.) |

**Ключевая идея:** LLM никогда не отвечает «от себя». Блюда берутся только из верифицированной базы рецептов (RAG), а числовые показатели проходят через детерминированный калькулятор.

---

## Стек технологий

| Слой | Технологии |
|------|-----------|
| **Backend** | Python 3.11+, FastAPI |
| **AI** | Agent Skills (.claude/skills/), PydanticAI, Structured Outputs |
| **CLI** | argparse, asyncio |
| **База данных** | PostgreSQL + pgvector (реляционные данные + векторные эмбеддинги) |
| **Очередь задач** | Celery + Redis (для API-режима) |
| **Инфраструктура** | Docker, Docker Compose |
| **Логирование** | Loguru |
| **Миграции** | Alembic |

---

## Быстрый старт (CLI-first, основной режим)

### Требования

- Python 3.11+
- Docker и Docker Compose
- `uv` (современный менеджер окружения и зависимостей)
- Агент с поддержкой Agent Skills (Claude Code, Cursor, и др.)

### Запуск

```bash
# 1. Клонировать репозиторий
git clone <repo-url>
cd nutriagent

# 2. Скопировать и заполнить переменные окружения
cp .env.example .env

# 3. Поднять БД и Redis
docker compose -p nutriagent up -d db redis

# 4. Установить зависимости
cd backend
uv sync --dev

# 5. Применить миграции
uv run alembic upgrade head

# 6. Загрузить рецепты
uv run python scripts/seed_recipes.py
```

### Основной путь: Agent Skills (без API)

Просто скажите агенту:
- *«Составь план питания для пользователя test@nutriagent.ru»*
- *«Сгенерируй рацион на неделю»*
- *«Покажи список покупок»*

Агент автоматически прочитает SKILL.md и выполнит полный цикл:
`context -> generate -> validate -> auto-fix -> save -> shopping-list`.

### CLI вручную (тот же пайплайн)

```bash
cd backend

# Посмотреть пользователей
uv run python cli.py users

# Получить контекст (рецепты + профиль)
uv run python cli.py context --user-id <UUID>

# Провалидировать план
uv run python cli.py validate --file plan.json

# Сохранить в БД
uv run python cli.py save --user-id <UUID> --file plan.json

# Агрегировать список покупок из дневного формата
uv run python cli.py shopping-list --file plan.json --day-format

# или автоопределение формата (day/week)
uv run python cli.py shopping-list --file plan.json --input-format auto
```

### API-режим (опционально)

```bash
# Запустить API-сервер
cd backend && uv run uvicorn app.main:app --reload --port 8000

# Запустить Celery worker
cd backend && uv run celery -A app.worker worker -l info

# Swagger-документация
open http://localhost:8000/docs
```

### Линтинг и форматирование (Ruff)

```bash
cd backend

# Проверка
uv run ruff check .

# Автоформат
uv run ruff format .

# Тесты
uv run pytest -q
```

---

## Agent Skills

Проект поддерживает формат [Agent Skills](https://agentskills.io/) — инструкции, которые AI-агент автоматически находит и выполняет.

```
.claude/skills/
├── generate-meal-plan/    # Генерация дневного плана
│   └── SKILL.md
├── generate-weekly-plan/  # Генерация плана на неделю + список покупок
│   └── SKILL.md
├── manage-users/          # CRUD пользователей
│   └── SKILL.md
└── setup-infrastructure/  # Запуск Docker + миграции
    └── SKILL.md
```

Цикл рефлексии реализуется **самим агентом**: он генерирует план, валидирует через CLI, и при ошибке исправляет — без внешнего API.

---

## MVP демо-сценарий (без API)

Для демонстрации готовности проекта достаточно CLI-first потока:

1. `uv run python cli.py users` — выбрать пользователя
2. `uv run python cli.py context --user-id <UUID> --day 1` — получить контекст
3. Агент генерирует JSON плана (`/tmp/plan.json`)
4. `uv run python cli.py validate --file /tmp/plan.json`
5. При ошибке — автоисправление и повтор шага 4 (до `valid=true`)
6. `uv run python cli.py save --user-id <UUID> --file /tmp/plan.json`
7. `uv run python cli.py shopping-list --file /tmp/plan.json --day-format`

Демонстрационный итог: валидный план, `plan_id` в БД и агрегированный список покупок.

---

## Структура проекта

```
nutriagent/
├── .claude/skills/          # Agent Skills (SKILL.md)
├── backend/
│   ├── app/
│   │   ├── api/             # FastAPI роуты
│   │   │   ├── routes/
│   │   │   │   ├── users.py # CRUD профиля
│   │   │   │   └── plans.py # Генерация + статус + план
│   │   │   └── schemas.py   # Pydantic-схемы запросов/ответов
│   │   │
│   │   ├── core/
│   │   │   ├── agent/       # AI-оркестратор
│   │   │   │   ├── orchestrator.py
│   │   │   │   ├── prompts/ # Шаблоны промптов (.yml)
│   │   │   │   └── schemas.py
│   │   │   │
│   │   │   ├── skills/      # Детерминированные инструменты
│   │   │   │   ├── calculator.py   # Расчёт КБЖУ (Миффлин-Сан Жеор)
│   │   │   │   ├── validator.py    # Валидация плана (±5%)
│   │   │   │   └── aggregator.py   # Список покупок
│   │   │   │
│   │   │   └── rag/
│   │   │       └── retriever.py    # Поиск рецептов + фильтр аллергенов
│   │   │
│   │   ├── db/
│   │   │   ├── models.py    # User, Recipe, MealPlan
│   │   │   └── session.py   # Async SQLAlchemy
│   │   │
│   │   ├── worker/          # Celery (для API-режима)
│   │   └── config.py        # pydantic-settings
│   │
│   ├── cli.py               # CLI-интерфейс для агента
│   ├── data/recipes.json    # 48 рецептов с КБЖУ
│   ├── scripts/seed_recipes.py
│   ├── tests/
│   └── alembic/
│
├── docker-compose.yml
├── .env.example
├── product.md               # Продуктовое видение
├── plan.md                  # План разработки
└── README.md
```

---

## Модель данных

### users
| Поле | Тип | Описание |
|------|-----|----------|
| `id` | UUID | PK |
| `email` | String | Unique |
| `password_hash` | String | bcrypt |
| `age`, `weight_kg`, `height_cm` | Number | Антропометрия |
| `gender` | Enum | male / female |
| `activity_level` | Enum | sedentary / light / moderate / active / very_active |
| `goal` | Enum | lose / maintain / gain |
| `allergies` | JSONB | Список аллергенов |
| `target_calories` | Integer | Рассчитанная норма (Миффлин-Сан Жеор) |

### recipes
| Поле | Тип | Описание |
|------|-----|----------|
| `id` | UUID | PK |
| `title` | String | Название |
| `ingredients` | JSONB | Ингредиенты с граммовками |
| `calories`, `protein`, `fat`, `carbs` | Float | КБЖУ на порцию |
| `embedding` | Vector(1536) | Для семантического поиска |
| `tags` | Array[String] | завтрак, обед, веган... |

### meal_plans
| Поле | Тип | Описание |
|------|-----|----------|
| `id` | UUID | PK |
| `user_id` | UUID | FK → users |
| `status` | Enum | PENDING / GENERATING / READY / FAILED |
| `plan_data` | JSONB | Structured Output (план) |
| `start_date`, `end_date` | Date | Период |

---

## Как работает цикл рефлексии

```
     Профиль пользователя
              │
              ▼
   ┌─────────────────────┐
   │  RAG: поиск рецептов │ ──► Пул ~30 блюд (без аллергенов)
   │  (cli.py context)    │
   └──────────┬──────────┘
              │
              ▼
   ┌─────────────────────┐
   │  Агент: генерация    │ ──► JSON план (Structured Output)
   │  (Actor)             │
   └──────────┬──────────┘
              │
              ▼
   ┌─────────────────────┐
   │  Calculator Skill    │ ──► Пересчёт калорий по справочнику
   │  (cli.py validate)   │
   │  (Critic)            │
   └──────────┬──────────┘
              │
         ┌────┴────┐
         │  OK?    │
         └────┬────┘
          Да  │  Нет (отклонение > 5%)
              │     │
              │     ▼
              │  Агент исправляет план → retry
              │     │
              │     └──────────► Назад к генерации
              ▼
        Финальный план
       (cli.py save)
```

---

## API (REST)

| Метод | Эндпоинт | Описание |
|-------|----------|----------|
| `POST` | `/api/users` | Создание профиля |
| `GET` | `/api/users/:id` | Получение профиля |
| `PUT` | `/api/users/:id` | Обновление профиля |
| `POST` | `/api/generate-plan` | Запуск генерации (task_id) |
| `GET` | `/api/tasks/:task_id` | Статус генерации |
| `GET` | `/api/plans/:id` | Готовый план |
| `GET` | `/api/plans/:id/shopping-list` | Список покупок |

Swagger: `http://localhost:8000/docs`

---

## Frontend MVP (Astro + React)

В репозитории добавлен простой клиент с онбордингом:

```bash
cd frontend
cp .env.example .env   # при необходимости поменяй PUBLIC_API_BASE_URL
npm install
npm run dev
```

UI доступен на `http://127.0.0.1:4321`.

Онбординг собирает:
- базовую анкету (пол, возраст, вес, рост, активность, цель),
- предпочтения,
- нелюбимые продукты,
- заболевания и аллергии.

После отправки фронт:
1. создаёт профиль через `POST /api/users`,
2. запускает генерацию через `POST /api/generate-plan`,
3. поллит `GET /api/tasks/{task_id}`,
4. загружает план `GET /api/plans/{id}`,
5. подтягивает детали рецептов `GET /api/recipes/{id}`.

---

## Лицензия

MIT

---

> **Дисклеймер:** Рекомендации ИИ носят ознакомительный характер. Проконсультируйтесь с врачом перед изменением рациона питания.
