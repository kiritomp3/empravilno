from __future__ import annotations
import json
import re
from typing import Any

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def _escape_inner_quotes(candidate: str) -> str:
    """
    Мягко чинит частый ответ модели: неэкранированные кавычки внутри строковых значений.
    """
    result: list[str] = []
    in_string = False
    escaped = False
    length = len(candidate)

    for idx, char in enumerate(candidate):
        if escaped:
            result.append(char)
            escaped = False
            continue

        if char == "\\":
            result.append(char)
            escaped = True
            continue

        if char == '"':
            if not in_string:
                in_string = True
                result.append(char)
                continue

            next_non_ws = ""
            for next_idx in range(idx + 1, length):
                probe = candidate[next_idx]
                if not probe.isspace():
                    next_non_ws = probe
                    break

            if next_non_ws in {",", "}", "]", ":"} or next_non_ws == "":
                in_string = False
                result.append(char)
            else:
                result.append('\\"')
            continue

        result.append(char)

    return "".join(result)


def _load_json_with_repairs(candidate: str) -> dict[str, Any]:
    normalized = candidate.strip()
    attempts = [
        normalized,
        re.sub(r",\s*([\}\]])", r"\1", normalized),
        _escape_inner_quotes(re.sub(r",\s*([\}\]])", r"\1", normalized)),
    ]

    last_error: Exception | None = None
    for attempt in attempts:
        try:
            return json.loads(attempt)
        except Exception as exc:
            last_error = exc

    if last_error:
        raise last_error
    raise ValueError("unable to parse json")

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
            return _load_json_with_repairs(candidate)
        except Exception:
            # пойдём дальше — попробуем универсальный захват
            pass

    # 2) Универсальный захват: от первой '{' до последней '}'
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no JSON object found")
    candidate = text[start:end + 1].strip()
    return _load_json_with_repairs(candidate)
