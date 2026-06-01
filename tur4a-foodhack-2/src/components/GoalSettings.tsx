import React, { useState } from "react";
import { Settings, Calculator, Check, Flame, Star, Droplets, Wheat, ChevronDown, ChevronUp } from "lucide-react";
import { UserGoals } from "../types";

interface GoalSettingsProps {
  goals: UserGoals;
  onSaveGoals: (newGoals: UserGoals) => void;
}

export default function GoalSettings({ goals, onSaveGoals }: GoalSettingsProps) {
  // Manual goals editor state
  const [kcal, setKcal] = useState(goals.kcal.toString());
  const [protein, setProtein] = useState(goals.protein.toString());
  const [fat, setFat] = useState(goals.fat.toString());
  const [carb, setCarb] = useState(goals.carb.toString());

  const [isSaved, setIsSaved] = useState(false);
  const [showCalculator, setShowCalculator] = useState(false);

  // Synchronize when outer goals change (e.g., loaded from database)
  React.useEffect(() => {
    setKcal(goals.kcal.toString());
    setProtein(goals.protein.toString());
    setFat(goals.fat.toString());
    setCarb(goals.carb.toString());
  }, [goals]);

  // Calculator inputs state
  const [gender, setGender] = useState<"male" | "female">("female");
  const [age, setAge] = useState("28");
  const [height, setHeight] = useState("165");
  const [weight, setWeight] = useState("62");
  const [activity, setActivity] = useState("1.375"); // moderate/light activity
  const [targetMode, setTargetMode] = useState<"lose" | "maintain" | "gain">("lose");

  const [calculatedGoals, setCalculatedGoals] = useState<UserGoals | null>(null);

  // Perform Mifflin-St Jeor + Macro split math
  const handleCalculate = (e: React.FormEvent) => {
    e.preventDefault();
    const w = parseFloat(weight) || 60;
    const h = parseFloat(height) || 165;
    const a = parseFloat(age) || 28;
    const mult = parseFloat(activity) || 1.375;

    // 1. Calculate BMR
    let bmr = 0;
    if (gender === "male") {
      bmr = 10 * w + 6.25 * h - 5 * a + 5;
    } else {
      bmr = 10 * w + 6.25 * h - 5 * a - 161;
    }

    // 2. TDEE
    let tdee = bmr * mult;

    // 3. Goal multiplier
    let calorieGoal = Math.round(tdee);
    if (targetMode === "lose") {
      calorieGoal = Math.round(tdee * 0.82); // 18% deficit
    } else if (targetMode === "gain") {
      calorieGoal = Math.round(tdee * 1.15); // 15% surplus
    }

    // Prevent unhealthy goals
    calorieGoal = Math.max(gender === "male" ? 1400 : 1200, calorieGoal);

    // 4. Nutrients macro structure
    // Protein: Lose: 2.0g/kg, Maintain: 1.6g/kg, Gain: 2.0g/kg
    // Fat: 1.0g/kg (Lose: 0.9g/kg, Gain: 1.1g/kg)
    // Carbs: rest of calories
    let proteinGrams = 0;
    let fatGrams = 0;

    if (targetMode === "lose") {
      proteinGrams = Math.round(w * 2.0);
      fatGrams = Math.round(w * 0.9);
    } else if (targetMode === "gain") {
      proteinGrams = Math.round(w * 2.0);
      fatGrams = Math.round(w * 1.1);
    } else {
      proteinGrams = Math.round(w * 1.6);
      fatGrams = Math.round(w * 1.0);
    }

    // Safeguard minimum B/Ж
    proteinGrams = Math.max(40, proteinGrams);
    fatGrams = Math.max(35, fatGrams);

    // Carbohydrates: (Total kcal - (Protein*4 + Fat*9)) / 4
    const pKcal = proteinGrams * 4;
    const fKcal = fatGrams * 9;
    let carbGrams = Math.round((calorieGoal - pKcal - fKcal) / 4);
    carbGrams = Math.max(50, carbGrams);

    // Re-adjust calorie goal based on precise final macros
    const preciseKcal = proteinGrams * 4 + fatGrams * 9 + carbGrams * 4;

    const result: UserGoals = {
      kcal: preciseKcal,
      protein: proteinGrams,
      fat: fatGrams,
      carb: carbGrams,
    };

    setCalculatedGoals(result);
  };

  const handleApplyCalculated = () => {
    if (!calculatedGoals) return;
    onSaveGoals(calculatedGoals);
    
    // Set manual fields instantly
    setKcal(calculatedGoals.kcal.toString());
    setProtein(calculatedGoals.protein.toString());
    setFat(calculatedGoals.fat.toString());
    setCarb(calculatedGoals.carb.toString());

    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 3000);
  };

  const handleManualSave = (e: React.FormEvent) => {
    e.preventDefault();
    const finalGoals: UserGoals = {
      kcal: Math.max(500, parseInt(kcal) || 2000),
      protein: Math.max(10, parseInt(protein) || 120),
      fat: Math.max(10, parseInt(fat) || 70),
      carb: Math.max(10, parseInt(carb) || 250),
    };
    onSaveGoals(finalGoals);
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 3000);
  };

  return (
    <div className="bg-white/60 dark:bg-slate-900/40 backdrop-blur-xl border border-white/80 dark:border-slate-800/60 p-6 sm:p-8 rounded-3xl shadow-xl shadow-emerald-900/5 transition-colors duration-300">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="p-2 bg-indigo-500 text-white rounded-xl shadow-md shadow-indigo-200/30">
            <Settings size={18} />
          </div>
          <h3 className="text-lg font-bold text-slate-800 dark:text-slate-200 font-display">
            Настройка целей
          </h3>
        </div>
        <button
          type="button"
          onClick={() => setShowCalculator((prev) => !prev)}
          className="text-xs font-bold text-indigo-700 dark:text-indigo-400 bg-indigo-100/60 dark:bg-indigo-950/40 hover:bg-indigo-50 dark:hover:bg-indigo-900/50 px-3 py-1.5 rounded-full border border-indigo-200/40 dark:border-indigo-900/30 cursor-pointer flex items-center gap-1 transition-all"
        >
          <Calculator size={12} />
          {showCalculator ? "Скрыть калькулятор" : "ИИ Калькулятор"}
        </button>
      </div>

      {isSaved && (
        <div className="mb-4 p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-800 rounded-xl text-xs font-semibold animate-fade-in flex items-center gap-1.5 shadow-2xs">
          <Check size={14} className="text-emerald-600" />
          <span>Новые КБЖУ цели успешно сохранены в облаке!</span>
        </div>
      )}

      {/* Main Form container: conditionally renders calculator wizard */}
      {!showCalculator ? (
        <form onSubmit={handleManualSave} className="space-y-4">
          <p className="text-[11px] text-slate-500 dark:text-slate-400 font-medium">
            Укажите персональные рамки КБЖУ вручную. Они будут учитываться на дашборде.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col">
              <label className="text-[10px] uppercase font-bold text-slate-400 dark:text-slate-500 mb-1 tracking-wider">
                Калории (ккал)
              </label>
              <input
                type="number"
                value={kcal}
                onChange={(e) => setKcal(e.target.value)}
                className="w-full h-10 px-3.5 bg-white/70 dark:bg-slate-800/60 border border-slate-200 hover:border-indigo-400 dark:border-slate-700/60 rounded-xl text-sm font-bold text-slate-850 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-indigo-400 outline-hidden"
              />
            </div>
            <div className="flex flex-col">
              <label className="text-[10px] uppercase font-bold text-slate-400 dark:text-slate-500 mb-1 tracking-wider">
                Белки (г)
              </label>
              <input
                type="number"
                value={protein}
                onChange={(e) => setProtein(e.target.value)}
                className="w-full h-10 px-3.5 bg-white/70 dark:bg-slate-800/60 border border-slate-200 hover:border-indigo-400 dark:border-slate-700/60 rounded-xl text-sm font-bold text-slate-850 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-indigo-400 outline-hidden"
              />
            </div>
            <div className="flex flex-col">
              <label className="text-[10px] uppercase font-bold text-slate-400 dark:text-slate-500 mb-1 tracking-wider">
                Жиры (г)
              </label>
              <input
                type="number"
                value={fat}
                onChange={(e) => setFat(e.target.value)}
                className="w-full h-10 px-3.5 bg-white/70 dark:bg-slate-800/60 border border-slate-200 hover:border-indigo-400 dark:border-slate-700/60 rounded-xl text-sm font-bold text-slate-850 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-indigo-400 outline-hidden"
              />
            </div>
            <div className="flex flex-col">
              <label className="text-[10px] uppercase font-bold text-slate-400 dark:text-slate-500 mb-1 tracking-wider">
                Углеводы (г)
              </label>
              <input
                type="number"
                value={carb}
                onChange={(e) => setCarb(e.target.value)}
                className="w-full h-10 px-3.5 bg-white/70 dark:bg-slate-800/60 border border-slate-200 hover:border-indigo-400 dark:border-slate-700/60 rounded-xl text-sm font-bold text-slate-850 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-indigo-400 outline-hidden"
              />
            </div>
          </div>
          <button
            type="submit"
            className="w-full py-2.5 px-4 bg-indigo-500 hover:bg-indigo-600 text-white font-bold text-xs uppercase tracking-wider rounded-xl shadow-md cursor-pointer transition-all active:scale-95"
          >
            Сохранить цели вручную
          </button>
        </form>
      ) : (
        /* Mifflin-St Jeor Interactive Calculation Form */
        <div className="space-y-4 animate-fade-in text-slate-800 dark:text-slate-200">
          <p className="text-[10px] sm:text-[11px] text-slate-500 dark:text-slate-400 font-medium leading-relaxed">
            Впишите свои антропометрические показатели, чтобы рассчитать оптимальный баланс калорий и нутриентов по научной формуле <strong>Mifflin-St Jeor</strong>.
          </p>

          <form onSubmit={handleCalculate} className="space-y-3.5">
            {/* Gender switch */}
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => setGender("female")}
                className={`py-2 px-3 text-xs font-bold rounded-xl border cursor-pointer transition-all ${
                  gender === "female"
                    ? "bg-rose-500 text-white border-rose-400 shadow-sm"
                    : "bg-white/70 dark:bg-slate-800/40 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700/60 hover:bg-slate-50"
                }`}
              >
                🚺 Женщина (-161)
              </button>
              <button
                type="button"
                onClick={() => setGender("male")}
                className={`py-2 px-3 text-xs font-bold rounded-xl border cursor-pointer transition-all ${
                  gender === "male"
                    ? "bg-blue-500 text-white border-blue-400 shadow-sm"
                    : "bg-white/70 dark:bg-slate-800/40 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700/60 hover:bg-slate-50"
                }`}
              >
                🚹 Мужчина (+5)
              </button>
            </div>

            {/* Age, Height, Weight row */}
            <div className="grid grid-cols-3 gap-2">
              <div className="flex flex-col">
                <label className="text-[9px] uppercase font-bold text-slate-400 dark:text-slate-500 mb-1">
                  Возраст (лет)
                </label>
                <input
                  type="number"
                  value={age}
                  onChange={(e) => setAge(e.target.value)}
                  placeholder="28"
                  min="12"
                  max="100"
                  className="w-full h-10 px-2.5 bg-white/70 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl text-xs font-bold focus:outline-hidden focus:ring-1 focus:ring-indigo-400 outline-hidden"
                  required
                />
              </div>
              <div className="flex flex-col">
                <label className="text-[9px] uppercase font-bold text-slate-400 dark:text-slate-500 mb-1">
                  Рост (см)
                </label>
                <input
                  type="number"
                  value={height}
                  onChange={(e) => setHeight(e.target.value)}
                  placeholder="165"
                  min="100"
                  max="250"
                  className="w-full h-10 px-2.5 bg-white/70 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl text-xs font-bold focus:outline-hidden focus:ring-1 focus:ring-indigo-400 outline-hidden"
                  required
                />
              </div>
              <div className="flex flex-col">
                <label className="text-[9px] uppercase font-bold text-slate-400 dark:text-slate-500 mb-1">
                  Вес (кг)
                </label>
                <input
                  type="number"
                  value={weight}
                  onChange={(e) => setWeight(e.target.value)}
                  placeholder="62"
                  min="30"
                  max="300"
                  className="w-full h-10 px-2.5 bg-white/70 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl text-xs font-bold focus:outline-hidden focus:ring-1 focus:ring-indigo-400 outline-hidden"
                  required
                />
              </div>
            </div>

            {/* Physical Activity Multiplier selector */}
            <div className="flex flex-col">
              <label className="text-[9px] uppercase font-bold text-slate-400 dark:text-slate-500 mb-1 tracking-wider">
                Уровень физической активности
              </label>
              <select
                value={activity}
                onChange={(e) => setActivity(e.target.value)}
                className="w-full h-10 px-3 bg-white/70 dark:bg-slate-800/60 border border-slate-200 dark:border-slate-700/60 rounded-xl text-xs font-bold text-slate-700 dark:text-slate-200 focus:outline-hidden cursor-pointer outline-hidden"
              >
                <option value="1.2">Офисный / Малоподвижный (1.2)</option>
                <option value="1.375">Легкая активность (тренировки 1-2 раза в нед) (1.375)</option>
                <option value="1.55">Умеренная спорт активность (3-5 раз в нед) (1.55)</option>
                <option value="1.725">Высокая нагрузка (тяжелый спорт ежедневно) (1.725)</option>
                <option value="1.9">Проф. спортсмен / Экстремальная физ-работа (1.9)</option>
              </select>
            </div>

            {/* Goal Strategy Selection */}
            <div className="flex flex-col">
              <label className="text-[9px] uppercase font-bold text-slate-400 dark:text-slate-500 mb-1 tracking-wider">
                Основная задача рацион-режима
              </label>
              <div className="grid grid-cols-3 gap-2">
                {[
                  { id: "lose", label: "🔥 Похудение", desc: "-18% Дефицит" },
                  { id: "maintain", label: "⚖️ Баланс", desc: "Удержание" },
                  { id: "gain", label: "💪 Профицит", desc: "+15% Набор" }
                ].map((st) => (
                  <button
                    key={st.id}
                    type="button"
                    onClick={() => setTargetMode(st.id as any)}
                    className={`p-2.5 rounded-xl border text-center cursor-pointer flex flex-col items-center justify-center transition-all ${
                      targetMode === st.id
                        ? "bg-indigo-500 text-white border-indigo-400 shadow-sm"
                        : "bg-white/70 dark:bg-slate-800/40 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700/60 hover:bg-slate-50"
                    }`}
                  >
                    <span className="text-[10px] font-bold block">{st.label}</span>
                    <span className="text-[8px] opacity-75 mt-0.5">{st.desc}</span>
                  </button>
                ))}
              </div>
            </div>

            <button
              type="submit"
              className="w-full py-2.5 px-4 bg-indigo-500 hover:bg-indigo-600 text-white font-bold text-xs uppercase tracking-wider rounded-xl shadow-md cursor-pointer transition-all flex items-center justify-center gap-1.5 active:scale-97"
            >
              📊 Рассчитать КБЖУ
            </button>
          </form>

          {/* Calculator Results Display */}
          {calculatedGoals && (
            <div className="p-4 bg-indigo-500/5 dark:bg-slate-900/60 border border-indigo-500/15 dark:border-slate-800/60 rounded-2xl animate-fade-in text-slate-800 dark:text-slate-100 mt-4 shadow-sm">
              <h4 className="text-xs uppercase font-extrabold text-indigo-700 dark:text-indigo-400 mb-3 tracking-wider flex items-center gap-1">
                <Calculator size={14} />
                Ваши индивидуальные рекомендации:
              </h4>

              {/* Dynamic Values list */}
              <div className="space-y-2 mb-4">
                <div className="flex items-center justify-between text-xs font-semibold py-1 border-b border-dashed border-slate-200 dark:border-slate-800">
                  <span className="text-slate-500 dark:text-slate-400 flex items-center gap-1">
                    <Flame size={12} className="text-amber-500" /> Спланировано калорий:
                  </span>
                  <span className="font-extrabold text-slate-800 dark:text-slate-100">{calculatedGoals.kcal} ккал/день</span>
                </div>
                <div className="flex items-center justify-between text-xs font-semibold py-1 border-b border-dashed border-slate-200 dark:border-slate-800">
                  <span className="text-slate-500 dark:text-slate-400 flex items-center gap-1">
                    <Star size={12} className="text-blue-500" /> Рекомендуемый Белок:
                  </span>
                  <span className="font-extrabold text-blue-600 dark:text-blue-400">{calculatedGoals.protein} г/день</span>
                </div>
                <div className="flex items-center justify-between text-xs font-semibold py-1 border-b border-dashed border-slate-200 dark:border-slate-800">
                  <span className="text-slate-500 dark:text-slate-400 flex items-center gap-1">
                    <Droplets size={12} className="text-orange-500" /> Рекомендуемые Жиры:
                  </span>
                  <span className="font-extrabold text-orange-600 dark:text-orange-400">{calculatedGoals.fat} г/день</span>
                </div>
                <div className="flex items-center justify-between text-xs font-semibold py-1 border-b border-dashed border-slate-200 dark:border-slate-800">
                  <span className="text-slate-500 dark:text-slate-400 flex items-center gap-1">
                    <Wheat size={12} className="text-emerald-500" /> Углеводы под баланс:
                  </span>
                  <span className="font-extrabold text-emerald-600 dark:text-emerald-400">{calculatedGoals.carb} г/день</span>
                </div>
              </div>

              <button
                type="button"
                onClick={handleApplyCalculated}
                className="w-full py-3 bg-emerald-500 hover:bg-emerald-600 text-white font-extrabold text-xs uppercase tracking-wider rounded-xl shadow-md transition-all flex items-center justify-center gap-1.5 cursor-pointer hover:-translate-y-0.5 active:translate-y-0"
              >
                ✅ Применить и сделать новой целью!
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
