import React, { createContext, useContext, useState, useEffect } from "react";

export type Language = "ru" | "en";

interface LanguageContextProps {
  language: Language;
  setLanguage: (lang: Language) => void;
  t: (key: string, variables?: Record<string, any>) => string;
}

const LanguageContext = createContext<LanguageContextProps | undefined>(undefined);

const translations: Record<Language, Record<string, string>> = {
  ru: {
    // Header & Brand
    app_title: "tur4a FoodHack",
    app_sub_title: "Личное меню и калькулятор калорий",
    version_label: "Модульная v2.5",
    sign_out_title: "Выйти из аккаунта",
    profile_fallback: "Кабинет",
    tab_diary: "Дневник",
    tab_add: "Добавить",
    tab_ai_progress: "ИИ & Прогресс",
    tip_title: "Совет дня",
    tip_content: "Для стабильного энергообмена и долгого ощущения сытости сбалансируйте ужин сложными углеводами и добавьте больше пищевой клетчатки (овощей).",
    
    // Auth Page
    auth_profile_title: "Личный кабинет и КБЖУ дневник",
    auth_feat1_title: "Персональный доступ",
    auth_feat1_desc: "Все ваши блюда, статистики КБЖУ и шаблоны надежно хранятся в защищенном облаке Firestore.",
    auth_feat2_title: "ИИ-сканирование готовых блюд",
    auth_feat2_desc: "Встроенный анализатор распознает калории, белки, жиры и углеводы прямо по фотографии или запросу.",
    auth_feat3_title: "Гибкие рационы (IIFYM)",
    auth_feat3_desc: "Свободный учет любимой еды. Копирование меню вчерашнего дня в 1 клик для экономии времени.",
    auth_btn_google: "Создать аккаунт через Google",
    loading_secure_cloud: "Загрузка безопасного облака...",
    theme_light_tooltip: "Включить светлую тему",
    theme_dark_tooltip: "Включить темную тему",

    // Summary Box
    summary_title: "Итоги Дня",
    summary_badge: "КБЖУ Баланс",
    summary_circle_of: "из {targetKcal} ккал",
    summary_protein: "Белки",
    summary_fat: "Жиры",
    summary_carbs: "Углеводы",
    summary_goal_of: "цель: {val}г",

    // Date Picker
    date_selected_label: "Выбранный день",
    date_today_btn: "Сегодня",
    date_prev_title: "Предыдущий день",
    date_next_title: "Следующий день",
    date_today_name: "Сегодня",
    date_yesterday_name: "Вчера",
    date_tomorrow_name: "Завтра",

    // Meal Sections
    meal_copy_btn: "СКОПИРОВАТЬ ИЗ ВЧЕРА",
    meal_copy_copied: "Скопировано",
    meal_copy_fail: "Нет вчерашних записей для копирования",
    meal_header: "ВАШЕ МЕНЮ",
    meal_positions: "Позиций: {count}",
    meal_breakfast: "ЗАВТРАК",
    meal_lunch: "ОБЕД",
    meal_dinner: "УЖИН",
    meal_snack: "ПЕРЕКУС",
    meal_empty: "ПУСТО",
    meal_delete_tooltip: "Удалить",

    // Add Food Form
    add_title: "Добавить блюдо",
    add_smart_calc: "УМНЫЙ РАСЧЁТ",
    add_meal_label: "ПРИЕМ ПИЩИ",
    add_templates_history: "ИСТОРИЯ ШАБЛОНОВ (НАЖМИТЕ ДЛЯ ВЫБОРА):",
    add_name_label: "НАЗВАНИЕ БЛЮДА / ПРОДУКТА",
    add_name_placeholder: "Введите название (например, Рис отварной)",
    add_amount_label: "МЕРА СЪЕДЕННОГО",
    add_custom_kbju_badge: "У меня свои данные KBJU на 100гр/порцию",
    add_custom_kbju_volume: "ДЛЯ КАКОГО ОБЪЕМА ЭТИ ДАННЫЕ?",
    add_custom_kbju_stats: "УКАЖИТЕ КБЖУ ДЛЯ ЭТОГО ОБЪЕМА",
    add_kcal_label: "Калории (ккал)",
    add_protein_label: "Белки (г)",
    add_fat_label: "Жиры (г)",
    add_carbs_label: "Углеводы (г)",
    add_save_tmpl_checkbox: "Сохранить этот продукт как постоянный шаблон",
    add_btn_submit: "Добавить в меню",
    add_error_no_name: "Пожалуйста, введите название блюда / продукта",
    add_error_zero_weight: "Укажите количество в {unit} (например, {val})",
    add_success_msg: "Блюдо успешно добавлено в меню!",

    // AI Scanner
    ai_title: "ИИ-АНАЛИЗАТОР БЛЮД",
    ai_desc: "Опишите ваш прием пищи текстом или загрузите фото. ИИ мгновенно рассчитает калорийность и КБЖУ.",
    ai_placeholder: "Пример: Тарелка борща 350г и два куска ржаного хлеба",
    ai_btn_photo: "Загрузить фото",
    ai_btn_text: "Распознать текст",
    ai_loading: "Идет магия анализа ИИ...",
    ai_error_input: "Пожалуйста, введите текстовое описание или прикрепите изображение.",
    ai_success_title: "БЛЮДО СФОРМИРОВАНО!",
    ai_success_note: "Вы можете отредактировать вес и нажать Добавить в меню.",

    // Goal Settings
    goals_title: "Управление целями КБЖУ",
    goals_desc: "Настройте свои дневные лимиты вручную или воспользуйтесь автоматическим расчетом по формуле.",
    goals_tab_manual: "Ручной ввод",
    goals_tab_auto: "Калькулятор целей",
    goals_label_kcal: "Дневная калорийность",
    goals_label_protein: "Белки (Б)",
    goals_label_fat: "Жиры (Ж)",
    goals_label_carbs: "Углеводы (У)",
    goals_feedback_manual: "Цели успешно сохранены вручную!",
    goals_feedback_auto: "Цели рассчитаны и сохранены автоматически!",
    goals_btn_save_manually: "Сохранить цели вручную",
    goals_calc_title: "Автоматический расчет КБЖУ",
    goals_calc_sex: "Биологический пол",
    goals_calc_male: "Мужской",
    goals_calc_female: "Женский",
    goals_calc_weight: "Текущий вес (кг)",
    goals_calc_height: "Рост (см)",
    goals_calc_age: "Возраст (лет)",
    goals_calc_activity: "Уровень активности",
    goals_activity_low: "Минимальный (сидячий)",
    goals_activity_mid: "Умеренный (3-5 тренировок в неделю)",
    goals_activity_high: "Высокий (тяжелый физический труд / ежедневный спорт)",
    goals_calc_goal: "Ваша цель",
    goals_goal_deficit: "Похудение (дефицит 15%)",
    goals_goal_balance: "Поддержание веса (баланс)",
    goals_goal_surplus: "Набор массы (профицит 10%)",
    goals_btn_calc_apply: "Рассчитать и применить цели КБЖУ",

    // Progress Analysis
    progress_title: "Анализ прогресса за неделю",
    progress_desc: "Ваша статистика соблюдения баланса КБЖУ за последние 7 дней.",
    progress_tooltip_prompt: "Наведите курсор на точку графика для просмотра деталей",
    progress_avg_line: "СРЕДНЕЕ: {avg} ККАЛ",
    progress_legend_kcal: "Калории",
    progress_legend_goal: "Цель ({val})",
    progress_tooltip_date: "Дата",
    progress_tooltip_kcal: "Калорийность:",
    progress_tooltip_p: "Белки (Б):",
    progress_tooltip_f: "Жиры (Ж):",
    progress_tooltip_c: "Углеводы (У):",
    progress_verdict_title: "Вердикт диетолога",
    progress_verdict_perfect: "Идеально! Ваш средний калораж {avg} ккал отлично соответствует цели {goal} ккал (+/- 15%). Дисциплина на высоте!",
    progress_verdict_deficit: "Режим дефицита. Ваш средний калораж {avg} ккал ниже целевого лимита {goal} ккал. Отличный темп для здорового снижения веса!",
    progress_verdict_surplus: "Режим избытка. Ваш средний калораж {avg} ккал превышает целевой ориентир {goal} ккал. Подходит для набора мышечной массы и активного восстановления.",

    // Footer
    footer_goal: "Цель: Здоровье & Баланс",
    footer_method: "Метод: IIFYM (Flexible Dieting)",
    footer_compliance: "Прогресс КБЖУ: {percent}%",
    footer_copyright: "tur4a FoodHack (Модульная / Сетка Glassmorphism)",
  },
  en: {
    // Header & Brand
    app_title: "tur4a FoodHack",
    app_sub_title: "Personal menu & calorie calculator",
    version_label: "Modular v2.5",
    sign_out_title: "Sign out of account",
    profile_fallback: "Account",
    tab_diary: "Diary",
    tab_add: "Add Item",
    tab_ai_progress: "AI & Chart",
    tip_title: "Tip of the Day",
    tip_content: "For steady energy levels and long-lasting fullness, balance your dinner with complex carbs and add plenty of dietary fiber (fresh vegetables).",

    // Auth Page
    auth_profile_title: "Personal Profile & Calorie Diary",
    auth_feat1_title: "Personal Access",
    auth_feat1_desc: "All your meals, KBJU statistics, and templates are securely stored in a protected Firestore cloud.",
    auth_feat2_title: "AI Scanning of Ready Meals",
    auth_feat2_desc: "The built-in analyzer detects calories, proteins, fats, and carbohydrates right from a photo or prompt.",
    auth_feat3_title: "Flexible Diets (IIFYM)",
    auth_feat3_desc: "Track any favorite food. Copy yesterday's menu in 1 click to save time.",
    auth_btn_google: "Create an Account with Google",
    loading_secure_cloud: "Loading secure cloud...",
    theme_light_tooltip: "Enable light theme",
    theme_dark_tooltip: "Enable dark theme",

    // Summary Box
    summary_title: "Today's Summary",
    summary_badge: "KBJU Balance",
    summary_circle_of: "of {targetKcal} kcal",
    summary_protein: "Protein",
    summary_fat: "Fat",
    summary_carbs: "Carbs",
    summary_goal_of: "goal: {val}g",

    // Date Picker
    date_selected_label: "Selected day",
    date_today_btn: "Today",
    date_prev_title: "Previous day",
    date_next_title: "Next day",
    date_today_name: "Today",
    date_yesterday_name: "Yesterday",
    date_tomorrow_name: "Tomorrow",

    // Meal Sections
    meal_copy_btn: "COPY FROM YESTERDAY",
    meal_copy_copied: "Copied",
    meal_copy_fail: "No yesterday entries to copy",
    meal_header: "YOUR MENU",
    meal_positions: "Items: {count}",
    meal_breakfast: "BREAKFAST",
    meal_lunch: "LUNCH",
    meal_dinner: "DINNER",
    meal_snack: "SNACKS",
    meal_empty: "EMPTY",
    meal_delete_tooltip: "Delete",

    // Add Food Form
    add_title: "Add Food Item",
    add_smart_calc: "SMART MATH",
    add_meal_label: "MEAL OF THE DAY",
    add_templates_history: "TEMPLATES HISTORY (CLICK TO POPULATE):",
    add_name_label: "FOOD / PRODUCT NAME",
    add_name_placeholder: "Enter details (e.g., Boiled rice)",
    add_amount_label: "AMOUNT CONSUMED",
    add_custom_kbju_badge: "I have specific macro data per 100g/serving",
    add_custom_kbju_volume: "FOR WHAT VOLUME IS THIS DATA?",
    add_custom_kbju_stats: "SPECIFY KBJU FOR THIS VOLUME",
    add_kcal_label: "Calories (kcal)",
    add_protein_label: "Protein (g)",
    add_fat_label: "Fat (g)",
    add_carbs_label: "Carbs (g)",
    add_save_tmpl_checkbox: "Save this product as a permanent template",
    add_btn_submit: "Add to Menu",
    add_error_no_name: "Please enter a food / product name",
    add_error_zero_weight: "Specify weight/pieces in {unit} (e.g. {val})",
    add_success_msg: "Meal added successfully!",

    // AI Scanner
    ai_title: "AI MEAL ANALYZER",
    ai_desc: "Describe your meal in text or upload a photo. AI will instantly calculate calories and KBJU.",
    ai_placeholder: "Example: A bowl of borsch 350g and two slices of dark rye bread",
    ai_btn_photo: "Upload Photo",
    ai_btn_text: "Analyze Text",
    ai_loading: "AI analytical magic in progress...",
    ai_error_input: "Please provide a description or upload an image.",
    ai_success_title: "MEAL SPECS CREATED!",
    ai_success_note: "You can adjust the weight and click Add to Menu.",

    // Goal Settings
    goals_title: "Manage Targets & Limits",
    goals_desc: "Configure your daily targets manually or use the formula for automatic calculation.",
    goals_tab_manual: "Manual Entry",
    goals_tab_auto: "Goals Calculator",
    goals_label_kcal: "Daily Calories",
    goals_label_protein: "Proteins (P)",
    goals_label_fat: "Fats (F)",
    goals_label_carbs: "Carbohydrates (C)",
    goals_feedback_manual: "Goals successfully saved manually!",
    goals_feedback_auto: "Goals calculated and saved automatically!",
    goals_btn_save_manually: "Save goals manually",
    goals_calc_title: "Automatic Targets Calculator",
    goals_calc_sex: "Biological Sex",
    goals_calc_male: "Male",
    goals_calc_female: "Female",
    goals_calc_weight: "Weight (kg)",
    goals_calc_height: "Height (cm)",
    goals_calc_age: "Age (years)",
    goals_calc_activity: "Activity Multiplier",
    goals_activity_low: "Sedentary / Desk Job",
    goals_activity_mid: "Active (3-5 workouts per week)",
    goals_activity_high: "Highly Active (hard physical labor / daily sports)",
    goals_calc_goal: "Your Fitness / Diet Goal",
    goals_goal_deficit: "Fat Loss (15% deficit)",
    goals_goal_balance: "Weight Maintenance (balance)",
    goals_goal_surplus: "Muscle Gain (10% surplus)",
    goals_btn_calc_apply: "Compute & Save Daily Goals",

    // Progress Analysis
    progress_title: "Weekly Compliance Analytics",
    progress_desc: "Your calorie and macro stability compliance record for the last 7 days.",
    progress_tooltip_prompt: "Hover over chart nodes to review specific dates and values",
    progress_avg_line: "AVERAGE: {avg} KCAL",
    progress_legend_kcal: "Calories",
    progress_legend_goal: "Goal ({val})",
    progress_tooltip_date: "Date",
    progress_tooltip_kcal: "Calories:",
    progress_tooltip_p: "Protein (P):",
    progress_tooltip_f: "Fats (F):",
    progress_tooltip_c: "Carbs (C):",
    progress_verdict_title: "Dietitian's Evaluation",
    progress_verdict_perfect: "Excellent! Your average intake of {avg} kcal sits right within your target window of {goal} kcal (+/- 15%). Outstanding dietary stability!",
    progress_verdict_deficit: "Caloric Deficit. Your average intake of {avg} kcal is below your target of {goal} kcal. Ideal rhythm for safe and steady weight loss!",
    progress_verdict_surplus: "Caloric Surplus. Your average intake of {avg} kcal is above your target of {goal} kcal. Great for safe, deliberate muscle and strength gains.",

    // Footer
    footer_goal: "Goal: Health & Balance",
    footer_method: "Method: IIFYM (Flexible Dieting)",
    footer_compliance: "KBJU Accuracy: {percent}%",
    footer_copyright: "tur4a FoodHack (Modular / Glassmorphism Grid)",
  }
};

export const LanguageProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [language, setLanguageState] = useState<Language>(() => {
    try {
      const stored = localStorage.getItem("app_lang");
      if (stored === "ru" || stored === "en") {
        return stored;
      }
    } catch {}
    return "ru"; // default to Russian
  });

  const setLanguage = (lang: Language) => {
    setLanguageState(lang);
    try {
      localStorage.setItem("app_lang", lang);
    } catch {}
  };

  const t = (key: string, variables?: Record<string, any>): string => {
    const rawValue = translations[language][key] || translations["ru"][key] || key;
    if (!variables) return rawValue;

    let processedValue = rawValue;
    Object.entries(variables).forEach(([vKey, vVal]) => {
      processedValue = processedValue.replace(new RegExp(`\\{${vKey}\\}`, "g"), String(vVal));
    });
    return processedValue;
  };

  return (
    <LanguageContext.Provider value={{ language, setLanguage, t }}>
      {children}
    </LanguageContext.Provider>
  );
};

export const useLanguage = () => {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error("useLanguage must be used within a LanguageProvider");
  }
  return context;
};
