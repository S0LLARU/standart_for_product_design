#!/usr/bin/env python3
"""Собирает человеческий чек-лист из STANDARD.md и checklist/items.toml.

Нормативный текст, уровень и этап требований читаются из STANDARD.md,
вопросы и подсказки — из checklist/items.toml. Скрипт проверяет, что
оба источника описывают одни и те же требования, и записывает:

  site/checklist.html     — интерактивный чек-лист
  checklists/WORKSHEET.md — тот же чек-лист как документ для чтения и печати

Запуск: python3 scripts/build_checklist.py
Проверка без записи: python3 scripts/build_checklist.py --check
"""

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STANDARD = ROOT / "STANDARD.md"
ITEMS = ROOT / "checklist" / "items.toml"
TEMPLATE = ROOT / "checklist" / "template.html"
OUT_HTML = ROOT / "site" / "checklist.html"
OUT_MD = ROOT / "checklists" / "WORKSHEET.md"

LEVELS = {"О": "Обязательно", "Р": "Рекомендуется"}
STAGES = {"М": "Макет", "М+Р": "Макет и сборка", "Р": "Сборка"}
PRINCIPLE_SHORT = {
    1: "Инновационность",
    2: "Полезность",
    3: "Эстетичность",
    4: "Понятность",
    5: "Ненавязчивость",
    6: "Честность",
    7: "Долговечность",
    8: "Тщательность",
    9: "Экологичность",
    10: "Как можно меньше дизайна",
}


def plain(text):
    """Убирает markdown-ссылки и обратные кавычки."""
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    return text.replace("`", "").strip()


def parse_standard():
    text = STANDARD.read_text(encoding="utf-8")
    version = re.search(r"\*\*Версия:\*\*\s*([\d.]+)", text).group(1)
    principles, reqs = {}, {}
    current = None
    for line in text.splitlines():
        m = re.match(r"^## (\d+)\. (.+)$", line)
        if m:
            current = int(m.group(1))
            principles[current] = {"n": current, "title": m.group(2).strip(), "short": PRINCIPLE_SHORT[current]}
            continue
        m = re.match(r"^\| (R(\d+)\.\d+) \| (.+) \| ([ОР]) \| (М\+Р|М|Р) \| (.+) \|$", line)
        if m:
            rid, pnum = m.group(1), int(m.group(2))
            if pnum != current:
                sys.exit(f"{rid}: стоит в разделе принципа {current}, а не {pnum}")
            reqs[rid] = {
                "id": rid,
                "principle": pnum,
                "text": plain(m.group(3)),
                "level": m.group(4),
                "stage": m.group(5),
                "check": plain(m.group(6)),
            }
    return version, principles, reqs


def load():
    version, principles, reqs = parse_standard()
    data = tomllib.loads(ITEMS.read_text(encoding="utf-8"))
    groups, items = data["groups"], data["items"]

    errors = []
    for rid in reqs.keys() - items.keys():
        errors.append(f"{rid} есть в STANDARD.md, но нет в items.toml")
    for rid in items.keys() - reqs.keys():
        errors.append(f"{rid} есть в items.toml, но нет в STANDARD.md")
    for rid, it in items.items():
        for field in ("group", "q", "how", "red"):
            if not it.get(field):
                errors.append(f"{rid}: не заполнено поле {field}")
        if it.get("group") not in groups:
            errors.append(f"{rid}: неизвестная группа {it.get('group')!r}")
        stage = reqs.get(rid, {}).get("stage")
        if stage == "Р" and (it.get("q_design") or it.get("how_design")):
            errors.append(f"{rid}: этап Р не проверяется в макете, q_design и how_design не нужны")
    if errors:
        sys.exit("Чек-лист не собран:\n  " + "\n  ".join(sorted(errors)))

    def sort_key(rid):
        p, n = rid[1:].split(".")
        return int(p), int(n)

    merged = []
    for rid in sorted(reqs, key=sort_key):
        it = items[rid]
        merged.append({
            **reqs[rid],
            "group": it["group"],
            "q": it["q"],
            "qDesign": it.get("q_design", it["q"]),
            "how": it["how"],
            "howDesign": it.get("how_design", it["how"]),
            "red": it["red"],
            "quick": bool(it.get("quick", False)),
        })
    group_list = [
        {"key": k, "title": g["title"], "intro": g["intro"], "order": g["order"]}
        for k, g in sorted(groups.items(), key=lambda kv: kv[1]["order"])
    ]
    order = {rid: i for i, rid in enumerate(items)}  # порядок внутри группы — как в items.toml
    merged.sort(key=lambda r: ([g["key"] for g in group_list].index(r["group"]), order[r["id"]]))
    return {
        "version": version,
        "principles": [principles[k] for k in sorted(principles)],
        "groups": group_list,
        "items": merged,
    }


def build_html(data):
    template = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    if "__CHECKLIST_DATA__" not in template:
        sys.exit("В template.html нет метки __CHECKLIST_DATA__")
    return template.replace("__CHECKLIST_DATA__", payload)


def build_md(data):
    items, groups = data["items"], data["groups"]
    count = {s: sum(1 for i in items if i["stage"] == s) for s in STAGES}
    quick = [i["id"] for i in items if i["quick"]]
    lines = [
        "# Рабочий лист проверки",
        "",
        "<!-- Файл собирается скриптом scripts/build_checklist.py. Правьте checklist/items.toml и STANDARD.md, а не этот файл. -->",
        "",
        f"Стандарт версии {data['version']}. Все 48 требований в том порядке, в каком их удобно проверять: от задачи к экранам, сценарию, ошибкам и реальным данным.",
        "",
        "Тот же чек-лист есть в интерактивном виде: `site/checklist.html`. В нём можно отмечать пункты, получить вердикт и выгрузить отчёт.",
        "",
        "## Как пользоваться",
        "",
        "| Проверка | Какие пункты | Какой вопрос читать |",
        "| --- | --- | --- |",
        f"| Дизайн-ревью макета | этапы «Макет» и «Макет и сборка» — {count['М'] + count['М+Р']} пунктов | «В макете» |",
        f"| Быстрая проверка макета | {len(quick)} пунктов с пометкой ⚡ | «В макете» |",
        f"| Приёмка сборки | этапы «Макет и сборка» и «Сборка» — {count['М+Р'] + count['Р']} пунктов | «В продукте» |",
        "| Аудит продукта | все 48 | «В продукте» |",
        "",
        "Для каждого пункта ставим одну отметку:",
        "",
        "**Да** — проверено, соответствует · **Частично** — не везде · **Нет** — не соответствует · **Н/п** — не применимо, с объяснением · **Не проверить** — по имеющимся материалам нельзя.",
        "",
        "Для «Частично» и «Нет» указываем серьёзность — что случится с человеком:",
        "",
        "| | Серьёзность | Что случится с человеком |",
        "| --- | --- | --- |",
        "| P0 | Блокер | Не закончит задачу, потеряет данные или будет введён в заблуждение |",
        "| P1 | Серьёзно | Трудно восстановиться после ошибки, непонятно, что происходит |",
        "| P2 | Нагрузка | Лишние действия, поиск, запоминание |",
        "| P3 | Полировка | Мелкие визуальные неточности |",
        "",
        "В макете серьёзность оцениваем так, как если бы решение реализовали как есть.",
        "",
    ]
    for g in groups:
        gi = [i for i in items if i["group"] == g["key"]]
        lines += [f"## {g['order']}. {g['title']}", "", g["intro"], ""]
        for i in gi:
            badges = f"{LEVELS[i['level']]} · {STAGES[i['stage']]} · Принцип {i['principle']}, {PRINCIPLE_SHORT[i['principle']]}"
            mark = " ⚡" if i["quick"] else ""
            lines += [f"### {i['id']}{mark}", "", f"*{badges}*", ""]
            if i["stage"] == "М+Р":
                lines += [
                    f"**В макете:** {i['qDesign']}",
                    "",
                    f"> {i['howDesign']}",
                    "",
                    f"**В продукте:** {i['q']}",
                    "",
                    f"> {i['how']}",
                    "",
                ]
            else:
                lines += [f"**{i['q']}**", "", f"> {i['how']}", ""]
            lines += [
                f"Тревожный признак: {i['red']}",
                "",
                f"Требование: {i['text']}",
                "",
                "☐ Да  ☐ Частично  ☐ Нет  ☐ Н/п  ☐ Не проверить   Серьёзность: ☐ P0  ☐ P1  ☐ P2  ☐ P3",
                "",
                "Заметка:",
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"


def main():
    data = load()
    html, md = build_html(data), build_md(data)
    if "--check" in sys.argv:
        stale = [p for p, c in ((OUT_HTML, html), (OUT_MD, md)) if not p.exists() or p.read_text(encoding="utf-8") != c]
        if stale:
            sys.exit("Устарели, запустите scripts/build_checklist.py: " + ", ".join(str(p.relative_to(ROOT)) for p in stale))
        print(f"Чек-лист актуален: {len(data['items'])} пунктов, стандарт {data['version']}")
        return
    OUT_HTML.parent.mkdir(exist_ok=True)
    OUT_HTML.write_text(html, encoding="utf-8")
    OUT_MD.write_text(md, encoding="utf-8")
    print(f"Собрано: {len(data['items'])} пунктов, стандарт {data['version']}")
    print(f"  {OUT_HTML.relative_to(ROOT)}\n  {OUT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
