import { useEffect, useState } from "react";
import type { FormEvent } from "react";

type ActivityLevel = "sedentary" | "light" | "moderate" | "active" | "very_active";
type Goal = "lose" | "maintain" | "gain";
type Gender = "male" | "female";

type MealItem = {
  type: string;
  time: string;
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
  user_profile?: {
    target_calories?: number;
  };
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
  prep_time_min?: number;
};

type ShoppingItem = {
  name: string;
  amount: number;
  unit: string;
};

type PipelineStep = {
  key: string;
  status: "pending" | "running" | "completed" | "failed" | "skipped";
  message: string;
};

type TaskStatus = {
  task_id: string;
  mode?: string | null;
  status: "PENDING" | "RUNNING" | "READY" | "FAILED";
  quality_status?: "valid" | "partially_valid" | "failed" | null;
  current_step?: string | null;
  steps: PipelineStep[];
  plan_id?: string | null;
  warnings?: string[] | null;
  error?: string | null;
  shopping_list?: ShoppingItem[] | null;
};

const API_BASE = import.meta.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const MAX_STEP = 4;
const DEFAULT_DAYS = 3;

function buildDemoEmail() {
  return `demo+${Math.floor(Date.now() / 1000)}@nutriagent.local`;
}

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

function formatMealType(value: string): string {
  const labels: Record<string, string> = {
    breakfast: "Завтрак",
    lunch: "Обед",
    dinner: "Ужин",
    snack: "Перекус",
    second_snack: "Второй перекус",
  };
  return labels[value] ?? value;
}

function formatStepLabel(value: string): string {
  const labels: Record<string, string> = {
    context: "context",
    generate: "generate",
    validate: "validate",
    "auto-fix": "auto-fix",
    save: "save",
    "shopping-list": "shopping-list",
  };
  return labels[value] ?? value;
}

function formatStepState(value: PipelineStep["status"]): string {
  const labels: Record<PipelineStep["status"], string> = {
    pending: "Ожидает",
    running: "В работе",
    completed: "Готово",
    failed: "Ошибка",
    skipped: "Пропущено",
  };
  return labels[value];
}

export default function NutriOnboardingApp() {
  const [step, setStep] = useState(1);
  const [status, setStatus] = useState("Заполните профиль и запустите генерацию через agent_cli.");
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [task, setTask] = useState<TaskStatus | null>(null);
  const [planId, setPlanId] = useState("");
  const [plan, setPlan] = useState<WeeklyPlan | null>(null);
  const [shoppingList, setShoppingList] = useState<ShoppingItem[]>([]);
  const [warnings, setWarnings] = useState<string[]>([]);
  const [activeDay, setActiveDay] = useState(1);
  const [openRecipeId, setOpenRecipeId] = useState<string | null>(null);
  const [recipesMap, setRecipesMap] = useState<Record<string, RecipeDetail>>({});
  const [copied, setCopied] = useState(false);

  const [form, setForm] = useState({
    email: buildDemoEmail(),
    password: "demo123",
    age: "30",
    weight_kg: "75",
    height_cm: "175",
    gender: "male" as Gender,
    activity_level: "moderate" as ActivityLevel,
    goal: "maintain" as Goal,
    allergies: "",
    preferences: "высокобелковый, быстрый",
    disliked_ingredients: "",
    diseases: "",
  });

  useEffect(() => {
    if (!copied) {
      return undefined;
    }
    const timeoutId = window.setTimeout(() => setCopied(false), 1800);
    return () => window.clearTimeout(timeoutId);
  }, [copied]);

  function updateField<K extends keyof typeof form>(key: K, value: (typeof form)[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function nextStep() {
    if (step === 1 && (!form.email.trim() || !form.password.trim())) {
      setError("Заполните email и пароль.");
      return;
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

    if (ids.length === 0) {
      setRecipesMap({});
      return;
    }

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
      const nextMap: Record<string, RecipeDetail> = {};
      for (const recipe of recipes) {
        nextMap[recipe.id] = recipe;
      }
      setRecipesMap(nextMap);
    } catch {
      setRecipesMap({});
    }
  }

  async function loadPlanArtifacts(nextPlanId: string, fallbackShoppingList?: ShoppingItem[] | null) {
    const [planResponse, shoppingResponse] = await Promise.all([
      fetch(`${API_BASE}/api/plans/${nextPlanId}`),
      fetch(`${API_BASE}/api/plans/${nextPlanId}/shopping-list`),
    ]);

    if (!planResponse.ok) {
      throw new Error("Не удалось получить готовый план.");
    }

    const planPayload = (await planResponse.json()) as {
      plan_data: WeeklyPlan | null;
      warnings?: string[];
      quality_status?: string | null;
    };
    if (!planPayload.plan_data?.days?.length) {
      throw new Error("План пустой. Для демо не удалось собрать ни одного дня.");
    }

    const normalizedDays = [...planPayload.plan_data.days].sort((a, b) => a.day_number - b.day_number);
    const normalizedPlan = { ...planPayload.plan_data, days: normalizedDays };
    setPlan(normalizedPlan);
    setActiveDay(normalizedDays[0]?.day_number ?? 1);
    if (planPayload.warnings?.length) {
      setWarnings((prev) => Array.from(new Set([...prev, ...planPayload.warnings!])));
    }

    if (shoppingResponse.ok) {
      const shoppingPayload = (await shoppingResponse.json()) as { items: ShoppingItem[] };
      setShoppingList(shoppingPayload.items);
    } else {
      setShoppingList(fallbackShoppingList ?? []);
    }

    await loadRecipeDetails(normalizedPlan);
  }

  async function pollTask(taskId: string) {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await sleep(1200);

      const response = await fetch(`${API_BASE}/api/tasks/${taskId}`);
      if (!response.ok) {
        throw new Error("Не удалось получить статус пайплайна.");
      }

      const payload = (await response.json()) as TaskStatus;
      setTask(payload);
      setWarnings(payload.warnings ?? []);

      const runningStep = payload.steps.find((item) => item.status === "running");
      if (payload.status === "FAILED") {
        throw new Error(
          payload.error || "Пайплайн остановился с ошибкой. Проверьте текст этапа validate/auto-fix.",
        );
      }

      if (payload.status === "READY" && payload.plan_id) {
        setStatus("План готов. Загружаем артефакты.");
        setPlanId(payload.plan_id);
        await loadPlanArtifacts(payload.plan_id, payload.shopping_list);
        return;
      }

      if (runningStep) {
        setStatus(`${formatStepLabel(runningStep.key)}: ${runningStep.message}`);
      }
    }

    throw new Error("Пайплайн не завершился вовремя. Попробуйте перезапустить генерацию.");
  }

  async function generateWeeklyPlan(event: FormEvent) {
    event.preventDefault();
    setError("");
    setTask(null);
    setPlan(null);
    setPlanId("");
    setShoppingList([]);
    setWarnings([]);
    setRecipesMap({});
    setOpenRecipeId(null);
    setCopied(false);
    setIsSubmitting(true);
    setStatus("Создаём профиль пользователя.");

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
      setStatus("Профиль создан. Запускаем agent_cli pipeline.");
      setStep(5);

      const generateResponse = await fetch(`${API_BASE}/api/generate-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: userData.id, days: DEFAULT_DAYS, mode: "agent_cli" }),
      });

      if (!generateResponse.ok) {
        const details = await generateResponse.text();
        throw new Error(`Не удалось запустить пайплайн: ${details}`);
      }

      const generation = (await generateResponse.json()) as { task_id: string };
      await pollTask(generation.task_id);
      setStatus("Готово: можно показать план, блюда и список покупок.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Неизвестная ошибка.");
      setStatus("Генерация не завершилась. Исправьте профиль или перезапустите pipeline.");
    } finally {
      setIsSubmitting(false);
    }
  }

  async function copyShoppingList() {
    try {
      const content = shoppingList.map((item) => `${item.name} — ${item.amount} ${item.unit}`).join("\n");
      await navigator.clipboard.writeText(content);
      setCopied(true);
    } catch {
      setError("Не удалось скопировать список покупок.");
    }
  }

  const activeDayPlan = plan?.days.find((day) => day.day_number === activeDay) ?? null;
  const activeRecipe = openRecipeId ? recipesMap[openRecipeId] : null;

  return (
    <main className="page-shell">
      <section className="hero">
        <article className="hero-card">
          <h1>NutriAgent Agent CLI</h1>
          <p>
            Полный пользовательский сценарий: онбординг, запуск agent_cli-пайплайна, статус
            этапов, готовый план, карточки блюд и агрегированный список покупок.
          </p>
          <div className="meta">
            <span className="pill">Onboarding</span>
            <span className="pill">agent_cli pipeline</span>
            <span className="pill">Plan + Recipes + Shopping list</span>
          </div>
        </article>

        <article className="card">
          <div className="small">Шаг {Math.min(step, MAX_STEP)} из 4</div>
          <h3 style={{ marginTop: 8 }}>
            {step < 5 ? "Подготовка профиля" : "План готов"}
          </h3>
          <div className="status-box">
            <strong>Статус:</strong> {status}
          </div>
          {error && <div className="error">{error}</div>}
          {warnings.length > 0 && (
            <div className="warning-box">
              <strong>Важно:</strong> {warnings[0]}
            </div>
          )}
          <div className="kpi-row">
            <div className="kpi-card">
              <span className="small">Запуск</span>
              <strong>1 кнопка</strong>
            </div>
            <div className="kpi-card">
              <span className="small">Дней в демо</span>
              <strong>{DEFAULT_DAYS}</strong>
            </div>
            <div className="kpi-card">
              <span className="small">Артефакты</span>
              <strong>4 экрана</strong>
            </div>
          </div>
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
                    <label htmlFor="weight_kg">Вес, кг</label>
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
                    <label htmlFor="height_cm">Рост, см</label>
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
                    <label htmlFor="activity_level">Активность</label>
                    <select
                      id="activity_level"
                      value={form.activity_level}
                      onChange={(e) => updateField("activity_level", e.target.value as ActivityLevel)}
                    >
                      <option value="sedentary">Сидячий</option>
                      <option value="light">Лёгкая</option>
                      <option value="moderate">Умеренная</option>
                      <option value="active">Высокая</option>
                      <option value="very_active">Очень высокая</option>
                    </select>
                  </div>
                  <div className="field">
                    <label htmlFor="goal">Цель</label>
                    <select id="goal" value={form.goal} onChange={(e) => updateField("goal", e.target.value as Goal)}>
                      <option value="lose">Снижение веса</option>
                      <option value="maintain">Поддержание</option>
                      <option value="gain">Набор</option>
                    </select>
                  </div>
                  <div className="field wide">
                    <label htmlFor="preferences">Предпочтения</label>
                    <textarea
                      id="preferences"
                      value={form.preferences}
                      onChange={(e) => updateField("preferences", e.target.value)}
                      placeholder="рыба, без глютена, высокобелковый"
                    />
                  </div>
                </>
              )}

              {step === 3 && (
                <>
                  <div className="field wide">
                    <label htmlFor="allergies">Аллергии</label>
                    <textarea
                      id="allergies"
                      value={form.allergies}
                      onChange={(e) => updateField("allergies", e.target.value)}
                      placeholder="орехи, молоко"
                    />
                  </div>
                  <div className="field wide">
                    <label htmlFor="disliked_ingredients">Нелюбимые ингредиенты</label>
                    <textarea
                      id="disliked_ingredients"
                      value={form.disliked_ingredients}
                      onChange={(e) => updateField("disliked_ingredients", e.target.value)}
                      placeholder="лук, печень, брокколи"
                    />
                  </div>
                  <div className="field wide">
                    <label htmlFor="diseases">Состояния / ограничения</label>
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
                <div className="field wide">
                  <label>Краткое резюме перед запуском</label>
                  <div className="summary-grid">
                    <div className="summary-item">
                      <span className="small">Профиль</span>
                      <strong>{form.email}</strong>
                    </div>
                    <div className="summary-item">
                      <span className="small">Параметры</span>
                      <strong>
                        {form.gender}, {form.age} лет, {form.weight_kg} кг, {form.height_cm} см
                      </strong>
                    </div>
                    <div className="summary-item">
                      <span className="small">Цель</span>
                      <strong>
                        {form.goal} / {form.activity_level}
                      </strong>
                    </div>
                    <div className="summary-item">
                      <span className="small">Предпочтения</span>
                      <strong>{form.preferences || "не указаны"}</strong>
                    </div>
                    <div className="summary-item">
                      <span className="small">Аллергии</span>
                      <strong>{form.allergies || "не указаны"}</strong>
                    </div>
                    <div className="summary-item">
                      <span className="small">Ограничения</span>
                      <strong>{form.diseases || "не указаны"}</strong>
                    </div>
                  </div>
                </div>
              )}
            </div>

            <div className="actions">
              <div>
                {step > 1 && (
                  <button type="button" className="btn btn-secondary" onClick={prevStep} disabled={isSubmitting}>
                    Назад
                  </button>
                )}
              </div>
              <div>
                {step < MAX_STEP && (
                  <button type="button" className="btn btn-primary" onClick={nextStep} disabled={isSubmitting}>
                    Далее
                  </button>
                )}
                {step === MAX_STEP && (
                  <button type="submit" className="btn btn-primary" disabled={isSubmitting}>
                    {isSubmitting ? "Собираем рацион..." : "Составить план"}
                  </button>
                )}
              </div>
            </div>
          </form>
        </section>
      )}

      {step === 5 && (
        <section className="content-grid">
          <article className="card">
            <div className="section-head">
              <div>
                <div className="small">Pipeline</div>
                <h3>Статус выполнения</h3>
              </div>
              <div className="plan-badge">
                {task?.mode ? `mode: ${task.mode}` : "mode: agent_cli"}
                {planId ? ` • plan_id: ${planId}` : ""}
              </div>
            </div>

            <div className="pipeline-list">
              {(task?.steps ?? []).map((item) => (
                <div key={item.key} className={`pipeline-step is-${item.status}`}>
                  <div>
                    <strong>{formatStepLabel(item.key)}</strong>
                    <div className="small">{item.message || "Ожидает запуска."}</div>
                  </div>
                  <span className="step-state">{formatStepState(item.status)}</span>
                </div>
              ))}
              {!task && <div className="empty-state">Запуск ещё не начался.</div>}
            </div>
          </article>

          <article className="card">
            <div className="section-head">
              <div>
                <div className="small">Shopping list</div>
                <h3>Список покупок</h3>
              </div>
              <button
                type="button"
                className="btn btn-secondary"
                onClick={copyShoppingList}
                disabled={shoppingList.length === 0}
              >
                {copied ? "Скопировано" : "Скопировать"}
              </button>
            </div>

            {shoppingList.length > 0 ? (
              <div className="shopping-grid">
                {shoppingList.map((item) => (
                  <div key={`${item.name}-${item.unit}`} className="shopping-item">
                    <strong>{item.name}</strong>
                    <span>
                      {item.amount} {item.unit}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">Список покупок появится после шага shopping-list.</div>
            )}
          </article>
        </section>
      )}

      {step === 5 && plan && (
        <>
          <section className="card result-card">
            <div className="section-head">
              <div>
                <div className="small">Результат</div>
                <h3>Готовый план питания</h3>
              </div>
              <div className="day-summary">
                <span>Цель: {plan.daily_target_calories} ккал/день</span>
                <span>Дней: {plan.total_days}</span>
              </div>
            </div>

            <div className="disclaimer">
              Дисклеймер: демонстрационный рацион не заменяет консультацию врача или диетолога и
              подходит только для показа пользовательского сценария.
            </div>

            <div className="days-head">
              {plan.days.map((day) => (
                <button
                  key={day.day_number}
                  type="button"
                  className={`day-chip ${activeDay === day.day_number ? "active" : ""}`}
                  onClick={() => setActiveDay(day.day_number)}
                >
                  День {day.day_number}
                </button>
              ))}
            </div>

            {activeDayPlan ? (
              <>
                <div className="daily-overview">
                  <div className="metric-box">
                    <span className="small">Калории</span>
                    <strong>{Math.round(activeDayPlan.total_calories)}</strong>
                  </div>
                  <div className="metric-box">
                    <span className="small">Белки</span>
                    <strong>{Math.round(activeDayPlan.total_protein)} г</strong>
                  </div>
                  <div className="metric-box">
                    <span className="small">Жиры</span>
                    <strong>{Math.round(activeDayPlan.total_fat)} г</strong>
                  </div>
                  <div className="metric-box">
                    <span className="small">Углеводы</span>
                    <strong>{Math.round(activeDayPlan.total_carbs)} г</strong>
                  </div>
                </div>

                <div className="meals-grid">
                  {activeDayPlan.meals.map((meal) => (
                    <article key={`${activeDayPlan.day_number}-${meal.type}`} className="meal-card">
                      <div className="meal-topline">
                        <span className="pill">{formatMealType(meal.type)}</span>
                        <span className="small">{meal.time}</span>
                      </div>
                      <h4>{meal.title}</h4>
                      <div className="macro">
                        {Math.round(meal.calories)} ккал • Б {Math.round(meal.protein)} • Ж{" "}
                        {Math.round(meal.fat)} • У {Math.round(meal.carbs)}
                      </div>
                      <div className="ingredients-preview">
                        {(meal.ingredients_summary || []).slice(0, 3).map((item) => item.name).join(", ") ||
                          "Ингредиенты появятся после загрузки карточки."}
                      </div>
                      <button
                        type="button"
                        className="btn btn-secondary"
                        onClick={() => setOpenRecipeId(meal.recipe_id)}
                      >
                        Открыть карточку блюда
                      </button>
                    </article>
                  ))}
                </div>
              </>
            ) : (
              <div className="empty-state">День не выбран или план ещё не загружен.</div>
            )}
          </section>

          {openRecipeId && (
            <div className="modal-backdrop" onClick={() => setOpenRecipeId(null)} role="presentation">
              <div className="modal-card" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
                <div className="section-head">
                  <div>
                    <div className="small">Карточка блюда</div>
                    <h3>{activeRecipe?.title ?? "Загружаем рецепт"}</h3>
                  </div>
                  <button type="button" className="btn btn-secondary" onClick={() => setOpenRecipeId(null)}>
                    Закрыть
                  </button>
                </div>

                {activeRecipe ? (
                  <>
                    <p className="modal-description">
                      {activeRecipe.description || "Описание пока не заполнено, но КБЖУ и ингредиенты уже доступны."}
                    </p>
                    <div className="daily-overview compact">
                      <div className="metric-box">
                        <span className="small">Калории</span>
                        <strong>{Math.round(activeRecipe.calories)}</strong>
                      </div>
                      <div className="metric-box">
                        <span className="small">Белки</span>
                        <strong>{Math.round(activeRecipe.protein)} г</strong>
                      </div>
                      <div className="metric-box">
                        <span className="small">Жиры</span>
                        <strong>{Math.round(activeRecipe.fat)} г</strong>
                      </div>
                      <div className="metric-box">
                        <span className="small">Углеводы</span>
                        <strong>{Math.round(activeRecipe.carbs)} г</strong>
                      </div>
                    </div>
                    <div className="ingredients-list">
                      {activeRecipe.ingredients.map((ingredient) => (
                        <div key={`${ingredient.name}-${ingredient.unit}-${ingredient.amount}`} className="ingredient-row">
                          <span>{ingredient.name}</span>
                          <strong>
                            {ingredient.amount} {ingredient.unit}
                          </strong>
                        </div>
                      ))}
                    </div>
                  </>
                ) : (
                  <div className="empty-state">Карточка блюда пока недоступна.</div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </main>
  );
}
