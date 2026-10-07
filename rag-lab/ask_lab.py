"""Лаборатория RAG: те же вопросы через настоящий claude_agent — без базы и с базой.

  python ask_lab.py "вопрос"                  — один вопрос, ответ с базой
  python ask_lab.py "вопрос" --no-kb          — baseline
  python ask_lab.py "вопрос" --compare        — оба ответа подряд
  python ask_lab.py --batch                   — все вопросы из test_questions.json -> reports/<дата>.md
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))

from dotenv import load_dotenv

load_dotenv(ROOT.parent / ".env")

import claude_agent  # noqa: E402
import kb_search  # noqa: E402

INSTRUCTION = (
    "Ниже — выдержки из справочных источников (реестр ветпрепаратов Россельхознадзора, FDA). "
    "Используй их как приоритетные: опирайся на них, называй источник (название препарата или документ). "
    "Числа и дозировки бери ТОЛЬКО из источников; если в источниках этого нет — скажи, что точной схемы "
    "у тебя нет, и отправь к ветеринару. Не выдумывай. Если выдержки не по теме вопроса — игнорируй их."
)


def build_context(question: str, k: int, species: str | None):
    hits = kb_search.search(question, k=k, species=species)
    if not hits:
        return None, []
    blocks = []
    for i, h in enumerate(hits, 1):
        blocks.append(f"[{i}] {h['title']} ({h['source']}, {h['url']})\n{h['text'][:1800]}")
    return INSTRUCTION + "\n\n" + "\n\n".join(blocks), hits


def compose(question: str, ctx: str | None) -> str:
    """Вопрос идёт первым, справка — после; иначе модель принимает справку за отдельную реплику."""
    if not ctx:
        return question
    return (
        f"Вопрос владельца: {question}\n\n"
        "(Служебная справка для ответа на этот вопрос. Владелец её не видит. "
        "Отвечай на вопрос сразу, опираясь на справку; не переспрашивай то, что можно ответить по ней.)\n"
        + ctx
    )


def ask(question: str, use_kb: bool, k: int = 5, species: str | None = None):
    ctx, hits = (build_context(question, k, species) if use_kb else (None, []))
    t = time.time()
    reply = claude_agent.ask_text(compose(question, ctx))
    return reply.text, reply.usage, hits, time.time() - t


def show(question, use_kb, k, species):
    text, usage, hits, sec = ask(question, use_kb, k, species)
    print(f"\n=== {'С БАЗОЙ' if use_kb else 'БЕЗ БАЗЫ'} ({sec:.1f} c, {usage}) ===")
    for i, h in enumerate(hits, 1):
        print(f"  [{i}] {h['source']}: {h['title'][:70]}")
    print(text)


def batch(k):
    qs = json.loads((ROOT / "test_questions.json").read_text(encoding="utf-8"))
    out = ["# Отчёт: baseline vs RAG\n"]
    for q in qs:
        question, species = q["q"], q.get("species")
        base, bu, _, _ = ask(question, False)
        rag, ru, hits, _ = ask(question, True, k, species)
        out.append(f"## {question}\n")
        out.append("**Найдено:** " + ("; ".join(f"{h['source']}: {h['title'][:60]}" for h in hits) or "ничего") + "\n")
        out.append(f"### Без базы\n{base}\n\n### С базой\n{rag}\n")
        print("готово:", question)
    (ROOT / "reports").mkdir(exist_ok=True)
    path = ROOT / "reports" / f"report_{time.strftime('%Y%m%d_%H%M')}.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print("отчёт:", path)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("question", nargs="?")
    ap.add_argument("--no-kb", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--batch", action="store_true")
    ap.add_argument("--species", default=None)
    ap.add_argument("-k", type=int, default=5)
    a = ap.parse_args()
    if a.batch:
        batch(a.k)
    elif a.compare:
        show(a.question, False, a.k, a.species)
        show(a.question, True, a.k, a.species)
    else:
        show(a.question, not a.no_kb, a.k, a.species)
