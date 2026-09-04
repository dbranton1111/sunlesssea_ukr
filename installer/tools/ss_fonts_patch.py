#!/usr/bin/env python3
"""
ss_fonts_patch.py - підміняє вшиті латинські шрифти Sunless Sea на кириличні.

У грі дев'ять шрифтових об'єктів двох родин:
  DroidSerif*  - основний текст, звичайний серіф
  TrajanPro*   - заголовки, капітель без малих літер

    pip3 install UnityPy fonttools

    python3 ss_fonts_patch.py scan
    python3 ss_fonts_patch.py apply --serif /шлях/Serif.ttf --caps /шлях/Caps.ttf
    python3 ss_fonts_patch.py apply ... --dry-run
    python3 ss_fonts_patch.py revert
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

try:
    import UnityPy
except ImportError:
    sys.exit("Немає UnityPy. Постав: pip3 install UnityPy")

try:
    from fontTools.ttLib import TTFont
except ImportError:
    sys.exit("Немає fonttools. Постав: pip3 install fonttools")

UA_REQUIRED = "іїєґІЇЄҐабвгдежзийклмнопрстуфхцчшщьюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЬЮЯ"
LATIN_SAMPLE = "AaBbCcXxYyZz0123456789"

SERIF_OBJECTS = {
    "DroidSerif_native": "regular",
    "DroidSerif-Bold": "bold",
    "DroidSerif-Italic": "italic",
    "DroidSerif-BoldItalic": "bolditalic",
}
CAPS_OBJECTS = {
    "TrajanPro_native": "regular",
    "TrajanPro-Bold_small": "bold",
    "TrajanPro-Bold_large": "bold",
    "TrajanPro-Bold_MapSmall": "bold",
    "TrajanPro-Bold_MapLarge": "bold",
}

SYSTEM_FONT_DIRS = [
    "/System/Library/Fonts",
    "/System/Library/Fonts/Supplemental",
    "/Library/Fonts",
    str(Path.home() / "Library/Fonts"),
    "C:/Windows/Fonts",
    "/usr/share/fonts",
]


def game_data_dir(explicit):
    if explicit:
        p = Path(explicit)
        if not p.exists():
            sys.exit(f"Шлях не існує: {p}")
        return p
    home = Path.home()
    guesses = [
        home / "Library/Application Support/Steam/steamapps/common/SunlessSea",
        Path("C:/Program Files (x86)/Steam/steamapps/common/SunlessSea"),
        home / ".steam/steam/steamapps/common/SunlessSea",
    ]
    for g in guesses:
        if g.exists():
            return g
    sys.exit("Папку гри не знайдено. Передай --game вручну.")


def find_resources(game_dir):
    hits = list(game_dir.rglob("resources.assets"))
    if not hits:
        sys.exit("resources.assets не знайдено")
    return hits[0]


def codepoints(path):
    tt = TTFont(str(path), fontNumber=0, lazy=True)
    cps = set()
    for table in tt["cmap"].tables:
        cps.update(table.cmap.keys())
    return cps


def cmd_scan():
    print("Шрифти в системі з повним українським набором:\n")
    seen = set()
    for folder in SYSTEM_FONT_DIRS:
        base = Path(folder)
        if not base.exists():
            continue
        for f in sorted(base.rglob("*")):
            if f.suffix.lower() not in (".ttf", ".otf", ".ttc"):
                continue
            if f.name in seen:
                continue
            seen.add(f.name)
            try:
                cps = codepoints(f)
            except Exception:  # noqa: BLE001
                continue
            if all(ord(c) in cps for c in UA_REQUIRED) and all(ord(c) in cps for c in LATIN_SAMPLE):
                kind = "serif?" if any(k in f.stem.lower() for k in ("serif", "times", "georgia", "garamond", "charter", "palatino", "baskerville")) else ""
                print(f"  {f}  ({len(cps)} гліфів) {kind}")
    print("\nДля основного тексту бери серіф. Для заголовків підійде будь-який,")
    print("бо скрипт усе одно перебудує його в капітель.")


def make_caps_variant(src_path, out_path):
    """Відображає рядкові коди на великі гліфи, щоб зберегти капітель Trajan."""
    tt = TTFont(str(src_path), fontNumber=0)
    pairs = []
    for lower, upper in [(chr(c), chr(c - 32)) for c in range(ord("a"), ord("z") + 1)]:
        pairs.append((ord(lower), ord(upper)))
    for lower, upper in [(chr(c), chr(c - 32)) for c in range(0x430, 0x450)]:
        pairs.append((ord(lower), ord(upper)))
    pairs += [(0x456, 0x406), (0x457, 0x407), (0x454, 0x404), (0x491, 0x490)]

    for table in tt["cmap"].tables:
        cmap = table.cmap
        for low_cp, up_cp in pairs:
            if up_cp in cmap:
                cmap[low_cp] = cmap[up_cp]
    tt.save(str(out_path))
    return out_path


def patch(resources_path, replacements, dry_run):
    env = UnityPy.load(str(resources_path))
    patched = []

    for obj in env.objects:
        if obj.type.name != "Font":
            continue
        tree = obj.read_typetree()
        name = tree.get("m_Name", "")
        if name not in replacements:
            continue
        blob = replacements[name].read_bytes()
        old_size = len(tree.get("m_FontData") or [])
        print(f"  {name}: {old_size} -> {len(blob)} байт  ({replacements[name].name})")
        if dry_run:
            patched.append(name)
            continue
        tree["m_FontData"] = list(blob)
        obj.save_typetree(tree)
        patched.append(name)

    if dry_run:
        print("\nПробний прогін, нічого не записано.")
        return patched

    data = env.file.save()
    resources_path.write_bytes(data)
    print(f"\nЗаписано: {resources_path} ({len(data)} байт)")
    return patched


def guess_siblings(regular):
    """Знаходить bold/italic/bolditalic поруч із звичайним накресленням."""
    folder, stem, suffix = regular.parent, regular.stem, regular.suffix
    variants = {
        "regular": regular,
        "bold": folder / f"{stem} Bold{suffix}",
        "italic": folder / f"{stem} Italic{suffix}",
        "bolditalic": folder / f"{stem} Bold Italic{suffix}",
    }
    for style, path in list(variants.items()):
        if not path.exists():
            variants[style] = regular
    return variants


def check_font(path):
    if path.suffix.lower() == ".ttc":
        sys.exit(f"{path.name} це колекція TTC. Unity її не прочитає, візьми звичайний .ttf")
    if not path.exists():
        sys.exit(f"Немає файлу: {path}")
    missing = "".join(c for c in UA_REQUIRED if ord(c) not in codepoints(path))
    if missing:
        sys.exit(f"{path.name} не має символів: {missing}")


def cmd_apply(game_dir, serif, caps, dry_run):
    serif_path, caps_path = Path(serif), Path(caps)
    check_font(serif_path)
    check_font(caps_path)

    serif_variants = guess_siblings(serif_path)
    for style, path in serif_variants.items():
        if path != serif_path:
            check_font(path)
        print(f"  {style}: {path.name}")
    print()

    resources = find_resources(game_dir)
    backup = resources.with_suffix(".assets.orig")
    if not backup.exists():
        shutil.copy2(resources, backup)
        print(f"Бекап: {backup}")
    else:
        print(f"Бекап уже є: {backup}")

    caps_built = Path("._ss_caps_variant.ttf")
    make_caps_variant(caps_path, caps_built)
    print(f"Капітельний варіант зібрано з {caps_path.name}\n")

    replacements = {}
    for obj_name, style in SERIF_OBJECTS.items():
        replacements[obj_name] = serif_variants[style]
    for obj_name in CAPS_OBJECTS:
        replacements[obj_name] = caps_built

    patched = patch(resources, replacements, dry_run)
    caps_built.unlink(missing_ok=True)

    print(f"\nОброблено об'єктів: {len(patched)}")
    if not dry_run and sys.platform == "darwin":
        app = next((p for p in game_dir.glob("*.app")), None)
        if app:
            print("\nТепер перепідпиши застосунок, інакше macOS не запустить його:")
            print(f'  codesign --force --deep --sign - "{app}"')


def cmd_revert(game_dir):
    resources = find_resources(game_dir)
    backup = resources.with_suffix(".assets.orig")
    if not backup.exists():
        sys.exit(f"Бекапу немає: {backup}")
    shutil.copy2(backup, resources)
    print(f"Повернуто з {backup}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["scan", "apply", "revert"])
    ap.add_argument("--game")
    ap.add_argument("--serif", help="TTF для основного тексту")
    ap.add_argument("--caps", help="TTF для заголовків")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.command == "scan":
        cmd_scan()
        return

    game_dir = game_data_dir(args.game)
    if args.command == "apply":
        if not args.serif or not args.caps:
            sys.exit("Потрібні --serif і --caps. Спершу глянь: python3 ss_fonts_patch.py scan")
        cmd_apply(game_dir, args.serif, args.caps, args.dry_run)
    else:
        cmd_revert(game_dir)


if __name__ == "__main__":
    main()
