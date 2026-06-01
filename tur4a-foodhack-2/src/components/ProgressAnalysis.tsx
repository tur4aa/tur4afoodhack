import React, { useState } from "react";
import { TrendingUp, BarChart, Calendar, Award, CheckCircle2, ChevronRight, Activity } from "lucide-react";
import { DiaryData, UserGoals, DayData } from "../types";

interface ProgressAnalysisProps {
  historyData: DiaryData;
  goals: UserGoals;
}

export default function ProgressAnalysis({ historyData, goals }: ProgressAnalysisProps) {
  const [range, setRange] = useState<"week" | "month" | "three_months">("week");
  const [hoveredDay, setHoveredDay] = useState<{ date: string; kcal: number; protein: number; fat: number; carb: number } | null>(null);

  // Helper to format Date objects to YYYY-MM-DD local format
  const getFormatDate = (date: Date): string => {
    const y = date.getFullYear();
    const m = String(date.getMonth() + 1).padStart(2, "0");
    const d = String(date.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  };

  // Helper to get beautiful Russian day/month labels
  const getLabelDate = (dateStr: string, includeYear = false): string => {
    try {
      const d = new Date(dateStr);
      if (isNaN(d.getTime())) return dateStr;
      if (range === "week") {
        return d.toLocaleDateString("ru-RU", { weekday: "short", day: "numeric" });
      }
      return d.toLocaleDateString("ru-RU", { day: "numeric", month: "short" });
    } catch {
      return dateStr;
    }
  };

  // 1. Gather N days timeline list (consecutive backwards from today)
  const getTimelineDaysCount = () => {
    if (range === "week") return 7;
    if (range === "month") return 30;
    return 90;
  };

  const daysCount = getTimelineDaysCount();
  const timelineData = Array.from({ length: daysCount }).map((_, idx) => {
    const d = new Date();
    d.setDate(d.getDate() - (daysCount - 1 - idx)); // oldest to newest (left to right)
    const dateStr = getFormatDate(d);
    
    // Sum breakfast + lunch + dinner + snack
    let dailyKcal = 0;
    let dailyProtein = 0;
    let dailyFat = 0;
    let dailyCarb = 0;
    let hasLogged = false;

    const dayEntry = historyData[dateStr];
    if (dayEntry) {
      hasLogged = true;
      const meals: ("breakfast" | "lunch" | "dinner" | "snack")[] = ["breakfast", "lunch", "dinner", "snack"];
      meals.forEach((meal) => {
        const list = dayEntry[meal] || [];
        list.forEach((item) => {
          dailyKcal += item.kcal || 0;
          dailyProtein += item.protein || 0;
          dailyFat += item.fat || 0;
          dailyCarb += item.carb || 0;
        });
      });
    }

    return {
      date: dateStr,
      label: getLabelDate(dateStr),
      kcal: Math.round(dailyKcal),
      protein: Math.round(dailyProtein),
      fat: Math.round(dailyFat),
      carb: Math.round(dailyCarb),
      hasLogged,
    };
  });

  // 2. Metrics Calculations
  const loggedDays = timelineData.filter((d) => d.hasLogged || d.kcal > 0);
  const totalLoggedKcal = loggedDays.reduce((acc, d) => acc + d.kcal, 0);
  const avgKcal = loggedDays.length > 0 ? Math.round(totalLoggedKcal / loggedDays.length) : 0;

  const avgProtein = loggedDays.length > 0 ? Math.round(loggedDays.reduce((acc, d) => acc + d.protein, 0) / loggedDays.length) : 0;
  const avgFat = loggedDays.length > 0 ? Math.round(loggedDays.reduce((acc, d) => acc + d.fat, 0) / loggedDays.length) : 0;
  const avgCarb = loggedDays.length > 0 ? Math.round(loggedDays.reduce((acc, d) => acc + d.carb, 0) / loggedDays.length) : 0;

  // Days within user limit accuracy (within ±15% of goals.kcal OR below if losing target)
  const targetKcal = goals.kcal;
  const adherenceDays = loggedDays.filter((d) => {
    const diff = Math.abs(d.kcal - targetKcal);
    // Adhered if within 15% of calorie goals
    return diff <= targetKcal * 0.15;
  });

  const adherencePercent = loggedDays.length > 0 
    ? Math.round((adherenceDays.length / loggedDays.length) * 100) 
    : 0;

  // 3. SVG Chart Variables Config
  const chartHeight = 180;
  const chartWidth = 500;
  const paddingLeft = 40;
  const paddingRight = 15;
  const paddingTop = 20;
  const paddingBottom = 30;

  const maxCalVal = Math.max(
    ...timelineData.map((d) => d.kcal),
    targetKcal,
    1500
  );

  const getX = (index: number) => {
    const usableWidth = chartWidth - paddingLeft - paddingRight;
    const spacing = timelineData.length > 1 ? usableWidth / (timelineData.length - 1) : usableWidth;
    return paddingLeft + index * spacing;
  };

  const getY = (kcalVal: number) => {
    const usableHeight = chartHeight - paddingTop - paddingBottom;
    const ratio = kcalVal / maxCalVal;
    return chartHeight - paddingBottom - ratio * usableHeight;
  };

  const targetLineY = getY(targetKcal);

  // Generate SVG Path for Calorie intake line
  const linePoints = timelineData.map((d, idx) => `${getX(idx)},${getY(d.kcal)}`).join(" ");

  return (
    <div className="bg-white/60 dark:bg-slate-900/40 backdrop-blur-xl border border-white/80 dark:border-slate-800/60 p-6 sm:p-8 rounded-3xl shadow-xl shadow-emerald-900/5 transition-colors duration-300 w-full flex flex-col gap-6">
      
      {/* Header and Filter */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-slate-200/50 dark:border-slate-800/40 pb-5">
        <div className="flex items-center gap-2">
          <div className="p-2 bg-emerald-500 text-white rounded-xl shadow-md shadow-emerald-200/30">
            <TrendingUp size={18} />
          </div>
          <div>
            <h3 className="text-lg font-bold text-slate-800 dark:text-slate-200 font-display">
              Анализ прогресса
            </h3>
            <span className="text-[10px] font-black uppercase text-emerald-700 dark:text-emerald-400 mt-1 block tracking-wider">
              Динамика питания
            </span>
          </div>
        </div>

        {/* Range Selector */}
        <div className="flex bg-slate-100/70 dark:bg-slate-800/50 p-1.5 rounded-2xl gap-1 border border-slate-200/40 dark:border-slate-700/40 select-none">
          {[
            { id: "week", label: "Неделя" },
            { id: "month", label: "Месяц" },
            { id: "three_months", label: "3 Месяца" }
          ].map((r) => (
            <button
              key={r.id}
              onClick={() => {
                setRange(r.id as any);
                setHoveredDay(null);
              }}
              className={`py-1.5 px-3.5 text-xs font-black rounded-xl transition-all cursor-pointer ${
                range === r.id
                  ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm"
                  : "text-slate-500 hover:text-slate-800 dark:text-slate-400 dark:hover:text-slate-200"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {/* Numerical Analysis / Stats Bento Widgets */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        
        {/* Metric 1 */}
        <div className="bg-white/40 dark:bg-slate-900/40 backdrop-blur-xs p-4 rounded-2xl border border-white/60 dark:border-slate-800/35 flex flex-col">
          <span className="text-[9px] font-black uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Ср. калории
          </span>
          <span className="text-xl font-extrabold text-slate-800 dark:text-slate-100 font-display mt-1">
            {avgKcal.toLocaleString()}
          </span>
          <span className="text-[9px] font-bold text-slate-500 dark:text-slate-400 mt-0.5">
            из {targetKcal} ккал
          </span>
        </div>

        {/* Metric 2 */}
        <div className="bg-white/40 dark:bg-slate-900/40 backdrop-blur-xs p-4 rounded-2xl border border-white/60 dark:border-slate-800/35 flex flex-col">
          <span className="text-[9px] font-black uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Точность цели
          </span>
          <span className="text-xl font-extrabold text-indigo-600 dark:text-indigo-400 font-display mt-1">
            {adherencePercent}%
          </span>
          <span className="text-[9px] font-bold text-slate-500 dark:text-slate-400 mt-0.5">
            {adherenceDays.length} из {loggedDays.length || 1} дней в зоне
          </span>
        </div>

        {/* Metric 3 */}
        <div className="bg-white/40 dark:bg-slate-900/40 backdrop-blur-xs p-4 rounded-2xl border border-white/60 dark:border-slate-800/35 flex flex-col">
          <span className="text-[9px] font-black uppercase tracking-wider text-slate-400 dark:text-slate-500">
            Средние БЖУ
          </span>
          <span className="text-sm font-extrabold text-emerald-600 dark:text-emerald-400 font-display mt-2 leading-none">
            Б: {avgProtein}г | Ж: {avgFat}г
          </span>
          <span className="text-[10px] font-bold text-emerald-700 dark:text-emerald-400 mt-1 leading-none">
            Углеводы: {avgCarb}г
          </span>
        </div>

        {/* Metric 4 */}
        <div className="bg-white/40 dark:bg-slate-900/40 backdrop-blur-xs p-4 rounded-2xl border border-white/60 dark:border-slate-800/35 flex flex-col justify-center">
          <div className="flex items-center gap-1.5 text-xs font-bold text-emerald-800 dark:text-emerald-400">
            <CheckCircle2 size={14} className="text-emerald-500" />
            <span>Стабильно</span>
          </div>
          <p className="text-[9px] text-slate-500 dark:text-slate-400 mt-1 leading-relaxed">
            {range === "week"
              ? "Полноценный недельный цикл. Контролируйте уикенд."
              : "Длительный трек прогресса. Показывает настоящие изменения веса."}
          </p>
        </div>
      </div>

      {/* Chart Engine Section */}
      <div className="relative">
        <h4 className="text-[10px] uppercase font-bold tracking-widest text-slate-400 dark:text-slate-500 mb-3 flex items-center gap-1">
          <BarChart size={12} />
          График потребления калорий против дневной нормы:
        </h4>

        {/* SVG Graph View container */}
        <div className="w-full bg-white/70 dark:bg-slate-950/40 rounded-2xl p-4 border border-slate-200/40 dark:border-slate-800/60 transition-colors duration-300 overflow-x-auto">
          <div className="min-w-[460px]">
            <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} className="w-full h-auto">
              {/* Horizontal Grid lines */}
              {[4, 2, 1.33, 1].map((ratio, idx) => {
                const val = Math.round(maxCalVal / ratio);
                const gridY = getY(val);
                return (
                  <g key={idx}>
                    <line
                      x1={paddingLeft}
                      y1={gridY}
                      x2={chartWidth - paddingRight}
                      y2={gridY}
                      stroke="currentColor"
                      strokeDasharray="4 4"
                      className="text-slate-200 dark:text-slate-800/70"
                    />
                    <text
                      x={paddingLeft - 8}
                      y={gridY + 4}
                      className="text-[9px] font-mono text-slate-400 dark:text-slate-600 text-right"
                      textAnchor="end"
                    >
                      {val}
                    </text>
                  </g>
                );
              })}

              {/* Day column indicators for touch hover tracking */}
              {timelineData.map((d, idx) => {
                const cx = getX(idx);
                return (
                  <g key={idx} className="group">
                    {/* Invisible heavy touch strip */}
                    <rect
                      x={cx - (chartWidth / daysCount) / 2}
                      y={paddingTop}
                      width={chartWidth / daysCount}
                      height={chartHeight - paddingTop - paddingBottom}
                      fill="transparent"
                      className="cursor-pointer"
                      onMouseEnter={() => setHoveredDay(d)}
                      onMouseLeave={() => setHoveredDay(null)}
                      onClick={() => setHoveredDay(d)}
                    />
                    
                    {/* Vertical guideline on hover */}
                    {hoveredDay?.date === d.date && (
                      <line
                        x1={cx}
                        y1={paddingTop}
                        x2={cx}
                        y2={chartHeight - paddingBottom}
                        stroke="#10b981"
                        strokeWidth="1"
                        strokeDasharray="2 2"
                      />
                    )}
                  </g>
                );
              })}

              {/* User Goal Target Calibration line */}
              <line
                x1={paddingLeft}
                y1={targetLineY}
                x2={chartWidth - paddingRight}
                y2={targetLineY}
                stroke="#6366f1"
                strokeWidth="1.8"
                className="opacity-80"
              />
              <text
                x={chartWidth - paddingRight}
                y={targetLineY - 6}
                className="text-[10px] font-extrabold text-indigo-700 dark:text-indigo-400 text-right uppercase tracking-wider font-display"
                textAnchor="end"
              >
                Норма ({targetKcal} ккал)
              </text>

              {/* The Blue Calorie Line */}
              {timelineData.length > 1 && (
                <path
                  d={linePoints ? `M ${linePoints}` : ""}
                  fill="none"
                  stroke="url(#calorie-grad)"
                  strokeWidth="3.2"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              )}

              {/* Dots on the line nodes */}
              {timelineData.map((d, idx) => {
                const cx = getX(idx);
                const cy = getY(d.kcal);
                const isCurrentHovered = hoveredDay?.date === d.date;

                return (
                  <g key={idx}>
                    <circle
                      cx={cx}
                      cy={cy}
                      r={isCurrentHovered ? "6" : d.kcal > 0 ? "3.5" : "2"}
                      fill="currentColor"
                      className={`transition-all duration-300 ${
                        isCurrentHovered
                          ? "text-emerald-500"
                          : d.kcal > targetKcal
                          ? "text-orange-500"
                          : d.kcal > 0
                          ? "text-indigo-600 dark:text-emerald-400"
                          : "text-slate-350 dark:text-slate-800"
                      }`}
                    />
                  </g>
                );
              })}

              {/* Bottom timeline Russian labels (Show conditional spacing to keep readable) */}
              {timelineData.map((d, idx) => {
                const cx = getX(idx);
                const isEvenWeek = timelineData.length < 10 || idx % Math.round(timelineData.length / 7) === 0;

                if (!isEvenWeek && idx !== timelineData.length - 1 && idx !== 0) return null;

                return (
                  <text
                    key={idx}
                    x={cx}
                    y={chartHeight - 12}
                    className="text-[9px] font-bold text-slate-550 dark:text-slate-400 font-display text-center"
                    textAnchor="middle"
                  >
                    {d.label}
                  </text>
                );
              })}

              {/* Gradient defs for calorie progress line */}
              <defs>
                <linearGradient id="calorie-grad" x1="0%" y1="0%" x2="100%" y2="0%">
                  <stop offset="0%" stopColor="#6366f1" />
                  <stop offset="50%" stopColor="#10b981" />
                  <stop offset="100%" stopColor="#3b82f6" />
                </linearGradient>
              </defs>
            </svg>
          </div>
        </div>

        {/* Live Hover tooltip detail sheet overlay */}
        {hoveredDay && (
          <div className="absolute top-1/2 left-1/2 transform -translate-x-1/2 -translate-y-1/2 md:translate-x-0 md:translate-y-0 md:top-6 md:right-6 bg-white/95 dark:bg-slate-900 border border-emerald-500/20 rounded-2xl p-4 shadow-2xl animate-fade-in z-20 max-w-xs pointer-events-none transition-all">
            <div className="flex items-center gap-1.5 font-bold uppercase tracking-wider text-[10px] text-emerald-700 dark:text-emerald-400">
              <Calendar size={12} />
              <span>{new Date(hoveredDay.date).toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" })}</span>
            </div>
            <div className="mt-2 space-y-1.5 text-xs font-semibold text-slate-700 dark:text-slate-200">
              <div className="flex justify-between items-center gap-6">
                <span>Калорийность:</span>
                <span className="font-extrabold text-slate-900 dark:text-white">{hoveredDay.kcal} ккал</span>
              </div>
              <div className="flex justify-between items-center gap-6 pt-1 text-[11px] font-semibold border-t border-dashed border-slate-200 dark:border-slate-800">
                <span>Белки (Б):</span>
                <span>{hoveredDay.protein}г</span>
              </div>
              <div className="flex justify-between items-center gap-6 text-[11px] font-semibold">
                <span>Жиры (Ж):</span>
                <span>{hoveredDay.fat}г</span>
              </div>
              <div className="flex justify-between items-center gap-6 text-[11px] font-semibold">
                <span>Углеводы (У):</span>
                <span>{hoveredDay.carb}г</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Insight Tips Box */}
      <div className="p-4 bg-emerald-500/5 dark:bg-emerald-950/10 border border-emerald-500/10 dark:border-emerald-800/25 rounded-2xl flex items-start gap-3">
        <Award className="text-emerald-600 dark:text-emerald-400 shrink-0 mt-0.5" size={16} />
        <div>
          <h5 className="text-xs font-black text-emerald-850 dark:text-emerald-300 uppercase tracking-wider">
            Аналитика & Рекомендация
          </h5>
          <p className="text-[11px] text-emerald-800/90 dark:text-slate-400 mt-1 leading-relaxed">
            {avgKcal === 0
              ? "У вас пока недостаточно данных в выбранном диапазоне. Начните вносить продукты в Дневник!"
              : avgKcal > targetKcal
              ? `Потребление калорий превышает цель на ${Math.abs(avgKcal - targetKcal)} ккал. Попробуйте сдвинуть фокус в сторону продуктов с увеличенным белком (например, творог 5%, куриное филе) для сытости.`
              : `Отличный результат! Средняя калорийность (${avgKcal} ккал) держится ниже предела. Это формирует здоровый дефицит и подталкивает прогресс жиросжигания. Убедитесь, что белков съедаете не менее 1.5г накг веса.`}
          </p>
        </div>
      </div>
    </div>
  );
}
