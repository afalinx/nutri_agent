# Запуск инфраструктуры

## Описание
Поднимает необходимые сервисы (PostgreSQL + Redis) и проверяет их работу.

## Когда использовать
- "Запусти проект"
- "Подними БД"
- "Setup" / "Start"

## Инструкции

### Шаг 1: Docker
```bash
cd /Users/dmitriy/Downloads/Диплом && docker compose -p nutriagent up -d db redis
```

### Шаг 2: Проверка
```bash
docker compose -p nutriagent ps
```
Убедись, что `db` и `redis` в статусе `Up (healthy)`.

### Шаг 3: Миграции (если нужно)
```bash
cd backend && PYTHONPATH=. alembic upgrade head
```

### Шаг 4: Сидирование рецептов (если база пустая)
```bash
cd backend && PYTHONPATH=. python scripts/seed_recipes.py
```

### Шаг 5: API сервер (если нужен)
```bash
cd backend && uvicorn app.main:app --reload --port 8000
```

## Порты
- PostgreSQL: `localhost:5433` (внутри Docker — `db:5432`)
- Redis: `localhost:6379`
- API: `localhost:8000`
