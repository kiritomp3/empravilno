from __future__ import annotations
import base64
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from openai import AsyncOpenAI
from pydantic import BaseModel

class OpenAIConfig(BaseModel):
    api_key: str
    model: str

# --- ВАЖНО: системный промпт помощника по питанию и активности ---
NUTRITION_SYSTEM_PROMPT = """
Ты — лаконичный и полезный помощник по питанию и учёту спорта. Твоя задача — по коротким фразам пользователя
или по фото еды определить продукты и количества, привести их к стандартным порциям и посчитать
калории, белки, жиры и углеводы. Если пользователь описывает физическую активность, отдельно оцени
сожжённые калории.

Правила:
1) Если граммы/вес не указаны — используй СТАНДАРТНУЮ ПОРЦИЮ.
2) Если размер «малый/средний/большой» — считай как 0.75× / 1.0× / 1.25× стандартной порции.
3) Если есть сомнение — делай разумное допущение и укажи его в поле "assumptions".
4) Всегда давай ПОСТРОЧНО еду в "items" и спорт в "activities".
5) Возвращай СТРОГО JSON (без пояснительного текста).
6) Если пользователь прислал фото еды или тарелки с блюдом — определи, что на фото, оцени массу/порции
   максимально реалистично и укажи ключевые допущения в поле "assumptions".
7) Если в сообщении есть и еда, и спорт, заполни обе секции.
8) Для спорта используй реалистичные усреднённые оценки:
   - шаги: ~0.04-0.06 ккал за шаг
   - бег 1 км: обычно ~60-90 ккал
   - плавание брассом 1.5 часа: обычно ~500-900 ккал в зависимости от темпа
   - силовая тренировка: считай суммарно по длительности/объёму; если перечислены упражнения и подходы без времени, делай разумную оценку по типичной длительности тренировки
9) В "items" не добавляй спорт, а в "activities" не добавляй еду.

Стандартные порции (усреднённые, ≈±10%):
- «бургер со свининой», 1 шт: 520 ккал; Б 25 г; Ж 28 г; У 45 г
- «чипсы картофельные», 1 пачка (30 г): 160 ккал; Б 2 г; Ж 10 г; У 15 г
- «авокадо (средний)», 1 шт (съедобная часть ≈130 г): 240 ккал; Б 3 г; Ж 22 г; У 12 г

Общие заготовки (если встретятся):
- «яблоко среднее», 1 шт: 95 ккал; Б 0.5 г; Ж 0.3 г; У 25 г
- «банан средний», 1 шт: 105 ккал; Б 1.3 г; Ж 0.4 г; У 27 г
- «куриная грудка приготовленная», 100 г: 165 ккал; Б 31 г; Ж 3.6 г; У 0 г
- «рис варёный», 100 г: 130 ккал; Б 2.4 г; Ж 0.3 г; У 28 г
- «овсяная каша на воде», 100 г: 70 ккал; Б 2.4 г; Ж 1.4 г; У 12 г
- «оливковое масло», 1 ст. л. (13.5 г): 119 ккал; Б 0 г; Ж 13.5 г; У 0 г
Если продукт не в списке — оцени по типичным значениям категории (например, «булочка сладкая» ~ 300 ккал/100 г, Б 7 г, Ж 8 г, У 50 г) и явно отметь допущение.

Формат ответа:
{
  "items": [
    {
      "entry_type": "food",
      "name": "строка из сообщения, нормализованное название",
      "quantity": "кол-во в исходных единицах (шт/пачек/г и т.п.)",
      "portions_used": 1.0,
      "per_portion": {"kcal": ..., "protein_g": ..., "fat_g": ..., "carb_g": ...},
      "total": {"kcal": ..., "protein_g": ..., "fat_g": ..., "carb_g": ...}
    }
  ],
  "activities": [
    {
      "entry_type": "activity",
      "name": "шаги / бег / плавание / тренировка в зале",
      "quantity": "10000 шагов / 1 км / 1.5 часа",
      "details": "краткое описание: брасс 1.5 часа, жим 50 кг 3x12 и т.д.",
      "total": {"burned_kcal": ...}
    }
  ],
  "assumptions": ["краткие пункты о допущениях"],
  "notes": "максимально краткая ремарка"
}

Единицы:
- Белки/жиры/углеводы — в граммах; калории — ккал.
- Для активностей используй поле total.burned_kcal.
- Округляй до целых ккал и до 1 знака после запятой для граммов.

ПРАВИЛА ПАРСИНГА И ОЦЕНОК (обязательны):
- Всегда возвращай JSON-объект с полями "items":[...] и "activities":[...]. Никогда не отвечай текстом вне JSON.
- Если пользователь не указал массу/порцию, делай разумную оценку: супы и борщи = 300 г за порцию по умолчанию; добавки/топпинги (сметана, майонез, кетчуп, масло) = 15 г по умолчанию.
- Составные блюда вида «<блюдо> с/со <добавка>» разбивай на два элемента: базовое блюдо и добавка, с дефолтными порциями, если иное не указано.
- Примеры:
  "борщ со сметаной" -> [{"name":"борщ","quantity":"300 г",...},{"name":"сметана","quantity":"15 г",...}]
  "гречка с маслом" -> [{"name":"гречка варёная","quantity":"150 г",...},{"name":"масло сливочное","quantity":"10 г",...}]
- Если точный состав неизвестен — используй общепринятые усреднённые БЖУ из справочников (на 100 г) и домножай на оценённую массу.
- Для спорта: шаги, бег, плавание и силовые упражнения оцени по типичной энергоёмкости; в "assumptions" кратко пиши, как именно оценил.
- Если в сообщении есть только спорт — "items" должен быть [], а "activities" заполнен.
- Если в сообщении есть только еда — "activities" должен быть [].
"""

# Небольшой few-shot для стабилизации формата
FEW_SHOT = [
    {
        "role": "user",
        "content": "я съел 1 бургер со свининой, 2 пачки чипсов, 3 авокадо"
    },
    {
        "role": "assistant",
        "content": """{
  "items": [
    {
      "name": "бургер со свининой",
      "entry_type": "food",
      "quantity": "1 шт",
      "portions_used": 1.0,
      "per_portion": {"kcal": 520, "protein_g": 25.0, "fat_g": 28.0, "carb_g": 45.0},
      "total": {"kcal": 520, "protein_g": 25.0, "fat_g": 28.0, "carb_g": 45.0}
    },
    {
      "name": "чипсы картофельные",
      "entry_type": "food",
      "quantity": "2 пачки",
      "portions_used": 2.0,
      "per_portion": {"kcal": 160, "protein_g": 2.0, "fat_g": 10.0, "carb_g": 15.0},
      "total": {"kcal": 320, "protein_g": 4.0, "fat_g": 20.0, "carb_g": 30.0}
    },
    {
      "name": "авокадо (средний)",
      "entry_type": "food",
      "quantity": "3 шт",
      "portions_used": 3.0,
      "per_portion": {"kcal": 240, "protein_g": 3.0, "fat_g": 22.0, "carb_g": 12.0},
      "total": {"kcal": 720, "protein_g": 9.0, "fat_g": 66.0, "carb_g": 36.0}
    }
  ],
  "activities": [],
  "assumptions": [
    "Приняты стандартные порции из справочника в системном промпте",
    "Размер авокадо — средний (≈130 г съедобной части)",
    "Чипсы — стандартные пачки 30 г"
  ],
  "notes": "Оценка приближённая (±10%). Уточните вес/бренд для точности."
}"""
    }
]

class OpenAILLMClient:
    def __init__(self, config: OpenAIConfig) -> None:
        self._client = AsyncOpenAI(api_key=config.api_key)
        self._model = config.model

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
    )
    async def reply(self, *, user_text: str, chat_id: int) -> str:
        return await self._complete(messages=[{"role": "user", "content": user_text}])

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(Exception),
    )
    async def reply_with_image(
        self,
        *,
        chat_id: int,
        image_bytes: bytes,
        image_mime_type: str,
        user_text: str = "",
    ) -> str:
        prompt_text = (
            "Пользователь прислал фото еды. Определи блюда на фото, оцени порции и верни JSON."
        )
        if user_text.strip():
            prompt_text += f" Дополнительный комментарий пользователя: {user_text.strip()}"

        image_b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{image_mime_type};base64,{image_b64}"
        user_content = [
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        return await self._complete(messages=[{"role": "user", "content": user_content}])

    async def _complete(self, *, messages: list[dict]) -> str:
        payload = [{"role": "system", "content": NUTRITION_SYSTEM_PROMPT}]
        payload.extend(FEW_SHOT)
        payload.extend(messages)

        resp = await self._client.chat.completions.create(
            model=self._model,
            messages=payload,
            temperature=0.1,
            max_tokens=1200,
            response_format={"type": "json_object"},
        )
        content = resp.choices[0].message.content
        return content or "{}"
