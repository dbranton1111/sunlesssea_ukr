#!/usr/bin/env python3
"""
ua_json_apply.py - заливає переклад із tm.json у ЖИВУ контентну теку гри.

Жива тека:  ~/Library/Application Support/com.failbettergames.sunlesssea
(НЕ плутати з unity.Failbetter Games.Sunless Sea - то мертвий артефакт 2024 року,
 гра його не читає.)

    python3 ua_json_apply.py --dry-run   # порахувати, нічого не писати
    python3 ua_json_apply.py             # застосувати (бекап робиться сам)
    python3 ua_json_apply.py restore     # повернути англійську з бекапу
    python3 ua_json_apply.py status      # що зараз стоїть

Заміна структурна: JSON парситься, значення міняються лише під текстовими
ключами, файл серіалізується назад. Перед записом перевіряється, що круговий
обіг оригіналу байт-у-байт точний - інакше файл не чіпається.
"""
import json, os, re, shutil, sys
from pathlib import Path

TM_PATH = Path(__file__).resolve().parent / "tm.json"
BACKUP = "_ua_backup_json"
SUBDIRS = ("entities", "encyclopaedia", "geography", "constants")
def dump(obj):
    """Серіалізація 1-в-1 у форматі гри: компактно, не-ASCII як \\uXXXX великими."""
    s = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
    return re.sub(r"\\u([0-9a-f]{4})", lambda m: "\\u" + m.group(1).upper(), s)

TEXT_KEYS = {
    "Name", "Description", "Teaser", "ChangeDescriptionText", "LevelDescriptionText",
    "MoveMessage", "AvailableAt", "HumanName", "Tooltip", "ButtonText", "Label",
    "Title", "BuyMessage", "SellMessage",
}
CODE_NAME_ASSETS = {
    "Tiles", "TileSets", "TileRules", "Flavours", "CombatAttacks",
    "SpawnedEntities", "personas", "Associations", "NavGrid2",
}
SKIP_VALUES = {"REUSE", "Unspecified", "Normal", "Sometimes", "Always", "Never"}
IDENTIFIER_RE = re.compile(r"^[a-z0-9_\-/.]+$")

# слід тестового патчу, яким шукали живу теку
TEST_ARTEFACT = ("WELCOME TO THE UNTERZEE.", "Welcome to the Unterzee.")


def data_dir():
    home = Path.home()
    if sys.platform == "darwin":
        p = home / "Library/Application Support/com.failbettergames.sunlesssea"
    elif sys.platform.startswith("win"):
        p = Path(os.environ.get("USERPROFILE", home)) / "AppData/LocalLow/Failbetter Games/Sunless Sea"
    else:
        p = home / ".config/unity3d/Failbetter Games/Sunless Sea"
    return p if p.is_dir() else None


def keys_for(asset):
    return TEXT_KEYS - {"Name"} if asset in CODE_NAME_ASSETS else TEXT_KEYS


def worth_translating(value):
    """Той самий фільтр, що і в ss_extract.py - щоб лічильник не брехав."""
    s = value.strip()
    if len(s) < 2 or s in SKIP_VALUES:
        return False
    if IDENTIFIER_RE.match(s) and " " not in s:
        return False
    return bool(re.search(r"[A-Za-z]", s))


class Stats:
    def __init__(self):
        self.repl = 0
        self.miss = 0
        self.missed = []


def translate(node, tk, pairs, norm, st, skip=False):
    """Міняє значення НА МІСЦІ, лише під текстовими ключами."""
    if isinstance(node, dict):
        if node.get("Name") == "REUSE":
            skip = True
        for k, v in list(node.items()):
            if isinstance(v, str):
                if k in tk and not skip:
                    tgt = pairs.get(v)
                    if tgt is None:
                        tgt = norm.get(v.replace("\r\n", "\n"))
                    if tgt is not None:
                        node[k] = tgt
                        st.repl += 1
                    elif worth_translating(v) and not re.search(r"[\u0400-\u04FF]", v):
                        st.miss += 1          # уже українські поля не рахуємо як пропуск
                        if len(st.missed) < 5:
                            st.missed.append(v[:60])
            else:
                translate(v, tk, pairs, norm, st, skip)
    elif isinstance(node, list):
        for item in node:
            translate(item, tk, pairs, norm, st, skip)


def json_files(D):
    for sub in SUBDIRS:
        d = D / sub
        if d.is_dir():
            for f in sorted(d.glob("*.json")):
                yield sub, f


def main():
    argv = sys.argv[1:]
    dry = "--dry-run" in argv
    cmd = next((a for a in argv if not a.startswith("-")), "apply")

    D = data_dir()
    if D is None:
        sys.exit("Не знайшов теку гри. Запусти гру хоча б раз.")
    bak = D / BACKUP
    print(f"Тека гри: {D}")

    if cmd == "status":
        print(f"бекап: {'є' if bak.is_dir() else 'НЕМАЄ'}")
        for sub, f in json_files(D):
            raw = f.read_text(encoding="utf-8", errors="replace")
            try:            # кирилиця лежить як \\uXXXX, тому рахуємо після розбору
                txt = json.dumps(json.loads(raw), ensure_ascii=False)
            except json.JSONDecodeError:
                txt = raw
            print(f"  {sub}/{f.name:<24} кирилиці: {len(re.findall(r'[Ѐ-ӿ]', txt))}")
        return

    if cmd == "restore":
        if not bak.is_dir():
            sys.exit("Бекапу немає - відновлювати нема з чого.")
        n = 0
        for sub in SUBDIRS:
            src = bak / sub
            if not src.is_dir():
                continue
            for f in src.glob("*.json"):
                shutil.copy2(f, D / sub / f.name)   # по файлу, без rmtree
                n += 1
        print(f"Повернуто англійську: {n} файлів.")
        return

    if cmd != "apply":
        sys.exit(f"Невідома команда: {cmd}")

    tm = json.loads(TM_PATH.read_text(encoding="utf-8"))
    extra = TM_PATH.parent / "tm_teaser.json"
    if extra.exists():                      # додаткова пам'ять: Teaser
        add = json.loads(extra.read_text(encoding="utf-8"))
        merged = dict(add); merged.update(tm)   # tm.json має перевагу
        tm = merged
        print(f"Додаткова пам'ять tm_teaser.json: {len(add)}")
    pairs, norm = {}, {}
    for e in tm.values():
        src, tgt = e.get("src"), e.get("tgt")
        if src and tgt and src != tgt:
            pairs[src] = tgt
            norm[src.replace("\r\n", "\n")] = tgt
    print(f"Пар у пам'яті перекладів: {len(pairs)}")

    if bak.is_dir():
        print(f"Бекап уже є: {bak}")
    elif not dry:
        bak.mkdir(parents=True)

    total = Stats()
    for sub, f in json_files(D):
        asset = f.stem
        raw = f.read_text(encoding="utf-8")
        clean = raw.replace(*TEST_ARTEFACT)          # прибрати слід тестового патчу
        try:
            data = json.loads(clean)
        except json.JSONDecodeError as err:
            print(f"  {sub}/{f.name:<24} ПРОПУЩЕНО: не парситься ({err})")
            continue
        if dump(data) != clean:
            print(f"  {sub}/{f.name:<24} ПРОПУЩЕНО: круговий обіг не точний")
            continue

        # бекап - чистий оригінал, без сліду тестового патчу
        if not dry:
            (bak / sub).mkdir(parents=True, exist_ok=True)
            dst = bak / sub / f.name
            if not dst.exists():
                dst.write_text(clean, encoding="utf-8")

        st = Stats()
        translate(data, keys_for(asset), pairs, norm, st)
        total.repl += st.repl
        total.miss += st.miss
        tail = "" if st.miss == 0 else f"  без перекладу: {st.miss}  напр. {st.missed[:2]}"
        print(f"  {sub}/{f.name:<24} замін: {st.repl:<7}{tail}")
        if not dry and st.repl:
            f.write_text(dump(data), encoding="utf-8")

    print(f"\nУсього: {total.repl} замін, {total.miss} полів без перекладу")
    if dry:
        print("Пробний прогін, нічого не записано. Прибери --dry-run, щоб застосувати.")
    else:
        print(f"Бекап оригіналів: {bak}   (відкат: python3 ua_json_apply.py restore)")


main()
