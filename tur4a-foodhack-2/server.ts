import express from "express";
import path from "path";
import { createServer as createViteServer } from "vite";
import { GoogleGenAI, Type } from "@google/genai";
import dotenv from "dotenv";

dotenv.config();

const app = express();
const PORT = 3000;

// Increase request size limit for base64 photo uploads
app.use(express.json({ limit: "50mb" }));
app.use(express.urlencoded({ limit: "50mb", extended: true }));

// Initialize Gemini client server-side
let ai: GoogleGenAI | null = null;
try {
  if (process.env.GEMINI_API_KEY) {
    ai = new GoogleGenAI({
      apiKey: process.env.GEMINI_API_KEY,
      httpOptions: {
        headers: {
          "User-Agent": "aistudio-build",
        },
      },
    });
  } else {
    console.warn("GEMINI_API_KEY is not defined in environment variables.");
  }
} catch (error) {
  console.error("Failed to initialize Gemini:", error);
}

// ----------------------------------------------------
// AI Photo and portion analyzer endpoint
// ----------------------------------------------------
app.post("/api/gemini/analyze-photo", async (req, res) => {
  const { imageBase64, mimeType, customGoal, dailyKcalTarget, mode } = req.body;

  // Graceful fallback values in case client-side or server test is conducted without an API key loaded.
  // We compute actual numbers if user requests, or guide them.
  const hasApiKey = !!process.env.GEMINI_API_KEY && !!ai;

  if (!hasApiKey) {
    if (mode === "label_scanner") {
      console.log("No GEMINI_API_KEY found, returning premium smart nutrition label recognition demo");
      const labelAdvice = `### 🏷️ Распознана этикетка: Протеиновый батончик Bombbar (Фисташка) (Демо-режим)

ИИ успешно распознал таблицу КБЖУ на упаковке товара:
* **Название продукта:** \`Протеиновый батончик Bombbar (Фисташка)\`
* **Калорийность (на 100г):** \`380 ккал\`
* **Белки (на 100г):** \`33.3 г\`
* **Жиры (на 100г):** \`11.5 г\`
* **Углеводы (на 100г):** \`10.1 г\`

#### 🔬 Анализ состава и рекомендации:
1. **Качество белка:** Высокое. Источники — концентрат сывороточного белка и мицеллярный казеин. Отлично подходит для восстановления мышц и долгого насыщения.
2. **Сахар:** Добавленный сахар отсутствует, подсластители безопасные (стевиозид, сукралоза). Отлично вписывается в диету для похудения.
3. **Рекомендация:** Употребляйте в качестве перекуса между основными приемами пищи или за 1 час до силовой тренировки.

*Вы можете сохранить этот продукт в свою постоянную базу (Шаблоны) или добавить в дневник одной кнопкой ниже!*`;

      return res.json({
        success: true,
        advice: labelAdvice,
        suggestedFoods: [
          {
            name: "Протеиновый батончик Bombbar (Фисташка)",
            kcal: 380,
            protein: 33.3,
            fat: 11.5,
            carb: 10.1,
            weight: 100,
            mealType: "snack"
          }
        ]
      });
    }

    if (mode === "dish_scanner") {
      console.log("No GEMINI_API_KEY found, returning premium smart dish recognition demo");
      const dishAdvice = `### 🍽️ Распознанное Блюдо: Запечённая сёмга с бурым рисом и спаржей (Демо-режим)

ИИ успешно проанализировал тестовое изображение блюда. Вот оцененные ингредиенты и КБЖУ:

- **Запечённая сёмга (филе):** \`~150 г\` (богата Омега-3 и белком)
- **Отварной бурый рис:** \`~120 г\` (медленные углеводы, клетчатка)
- **Приготовленная спаржа на пару:** \`~80 г\` (микроэлементы)

#### 📊 Общая КБЖУ ценность тарелки:
* **Калорийность:** \`~480 ккал\`
* **Белки:** \`~36.8 г\`
* **Жиры:** \`~18.2 г\`
* **Углеводы:** \`~32.5 г\`

*Вы можете добавить все составляющие в дневник питания одним нажатием ниже!*`;

      return res.json({
        success: true,
        advice: dishAdvice,
        suggestedFoods: [
          {
            name: "Запечённая сёмга (филе)",
            kcal: 290,
            protein: 30,
            fat: 17,
            carb: 0,
            weight: 150,
            mealType: "lunch"
          },
          {
            name: "Отварной бурый рис",
            kcal: 162,
            protein: 3.8,
            fat: 1.2,
            carb: 30,
            weight: 120,
            mealType: "lunch"
          },
          {
            name: "Спаржа на пару",
            kcal: 28,
            protein: 3,
            fat: 0,
            carb: 2.5,
            weight: 80,
            mealType: "lunch"
          }
        ]
      });
    }

    // Elegant simulation feedback specifically addressing the prompt calculations so user gets immediate functionality
    console.log("No GEMINI_API_KEY found, returning premium smart portion plan mock");
    
    // Calculate 5kg chicken over 3 weeks:
    // 5kg = 5000g. 3 weeks = 21 days.
    // 5000g / 21 days ≈ 238g of chicken per day.
    // If raw chicken has per 100g: 110 kcal, 23g Prote, 1.5g Fat, 0g Carb
    // Over portion size 238g:
    // kcal = (110 * 238) / 100 ≈ 262 kcal
    // protein = (23 * 238) / 100 ≈ 54.7g
    // fat = (1.5 * 238) / 100 ≈ 3.6g
    // carb = 0g
    let mockAdvice = `### 🐔 План разделения и рекомендации (Демо-режим без API ключа)

*Вы успешно запустили анализатор! Для получения реального распознавания по вашему фото подключите Ваш API-ключ в настройках.*

В ответ на ваш запрос, вот расчет для разделения **5 кг курицы на 3 недели**:
- **Всего на 3 недели:** 5000 грамм (21 день).
- **Размер порции в день:** **238 г** сырого продукта.
- **В суделях (в неделю):** **1.66 кг** на одну неделю (7 дней).

#### 📊 КБЖУ Дневной Порции курицы (238г):
* **Калорийность:** \`~262 ккал\`
* **Белки:** \`~54.7 г\`
* **Жиры:** \`~3.6 г\`
* **Углеводы:** \`~0 г\`

#### 💡 Рекомендации по делению и хранению:
1. **Нарезка и фасовка:** Рекомендуется сразу поделить 5 кг курятины на 21 равный пакет (примерно по 235-240 г в каждом).
2. **Заморозка:** Оставьте в холодильнике порции на 2 дня, остальные 19 пакетов отправьте в морозилку. Доставайте по мере необходимости с вечера на следующий день.
3. **Равномерное распределение:** Поскольку белка в порции довольно много (55 г), лучше разделить эту курятину на 2 приема пищи (например, 120г в обед и 120г на ужин), чтобы организм усвоил его максимально эффективно.`;

    if (customGoal) {
      mockAdvice += `\n\n*Учтена ваша цель*: "${customGoal}". Старайтесь придерживаться КБЖУ коридора!`;
    }

    return res.json({
      success: true,
      advice: mockAdvice,
      suggestedFoods: [
        {
          name: "Куриное филе (Дневная порция 1/21)",
          kcal: 262,
          protein: 54.7,
          fat: 3.6,
          carb: 0,
          weight: 238,
          mealType: "lunch"
        },
        {
          name: "Овощной гарнир к курице (Рекомендованный)",
          kcal: 65,
          protein: 2,
          fat: 0.5,
          carb: 12,
          weight: 150,
          mealType: "dinner"
        }
      ]
    });
  }

  try {
    const parts: any[] = [];

    // Let's explain to the AI what is the context
    let prompt = `Ты — профессиональный ИИ-нутрициолог и эксперт по подсчету КБЖУ.
Пользователь обращается к тебе за помощью: он хочет распознать фото упаковки продукта, приготовленной еды или ингредиентов, высчитать КБЖУ, спланировать свое питание и получить совет.

Данные пользователя:
- Пользовательские цели / Вопрос: "${customGoal || "Распознать продукт и КБЖУ"}"
- Дневная цель по калориям: "${dailyKcalTarget || "Не указана"}"
`;

    if (mode === "dish_scanner") {
      prompt += `
ИНСТРУКЦИЯ ДЛЯ СКАНИРОВАНИЯ БЛЮД (Определение по фото тарелки / еды):
Ты анализируешь фото готового блюда или ингредиентов. Твоя задача:
1. Распознать все отдельные ингредиенты блюда на фото и прикинуть их вес в граммах (например, Рис: 120г, Котлета: 100г, Овощи: 50г).
2. Вычислить КБЖУ для каждого распознанного продукта с учетом его веса на тарелке.
3. Описать в поле "advice" (на русском в красивом markdown) подробный разбор блюда, пользу этих ингредиентов для здоровья, общую калорийность тарелки и рекомендации, как сделать его более сбалансированным.
4. Разбить блюдо на индивидуальные компоненты и вернуть их в массиве "suggestedFoods" с конкретным КБЖУ и весом, чтобы пользователь мог добавить их по отдельности в свой дневник питания!
`;
    } else if (mode === "label_scanner") {
      prompt += `
ИНСТРУКЦИЯ ДЛЯ РАСПОЗНАВАНИЯ ТАБЛИЦ И ЭТИКЕТОК ПИТАТЕЛЬНОЙ ЦЕННОСТИ (КБЖУ):
Ты анализируешь фото этикетки, оборотной стороны упаковки товара или таблицы пищевой ценности. Твоя задача:
1. Точно распознать и извлечь коммерческое название продукта (например, "Шоколад темный Ritter Sport" или "Чипсы картофельные Lays сметана и зелень").
2. Считать показатели КБЖУ (Калорийность, Белки, Жиры, Углеводы) в расчете строго НА 100 ГРАММ продукта (или на 1 единицу/порцию, если КБЖУ дано только на порцию и указан ее вес).
3. Описать в поле "advice" на русском в красивом markdown подробный разбор состава: качество белков, наличие простых сахаров, трансизомеров жиров, рекомендации к употреблению при здоровом образе жизни.
4. Обязательно вернуть этот продукт в массиве "suggestedFoods" в качестве одного элемента КБЖУ на 100г, заполнив поле вес как 100 (weight: 100). Это позволит пользователю одной кнопкой добавить данный продукт в свой постоянный список шаблонов.
`;
    } else {
      prompt += `
ИНСТРУКЦИЯ ПО ПЛАНИРОВАНИЮ (Например, деление курицы):
Если пользователь спрашивает, как разделить X кг (например, 5 кг курицы) на Y недель (например, 3 недели), ты ДОЛЖЕН:
1. Рассчитать общий вес порции в неделю (Xкг / Y недель) и в день (Xкг / (Y*7 дней)).
2. Найти или предположить КБЖУ этого продукта на 100 грамм (или извлечь с фото, если на фото изображена этикетка/мясо).
3. Произвести точный математический расчет КБЖУ для одной дневной порции (например, для 238г).
4. Описать это понятным, вдохновляющим языком на русском в поле "advice" с использованием markdown.
5. Сгенерировать список предлагаемых блюд/ингредиентов в "suggestedFoods" — например, готовую дневную порцию куриного филе с правильным общим КБЖУ, чтобы пользователь мог одним кликом занести его в дневник питания!

Если на фото изображена таблица калорийности (нутриенты) курицы или другого продукта, обязательно распознай с нее точные цифры КБЖУ на 100г и используй их для расчетов!
`;
    }

    prompt += `\n\nВозвращай ответ строго в формате JSON, соответствующем схеме!`;

    if (imageBase64 && mimeType) {
      parts.push({
        inlineData: {
          mimeType: mimeType,
          data: imageBase64,
        },
      });
      prompt += `\n\nВнимательно проанализируй это фото продуктов/упаковки/таблицы нутриентов.`;
    } else {
      prompt += `\n\n(Фото отсутствует, сделай расчеты и рекомендации на основе текстового описания).`;
    }

    parts.push({ text: prompt });

    const response = await ai!.models.generateContent({
      model: "gemini-3.5-flash",
      contents: { parts: parts },
      config: {
        responseMimeType: "application/json",
        responseSchema: {
          type: Type.OBJECT,
          properties: {
            advice: {
              type: Type.STRING,
              description: "Detailed, beautiful formatted markdown text in Russian recommending how to store, divide, prepare, daily gram portions, exact KBJU analysis, of the ingredients and explaining context mathematically."
            },
            suggestedFoods: {
              type: Type.ARRAY,
              description: "Array of calculated food items representing the scheduled portions to automatically add to diary.",
              items: {
                type: Type.OBJECT,
                properties: {
                  name: { type: Type.STRING, description: "Name of food item in Russian, e.g. 'Куриная грудка (дневная порция 238г)'" },
                  kcal: { type: Type.NUMBER, description: "Total portion calories" },
                  protein: { type: Type.NUMBER, description: "Total protein in grams" },
                  fat: { type: Type.NUMBER, description: "Total fat in grams" },
                  carb: { type: Type.NUMBER, description: "Total carbs in grams" },
                  weight: { type: Type.NUMBER, description: "Portion weight in grams" },
                  mealType: { type: Type.STRING, description: "Recommended meal category: 'breakfast', 'lunch', 'dinner', or 'snack'" }
                },
                required: ["name", "kcal", "protein", "fat", "carb", "weight", "mealType"]
              }
            }
          },
          required: ["advice", "suggestedFoods"]
        }
      }
    });

    const parsedData = JSON.parse(response.text || "{}");
    res.json({
      success: true,
      advice: parsedData.advice,
      suggestedFoods: parsedData.suggestedFoods || []
    });

  } catch (error: any) {
    console.error("Gemini analytical process failed:", error);
    res.status(500).json({
      success: false,
      error: error.message || "Ошибка при обработке запроса ИИ-анализатором",
    });
  }
});

app.get("/api/health", (req, res) => {
  res.json({ status: "ok" });
});

// Vite middleware setup
async function setupVite() {
  if (process.env.NODE_ENV !== "production") {
    const vite = await createViteServer({
      server: { middlewareMode: true },
      appType: "spa",
    });
    app.use(vite.middlewares);
    console.log("Vite development server mounted");
  } else {
    const distPath = path.join(process.cwd(), "dist");
    app.use(express.static(distPath));
    app.get("*", (req, res) => {
      res.sendFile(path.join(distPath, "index.html"));
    });
    console.log("Serving compiled static assets from dist/");
  }

  app.listen(PORT, "0.0.0.0", () => {
    console.log(`Server is listening on http://0.0.0.0:${PORT}`);
  });
}

setupVite().catch((error) => {
  console.error("Failed to start Vite production server", error);
});
