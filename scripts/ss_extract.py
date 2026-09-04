#!/usr/bin/env python3
"""
ss_extract.py - конвеєр перекладу Sunless Sea без API, через чат.

Порядок роботи:
    python3 ss_extract.py extract            # зібрати рядки з ассетів у tm.json
    python3 ss_extract.py batches            # нарізати партії у batches/
    ... перекладаєш batches/batch_001.txt у чаті, зберігаєш у translated/ ...
    python3 ss_extract.py import             # вбрати переклад назад у tm.json
    python3 ss_extract.py stats              # скільки зроблено

Потім окремим скриптом переклад запаковується в resources.assets.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from pathlib import Path

try:
    import UnityPy
except ImportError:
    UnityPy = None

TM_PATH = Path("tm.json")
DUMP_DIR = Path("dumped")
BATCH_DIR = Path("batches")
TRANSLATED_DIR = Path("translated")

# Ключі з текстом, перевірені на російському пакеті.
TEXT_KEYS = {
    "Name", "Description", "Teaser", "ChangeDescriptionText", "LevelDescriptionText",
    "MoveMessage", "AvailableAt", "HumanName", "Tooltip", "ButtonText", "Label",
    "Title", "BuyMessage", "SellMessage",
}

# Ассети, де Name - це кодовий ідентифікатор, на який посилаються інші ассети
# (PrefabName, SpawnName, AllowedFlavours, Rule). Переклад таких Name ламає гру.
# Видимий текст у них лежить в HumanName, Label, Description, Tooltip.
CODE_NAME_ASSETS = {
    "Tiles", "TileSets", "TileRules", "Flavours", "CombatAttacks",
    "SpawnedEntities", "personas", "Associations", "NavGrid2",
}


def keys_for(asset):
    """Які ключі вважати текстом у конкретному ассеті."""
    if asset in CODE_NAME_ASSETS:
        return TEXT_KEYS - {"Name"}
    return TEXT_KEYS

# Пріоритет обробки: спершу дрібне й помітне, події в кінці.
ASSET_PRIORITY = [
    "Tutorials", "areas", "qualities", "exchanges", "personas",
    "Associations", "CombatItems", "CombatAttacks", "SpawnedEntities",
    "Flavours", "TileRules", "Tiles", "events",
]

TOKEN_RE = re.compile(r"\[(?:q|d|qb|qbc):[^\]]*\]")
SKIP_VALUES = {"REUSE", "Unspecified", "Normal", "Sometimes", "Always", "Never"}
IDENTIFIER_RE = re.compile(r"^[a-z0-9_\-/.]+$")


def game_dir():
    home = Path.home()
    guesses = [
        home / "Library/Application Support/Steam/steamapps/common/SunlessSea",
        Path("C:/Program Files (x86)/Steam/steamapps/common/SunlessSea"),
        home / ".steam/steam/steamapps/common/SunlessSea",
    ]
    for g in guesses:
        if g.exists():
            return g
    return None


def load_dumped():
    """Запасний шлях: читає вже витягнуті TextAsset з dumped/."""
    if not DUMP_DIR.exists():
        sys.exit(f"Немає ні папки гри, ні {DUMP_DIR}. Спершу: python3 ss_assets.py dump --out ./dumped")
    out = {}
    for f in sorted(DUMP_DIR.iterdir()):
        if not f.is_file() or f.name.startswith("."):
            continue
        name = f.name.split("__", 1)[1] if "__" in f.name else f.name
        try:
            out[name] = json.loads(f.read_text(encoding="utf-8-sig"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
    print(f"Джерело: {DUMP_DIR}/ (папку гри не видно)")
    return out


def load_text_assets():
    """Читає TextAsset з resources.assets, повертає {ім'я: розпарсений JSON}."""
    root = game_dir()
    if root is None or UnityPy is None:
        return load_dumped()
    resources = next(root.rglob("resources.assets"))
    env = UnityPy.load(str(resources))
    out = {}
    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        tree = obj.read_typetree()
        name = tree.get("m_Name", "")
        script = tree.get("m_Script", "")
        if isinstance(script, (list, tuple)):
            script = bytes(b & 0xFF for b in script).decode("utf-8", "replace")
        script = script.lstrip("\ufeff")  # частина ассетів іде з BOM
        if not script.lstrip().startswith(("[", "{")):
            continue
        try:
            out[name] = json.loads(script)
        except json.JSONDecodeError:
            continue
    return out


def string_id(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def worth_translating(key, value):
    if not isinstance(value, str):
        return False
    stripped = value.strip()
    if len(stripped) < 2 or stripped in SKIP_VALUES:
        return False
    if IDENTIFIER_RE.match(stripped) and " " not in stripped:
        return False
    if not re.search(r"[A-Za-z]", stripped):
        return False
    return True


def collect(node, asset, out, path="", skip_record=False):
    text_keys = keys_for(asset)
    if isinstance(node, dict):
        if node.get("Name") == "REUSE":
            skip_record = True
        for key, value in node.items():
            if key in text_keys and worth_translating(key, value) and not skip_record:
                sid = string_id(value)
                entry = out.setdefault(sid, {"src": value, "tgt": None, "locs": []})
                entry["locs"].append(f"{asset}:{path}{key}")
            else:
                collect(value, asset, out, f"{path}{key}.", skip_record)
    elif isinstance(node, list):
        for i, item in enumerate(node):
            collect(item, asset, out, f"{path}{i}.", skip_record)


def cmd_extract():
    assets = load_text_assets()
    print(f"Знайдено TextAsset з JSON: {len(assets)}\n")

    existing = json.loads(TM_PATH.read_text(encoding="utf-8")) if TM_PATH.exists() else {}
    strings = {}

    for name in ASSET_PRIORITY:
        if name not in assets:
            continue
        before = len(strings)
        collect(assets[name], name, strings)
        added = len(strings) - before
        print(f"  {name}: +{added} унікальних")

    for name in assets:
        if name not in ASSET_PRIORITY:
            collect(assets[name], name, strings)

    # переносимо вже наявні переклади
    kept = 0
    for sid, entry in strings.items():
        if sid in existing and existing[sid].get("tgt"):
            entry["tgt"] = existing[sid]["tgt"]
            kept += 1

    TM_PATH.write_text(json.dumps(strings, ensure_ascii=False, indent=1), encoding="utf-8")

    total_chars = sum(len(e["src"]) for e in strings.values())
    total_refs = sum(len(e["locs"]) for e in strings.values())
    print(f"\nУнікальних рядків: {len(strings)}")
    print(f"Усього входжень:   {total_refs}")
    print(f"Символів після дедуплікації: {total_chars}")
    print(f"Економія від дедуплікації: {100 - 100 * len(strings) // max(total_refs, 1)}%")
    if kept:
        print(f"Збережено наявних перекладів: {kept}")
    print(f"\nЗаписано: {TM_PATH}")


def asset_order(entry):
    first = entry["locs"][0].split(":")[0] if entry["locs"] else "zzz"
    return ASSET_PRIORITY.index(first) if first in ASSET_PRIORITY else 999


def cmd_batches(max_chars, only_asset, skip_assets, embed_prompt, out_dir):
    strings = json.loads(TM_PATH.read_text(encoding="utf-8"))
    pending = [(sid, e) for sid, e in strings.items() if not e.get("tgt")]

    def asset_of(entry):
        return entry["locs"][0].split(":")[0] if entry["locs"] else "?"

    if only_asset:
        pending = [(s, e) for s, e in pending if asset_of(e) == only_asset]
    if skip_assets:
        skip = set(skip_assets.split(","))
        pending = [(s, e) for s, e in pending if asset_of(e) not in skip]

    if not pending:
        sys.exit("Нема чого нарізати: усе вже перекладено або відфільтровано.")

    pending.sort(key=lambda kv: (asset_order(kv[1]), -len(kv[1]["src"])))

    prompt_text = ""
    if embed_prompt:
        prompt_path = Path("prompt.md")
        if not prompt_path.exists():
            sys.exit("Немає prompt.md поруч зі скриптом.")
        prompt_text = prompt_path.read_text(encoding="utf-8")
        # у вбудованому вигляді службова шапка про формат зайва
        marker = "\n---\n"
        if marker in prompt_text:
            prompt_text = prompt_text.split(marker, 1)[1].strip()

    out = Path(out_dir)
    out.mkdir(exist_ok=True)
    for old in out.glob("batch_*.txt"):
        try:
            old.unlink()
        except OSError:
            pass  # немає прав на видалення - старі файли просто перезапишуться

    groups, batch, size = [], [], 0
    for sid, entry in pending:
        length = len(entry["src"]) + 20
        if size + length > max_chars and batch:
            groups.append(batch)
            batch, size = [], 0
        batch.append((sid, entry))
        size += length
    if batch:
        groups.append(batch)

    index = []
    for i, group in enumerate(groups, start=1):
        fname = f"batch_{i:03d}.txt"
        stem = fname[:-4]
        assets = sorted({asset_of(e) for _, e in group})
        chars = sum(len(e["src"]) for _, e in group)

        parts = []
        if prompt_text:
            parts.append(prompt_text)
            parts.append("")
            parts.append("=" * 70)
            parts.append("")
        parts.append(f"# ПАРТІЯ {i:03d} з {len(groups):03d}")
        parts.append(f"# Ассети: {', '.join(assets)}. Рядків: {len(group)}. Символів: {chars}.")
        parts.append(f"# Результат зберегти як translated/{fname}")
        parts.append("# У самому перекладі лише блоки ### і переклади, без жодного іншого тексту.")
        parts.append(f"# Назви, яких немає в глосарії, окремо у translated/{stem}.names.txt")
        parts.append("")
        for sid, entry in group:
            parts.append(f"### {sid}")
            parts.append(entry["src"])

        (out / fname).write_text("\n".join(parts), encoding="utf-8")
        index.append((fname, len(group), chars, ", ".join(assets)))

    lines = ["# Партії на переклад", ""]
    lines.append(f"Усього партій: {len(groups)}")
    lines.append(f"Усього рядків: {sum(r[1] for r in index)}")
    lines.append(f"Усього символів: {sum(r[2] for r in index)}")
    lines.append("")
    lines.append("Кожен файл самодостатній: промпт із глосарієм уже всередині.")
    lines.append("Віддавай субагенту один файл, результат клади в translated/ під тим самим іменем.")
    lines.append("Коли назбирається, запускай: python3 ss_extract.py import")
    lines.append("")
    lines.append("| файл | рядків | символів | ассети |")
    lines.append("|---|---|---|---|")
    for fname, count, chars, assets in index:
        lines.append(f"| {fname} | {count} | {chars} | {assets} |")
    (out / "INDEX.md").write_text("\n".join(lines), encoding="utf-8")

    Path("translated").mkdir(exist_ok=True)

    print(f"Партій: {len(groups)}, рядків: {sum(r[1] for r in index)}, "
          f"символів: {sum(r[2] for r in index)}")
    print(f"Папка: {out}  (опис у {out}/INDEX.md)")
    print(f"Папку translated створено, клади туди відповіді під тими самими іменами.")


def validate(src, tgt):
    problems = []
    src_tokens = sorted(TOKEN_RE.findall(src))
    tgt_tokens = sorted(TOKEN_RE.findall(tgt))
    if src_tokens != tgt_tokens:
        problems.append(f"токени різняться: {src_tokens} проти {tgt_tokens}")
    src_braces = sorted(re.findall(r"\{[a-zA-Z0-9_]+\}", src))
    if src_braces != sorted(re.findall(r"\{[a-zA-Z0-9_]+\}", tgt)):
        problems.append("не збігаються підстановки у фігурних дужках")
    if src.count("[") != tgt.count("[") or src.count("]") != tgt.count("]"):
        problems.append("не збігається кількість квадратних дужок")
    if "|" in src and src.count("|") != tgt.count("|"):
        problems.append("не збігається кількість роздільників |")
    if "~" in src and src.count("~") != tgt.count("~"):
        problems.append("не збігається кількість роздільників ~")
    if re.match(r"^\s*<i>", src) and not re.match(r"^\s*<i>", tgt):
        problems.append("загублено тег <i>")
    if src.rstrip().endswith("...") and not tgt.rstrip().endswith("..."):
        problems.append("загублено три крапки в кінці")
    if not re.search(r"[\u0400-\u04FF]", tgt):
        problems.append("у перекладі немає кирилиці")
    return problems


def cmd_import():
    if not TRANSLATED_DIR.exists():
        sys.exit(f"Немає папки {TRANSLATED_DIR}. Клади туди перекладені партії.")
    strings = json.loads(TM_PATH.read_text(encoding="utf-8"))

    imported, skipped, flagged = 0, 0, []
    for f in sorted(TRANSLATED_DIR.glob("*.txt")):
        if f.name.endswith(".names.txt"):
            continue
        text = f.read_text(encoding="utf-8")
        # якщо субагент усе-таки дописав список назв у кінець - відрізаємо
        text = re.split(r"^#*\s*НОВІ НАЗВИ.*$", text, flags=re.M)[0]
        parts = re.split(r"^### ([0-9a-f]{10})\s*$", text, flags=re.M)
        # parts: [prefix, id, text, id, text, ...]
        for i in range(1, len(parts) - 1, 2):
            sid, body = parts[i], parts[i + 1].strip("\n")
            if sid not in strings:
                skipped += 1
                continue
            if not body.strip():
                skipped += 1
                continue
            # формат партії не передає кінцевий перенос рядка - відновлюємо з оригіналу
            src = strings[sid]["src"]
            tail = src[len(src.rstrip("\r\n")):]
            if tail and not body.endswith(tail):
                body = body + tail
            problems = validate(src, body)
            strings[sid]["tgt"] = body
            imported += 1
            if problems:
                flagged.append((f.name, sid, problems))

    TM_PATH.write_text(json.dumps(strings, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Прийнято рядків: {imported}, пропущено: {skipped}")
    if flagged:
        print(f"\nПідозрілих: {len(flagged)}")
        for fname, sid, problems in flagged[:30]:
            print(f"  {fname} {sid}: {'; '.join(problems)}")
        if len(flagged) > 30:
            print(f"  ... і ще {len(flagged) - 30}")


def cmd_stats():
    strings = json.loads(TM_PATH.read_text(encoding="utf-8"))
    by_asset = defaultdict(lambda: {"total": 0, "done": 0, "chars": 0, "chars_done": 0})
    for entry in strings.values():
        asset = entry["locs"][0].split(":")[0] if entry["locs"] else "?"
        st = by_asset[asset]
        st["total"] += 1
        st["chars"] += len(entry["src"])
        if entry.get("tgt"):
            st["done"] += 1
            st["chars_done"] += len(entry["src"])

    print(f"{'ассет':<20}{'рядків':>9}{'готово':>9}{'%':>6}{'символів':>12}")
    for asset in sorted(by_asset, key=lambda a: ASSET_PRIORITY.index(a) if a in ASSET_PRIORITY else 999):
        st = by_asset[asset]
        pct = 100 * st["done"] // max(st["total"], 1)
        print(f"{asset:<20}{st['total']:>9}{st['done']:>9}{pct:>5}%{st['chars']:>12}")

    total = sum(s["total"] for s in by_asset.values())
    done = sum(s["done"] for s in by_asset.values())
    chars = sum(s["chars"] for s in by_asset.values())
    chars_done = sum(s["chars_done"] for s in by_asset.values())
    print(f"\nУсього: {done} з {total} рядків ({100 * done // max(total, 1)}%)")
    print(f"Символів: {chars_done} з {chars} ({100 * chars_done // max(chars, 1)}%)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["extract", "batches", "import", "stats"])
    ap.add_argument("--max-chars", type=int, default=6000, help="розмір партії")
    ap.add_argument("--asset", help="нарізати партії тільки з одного ассета")
    ap.add_argument("--skip", help="пропустити ассети через кому, напр. events")
    ap.add_argument("--no-prompt", action="store_true", help="не вбудовувати промпт у партії")
    ap.add_argument("--out", default="batches", help="куди складати партії")
    args = ap.parse_args()

    if args.command == "extract":
        cmd_extract()
    elif args.command == "batches":
        cmd_batches(args.max_chars, args.asset, args.skip, not args.no_prompt, args.out)
    elif args.command == "import":
        cmd_import()
    else:
        cmd_stats()


if __name__ == "__main__":
    main()
