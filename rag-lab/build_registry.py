"""Загрузка открытого набора Россельхознадзора «Государственный реестр лекарственных
средств для ветеринарного применения (перечень лекарственных препаратов, прошедших
государственную регистрацию)» в kb.db.

Источник: https://fsvps.gov.ru/otkrytaya-sluzhba/otkrytye-dannye/ (паспорт набора
7708523530-gosreestrleksredstv). Это официальные открытые данные ведомства; поле
«Дозировка» в них — содержание действующего вещества, а НЕ схема применения, поэтому
из реестра нельзя получить ответ «сколько давать».
"""
import csv
import io
import re
import sys
from pathlib import Path

import kb_db

RAW = Path(__file__).parent / "raw" / "registry_drugs.csv"
SOURCE_URL = "https://fsvps.gov.ru/otkrytaya-sluzhba/otkrytye-dannye/"

COLUMNS = {
    "name": "Торговое наименование лекарственного препарата",
    "inn": "Международное непатентованное или химическое наименование",
    "form": "Лекарственная форма",
    "strength": "Дозировка",
    "holder": "Держатель регистрационного удостоверения",
    "group": "Фармакотерапевтическая группа, код анатомо-терапевтическо-химической классификации, рекомендованной Всемирной организацией здравоохранения",
    "indications": "Показания к применению",
    "contra": "Противопоказания",
    "side": "Побочные действия",
    "shelf": "Срок годности",
    "storage": "Условия хранения",
    "terms": "Условия отпуска",
    "reg_date": "Дата государственной регистрации",
    "reg_no": "Регистрационный №",
    "composition": "Качественный состав и количественный состав действующих веществ и качественный состав вспомогательных веществ",
    "pack": "Количество в потребительской упаковке",
}

DOG_CAT = re.compile(r"собак|кошк|кош[еа]к|щенк|котят|котов|плотоядн|мелких домашних|домашних (?:животных|плотоядных)|пушн", re.I)
LIVESTOCK_ONLY = re.compile(r"свин|крупн\w+ рогат|коров|телят|овец|коз[ыл]|лошад|птиц|цыпл|кур\b|кур[ыа]м|пчел|рыб|кролик", re.I)


def clean(s: str) -> str:
    s = (s or "").replace("\r", " ").replace("\n", " ")
    s = re.sub(r"\s+", " ", s).strip()
    # Источник отдаёт cp1251: символы вне неё (³, °, µ) уже заменены на «?».
    s = re.sub(r"(?<=\d) ?см\?", " см³", s)
    s = re.sub(r"(?<=\d) ?\?С\b", " °С", s)
    s = re.sub(r"(?<=\d) ?\?C\b", " °C", s)
    s = re.sub(r"(?<=\d) ?мк\?", " мкг", s)
    return s


def species_tag(row: dict) -> str:
    text = " ".join(row[k] for k in ("name", "inn", "indications", "contra", "group"))
    has_pet = bool(DOG_CAT.search(text))
    only_farm = bool(LIVESTOCK_ONLY.search(text)) and not has_pet
    if has_pet:
        return "dog_cat"
    if only_farm:
        return "farm"
    return "other"


def main():
    raw = RAW.read_bytes().decode("cp1251", errors="replace")
    reader = csv.DictReader(io.StringIO(raw), delimiter=";", quotechar='"')
    conn = kb_db.connect()
    kb_db.reset_source(conn, "registry")

    total = kept = 0
    by_tag = {"dog_cat": 0, "farm": 0, "other": 0}
    for rec in reader:
        total += 1
        row = {k: clean(rec.get(col, "")) for k, col in COLUMNS.items()}
        if not row["name"]:
            continue
        tag = species_tag(row)
        by_tag[tag] += 1
        if tag == "farm":
            continue  # сельхозпрепараты боту для питомцев не нужны
        title = f"{row['name']}" + (f" ({row['inn']})" if row["inn"] else "")
        parts = [
            f"Препарат: {row['name']}.",
            f"МНН/состав: {row['inn']}." if row["inn"] else "",
            f"Форма: {row['form']}." if row["form"] else "",
            f"Содержание действующего вещества: {row['strength']}." if row["strength"] else "",
            f"Группа: {row['group']}." if row["group"] else "",
            f"Показания: {row['indications']}" if row["indications"] else "",
            f"Противопоказания: {row['contra']}" if row["contra"] else "",
            f"Побочные действия: {row['side']}" if row["side"] else "",
            f"Условия отпуска: {row['terms']}." if row["terms"] else "",
            f"Срок годности: {row['shelf']}" if row["shelf"] else "",
            f"Хранение: {row['storage']}" if row["storage"] else "",
            f"Регистрационный №: {row['reg_no']}, дата регистрации {row['reg_date']}." if row["reg_no"] else "",
            f"Держатель РУ: {row['holder'][:120]}." if row["holder"] else "",
        ]
        text = "\n".join(p for p in parts if p)
        kb_db.add_chunk(
            conn,
            source="registry",
            species=tag,
            title=title,
            url=SOURCE_URL,
            text=text,
            extra=row["reg_no"],
        )
        kept += 1
    conn.commit()
    print(f"строк в файле: {total}; в базу: {kept}; по группам: {by_tag}")


if __name__ == "__main__":
    sys.exit(main())
