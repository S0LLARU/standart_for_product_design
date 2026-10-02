#!/usr/bin/env python3
"""Собирает чек-лист двух проверок из STANDARD.md и checklist/*.toml.

Нормативный текст, уровень и этап требований читаются из STANDARD.md,
вопросы, критерии и источники — из checklist/items.toml, протокол
ИИ-проверки — из checklist/ai_protocol.toml. Скрипт проверяет, что
источники согласованы, и записывает:

  site/checklist.html     — интерактивный чек-лист (проверка человеком и ИИ)
  checklists/WORKSHEET.md — рабочий лист для чтения и печати
  checklists/SOURCES.md   — карта источников: Рамс, Айв, HIG, W3C

Запуск:              python3 scripts/build_checklist.py
Проверка без записи: python3 scripts/build_checklist.py --check
Задание для ИИ:      python3 scripts/build_checklist.py --ai-prompt design|quick|release|audit
"""

import json
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STANDARD = ROOT / "STANDARD.md"
ITEMS = ROOT / "checklist" / "items.toml"
PROTOCOL = ROOT / "checklist" / "ai_protocol.toml"
TEMPLATE = ROOT / "checklist" / "template.html"
OUT_HTML = ROOT / "site" / "checklist.html"
OUT_MD = ROOT / "checklists" / "WORKSHEET.md"
OUT_SOURCES = ROOT / "checklists" / "SOURCES.md"

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
MODES = {
    "design": {"title": "Дизайн-ревью", "ctx": "design", "filter": lambda i: i["stage"] != "Р"},
    "quick": {"title": "Быстрая проверка", "ctx": "design", "filter": lambda i: i["quick"]},
    "release": {"title": "Приёмка сборки", "ctx": "build", "filter": lambda i: i["stage"] != "М"},
    "audit": {"title": "Аудит продукта", "ctx": "build", "filter": lambda i: True},
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


def ai_item_text(item, ctx):
    """Фрагмент задания для одного пункта. Тот же текст использует страница."""
    design = ctx == "design"
    question = item["qDesign"] if design else item["q"]
    criteria = item["criteriaDesign"] if design else item["criteria"]
    lines = [f"### {item['id']} — {LEVELS[item['level']].lower()}", f"Вопрос: {question}", "Критерии:"]
    lines += [f"{n}. {c}" for n, c in enumerate(criteria, 1)]
    lines.append(f"Тревожный признак: {item['red']}")
    return "\n".join(lines)


def load():
    version, principles, reqs = parse_standard()
    data = tomllib.loads(ITEMS.read_text(encoding="utf-8"))
    protocol = tomllib.loads(PROTOCOL.read_text(encoding="utf-8"))
    groups, items, sources = data["groups"], data["items"], data["sources"]

    errors = []
    for rid in reqs.keys() - items.keys():
        errors.append(f"{rid} есть в STANDARD.md, но нет в items.toml")
    for rid in items.keys() - reqs.keys():
        errors.append(f"{rid} есть в items.toml, но нет в STANDARD.md")
    for key in ("intro", "materials_design", "materials_build", "rules", "format"):
        if not protocol.get(key, "").strip():
            errors.append(f"ai_protocol.toml: не заполнено поле {key}")
    for rid, it in items.items():
        stage = reqs.get(rid, {}).get("stage")
        for field in ("group", "q", "how", "red", "criteria"):
            if not it.get(field):
                errors.append(f"{rid}: не заполнено поле {field}")
        if it.get("group") not in groups:
            errors.append(f"{rid}: неизвестная группа {it.get('group')!r}")
        for field in ("criteria", "criteria_design"):
            if field in it and (not isinstance(it[field], list) or not all(isinstance(c, str) and c.strip() for c in it[field])):
                errors.append(f"{rid}: {field} должен быть списком непустых строк")
        if stage == "М+Р" and not it.get("criteria_design"):
            errors.append(f"{rid}: у этапа М+Р нужны отдельные критерии для макета (criteria_design)")
        if stage == "М" and it.get("criteria_design"):
            errors.append(f"{rid}: у этапа М критерии одни для макета и продукта, criteria_design не нужен")
        if stage == "Р" and any(it.get(f) for f in ("q_design", "how_design", "criteria_design")):
            errors.append(f"{rid}: этап Р не проверяется в макете, поля *_design не нужны")
        for n in it.get("ive", []):
            if str(n) not in sources["ive"]:
                errors.append(f"{rid}: нет темы Айва {n}")
        for k in it.get("hig", []):
            if k not in sources["hig"]:
                errors.append(f"{rid}: нет раздела HIG {k!r} в [sources.hig]")
        for k in it.get("w3c", []):
            if k not in sources["w3c"]:
                errors.append(f"{rid}: нет источника W3C {k!r} в [sources.w3c]")
    if errors:
        sys.exit("Чек-лист не собран:\n  " + "\n  ".join(sorted(errors)))

    group_keys = [k for k, _ in sorted(groups.items(), key=lambda kv: kv[1]["order"])]
    order = {rid: i for i, rid in enumerate(items)}  # порядок внутри группы — как в items.toml
    merged = []
    for rid in sorted(reqs, key=lambda r: (group_keys.index(items[r]["group"]), order[r])):
        it = items[rid]
        item = {
            **reqs[rid],
            "group": it["group"],
            "q": it["q"],
            "qDesign": it.get("q_design", it["q"]),
            "how": it["how"],
            "howDesign": it.get("how_design", it["how"]),
            "red": it["red"],
            "criteria": it["criteria"],
            "criteriaDesign": it.get("criteria_design", it["criteria"]),
            "quick": bool(it.get("quick", False)),
            "ive": [{"n": n, "title": sources["ive"][str(n)]} for n in it.get("ive", [])],
            "hig": [{"key": k, **sources["hig"][k]} for k in it.get("hig", [])],
            "w3c": [{"key": k, **sources["w3c"][k]} for k in it.get("w3c", [])],
        }
        if item["stage"] != "Р":
            item["aiDesign"] = ai_item_text(item, "design")
        item["aiBuild"] = ai_item_text(item, "build")
        merged.append(item)

    return {
        "version": version,
        "principles": [principles[k] for k in sorted(principles)],
        "groups": [{"key": k, "title": groups[k]["title"], "intro": groups[k]["intro"], "order": groups[k]["order"]} for k in group_keys],
        "items": merged,
        "sources": sources,
        "protocol": {k: protocol[k].strip() for k in ("intro", "materials_design", "materials_build", "rules", "format")},
    }


def ai_prompt(data, mode, context):
    """Полное задание для ИИ. Страница собирает его в том же порядке."""
    m = MODES[mode]
    p = data["protocol"]
    items = [i for i in data["items"] if m["filter"](i)]
    key = "aiDesign" if m["ctx"] == "design" else "aiBuild"
    intro = p["intro"].format(mode=m["title"], materials=p["materials_" + m["ctx"]], version=data["version"])
    return "\n\n".join([intro, p["rules"], "Контекст от команды:\n" + context, "Пункты для проверки:", "\n\n".join(i[key] for i in items), p["format"]]) + "\n"


def build_html(data):
    template = TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    if "__CHECKLIST_DATA__" not in template:
        sys.exit("В template.html нет метки __CHECKLIST_DATA__")
    return template.replace("__CHECKLIST_DATA__", payload)


def count(data, mode):
    return sum(1 for i in data["items"] if MODES[mode]["filter"](i))


def build_md(data):
    items, groups = data["items"], data["groups"]
    total = len(items)
    lines = [
        "# Рабочий лист проверки",
        "",
        "<!-- Файл собирается скриптом scripts/build_checklist.py. Правьте checklist/items.toml и STANDARD.md, а не этот файл. -->",
        "",
        f"Стандарт версии {data['version']}. Все {total} требований в том порядке, в каком их удобно проверять: от задачи к экранам, сценарию, ошибкам и реальным данным.",
        "",
        "У каждого требования есть критерии — короткие утверждения. На каждый отвечаете «да» или «нет». Требование выполнено, когда выполнены все его критерии. По этим же критериям проходит ИИ-проверка, поэтому ответы человека и ИИ можно сравнить пункт за пунктом.",
        "",
        "Тот же чек-лист в интерактивном виде — `site/checklist.html`: там итог пункта и вердикт считаются сами, туда же загружается результат ИИ-проверки.",
        "",
        "## Какие пункты проходить",
        "",
        "| Проверка | Пункты | Какие критерии читать |",
        "| --- | --- | --- |",
        f"| Дизайн-ревью макета | этапы «Макет» и «Макет и сборка» — {count(data, 'design')} | «В макете» |",
        f"| Быстрая проверка макета | с пометкой ⚡ — {count(data, 'quick')} | «В макете» |",
        f"| Приёмка сборки | этапы «Макет и сборка» и «Сборка» — {count(data, 'release')} | «В продукте» |",
        f"| Аудит продукта | все — {total} | «В продукте» |",
        "",
        "## Как отмечать",
        "",
        "1. Пройдите критерии пункта и отметьте каждый: выполнен или нет.",
        "2. Итог пункта: все критерии выполнены — **Да**; часть — **Частично**; ни одного — **Нет**.",
        "3. Если пункт не относится к решению — **Н/п** с объяснением. Если проверить нечем — **Не проверить**.",
        "4. Для «Частично» и «Нет» укажите серьёзность — что случится с человеком:",
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
            mark = " ⚡" if i["quick"] else ""
            src = [f"Рамс {i['principle']}"] + [f"Айв {s['n']}" for s in i["ive"]] + [f"HIG {s['key']}" for s in i["hig"]] + [s["title"] for s in i["w3c"]]
            lines += [
                f"### {i['id']}{mark}",
                "",
                f"*{LEVELS[i['level']]} · {STAGES[i['stage']]} · {', '.join(src)}*",
                "",
            ]
            if i["stage"] == "М+Р":
                lines += [f"**В макете:** {i['qDesign']}", ""]
                lines += [f"- [ ] {c}" for c in i["criteriaDesign"]]
                lines += ["", f"> {i['howDesign']}", "", f"**В продукте:** {i['q']}", ""]
                lines += [f"- [ ] {c}" for c in i["criteria"]]
                lines += ["", f"> {i['how']}", ""]
            else:
                lines += [f"**{i['q']}**", ""]
                lines += [f"- [ ] {c}" for c in i["criteria"]]
                lines += ["", f"> {i['how']}", ""]
            lines += [
                f"Тревожный признак: {i['red']}",
                "",
                f"Требование: {i['text']}",
                "",
                "Итог: ☐ Да  ☐ Частично  ☐ Нет  ☐ Н/п  ☐ Не проверить   Серьёзность: ☐ P0  ☐ P1  ☐ P2  ☐ P3",
                "",
                "Заметка:",
                "",
            ]
    return "\n".join(lines).rstrip() + "\n"


def build_sources(data):
    items, src = data["items"], data["sources"]
    by_ive, by_hig, by_w3c = {}, {}, {}
    for i in items:
        for s in i["ive"]:
            by_ive.setdefault(s["n"], []).append(i["id"])
        for s in i["hig"]:
            by_hig.setdefault(s["key"], []).append(i["id"])
        for s in i["w3c"]:
            by_w3c.setdefault(s["key"], []).append(i["id"])
    rid_key = lambda r: tuple(int(x) for x in r[1:].split("."))
    ids = lambda xs: ", ".join(sorted(xs, key=rid_key)) if xs else "—"
    lines = [
        "# Карта источников",
        "",
        "<!-- Файл собирается скриптом scripts/build_checklist.py из checklist/items.toml. Не правьте его руками. -->",
        "",
        f"Какие требования стандарта {data['version']} на что опираются. Принципы, высказывания и рекомендации принадлежат их авторам; требования и критерии — наша интерпретация.",
        "",
        "## Дитер Рамс — десять принципов хорошего дизайна",
        "",
        "Структура стандарта: каждое требование относится к одному принципу. Руководство: [principles/RAMS_PRINCIPLES.md](../principles/RAMS_PRINCIPLES.md).",
        "",
        "| Принцип | Требования |",
        "| --- | --- |",
    ]
    for p in data["principles"]:
        lines.append(f"| {p['n']}. {p['title']} | {ids([i['id'] for i in items if i['principle'] == p['n']])} |")
    lines += [
        "",
        "## Джони Айв — подход к работе над продуктом",
        "",
        "Темы — наша систематизация интервью, а не авторский свод Айва. Руководство: [principles/IVE_DESIGN_GUIDE.md](../principles/IVE_DESIGN_GUIDE.md).",
        "",
        "| Тема | Требования |",
        "| --- | --- |",
    ]
    for n in sorted(src["ive"], key=int):
        reqs = by_ive.get(int(n), [])
        note = ids(reqs) if reqs else "Отражена в процессе: стадии обсуждения на дизайн-ревью, а не отдельное требование"
        lines.append(f"| {n}. {src['ive'][n]} | {note} |")
    lines += [
        "",
        "## Apple Human Interface Guidelines",
        "",
        "Конкретные взаимодействия и элементы интерфейса. Руководство: [principles/HIG_GUIDE.md](../principles/HIG_GUIDE.md).",
        "",
        "| Раздел | Требования |",
        "| --- | --- |",
    ]
    for k, s in src["hig"].items():
        lines.append(f"| [{s['title']}]({s['url']}) | {ids(by_hig.get(k, []))} |")
    lines += ["", "## W3C", "", "Технические требования к доступности в вебе.", "", "| Источник | Требования |", "| --- | --- |"]
    for k, s in src["w3c"].items():
        lines.append(f"| [{s['title']}]({s['url']}) | {ids(by_w3c.get(k, []))} |")
    return "\n".join(lines) + "\n"


def main():
    data = load()
    if "--ai-prompt" in sys.argv:
        idx = sys.argv.index("--ai-prompt")
        mode = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else "design"
        if mode not in MODES:
            sys.exit(f"Неизвестный режим {mode!r}. Есть: {', '.join(MODES)}")
        context = "<Опишите продукт, проверяемый сценарий и что изображено на приложенных экранах. Добавьте аннотации из макета, если они есть.>"
        sys.stdout.write(ai_prompt(data, mode, context))
        return
    outputs = {OUT_HTML: build_html(data), OUT_MD: build_md(data), OUT_SOURCES: build_sources(data)}
    if "--check" in sys.argv:
        stale = [p for p, c in outputs.items() if not p.exists() or p.read_text(encoding="utf-8") != c]
        if stale:
            sys.exit("Устарели, запустите scripts/build_checklist.py: " + ", ".join(str(p.relative_to(ROOT)) for p in stale))
        print(f"Чек-лист актуален: {len(data['items'])} пунктов, стандарт {data['version']}")
        return
    for path, content in outputs.items():
        path.parent.mkdir(exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"Собрано: {len(data['items'])} пунктов, стандарт {data['version']}")
    for path in outputs:
        print(f"  {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
