from __future__ import annotations
import json
import re
from typing import Any

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)

def extract_json_object(text: str) -> dict[str, Any]:
    """
    Пытается достать первый валидный JSON-объект из строки:
    - поддерживает блоки ```json ... ```
    - убирает префикс/суффикс вокруг { ... }
    - аккуратно подрезает по первой '{' и последней '}'
    - если не удаётся распарсить, поднимает ValueError
    """

    if not text:
        raise ValueError("empty content")

    # 1) Сначала ищем fenced-блок ```json ... ```
    m = _JSON_FENCE_RE.search(text)
    if m:
        candidate = m.group(1).strip()
        try:
            return json.loads(candidate)
        except Exception:
            # пойдём дальше — попробуем универсальный захват
            pass

    # 2) Универсальный захват: от первой '{' до последней '}'
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found")
    candidate = text[start:end + 1].strip()

    # Иногда модель возвращает лишние запятые перед закрывающими скобками — подчищаем простые случаи
    candidate = re.sub(r",\s*([\}\]])", r"\1", candidate)

    return json.loads(candidate)