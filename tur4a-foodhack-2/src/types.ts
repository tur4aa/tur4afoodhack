export interface FoodItem {
  id: string;
  name: string;
  kcal: number;
  protein: number;
  fat: number;
  carb: number;
  weight?: number; // Weight in grams (default 100g if not specified)
  unit?: string;   // e.g. "г", "шт", "порц"
  portionSize?: number; // e.g. 1, 2, 150
}

export interface FoodTemplate {
  id: string;
  name: string;
  kcal: number;     // per baseAmount of baseUnit
  protein: number;  // per baseAmount of baseUnit
  fat: number;      // per baseAmount of baseUnit
  carb: number;     // per baseAmount of baseUnit
  usageCount: number; // to sort by popularity
  baseAmount?: number; // default 100
  baseUnit?: string;   // default "г"
}

export interface UserGoals {
  kcal: number;
  protein: number;
  fat: number;
  carb: number;
}

export interface DayData {
  breakfast: FoodItem[];
  lunch: FoodItem[];
  dinner: FoodItem[];
  snack: FoodItem[];
}

export interface DiaryData {
  [date: string]: DayData;
}

export type MealType = "breakfast" | "lunch" | "dinner" | "snack";
