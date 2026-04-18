# Запуск проекта после `git clone`

Инструкция описывает текущий рабочий режим ветки `wip/agent-cli-catalog-runtime`: FastAPI backend, Celery worker, Redis, PostgreSQL + pgvector, Astro frontend и генерация через `agent_cli`.

## 1. Требования

- Docker Desktop или Docker Engine с Docker Compose
- Python 3.11+
- `uv`
- Node.js 20+
- npm
- OpenRouter API key

Проверка:

```bash
docker ps
uv --version
node --version
npm --version
```

## 2. Клонирование

```bash
git clone https://github.com/afalinx/nutri_agent.git
cd nutri_agent
git checkout wip/agent-cli-catalog-runtime
```

Если ветка уже слита в основную, checkout отдельной ветки не нужен.

## 3. Переменные окружения

```bash
cp .env.example .env
```

Минимально проверь в `.env`:

```env
DATABASE_URL=postgresql+asyncpg://nutriagent:nutriagent@localhost:5433/nutriagent
REDIS_URL=redis://localhost:6379/0

OPENROUTER_API_KEY=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL_NAME=openai/gpt-4o

LLM_TIMEOUT_SEC=45
LLM_MAX_OUTPUT_TOKENS=900
LLM_MAX_RETRIES=2
LLM_CONTEXT_RECIPE_LIMIT=18
AGENT_CLI_MIN_CONTEXT_RECIPE_LIMIT=32
LLM_RETRY_HISTORY_LIMIT=1
LLM_RETRY_RESPONSE_PREVIEW_CHARS=300
```

Важно: при локальном запуске backend с хоста Postgres доступен на `localhost:5433`. Внутри Docker Compose сервис `db` слушает `5432`, но наружу он проброшен как `5433:5432`.

## 4. Инфраструктура

Из корня проекта:

```bash
docker compose -p nutriagent up -d db redis
docker compose -p nutriagent ps
```

Ожидаемо:

- `nutriagent-db-1` в состоянии `healthy`
- `nutriagent-redis-1` в состоянии `healthy`

## 5. Backend

```bash
cd backend
uv sync --dev
uv run alembic upgrade heads
```

Если база пустая, наполни стартовый каталог:

```bash
uv run python scripts/seed_recipes.py
```

Опционально проверить состояние каталога:

```bash
uv run python scripts/validate_catalog_state.py
```

## 6. Запуск backend API

В отдельном терминале:

```bash
cd backend
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Проверка:

```bash
open http://127.0.0.1:8000/docs
```

## 7. Запуск Celery worker

Во втором отдельном терминале:

```bash
cd backend
uv run celery -A app.worker.celery_app worker --loglevel=info --pool=solo
```

Для локальной разработки на macOS сейчас используется `--pool=solo`, чтобы избежать проблем с event loop и fork-процессами.

## 8. Frontend

В третьем терминале:

```bash
cd frontend
npm install
npm run build
npm run preview
```

Открыть:

```text
http://127.0.0.1:4321/
```

## 9. Текущий demo flow

Frontend сейчас запускает генерацию на `3` дня.

Причина: backend уже строго запрещает повторы блюд между днями, но текущий каталог ещё недостаточно широк для стабильной 7-дневной генерации без повторов. Для 3 дней текущий `agent_cli` flow проходит end-to-end:

```text
profile -> /api/generate-plan -> Celery task -> agent_cli -> validate -> auto-fix -> save -> shopping-list
```

Генерация использует:

- реальные рецепты из PostgreSQL
- LLM через OpenRouter
- deterministic validation
- deterministic auto-fix
- сохранение результата в `meal_plans`
- shopping list из сохранённого плана

Это не старый demo pipeline и не статический JSON.

## 10. Быстрая backend-проверка генерации

Если нужно проверить без UI:

```bash
curl -s -X POST http://127.0.0.1:8000/api/users \
  -H 'Content-Type: application/json' \
  -d '{
    "email": "demo@example.com",
    "password": "demo-password",
    "age": 30,
    "weight_kg": 75,
    "height_cm": 175,
    "gender": "male",
    "activity_level": "moderate",
    "goal": "maintain",
    "allergies": [],
    "preferences": ["высокобелковый", "быстрый"],
    "disliked_ingredients": [],
    "diseases": []
  }'
```

Затем взять `id` из ответа:

```bash
curl -s -X POST http://127.0.0.1:8000/api/generate-plan \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"<USER_ID>","days":3,"mode":"agent_cli"}'
```

Проверить задачу:

```bash
curl -s http://127.0.0.1:8000/api/tasks/<TASK_ID>
```

Когда статус станет `READY`, получить план:

```bash
curl -s http://127.0.0.1:8000/api/plans/<PLAN_ID>
curl -s http://127.0.0.1:8000/api/plans/<PLAN_ID>/shopping-list
```

## 11. Тесты

Backend:

```bash
cd backend
uv run pytest -q
```

Frontend:

```bash
cd frontend
npm run build
```

## 12. Частые проблемы

### `relation "recipes" does not exist`

Миграции не применены или подключение идёт не к той базе.

Проверь:

```bash
psql postgresql://nutriagent:nutriagent@localhost:5433/nutriagent -c '\dt'
```

Затем:

```bash
cd backend
uv run alembic upgrade heads
```

### `Failed to fetch` во frontend

Проверь, что backend запущен на `127.0.0.1:8000`, а frontend открыт на `127.0.0.1:4321`.

### Повтор блюда между днями

Для 3 дней это не должно быть стабильной ошибкой. Для 7 дней это ожидаемый текущий риск: каталог ещё нужно расширять и улучшать retrieval/diversity policy.

### OpenRouter 400 из-за JSON

Проверь, что модель поддерживает `response_format=json_object`, а `OPENROUTER_API_KEY` валиден.

## 13. Что ещё не production-ready

- 7-дневная генерация без повторов пока не гарантирована.
- Каталог рецептов ещё нужно расширять через controlled source discovery.
- Dedupe canonical recipes нужно усилить по нормализованным ингредиентам, а не только по сырой строке.
- `gastronom.ru` extractor/research output требует отдельной доработки.
- pgvector-поиск и embedding lifecycle ещё не доведены до полноценного retrieval layer.
