#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Українізатор Sunless Sea – встановлення в один запуск.

    python3 install.py            # встановити
    python3 install.py uninstall  # відкотити все
    python3 install.py --game "шлях"  --data "шлях"   # якщо не знайшло само

Потрібно: Python 3.8+, UnityPy, fonttools.
    pip3 install UnityPy fonttools
Для перекладу інтерфейсу на macOS/Linux потрібен Mono (на Windows не потрібен).
"""
import json, os, re, shutil, struct, subprocess, sys, hashlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
TOOLS = HERE / "tools"
SUBDIRS = ("entities", "encyclopaedia", "geography", "constants")
TEXT_KEYS = {"Name","Description","Teaser","ChangeDescriptionText","LevelDescriptionText",
             "MoveMessage","AvailableAt","HumanName","Tooltip","ButtonText","Label",
             "Title","BuyMessage","SellMessage"}
CODE_NAME_ASSETS = {"Tiles","TileSets","TileRules","Flavours","CombatAttacks",
                    "SpawnedEntities","personas","Associations","NavGrid2"}
BACKUP_CONTENT = "_ua_backup"

def h(s): return hashlib.sha1(s.encode("utf-8")).hexdigest()[:10]
def say(*a): print(*a, flush=True)

# ---------- пошук тек ----------
def find_content_dir(explicit):
    if explicit:
        p = Path(explicit).expanduser()
        if not (p / "entities" / "events.json").exists():
            say(f"У теці немає entities/events.json: {p}")
            return None
        return p
    home = Path.home()
    c = []
    if sys.platform == "darwin":
        c.append(home / "Library/Application Support/com.failbettergames.sunlesssea")
    elif sys.platform.startswith("win"):
        base = Path(os.environ.get("USERPROFILE", home))
        c += [base / "AppData/LocalLow/Failbetter Games/Sunless Sea",
              base / "AppData/LocalLow/Failbetter Games/SunlessSea"]
    else:
        c += [home / ".config/unity3d/Failbetter Games/Sunless Sea",
              home / ".config/unity3d/FailbetterGames/SunlessSea"]
    for p in c:
        if (p / "entities" / "events.json").exists(): return p
    return None

def find_game_dir(explicit):
    if explicit: return Path(explicit).expanduser()
    home = Path.home()
    c = [home / "Library/Application Support/Steam/steamapps/common/SunlessSea",
         Path("C:/Program Files (x86)/Steam/steamapps/common/SunlessSea"),
         Path("C:/Program Files/Steam/steamapps/common/SunlessSea"),
         home / ".steam/steam/steamapps/common/SunlessSea",
         home / ".local/share/Steam/steamapps/common/SunlessSea"]
    for p in c:
        if p.exists() and list(p.rglob("resources.assets")): return p
    return None

def find_resources(game): return next(iter(game.rglob("resources.assets")), None)
def find_dll(game):       return next(iter(game.rglob("Managed/Sunless.Game.dll")), None)
def find_app(game):       return next((p for p in game.glob("*.app")), None)

# ---------- 1. контент ----------
def dump_json(obj):
    s = json.dumps(obj, ensure_ascii=True, separators=(",", ":"))
    return re.sub(r"\\u([0-9a-f]{4})", lambda m: "\\u" + m.group(1).upper(), s)

def keys_for(asset): return TEXT_KEYS - {"Name"} if asset in CODE_NAME_ASSETS else TEXT_KEYS

def walk(node, tk, table, stat, skip=False):
    if isinstance(node, dict):
        if node.get("Name") == "REUSE": skip = True
        for k, v in list(node.items()):
            if isinstance(v, str):
                if k in tk and not skip:
                    t = table.get(h(v)) or table.get(h(v.replace("\r\n", "\n")))
                    if t is not None: node[k] = t; stat[0] += 1
            else: walk(v, tk, table, stat, skip)
    elif isinstance(node, list):
        for it in node: walk(it, tk, table, stat, skip)

def step_content(cdir):
    table = json.loads((DATA / "content.json").read_text(encoding="utf-8"))
    bak = cdir / BACKUP_CONTENT
    total = [0]
    for sub in SUBDIRS:
        d = cdir / sub
        if not d.is_dir(): continue
        for f in sorted(d.glob("*.json")):
            raw = f.read_text(encoding="utf-8")
            try: obj = json.loads(raw)
            except json.JSONDecodeError: say(f"   {sub}/{f.name}: не JSON, пропущено"); continue
            if dump_json(obj) != raw:
                say(f"   {sub}/{f.name}: формат не відтворюється точно, пропущено"); continue
            (bak / sub).mkdir(parents=True, exist_ok=True)
            dst = bak / sub / f.name
            if not dst.exists(): dst.write_text(raw, encoding="utf-8")
            st = [0]
            walk(obj, keys_for(f.stem), table, st)
            if st[0]: f.write_text(dump_json(obj), encoding="utf-8")
            total[0] += st[0]
    say(f"   замін у тексті: {total[0]}")
    return total[0] > 0

# ---------- 2. шрифти ----------
FONT_PICKS = {
    "darwin": [("/System/Library/Fonts/Supplemental/Georgia.ttf",
                "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf")],
    "win":    [("C:/Windows/Fonts/georgia.ttf", "C:/Windows/Fonts/timesbd.ttf")],
    "linux":  [("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf")],
}
def pick_fonts():
    key = "darwin" if sys.platform == "darwin" else ("win" if sys.platform.startswith("win") else "linux")
    for serif, caps in FONT_PICKS[key]:
        if Path(serif).exists() and Path(caps).exists(): return serif, caps
    return None, None

def step_fonts(game):
    serif, caps = pick_fonts()
    if not serif:
        say("   системних кириличних шрифтів не знайдено – пропущено.")
        say("   Без цього кирилиця не намалюється. Признач вручну:")
        say("   python3 tools/ss_fonts_patch.py apply --serif <шлях.ttf> --caps <шлях.ttf>")
        return False
    say(f"   шрифти: {Path(serif).name} / {Path(caps).name}")
    r = subprocess.run([sys.executable, str(TOOLS / "ss_fonts_patch.py"), "apply",
                        "--game", str(game), "--serif", serif, "--caps", caps],
                       capture_output=True, text=True)
    if r.returncode != 0:
        say("   помилка патчу шрифтів:"); say(r.stdout[-800:]); say(r.stderr[-800:]); return False
    return True

# ---------- 3. інтерфейс в ассетах ----------
def step_assets_ui(res):
    try: import UnityPy
    except ImportError: say("   немає UnityPy – пропущено"); return False
    table = json.loads((DATA / "ui_assets.json").read_text(encoding="utf-8"))
    bak = res.with_suffix(res.suffix + ".ua-resui")
    if not bak.exists(): shutil.copy2(res, bak)
    env = UnityPy.load(str(bak))
    done = 0
    for o in env.objects:
        if o.type.name != "MonoBehaviour": continue
        try: b = o.get_raw_data()
        except Exception: continue
        changed = False
        i = 0
        while i + 4 <= len(b):
            L = struct.unpack_from("<i", b, i)[0]
            if 2 <= L <= 300 and i + 4 + L <= len(b):
                chunk = b[i+4:i+4+L]
                try: s = chunk.decode("utf-8")
                except UnicodeDecodeError: i += 4; continue
                t = table.get(h(s))
                if t is not None:
                    nb = t.encode("utf-8")
                    b = (b[:i] + struct.pack("<i", len(nb)) + nb + b"\0"*((4-len(nb)%4)%4)
                         + b[i+4+L+((4-L%4)%4):])
                    done += 1; changed = True
                    i += 4 + len(nb) + ((4-len(nb)%4)%4); continue
                i += 4 + L + ((4-L%4)%4); continue
            i += 4
        if changed: o.set_raw_data(b)
    res.write_bytes(env.file.save())
    say(f"   замін в ассетах: {done}")
    return True

# ---------- 4. інтерфейс у збірці ----------
def step_dll_ui(dll):
    bak = dll.with_suffix(dll.suffix + ".ua-prepack")
    if not bak.exists(): shutil.copy2(dll, bak)
    delta = DATA / "dll_patch.bin"
    if delta.exists():
        sys.path.insert(0, str(TOOLS))
        try:
            import dll_delta
            dll.write_bytes(dll_delta.apply(bak.read_bytes(), delta.read_bytes()))
            say("   готовий патч інтерфейсу накладено")
            return True
        except SystemExit as e:
            if str(e) == "SRC_MISMATCH":
                say("   версія гри не та, для якої зроблено готовий патч – пробую інакше")
            else:
                say(f"   готовий патч не наклався ({e}) – пробую інакше")
        except Exception as e:
            say(f"   готовий патч не наклався ({e}) – пробую інакше")
    exe = TOOLS / "ss_ui_patch.exe"
    if not exe.exists(): say("   інструмента немає – пропущено"); return False
    cmd = [str(exe), str(bak), str(dll), str(DATA / "ui_dll.json")]
    if not sys.platform.startswith("win"):
        if shutil.which("mono") is None:
            say("   Mono не встановлено – переклад інтерфейсу збірки пропущено.")
            say("   Решта перекладу працює. Щоб доробити: brew install mono, потім запусти ще раз.")
            return False
        cmd = ["mono"] + cmd
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(TOOLS))
    if r.returncode != 0:
        say("   помилка патчу збірки:"); say(r.stdout[-600:]); say(r.stderr[-600:]); return False
    for line in r.stdout.strip().splitlines()[-1:]: say("   " + line.strip())
    return True

# ---------- відкат ----------
def uninstall(game, cdir):
    n = 0
    if cdir:
        bak = cdir / BACKUP_CONTENT
        if bak.is_dir():
            for sub in SUBDIRS:
                for f in (bak / sub).glob("*.json") if (bak / sub).is_dir() else []:
                    shutil.copy2(f, cdir / sub / f.name); n += 1
            say(f"Текст повернуто: {n} файлів")
    if game:
        res = find_resources(game)
        # .orig – стан до патчу шрифтів, тобто найчистіший
        for cand in (res.with_suffix(".assets.orig"),
                     res.with_suffix(res.suffix + ".ua-resui")):
            if cand.exists(): shutil.copy2(cand, res); say(f"Ассети повернуто з {cand.name}"); break
        dll = find_dll(game)
        if dll:
            b = dll.with_suffix(dll.suffix + ".ua-prepack")
            if b.exists(): shutil.copy2(b, dll); say("Збірку повернуто")
        resign(game)
    say("Готово.")

def resign(game):
    if sys.platform != "darwin": return
    app = find_app(game)
    if not app: return
    say("Перепідписую застосунок…")
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(app)],
                   capture_output=True, text=True)

def main():
    args = sys.argv[1:]
    def opt(name):
        return args[args.index(name)+1] if name in args and args.index(name)+1 < len(args) else None
    game = find_game_dir(opt("--game"))
    cdir = find_content_dir(opt("--data"))

    if "uninstall" in args:
        uninstall(game, cdir); return

    say("Українізатор Sunless Sea\n")
    if cdir is None:
        say("Не знайшов теку з контентом гри.")
        say("Запусти гру хоча б раз, почни нову гру, вийди – і спробуй ще раз.")
        say("Або передай шлях: python3 install.py --data \"<шлях>\"")
        sys.exit(1)
    say(f"Контент гри: {cdir}")
    if game is None:
        say("Теку гри не знайдено – інтерфейс і шрифти пропущу.")
        say("Щоб зробити повністю: python3 install.py --game \"<шлях до SunlessSea>\"")
    else:
        say(f"Гра: {game}")
    say("")

    say("1/4 Текст гри")
    step_content(cdir)

    if game:
        res = find_resources(game)
        say("2/4 Шрифти")
        step_fonts(game)
        say("3/4 Інтерфейс в ассетах")
        step_assets_ui(res)
        say("4/4 Інтерфейс у збірці")
        dll = find_dll(game)
        if dll: step_dll_ui(dll)
        else: say("   Sunless.Game.dll не знайдено – пропущено")
        resign(game)

    say("\nГотово. Запускай гру і починай НОВУ гру:")
    say("старі збереження зберігають англійські описи всередині себе.")
    say("Відкотити все: python3 install.py uninstall")

main()
