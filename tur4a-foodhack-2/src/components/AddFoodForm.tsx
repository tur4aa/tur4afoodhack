import React, { useState, useEffect } from "react";
import { Plus, Utensils, Scale, Sparkles, Flame, Check, Bookmark, Trash2, ArrowRight } from "lucide-react";
import { MealType, FoodTemplate } from "../types";

interface AddFoodFormProps {
  templates: FoodTemplate[];
  onSaveTemplate: (template: FoodTemplate) => void;
  onDeleteTemplate: (id: string) => void;
  onAdd: (
    mealType: MealType,
    name: string,
    kcal: number,
    protein: number,
    fat: number,
    carb: number,
    weight: number,
    unit?: string,
    portionSize?: number
  ) => void;
}

// Global weight in grams equivalent of each unit to allow safe cross-unit math conversion
const UNIT_WEIGHTS: Record<string, number> = {
  "г": 1,
  "шт": 50,
  "ст. л.": 15,
  "ч. л.": 5,
  "стакан": 240,
  "порц": 150
};

export default function AddFoodForm({ templates, onSaveTemplate, onDeleteTemplate, onAdd }: AddFoodFormProps) {
  const [mealType, setMealType] = useState<MealType>("breakfast");
  const [name, setName] = useState("");
  const [unit, setUnit] = useState<string>("г"); // Weight unit selection: "г", "шт", "ст. л.", "ч. л.", "стакан", "порц"
  const [weight, setWeight] = useState<string>("100"); // Eaten quantity (weight grams or piece count)
  
  // Custom baseline for KBJU
  const [customBase, setCustomBase] = useState<boolean>(false);
  const [baseAmount, setBaseAmount] = useState<string>("100");
  const [baseUnit, setBaseUnit] = useState<string>("г");

  const [kcal, setKcal] = useState<string>("");         // specified per custom base quantity
  const [protein, setProtein] = useState<string>("");   // specified per custom base quantity
  const [fat, setFat] = useState<string>("");           // specified per custom base quantity
  const [carb, setCarb] = useState<string>("");         // specified per custom base quantity
  
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  // Math Conversion ratio generator
  const getConversionFactor = (
    loggedAmt: number,
    loggedU: string,
    baseAmt: number,
    baseU: string
  ): number => {
    if (loggedU === baseU) {
      return loggedAmt / (baseAmt || 1);
    }
    const loggedWeight = UNIT_WEIGHTS[loggedU] || 1;
    const baseWeight = UNIT_WEIGHTS[baseU] || 100;
    
    const loggedGrams = loggedAmt * loggedWeight;
    const baseGrams = baseAmt * baseWeight;
    
    return loggedGrams / (baseGrams || 1);
  };

  // Handle Quick Tag select
  const handleSelectTemplate = (tmpl: FoodTemplate) => {
    setName(tmpl.name);
    setKcal(tmpl.kcal.toString());
    setProtein(tmpl.protein.toString());
    setFat(tmpl.fat.toString());
    setCarb(tmpl.carb.toString());
    
    // Set custom base parameters from template if present
    const tBaseAmt = tmpl.baseAmount ?? 100;
    const tBaseUnit = tmpl.baseUnit ?? "г";
    
    setBaseAmount(tBaseAmt.toString());
    setBaseUnit(tBaseUnit);
    
    if (tBaseAmt !== 100 || tBaseUnit !== "г") {
      setCustomBase(true);
    } else {
      setCustomBase(false);
    }

    // Set logged unit and amount to match template default
    setUnit(tBaseUnit);
    setWeight(tBaseAmt.toString());
    setError(null);
  };

  const handleDeleteTemplate = (e: React.MouseEvent, id: string) => {
    e.stopPropagation(); // prevent select action
    onDeleteTemplate(id);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();

    if (!name.trim()) {
      setError("Пожалуйста, введите название блюда / продукта");
      return;
    }

    const numValue = parseFloat(weight) || 0;
    if (numValue <= 0) {
      setError(`Укажите количество в "${unit}" (например, ${unit === "г" ? "100" : "1"})`);
      return;
    }

    setError(null);

    // Baseline stats loaded
    const baseKcal = parseFloat(kcal) || 0;
    const baseProtein = parseFloat(protein) || 0;
    const baseFat = parseFloat(fat) || 0;
    const baseCarb = parseFloat(carb) || 0;

    // Resolve what base values the entered stats correspond to
    const bAmt = customBase ? (parseFloat(baseAmount) || 100) : (unit === "г" ? 100 : 1);
    const bUnit = customBase ? baseUnit : (unit === "г" ? "г" : unit);

    // Dynamic factor
    const factor = getConversionFactor(numValue, unit, bAmt, bUnit);

    const finalKcal = Math.round(baseKcal * factor);
    const finalProtein = Math.round((baseProtein * factor) * 10) / 10;
    const finalFat = Math.round((baseFat * factor) * 10) / 10;
    const finalCarb = Math.round((baseCarb * factor) * 10) / 10;

    // Eaten grams representation
    const finalGrams = unit === "г" ? numValue : numValue * (UNIT_WEIGHTS[unit] || 50);

    // Trigger parent callback
    onAdd(
      mealType,
      name.trim(),
      finalKcal,
      finalProtein,
      finalFat,
      finalCarb,
      finalGrams,
      unit,
      numValue
    );

    // Save or update template inside parent (using Firestore or localStorage dependency)
    const exists = templates.find(t => t.name.toLowerCase() === name.trim().toLowerCase());
    const newTmpl: FoodTemplate = {
      id: exists ? exists.id : `tmpl-${Date.now()}`,
      name: name.trim(),
      kcal: baseKcal,
      protein: baseProtein,
      fat: baseFat,
      carb: baseCarb,
      usageCount: exists ? exists.usageCount + 1 : 1,
      baseAmount: bAmt,
      baseUnit: bUnit,
    };
    onSaveTemplate(newTmpl);

    // Provide visual success feedback
    setSuccessMsg(`Добавлено в ${mealType}: ${name} (${numValue} ${unit})`);
    setTimeout(() => setSuccessMsg(null), 3500);

    // Reset fields except weight
    setName("");
    setKcal("");
    setProtein("");
    setFat("");
    setCarb("");
  };

  // Live calculation values for live portion preview card
  const portionValue = parseFloat(weight) || (unit === "г" ? 100 : 1);
  const bAmt = customBase ? (parseFloat(baseAmount) || 100) : (unit === "г" ? 100 : 1);
  const bUnit = customBase ? baseUnit : (unit === "г" ? "г" : unit);

  const factor = (() => {
    const loggedAmt = portionValue;
    const loggedU = unit;
    if (loggedU === bUnit) {
      return loggedAmt / (bAmt || 1);
    }
    const loggedWeight = UNIT_WEIGHTS[loggedU] || 1;
    const baseWeight = UNIT_WEIGHTS[bUnit] || 100;
    
    return (loggedAmt * loggedWeight) / ((bAmt * baseWeight) || 1);
  })();

  const liveKcal = Math.round((parseFloat(kcal) || 0) * factor);
  const liveProtein = Math.round((parseFloat(protein) || 0) * factor * 10) / 10;
  const liveFat = Math.round((parseFloat(fat) || 0) * factor * 10) / 10;
  const liveCarb = Math.round((parseFloat(carb) || 0) * factor * 10) / 10;

  // Render top 10 most popular template pills for simple usage
  const quickPills = templates.slice(0, 10);

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-white/60 dark:bg-slate-900/40 backdrop-blur-xl border border-white/80 dark:border-slate-800/60 p-6 sm:p-8 rounded-3xl shadow-xl shadow-emerald-900/5 mb-6 add-food-form transition-colors duration-300"
    >
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div className="p-2 bg-emerald-500 text-white rounded-xl shadow-md shadow-emerald-200/30">
            <Utensils size={18} />
          </div>
          <h3 className="text-lg font-bold text-slate-800 dark:text-slate-200 font-display form-title">
            Добавить блюдо
          </h3>
        </div>
        <span className="text-[10px] uppercase font-bold text-emerald-700 dark:text-emerald-300 bg-emerald-100/60 dark:bg-emerald-950/40 px-2.5 py-1 rounded-md border border-emerald-200/40 dark:border-emerald-900/40">
          Умный расчёт
        </span>
      </div>

      {error && (
        <div className="mb-4 p-3 bg-red-500/10 border border-red-500/20 text-red-700 rounded-xl text-xs font-semibold animate-fade-in flex items-center gap-1.5">
          <span>⚠️ {error}</span>
        </div>
      )}

      {successMsg && (
        <div className="mb-4 p-3 bg-emerald-500/10 border border-emerald-500/20 text-emerald-800 rounded-xl text-xs font-semibold animate-fade-in flex items-center gap-1.5 justify-between">
          <span className="flex items-center gap-1">
            <Check size={14} className="text-emerald-600" />
            {successMsg}
          </span>
          <button type="button" onClick={() => setSuccessMsg(null)} className="text-[10px] text-emerald-600 font-bold hover:underline">
            ОК
          </button>
        </div>
      )}

      <div className="space-y-4">
        {/* Row: Meal Type Selection */}
        <div className="form-group flex flex-col">
          <label className="text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase mb-1.5 block tracking-wider">
            Прием пищи
          </label>
          <select
            id="meal-type"
            value={mealType}
            onChange={(e) => setMealType(e.target.value as MealType)}
            className="w-full h-11 px-4 bg-white/70 dark:bg-slate-800/60 border border-slate-200/60 dark:border-slate-700/60 rounded-xl text-sm font-semibold text-slate-700 dark:text-slate-200 focus:outline-hidden focus:ring-2 focus:ring-emerald-400 focus:border-emerald-400 transition-all cursor-pointer outline-hidden appearance-none"
          >
            <option value="breakfast">Завтрак</option>
            <option value="lunch">Обед</option>
            <option value="dinner">Ужин</option>
            <option value="snack">Перекус</option>
          </select>
        </div>

        {/* Product Templates / Frequency Pills */}
        {quickPills.length > 0 && (
          <div className="flex flex-col gap-1.5">
            <span className="text-[10px] font-bold text-indigo-700 dark:text-indigo-400 uppercase tracking-wider flex items-center gap-1">
              <Bookmark size={10} className="fill-indigo-100 dark:fill-indigo-950/40" />
              История шаблонов (нажмите для выбора):
            </span>
            <div className="flex flex-wrap gap-1.5 max-h-24 overflow-y-auto pt-0.5 pb-2">
              {templates.slice(0, 10).map((tmpl) => {
                const bAmtStr = tmpl.baseAmount && tmpl.baseAmount !== 100 ? `${tmpl.baseAmount}` : "";
                const bUnitStr = tmpl.baseUnit && tmpl.baseUnit !== "г" ? tmpl.baseUnit : bAmtStr ? "г" : "100г";
                const labelText = bAmtStr ? `на ${bAmtStr}${bUnitStr}` : `на ${bUnitStr}`;
                
                return (
                  <div
                    key={tmpl.id}
                    onClick={() => handleSelectTemplate(tmpl)}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white/80 dark:bg-slate-800/50 hover:bg-emerald-500 hover:text-white hover:border-emerald-400 text-slate-700 dark:text-slate-300 border border-slate-200/70 dark:border-slate-700/60 text-xs font-semibold rounded-full cursor-pointer transition-all active:scale-95 group shadow-2xs"
                    title={`${tmpl.name} (${tmpl.kcal} ккал ${labelText}) - нажмите для автозаполнения`}
                  >
                    <span>{tmpl.name}</span>
                    <span className="text-[9px] opacity-60 font-mono">({tmpl.kcal} / {bAmtStr || "100"}{bUnitStr})</span>
                    {
                      // Allow deleting custom (non-seeded) templates
                      !["tmpl-1", "tmpl-2", "tmpl-3", "tmpl-4", "tmpl-5", "tmpl-6"].includes(tmpl.id) && (
                        <button
                          type="button"
                          onClick={(e) => handleDeleteTemplate(e, tmpl.id)}
                          className="text-slate-400 hover:text-red-300 ml-1 p-0.5 rounded-full hover:bg-slate-100/20"
                          title="Удалить шаблон"
                        >
                          ×
                        </button>
                      )
                    }
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {/* Food Name Input */}
        <div className="form-group flex flex-col">
          <label className="text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase mb-1.5 block tracking-wider">
            Название блюда / продукта
          </label>
          <div className="relative">
            <input
              id="food-name"
              type="text"
              value={name}
              onChange={(e) => {
                setName(e.target.value);
                if (error) setError(null);
              }}
              placeholder="Введите название (например, Рис отварной)"
              className="w-full h-11 px-4 bg-white/70 dark:bg-slate-800/60 border border-slate-200/60 dark:border-slate-700/60 rounded-xl text-sm font-semibold text-slate-800 dark:text-slate-200 placeholder-slate-400 dark:placeholder-slate-500 focus:outline-hidden focus:ring-2 focus:ring-emerald-400 focus:border-emerald-400 transition-all outline-hidden"
              required
            />
          </div>
        </div>

        {/* Unit Selection Segments - Supporting 6 units requested by user */}
        <div className="form-group flex flex-col">
          <label className="text-[11px] font-bold text-slate-500 dark:text-slate-400 uppercase mb-1.5 block tracking-wider">
            Мера съеденного
          </label>
          <div className="grid grid-cols-3 gap-2">
            {[
              { id: "г", label: "Граммы", placeholder: "100" },
              { id: "шт", label: "Штуки", placeholder: "1" },
              { id: "ст. л.", label: "Столовые ложки", placeholder: "1" },
              { id: "ч. л.", label: "Чайные ложки", placeholder: "1" },
              { id: "стакан", label: "Стаканы", placeholder: "1" },
              { id: "порц", label: "Порции", placeholder: "1" }
            ].map((opt) => (
              <button
                key={opt.id}
                type="button"
                onClick={() => {
                  setUnit(opt.id);
                  setWeight(opt.placeholder);
                  setError(null);
                }}
                className={`py-2 px-1 text-[10px] sm:text-xs font-extrabold rounded-xl border transition-all cursor-pointer ${
                  unit === opt.id
                    ? "bg-emerald-500 text-white border-emerald-400 shadow-sm font-black"
                    : "bg-white/70 dark:bg-slate-800/40 hover:bg-white dark:hover:bg-slate-800/60 text-slate-700 dark:text-slate-300 border-slate-200/60 dark:border-slate-700/60"
                }`}
              >
                {opt.label} ({opt.id})
              </button>
            ))}
          </div>
        </div>

        {/* Central input for quantity/weight eaten */}
        <div className="form-group flex flex-col p-3.5 bg-emerald-500/5 dark:bg-emerald-950/10 border border-emerald-500/10 dark:border-emerald-700/20 rounded-2xl">
          <div className="flex items-center justify-between mb-1.5">
            <label className="text-[11px] font-extrabold text-emerald-800 dark:text-emerald-400 uppercase tracking-wider flex items-center gap-1">
              <Scale size={12} className="text-emerald-600" />
              Кол-во или масса съеденного
            </label>
            <span className="text-[10px] text-emerald-700 dark:text-emerald-300 font-bold">Порция: {portionValue} {unit}</span>
          </div>
          <input
            id="food-weight"
            type="number"
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
            placeholder={unit === "г" ? "100" : "1"}
            min="0.1"
            step="any"
            className="w-full h-11 px-4 bg-white/80 dark:bg-slate-800/70 border border-emerald-500/10 dark:border-emerald-700/25 rounded-xl text-sm font-extrabold text-emerald-900 dark:text-emerald-100 focus:outline-hidden focus:ring-2 focus:ring-emerald-400 focus:border-emerald-400 transition-all outline-hidden"
            required
          />
          <p className="text-[9px] text-emerald-600/80 mt-1.5 font-medium leading-relaxed">
            * Укажите съеденное количество в {unit}. Рассчитанный вес: {unit === "г" ? `${portionValue} г` : `≈ ${portionValue * (UNIT_WEIGHTS[unit] || 50)} г`}
          </p>
        </div>

        {/* CUSTOM PORTION BASIS SWITCH (Allows specifying KBJU on arbitrary amount e.g. 50g, 1 piece, etc.) */}
        <div className="p-3.5 bg-slate-100/60 dark:bg-slate-800/20 border border-slate-200/50 dark:border-slate-700/50 rounded-2xl flex flex-col gap-3">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-black uppercase text-slate-500 dark:text-slate-400 tracking-wider">
              КБЖУ указаны не на 100 грамм?
            </span>
            <button
              type="button"
              onClick={() => {
                setCustomBase(!customBase);
                if (!customBase) {
                  setBaseAmount(unit === "г" ? "100" : "1");
                  setBaseUnit(unit);
                }
              }}
              className={`py-1 px-2.5 text-[9px] font-bold rounded-md transition-all cursor-pointer border ${
                customBase
                  ? "bg-indigo-505 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300 border-indigo-200/60 dark:border-indigo-800/40"
                  : "bg-white dark:bg-slate-700 hover:bg-slate-150 text-slate-600 dark:text-slate-400 border-slate-200/60"
              }`}
            >
              {customBase ? "Своя мера: ВКЛ" : "Стандартные 100г / 1шт"}
            </button>
          </div>

          {customBase && (
            <div className="grid grid-cols-2 gap-3 p-3 bg-white/50 dark:bg-slate-900/60 rounded-xl border border-dashed border-slate-200 dark:border-slate-800/80 animate-fade-in">
              <div className="flex flex-col">
                <label className="text-[9px] uppercase font-bold text-slate-400 mb-1">
                  Какое сырье/вес в упаковке
                </label>
                <input
                  type="number"
                  value={baseAmount}
                  onChange={(e) => setBaseAmount(e.target.value)}
                  placeholder="100"
                  min="0.1"
                  step="any"
                  className="h-10 px-3 bg-white dark:bg-slate-800 rounded-xl text-xs font-bold border border-slate-200 dark:border-slate-700"
                />
              </div>
              <div className="flex flex-col">
                <label className="text-[9px] uppercase font-bold text-slate-400 mb-1">
                  Мера этой базы КБЖУ
                </label>
                <select
                  value={baseUnit}
                  onChange={(e) => setBaseUnit(e.target.value)}
                  className="h-10 px-2 bg-white dark:bg-slate-800 rounded-xl text-xs font-bold border border-slate-200 dark:border-slate-700 cursor-pointer outline-hidden"
                >
                  <option value="г">г (Граммы)</option>
                  <option value="шт">шт (Штука)</option>
                  <option value="ст. л.">ст. л. (Стол. ложка)</option>
                  <option value="ч. л.">ч. л. (Чайная ложка)</option>
                  <option value="стакан">стакан (Стакан)</option>
                  <option value="порц">порц (Порция)</option>
                </select>
              </div>
            </div>
          )}
        </div>

        {/* KBJU Grid Inputs */}
        <div>
          <span className="text-[10px] font-bold text-slate-500 dark:text-slate-400 uppercase tracking-wider block mb-2.5">
            Характеристики продукта ({customBase ? `на ${baseAmount} ${baseUnit}` : (unit === "г" ? "на 100 грамм" : `на 1 ${unit}`)}):
          </span>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 form-row-4">
            <div className="form-group block">
              <label className="text-[10px] font-bold text-slate-400 dark:text-slate-500 mb-1 block tracking-tight">
                Ккал
              </label>
              <input
                id="food-kcal"
                type="number"
                value={kcal}
                onChange={(e) => setKcal(e.target.value)}
                placeholder="0"
                min="0"
                className="w-full h-11 px-3 bg-white/50 dark:bg-slate-800/40 border border-slate-200/50 dark:border-slate-700/60 rounded-xl text-sm font-bold text-slate-750 dark:text-slate-200 focus:outline-hidden focus:ring-1 focus:ring-emerald-400 outline-hidden"
              />
            </div>

            <div className="form-group block">
              <label className="text-[10px] font-bold text-slate-400 dark:text-slate-500 mb-1 block tracking-tight">
                Белки (г)
              </label>
              <input
                id="food-protein"
                type="number"
                value={protein}
                onChange={(e) => setProtein(e.target.value)}
                placeholder="0"
                min="0"
                className="w-full h-11 px-3 bg-white/50 dark:bg-slate-800/40 border border-slate-200/50 dark:border-slate-700/60 rounded-xl text-sm font-bold text-slate-750 dark:text-slate-200 focus:outline-hidden focus:ring-1 focus:ring-emerald-400 outline-hidden"
              />
            </div>

            <div className="form-group block">
              <label className="text-[10px] font-bold text-slate-400 dark:text-slate-500 mb-1 block tracking-tight">
                Жиры (г)
              </label>
              <input
                id="food-fat"
                type="number"
                value={fat}
                onChange={(e) => setFat(e.target.value)}
                placeholder="0"
                min="0"
                className="w-full h-11 px-3 bg-white/50 dark:bg-slate-800/40 border border-slate-200/50 dark:border-slate-700/60 rounded-xl text-sm font-bold text-slate-750 dark:text-slate-200 focus:outline-hidden focus:ring-1 focus:ring-emerald-400 outline-hidden"
              />
            </div>

            <div className="form-group block">
              <label className="text-[10px] font-bold text-slate-400 dark:text-slate-500 mb-1 block tracking-tight">
                Углеводы (г)
              </label>
              <input
                id="food-carb"
                type="number"
                value={carb}
                onChange={(e) => setCarb(e.target.value)}
                placeholder="0"
                min="0"
                className="w-full h-11 px-3 bg-white/50 dark:bg-slate-800/40 border border-slate-200/50 dark:border-slate-700/60 rounded-xl text-sm font-bold text-slate-750 dark:text-slate-200 focus:outline-hidden focus:ring-1 focus:ring-emerald-400 outline-hidden"
              />
            </div>
          </div>
        </div>

        {/* Interactive Math Preview Card */}
        {(name || kcal || protein || fat || carb) && (
          <div className="p-3.5 bg-indigo-500/5 dark:bg-indigo-950/20 rounded-2xl border border-indigo-500/10 dark:border-indigo-800/30 text-indigo-950/80 dark:text-indigo-300 text-xs font-semibold animate-fade-in flex flex-col justify-between items-start gap-2.5 mt-4 shadow-2xs">
            <div className="flex items-center gap-1.5 flex-wrap">
              <Flame size={14} className="text-indigo-500 dark:text-indigo-400 shrink-0" />
              <span>Формула перевода порции:</span>
              <span className="text-slate-800 dark:text-slate-200 underline font-extrabold">{name || "Блюдо"}</span>
            </div>
            
            <div className="flex flex-col sm:flex-row items-center w-full justify-between gap-1.5 pt-1.5 border-t border-dashed border-indigo-500/10 dark:border-indigo-950/20 text-[11px]">
              <div className="text-slate-500 dark:text-slate-400 font-medium flex items-center gap-1">
                <span>Масштаб: {portionValue} {unit}</span>
                <ArrowRight size={10} />
                <span>на {bAmt} {bUnit} (Кэф: {factor.toFixed(2)})</span>
              </div>
              <div className="font-extrabold text-indigo-700 dark:text-indigo-300 font-display">
                {liveKcal} ккал | Б: {liveProtein}г | Ж: {liveFat}г | У: {liveCarb}г
              </div>
            </div>
          </div>
        )}

        {/* Dynamic submit button */}
        <button
          id="add-btn"
          type="submit"
          className="w-full py-4 bg-emerald-500 hover:bg-emerald-600 text-white font-bold rounded-2xl shadow-lg shadow-emerald-200/30 transition-all hover:-translate-y-0.5 active:translate-y-0 cursor-pointer text-sm tracking-wide mt-4"
        >
          Добавить в меню
        </button>
      </div>
    </form>
  );
}
