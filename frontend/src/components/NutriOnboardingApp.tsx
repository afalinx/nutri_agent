import { useState } from "react";
import type { FormEvent } from "react";

type ActivityLevel =
  | "sedentary"
  | "light"
  | "moderate"
  | "active"
  | "very_active";

type Goal = "lose" | "maintain" | "gain";
type Gender = "male" | "female";

type MealItem = {
  type: string;
  recipe_id: string;
  title: string;
  calories: number;
  protein: number;
  fat: number;
  carbs: number;
  ingredients_summary: Array<{ name: string; amount: number; unit: string }>;
};

type DayPlan = {
  day_number: number;
  total_calories: number;
  total_protein: number;
  total_fat: number;
  total_carbs: number;
  meals: MealItem[];
};

type WeeklyPlan = {
  total_days: number;
  daily_target_calories: number;
  days: DayPlan[];
};

type RecipeDetail = {
  id: string;
  title: string;
  description?: string;
  ingredients: Array<{ name: string; amount: number; unit: string }>;
  calories: number;
  protein: number;
  fat: number;
  carbs: number;
  tags?: string[];
};

const API_BASE = import.meta.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const MAX_STEP = 4;

function splitList(input: string): string[] {
  return input
    .split(/[,;\n]/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export default function NutriOnboardingApp() {
  const [step, setStep] = useState(1);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const [plan, setPlan] = useState<WeeklyPlan | null>(null);
  const [activeDay, setActiveDay] = useState(1);
  const [openRecipeId, setOpenRecipeId] = useState<string | null>(null);
  const [recipesMap, setRecipesMap] = useState<Record<string, RecipeDetail>>({});

  const [form, setForm] = useState({
    email: "",
    password: "",
    age: "30",
    weight_kg: "75",
    height_cm: "175",
    gender: "male" as Gender,
    activity_level: "moderate" as ActivityLevel,
    goal: "maintain" as Goal,
    allergies: "",
    preferences: "",
    disliked_ingredients: "",
    diseases: "",
  });

  function updateField<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function nextStep() {
    if (step === 1) {
      if (!form.email.trim() || !form.password.trim()) {
        setError("Заполните email и пароль.");
        return;
      }
    }
    setError("");
    setStep((prev) => Math.min(MAX_STEP, prev + 1));
  }

  function prevStep() {
    setError("");
    setStep((prev) => Math.max(1, prev - 1));
  }

  async function loadRecipeDetails(planData: WeeklyPlan) {
    const ids = Array.from(
      new Set(planData.days.flatMap((day) => day.meals.map((meal) => meal.recipe_id))),
    );

    try {
      const response = await fetch(`${API_BASE}/api/recipes/batch`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ recipe_ids: ids }),
      });

      if (!response.ok) {
        return;
      }

      const recipes = (await response.json()) as RecipeDetail[];
      const map: Record<string, RecipeDetail> = {};
      for (const recipe of recipes) {
        map[recipe.id] = recipe;
      }
      setRecipesMap(map);
    } catch {
      // Fallback: silent fail, recipes will show summary from plan
    }
  }

  async function generateWeeklyPlan(event: FormEvent) {
    event.preventDefault();
    setError("");
    setStatus("Создаём профиль...");
    setIsSubmitting(true);

    try {
      const createUserBody = {
        email: form.email.trim(),
        password: form.password,
        age: Number(form.age),
        weight_kg: Number(form.weight_kg),
        height_cm: Number(form.height_cm),
        gender: form.gender,
        activity_level: form.activity_level,
        goal: form.goal,
        allergies: splitList(form.allergies),
        preferences: splitList(form.preferences),
        disliked_ingredients: splitList(form.disliked_ingredients),
        diseases: splitList(form.diseases),
      };

      const userResponse = await fetch(`${API_BASE}/api/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(createUserBody),
      });

      if (!userResponse.ok) {
        const details = await userResponse.text();
        throw new Error(`Не удалось создать профиль: ${details}`);
      }

      const userData = (await userResponse.json()) as { id: string };
      setStatus("Профиль создан. Запускаем AI-генерацию плана...");

      const generateResponse = await fetch(`${API_BASE}/api/generate-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userData.id, days: 7 }),
      });

      if (!generateResponse.ok) {
        const details = await generateResponse.text();
        throw new Error(`Не удалось запустить генерацию: ${details}`);
      }

      const generation = (await generateResponse.json()) as { task_id: string };
      let readyPlanId = "";
      let elapsedMs = 0;

      for (let attempt = 0; attempt < 120; attempt += 1) {
        // Exponential backoff: 2s → 4s → 6s
        const delay = elapsedMs < 30000 ? 2000 : elapsedMs < 60000 ? 4000 : 6000;
        await sleep(delay);
        elapsedMs += delay;

        const taskResponse = await fetch(`${API_BASE}/api/tasks/${generation.task_id}`);
        if (!taskResponse.ok) {
          throw new Error("Не удалось получить статус генерации.");
        }
        const task = (await taskResponse.json()) as {
          status: string;
          plan_id?: string;
          error?: string;
        };

        setStatus(`Генерация: ${task.status}`);

        if (task.status === "READY" && task.plan_id) {
          readyPlanId = task.plan_id;
          break;
        }
        if (task.status === "FAILED") {
          throw new Error(task.error || "Генерация завершилась с ошибкой.");
        }
      }

      if (!readyPlanId) {
        throw new Error("Генерация не завершилась вовремя. Попробуйте снова.");
      }

      setStatus("Загружаем недельный рацион...");
      const planResponse = await fetch(`${API_BASE}/api/plans/${readyPlanId}`);
      if (!planResponse.ok) {
        throw new Error("Не удалось получить готовый план.");
      }
      const payload = (await planResponse.json()) as { plan_data: WeeklyPlan | null };
      if (!payload.plan_data) {
        throw new Error("План пустой. Проверьте логи backend.");
      }

      const normalizedDays = [...payload.plan_data.days].sort(
        (a, b) => a.day_number - b.day_number,
      );
      const normalizedPlan = { ...payload.plan_data, days: normalizedDays };

      setPlan(normalizedPlan);
      setActiveDay(normalizedDays[0]?.day_number ?? 1);
      setOpenRecipeId(null);
      await loadRecipeDetails(normalizedPlan);

      setStatus("Готово: персонализированный рацион сформирован.");
      setStep(5);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Неизвестная ошибка.");
      setStatus("");
    } finally {
      setIsSubmitting(false);
    }
  }

  const activeDayPlan = plan?.days.find((day) => day.day_number === activeDay) ?? null;

  return (
    <main className="page-shell">
      <section className="hero">
        <article className="hero-card">
          <h1>Nutri Agent MVP</h1>
          <p>
            Онбординг собирает ваш профиль, затем backend создаёт пользователя, агент формирует
            рацион на 7 дней и возвращает детальный план по каждому приёму пищи.
          </p>
          <div className="meta">
            <span className="pill">Astro + React</span>
            <span className="pill">FastAPI + Redis + Postgres</span>
            <span className="pill">LLM с валидацией</span>
          </div>
        </article>
        <article className="card">
          <div className="small">Шаг {Math.min(step, MAX_STEP)} из 4</div>
          <h3 style={{ marginTop: 8 }}>
            {step < 5 ? "Онбординг пользователя" : "Ваш недельный рацион готов"}
          </h3>
          {status && (
            <div className="status-box">
              <strong>Статус:</strong> {status}
            </div>
          )}
          {error && <div className="error">{error}</div>}
        </article>
      </section>

      {step < 5 && (
        <section className="card">
          <form onSubmit={generateWeeklyPlan}>
            <div className="form-grid">
              {step === 1 && (
                <>
                  <div className="field">
                    <label htmlFor="email">Email</label>
                    <input
                      id="email"
                      type="email"
                      value={form.email}
                      onChange={(e) => updateField("email", e.target.value)}
                      placeholder="user@example.com"
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="password">Пароль</label>
                    <input
                      id="password"
                      type="password"
                      value={form.password}
                      onChange={(e) => updateField("password", e.target.value)}
                      placeholder="Минимум 6 символов"
                      minLength={6}
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="age">Возраст</label>
                    <input
                      id="age"
                      type="number"
                      value={form.age}
                      onChange={(e) => updateField("age", e.target.value)}
                      min={10}
                      max={120}
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="weight_kg">Вес (кг)</label>
                    <input
                      id="weight_kg"
                      type="number"
                      value={form.weight_kg}
                      onChange={(e) => updateField("weight_kg", e.target.value)}
                      min={20}
                      max={300}
                      step="0.1"
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="height_cm">Рост (см)</label>
                    <input
                      id="height_cm"
                      type="number"
                      value={form.height_cm}
                      onChange={(e) => updateField("height_cm", e.target.value)}
                      min={80}
                      max={260}
                      step="0.1"
                      required
                    />
                  </div>
                  <div className="field">
                    <label htmlFor="gender">Пол</label>
                    <select
                      id="gender"
                      value={form.gender}
                      onChange={(e) => updateField("gender", e.target.value as Gender)}
                    >
                      <option value="male">Мужской</option>
                      <option value="female">Женский</option>
                    </select>
                  </div>
                </>
              )}

              {step === 2 && (
                <>
                  <div className="field">
                    <label htmlFor="activity_level">Уровень активности</label>
                    <select
                      id="activity_level"
                      value={form.activity_level}
                      onChange={(e) =>
                        updateField("activity_level", e.target.value as ActivityLevel)
                      }
                    >
                      <option value="sedentary">Сидячий</option>
                      <option value="light">Лёгкая активность</option>
                      <option value="moderate">Умеренная активность</option>
                      <option value="active">Высокая активность</option>
                      <option value="very_active">Очень высокая активность</option>
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="goal">Цель</label>
                    <select
                      id="goal"
                      value={form.goal}
                      onChange={(e) => updateField("goal", e.target.value as Goal)}
                    >
                      <option value="lose">Снижение веса</option>
                      <option value="maintain">Поддержание</option>
                      <option value="gain">Набор массы</option>
                    </select>
                  </div>
                  <div className="field wide">
                    <label htmlFor="preferences">
                      Предпочтения (через запятую: рыба, без глютена, высокобелковый)
                    </label>
                    <textarea
                      id="preferences"
                      value={form.preferences}
                      onChange={(e) => updateField("preferences", e.target.value)}
                    />
                  </div>
                </>
              )}

              {step === 3 && (
                <>
                  <div className="field wide">
                    <label htmlFor="allergies">Аллергии (через запятую)</label>
                    <textarea
                      id="allergies"
                      value={form.allergies}
                      onChange={(e) => updateField("allergies", e.target.value)}
                      placeholder="орехи, молоко, яйца"
                    />
                  </div>
                  <div className="field wide">
                    <label htmlFor="disliked_ingredients">Что не любите (ингредиенты)</label>
                    <textarea
                      id="disliked_ingredients"
                      value={form.disliked_ingredients}
                      onChange={(e) => updateField("disliked_ingredients", e.target.value)}
                      placeholder="лук, брокколи, печень"
                    />
                  </div>
                  <div className="field wide">
                    <label htmlFor="diseases">Заболевания/состояния</label>
                    <textarea
                      id="diseases"
                      value={form.diseases}
                      onChange={(e) => updateField("diseases", e.target.value)}
                      placeholder="diabetes, gastritis, hypertension"
                    />
                  </div>
                </>
              )}

              {step === 4 && (
                <>
                  <div className="field wide">
                    <label>Проверьте данные перед отправкой</label>
                    <div className="status-box">
                      <div>
                        <strong>Пользователь:</strong> {form.email}
                      </div>
                      <div>
                        <strong>Параметры:</strong> {form.gender}, {form.age} лет, {form.weight_kg}{" "}
                        кг, {form.height_cm} см
                      </div>
                      <div>
                        <strong>Цель:</strong> {form.goal} | <strong>Активность:</strong>{" "}
                        {form.activity_level}
                      </div>
                      <div>
                        <strong>Предпочтения:</strong> {form.preferences || "не указаны"}
                      </div>
                      <div>
                        <strong>Аллергии:</strong> {form.allergies || "не указаны"}
                      </div>
                      <div>
                        <strong>Не любит:</strong> {form.disliked_ingredients || "не указано"}
                      </div>
                      <div>
                        <strong>Заболевания:</strong> {form.diseases || "не указаны"}
                      </div>
                    </div>
                  </div>
                </>
              )}
            </div>

            <div className="actions">
              <div>
                {step > 1 && (
                  <button
                    type="button"
                    className="btn btn-secondary"
                    onClick={prevStep}
                    disabled={isSubmitting}
                  >
                    Назад
                  </button>
                )}
              </div>
              <div>
                {step < MAX_STEP && (
                  <button
                    type="button"
                    className="btn btn-primary"
                    onClick={nextStep}
                    disabled={isSubmitting}
                  >
                    Далее
                  </button>
                )}
                {step === MAX_STEP && (
                  <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
                    {isSubmitting ? "Генерация..." : "Сформировать рацион на неделю"}
                  </button>
                )}
              </div>
            </div>
          </form>
        </section>
      )}

      {step === 5 && plan && (
        <section className="card">
          <h3 style={{ marginTop: 0 }}>Недельный план питания</h3>
          <p className="small">
            Целевой калораж: <strong>{plan.daily_target_calories}</strong> ккал в день
          </p>

          <div className="days-head">
            {plan.days.map((day) => (
              <button
                key={day.day_number}
                className={`day-chip ${activeDay === day.day_number ? "active" : ""}`}
                type="button"
                onClick={() => {
                  setActiveDay(day.day_number);
                  setOpenRecipeId(null);
                }}
              >
                День {day.day_number}
              </button>
            ))}
          </div>

          {activeDayPlan && (
            <>
              <div className="status-box">
                <strong>Итоги дня:</strong> {Math.round(activeDayPlan.total_calories)} ккал | Б{" "}
                {Math.round(activeDayPlan.total_protein)} г | Ж{" "}
                {Math.round(activeDayPlan.total_fat)} г | У {Math.round(activeDayPlan.total_carbs)} г
              </div>

              <div className="meals-grid">
                {activeDayPlan.meals.map((meal) => {
                  const recipe = recipesMap[meal.recipe_id];
                  const isOpen = openRecipeId === meal.recipe_id;

                  return (
                    <article key={`${meal.recipe_id}-${meal.type}`} className="meal-card">
                      <div className="small">{meal.type.toUpperCase()}</div>
                      <h4>{meal.title}</h4>
                      <div className="macro">
                        {Math.round(meal.calories)} ккал | Б {Math.round(meal.protein)} | Ж{" "}
                        {Math.round(meal.fat)} | У {Math.round(meal.carbs)}
                      </div>

                      <div style={{ marginTop: 10 }}>
                        <button
                          type="button"
                          className="btn btn-secondary"
                          onClick={() => setOpenRecipeId(isOpen ? null : meal.recipe_id)}
                        >
                          {isOpen ? "Скрыть рецепт" : "Показать рецепт"}
                        </button>
                      </div>

                      {isOpen && (
                        <div className="recipe-detail">
                          <div>
                            <strong>Как приготовить:</strong>{" "}
                            {recipe?.description || "Инструкция недоступна в БД."}
                          </div>
                          <div style={{ marginTop: 8 }}>
                            <strong>Состав:</strong>
                            <ul>
                              {(recipe?.ingredients || meal.ingredients_summary).map((ingredient) => (
                                <li key={`${ingredient.name}-${ingredient.amount}-${ingredient.unit}`}>
                                  {ingredient.name}: {ingredient.amount} {ingredient.unit}
                                </li>
                              ))}
                            </ul>
                          </div>
                        </div>
                      )}
                    </article>
                  );
                })}
              </div>
            </>
          )}

          <div className="actions">
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => {
                setStep(1);
                setPlan(null);
                setRecipesMap({});
                setActiveDay(1);
                setOpenRecipeId(null);
                setStatus("");
                setError("");
              }}
            >
              Новый онбординг
            </button>
          </div>
        </section>
      )}
    </main>
  );
}
