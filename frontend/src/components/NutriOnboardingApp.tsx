import { startTransition, useEffect, useRef, useState } from "react";
import type { FormEvent, ReactNode, SVGProps } from "react";

type ActivityLevel = "sedentary" | "light" | "moderate" | "active" | "very_active";
type Goal = "lose" | "maintain" | "gain";
type Gender = "male" | "female";

type MealSlot = {
  type: string;
  time: string;
  calories_pct: number;
};

type Ingredient = {
  name: string;
  amount: number;
  unit: string;
};

type MealItem = {
  type: string;
  time?: string;
  recipe_id: string;
  title: string;
  calories: number;
  protein: number;
  fat: number;
  carbs: number;
  ingredients_summary: Ingredient[];
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
  user_profile?: {
    goal?: Goal;
  };
  total_days: number;
  daily_target_calories: number;
  days: DayPlan[];
};

type RecipeDetail = {
  id: string;
  title: string;
  description?: string;
  ingredients: Ingredient[];
  calories: number;
  protein: number;
  fat: number;
  carbs: number;
  tags?: string[];
  meal_type?: string;
  allergens?: string[];
  ingredients_short?: string;
  prep_time_min?: number;
  category?: string;
};

type ShoppingItem = {
  name: string;
  amount: number;
  unit: string;
};

type UserResponse = {
  id: string;
  email: string;
  age: number;
  weight_kg: number;
  height_cm: number;
  gender: Gender;
  activity_level: ActivityLevel;
  goal: Goal;
  allergies: string[];
  preferences: string[];
  disliked_ingredients: string[];
  diseases: string[];
  target_calories: number | null;
  meal_schedule: MealSlot[] | null;
};

type PlanResponse = {
  id: string;
  user_id: string;
  status: string;
  start_date: string | null;
  end_date: string | null;
  plan_data: WeeklyPlan | null;
};

type StoredSession = {
  userId?: string;
  planId?: string;
  taskId?: string;
};

type Screen =
  | { name: "onboarding" }
  | { name: "generating" }
  | { name: "home" }
  | { name: "weekly" }
  | { name: "shopping" }
  | { name: "profile" }
  | { name: "recipe"; recipeId: string };

type OnboardingForm = {
  email: string;
  password: string;
  age: string;
  weight_kg: string;
  height_cm: string;
  gender: Gender;
  activity_level: ActivityLevel;
  goal: Goal;
  allergies: string;
  preferences: string;
  disliked_ingredients: string;
  diseases: string;
};

type ProfileDraft = {
  age: string;
  weight_kg: string;
  height_cm: string;
  gender: Gender;
  activity_level: ActivityLevel;
  goal: Goal;
  allergies: string;
  preferences: string;
  disliked_ingredients: string;
  diseases: string;
};

type QuickAction = {
  label: string;
  description: string;
  icon: ReactNode;
  onClick: () => void;
};

const API_BASE = import.meta.env.PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const STORAGE_KEY = "nutri-agent/mobile-session/v2";
const PLAN_DAYS = 3;
const ONBOARDING_STEPS = 4;

const emptyOnboardingForm: OnboardingForm = {
  email: "",
  password: "",
  age: "30",
  weight_kg: "75",
  height_cm: "175",
  gender: "female",
  activity_level: "moderate",
  goal: "maintain",
  allergies: "",
  preferences: "",
  disliked_ingredients: "",
  diseases: "",
};

function splitList(input: string): string[] {
  return input
    .split(/[,;\n]/g)
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinList(input?: string[]): string {
  return (input ?? []).join(", ");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

function readStoredSession(): StoredSession | null {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as StoredSession) : null;
  } catch {
    return null;
  }
}

function writeStoredSession(next: StoredSession): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
}

function patchStoredSession(patch: Partial<StoredSession>): void {
  const current = readStoredSession() ?? {};
  const next = { ...current, ...patch };

  if (!next.userId && !next.planId && !next.taskId) {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(STORAGE_KEY);
    }
    return;
  }

  writeStoredSession(next);
}

function clearStoredSession(): void {
  if (typeof window !== "undefined") {
    window.localStorage.removeItem(STORAGE_KEY);
  }
}

async function readError(response: Response): Promise<string> {
  try {
    const text = await response.text();
    return text || `HTTP ${response.status}`;
  } catch {
    return `HTTP ${response.status}`;
  }
}

function formatGoal(goal: Goal | string | undefined): string {
  switch (goal) {
    case "lose":
      return "Fat loss";
    case "gain":
      return "Muscle gain";
    default:
      return "Balance";
  }
}

function formatActivity(activity: ActivityLevel | string | undefined): string {
  switch (activity) {
    case "sedentary":
      return "Low activity";
    case "light":
      return "Light activity";
    case "active":
      return "High activity";
    case "very_active":
      return "Very active";
    default:
      return "Moderate activity";
  }
}

function formatMealType(type: string): string {
  switch (type) {
    case "breakfast":
      return "Breakfast";
    case "lunch":
      return "Lunch";
    case "dinner":
      return "Dinner";
    case "snack":
      return "Snack";
    case "second_snack":
      return "Late snack";
    default:
      return type.replaceAll("_", " ");
  }
}

function mealVisualClass(type: string): string {
  switch (type) {
    case "breakfast":
      return "meal-visual breakfast";
    case "lunch":
      return "meal-visual lunch";
    case "dinner":
      return "meal-visual dinner";
    case "snack":
      return "meal-visual snack";
    default:
      return "meal-visual";
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function getTodayIndex(plan: PlanResponse | null): number {
  const totalDays = plan?.plan_data?.days.length ?? 1;
  if (!plan?.start_date) {
    return 1;
  }

  const start = new Date(`${plan.start_date}T00:00:00`);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const diff = Math.floor((today.getTime() - start.getTime()) / 86_400_000);
  return clamp(diff + 1, 1, totalDays);
}

function formatShortDate(offset = 0): string {
  const date = new Date();
  date.setDate(date.getDate() + offset);
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(date);
}

function formatPlanDayLabel(plan: PlanResponse | null, dayNumber: number): string {
  if (!plan?.start_date) {
    return formatShortDate(dayNumber - 1);
  }

  const date = new Date(`${plan.start_date}T00:00:00`);
  date.setDate(date.getDate() + dayNumber - 1);
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
  }).format(date);
}

function AppIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <rect x="3" y="3" width="18" height="18" rx="6" fill="currentColor" opacity="0.12" />
      <path
        d="M8.5 15.5c1.6 1.3 3.4 1.9 5.4 1.9 1.5 0 2.8-.4 3.6-1.3.8-.8 1.1-1.8 1.1-3 0-1.3-.4-2.4-1.3-3.1-.8-.8-1.9-1.2-3.3-1.2-1.2 0-2.3.3-3.3 1-.2-2.1-1.4-3.4-3.4-3.9"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
      <path
        d="M7 8.4c.6.7 1.4 1 2.4 1.1M6.4 12.5c.7.8 1.6 1.2 2.8 1.2"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function ArrowLeftIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path
        d="M14.5 6.5 9 12l5.5 5.5"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function CalendarIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <rect x="4" y="5" width="16" height="15" rx="4" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M8 3.5v4M16 3.5v4M4 9.5h16" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
    </svg>
  );
}

function CartIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path
        d="M7.5 7h10.8l-1.2 6.1a2 2 0 0 1-2 1.6H9.6a2 2 0 0 1-2-1.6L6 4.8H4.5"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
      <circle cx="10" cy="18.3" r="1.2" fill="currentColor" />
      <circle cx="16.6" cy="18.3" r="1.2" fill="currentColor" />
    </svg>
  );
}

function UserIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <circle cx="12" cy="8.3" r="3.5" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M5.5 19c1.8-2.8 4-4.2 6.5-4.2S16.7 16.2 18.5 19" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
    </svg>
  );
}

function SparkIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path
        d="m12 4 1.5 4.5L18 10l-4.5 1.5L12 16l-1.5-4.5L6 10l4.5-1.5L12 4Zm6.4 11.6.8 2.1 2.1.8-2.1.8-.8 2.1-.8-2.1-2.1-.8 2.1-.8.8-2.1Zm-12-1.8.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9.9-2.4Z"
        fill="currentColor"
      />
    </svg>
  );
}

function RefreshIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path
        d="M18 8.5a7 7 0 1 0 1.5 6.8M18 4.8v3.7h-3.7"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function CheckIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path
        d="m5 12.6 4.1 4.1L19 6.8"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function TimeIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" strokeWidth="1.8" />
      <path d="M12 8v4.4l2.8 1.8" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
    </svg>
  );
}

function ChevronRightIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" {...props}>
      <path
        d="m10 6.5 5.5 5.5-5.5 5.5"
        fill="none"
        stroke="currentColor"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="1.8"
      />
    </svg>
  );
}

function ScreenHeader({
  title,
  subtitle,
  onBack,
}: {
  title: string;
  subtitle?: string;
  onBack?: () => void;
}) {
  return (
    <header className="screen-header">
      <div className="screen-header__lead">
        {onBack ? (
          <button type="button" className="icon-button" onClick={onBack} aria-label="Go back">
            <ArrowLeftIcon className="icon" />
          </button>
        ) : (
          <span className="icon-button icon-button--ghost" aria-hidden="true">
            <AppIcon className="icon icon--brand" />
          </span>
        )}
        <div>
          <div className="screen-header__eyebrow">NutriAgent</div>
          <h2>{title}</h2>
        </div>
      </div>
      {subtitle ? <p className="screen-header__copy">{subtitle}</p> : null}
    </header>
  );
}

export default function NutriOnboardingApp() {
  const aliveRef = useRef(true);
  const [isBooting, setIsBooting] = useState(true);
  const [screenStack, setScreenStack] = useState<Screen[]>([{ name: "onboarding" }]);
  const [user, setUser] = useState<UserResponse | null>(null);
  const [planRecord, setPlanRecord] = useState<PlanResponse | null>(null);
  const [recipesMap, setRecipesMap] = useState<Record<string, RecipeDetail>>({});
  const [shoppingList, setShoppingList] = useState<ShoppingItem[] | null>(null);
  const [shoppingLoading, setShoppingLoading] = useState(false);
  const [shoppingCopied, setShoppingCopied] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [generationStatus, setGenerationStatus] = useState("PENDING");
  const [generationError, setGenerationError] = useState("");
  const [globalNotice, setGlobalNotice] = useState("");
  const [errorNotice, setErrorNotice] = useState("");
  const [isWorking, setIsWorking] = useState(false);
  const [isSavingProfile, setIsSavingProfile] = useState(false);
  const [selectedDayNumber, setSelectedDayNumber] = useState(1);
  const [onboardingStep, setOnboardingStep] = useState(1);
  const [onboardingForm, setOnboardingForm] = useState<OnboardingForm>(emptyOnboardingForm);
  const [profileDraft, setProfileDraft] = useState<ProfileDraft>({
    age: "",
    weight_kg: "",
    height_cm: "",
    gender: "female",
    activity_level: "moderate",
    goal: "maintain",
    allergies: "",
    preferences: "",
    disliked_ingredients: "",
    diseases: "",
  });

  const currentScreen = screenStack[screenStack.length - 1];
  const planData = planRecord?.plan_data ?? null;
  const todayIndex = getTodayIndex(planRecord);
  const todayPlan = planData?.days.find((day) => day.day_number === todayIndex) ?? planData?.days[0] ?? null;
  const todayCalories = todayPlan?.total_calories ?? 0;
  const dailyTarget = planData?.daily_target_calories ?? user?.target_calories ?? 0;
  const todayProgress = dailyTarget > 0 ? clamp(Math.round((todayCalories / dailyTarget) * 100), 0, 100) : 0;

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!user) {
      return;
    }

    setProfileDraft({
      age: String(user.age),
      weight_kg: String(user.weight_kg),
      height_cm: String(user.height_cm),
      gender: user.gender,
      activity_level: user.activity_level,
      goal: user.goal,
      allergies: joinList(user.allergies),
      preferences: joinList(user.preferences),
      disliked_ingredients: joinList(user.disliked_ingredients),
      diseases: joinList(user.diseases),
    });
  }, [user]);

  useEffect(() => {
    setSelectedDayNumber(todayIndex);
  }, [todayIndex, planRecord?.id]);

  useEffect(() => {
    async function restoreSession() {
      const stored = readStoredSession();
      if (!stored?.userId && !stored?.planId && !stored?.taskId) {
        setIsBooting(false);
        return;
      }

      try {
        if (stored.userId) {
          const restoredUser = await fetchUser(stored.userId);
          if (!aliveRef.current) {
            return;
          }
          setUser(restoredUser);
        }

        if (stored.taskId && stored.userId) {
          setTaskId(stored.taskId);
          startTransition(() => {
            setScreenStack([{ name: "generating" }]);
          });
          setIsBooting(false);
          void monitorTask(stored.taskId, stored.userId);
          return;
        }

        if (stored.planId && stored.userId) {
          await hydratePlan(stored.userId, stored.planId);
          if (!aliveRef.current) {
            return;
          }
          startTransition(() => {
            setScreenStack([{ name: "home" }]);
          });
          setIsBooting(false);
          return;
        }
      } catch {
        clearAppState();
      }

      setIsBooting(false);
    }

    void restoreSession();
  }, []);

  useEffect(() => {
    if (currentScreen.name !== "shopping" || !planRecord?.id || shoppingList || shoppingLoading) {
      return;
    }

    void loadShoppingList(planRecord.id);
  }, [currentScreen.name, planRecord?.id, shoppingList, shoppingLoading]);

  useEffect(() => {
    if (!shoppingCopied) {
      return;
    }

    const timeout = window.setTimeout(() => {
      setShoppingCopied(false);
    }, 1600);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [shoppingCopied]);

  useEffect(() => {
    if (!globalNotice && !errorNotice) {
      return;
    }

    const timeout = window.setTimeout(() => {
      setGlobalNotice("");
      setErrorNotice("");
    }, 3600);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [globalNotice, errorNotice]);

  function clearAppState() {
    clearStoredSession();
    setUser(null);
    setPlanRecord(null);
    setRecipesMap({});
    setShoppingList(null);
    setTaskId(null);
    setGenerationStatus("PENDING");
    setGenerationError("");
    setGlobalNotice("");
    setErrorNotice("");
    setIsWorking(false);
    setOnboardingStep(1);
    setOnboardingForm(emptyOnboardingForm);
    setSelectedDayNumber(1);
    startTransition(() => {
      setScreenStack([{ name: "onboarding" }]);
    });
  }

  function pushScreen(screen: Screen) {
    startTransition(() => {
      setScreenStack((current) => [...current, screen]);
    });
  }

  function resetToScreen(screen: Screen) {
    startTransition(() => {
      setScreenStack([screen]);
    });
  }

  function popScreen() {
    startTransition(() => {
      setScreenStack((current) => (current.length > 1 ? current.slice(0, -1) : current));
    });
  }

  async function fetchUser(userId: string): Promise<UserResponse> {
    const response = await fetch(`${API_BASE}/api/users/${userId}`);
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    return (await response.json()) as UserResponse;
  }

  async function fetchPlan(planId: string): Promise<PlanResponse> {
    const response = await fetch(`${API_BASE}/api/plans/${planId}`);
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    return (await response.json()) as PlanResponse;
  }

  async function loadRecipeDetails(nextPlanData: WeeklyPlan | null): Promise<void> {
    if (!nextPlanData) {
      setRecipesMap({});
      return;
    }

    const recipeIds = Array.from(
      new Set(nextPlanData.days.flatMap((day) => day.meals.map((meal) => meal.recipe_id))),
    );

    if (recipeIds.length === 0) {
      setRecipesMap({});
      return;
    }

    const response = await fetch(`${API_BASE}/api/recipes/batch`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ recipe_ids: recipeIds }),
    });

    if (!response.ok) {
      return;
    }

    const payload = (await response.json()) as RecipeDetail[];
    if (!aliveRef.current) {
      return;
    }

    const nextMap: Record<string, RecipeDetail> = {};
    for (const recipe of payload) {
      nextMap[recipe.id] = recipe;
    }
    setRecipesMap(nextMap);
  }

  async function hydratePlan(userId: string, planId: string): Promise<void> {
    const [nextUser, nextPlan] = await Promise.all([fetchUser(userId), fetchPlan(planId)]);
    if (!aliveRef.current) {
      return;
    }

    setUser(nextUser);
    setPlanRecord(nextPlan);
    patchStoredSession({ userId, planId, taskId: undefined });
    await loadRecipeDetails(nextPlan.plan_data);
  }

  async function loadShoppingList(planId: string): Promise<void> {
    setShoppingLoading(true);
    try {
      const response = await fetch(`${API_BASE}/api/plans/${planId}/shopping-list`);
      if (!response.ok) {
        throw new Error(await readError(response));
      }

      const payload = (await response.json()) as { items: ShoppingItem[] };
      if (!aliveRef.current) {
        return;
      }

      setShoppingList(payload.items);
    } catch (error) {
      if (!aliveRef.current) {
        return;
      }
      setErrorNotice(error instanceof Error ? error.message : "Could not load shopping list.");
    } finally {
      if (aliveRef.current) {
        setShoppingLoading(false);
      }
    }
  }

  async function monitorTask(nextTaskId: string, userId: string): Promise<void> {
    setTaskId(nextTaskId);
    setGenerationError("");
    setGenerationStatus("PENDING");

    for (let attempt = 0; attempt < 120; attempt += 1) {
      if (attempt > 0) {
        const delay = attempt < 10 ? 1800 : attempt < 30 ? 3200 : 5200;
        await sleep(delay);
      }

      const response = await fetch(`${API_BASE}/api/tasks/${nextTaskId}`);
      if (!response.ok) {
        const message = await readError(response);
        if (!aliveRef.current) {
          return;
        }
        setGenerationError(message);
        setErrorNotice(message);
        return;
      }

      const task = (await response.json()) as {
        status: string;
        plan_id?: string;
        error?: string;
      };

      if (!aliveRef.current) {
        return;
      }

      setGenerationStatus(task.status);

      if (task.status === "FAILED") {
        const message = task.error || "Plan generation failed.";
        setGenerationError(message);
        setErrorNotice(message);
        return;
      }

      if (task.status === "READY" && task.plan_id) {
        await hydratePlan(userId, task.plan_id);
        if (!aliveRef.current) {
          return;
        }

        patchStoredSession({ userId, planId: task.plan_id, taskId: undefined });
        setTaskId(null);
        setGlobalNotice("Your fresh week is ready.");
        setShoppingList(null);
        resetToScreen({ name: "home" });
        return;
      }
    }

    setGenerationError("Generation took too long. Please try again.");
  }

  async function createUserAndGenerate(event: FormEvent) {
    event.preventDefault();
    setErrorNotice("");
    setGlobalNotice("");
    setIsWorking(true);

    try {
      const createUserBody = {
        email: onboardingForm.email.trim(),
        password: onboardingForm.password,
        age: Number(onboardingForm.age),
        weight_kg: Number(onboardingForm.weight_kg),
        height_cm: Number(onboardingForm.height_cm),
        gender: onboardingForm.gender,
        activity_level: onboardingForm.activity_level,
        goal: onboardingForm.goal,
        allergies: splitList(onboardingForm.allergies),
        preferences: splitList(onboardingForm.preferences),
        disliked_ingredients: splitList(onboardingForm.disliked_ingredients),
        diseases: splitList(onboardingForm.diseases),
      };

      const createResponse = await fetch(`${API_BASE}/api/users`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(createUserBody),
      });

      if (!createResponse.ok) {
        throw new Error(await readError(createResponse));
      }

      const createdUser = (await createResponse.json()) as UserResponse;
      if (!aliveRef.current) {
        return;
      }

      setUser(createdUser);
      patchStoredSession({ userId: createdUser.id, planId: undefined, taskId: undefined });
      resetToScreen({ name: "generating" });

      const generateResponse = await fetch(`${API_BASE}/api/generate-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: createdUser.id, days: PLAN_DAYS }),
      });

      if (!generateResponse.ok) {
        throw new Error(await readError(generateResponse));
      }

      const generation = (await generateResponse.json()) as { task_id: string };
      patchStoredSession({ userId: createdUser.id, taskId: generation.task_id, planId: undefined });
      await monitorTask(generation.task_id, createdUser.id);
    } catch (error) {
      if (!aliveRef.current) {
        return;
      }
      setErrorNotice(error instanceof Error ? error.message : "Could not start onboarding.");
      resetToScreen({ name: "onboarding" });
    } finally {
      if (aliveRef.current) {
        setIsWorking(false);
      }
    }
  }

  async function regenerateWeek() {
    if (!user) {
      return;
    }

    setErrorNotice("");
    setGlobalNotice("");
    setGenerationStatus("PENDING");
    setGenerationError("");
    resetToScreen({ name: "generating" });

    try {
      const response = await fetch(`${API_BASE}/api/generate-plan`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ user_id: user.id, days: PLAN_DAYS }),
      });

      if (!response.ok) {
        throw new Error(await readError(response));
      }

      const generation = (await response.json()) as { task_id: string };
      patchStoredSession({ userId: user.id, taskId: generation.task_id, planId: undefined });
      await monitorTask(generation.task_id, user.id);
    } catch (error) {
      if (!aliveRef.current) {
        return;
      }
      setGenerationError(error instanceof Error ? error.message : "Could not refresh your week.");
    }
  }

  async function saveProfile() {
    if (!user) {
      return;
    }

    setIsSavingProfile(true);
    setErrorNotice("");
    setGlobalNotice("");

    try {
      const response = await fetch(`${API_BASE}/api/users/${user.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          age: Number(profileDraft.age),
          weight_kg: Number(profileDraft.weight_kg),
          height_cm: Number(profileDraft.height_cm),
          gender: profileDraft.gender,
          activity_level: profileDraft.activity_level,
          goal: profileDraft.goal,
          allergies: splitList(profileDraft.allergies),
          preferences: splitList(profileDraft.preferences),
          disliked_ingredients: splitList(profileDraft.disliked_ingredients),
          diseases: splitList(profileDraft.diseases),
        }),
      });

      if (!response.ok) {
        throw new Error(await readError(response));
      }

      const updatedUser = (await response.json()) as UserResponse;
      if (!aliveRef.current) {
        return;
      }

      setUser(updatedUser);
      setGlobalNotice("Preferences saved. Generate a fresh week to apply them.");
    } catch (error) {
      if (!aliveRef.current) {
        return;
      }
      setErrorNotice(error instanceof Error ? error.message : "Could not save profile.");
    } finally {
      if (aliveRef.current) {
        setIsSavingProfile(false);
      }
    }
  }

  async function copyShoppingItems() {
    if (!shoppingList?.length || !navigator.clipboard) {
      return;
    }

    const text = shoppingList
      .map((item) => `${item.name} — ${item.amount} ${item.unit}`)
      .join("\n");

    await navigator.clipboard.writeText(text);
    setShoppingCopied(true);
  }

  function openCalendarExport() {
    if (!planRecord?.id || typeof window === "undefined") {
      return;
    }

    const link = document.createElement("a");
    link.href = `${API_BASE}/api/plans/${planRecord.id}/calendar.ics`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.click();
  }

  function updateOnboarding<K extends keyof OnboardingForm>(key: K, value: OnboardingForm[K]) {
    setOnboardingForm((current) => ({ ...current, [key]: value }));
  }

  function updateProfileDraft<K extends keyof ProfileDraft>(key: K, value: ProfileDraft[K]) {
    setProfileDraft((current) => ({ ...current, [key]: value }));
  }

  function validateStep(step: number): string | null {
    if (step === 1) {
      if (!onboardingForm.email.trim() || !onboardingForm.password.trim()) {
        return "Add an email and password to create your plan.";
      }
      if (onboardingForm.password.trim().length < 6) {
        return "Password should be at least 6 characters.";
      }
    }

    if (step === 2) {
      if (!onboardingForm.age || !onboardingForm.weight_kg || !onboardingForm.height_cm) {
        return "Fill in your body metrics before continuing.";
      }
    }

    return null;
  }

  function goToNextStep() {
    const validationError = validateStep(onboardingStep);
    if (validationError) {
      setErrorNotice(validationError);
      return;
    }

    setErrorNotice("");
    setOnboardingStep((current) => clamp(current + 1, 1, ONBOARDING_STEPS));
  }

  function goToPreviousStep() {
    setErrorNotice("");
    setOnboardingStep((current) => clamp(current - 1, 1, ONBOARDING_STEPS));
  }

  function openRecipe(recipeId: string) {
    pushScreen({ name: "recipe", recipeId });
  }

  function getRecipeById(recipeId: string): RecipeDetail | null {
    return recipesMap[recipeId] ?? null;
  }

  function getMealByRecipeId(recipeId: string): MealItem | null {
    for (const day of planData?.days ?? []) {
      const found = day.meals.find((meal) => meal.recipe_id === recipeId);
      if (found) {
        return found;
      }
    }
    return null;
  }

  function renderBoot() {
    return (
      <section className="boot-screen screen-card">
        <div className="brand-lockup">
          <span className="brand-lockup__badge">
            <AppIcon className="icon icon--brand" />
          </span>
          <div>
            <div className="eyebrow">Warm mobile nutrition</div>
            <h1>Loading your companion</h1>
          </div>
        </div>
        <div className="boot-orbit" />
        <p className="soft-copy">
          Restoring your current plan, preferences, and today&apos;s quick actions.
        </p>
      </section>
    );
  }

  function renderOnboarding() {
    return (
      <section className="screen-card screen-card--onboarding">
        <div className="welcome-hero">
          <div className="brand-lockup">
            <span className="brand-lockup__badge">
              <AppIcon className="icon icon--brand" />
            </span>
            <div>
              <div className="eyebrow">Mobile plan setup</div>
              <h1>Build your week in four calm steps</h1>
            </div>
          </div>
          <p className="welcome-copy">
            A structured onboarding for goals, preferences, and restrictions. Then NutriAgent
            turns it into a full 7-day plan.
          </p>
          <div className="step-track" aria-label={`Step ${onboardingStep} of ${ONBOARDING_STEPS}`}>
            {Array.from({ length: ONBOARDING_STEPS }).map((_, index) => (
              <span
                key={index}
                className={`step-dot ${index + 1 <= onboardingStep ? "is-active" : ""}`}
              />
            ))}
          </div>
        </div>

        <form onSubmit={createUserAndGenerate} className="form-shell">
          {onboardingStep === 1 ? (
            <>
              <div className="section-copy">
                <span className="section-copy__eyebrow">Account</span>
                <h2>Start with the basics</h2>
                <p>We save your active plan locally so you return straight to Today.</p>
              </div>
              <label className="field">
                <span>Email</span>
                <input
                  type="email"
                  value={onboardingForm.email}
                  onChange={(event) => updateOnboarding("email", event.target.value)}
                  placeholder="you@example.com"
                />
              </label>
              <label className="field">
                <span>Password</span>
                <input
                  type="password"
                  value={onboardingForm.password}
                  onChange={(event) => updateOnboarding("password", event.target.value)}
                  placeholder="At least 6 characters"
                />
              </label>
            </>
          ) : null}

          {onboardingStep === 2 ? (
            <>
              <div className="section-copy">
                <span className="section-copy__eyebrow">Body metrics</span>
                <h2>Give the planner clean inputs</h2>
                <p>Calories are calculated automatically from your profile and activity.</p>
              </div>
              <div className="field-grid">
                <label className="field">
                  <span>Age</span>
                  <input
                    type="number"
                    min={10}
                    max={120}
                    value={onboardingForm.age}
                    onChange={(event) => updateOnboarding("age", event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Weight, kg</span>
                  <input
                    type="number"
                    min={20}
                    max={300}
                    step="0.1"
                    value={onboardingForm.weight_kg}
                    onChange={(event) => updateOnboarding("weight_kg", event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Height, cm</span>
                  <input
                    type="number"
                    min={80}
                    max={260}
                    step="0.1"
                    value={onboardingForm.height_cm}
                    onChange={(event) => updateOnboarding("height_cm", event.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Gender</span>
                  <select
                    value={onboardingForm.gender}
                    onChange={(event) => updateOnboarding("gender", event.target.value as Gender)}
                  >
                    <option value="female">Female</option>
                    <option value="male">Male</option>
                  </select>
                </label>
              </div>
            </>
          ) : null}

          {onboardingStep === 3 ? (
            <>
              <div className="section-copy">
                <span className="section-copy__eyebrow">Goal and rhythm</span>
                <h2>Shape the tone of the week</h2>
                <p>We use these preferences to bias the recipe catalog before generation.</p>
              </div>
              <label className="field">
                <span>Activity</span>
                <select
                  value={onboardingForm.activity_level}
                  onChange={(event) =>
                    updateOnboarding("activity_level", event.target.value as ActivityLevel)
                  }
                >
                  <option value="sedentary">Low activity</option>
                  <option value="light">Light activity</option>
                  <option value="moderate">Moderate activity</option>
                  <option value="active">High activity</option>
                  <option value="very_active">Very active</option>
                </select>
              </label>
              <label className="field">
                <span>Goal</span>
                <select
                  value={onboardingForm.goal}
                  onChange={(event) => updateOnboarding("goal", event.target.value as Goal)}
                >
                  <option value="lose">Fat loss</option>
                  <option value="maintain">Maintain</option>
                  <option value="gain">Gain muscle</option>
                </select>
              </label>
              <label className="field">
                <span>Preferences</span>
                <textarea
                  value={onboardingForm.preferences}
                  onChange={(event) => updateOnboarding("preferences", event.target.value)}
                  placeholder="Mediterranean, high protein, fish, simple dinners"
                />
              </label>
            </>
          ) : null}

          {onboardingStep === 4 ? (
            <>
              <div className="section-copy">
                <span className="section-copy__eyebrow">Restrictions and review</span>
                <h2>Lock your guardrails</h2>
                <p>These fields protect the generation step from unsafe or unwanted choices.</p>
              </div>
              <label className="field">
                <span>Allergies</span>
                <textarea
                  value={onboardingForm.allergies}
                  onChange={(event) => updateOnboarding("allergies", event.target.value)}
                  placeholder="nuts, milk, eggs"
                />
              </label>
              <label className="field">
                <span>Disliked ingredients</span>
                <textarea
                  value={onboardingForm.disliked_ingredients}
                  onChange={(event) =>
                    updateOnboarding("disliked_ingredients", event.target.value)
                  }
                  placeholder="broccoli, liver, onion"
                />
              </label>
              <label className="field">
                <span>Conditions</span>
                <textarea
                  value={onboardingForm.diseases}
                  onChange={(event) => updateOnboarding("diseases", event.target.value)}
                  placeholder="gastritis, diabetes, hypertension"
                />
              </label>
              <div className="review-card">
                <div>
                  <strong>{formatGoal(onboardingForm.goal)}</strong>
                  <span>{formatActivity(onboardingForm.activity_level)}</span>
                </div>
                <div>
                  <strong>
                    {onboardingForm.weight_kg} kg / {onboardingForm.height_cm} cm
                  </strong>
                  <span>{onboardingForm.gender === "female" ? "Female" : "Male"}</span>
                </div>
              </div>
            </>
          ) : null}

          <div className="sticky-actions">
            {onboardingStep > 1 ? (
              <button type="button" className="button button--ghost" onClick={goToPreviousStep}>
                Back
              </button>
            ) : (
              <button type="button" className="button button--ghost" onClick={clearAppState}>
                Reset
              </button>
            )}

            {onboardingStep < ONBOARDING_STEPS ? (
              <button type="button" className="button button--primary" onClick={goToNextStep}>
                Continue
              </button>
            ) : (
              <button type="submit" className="button button--primary" disabled={isWorking}>
                {isWorking ? "Starting..." : "Generate my week"}
              </button>
            )}
          </div>
        </form>
      </section>
    );
  }

  function renderGenerating() {
    const statusText =
      generationStatus === "READY"
        ? "Your week is almost on screen."
        : generationStatus === "FAILED"
          ? generationError || "Generation failed."
          : generationStatus === "GENERATING"
            ? "Matching recipes, balancing calories, building the final week."
            : "Creating your nutrition profile and queueing the plan.";

    const stages = [
      { label: "Profile parsed", active: generationStatus !== "PENDING" || !!user },
      { label: "Recipe pool matched", active: generationStatus === "GENERATING" || generationStatus === "READY" },
      { label: "Week balanced", active: generationStatus === "READY" },
    ];

    return (
      <section className="screen-card screen-card--generation">
        <div className="generation-orbit">
          <span className="generation-orbit__ring" />
          <span className="generation-orbit__ring generation-orbit__ring--accent" />
          <span className="generation-orbit__core">
            <SparkIcon className="icon icon--large" />
          </span>
        </div>
        <div className="section-copy section-copy--centered">
          <span className="section-copy__eyebrow">AI planning in progress</span>
          <h1>Designing your week</h1>
          <p>{statusText}</p>
        </div>

        <div className="progress-stack">
          {stages.map((stage) => (
            <div key={stage.label} className={`progress-step ${stage.active ? "is-active" : ""}`}>
              <span className="progress-step__icon">
                {stage.active ? <CheckIcon className="icon" /> : <span className="progress-step__dot" />}
              </span>
              <div>
                <strong>{stage.label}</strong>
                <p>{stage.active ? "Moving forward" : "Waiting for this stage"}</p>
              </div>
            </div>
          ))}
        </div>

        {generationError ? (
          <div className="alert alert--error">
            <strong>Couldn&apos;t finish this run.</strong>
            <p>{generationError}</p>
            <button type="button" className="button button--primary" onClick={regenerateWeek}>
              Try again
            </button>
          </div>
        ) : null}
      </section>
    );
  }

  function renderEmptyHome() {
    return (
      <section className="screen-card">
        <ScreenHeader
          title="Today"
          subtitle="This home screen becomes your daily nutrition hub once a plan is ready."
        />
        <div className="empty-state">
          <div className="empty-state__icon">
            <SparkIcon className="icon icon--large" />
          </div>
          <h3>No active week yet</h3>
          <p>Generate your first 7-day plan to unlock Today, Weekly Plan, recipes, and shopping.</p>
          <button type="button" className="button button--primary" onClick={user ? regenerateWeek : clearAppState}>
            {user ? "Generate my first week" : "Start onboarding"}
          </button>
        </div>
      </section>
    );
  }

  function renderQuickActions(actions: QuickAction[]) {
    return (
      <div className="quick-actions">
        {actions.map((action) => (
          <button key={action.label} type="button" className="action-card" onClick={action.onClick}>
            <span className="action-card__icon">{action.icon}</span>
            <div>
              <strong>{action.label}</strong>
              <p>{action.description}</p>
            </div>
            <ChevronRightIcon className="icon action-card__chevron" />
          </button>
        ))}
      </div>
    );
  }

  function renderMealCard(meal: MealItem, mode: "home" | "weekly") {
    return (
      <button
        key={`${meal.recipe_id}-${meal.type}`}
        type="button"
        className={`meal-card ${mode === "home" ? "meal-card--featured" : ""}`}
        onClick={() => openRecipe(meal.recipe_id)}
      >
        <div className={mealVisualClass(meal.type)}>
          <div className="meal-visual__content">
            <span className="pill pill--soft">{formatMealType(meal.type)}</span>
            <strong>{meal.title}</strong>
            <p>{meal.time || "Flexible time"} · {Math.round(meal.calories)} kcal</p>
          </div>
        </div>
        <div className="meal-card__body">
          <div>
            <h3>{meal.title}</h3>
            <p>{meal.time || "Planned meal"} · P {Math.round(meal.protein)} · C {Math.round(meal.carbs)}</p>
          </div>
          <span className="meal-card__cta">
            <ChevronRightIcon className="icon" />
          </span>
        </div>
      </button>
    );
  }

  function renderHome() {
    if (!planData || !todayPlan) {
      return renderEmptyHome();
    }

    const actions: QuickAction[] = [
      {
        label: "Weekly Plan",
        description: `Review all ${PLAN_DAYS} generated days and switch by date.`,
        icon: <CalendarIcon className="icon" />,
        onClick: () => pushScreen({ name: "weekly" }),
      },
      {
        label: "Shopping List",
        description: "See the aggregated grocery list for the full week.",
        icon: <CartIcon className="icon" />,
        onClick: () => pushScreen({ name: "shopping" }),
      },
      {
        label: "Profile",
        description: "Update goals, dislikes, allergies, and activity.",
        icon: <UserIcon className="icon" />,
        onClick: () => pushScreen({ name: "profile" }),
      },
      {
        label: "Refresh Week",
        description: "Run the planner again with your current constraints.",
        icon: <RefreshIcon className="icon" />,
        onClick: regenerateWeek,
      },
    ];

    return (
      <section className="screen-card screen-card--home">
        <div className="home-hero">
          <div className="home-hero__top">
            <div>
              <div className="eyebrow eyebrow--light">
                Today · {formatPlanDayLabel(planRecord, todayIndex)}
              </div>
              <h1>Keep the day calm and on target</h1>
            </div>
            <span className="hero-badge">{formatGoal(planData.user_profile?.goal || user?.goal)}</span>
          </div>
        <div className="home-hero__bottom">
            <div className="progress-cluster">
              <div className="progress-cluster__value">{todayProgress}%</div>
              <div>
                <strong>{Math.round(todayCalories)} / {Math.round(dailyTarget)} kcal</strong>
                <p>Today&apos;s planned calories</p>
              </div>
            </div>
            <div className="progress-bar">
              <span style={{ width: `${todayProgress}%` }} />
            </div>
            <div className="hero-stats">
              <div>
                <strong>{todayPlan.meals.length}</strong>
                <span>Meals</span>
              </div>
              <div>
                <strong>{Math.round(todayPlan.total_protein)}g</strong>
                <span>Protein</span>
              </div>
              <div>
                <strong>{Math.round(todayPlan.total_carbs)}g</strong>
                <span>Carbs</span>
              </div>
            </div>
            <button type="button" className="mini-link mini-link--light" onClick={openCalendarExport}>
              Добавить в календарь
            </button>
          </div>
        </div>

        <section className="section-block">
          <div className="section-heading">
            <div>
              <span className="section-heading__eyebrow">Today&apos;s meals</span>
              <h2>Open any meal to see the full recipe</h2>
            </div>
            <button type="button" className="mini-link" onClick={() => pushScreen({ name: "weekly" })}>
              Full week
            </button>
          </div>
          <div className="meal-stack">
            {todayPlan.meals.map((meal) => renderMealCard(meal, "home"))}
          </div>
        </section>

        <section className="section-block">
          <div className="section-heading">
            <div>
              <span className="section-heading__eyebrow">Quick actions</span>
              <h2>Jump into the rest of the app</h2>
            </div>
          </div>
          {renderQuickActions(actions)}
        </section>
      </section>
    );
  }

  function renderWeeklyPlan() {
    if (!planData) {
      return renderEmptyHome();
    }

    const activeDay =
      planData.days.find((day) => day.day_number === selectedDayNumber) ?? planData.days[0];

    return (
      <section className="screen-card">
        <ScreenHeader
          title="Weekly Plan"
          subtitle="A day-selector view grounded in the same plan payload as the Home screen."
          onBack={popScreen}
        />

        <div className="section-toolbar section-toolbar--tight">
          <div className="soft-copy">Export the whole week as an iCalendar file.</div>
          <button type="button" className="mini-link" onClick={openCalendarExport}>
            Добавить в календарь
          </button>
        </div>

        <div className="chip-row" role="tablist" aria-label="Plan days">
          {planData.days.map((day) => (
            <button
              key={day.day_number}
              type="button"
              className={`day-chip ${day.day_number === selectedDayNumber ? "is-active" : ""}`}
              onClick={() => setSelectedDayNumber(day.day_number)}
            >
              <span>Day {day.day_number}</span>
              <small>{formatPlanDayLabel(planRecord, day.day_number)}</small>
            </button>
          ))}
        </div>

        <div className="day-summary">
          <div>
            <strong>{Math.round(activeDay.total_calories)} kcal</strong>
            <span>Daily total</span>
          </div>
          <div>
            <strong>{Math.round(activeDay.total_protein)}g</strong>
            <span>Protein</span>
          </div>
          <div>
            <strong>{Math.round(activeDay.total_fat)}g</strong>
            <span>Fat</span>
          </div>
        </div>

        <div className="meal-stack meal-stack--compact">
          {activeDay.meals.map((meal) => renderMealCard(meal, "weekly"))}
        </div>
      </section>
    );
  }

  function renderRecipeDetail() {
    if (currentScreen.name !== "recipe") {
      return null;
    }

    const recipe = getRecipeById(currentScreen.recipeId);
    const meal = getMealByRecipeId(currentScreen.recipeId);

    if (!meal) {
      return (
        <section className="screen-card">
          <ScreenHeader title="Recipe" subtitle="Could not find this recipe in the current plan." onBack={popScreen} />
          <div className="empty-state">
            <h3>Recipe not available</h3>
            <p>Return to Today or Weekly Plan and pick another meal card.</p>
          </div>
        </section>
      );
    }

    const ingredients = recipe?.ingredients ?? meal.ingredients_summary ?? [];

    return (
      <section className="screen-card screen-card--detail">
        <ScreenHeader
          title={meal.title}
          subtitle="Recipe detail with macros, ingredients, and a quick jump into groceries."
          onBack={popScreen}
        />

        <div className={`${mealVisualClass(meal.type)} meal-visual--detail`}>
          <div className="meal-visual__content meal-visual__content--detail">
            <span className="pill pill--soft">{formatMealType(meal.type)}</span>
            <strong>{meal.title}</strong>
            <p>{meal.time || "Anytime meal"} · {recipe?.prep_time_min ? `${recipe.prep_time_min} min` : "Ready when you are"}</p>
          </div>
        </div>

        <div className="macro-grid">
          <div>
            <strong>{Math.round(meal.calories)}</strong>
            <span>kcal</span>
          </div>
          <div>
            <strong>{Math.round(meal.protein)}g</strong>
            <span>Protein</span>
          </div>
          <div>
            <strong>{Math.round(meal.fat)}g</strong>
            <span>Fat</span>
          </div>
          <div>
            <strong>{Math.round(meal.carbs)}g</strong>
            <span>Carbs</span>
          </div>
        </div>

        <section className="detail-block">
          <div className="section-heading">
            <div>
              <span className="section-heading__eyebrow">Description</span>
              <h2>What this meal does</h2>
            </div>
          </div>
          <p className="soft-copy">
            {recipe?.description ||
              "A guided meal from your current plan. Exact ingredients come from the verified recipe catalog used during generation."}
          </p>
          {recipe?.tags?.length ? (
            <div className="tag-row">
              {recipe.tags.slice(0, 4).map((tag) => (
                <span key={tag} className="pill pill--outline">
                  {tag}
                </span>
              ))}
            </div>
          ) : null}
        </section>

        <section className="detail-block">
          <div className="section-heading">
            <div>
              <span className="section-heading__eyebrow">Ingredients</span>
              <h2>What to prepare</h2>
            </div>
          </div>
          <div className="ingredient-list">
            {ingredients.map((ingredient) => (
              <div key={`${ingredient.name}-${ingredient.amount}-${ingredient.unit}`} className="ingredient-row">
                <div>
                  <strong>{ingredient.name}</strong>
                  <span>{ingredient.unit}</span>
                </div>
                <span>{ingredient.amount} {ingredient.unit}</span>
              </div>
            ))}
          </div>
        </section>

        <div className="sticky-footer">
          <div className="sticky-footer__summary">
            <strong>{Math.round(meal.calories)} kcal</strong>
            <span>{formatMealType(meal.type)}</span>
          </div>
          <button type="button" className="button button--primary" onClick={() => pushScreen({ name: "shopping" })}>
            Open shopping list
          </button>
        </div>
      </section>
    );
  }

  function renderShopping() {
    return (
      <section className="screen-card">
        <ScreenHeader
          title="Shopping List"
          subtitle="Aggregated ingredients for the current 7-day plan."
          onBack={popScreen}
        />

        <div className="section-toolbar">
          <div className="soft-copy">
            {shoppingList?.length ? `${shoppingList.length} items grouped for the week` : "Loading items..."}
          </div>
          <button
            type="button"
            className="button button--ghost button--small"
            onClick={copyShoppingItems}
            disabled={!shoppingList?.length}
          >
            {shoppingCopied ? "Copied" : "Copy"}
          </button>
        </div>

        {shoppingLoading ? (
          <div className="loading-card">
            <TimeIcon className="icon icon--brand" />
            <span>Building your grocery list…</span>
          </div>
        ) : null}

        {!shoppingLoading && shoppingList?.length ? (
          <div className="shopping-list">
            {shoppingList.map((item) => (
              <div key={`${item.name}-${item.unit}`} className="shopping-row">
                <div>
                  <strong>{item.name}</strong>
                  <span>{item.unit}</span>
                </div>
                <span>{item.amount} {item.unit}</span>
              </div>
            ))}
          </div>
        ) : null}

        {!shoppingLoading && !shoppingList?.length ? (
          <div className="empty-state empty-state--compact">
            <h3>No shopping items yet</h3>
            <p>Generate a plan or reopen the screen after the current week is ready.</p>
          </div>
        ) : null}
      </section>
    );
  }

  function renderProfile() {
    return (
      <section className="screen-card">
        <ScreenHeader
          title="Profile"
          subtitle="Edit the nutrition inputs that shape your next generated week."
          onBack={popScreen}
        />

        <div className="profile-summary">
          <div>
            <span className="profile-summary__label">Email</span>
            <strong>{user?.email ?? "No email loaded"}</strong>
          </div>
          <div>
            <span className="profile-summary__label">Current target</span>
            <strong>{user?.target_calories ? `${user.target_calories} kcal` : "Pending"}</strong>
          </div>
        </div>

        <div className="profile-blocks">
          <section className="profile-block">
            <h3>Body</h3>
            <div className="field-grid">
              <label className="field">
                <span>Age</span>
                <input
                  type="number"
                  value={profileDraft.age}
                  onChange={(event) => updateProfileDraft("age", event.target.value)}
                />
              </label>
              <label className="field">
                <span>Weight, kg</span>
                <input
                  type="number"
                  value={profileDraft.weight_kg}
                  onChange={(event) => updateProfileDraft("weight_kg", event.target.value)}
                />
              </label>
              <label className="field">
                <span>Height, cm</span>
                <input
                  type="number"
                  value={profileDraft.height_cm}
                  onChange={(event) => updateProfileDraft("height_cm", event.target.value)}
                />
              </label>
              <label className="field">
                <span>Gender</span>
                <select
                  value={profileDraft.gender}
                  onChange={(event) => updateProfileDraft("gender", event.target.value as Gender)}
                >
                  <option value="female">Female</option>
                  <option value="male">Male</option>
                </select>
              </label>
            </div>
          </section>

          <section className="profile-block">
            <h3>Goal and activity</h3>
            <label className="field">
              <span>Activity</span>
              <select
                value={profileDraft.activity_level}
                onChange={(event) =>
                  updateProfileDraft("activity_level", event.target.value as ActivityLevel)
                }
              >
                <option value="sedentary">Low activity</option>
                <option value="light">Light activity</option>
                <option value="moderate">Moderate activity</option>
                <option value="active">High activity</option>
                <option value="very_active">Very active</option>
              </select>
            </label>
            <label className="field">
              <span>Goal</span>
              <select
                value={profileDraft.goal}
                onChange={(event) => updateProfileDraft("goal", event.target.value as Goal)}
              >
                <option value="lose">Fat loss</option>
                <option value="maintain">Maintain</option>
                <option value="gain">Gain muscle</option>
              </select>
            </label>
            <label className="field">
              <span>Preferences</span>
              <textarea
                value={profileDraft.preferences}
                onChange={(event) => updateProfileDraft("preferences", event.target.value)}
              />
            </label>
          </section>

          <section className="profile-block">
            <h3>Restrictions</h3>
            <label className="field">
              <span>Allergies</span>
              <textarea
                value={profileDraft.allergies}
                onChange={(event) => updateProfileDraft("allergies", event.target.value)}
              />
            </label>
            <label className="field">
              <span>Disliked ingredients</span>
              <textarea
                value={profileDraft.disliked_ingredients}
                onChange={(event) => updateProfileDraft("disliked_ingredients", event.target.value)}
              />
            </label>
            <label className="field">
              <span>Conditions</span>
              <textarea
                value={profileDraft.diseases}
                onChange={(event) => updateProfileDraft("diseases", event.target.value)}
              />
            </label>
          </section>
        </div>

        <div className="sticky-actions">
          <button type="button" className="button button--ghost" onClick={popScreen}>
            Back
          </button>
          <button type="button" className="button button--primary" onClick={saveProfile} disabled={isSavingProfile}>
            {isSavingProfile ? "Saving..." : "Save profile"}
          </button>
        </div>

        <button type="button" className="secondary-cta" onClick={regenerateWeek}>
          Generate fresh week with these settings
        </button>
      </section>
    );
  }

  function renderCurrentScreen() {
    if (isBooting) {
      return renderBoot();
    }

    switch (currentScreen.name) {
      case "generating":
        return renderGenerating();
      case "home":
        return renderHome();
      case "weekly":
        return renderWeeklyPlan();
      case "shopping":
        return renderShopping();
      case "profile":
        return renderProfile();
      case "recipe":
        return renderRecipeDetail();
      case "onboarding":
      default:
        return renderOnboarding();
    }
  }

  return (
    <main className="app-shell">
      <div className="phone-shell">
        <div className="phone-shell__glow phone-shell__glow--top" />
        <div className="phone-shell__glow phone-shell__glow--bottom" />

        {(globalNotice || errorNotice) && (
          <div className={`floating-notice ${errorNotice ? "is-error" : ""}`}>
            <strong>{errorNotice ? "Attention" : "Updated"}</strong>
            <span>{errorNotice || globalNotice}</span>
          </div>
        )}

        {renderCurrentScreen()}
      </div>
    </main>
  );
}
