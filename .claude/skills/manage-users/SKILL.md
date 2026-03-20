# Управление пользователями

## Описание
Создание и управление профилями пользователей через API или CLI.

## Когда использовать
- "Создай нового пользователя"
- "Покажи профиль"
- "Измени цель / вес / аллергии"

## Инструкции

### Посмотреть всех пользователей
```bash
cd backend && PYTHONPATH=. python cli.py users
```

### Создать пользователя через API
Убедись, что сервер запущен (`uvicorn app.main:app --port 8000`), затем:
```bash
curl -s -X POST http://localhost:8000/api/users \
  -H "Content-Type: application/json" \
  -d '{
    "email": "<email>",
    "password": "<password>",
    "age": <int>,
    "weight_kg": <float>,
    "height_cm": <float>,
    "gender": "male|female",
    "activity_level": "sedentary|light|moderate|active|very_active",
    "goal": "lose|maintain|gain",
    "allergies": ["<аллерген1>", "<аллерген2>"]
  }'
```
Система автоматически рассчитает `target_calories` по формуле Миффлина-Сан Жеора.

### Обновить профиль
```bash
curl -s -X PUT http://localhost:8000/api/users/<USER_ID> \
  -H "Content-Type: application/json" \
  -d '{"goal": "lose", "weight_kg": 75}'
```
Калораж пересчитается автоматически.

## Параметры
- **gender**: male, female
- **activity_level**: sedentary (сидячий), light (лёгкая активность), moderate (умеренная), active (активный), very_active (очень активный)
- **goal**: lose (похудение, -15% калорий), maintain (поддержание), gain (набор, +15% калорий)
- **allergies**: список строк — рецепты с этими ингредиентами будут исключены из RAG-поиска
