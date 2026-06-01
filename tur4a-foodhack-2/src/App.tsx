import React, { useState, useEffect } from "react";
import { Sparkles, Heart, LogIn, LogOut, User as UserIcon, Loader2 } from "lucide-react";
import DatePicker from "./components/DatePicker";
import SummaryBox from "./components/SummaryBox";
import AddFoodForm from "./components/AddFoodForm";
import MealSection from "./components/MealSection";
import AiScanner from "./components/AiScanner";
import GoalSettings from "./components/GoalSettings";
import ProgressAnalysis from "./components/ProgressAnalysis";
import { DiaryData, DayData, MealType, FoodItem, FoodTemplate, UserGoals } from "./types";
import { useLanguage } from "./LanguageContext";

// Firebase SDK integrations
import {
  auth,
  db,
  googleProvider,
  handleFirestoreError,
  OperationType,
} from "./firebase";
import {
  signInWithPopup,
  signOut,
  onAuthStateChanged,
  User,
} from "firebase/auth";
import {
  doc,
  collection,
  setDoc,
  deleteDoc,
  onSnapshot,
  serverTimestamp,
  writeBatch,
} from "firebase/firestore";

const defaultTemplates: FoodTemplate[] = [
  { id: "tmpl-1", name: "Творог 5%", kcal: 121, protein: 17, fat: 5, carb: 3, usageCount: 6 },
  { id: "tmpl-2", name: "Куриное филе (сырое)", kcal: 110, protein: 23, fat: 1.5, carb: 0, usageCount: 5 },
  { id: "tmpl-3", name: "Яйцо куриное (1 шт ≈ 55г)", kcal: 157, protein: 13, fat: 11, carb: 0.7, usageCount: 4 },
  { id: "tmpl-4", name: "Овсяные хлопья", kcal: 352, protein: 12, fat: 6, carb: 62, usageCount: 3 },
  { id: "tmpl-5", name: "Банан", kcal: 95, protein: 1.5, fat: 0.2, carb: 21.8, usageCount: 2 },
  { id: "tmpl-6", name: "Гречка отварная", kcal: 110, protein: 4, fat: 1, carb: 21, usageCount: 1 },
];

// Helper to parse numbers safely and eliminate any potential NaN values (arising from js typeof NaN === "number")
const parseSafeNum = (val: any, fallback = 0): number => {
  const num = typeof val === "number" ? val : parseFloat(val);
  return Number.isFinite(num) ? num : fallback;
};

const sanitizeFoodTemplate = (tmpl: any, index: number): FoodTemplate => {
  const rawId = typeof tmpl?.id === "string" ? tmpl.id : `tmpl-gen-${Date.now()}-${index}`;
  const safeId = rawId.replace(/[^a-zA-Z0-9_\-]/g, '') || `id-gen-${index}`;
  
  const name = typeof tmpl?.name === "string" ? tmpl.name.slice(0, 140) : `Продукт ${index + 1}`;
  
  const kcal = parseSafeNum(tmpl?.kcal, 0);
  const protein = parseSafeNum(tmpl?.protein, 0);
  const fat = parseSafeNum(tmpl?.fat, 0);
  const carb = parseSafeNum(tmpl?.carb, 0);
  const usageCount = parseSafeNum(tmpl?.usageCount, 1);

  return {
    id: safeId,
    name: name.trim() || `Продукт ${index + 1}`,
    kcal: Math.max(0, Math.min(10000, kcal)),
    protein: Math.max(0, Math.min(1000, protein)),
    fat: Math.max(0, Math.min(1000, fat)),
    carb: Math.max(0, Math.min(1000, carb)),
    usageCount: Math.max(0, usageCount),
  };
};

// Helper function to enrich items loaded from storage with safe types and stable IDs
const enrichDayData = (data: any): DayData => {
  const meals: MealType[] = ["breakfast", "lunch", "dinner", "snack"];
  const enriched: Partial<DayData> = {};

  meals.forEach((meal) => {
    const rawList = Array.isArray(data?.[meal]) ? data[meal] : [];
    enriched[meal] = rawList.map((item: any, idIndex: number) => ({
      id: item.id || `${meal}-${idIndex}-${Date.now()}-${Math.random()}`,
      name: item.name || "",
      kcal: typeof item.kcal === "number" ? item.kcal : parseFloat(item.kcal) || 0,
      protein: typeof item.protein === "number" ? item.protein : parseFloat(item.protein) || 0,
      fat: typeof item.fat === "number" ? item.fat : parseFloat(item.fat) || 0,
      carb: typeof item.carb === "number" ? item.carb : parseFloat(item.carb) || 0,
      weight: typeof item.weight === "number" ? item.weight : parseFloat(item.weight) || 100,
    }));
  });

  return enriched as DayData;
};

export default function App() {
  const { language, setLanguage, t } = useLanguage();

  // Initialize date to today's date formatted to YYYY-MM-DD
  const [selectedDate, setSelectedDate] = useState<string>(() => {
    return new Date().toISOString().split("T")[0];
  });

  // Customizable calorie goals
  const [goals, setGoals] = useState<UserGoals>(() => {
    try {
      const stored = localStorage.getItem("userGoals");
      if (stored) {
        const parsed = JSON.parse(stored);
        if (typeof parsed.kcal === "number") return parsed;
      }
    } catch {}
    return { kcal: 2000, protein: 120, fat: 70, carb: 250 };
  });

  // Real-time sequential log entries for Progress tracking
  const [historyData, setHistoryData] = useState<DiaryData>({});

  const handleSaveGoals = async (newGoals: UserGoals) => {
    setGoals(newGoals);
    try {
      localStorage.setItem("userGoals", JSON.stringify(newGoals));
    } catch {}
    if (!user) return;
    try {
      const goalsDocRef = doc(db, "users", user.uid, "settings", "goals");
      await setDoc(goalsDocRef, {
        ...newGoals,
        updatedAt: serverTimestamp()
      });
    } catch (e) {
      console.error("Error saving goals to Cloud:", e);
    }
  };

  const [activeMobileTab, setActiveMobileTab] = useState<"menu" | "form" | "summary">("menu");
  const [copyFeedback, setCopyFeedback] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Dark Mode State
  const [darkMode, setDarkMode] = useState<boolean>(() => {
    try {
      const stored = localStorage.getItem("darkMode");
      if (stored) return stored === "true";
    } catch {}
    return false;
  });

  useEffect(() => {
    try {
      localStorage.setItem("darkMode", String(darkMode));
    } catch {}
    if (darkMode) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [darkMode]);

  // Firebase Authentication & Loading state
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState<boolean>(true);
  const [dayLoading, setDayLoading] = useState<boolean>(false);

  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (currentUser) => {
      setUser(currentUser);
      setAuthLoading(false);
    });
    return () => unsubscribe();
  }, []);

  // Sync customizable goals from Cloud Firestore
  useEffect(() => {
    if (!user) return;
    try {
      const goalsDocRef = doc(db, "users", user.uid, "settings", "goals");
      const unsubscribe = onSnapshot(goalsDocRef, (snap) => {
        if (snap.exists()) {
          const data = snap.data();
          setGoals({
            kcal: parseSafeNum(data.kcal, 2000),
            protein: parseSafeNum(data.protein, 120),
            fat: parseSafeNum(data.fat, 70),
            carb: parseSafeNum(data.carb, 250),
          });
        }
      });
      return () => unsubscribe();
    } catch (e) {
      console.error("Error syncing goals from cloud:", e);
    }
  }, [user]);

  // Sync complete sequential historical day logs for Progress Charting
  useEffect(() => {
    if (!user) {
      try {
        const stored = localStorage.getItem("dietDiaryData");
        if (stored) {
          const parsed = JSON.parse(stored);
          setHistoryData(parsed);
          // Also sync today's view
          if (parsed[selectedDate]) {
            setDiaryData(prev => ({ ...prev, [selectedDate]: parsed[selectedDate] }));
          }
        }
      } catch {}
      return;
    }

    try {
      const daysCol = collection(db, "users", user.uid, "days");
      const unsubscribe = onSnapshot(daysCol, (snapshot) => {
        const hist: DiaryData = {};
        snapshot.forEach((docSnap) => {
          hist[docSnap.id] = enrichDayData(docSnap.data());
        });
        setHistoryData(hist);
        
        const targetDay = hist[selectedDate];
        if (targetDay) {
          setDiaryData((prev) => ({
            ...prev,
            [selectedDate]: targetDay,
          }));
        }
      });
      return () => unsubscribe();
    } catch (e) {
      console.error("Error syncing history logs from cloud:", e);
    }
  }, [user, selectedDate]);

  const handleGoogleLogin = async () => {
    try {
      setAuthLoading(true);
      await signInWithPopup(auth, googleProvider);
    } catch (e) {
      console.error("Auth Error (Google Sign in aborted or failed):", e);
    } finally {
      setAuthLoading(false);
    }
  };

  const handleSignOut = async () => {
    try {
      await signOut(auth);
      setDiaryData({});
      // Reset templates state back to localStorage (or default templates)
      try {
        const stored = localStorage.getItem("foodTemplates");
        if (stored) {
          setTemplates(JSON.parse(stored));
        } else {
          setTemplates(defaultTemplates);
        }
      } catch (e) {
        setTemplates(defaultTemplates);
      }
    } catch (e) {
      console.error("SignOut Error:", e);
    }
  };

  // Load food templates state in App
  const [templates, setTemplates] = useState<FoodTemplate[]>(() => {
    try {
      const stored = localStorage.getItem("foodTemplates");
      if (stored) {
        return JSON.parse(stored);
      }
    } catch (e) {
      console.error("Error loading templates", e);
    }
    return defaultTemplates;
  });

  // Main client diary entries dictionary (synchronized with Firestore)
  const [diaryData, setDiaryData] = useState<DiaryData>({});

  // Real-time listener for user templates
  useEffect(() => {
    if (!user) return;

    try {
      const templatesCol = collection(db, "users", user.uid, "templates");
      const unsubscribe = onSnapshot(templatesCol, (snapshot) => {
        const items: FoodTemplate[] = [];
        snapshot.forEach((docSnap) => {
          items.push(docSnap.data() as FoodTemplate);
        });

        if (items.length > 0) {
          items.sort((a, b) => (b.usageCount || 0) - (a.usageCount || 0));
          setTemplates(items);
        } else {
          // Templates collection empty in Firestore? Bootstrap with local templates or defaults securely using writeBatch
          let templatesToBootstrap = defaultTemplates;
          try {
            const stored = localStorage.getItem("foodTemplates");
            if (stored) {
              const parsed = JSON.parse(stored);
              if (Array.isArray(parsed) && parsed.length > 0) {
                templatesToBootstrap = parsed;
              }
            }
          } catch (err) {
            console.error("Failed to read foodTemplates from storage for bootstrap:", err);
          }

          const batch = writeBatch(db);
          templatesToBootstrap.forEach((tmpl, idx) => {
            const sanitized = sanitizeFoodTemplate(tmpl, idx);
            const tmplDocRef = doc(db, "users", user.uid, "templates", sanitized.id);
            batch.set(tmplDocRef, sanitized);
          });

          batch.commit().catch((err) => {
            console.error("Error executing atomic template bootstrap batch:", err);
          });
        }
      }, (error) => {
        handleFirestoreError(error, OperationType.GET, `users/${user.uid}/templates`);
      });

      return () => unsubscribe();
    } catch (e) {
      console.error("Error setting up template listener:", e);
    }
  }, [user]);

  // Real-time listener for current date log document
  useEffect(() => {
    if (!user) return;

    setDayLoading(true);
    try {
      const dayDocRef = doc(db, "users", user.uid, "days", selectedDate);
      const unsubscribe = onSnapshot(dayDocRef, (snap) => {
        setDayLoading(false);
        if (snap.exists()) {
          const enriched = enrichDayData(snap.data());
          setDiaryData((prev) => ({
            ...prev,
            [selectedDate]: enriched,
          }));
        } else {
          setDiaryData((prev) => ({
            ...prev,
            [selectedDate]: {
              breakfast: [],
              lunch: [],
              dinner: [],
              snack: [],
            },
          }));
        }
      }, (error) => {
        setDayLoading(false);
        handleFirestoreError(error, OperationType.GET, `users/${user.uid}/days/${selectedDate}`);
      });

      return () => unsubscribe();
    } catch (e) {
      setDayLoading(false);
      console.error("Error setting up day listener:", e);
    }
  }, [user, selectedDate]);

  // Handle saving and deleting life-time templates
  const handleSaveTemplate = async (template: FoodTemplate) => {
    // Sanitize template to guarantee security rules compliance
    const sanitized = sanitizeFoodTemplate(template, 0);

    if (!user) {
      setTemplates((prev) => {
        const filtered = prev.filter((t) => t.name.toLowerCase() !== sanitized.name.toLowerCase());
        const arr = [sanitized, ...filtered].sort((a, b) => b.usageCount - a.usageCount);
        localStorage.setItem("foodTemplates", JSON.stringify(arr));
        return arr;
      });
      return;
    }

    try {
      const tmplDocRef = doc(db, "users", user.uid, "templates", sanitized.id);
      await setDoc(tmplDocRef, {
        ...sanitized,
        updatedAt: serverTimestamp()
      });
    } catch (error) {
      handleFirestoreError(error, OperationType.WRITE, `users/${user.uid}/templates/${sanitized.id}`);
    }
  };

  const handleDeleteTemplate = async (id: string) => {
    if (!user) {
      setTemplates((prev) => {
        const arr = prev.filter((t) => t.id !== id);
        localStorage.setItem("foodTemplates", JSON.stringify(arr));
        return arr;
      });
      return;
    }

    try {
      const tmplDocRef = doc(db, "users", user.uid, "templates", id);
      await deleteDoc(tmplDocRef);
    } catch (error) {
      handleFirestoreError(error, OperationType.DELETE, `users/${user.uid}/templates/${id}`);
    }
  };

  // Backward compatibility layer: expose window.deleteFood for legacy integrations
  useEffect(() => {
    (window as any).deleteFood = (mealType: string, index: number) => {
      if (["breakfast", "lunch", "dinner", "snack"].includes(mealType)) {
        handleDeleteFood(mealType as MealType, index);
      }
    };
    return () => {
      delete (window as any).deleteFood;
    };
  }, [selectedDate, diaryData, user]);

  // Copy yesterday's menu logic
  const handleCopyYesterday = async () => {
    try {
      const currentDate = new Date(selectedDate);
      if (isNaN(currentDate.getTime())) {
        setCopyFeedback({ type: "error", text: "Установите корректную дату" });
        return;
      }

      const yesterday = new Date(currentDate);
      yesterday.setDate(yesterday.getDate() - 1);
      const yesterdayStr = yesterday.toISOString().split("T")[0];

      const yesterdayData = diaryData[yesterdayStr];
      const hasYesterdayMeals = yesterdayData && (
        (yesterdayData.breakfast?.length || 0) > 0 ||
        (yesterdayData.lunch?.length || 0) > 0 ||
        (yesterdayData.dinner?.length || 0) > 0 ||
        (yesterdayData.snack?.length || 0) > 0
      );

      if (!hasYesterdayMeals) {
        setCopyFeedback({
          type: "error",
          text: `Вчера (${yesterdayStr}) не было внесено никаких блюд! Сначала заполните предыдущий день.`,
        });
        setTimeout(() => setCopyFeedback(null), 5000);
        return;
      }

      // Proportional deep copy representing today's inputs
      const copiedBreakfast = (yesterdayData.breakfast || []).map(item => ({
        ...item,
        id: `breakfast-${Date.now()}-${Math.random()}`
      }));
      const copiedLunch = (yesterdayData.lunch || []).map(item => ({
        ...item,
        id: `lunch-${Date.now()}-${Math.random()}`
      }));
      const copiedDinner = (yesterdayData.dinner || []).map(item => ({
        ...item,
        id: `dinner-${Date.now()}-${Math.random()}`
      }));
      const copiedSnack = (yesterdayData.snack || []).map(item => ({
        ...item,
        id: `snack-${Date.now()}-${Math.random()}`
      }));

      if (!user) {
        setDiaryData(prev => {
          const res = {
            ...prev,
            [selectedDate]: {
              breakfast: copiedBreakfast,
              lunch: copiedLunch,
              dinner: copiedDinner,
              snack: copiedSnack
            }
          };
          localStorage.setItem("dietDiaryData", JSON.stringify(res));
          return res;
        });
      } else {
        const dayDocRef = doc(db, "users", user.uid, "days", selectedDate);
        await setDoc(dayDocRef, {
          breakfast: copiedBreakfast,
          lunch: copiedLunch,
          dinner: copiedDinner,
          snack: copiedSnack,
          updatedAt: serverTimestamp()
        });
      }

      setCopyFeedback({
        type: "success",
        text: "Меню вчерашнего дня успешно скопировано в выбранную дату!",
      });
      setTimeout(() => setCopyFeedback(null), 4000);
    } catch (e) {
      console.error("Error copy yesterday", e);
      setCopyFeedback({ type: "error", text: "Ошибка при копировании вчерашнего дня" });
      setTimeout(() => setCopyFeedback(null), 4000);
    }
  };

  // Get current day's food arrays, default to empty arrays
  const currentDayData: DayData = diaryData[selectedDate] || {
    breakfast: [],
    lunch: [],
    dinner: [],
    snack: [],
  };

  // Add item handler with portion weight
  const handleAddFood = async (
    mealType: MealType,
    name: string,
    kcal: number,
    protein: number,
    fat: number,
    carb: number,
    weight: number,
    unit?: string,
    portionSize?: number
  ) => {
    const newItem: FoodItem = {
      id: `${mealType}-${Date.now()}-${Math.random()}`,
      name,
      kcal,
      protein,
      fat,
      carb,
      weight,
      unit,
      portionSize,
    };

    if (!user) {
      setDiaryData((prev) => {
        const day = prev[selectedDate] || { breakfast: [], lunch: [], dinner: [], snack: [] };
        const updatedMeal = [...(day[mealType] || []), newItem];
        const res = {
          ...prev,
          [selectedDate]: { ...day, [mealType]: updatedMeal },
        };
        localStorage.setItem("dietDiaryData", JSON.stringify(res));
        return res;
      });
      return;
    }

    try {
      const dayDocRef = doc(db, "users", user.uid, "days", selectedDate);
      const currentDay = diaryData[selectedDate] || { breakfast: [], lunch: [], dinner: [], snack: [] };
      const updatedDay = {
        ...currentDay,
        [mealType]: [...(currentDay[mealType] || []), newItem],
        updatedAt: serverTimestamp(),
      };
      await setDoc(dayDocRef, {
        breakfast: updatedDay.breakfast || [],
        lunch: updatedDay.lunch || [],
        dinner: updatedDay.dinner || [],
        snack: updatedDay.snack || [],
        updatedAt: serverTimestamp(),
      });
    } catch (error) {
      handleFirestoreError(error, OperationType.WRITE, `users/${user.uid}/days/${selectedDate}`);
    }
  };

  // Delete item handler
  const handleDeleteFood = async (mealType: MealType, index: number) => {
    if (!user) {
      setDiaryData((prev) => {
        const day = prev[selectedDate];
        if (!day || !day[mealType]) return prev;

        const updatedMeal = [...day[mealType]];
        updatedMeal.splice(index, 1);

        const res = {
          ...prev,
          [selectedDate]: { ...day, [mealType]: updatedMeal },
        };
        localStorage.setItem("dietDiaryData", JSON.stringify(res));
        return res;
      });
      return;
    }

    try {
      const dayDocRef = doc(db, "users", user.uid, "days", selectedDate);
      const currentDay = diaryData[selectedDate];
      if (!currentDay || !currentDay[mealType]) return;

      const updatedMeal = [...currentDay[mealType]];
      updatedMeal.splice(index, 1);

      await setDoc(dayDocRef, {
        ...currentDay,
        [mealType]: updatedMeal,
        updatedAt: serverTimestamp(),
      });
    } catch (error) {
      handleFirestoreError(error, OperationType.DELETE, `users/${user.uid}/days/${selectedDate}`);
    }
  };

  // Calculate totals for summary readout
  const computeTotals = () => {
    let kcal = 0;
    let protein = 0;
    let fat = 0;
    let carb = 0;

    const meals: MealType[] = ["breakfast", "lunch", "dinner", "snack"];
    meals.forEach((meal) => {
      const list = currentDayData[meal] || [];
      list.forEach((item) => {
        kcal += item.kcal;
        protein += item.protein;
        fat += item.fat;
        carb += item.carb;
      });
    });

    return {
      kcal: Math.round(kcal),
      protein: Math.round(protein),
      fat: Math.round(fat),
      carb: Math.round(carb),
    };
  };

  const totals = computeTotals();

  if (authLoading) {
    return (
      <div className={`min-h-screen w-full bg-emerald-50/60 dark:bg-slate-950 font-sans flex items-center justify-center relative overflow-hidden transition-colors duration-300 ${darkMode ? "dark" : ""}`}>
        <div className="absolute -top-24 -left-24 w-96 h-96 bg-emerald-200/50 dark:bg-emerald-900/10 rounded-full mix-blend-multiply filter blur-3xl opacity-70 pointer-events-none"></div>
        <div className="absolute top-1/3 -right-24 w-96 h-96 bg-blue-200/50 dark:bg-sky-900/10 rounded-full mix-blend-multiply filter blur-3xl opacity-70 pointer-events-none"></div>
        
        <div className="bg-white/40 dark:bg-slate-900/40 backdrop-blur-xl border border-white/40 dark:border-slate-800/40 p-8 rounded-3xl shadow-xl flex flex-col items-center gap-4 max-w-sm w-full text-center">
          <Loader2 className="w-8 h-8 text-emerald-505 animate-spin" />
          <p className="text-sm font-bold text-slate-705 dark:text-slate-300 font-display">{t("loading_secure_cloud")}</p>
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <div className={`min-h-screen w-full bg-emerald-50/60 dark:bg-slate-950 font-sans text-slate-800 dark:text-slate-200 relative overflow-x-hidden flex flex-col items-center justify-center p-4 selection:bg-emerald-200 dark:selection:bg-emerald-900 transition-colors duration-300 ${darkMode ? "dark" : ""}`}>
        {/* Background Mesh Gradients */}
        <div className="absolute -top-24 -left-24 w-96 h-96 bg-emerald-200/50 dark:bg-emerald-900/10 rounded-full mix-blend-multiply filter blur-3xl opacity-70 pointer-events-none"></div>
        <div className="absolute top-1/3 -right-24 w-96 h-96 bg-blue-200/50 dark:bg-sky-900/10 rounded-full mix-blend-multiply filter blur-3xl opacity-70 pointer-events-none"></div>
        
        {/* Theme switcher & Lang selector on login page */}
        <div className="absolute top-6 right-6 flex items-center gap-2">
          {/* Language Switcher */}
          <div className="flex bg-white/80 dark:bg-slate-805/80 p-0.5 rounded-xl border border-slate-200 dark:border-slate-700 shadow-xs">
            <button
              onClick={() => setLanguage("ru")}
              className={`px-2.5 py-1 text-[10px] font-black rounded-lg transition-all cursor-pointer ${
                language === "ru"
                  ? "bg-emerald-500 text-white shadow-xs"
                  : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              RU
            </button>
            <button
              onClick={() => setLanguage("en")}
              className={`px-2.5 py-1 text-[10px] font-black rounded-lg transition-all cursor-pointer ${
                language === "en"
                  ? "bg-emerald-500 text-white shadow-xs"
                  : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              EN
            </button>
          </div>

          <button
            onClick={() => setDarkMode(prev => !prev)}
            className="p-2 w-10 h-10 rounded-xl flex items-center justify-center transition-all bg-white/80 dark:bg-slate-805 hover:bg-slate-100 dark:hover:bg-slate-700/80 text-slate-700 dark:text-yellow-400 border border-slate-200 dark:border-slate-700 cursor-pointer shadow-xs active:scale-95"
            title={darkMode ? t("theme_light_tooltip") : t("theme_dark_tooltip")}
          >
            {darkMode ? (
              <svg className="w-5 h-5 text-yellow-500 fill-yellow-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364l-.707.707M6.343 17.657l-.707.707m0-11.314l.707.707m11.314 11.314l.707.707M12 5a7 7 0 100 14 7 7 0 000-14z" />
              </svg>
            ) : (
              <svg className="w-5 h-5 text-slate-600 fill-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            )}
          </button>
        </div>

        <main className="relative z-10 w-full max-w-md bg-white/50 dark:bg-slate-900/55 backdrop-blur-xl border border-white/50 dark:border-slate-800/50 p-8 sm:p-10 rounded-[32px] shadow-2xl flex flex-col items-center">
          <div className="w-16 h-16 bg-emerald-500 rounded-2xl flex items-center justify-center shadow-lg shadow-emerald-500/30 mb-6">
            <svg className="w-9 h-9 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2.2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"></path>
            </svg>
          </div>

          <h1 className="text-2xl sm:text-3xl font-extrabold tracking-tight text-emerald-950 dark:text-emerald-400 font-display text-center mb-2">
            {t("app_title")}
          </h1>
          <p className="text-xs sm:text-sm text-slate-500 dark:text-slate-400 font-semibold uppercase tracking-wider block text-center mb-8">
            {t("auth_profile_title")}
          </p>

          <div className="w-full space-y-4 mb-8">
            <div className="flex items-start gap-3 p-3 bg-white/30 dark:bg-slate-800/10 rounded-2xl">
              <span className="text-lg">🛡️</span>
              <div>
                <h4 className="text-xs font-black text-slate-800 dark:text-slate-200 uppercase">{t("auth_feat1_title")}</h4>
                <p className="text-[11px] text-slate-505 dark:text-slate-400 mt-0.5">{t("auth_feat1_desc")}</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 bg-white/30 dark:bg-slate-800/10 rounded-2xl">
              <span className="text-lg">🤖</span>
              <div>
                <h4 className="text-xs font-black text-slate-800 dark:text-slate-200 uppercase">{t("auth_feat2_title")}</h4>
                <p className="text-[11px] text-slate-505 dark:text-slate-400 mt-0.5">{t("auth_feat2_desc")}</p>
              </div>
            </div>
            <div className="flex items-start gap-3 p-3 bg-white/30 dark:bg-slate-800/10 rounded-2xl">
              <span className="text-lg">⚡</span>
              <div>
                <h4 className="text-xs font-black text-slate-800 dark:text-slate-200 uppercase">{t("auth_feat3_title")}</h4>
                <p className="text-[11px] text-slate-505 dark:text-slate-400 mt-0.5">{t("auth_feat3_desc")}</p>
              </div>
            </div>
          </div>

          <button
            onClick={handleGoogleLogin}
            className="w-full py-4 px-6 bg-white hover:bg-slate-50 dark:bg-slate-850 dark:hover:bg-slate-800 text-slate-700 dark:text-white font-bold text-sm tracking-wide rounded-2xl border border-slate-200/80 dark:border-slate-800 transition-all flex items-center justify-center gap-3 shadow-md hover:-translate-y-0.5 active:translate-y-0 cursor-pointer"
          >
            <svg className="w-5 h-5 shrink-0" viewBox="0 0 24 24" fill="none">
              <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
              <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
              <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.06H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.94l3.66-2.85z" fill="#FBBC05"/>
              <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.06l3.66 2.85c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
            </svg>
            {t("auth_btn_google")}
          </button>
        </main>
      </div>
    );
  }

  return (
    <div className={`min-h-screen w-full bg-emerald-50/60 dark:bg-slate-950 font-sans text-slate-800 dark:text-slate-200 relative overflow-x-hidden flex flex-col selection:bg-emerald-200 dark:selection:bg-emerald-900 selection:text-emerald-950 dark:selection:text-emerald-50 antialiased transition-colors duration-300 ${darkMode ? "dark" : ""}`}>
      {/* Background Mesh Gradients */}
      <div className="absolute -top-24 -left-24 w-96 h-96 bg-emerald-200/50 dark:bg-emerald-900/10 rounded-full mix-blend-multiply filter blur-3xl opacity-70 pointer-events-none"></div>
      <div className="absolute top-1/3 -right-24 w-96 h-96 bg-blue-200/50 dark:bg-sky-900/10 rounded-full mix-blend-multiply filter blur-3xl opacity-70 pointer-events-none"></div>
      <div className="absolute -bottom-24 left-1/4 w-96 h-96 bg-lime-200/40 dark:bg-emerald-950/10 rounded-full mix-blend-multiply filter blur-3xl opacity-60 pointer-events-none"></div>

      {/* Header Section */}
      <header className="relative z-10 flex flex-col sm:flex-row items-center justify-between gap-4 px-6 py-5 sm:px-10 sm:py-6 bg-white/30 dark:bg-slate-900/40 backdrop-blur-md border-b border-white/40 dark:border-slate-800/40 shadow-xs mb-8">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-emerald-500 rounded-xl flex items-center justify-center shadow-lg shadow-emerald-200">
            <svg className="w-6 h-6 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01"></path>
            </svg>
          </div>
          <div>
            <h1 className="text-xl sm:text-2xl font-extrabold tracking-tight text-emerald-950 dark:text-emerald-400 font-display">{t("app_title")}</h1>
            <p className="text-[11px] text-emerald-800 dark:text-emerald-400/80 font-semibold uppercase tracking-wider block mt-0.5">{t("app_sub_title")}</p>
          </div>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {/* User Profile Pill */}
          {user && (
            <div className="flex items-center gap-2 px-3 py-1.5 bg-white/50 dark:bg-slate-800 rounded-xl border border-slate-200/80 dark:border-slate-700/85 max-w-[200px] sm:max-w-xs overflow-hidden shadow-xs">
              {user.photoURL ? (
                <img
                  src={user.photoURL}
                  referrerPolicy="no-referrer"
                  alt={user.displayName || "Avatar"}
                  className="w-5 h-5 rounded-md object-cover"
                />
              ) : (
                <UserIcon size={14} className="text-slate-500" />
              )}
              <span className="text-[11px] font-black text-slate-700 dark:text-slate-300 truncate max-w-[70px] sm:max-w-[110px]" title={user.displayName || user.email || ""}>
                {user.displayName || user.email?.split("@")[0] || t("profile_fallback")}
              </span>
              <button
                onClick={handleSignOut}
                className="p-1 text-slate-400 hover:text-red-500 rounded-md transition-colors cursor-pointer"
                title={t("sign_out_title")}
              >
                <LogOut size={13} />
              </button>
            </div>
          )}

          {/* Language Switcher */}
          <div className="flex bg-white/50 dark:bg-slate-800 p-0.5 rounded-xl border border-slate-200/80 dark:border-slate-700 shadow-xs">
            <button
              onClick={() => setLanguage("ru")}
              className={`px-2 py-1 text-[10px] font-black rounded-lg transition-all cursor-pointer ${
                language === "ru"
                  ? "bg-emerald-500 text-white shadow-xs"
                  : "text-slate-500 dark:text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              RU
            </button>
            <button
              onClick={() => setLanguage("en")}
              className={`px-2 py-1 text-[10px] font-black rounded-lg transition-all cursor-pointer ${
                language === "en"
                  ? "bg-emerald-500 text-white shadow-xs"
                  : "text-slate-400 hover:text-slate-800 dark:hover:text-slate-200"
              }`}
            >
              EN
            </button>
          </div>

          {/* Theme Switcher Toggle button */}
          <button
            onClick={() => setDarkMode(prev => !prev)}
            className="p-2 w-10 h-10 rounded-xl flex items-center justify-center transition-all bg-white/80 dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700/80 text-slate-700 dark:text-yellow-400 border border-slate-200 dark:border-slate-700 cursor-pointer shadow-xs active:scale-95"
            title={darkMode ? t("theme_light_tooltip") : t("theme_dark_tooltip")}
          >
            {darkMode ? (
              <svg className="w-5 h-5 text-yellow-500 fill-yellow-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364-6.364l-.707.707M6.343 17.657l-.707.707m0-11.314l.707.707m11.314 11.314l.707.707M12 5a7 7 0 100 14 7 7 0 000-14z" />
              </svg>
            ) : (
              <svg className="w-5 h-5 text-slate-600 fill-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
              </svg>
            )}
          </button>

          <span className="text-[10px] sm:text-xs font-black px-3 py-1 bg-emerald-100/70 dark:bg-slate-800 text-emerald-800 dark:text-slate-300 rounded-full border border-emerald-200/30 dark:border-slate-700/60">
            {t("version_label")}
          </span>
        </div>
      </header>

      {/* Mobile Sticky Tab Segment Bar (visible only on mobile/tablets under lg) */}
      <div className="lg:hidden sticky top-[72px] sm:top-[88px] z-20 px-4 py-2 bg-emerald-50/95 dark:bg-slate-900/90 backdrop-blur-md border-b border-emerald-500/10 dark:border-slate-800/40 mb-6 -mt-4 flex justify-between gap-2 transition-colors duration-300">
        {[
          { id: "menu", label: t("tab_diary"), icon: "📋" },
          { id: "form", label: t("tab_add"), icon: "✍️" },
          { id: "summary", label: t("tab_ai_progress"), icon: "🤖" },
        ].map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveMobileTab(tab.id as any)}
            className={`flex-1 py-3 px-2 rounded-2xl text-[11px] font-black transition-all cursor-pointer flex items-center justify-center gap-1.5 shadow-xs ${
              activeMobileTab === tab.id
                ? "bg-emerald-500 text-white shadow-md shadow-emerald-200"
                : "bg-white dark:bg-slate-800 text-emerald-800 dark:text-emerald-300 hover:bg-slate-50 dark:hover:bg-slate-700/60 border border-slate-200/40 dark:border-slate-700/60"
            }`}
          >
            <span className="text-sm">{tab.icon}</span>
            <span>{tab.label}</span>
          </button>
        ))}
      </div>

      {/* Main Content Grid arranged into 3 responsive columns */}
      <main className="relative z-10 flex-1 grid grid-cols-1 lg:grid-cols-12 gap-8 px-4 sm:px-10 pb-12 w-full max-w-7xl mx-auto items-start">
        
        {/* Column 1: Progress & Summary + Tip of the day */}
        <section className={`lg:col-span-4 flex flex-col gap-6 w-full ${activeMobileTab === "summary" ? "block" : "hidden lg:flex"}`}>
          <SummaryBox
            kcal={totals.kcal}
            protein={totals.protein}
            fat={totals.fat}
            carb={totals.carb}
            goals={goals}
          />

          {/* Advice of the Day - highly aesthetic element from the theme design */}
          <div className="bg-emerald-600 dark:bg-slate-900/45 p-6 rounded-3xl border border-transparent dark:border-slate-800/60 shadow-xl shadow-emerald-950/10 text-white relative overflow-hidden transition-all hover:scale-101 hover:shadow-2xl">
            <div className="relative z-10">
              <h4 className="text-base font-bold mb-1.5 font-display flex items-center gap-1.5 text-white dark:text-emerald-400">
                <Sparkles size={16} />
                {t("tip_title")}
              </h4>
              <p className="text-emerald-50 dark:text-slate-300 text-xs sm:text-sm leading-relaxed opacity-95">
                {t("tip_content")}
              </p>
            </div>
            <div className="absolute top-0 right-0 p-4 opacity-15 transform translate-x-4 -translate-y-4 text-white dark:text-emerald-600">
              <svg className="w-24 h-24" fill="currentColor" viewBox="0 0 20 20">
                <path d="M11 3a1 1 0 10-2 0v1a1 1 0 102 0V3zM15.657 5.757a1 1 0 00-1.414-1.414l-.707.707a1 1 0 001.414 1.414l.707-.707zM18 10a1 1 0 01-1 1h-1a1 1 0 110-2h1a1 1 0 011 1zM5.05 6.464A1 1 0 106.465 5.05l-.708-.707a1 1 0 00-1.414 1.414l.707.707zM5 10a1 1 0 01-1 1H3a1 1 0 110-2h1a1 1 0 011 1zM8 16v-1a1 1 0 112 0v1a1 1 0 11-2 0zM13.464 15.05a1 1 0 011.415-1.415l.707.707a1 1 0 01-1.414 1.414l-.707-.707zM14.586 11H12.414l-1.707 1.707a1 1 0 01-1.414 0L7.586 11H5.414a1 1 0 01-.707-1.707l1.707-1.707a1 1 0 011.414 0L9 8.586V6a1 1 0 012 0v2.586l1.293-1.293a1 1 0 011.414 0l1.707 1.707a1 1 0 01-.707 1.707z"></path>
              </svg>
            </div>
          </div>

          {/* AI Scanner Component */}
          <AiScanner
            selectedDate={selectedDate}
            onAddFood={handleAddFood}
            templates={templates}
            onSaveTemplate={handleSaveTemplate}
          />
        </section>

        {/* Column 2: Datepicker and Form */}
        <section className={`lg:col-span-4 flex flex-col gap-6 w-full relative ${activeMobileTab === "form" ? "block" : "hidden lg:flex"}`}>
          <DatePicker selectedDate={selectedDate} onChange={setSelectedDate} />
          {dayLoading && (
            <div className="absolute inset-0 bg-slate-900/10 dark:bg-slate-950/20 backdrop-blur-xs flex items-center justify-center z-10 rounded-3xl">
              <Loader2 className="w-8 h-8 text-emerald-500 animate-spin" />
            </div>
          )}
          <AddFoodForm
            templates={templates}
            onSaveTemplate={handleSaveTemplate}
            onDeleteTemplate={handleDeleteTemplate}
            onAdd={handleAddFood}
          />
        </section>

        {/* Column 3: Daily Log */}
        <section className={`lg:col-span-4 w-full flex flex-col gap-0 select-none relative ${activeMobileTab === "menu" ? "block" : "hidden lg:flex"}`}>
          <div className="mb-4 flex items-center justify-between px-2">
            <h3 className="text-sm uppercase tracking-wider font-bold text-emerald-800 dark:text-emerald-400 font-display">
              {t("meal_header")}
            </h3>
            <span className="text-xs font-semibold text-emerald-600/90 dark:text-emerald-400/80">
              {t("meal_positions").replace("{count}", String(currentDayData.breakfast.length + currentDayData.lunch.length + currentDayData.dinner.length + currentDayData.snack.length))}
            </span>
          </div>

          {/* Copy Yesterday's Menu Button */}
          <button
            id="copy-yesterday"
            onClick={handleCopyYesterday}
            className="mb-4 w-full py-3 px-4 bg-emerald-500 hover:bg-emerald-600 text-white font-bold text-xs uppercase tracking-wider rounded-2xl transition-all flex items-center justify-center gap-2 shadow-md hover:-translate-y-0.5 active:translate-y-0 cursor-pointer"
            title={t("meal_copy_btn")}
          >
            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M8 7v8a2 2 0 002 2h6M8 7V5a2 2 0 012-2h4.586a1 1 0 01.707.293l4.414 4.414a1 1 0 01.293.707V15a2 2 0 01-2 2h-2M8 7H6a2 2 0 00-2 2v10a2 2 0 002 2h8a2 2 0 002-2v-2"></path>
            </svg>
            {t("meal_copy_btn")}
          </button>

          {copyFeedback && (
            <div className={`mb-4 p-3.5 text-xs font-bold rounded-2xl border text-center animate-fade-in ${
              copyFeedback.type === "success" 
                ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-800" 
                : "bg-red-500/10 border-red-500/20 text-red-700"
            }`}>
              {copyFeedback.text}
            </div>
          )}

          {dayLoading && (
            <div className="absolute inset-0 bg-slate-900/10 dark:bg-slate-950/20 backdrop-blur-xs flex items-center justify-center z-10 rounded-3xl">
              <Loader2 className="w-8 h-8 text-emerald-505 animate-spin" />
            </div>
          )}

          <div id="menu-container" className="space-y-4">
            <MealSection
              type="breakfast"
              items={currentDayData.breakfast}
              onDelete={(idx) => handleDeleteFood("breakfast", idx)}
            />
            <MealSection
              type="lunch"
              items={currentDayData.lunch}
              onDelete={(idx) => handleDeleteFood("lunch", idx)}
            />
            <MealSection
              type="dinner"
              items={currentDayData.dinner}
              onDelete={(idx) => handleDeleteFood("dinner", idx)}
            />
            <MealSection
              type="snack"
              items={currentDayData.snack}
              onDelete={(idx) => handleDeleteFood("snack", idx)}
            />
          </div>
        </section>

      </main>

      {/* Dynamic Dashboard Section for Progress & Goal Customization */}
      <div className={`relative z-10 max-w-7xl mx-auto px-4 sm:px-10 pb-12 w-full flex flex-col gap-8 ${activeMobileTab === "summary" ? "block" : "hidden lg:flex"}`}>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-8 w-full items-start">
          <GoalSettings goals={goals} onSaveGoals={handleSaveGoals} />
          <ProgressAnalysis historyData={historyData} goals={goals} />
        </div>
      </div>

      {/* Bottom Bar Info */}
      <footer className="relative z-10 px-6 py-5 sm:px-10 sm:py-6 bg-emerald-950/5 dark:bg-slate-900/30 backdrop-blur-xs border-t border-white/20 dark:border-slate-800/50 mt-auto transition-colors duration-300">
        <div className="max-w-7xl mx-auto flex flex-col sm:flex-row justify-between items-center gap-3 text-[11px] font-bold text-emerald-800 dark:text-slate-400 uppercase tracking-widest text-center">
          <span>{t("footer_copyright")}</span>
          <div className="flex flex-wrap justify-center gap-x-6 gap-y-1.5 font-semibold">
            <span>{t("footer_goal")}</span>
            <span>{t("footer_method")}</span>
            <span className="font-extrabold text-emerald-950 dark:text-emerald-300">
              {t("footer_compliance").replace("{percent}", String((() => {
                let logged = 0, success = 0;
                const today = new Date();
                for (let i = 0; i < 7; i++) {
                  const d = new Date(today);
                  d.setDate(today.getDate() - i);
                  const dStr = d.toISOString().split("T")[0];
                  const dayVal = historyData[dStr];
                  if (dayVal) {
                    let dayKcal = 0;
                    const meals: ("breakfast" | "lunch" | "dinner" | "snack")[] = ["breakfast", "lunch", "dinner", "snack"];
                    meals.forEach(m => (dayVal[m] || []).forEach(item => dayKcal += (item.kcal || 0)));
                    if (dayKcal > 0) {
                      logged++;
                      if (Math.abs(dayKcal - goals.kcal) <= goals.kcal * 0.15) {
                        success++;
                      }
                    }
                  }
                }
                return logged > 0 ? Math.round((success / logged) * 100) : 100;
              })()))}%
            </span>
          </div>
        </div>
      </footer>
    </div>
  );
}
