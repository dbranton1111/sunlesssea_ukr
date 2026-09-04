#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dll_delta.py – бінарна різниця між оригінальним і пропатченим Sunless.Game.dll.

Формат тримає лише інструкції «скопіюй з оригіналу» та вставки нових байтів,
тож у файлі різниці немає коду й англійського тексту Failbetter: усе, що
збігається з оригіналом, береться з копії гравця.

    python3 dll_delta.py make orig.dll patched.dll dll_patch.bin
    python3 dll_delta.py apply orig.dll dll_patch.bin out.dll
"""
import hashlib, struct, sys, zlib
from pathlib import Path

MAGIC = b"UASSDLT1"
B = 20  # мінімальна довжина збігу


def sha(b): return hashlib.sha256(b).digest()


def make(src, tgt):
    index = {}
    step = 8
    for i in range(0, len(src) - B + 1, step):
        index.setdefault(bytes(src[i:i + B]), i)
    ops, pending, i = [], bytearray(), 0
    while i < len(tgt):
        j = index.get(bytes(tgt[i:i + B])) if i + B <= len(tgt) else None
        if j is None:
            pending.append(tgt[i]); i += 1; continue
        e = 0
        while i + B + e < len(tgt) and j + B + e < len(src) and tgt[i + B + e] == src[j + B + e]:
            e += 1
        b = 0
        while b < len(pending) and j - b - 1 >= 0 and tgt[i - b - 1] == src[j - b - 1]:
            b += 1
        if b: del pending[len(pending) - b:]
        if pending:
            ops.append((b"I", bytes(pending))); pending = bytearray()
        ops.append((b"C", j - b, B + e + b))
        i += B + e
    if pending: ops.append((b"I", bytes(pending)))

    out = bytearray()
    ins_total = 0
    for op in ops:
        if op[0] == b"C":
            out += b"C" + struct.pack("<II", op[1], op[2])
        else:
            out += b"I" + struct.pack("<I", len(op[1])) + op[1]
            ins_total += len(op[1])
    body = zlib.compress(bytes(out), 9)
    head = MAGIC + sha(src) + sha(tgt) + struct.pack("<I", len(tgt))
    return head + body, ins_total, len(ops)


def apply(src, patch):
    if patch[:8] != MAGIC:
        raise SystemExit("Це не файл різниці.")
    src_h, tgt_h = patch[8:40], patch[40:72]
    tgt_len = struct.unpack_from("<I", patch, 72)[0]
    if sha(src) != src_h:
        raise SystemExit("SRC_MISMATCH")
    ops = zlib.decompress(patch[76:])
    out = bytearray(); p = 0
    while p < len(ops):
        t = ops[p:p + 1]; p += 1
        if t == b"C":
            o, l = struct.unpack_from("<II", ops, p); p += 8
            out += src[o:o + l]
        else:
            l = struct.unpack_from("<I", ops, p)[0]; p += 4
            out += ops[p:p + l]; p += l
    if len(out) != tgt_len or sha(bytes(out)) != tgt_h:
        raise SystemExit("Різниця не зійшлася.")
    return bytes(out)


def main():
    a = sys.argv[1:]
    if len(a) == 4 and a[0] == "make":
        src = Path(a[1]).read_bytes(); tgt = Path(a[2]).read_bytes()
        blob, ins, n = make(src, tgt)
        Path(a[3]).write_bytes(blob)
        chk = apply(src, blob)
        print("перевірка збігу:", "так" if chk == tgt else "НІ")
        print(f"оригінал {len(src)} → ціль {len(tgt)}")
        print(f"різниця {len(blob)} байт, нових байтів {ins}, інструкцій {n}")
    elif len(a) == 4 and a[0] == "apply":
        out = apply(Path(a[1]).read_bytes(), Path(a[2]).read_bytes())
        Path(a[3]).write_bytes(out)
        print("готово")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
