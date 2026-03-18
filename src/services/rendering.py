from __future__ import annotations
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from html import escape
from typing import Iterable
import tempfile
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
from openpyxl import load_workbook

def _to_decimal(v) -> Decimal:
    try:
        return Decimal(str(v))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")

def _round_macro(v, digits=1) -> float:
    try:
        quant = Decimal("1") if digits == 0 else Decimal("1").scaleb(-digits)
        return float(_to_decimal(v).quantize(quant, rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0

def _num(v, digits=1):
    try:
        if isinstance(v, (int,)):
            return str(v)
        f = float(v)
        s = f"{f:.{digits}f}".rstrip("0").rstrip(".")
        return s if s else "0"
    except Exception:
        return str(v)

def render_day_table(items: list[dict]) -> str:
    """
    Рендерит таблицу в HTML <pre> с ровными колонками.
    Каждый элемент items — dict c полями:
      - name: str
      - total: { kcal, protein_g, fat_g, carb_g }
    """
    rows = []
    totals = {
        "kcal": Decimal("0"),
        "protein_g": Decimal("0"),
        "fat_g": Decimal("0"),
        "carb_g": Decimal("0"),
    }

    for it in items:
        name = (it.get("name") or "—").strip()
        total = it.get("total") or {}
        kcal = int(_round_macro(total.get("kcal", 0), 0))
        p = _round_macro(total.get("protein_g", 0))
        f = _round_macro(total.get("fat_g", 0))
        c = _round_macro(total.get("carb_g", 0))

        rows.append((name, kcal, p, f, c))
        totals["kcal"] += _to_decimal(total.get("kcal", 0))
        totals["protein_g"] += _to_decimal(total.get("protein_g", 0))
        totals["fat_g"] += _to_decimal(total.get("fat_g", 0))
        totals["carb_g"] += _to_decimal(total.get("carb_g", 0))

    totals["kcal"] = int(_round_macro(totals["kcal"], 0))
    totals["protein_g"] = _round_macro(totals["protein_g"], 1)
    totals["fat_g"] = _round_macro(totals["fat_g"], 1)
    totals["carb_g"] = _round_macro(totals["carb_g"], 1)

    if not rows:
        return "<pre>Пусто</pre>"

    # ширина колонки "Блюдо"
    name_w = max(6, min(40, max(len(r[0]) for r in rows)))  # не растягиваем бесконечно
    head = f"{'Блюдо'.ljust(name_w)}  {'ккал':>6}  {'Б':>5}  {'Ж':>5}  {'У':>5}"
    sep  = f"{'─'*name_w}  {'─'*6}  {'─'*5}  {'─'*5}  {'─'*5}"
    lines = [head, sep]

    for n,k,p,f,c in rows:
        # экранируем HTML, чтобы не сломать разметку, и ужимаем длинные названия
        n_disp = escape(n[:name_w])
        lines.append(
            f"{n_disp.ljust(name_w)}  {str(k).rjust(6)}  {_num(p):>5}  {_num(f):>5}  {_num(c):>5}"
        )

    lines.append(sep)
    lines.append(
        f"{'ИТОГО'.ljust(name_w)}  {str(totals['kcal']).rjust(6)}  "
        f"{_num(totals['protein_g']):>5}  {_num(totals['fat_g']):>5}  {_num(totals['carb_g']):>5}"
    )
    return "<pre>\n" + "\n".join(lines) + "\n</pre>"

def items_to_dataframe(items: list[dict]) -> pd.DataFrame:
    """
    Превращает список записей дневника в DataFrame с итоговой строкой.
    Ожидаемый формат item:
      {
        "name": str,
        "quantity": "100 г" | "1 шт" | ...,
        "total": {"kcal": int, "protein_g": float, "fat_g": float, "carb_g": float}
      }
    """
    rows = []
    totals = {
        "kcal": Decimal("0"),
        "protein_g": Decimal("0"),
        "fat_g": Decimal("0"),
        "carb_g": Decimal("0"),
    }
    for it in items:
        name = it.get("name", "")
        qty  = it.get("quantity", "")
        tot  = it.get("total", {}) or {}
        kcal = int(_round_macro(tot.get("kcal", 0), 0))
        protein = _round_macro(tot.get("protein_g", 0.0))
        fat = _round_macro(tot.get("fat_g", 0.0))
        carb = _round_macro(tot.get("carb_g", 0.0))
        rows.append({
            "Название": name,
            "Кол-во": qty,
            "Ккал": kcal,
            "Белки, г": protein,
            "Жиры, г": fat,
            "Углеводы, г": carb,
        })
        totals["kcal"] += _to_decimal(tot.get("kcal", 0))
        totals["protein_g"] += _to_decimal(tot.get("protein_g", 0))
        totals["fat_g"] += _to_decimal(tot.get("fat_g", 0))
        totals["carb_g"] += _to_decimal(tot.get("carb_g", 0))

    df = pd.DataFrame(rows, columns=["Название", "Кол-во", "Ккал", "Белки, г", "Жиры, г", "Углеводы, г"])

    if not df.empty:
        totals = {
            "Название": "ИТОГО",
            "Кол-во": "",
            "Ккал": int(_round_macro(totals["kcal"], 0)),
            "Белки, г": _round_macro(totals["protein_g"], 1),
            "Жиры, г": _round_macro(totals["fat_g"], 1),
            "Углеводы, г": _round_macro(totals["carb_g"], 1),
        }
        df = pd.concat([df, pd.DataFrame([totals])], ignore_index=True)

    return df

def save_dataframe_as_xlsx(df: pd.DataFrame, base_name: str = "nutrition_day") -> Path:
    """
    Сохраняет DataFrame в .xlsx и возвращает путь к файлу.
    """
    tmpdir = Path(tempfile.gettempdir())
    path = tmpdir / f"{base_name}.xlsx"
    df.to_excel(path, index=False)
    wb = load_workbook(path)
    ws = wb.active
    for row in ws.iter_rows(min_row=2):
        if len(row) >= 6:
            row[2].number_format = "0"
            row[3].number_format = "0.0"
            row[4].number_format = "0.0"
            row[5].number_format = "0.0"
    wb.save(path)
    return path

def save_dataframe_as_csv(df: pd.DataFrame, base_name: str = "nutrition_day") -> Path:
    """
    Сохраняет DataFrame в .csv (UTF-8) и возвращает путь к файлу.
    """
    tmpdir = Path(tempfile.gettempdir())
    path = tmpdir / f"{base_name}.csv"
    df.to_csv(path, index=False)
    return path

def render_dataframe_to_png(
    df: pd.DataFrame,
    base_name: str = "nutrition_day",
    # ключевые ручки масштаба ↓
    target_width_px: int | None = 2400,   # итоговая ширина в пикселях (None = по умолчанию)
    target_height_px: int | None = None,  # высота; если None — вычислим по строкам
    dpi: int = 300,                       # плотность пикселей (влияет на чёткость текста)
    font_size: int = 11,                  # базовый размер шрифта в таблице
    xscale: float = 1.15,                 # горизонтальный масштаб ячеек
    yscale: float = 1.35,                 # вертикальный масштаб ячеек
    pad_inches: float = 0.15,             # поля вокруг рисунка
    use_tight_layout: bool = False        # можно отключить сжатие
) -> Path:
    """
    Рисует таблицу в PNG (без осей) и возвращает путь к картинке.
    Делает изображение физически больше (по пикселям) и реально задаёт ширины столбцов.
    """
    tmpdir = Path(tempfile.gettempdir())
    path = tmpdir / f"{base_name}.png"

    # --- оценка размеров таблицы ---
    n_rows, n_cols = df.shape
    # длина в символах для каждой колонки (учтём и заголовок)
    sym_widths = []
    for col in df.columns:
        max_cell = int(max(df[col].astype(str).map(len).max() if not df.empty else 0, len(str(col))))
        sym_widths.append(max(4, min(36, int(max_cell * 1.0))))  # чуть щедрее, чем было

    # нормируем ширины столбцов в долях от оси (sum ≈ 1.0)
    total = sum(sym_widths) or 1
    col_fracs = [w / total for w in sym_widths]

    # --- расчёт физического размера рисунка ---
    # если задана целевая ширина в пикселях — переведём её в дюймы через dpi
    if target_width_px is None:
        target_width_in = max(8.0, total * 0.28)  # запас по умолчанию
    else:
        target_width_in = max(6.0, target_width_px / dpi)

    # высота: базово ~ 0.6" на строку + строка заголовка
    base_height_in = (n_rows + 1) * 0.6
    if target_height_px is not None:
        target_height_in = max(base_height_in, target_height_px / dpi)
    else:
        target_height_in = max(3.0, base_height_in)

    plt.figure(figsize=(target_width_in, target_height_in), dpi=dpi)
    ax = plt.gca()
    ax.axis('off')

    # создаём таблицу и применяем ДОЛИ ширин столбцов
    table = ax.table(
        cellText=df.values,
        colLabels=list(df.columns),
        colWidths=col_fracs,   # <- реально работает, в долях от ширины осей
        loc='center'
    )

    # шрифт
    table.auto_set_font_size(False)
    table.set_fontsize(font_size)

    # масштаб ячеек (увеличивает paddings/высоту/ширину содержимого)
    table.scale(xscale, yscale)

    # жирным строку "ИТОГО" (если есть)
    if n_rows > 0 and str(df.iloc[-1, 0]) == "ИТОГО":
        last_idx = n_rows - 1
        for j in range(n_cols):
            cell = table[(last_idx + 1, j)]  # +1 — из-за строки заголовков
            cell.set_text_props(fontweight='bold')

    if use_tight_layout:
        plt.tight_layout()
    plt.savefig(path, bbox_inches='tight', pad_inches=pad_inches)
    plt.close()
    return path

def build_day_files(items: list[dict], prefer_xlsx: bool = True) -> dict:
    """
    Универсальная «сборка»: из элементов делает DataFrame,
    сохраняет CSV/XLSX и PNG, возвращает словарь с путями.
    """
    df = items_to_dataframe(items)
    base = "nutrition_day"

    xlsx = save_dataframe_as_xlsx(df, base) if prefer_xlsx else None
    csv  = None if prefer_xlsx else save_dataframe_as_csv(df, base)
    png  = render_dataframe_to_png(df, base_name="nutrition_day_big",
                        target_width_px=4500, dpi=400,
                        font_size=15, xscale=1.2, yscale=2.5)

    return {
        "png": png,
        "xlsx": xlsx,
        "csv": csv,
        "caption": "Дневник питания за день",
        "empty": df.empty,
    }
