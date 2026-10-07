"""Хранилище базы знаний (лаборатория). Отдельный файл kb.db — боевую схему
vetbot.db/core.db не трогаем."""
import re
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "kb.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    id       INTEGER PRIMARY KEY,
    source   TEXT NOT NULL,        -- registry | fda
    species  TEXT NOT NULL,        -- dog_cat | dog | cat | other
    title    TEXT NOT NULL,
    url      TEXT NOT NULL,
    text     TEXT NOT NULL,        -- то, что ищем и показываем модели (по-русски)
    original TEXT,                 -- английский оригинал (для FDA)
    extra    TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    title, text, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2'
);
"""


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def reset_source(conn, source: str) -> None:
    conn.execute("DELETE FROM chunks WHERE source = ?", (source,))
    conn.execute("INSERT INTO chunks_fts(chunks_fts) VALUES('rebuild')")
    conn.commit()


def add_chunk(conn, *, source, species, title, url, text, original=None, extra=None) -> int:
    cur = conn.execute(
        "INSERT INTO chunks(source, species, title, url, text, original, extra) VALUES (?,?,?,?,?,?,?)",
        (source, species, title, url, text, original, extra),
    )
    rowid = cur.lastrowid
    conn.execute("INSERT INTO chunks_fts(rowid, title, text) VALUES (?,?,?)", (rowid, title, text))
    return rowid


STOP = set("""а без более бы был была были было быть в вам вас ведь весь во вот все всего вы где да даже для до его ее ей ему если есть еще же за здесь и из или им их к как ко когда кто ли либо мне может мое можно мой мы на над надо наш не него нет ни них но ну о об однако он она они оно от очень по под после потому при про с со так также такой там те тем то того тоже той только том ты у уже хотя чего чей чем что чтобы чье чья эта эти это я
собака собаки собаку собаке собаку кошка кошки кошку кошке мой моя моей моего нужно надо можно ли какие какой какая какое""".split())

ENDINGS = re.compile(r"(?:ировать|ирует|ировал|ования|ование|ением|ения|ение|ыми|ими|ами|ями|ого|его|ому|ему|ых|их|ов|ев|ей|ом|ем|ах|ях|ою|ею|ая|яя|ое|ее|ые|ие|ый|ий|ой|ла|ло|ли|ет|ут|ют|ит|ат|ят|ть|ся|ы|и|а|я|у|ю|е|о|ь)$")

TRANSLIT = {"a":"а","b":"б","c":"к","d":"д","e":"е","f":"ф","g":"г","h":"х","i":"и","j":"дж","k":"к","l":"л","m":"м","n":"н","o":"о","p":"п","q":"к","r":"р","s":"с","t":"т","u":"у","v":"в","w":"в","x":"кс","y":"и","z":"з"}


def stem(word: str) -> str:
    w = word.lower().replace("ё", "е")
    if re.fullmatch(r"[a-z0-9]+", w):
        return w  # латиница как есть; транслитерация — в kb_search
    s = ENDINGS.sub("", w)
    return s if len(s) >= 4 else w


def tokens(query: str) -> list[str]:
    words = re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", query)
    out = []
    for w in words:
        lw = w.lower()
        if lw in STOP or len(lw) < 3:
            continue
        out.append(stem(lw))
    return out
