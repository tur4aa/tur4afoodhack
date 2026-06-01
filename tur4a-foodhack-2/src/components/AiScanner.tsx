import React, { useState, useRef } from "react";
import { Camera, Image, Wand2, Sparkles, Plus, Check, Loader2, RefreshCw, HelpCircle, FileText, Bookmark } from "lucide-react";
import { MealType, FoodItem, FoodTemplate } from "../types";

interface SuggestedFoodItem {
  name: string;
  kcal: number;
  protein: number;
  fat: number;
  carb: number;
  weight: number;
  mealType: MealType;
}

interface AiScannerProps {
  selectedDate: string;
  onAddFood: (
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
  templates: FoodTemplate[];
  onSaveTemplate: (template: FoodTemplate) => void;
}

const PLANNER_PRESETS = [
  "Как поделить 5 кг курицы на 3 недели? Сколько есть в день в граммах и КБЖУ?",
  "Проанализировать БЖУ продукта по фото упаковки",
  "Спланировать дневной рацион под сушку/похудение из этих ingredients",
];

const SCANNER_PRESETS = [
  "Распознать БЖУ готового блюда на тарелке по фотографии",
  "Разобрать салат с креветками и авокадо на ингредиенты и рассчитать КБЖУ",
  "Оценить КБЖУ порции запеченной рыбы с пюре по фото",
];

const LABEL_PRESETS = [
  "Распознать БЖУ протеинового батончика с этикетки и сохранить в базу",
  "Считать питательную ценность пачки творога по фото КБЖУ таблицы",
  "Внести КБЖУ печенья без сахара с фотографии состава продуктов",
];

export default function AiScanner({ selectedDate, onAddFood, templates, onSaveTemplate }: AiScannerProps) {
  const [mode, setMode] = useState<"dish_scanner" | "label_scanner" | "planner">("dish_scanner");
  const [imageBase64, setImageBase64] = useState<string | null>(null);
  const [mimeType, setMimeType] = useState<string>("");
  const [customGoal, setCustomGoal] = useState<string>(SCANNER_PRESETS[0]);
  const [dailyKcal, setDailyKcal] = useState<string>("2000");
  
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<{
    advice: string;
    suggestedFoods: SuggestedFoodItem[];
  } | null>(null);

  const [addedIndices, setAddedIndices] = useState<Record<number, boolean>>({});
  const [savedTemplateIndices, setSavedTemplateIndices] = useState<Record<number, boolean>>({});
  const fileInputRef = useRef<HTMLInputElement>(null);

  // File picker handler
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    processFile(file);
  };

  const processFile = (file: File) => {
    if (!file.type.startsWith("image/")) {
      setError("Пожалуйста, загрузите файл-изображение (PNG, JPEG, WebP)");
      return;
    }

    setMimeType(file.type);
    const reader = new FileReader();
    reader.onload = () => {
      if (typeof reader.result === "string") {
        const base64Content = reader.result.split(",")[1];
        setImageBase64(base64Content);
        setError(null);
      }
    };
    reader.onerror = () => {
      setError("Не удалось прочитать загруженный файл");
    };
    reader.readAsDataURL(file);
  };

  // Drag-and-drop mechanics
  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const file = e.dataTransfer.files?.[0];
    if (file) {
      processFile(file);
    }
  };

  // Run AI analysis
  const handleAnalyze = async () => {
    setLoading(true);
    setError(null);
    setAddedIndices({});
    
    try {
      const res = await fetch("/api/gemini/analyze-photo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          imageBase64,
          mimeType,
          customGoal: customGoal.trim(),
          dailyKcalTarget: parseFloat(dailyKcal) || 2000,
          mode,
        }),
      });

      if (!res.ok) {
        throw new Error(`Код ответа: ${res.status}`);
      }

      const data = await res.json();
      if (data.success) {
        setResponse({
          advice: data.advice,
          suggestedFoods: data.suggestedFoods || [],
        });
      } else {
        setError(data.error || "Не удалось завершить распознавание.");
      }
    } catch (e: any) {
      console.error(e);
      setError(`Ошибка связи с ИИ-сервером: ${e.message || "Пожалуйста, попробуйте позже"}`);
    } finally {
      setLoading(false);
    }
  };

  // Reset analysis states
  const handleReset = () => {
    setImageBase64(null);
    setMimeType("");
    setResponse(null);
    setError(null);
    setAddedIndices({});
    setSavedTemplateIndices({});
  };

  // Load suggest item to diary
  const handleAddSuggested = (item: SuggestedFoodItem, index: number) => {
    onAddFood(
      item.mealType,
      item.name,
      item.kcal,
      item.protein,
      item.fat,
      item.carb,
      item.weight
    );
    setAddedIndices(prev => ({ ...prev, [index]: true }));
  };

  // Save product from suggested item into lifetime Templates
  const handleSaveToTemplates = (item: SuggestedFoodItem, index: number) => {
    // Check if duplicate already exists on templates list
    const exists = templates.some(t => t.name.toLowerCase() === item.name.trim().toLowerCase());
    if (exists) {
      setSavedTemplateIndices(prev => ({ ...prev, [index]: true }));
      return;
    }

    const newTmpl: FoodTemplate = {
      id: `tmpl-${Date.now()}-${Math.random()}`,
      name: item.name.trim(),
      kcal: item.kcal,
      protein: item.protein,
      fat: item.fat,
      carb: item.carb,
      usageCount: 1,
    };

    onSaveTemplate(newTmpl);
    setSavedTemplateIndices(prev => ({ ...prev, [index]: true }));
  };

  // Highlight bold sections and code blocks inside custom markdown
  const renderMarkdown = (text: string) => {
    if (!text) return null;
    return text.split("\n").map((line, i) => {
      if (line.startsWith("#### ")) {
        return <h5 key={i} className="text-xs font-bold text-slate-800 mt-3 mb-1 uppercase tracking-wider">{line.replace("#### ", "")}</h5>;
      }
      if (line.startsWith("### ")) {
        return <h4 key={i} className="text-sm font-black text-slate-800 mt-4 mb-2 uppercase tracking-wide flex items-center gap-1.5 border-b border-slate-200/40 pb-1.5">{line.replace("### ", "")}</h4>;
      }
      if (line.startsWith("## ")) {
        return <h3 key={i} className="text-base font-black text-slate-900 mt-5 mb-2.5 uppercase tracking-wide border-b border-slate-200/80 pb-2">{line.replace("## ", "")}</h3>;
      }
      if (line.startsWith("- ") || line.startsWith("* ")) {
        const parsed = line.replace(/^[-*]\s+/, "");
        return (
          <li key={i} className="text-xs text-slate-700 leading-relaxed font-semibold ml-4 list-disc marker:text-emerald-500 mb-1">
            {parseBold(parsed)}
          </li>
        );
      }
      if (line.trim() === "") return <div key={i} className="h-2" />;
      return <p key={i} className="text-xs sm:text-sm text-slate-700 font-semibold leading-relaxed mb-2">{parseBold(line)}</p>;
    });
  };

  const parseBold = (text: string) => {
    const parts = text.split(/(\*\*.*?\*\*|`.*?`)/g);
    return parts.map((part, index) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={index} className="font-black text-emerald-950 bg-emerald-500/10 px-1 rounded-md">{part.slice(2, -2)}</strong>;
      }
      if (part.startsWith("`") && part.endsWith("`")) {
        return <code key={index} className="font-mono text-[10px] text-indigo-700 bg-indigo-50 border border-indigo-100 px-1.5 py-0.5 rounded-md font-bold">{part.slice(1, -1)}</code>;
      }
      return part;
    });
  };

  const activePresets = mode === "dish_scanner" 
    ? SCANNER_PRESETS 
    : mode === "label_scanner"
    ? LABEL_PRESETS
    : PLANNER_PRESETS;

  return (
    <div className="bg-white/40 backdrop-blur-xl border border-white/60 p-6 rounded-3xl shadow-xl shadow-emerald-900/5 flex flex-col gap-6">
      <div className="flex items-center justify-between border-b border-white/20 pb-4">
        <div className="flex items-center gap-2">
          <div className="p-2 bg-indigo-500 text-white rounded-xl shadow-lg shadow-indigo-200/30">
            <Wand2 size={18} />
          </div>
          <div>
            <h3 className="text-sm font-bold text-slate-800 font-display uppercase tracking-wide">
              ИИ-Анализатор & Порционер
            </h3>
            <p className="text-[10px] text-indigo-800 font-semibold tracking-wide">
              Распознавание по фото и расчет порций
            </p>
          </div>
        </div>
        <span className="text-[9px] font-black uppercase text-indigo-800 bg-indigo-100/70 px-2 py-0.5 rounded-md border border-indigo-200/20">
          Gemini-3.5
        </span>
      </div>

      {/* Sub-tabs segment for dish scanner / label scanner / portion planner */}
      <div className="grid grid-cols-3 gap-1 p-1 bg-slate-100/80 rounded-2xl border border-slate-200/40">
        <button
          type="button"
          onClick={() => {
            setMode("dish_scanner");
            setCustomGoal(SCANNER_PRESETS[0]);
            setResponse(null);
            setError(null);
          }}
          className={`py-2 px-1 text-[10px] sm:text-xs font-black rounded-xl transition-all cursor-pointer flex flex-col sm:flex-row items-center justify-center gap-1 leading-tight ${
            mode === "dish_scanner"
              ? "bg-indigo-500 text-white shadow-md shadow-indigo-200/30 animate-pulse"
              : "text-slate-600 hover:text-slate-800"
          }`}
        >
          <Camera size={13} />
          <span>Сканер Блюда</span>
        </button>
        <button
          type="button"
          onClick={() => {
            setMode("label_scanner");
            setCustomGoal(LABEL_PRESETS[0]);
            setResponse(null);
            setError(null);
          }}
          className={`py-2 px-1 text-[10px] sm:text-xs font-black rounded-xl transition-all cursor-pointer flex flex-col sm:flex-row items-center justify-center gap-1 leading-tight ${
            mode === "label_scanner"
              ? "bg-indigo-500 text-white shadow-md shadow-indigo-200/30 animate-pulse"
              : "text-slate-600 hover:text-slate-800"
          }`}
        >
          <FileText size={13} />
          <span>БЖУ Этикетки</span>
        </button>
        <button
          type="button"
          onClick={() => {
            setMode("planner");
            setCustomGoal(PLANNER_PRESETS[0]);
            setResponse(null);
            setError(null);
          }}
          className={`py-2 px-1 text-[10px] sm:text-xs font-black rounded-xl transition-all cursor-pointer flex flex-col sm:flex-row items-center justify-center gap-1 leading-tight ${
            mode === "planner"
              ? "bg-indigo-500 text-white shadow-md shadow-indigo-200/30 animate-pulse"
              : "text-slate-600 hover:text-slate-800"
          }`}
        >
          <Wand2 size={13} />
          <span>Планировать</span>
        </button>
      </div>

      {!response ? (
        <div className="flex flex-col gap-5">
          {/* Preset Chips */}
          <div className="flex flex-col gap-2">
            <span className="text-[10px] font-bold text-slate-500 uppercase tracking-wider block">
              Быстрые запросы / Предустановки целей:
            </span>
            <div className="flex flex-wrap gap-1.5">
              {activePresets.map((preset, index) => (
                <button
                  key={index}
                  type="button"
                  onClick={() => setCustomGoal(preset)}
                  className={`text-[10px] font-bold text-left px-3 py-1.5 rounded-xl border transition-all cursor-pointer ${
                    customGoal === preset
                      ? "bg-indigo-500 text-white border-indigo-400 shadow-xs"
                      : "bg-white/60 hover:bg-white text-slate-700 border-slate-200/60"
                  }`}
                >
                  {preset.length > 55 ? preset.substring(0, 52) + "..." : preset}
                </button>
              ))}
            </div>
          </div>

          {/* Goal Input form */}
          <div className="flex flex-col gap-4">
            <div className="form-group flex flex-col">
              <label className="text-[11px] font-bold text-slate-500 uppercase mb-1.5 tracking-wider">
                {mode === "dish_scanner" 
                  ? "Что вы хотите уточнить о блюде?" 
                  : mode === "label_scanner"
                  ? "Уточнение к этикетке (например, бренд или название)"
                  : "Ваша цель или вопрос к ИИ"}
              </label>
              <textarea
                value={customGoal}
                onChange={(e) => setCustomGoal(e.target.value)}
                placeholder={mode === "dish_scanner" 
                  ? "Например, Распознать готовую тарелку домашней еды и разделить на ингредиенты..." 
                  : mode === "label_scanner"
                  ? "Например, Расшифровать КБЖУ белкового батончика с фотографии упаковки и внести в Шаблоны..."
                  : "Например, посоветовать как поделить условно 5 кг курицы на 3 недели, сколько это будет в кбжу дневной нормы..."}
                rows={3}
                className="w-full p-3 bg-white/70 border border-slate-200/60 rounded-2xl text-xs font-semibold text-slate-700 placeholder-slate-400 focus:outline-hidden focus:ring-2 focus:ring-indigo-400 resize-none leading-relaxed"
              />
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="form-group flex flex-col">
                <label className="text-[11px] font-bold text-slate-500 uppercase mb-1.5 tracking-wider">
                  Дневная цель калорий (ккал)
                </label>
                <input
                  type="number"
                  value={dailyKcal}
                  onChange={(e) => setDailyKcal(e.target.value)}
                  placeholder="2000"
                  className="w-full h-11 px-4 bg-white/70 border border-slate-200/60 rounded-xl text-xs font-bold text-slate-700 focus:outline-hidden focus:ring-2 focus:ring-indigo-400"
                />
              </div>

              {/* Photo Upload Zone */}
              <div className="form-group flex flex-col">
                <label className="text-[11px] font-bold text-slate-500 uppercase mb-1.5 tracking-wider">
                  {mode === "dish_scanner" 
                    ? "Фото вашего блюда/еды" 
                    : mode === "label_scanner"
                    ? "Фото этикетки КБЖУ / упаковки"
                    : "Фото продуктов"}
                </label>
                <div
                  onDragOver={handleDragOver}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className="h-11 border border-dashed border-indigo-400/50 hover:border-indigo-500 bg-indigo-50/10 hover:bg-indigo-500/5 rounded-xl flex items-center justify-center gap-2 cursor-pointer transition-all active:scale-98"
                >
                  {imageBase64 ? (
                    <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-600 animate-pulse">
                      <Check size={14} />
                      <span>Фото готово ({mimeType.split("/")[1]})</span>
                    </div>
                  ) : (
                    <div className="flex items-center gap-1.5 text-xs font-bold text-indigo-600">
                      <Camera size={14} />
                      <span>Загрузить или снять</span>
                    </div>
                  )}
                  <input
                    type="file"
                    ref={fileInputRef}
                    onChange={handleFileChange}
                    accept="image/*"
                    className="hidden"
                    id="scanner-photo-input"
                  />
                </div>
              </div>
            </div>
          </div>

          {error && (
            <div className="p-3 bg-red-500/10 border border-red-500/20 text-red-700 text-xs font-semibold rounded-2xl animate-fade-in">
              ⚠️ {error}
            </div>
          )}

          {/* Trigger Analysis Button */}
          <button
            onClick={handleAnalyze}
            disabled={loading}
            className="w-full py-3.5 bg-indigo-500 hover:bg-indigo-600 disabled:bg-indigo-400 text-white font-extrabold rounded-2xl transition-all shadow-md active:scale-98 flex items-center justify-center gap-2 cursor-pointer text-xs uppercase tracking-wider"
          >
            {loading ? (
              <>
                <Loader2 size={16} className="animate-spin" />
                <span>
                  {mode === "dish_scanner" 
                    ? "Распознаем блюдо на фото..." 
                    : mode === "label_scanner"
                    ? "Считываем цифры с этикетки..."
                    : "Планируем порции..."}
                </span>
              </>
            ) : (
              <>
                <Sparkles size={16} className="text-yellow-300 animate-bounce" />
                <span>
                  {mode === "dish_scanner"
                    ? "Распознать блюдо и посчитать КБЖУ"
                    : mode === "label_scanner"
                    ? "Считать БЖУ с этикетки (в Шаблоны!)"
                    : "Рассчитать порции и БЖУ продукта"}
                </span>
              </>
            )}
          </button>
        </div>
      ) : (
        /* Response Analytical Panel */
        <div className="flex flex-col gap-6 animate-fade-in text-left">
          {/* Simulated Image Miniature inside analysis readout if provided */}
          {imageBase64 && (
            <div className="flex items-center gap-2.5 p-3 bg-slate-100/50 rounded-2xl border border-slate-200/20">
              <div className="w-12 h-12 rounded-xl bg-slate-300 overflow-hidden relative border border-slate-400/25 shrink-0">
                <img
                  src={`data:${mimeType};base64,${imageBase64}`}
                  alt="Scanned product screenshot"
                  className="w-full h-full object-cover"
                />
              </div>
              <div>
                <span className="text-[10px] text-slate-400 block font-bold uppercase tracking-wide">Анализируемое фото</span>
                <span className="text-xs font-extrabold text-slate-700 truncate block max-w-[200px]">
                  {customGoal}
                </span>
              </div>
            </div>
          )}

          {/* Structured Markdown Insights Block parsed natively */}
          <div className="bg-white/80 border border-white p-5 rounded-3xl shadow- inner max-h-[350px] overflow-y-auto custom-scroll">
            <div className="prose prose-sm prose-slate font-sans">
              {renderMarkdown(response.advice)}
            </div>
          </div>

          {/* Suggested Food Items to Add to Menu Panel */}
          {response.suggestedFoods.length > 0 && (
            <div className="flex flex-col gap-3">
              <span className="text-[10px] font-black text-indigo-800 uppercase tracking-wider block">
                📋 Сгенерированные порции (кликните, чтобы внести в меню):
              </span>
              <div className="space-y-2.5">
                {response.suggestedFoods.map((item, idx) => (
                  <div
                    key={idx}
                    className="p-3 bg-indigo-50/50 border border-indigo-200/40 rounded-2xl flex items-center justify-between gap-3 shadow-2xs hover:border-indigo-300/60 transition-all"
                  >
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-bold text-slate-800 flex items-center gap-1.5 flex-wrap">
                        <span className="truncate">{item.name}</span>
                        <span className="text-[9px] font-black text-indigo-800 bg-indigo-500/15 px-1.5 py-0.5 rounded-md">
                          {item.weight}г
                        </span>
                        <span className="text-[9px] font-black text-amber-800 bg-amber-500/15 px-1.5 py-0.5 rounded-md tracking-wider">
                          {item.mealType.toUpperCase()}
                        </span>
                      </div>
                      <div className="text-[10px] text-slate-500 font-semibold mt-1">
                        Б: <span className="text-blue-600">{item.protein}г</span> | Ж: <span className="text-orange-600">{item.fat}г</span> | У: <span className="text-emerald-600">{item.carb}г</span> | <span className="font-extrabold text-slate-600">{item.kcal} ккал</span>
                      </div>
                    </div>
                    
                    <div className="flex flex-col sm:flex-row gap-1.5 shrink-0 items-stretch sm:items-center">
                      <button
                        type="button"
                        disabled={savedTemplateIndices[idx]}
                        onClick={() => handleSaveToTemplates(item, idx)}
                        className={`px-3 py-2 rounded-xl text-[10px] font-extrabold uppercase tracking-wide cursor-pointer select-none transition-all flex items-center justify-center gap-1.5 active:scale-95 ${
                          savedTemplateIndices[idx]
                            ? "bg-emerald-600 text-white border border-emerald-500 shadow-sm"
                            : "bg-white border border-indigo-200 text-indigo-700 hover:bg-indigo-50 hover:border-indigo-300"
                        }`}
                        title="Добавить этот продукт в вашу постоянную базу шаблонов"
                      >
                        {savedTemplateIndices[idx] ? (
                          <>
                            <Check size={12} strokeWidth={3} />
                            <span>В базе!</span>
                          </>
                        ) : (
                          <>
                            <Bookmark size={12} strokeWidth={2} />
                            <span>В базу 💾</span>
                          </>
                        )}
                      </button>

                      <button
                        type="button"
                        disabled={addedIndices[idx]}
                        onClick={() => handleAddSuggested(item, idx)}
                        className={`px-3 py-2 rounded-xl text-[10px] font-extrabold uppercase tracking-wide cursor-pointer select-none transition-all flex items-center justify-center gap-1 active:scale-95 ${
                          addedIndices[idx]
                            ? "bg-emerald-500 text-white"
                            : "bg-indigo-500 hover:bg-indigo-600 text-white hover:shadow-sm"
                        }`}
                      >
                        {addedIndices[idx] ? (
                          <>
                            <Check size={12} strokeWidth={3} />
                            <span>Внесено</span>
                          </>
                        ) : (
                          <>
                            <Plus size={12} strokeWidth={3} />
                            <span>В дневник</span>
                          </>
                        )}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Reset / New Analysis controls */}
          <div className="flex items-center gap-2">
            <button
              onClick={handleReset}
              className="px-4 py-2.5 bg-white border border-slate-200 hover:bg-slate-50 text-slate-600 text-[10px] font-black uppercase tracking-wider rounded-xl transition-all flex items-center gap-1.5 cursor-pointer"
            >
              <RefreshCw size={12} />
              Новый расчет / Вопрос
            </button>
            <span className="text-[10px] font-bold text-slate-400">
              * Все добавленные продукты улетят в дневник на текущую дату
            </span>
          </div>
        </div>
      )}
    </div>
  );
}
