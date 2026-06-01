import React from "react";
import { Sunrise, Sun, Moon, Apple, Trash2 } from "lucide-react";
import { motion, AnimatePresence } from "motion/react";
import { FoodItem, MealType } from "../types";

interface MealSectionProps {
  type: MealType;
  items: FoodItem[];
  onDelete: (index: number) => void;
}

const mealConfigs = {
  breakfast: {
    title: "ЗАВТРАК",
    icon: Sunrise,
    badgeColor: "text-amber-800 dark:text-amber-300 bg-amber-100/80 dark:bg-amber-950/40 border border-amber-200/30 dark:border-amber-900/30",
  },
  lunch: {
    title: "ОБЕД",
    icon: Sun,
    badgeColor: "text-orange-800 dark:text-orange-300 bg-orange-100/80 dark:bg-orange-950/40 border border-orange-200/30 dark:border-orange-900/30",
  },
  dinner: {
    title: "УЖИН",
    icon: Moon,
    badgeColor: "text-indigo-800 dark:text-indigo-300 bg-indigo-100/80 dark:bg-indigo-950/40 border border-indigo-200/30 dark:border-indigo-900/30",
  },
  snack: {
    title: "ПЕРЕКУС",
    icon: Apple,
    badgeColor: "text-emerald-800 dark:text-emerald-300 bg-emerald-100/80 dark:bg-emerald-950/40 border border-emerald-200/30 dark:border-emerald-900/30",
  },
};

export default function MealSection({ type, items, onDelete }: MealSectionProps) {
  const config = mealConfigs[type];
  const Icon = config.icon;

  // Calculate section sub-totals
  const subTotals = items.reduce(
    (acc, item) => {
      acc.kcal += item.kcal;
      acc.protein += item.protein;
      acc.fat += item.fat;
      acc.carb += item.carb;
      return acc;
    },
    { kcal: 0, protein: 0, fat: 0, carb: 0 }
  );

  return (
    <div className="bg-white/20 dark:bg-slate-900/30 backdrop-blur-md border border-white/40 dark:border-slate-800/40 p-5 rounded-3xl shadow-lg shadow-emerald-900/5 mb-6 meal-section transition-colors duration-300">
      {/* Header section with meal metadata */}
      <div className="flex items-center justify-between pb-4 mb-4 border-b border-white/20 dark:border-slate-800/30">
        <div className="flex items-center gap-2">
          <span className={`text-[10px] font-black uppercase tracking-wider px-2.5 py-1 rounded-lg ${config.badgeColor} meal-title flex items-center gap-1`}>
            <Icon size={12} />
            {config.title}
          </span>
        </div>

        <span className="text-xs font-bold text-slate-500 dark:text-slate-400 bg-white/40 dark:bg-slate-800/40 px-2 py-0.5 rounded-md border border-white/60 dark:border-slate-700/60 transition-colors duration-300">
          {subTotals.kcal} ккал
        </span>
      </div>

      <ul className="space-y-3 food-list" id={`list-${type}`}>
        <AnimatePresence initial={false}>
          {items.length > 0 ? (
            items.map((item, index) => (
              <motion.li
                key={item.id}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, x: -15, height: 0, padding: 0 }}
                transition={{ duration: 0.2 }}
                className="bg-white/60 dark:bg-slate-900/60 hover:bg-white/85 dark:hover:bg-slate-900/80 p-3.5 rounded-2xl border border-white/80 dark:border-slate-800/40 flex justify-between items-center shadow-xs hover:shadow-md hover:scale-105 active:scale-[0.99] relative z-0 hover:z-10 transition-all duration-300 ease-out group food-item cursor-pointer"
              >
                <div className="flex-1 min-w-0 pr-4 food-info">
                  <div className="text-sm font-bold text-slate-800 dark:text-slate-200 flex items-center gap-1.5 flex-wrap">
                    <span className="truncate">{item.name}</span>
                    <span className="text-[10px] font-black text-emerald-800 dark:text-emerald-300 bg-emerald-500/10 dark:bg-emerald-500/20 px-1.5 py-0.5 rounded-md shrink-0">
                      {item.portionSize !== undefined && item.unit 
                        ? `${item.portionSize} ${item.unit}` 
                        : `${item.weight || 100}г`
                      }
                    </span>
                    <span className="text-[10px] font-bold text-slate-400 dark:text-slate-400 bg-slate-100/80 dark:bg-slate-800/80 px-1 py-0.5 rounded-md shrink-0 border border-slate-200/20 dark:border-slate-700/40">
                      {item.kcal} ккал
                    </span>
                  </div>
                  <div className="text-[10px] text-slate-500 dark:text-slate-400 font-semibold mt-1 food-kbju">
                    Б: <span className="text-blue-600 dark:text-blue-400">{item.protein}г</span> | Ж: <span className="text-orange-600 dark:text-orange-400">{item.fat}г</span> | У: <span className="text-emerald-600 dark:text-emerald-400">{item.carb}г</span>
                  </div>
                </div>

                <button
                  type="button"
                  onClick={() => onDelete(index)}
                  className="p-1.5 text-slate-300 dark:text-slate-600 hover:text-red-500 dark:hover:text-red-400 bg-transparent hover:bg-red-50 dark:hover:bg-red-950/30 rounded-xl cursor-pointer transition-all duration-200 active:scale-90 delete-btn"
                  title="Удалить из меню"
                >
                  <Trash2 size={16} />
                </button>
              </motion.li>
            ))
          ) : (
            <motion.li
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-center py-6 text-slate-400/80 dark:text-slate-600 text-xs font-bold uppercase tracking-wider"
              style={{ border: "none" }}
            >
              Пусто
            </motion.li>
          )}
        </AnimatePresence>
      </ul>
    </div>
  );
}
