import React from "react";
import { Flame, Star, Droplets, Wheat } from "lucide-react";
import { UserGoals } from "../types";

interface SummaryBoxProps {
  kcal: number;
  protein: number;
  fat: number;
  carb: number;
  goals: UserGoals;
}

export default function SummaryBox({ kcal, protein, fat, carb, goals }: SummaryBoxProps) {
  const targetKcal = goals.kcal;
  const targetProtein = goals.protein;
  const targetFat = goals.fat;
  const targetCarb = goals.carb;

  const kcalPercent = Math.min((kcal / targetKcal) * 100, 100);
  const proteinPercent = Math.min((protein / targetProtein) * 100, 100);
  const fatPercent = Math.min((fat / targetFat) * 100, 100);
  const carbPercent = Math.min((carb / targetCarb) * 100, 100);

  // SVG parameters for 176px circle (radius 80, circumference = 2 * pi * 80 ≈ 502.65)
  const radius = 80;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (kcalPercent / 100) * circumference;

  return (
    <div className="bg-white/40 dark:bg-slate-900/40 backdrop-blur-xl border border-white/60 dark:border-slate-800/60 p-6 rounded-3xl shadow-xl shadow-emerald-900/5 transition-colors duration-300">
      <div className="flex items-center justify-between mb-6">
        <h3 className="text-sm uppercase tracking-wider font-bold text-emerald-800 dark:text-emerald-400 font-display">
          Итоги Дня
        </h3>
        <span className="text-xs font-bold text-emerald-700 dark:text-emerald-300 bg-emerald-100/60 dark:bg-emerald-950/40 px-2.5 py-1 rounded-full border border-emerald-200/40 dark:border-emerald-900/40">
          КБЖУ Баланс
        </span>
      </div>

      {/* Circular Calorie Gauge matching theme */}
      <div className="relative w-48 h-48 mx-auto mb-8 flex items-center justify-center">
        <svg className="w-full h-full transform -rotate-90">
          {/* Track Circle */}
          <circle
            cx="96"
            cy="96"
            r={radius}
            stroke="currentColor"
            strokeWidth="12"
            fill="transparent"
            className="text-white/40 dark:text-slate-800/60"
          />
          {/* Progress Circle with elegant gradient color simulation */}
          <circle
            cx="96"
            cy="96"
            r={radius}
            stroke="currentColor"
            strokeWidth="12"
            fill="transparent"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            className="text-emerald-500 dark:text-emerald-400 transition-all duration-500 ease-out"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-4xl font-black text-slate-800 dark:text-slate-100 tracking-tight font-display" id="total-kcal">
            {kcal.toLocaleString()}
          </span>
          <span className="text-xs font-bold text-slate-500 dark:text-slate-400 uppercase mt-0.5 tracking-wider">
            из {targetKcal} ккал
          </span>
        </div>
      </div>

      {/* BJU Frosted Mini cards container */}
      <div className="grid grid-cols-3 gap-2.5 metrics-grid">
        {/* Protein */}
        <div className="bg-white/60 dark:bg-slate-900/60 backdrop-blur-xs rounded-2xl p-3 text-center border border-white/80 dark:border-slate-800/40 transition-all hover:scale-103 duration-300">
          <span className="block text-[10px] font-bold text-blue-600 dark:text-blue-400 uppercase tracking-wider">
            Белки
          </span>
          <span className="text-lg font-extrabold text-slate-800 dark:text-slate-100 font-display" id="total-protein">
            {protein}г
          </span>
          <div className="w-full bg-white/40 dark:bg-slate-800/30 h-1.5 rounded-full mt-2 overflow-hidden shadow-2xs">
            <div
              className="bg-blue-400 dark:bg-blue-500 h-1.5 rounded-full transition-all duration-500"
              style={{ width: `${proteinPercent}%` }}
            />
          </div>
          <span className="text-[9px] font-medium text-slate-400 dark:text-slate-500 mt-1 block">цель: {targetProtein}г</span>
        </div>

        {/* Fat */}
        <div className="bg-white/60 dark:bg-slate-900/60 backdrop-blur-xs rounded-2xl p-3 text-center border border-white/80 dark:border-slate-800/40 transition-all hover:scale-103 duration-300">
          <span className="block text-[10px] font-bold text-orange-600 dark:text-orange-400 uppercase tracking-wider">
            Жиры
          </span>
          <span className="text-lg font-extrabold text-slate-800 dark:text-slate-100 font-display" id="total-fat">
            {fat}г
          </span>
          <div className="w-full bg-white/40 dark:bg-slate-800/30 h-1.5 rounded-full mt-2 overflow-hidden shadow-2xs">
            <div
              className="bg-orange-400 dark:bg-orange-500 h-1.5 rounded-full transition-all duration-500"
              style={{ width: `${fatPercent}%` }}
            />
          </div>
          <span className="text-[9px] font-medium text-slate-400 dark:text-slate-500 mt-1 block">цель: {targetFat}г</span>
        </div>

        {/* Carbohydrates */}
        <div className="bg-white/60 dark:bg-slate-900/60 backdrop-blur-xs rounded-2xl p-3 text-center border border-white/80 dark:border-slate-800/40 transition-all hover:scale-103 duration-300">
          <span className="block text-[10px] font-bold text-emerald-600 dark:text-emerald-400 uppercase tracking-wider">
            Углев.
          </span>
          <span className="text-lg font-extrabold text-slate-800 dark:text-slate-100 font-display" id="total-carb">
            {carb}г
          </span>
          <div className="w-full bg-white/40 dark:bg-slate-800/30 h-1.5 rounded-full mt-2 overflow-hidden shadow-2xs">
            <div
              className="bg-emerald-400 dark:bg-emerald-500 h-1.5 rounded-full transition-all duration-500"
              style={{ width: `${carbPercent}%` }}
            />
          </div>
          <span className="text-[9px] font-medium text-slate-400 dark:text-slate-500 mt-1 block">цель: {targetCarb}г</span>
        </div>
      </div>
    </div>
  );
}
