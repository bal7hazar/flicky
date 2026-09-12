#!/usr/bin/env python3
"""Recursive-descent M68000 disassembler for the Flicky Mega Drive ROM.

Memory map handled:
  ROM  0x00000-0x0FFFF  : resident library code/data (runs in place)
  ROM  0x10000-0x1BFFF  : game code, copied to RAM 0xFF0000 and executed there
System-call table: ROM 0x22FC lists 58 word addresses; init builds
`jmp $xxxx.l` stubs at RAM 0xFFFA70 + 6*n, so `jsr $faXX.w` == call syscall n.
"""
import sys, struct, re, argparse
from capstone import Cs, CS_ARCH_M68K, CS_MODE_M68K_000

ap = argparse.ArgumentParser()
ap.add_argument('rom')
ap.add_argument('--out', default='disasm/flicky.asm')
ap.add_argument('--entries', default='tools/entries.txt', help='file of extra entry points (hex per line, # comments)')
args = ap.parse_args()

rom = open(args.rom, 'rb').read()
md = Cs(CS_ARCH_M68K, CS_MODE_M68K_000)

RAM_BASE, RAM_ROM_OFF, RAM_LEN = 0xFF0000, 0x10000, 0xC000
def canon(addr):
    if 0x10000 <= addr < 0x1C000: return addr - 0x10000 + RAM_BASE
    return addr
def to_off(addr):
    if 0 <= addr < 0x10000: return addr
    if RAM_BASE <= addr < RAM_BASE + RAM_LEN: return addr - RAM_BASE + RAM_ROM_OFF
    return None
def r16(a): return struct.unpack('>H', rom[a:a+2])[0]
def r32(a): return struct.unpack('>I', rom[a:a+4])[0]

# syscall table
n_sys = r16(0x22FC) + 1
syscalls = [r16(0x22FE + 2*i) for i in range(n_sys)]
sys_by_ram = {0xFFFA70 + 6*i: syscalls[i] for i in range(n_sys)}

entries = set()
for v in range(4, 0x100, 4):
    t = r32(v)
    if to_off(t) is not None and t != 0: entries.add(t)
entries.add(RAM_BASE)
entries.update(syscalls)
entries.add(canon(0x10E88))   # V-int handler installed at 0xFFFA7E
try:
    for line in open(args.entries):
        line = line.split('#')[0].strip()
        if line: entries.add(canon(int(line, 16)))
except FileNotFoundError:
    pass

insns = {}
labels = set(entries)
xrefs = {}
queue = list(entries)

HEX = r'\$([0-9a-f]+)'
def add_target(t, frm):
    t = canon(t)
    if to_off(t) is None: return
    labels.add(t); xrefs.setdefault(t, set()).add(frm)
    if t not in insns: queue.append(t)

def decode(a):
    off = to_off(a)
    if off is None: return None
    try:
        return next(md.disasm(rom[off:off+10], a, 1))
    except StopIteration:
        return None

def handle_targets(ins):
    m, s, a = ins.mnemonic, ins.op_str, ins.address
    if m in ('jmp', 'jsr', 'bsr') or (m.startswith('b') and m not in ('bchg','bclr','bset','btst')) or m.startswith('db'):
        mm = re.match(r'^' + HEX + r'(?:\.[lw])?$', s)
        if mm:
            t = int(mm.group(1), 16)
            if m in ('jmp', 'jsr') and s.endswith('.w'):
                t = t if t < 0x8000 else t | 0xFF0000   # sign-extended short absolute
            if t in sys_by_ram:
                add_target(sys_by_ram[t], a)
            else:
                add_target(t, a)
            return
        mm = re.search(r',\s*' + HEX + r'$', s)
        if mm and m.startswith('db'):
            add_target(int(mm.group(1), 16), a); return
        # jump table: jmp/jsr $d(pc, dN.w)  ->  table of bra.b at pc+2+d
        mm = re.match(r'^' + HEX + r'\(pc,\s*d\d\.[wl]\)$', s)
        if mm and m in ('jmp', 'jsr'):
            t = canon(int(mm.group(1), 16))
            k = 0
            while k < 64:
                off = to_off(t + 2*k)
                if off is None: break
                w = r16(off)
                if (w & 0xFF00) == 0x6000 and (w & 0xFF) != 0:   # bra.b
                    add_target(t + 2*k, a)
                elif w == 0x6000:  # bra.w
                    add_target(t + 2*k, a); k += 1
                else: break
                k += 1

def is_flow_end(ins):
    return ins.mnemonic in ('rts', 'rte', 'jmp', 'bra', 'rtr', 'illegal', 'stop')

while queue:
    a = queue.pop()
    while a not in insns:
        ins = decode(a)
        if ins is None:
            insns[a] = None; break
        insns[a] = ins
        handle_targets(ins)
        if is_flow_end(ins): break
        a += ins.size

# emit
covered = set()
for addr, ins in insns.items():
    if ins:
        for k in range(ins.size): covered.add(addr + k)

def segment_iter():
    yield (0, 0x1C000, 0)                 # rom offset range, addr base
    # the RAM segment is the same bytes as ROM 0x10000.. ; emit them at RAM addresses
def fmt_ops(ins):
    s = ins.op_str
    # annotate syscalls
    mm = re.match(r'^\$([0-9a-f]+)\.w$', s)
    if ins.mnemonic in ('jsr', 'jmp') and mm:
        t = int(mm.group(1), 16); t = t if t < 0x8000 else t | 0xFF0000
        if t in sys_by_ram:
            return f'{s}   ; syscall {sys_by_ram_idx[t]} -> loc_{sys_by_ram[t]:06X}'
    return s
sys_by_ram_idx = {0xFFFA70 + 6*i: i for i in range(n_sys)}

with open(args.out, 'w') as f:
    f.write('; Flicky (Mega Drive) recursive-descent disassembly\n')
    f.write('; Syscall table (RAM 0xFFFA70 + 6*n -> ROM target):\n')
    for i, t in enumerate(syscalls):
        f.write(f';   sys{i:02d} = loc_{t:06X}\n')
    for lo, hi, base in ((0, 0x10000, 0), (0x10000, 0x1C000, RAM_BASE - 0x10000)):
        f.write(f'\n; ===================== segment ROM {lo:05X}-{hi:05X} @ {lo+base:06X} =====================\n')
        a = lo + base
        end = hi + base
        while a < end:
            off = a - base
            if a in insns and insns[a]:
                ins = insns[a]
                if a in labels:
                    xr = ' '.join(f'{x:X}' for x in sorted(xrefs.get(a, ())))
                    f.write(f'\nloc_{a:06X}:' + (f'    ; xref: {xr}' if xr else '') + '\n')
                raw = rom[off:off+ins.size].hex()
                f.write(f'  {a:06X}  {raw:<20s}  {ins.mnemonic:<8s} {fmt_ops(ins)}\n')
                a += ins.size
            else:
                start = a
                while a < end and a not in covered and not (a in insns and insns[a]): a += 1
                f.write(f'\n; ---- data {start:06X}..{a-1:06X} ({a-start} bytes) ----\n')
                for x in range(start, a, 16):
                    chunk = rom[x-base:min(x+16, a)-base]
                    f.write(f'  {x:06X}  {chunk.hex(" ")}\n')
cov = len(covered)
print(f'{len(insns)} instructions, {len(labels)} labels, {cov} bytes of code ({cov*100/0x1C000:.1f}%), -> {args.out}')
