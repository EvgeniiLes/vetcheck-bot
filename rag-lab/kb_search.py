"""Поиск по базе знаний: FTS5 (BM25) + грубый русский стемминг по префиксу."""
import re

import kb_db

# Бренды, которые владельцы пишут латиницей, а в реестре они кириллицей.
BRAND_ALIASES = {
    "bravecto": "бравекто", "nexgard": "нексгард", "simparica": "симпарика",
    "credelio": "кределио", "frontline": "фронтлайн", "stronghold": "стронгхолд",
    "advocate": "адвокат", "drontal": "дронтал", "milbemax": "мильбемакс",
    "prazitel": "празител", "revolution": "революшн", "seresto": "серест",
    "cerenia": "серения", "rimadyl": "римадил", "metacam": "мелоксикам",
    "synulox": "синулокс", "amoxicillin": "амоксициллин", "ibuprofen": "ибупрофен",
    "paracetamol": "парацетамол",
}


def build_match(question: str) -> str:
    parts = []
    for tok in kb_db.tokens(question):
        tok = BRAND_ALIASES.get(tok, tok)
        parts.append(f'"{tok}"*' if not re.fullmatch(r"[a-z0-9]+", tok) else f'"{tok}"')
    return " OR ".join(parts)


def search(question: str, k: int = 5, species: str | None = None, sources: tuple[str, ...] | None = None):
    match = build_match(question)
    if not match:
        return []
    conn = kb_db.connect()
    sql = (
        "SELECT c.id, c.source, c.species, c.title, c.url, c.text, c.original, c.extra, "
        "bm25(chunks_fts, 4.0, 1.0) AS score "
        "FROM chunks_fts JOIN chunks c ON c.id = chunks_fts.rowid "
        "WHERE chunks_fts MATCH ?"
    )
    args: list = [match]
    if sources:
        sql += " AND c.source IN (%s)" % ",".join("?" * len(sources))
        args += list(sources)
    sql += " ORDER BY score LIMIT ?"
    args.append(k * 3)
    rows = [dict(r) for r in conn.execute(sql, args)]
    conn.close()
    if species:
        pref = [r for r in rows if r["species"] in (species, "dog_cat", "other")]
        rows = pref or rows
    # Препарат, названный в вопросе, — всегда первым (BM25 по длинному тексту его теряет).
    toks = [BRAND_ALIASES.get(t, t) for t in kb_db.tokens(question)]
    toks = [t for t in toks if len(t) >= 4]
    rows.sort(key=lambda r: 0 if any(t in r["title"].lower().replace("ё", "е") for t in toks) else 1)
    # Не более двух кусков из одного документа — иначе один источник заглушит остальные.
    seen: dict[str, int] = {}
    out = []
    for r in rows:
        key = r["title"] if r["source"] == "fda" else r["id"]
        seen[key] = seen.get(key, 0) + 1
        if r["source"] == "fda" and seen[key] > 2:
            continue
        out.append(r)
        if len(out) >= k:
            break
    return out
