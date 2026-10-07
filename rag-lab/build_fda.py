"""Загрузка страниц FDA (Center for Veterinary Medicine) для владельцев питомцев.

Лицензия: материалы fda.gov — общественное достояние (федеральное правительство США),
https://www.fda.gov/about-fda/about-website/website-policies#linking
Берём только страницы раздела animal-health-literacy и safety-health, которые касаются
собак/кошек. Текст на английском; для поиска по русским вопросам переводим фрагменты
на русский (перевод сохраняется рядом с оригиналом, источник — ссылка на страницу FDA).

Запуск:  python build_fda.py fetch      — скачать и разобрать страницы в raw/fda/*.json
         python build_fda.py translate  — перевести фрагменты и положить в kb.db
"""
import html
import json
import re
import sys
import time
from html.parser import HTMLParser
from pathlib import Path

import requests

import kb_db

ROOT = Path(__file__).parent
RAW = ROOT / "raw" / "fda"
H = {"User-Agent": "Mozilla/5.0 (kb-lab research; contact: admin)"}
BASE = "https://www.fda.gov"

HUBS = [
    "/animal-veterinary/animal-health-literacy/dangers-pets",
    "/animal-veterinary/animal-health-literacy/pet-food-and-treats",
    "/animal-veterinary/animal-health-literacy/other-pet-health-topics",
    "/animal-veterinary/animal-health-literacy/keep-worms-out-your-pets-heart-facts-about-heartworm-disease",
    "/animal-veterinary/resources-you/animal-health-literacy",
    "/animal-veterinary/safety-health/antiparasitic-resistance",
    "/animal-veterinary/safety-health/frequently-asked-questions-about-animal-drugs",
]
PET = re.compile(r"dog|cat|pet|feline|canine|flea|tick|heartworm|isoxazol|xylitol|toxic|poison|nsaid|pain|antibiot|antimicrob|raw|treat|dental|chew|parasit|dcm|grain|supplement|compound|adverse|food|diet|medic|drug|vomit|worm|dehydrat|jerky|tail|travel", re.I)
SKIP = re.compile(r"cattle|swine|chicken|poultry|horse|equine|livestock|food-producing|screwworm|african-swine|cloning|aquaculture|bee|fish|recall|withdraw|warning-letter|press|webinar|jobs|careers", re.I)


class TextExtractor(HTMLParser):
    """Достаёт текст из <main>, пропуская навигацию, скрипты и т.п."""
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "tr", "br", "div", "section"}
    DROP = {"script", "style", "nav", "header", "footer", "aside", "form", "noscript", "svg", "button"}

    def __init__(self):
        super().__init__()
        self.in_main = 0
        self.drop = 0
        self.buf: list[str] = []
        self.title = ""
        self._in_h1 = False

    def handle_starttag(self, tag, attrs):
        if tag == "main":
            self.in_main += 1
        if tag in self.DROP:
            self.drop += 1
        if self.in_main and not self.drop:
            if tag == "h1":
                self._in_h1 = True
            if tag in self.BLOCK:
                self.buf.append("\n")
            if tag == "li":
                self.buf.append("- ")

    def handle_endtag(self, tag):
        if tag == "main":
            self.in_main = max(0, self.in_main - 1)
        if tag in self.DROP:
            self.drop = max(0, self.drop - 1)
        if tag == "h1":
            self._in_h1 = False
        if self.in_main and not self.drop and tag in self.BLOCK:
            self.buf.append("\n")

    def handle_data(self, data):
        if self.in_main and not self.drop:
            if self._in_h1:
                self.title += data
            self.buf.append(data)


def parse(page_html: str) -> tuple[str, str]:
    p = TextExtractor()
    p.feed(page_html)
    text = html.unescape("".join(p.buf))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    return re.sub(r"\s+", " ", html.unescape(p.title)).strip(), text


def links_from(path: str) -> dict[str, str]:
    r = requests.get(BASE + path, headers=H, timeout=40)
    out = {}
    if r.status_code != 200:
        return out
    for href, text in re.findall(r'<a[^>]+href="([^"#?]+)"[^>]*>(.*?)</a>', r.text, re.S):
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()
        if href.startswith("/"):
            href = BASE + href
        if "fda.gov/animal-veterinary/" in href and text and len(text) > 6:
            out[href.split("?")[0]] = text
    return out


def cmd_fetch():
    RAW.mkdir(parents=True, exist_ok=True)
    cand: dict[str, str] = {}
    for hub in HUBS:
        for u, t in links_from(hub).items():
            cand[u] = t
        time.sleep(0.5)
    urls = [u for u, t in cand.items()
            if ("/animal-health-literacy/" in u or "/safety-health/" in u)
            and (PET.search(u) or PET.search(cand[u])) and not SKIP.search(u)]
    urls = sorted(set(urls))
    print(f"кандидатов: {len(cand)}, к загрузке: {len(urls)}")
    saved = 0
    for u in urls:
        slug = re.sub(r"[^a-z0-9]+", "-", u.split("/animal-veterinary/")[-1].lower()).strip("-")[:90]
        path = RAW / f"{slug}.json"
        if path.exists():
            continue
        try:
            r = requests.get(u, headers=H, timeout=40)
        except Exception as e:
            print("ERR", u, e)
            continue
        if r.status_code != 200:
            print(r.status_code, u)
            continue
        title, text = parse(r.text)
        if len(text) < 600:
            print("короткая, пропуск:", u, len(text))
            continue
        path.write_text(json.dumps({"url": u, "title": title or cand[u], "text": text}, ensure_ascii=False, indent=1), encoding="utf-8")
        saved += 1
        print(f"  + {title or cand[u]} ({len(text)} симв.)")
        time.sleep(0.6)
    print("сохранено:", saved)


def chunk(text: str, limit: int = 1800) -> list[str]:
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) > limit:
            chunks.append(cur.strip())
            cur = ""
        cur += p + "\n\n"
    if cur.strip():
        chunks.append(cur.strip())
    return chunks


def cmd_translate():
    import os
    from dotenv import load_dotenv
    load_dotenv(ROOT.parent / ".env")
    import anthropic
    client = anthropic.Anthropic()
    conn = kb_db.connect()
    kb_db.reset_source(conn, "fda")
    files = sorted(RAW.glob("*.json"))
    print("страниц:", len(files))
    n_chunks = 0
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        if re.search(r"Español|Sheep|Idea to the Marketplace|^Dangers for Pets|^Pet Food and Treats$|^Pet Meds$", doc["title"]):
            continue
        for i, part in enumerate(chunk(doc["text"])):
            resp = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=2500,
                system=(
                    "Ты переводчик ветеринарных текстов с английского на русский. Переводи точно, "
                    "без добавлений и сокращений. Названия препаратов и торговые марки оставляй как в оригинале "
                    "(латиницей), рядом в скобках можно дать общепринятую русскую форму. Сохраняй числа и единицы. "
                    "Выведи ТОЛЬКО перевод."
                ),
                messages=[{"role": "user", "content": part}],
            )
            ru = "".join(b.text for b in resp.content if b.type == "text").strip()
            kb_db.add_chunk(
                conn, source="fda", species="dog_cat",
                title=doc["title"], url=doc["url"], text=ru, original=part, extra=str(i),
            )
            n_chunks += 1
        conn.commit()
        print(f"  {doc['title'][:70]}")
    print("фрагментов в базе:", n_chunks)


if __name__ == "__main__":
    {"fetch": cmd_fetch, "translate": cmd_translate}[sys.argv[1]]()
