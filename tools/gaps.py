import re, sys
lines = open('disasm/flicky.asm').read().splitlines()
gaps = []
for l in lines:
    m = re.match(r'; ---- data ([0-9A-F]+)\.\.([0-9A-F]+) \((\d+) bytes\)', l)
    if m: gaps.append((int(m.group(1),16), int(m.group(2),16), int(m.group(3))))
refs = {}
for l in lines:
    m = re.match(r'  ([0-9A-F]{6})  \S+\s+(\S+)\s+(.*)$', l)
    if not m: continue
    a, mn, ops = int(m.group(1),16), m.group(2), m.group(3)
    if mn in ('jsr','jmp','bsr') or mn.startswith('b') or mn.startswith('db'): 
        if not re.search(r'\(pc', ops): continue
    for h in re.findall(r'\$([0-9a-f]{3,6})(?:\.[lw]|\(pc)', ops):
        t = int(h,16)
        if 0x10000 <= t < 0x1C000: t = t - 0x10000 + 0xFF0000
        refs.setdefault(t, []).append((a, mn))
for lo, hi, n in gaps:
    if n < 16: continue
    inside = sorted((t, v) for t, v in refs.items() if lo <= t <= hi)
    desc = ', '.join(f'{t:X}<-{",".join(f"{a:X}" for a,_ in v[:3])}' for t, v in inside[:8])
    print(f'{lo:06X}..{hi:06X} {n:6d}  refs:{len(inside):3d}  {desc}')
