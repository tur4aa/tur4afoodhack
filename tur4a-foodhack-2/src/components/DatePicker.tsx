import React from "react";
import { ChevronLeft, ChevronRight, Calendar } from "lucide-react";

interface DatePickerProps {
  selectedDate: string;
  onChange: (date: string) => void;
}

export default function DatePicker({ selectedDate, onChange }: DatePickerProps) {
  const handlePrevDay = () => {
    const date = new Date(selectedDate);
    date.setDate(date.getDate() - 1);
    onChange(date.toISOString().split("T")[0]);
  };

  const handleNextDay = () => {
    const date = new Date(selectedDate);
    date.setDate(date.getDate() + 1);
    onChange(date.toISOString().split("T")[0]);
  };

  const handleToday = () => {
    const today = new Date().toISOString().split("T")[0];
    onChange(today);
  };

  const formatDisplayDate = (dateStr: string) => {
    try {
      const date = new Date(dateStr);
      if (isNaN(date.getTime())) return dateStr;
      
      const today = new Date().toISOString().split("T")[0];
      const yesterday = new Date();
      yesterday.setDate(yesterday.getDate() - 1);
      const yesterdayStr = yesterday.toISOString().split("T")[0];

      if (dateStr === today) {
        return "Сегодня";
      } else if (dateStr === yesterdayStr) {
        return "Вчера";
      }

      return date.toLocaleDateString("ru-RU", {
        weekday: "short",
        day: "numeric",
        month: "long",
      });
    } catch {
      return dateStr;
    }
  };

  return (
    <div className="flex flex-col gap-3.5 bg-white/40 dark:bg-slate-900/40 backdrop-blur-md border border-white/60 dark:border-slate-800/60 p-4 rounded-3xl mb-6 shadow-sm transition-colors duration-300">
      {/* Top row: Label & Today button */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="p-2 bg-emerald-500 text-white rounded-xl shadow-md shadow-emerald-200/20">
            <Calendar size={16} />
          </div>
          <div>
            <span className="text-[9px] text-emerald-800 dark:text-emerald-400 uppercase tracking-wider block font-black leading-none mb-1">Выбранный день</span>
            <span className="text-xs font-bold text-slate-800 dark:text-slate-100 font-display">
              {formatDisplayDate(selectedDate)}
            </span>
          </div>
        </div>

        <button
          onClick={handleToday}
          className="px-2.5 py-1.5 bg-emerald-500 hover:bg-emerald-600 text-white text-[10px] font-black uppercase tracking-wider rounded-lg shadow-xs hover:shadow-md transition-all cursor-pointer active:scale-95 shrink-0"
        >
          Сегодня
        </button>
      </div>

      {/* Bottom row: Prev, Input Date, Next */}
      <div className="flex items-center gap-1.5">
        <button
          onClick={handlePrevDay}
          className="p-2 bg-white/70 dark:bg-slate-800/60 hover:bg-emerald-500 hover:text-white text-slate-600 dark:text-slate-300 rounded-xl border border-white/80 dark:border-slate-700/60 transition-all shadow-sm cursor-pointer active:scale-95 shrink-0 flex items-center justify-center"
          title="Предыдущий день"
        >
          <ChevronLeft size={16} />
        </button>

        <div className="relative flex-1 min-w-0">
          <input
            id="current-date"
            type="date"
            value={selectedDate}
            onChange={(e) => onChange(e.target.value)}
            className="w-full px-2.5 py-1.5 bg-white/60 dark:bg-slate-800/60 text-slate-700 dark:text-slate-200 border border-white/80 dark:border-slate-700/60 rounded-xl text-xs font-bold focus:outline-hidden focus:ring-2 focus:ring-emerald-400 outline-hidden cursor-pointer shadow-sm transition-all text-center"
          />
        </div>

        <button
          onClick={handleNextDay}
          className="p-2 bg-white/70 dark:bg-slate-800/60 hover:bg-emerald-500 hover:text-white text-slate-600 dark:text-slate-300 rounded-xl border border-white/80 dark:border-slate-700/60 transition-all shadow-sm cursor-pointer active:scale-95 shrink-0 flex items-center justify-center"
          title="Следующий день"
        >
          <ChevronRight size={16} />
        </button>
      </div>
    </div>
  );
}
