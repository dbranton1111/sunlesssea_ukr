#!/usr/bin/env python3
"""
ss_res_ui_patch.py - підміняє написи інтерфейсу всередині resources.assets.

Ці рядки лежать в об'єктах MonoBehaviour (елементи UI), куди UnityPy не має
описів типів, тому правимо сирі байти: рядок Unity зберігає як
int32-довжина + байти + вирівнювання до 4. Довжину переписуємо, файл
UnityPy перезбирає сам.

    python3 ss_res_ui_patch.py <resources.assets> <карта.tsv>

Карта: англійський рядок<TAB>український переклад, по рядку на пару.
Бекап робиться сам у <resources.assets>.ua-resui, якщо його ще немає.
"""
import struct, sys, shutil
from pathlib import Path
try:
    import UnityPy
except ImportError:
    sys.exit("Немає UnityPy: pip3 install UnityPy")

def replace_in(b, ob, nb):
    i = 0
    while i + 4 <= len(b):
        L = struct.unpack_from("<i", b, i)[0]
        if L == len(ob) and b[i+4:i+4+L] == ob:
            pad_old = (4 - L % 4) % 4
            pad_new = (4 - len(nb) % 4) % 4
            return b[:i] + struct.pack("<i", len(nb)) + nb + b"\0"*pad_new + b[i+4+L+pad_old:]
        i += 4
    return None

def main():
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    target = Path(sys.argv[1]); tsv = Path(sys.argv[2])
    if not target.exists(): sys.exit(f"Немає файлу: {target}")
    pairs = {}
    for line in tsv.read_text(encoding="utf-8").splitlines():
        if line.count("\t") != 1: continue
        en, ua = line.split("\t")
        if en and ua and en != ua: pairs[en] = ua
    print(f"Пар у карті: {len(pairs)}")

    bak = target.with_suffix(target.suffix + ".ua-resui")
    if not bak.exists():
        shutil.copy2(target, bak); print(f"Бекап: {bak}")
    else:
        print(f"Бекап уже є: {bak}")

    env = UnityPy.load(str(bak))          # завжди патчимо з чистого бекапу
    done = 0; miss = []
    for en, ua in pairs.items():
        ob, nb = en.encode(), ua.encode()
        hit = False
        for o in env.objects:
            if o.type.name != "MonoBehaviour": continue
            b = o.get_raw_data()
            if ob not in b: continue
            r = replace_in(b, ob, nb)
            if r is not None:
                o.set_raw_data(r); done += 1; hit = True
        if not hit: miss.append(en)
    target.write_bytes(env.file.save())
    print(f"Замінено: {done}   не знайдено в ассеті: {len(miss)}")
    for m in miss[:15]: print("   немає:", repr(m))
    # контроль: файл має читатися
    UnityPy.load(str(target))
    print("Перевірка: файл коректно перечитується.")

main()
