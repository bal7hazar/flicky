"""Interpréteur 68000 minimal pour exécuter le code de la ROM Flicky comme
référence (validation du port Python). VDP, Z80 et son sont des stubs ; le
V-int est délivré quand le code attend dans la boucle de sys42 (0xF42), ce qui
définit une frame.

Usage : from tools.m68k import Machine ; m = Machine(rom_bytes) ; m.run_frame(pad)
"""
from __future__ import annotations

import struct
from typing import Callable, Dict, List, Optional

M8, M16, M32 = 0xFF, 0xFFFF, 0xFFFFFFFF
MASK = (M8, M16, M32)
MSB = (0x80, 0x8000, 0x80000000)
BITS = (8, 16, 32)
# flags
C_, V_, Z_, N_, X_ = 1, 2, 4, 8, 16


def sext(v: int, size: int) -> int:
    v &= MASK[size]
    return v - (1 << BITS[size]) if v & MSB[size] else v


class Machine:
    def __init__(self, rom: bytes):
        self.rom = bytes(rom) + bytes(0x400000 - len(rom)) if len(rom) < 0x400000 else bytes(rom)
        self.rom_len = len(rom)
        self.ram = bytearray(0x10000)
        self.z80 = bytearray(0x10000)
        self.io = bytearray(0x20)
        self.D = [0] * 8
        self.A = [0] * 8
        self.pc = 0
        self.sr = 0x2700
        self.pad1 = 0          # bits actifs : 1 = pressé (format ff8e : S A C B R L D U)
        self.pad_th = 0x40
        self.frames = 0
        self.icount = 0
        self.vdp_writes: List = []
        self.trace: Optional[Callable] = None
        self.halted = False
        self.reset()
        self._ops: Dict[int, Callable] = {}

    # ------------------------------------------------------------------ mémoire
    def reset(self):
        self.A[7] = struct.unpack_from(">I", self.rom, 0)[0]
        self.pc = struct.unpack_from(">I", self.rom, 4)[0]
        self.sr = 0x2700

    def r8(self, a: int) -> int:
        a &= 0xFFFFFF
        if a < 0x400000:
            return self.rom[a]
        if a >= 0xFF0000:
            return self.ram[a & 0xFFFF]
        if a < 0xA10000:
            return self.z80[a & 0xFFFF]
        if a < 0xA10020:
            return self.io_read(a)
        if a == 0xA11100 or a == 0xA11101:
            return 0            # bus Z80 accordé
        if 0xC00000 <= a < 0xC00010:
            if a & 4:
                return 0x36 if (a & 1) == 0 else 0x00   # statut VDP
            return 0
        return 0

    def r16(self, a: int) -> int:
        a &= 0xFFFFFF
        if a < 0x400000:
            return (self.rom[a] << 8) | self.rom[a + 1]
        if a >= 0xFF0000:
            a &= 0xFFFF
            return (self.ram[a] << 8) | self.ram[(a + 1) & 0xFFFF]
        return (self.r8(a) << 8) | self.r8(a + 1)

    def r32(self, a: int) -> int:
        return (self.r16(a) << 16) | self.r16(a + 2)

    def w8(self, a: int, v: int):
        a &= 0xFFFFFF
        v &= 0xFF
        if a >= 0xFF0000:
            self.ram[a & 0xFFFF] = v
        elif 0xA00000 <= a < 0xA10000:
            self.z80[a & 0xFFFF] = v
        elif 0xA10000 <= a < 0xA10020:
            self.io_write(a, v)
        elif 0xC00000 <= a < 0xC00010:
            self.vdp_write(a, v, 0)

    def w16(self, a: int, v: int):
        a &= 0xFFFFFF
        v &= 0xFFFF
        if a >= 0xFF0000:
            a &= 0xFFFF
            self.ram[a] = v >> 8
            self.ram[(a + 1) & 0xFFFF] = v & 0xFF
        elif 0xC00000 <= a < 0xC00010:
            self.vdp_write(a, v, 1)
        else:
            self.w8(a, v >> 8)
            self.w8(a + 1, v)

    def w32(self, a: int, v: int):
        self.w16(a, (v >> 16) & 0xFFFF)
        self.w16(a + 2, v & 0xFFFF)

    def read(self, a: int, size: int) -> int:
        return (self.r8, self.r16, self.r32)[size](a)

    def write(self, a: int, v: int, size: int):
        (self.w8, self.w16, self.w32)[size](a, v)

    def io_read(self, a: int) -> int:
        off = a & 0x1F
        if off == 1:
            return 0x80          # overseas, NTSC, pas de TMSS
        if off == 3:             # manette 1 (bits actifs bas)
            p = self.pad1
            if self.pad_th & 0x40:
                v = ((p >> 5) & 1) << 5 | ((p >> 4) & 1) << 4 | ((p >> 3) & 1) << 3 | ((p >> 2) & 1) << 2 | (p & 3)
                return (~v & 0x3F) | 0x40
            v = ((p >> 7) & 1) << 5 | ((p >> 6) & 1) << 4 | (p & 3)
            return ~v & 0x3F
        if off == 5 or off == 7:
            return 0x7F
        return self.io[off]

    def io_write(self, a: int, v: int):
        off = a & 0x1F
        if off == 3:
            self.pad_th = v
        self.io[off] = v

    def vdp_write(self, a: int, v: int, size: int):
        pass

    # ------------------------------------------------------------------ flags
    def set_nz(self, v: int, size: int):
        f = self.sr & ~(N_ | Z_ | V_ | C_)
        v &= MASK[size]
        if v == 0:
            f |= Z_
        elif v & MSB[size]:
            f |= N_
        self.sr = f

    def flags_add(self, s: int, d: int, r: int, size: int, x: bool = True):
        m = MSB[size]
        f = self.sr & ~(N_ | Z_ | V_ | C_ | (X_ if x else 0))
        r &= MASK[size]
        if r == 0:
            f |= Z_
        elif r & m:
            f |= N_
        if ((s & m) == (d & m)) and ((r & m) != (s & m)):
            f |= V_
        if ((s + d) >> BITS[size]) & 1 if size < 2 else (s + d) > M32:
            f |= C_ | (X_ if x else 0)
        self.sr = f

    def flags_sub(self, s: int, d: int, r: int, size: int, x: bool = True):
        """r = d - s"""
        m = MSB[size]
        f = self.sr & ~(N_ | Z_ | V_ | C_ | (X_ if x else 0))
        r &= MASK[size]
        if r == 0:
            f |= Z_
        elif r & m:
            f |= N_
        if ((s & m) != (d & m)) and ((r & m) != (d & m)):
            f |= V_
        if (s & MASK[size]) > (d & MASK[size]):
            f |= C_ | (X_ if x else 0)
        self.sr = f

    def cond(self, cc: int) -> bool:
        sr = self.sr
        c, v, z, n = sr & C_, sr & V_, sr & Z_, sr & N_
        if cc == 0: return True
        if cc == 1: return False
        if cc == 2: return not c and not z
        if cc == 3: return bool(c or z)
        if cc == 4: return not c
        if cc == 5: return bool(c)
        if cc == 6: return not z
        if cc == 7: return bool(z)
        if cc == 8: return not v
        if cc == 9: return bool(v)
        if cc == 10: return not n
        if cc == 11: return bool(n)
        if cc == 12: return bool(n) == bool(v)
        if cc == 13: return bool(n) != bool(v)
        if cc == 14: return not z and (bool(n) == bool(v))
        return bool(z) or (bool(n) != bool(v))

    # ------------------------------------------------------------------ fetch / EA
    def fetch16(self) -> int:
        v = self.r16(self.pc)
        self.pc += 2
        return v

    def fetch32(self) -> int:
        v = self.r32(self.pc)
        self.pc += 4
        return v

    def ea_addr(self, mode: int, reg: int, size: int) -> int:
        """Adresse effective pour les modes mémoire (2..7)."""
        if mode == 2:
            return self.A[reg]
        if mode == 3:
            a = self.A[reg]
            inc = 1 << size
            if reg == 7 and size == 0:
                inc = 2
            self.A[reg] = (a + inc) & M32
            return a
        if mode == 4:
            inc = 1 << size
            if reg == 7 and size == 0:
                inc = 2
            a = (self.A[reg] - inc) & M32
            self.A[reg] = a
            return a
        if mode == 5:
            return (self.A[reg] + sext(self.fetch16(), 1)) & M32
        if mode == 6:
            return self.index_addr(self.A[reg])
        if reg == 0:
            return sext(self.fetch16(), 1) & M32
        if reg == 1:
            return self.fetch32()
        if reg == 2:
            base = self.pc
            return (base + sext(self.fetch16(), 1)) & M32
        if reg == 3:
            base = self.pc
            return self.index_addr(base)
        raise ValueError("EA immédiat sans adresse")

    def index_addr(self, base: int) -> int:
        ext = self.fetch16()
        idx = self.A[(ext >> 12) & 7] if ext & 0x8000 else self.D[(ext >> 12) & 7]
        if not (ext & 0x800):
            idx = sext(idx, 1)
        else:
            idx = sext(idx, 2)
        return (base + sext(ext, 0) + idx) & M32

    def ea_read(self, mode: int, reg: int, size: int) -> int:
        if mode == 0:
            return self.D[reg] & MASK[size]
        if mode == 1:
            return self.A[reg] & MASK[size]
        if mode == 7 and reg == 4:
            if size == 2:
                return self.fetch32()
            v = self.fetch16()
            return v & MASK[size]
        return self.read(self.ea_addr(mode, reg, size), size)

    def ea_write(self, mode: int, reg: int, size: int, v: int):
        if mode == 0:
            m = MASK[size]
            self.D[reg] = (self.D[reg] & ~m) | (v & m)
            return
        if mode == 1:
            self.A[reg] = v & M32 if size == 2 else sext(v, 1) & M32
            return
        self.write(self.ea_addr(mode, reg, size), v, size)

    def ea_rmw(self, mode: int, reg: int, size: int, fn: Callable[[int], int]):
        """lecture-modification-écriture avec une seule évaluation d'adresse."""
        if mode == 0:
            m = MASK[size]
            r = fn(self.D[reg] & m)
            self.D[reg] = (self.D[reg] & ~m) | (r & m)
            return
        if mode == 1:
            r = fn(self.A[reg] & MASK[size])
            self.A[reg] = r & M32
            return
        a = self.ea_addr(mode, reg, size)
        self.write(a, fn(self.read(a, size)), size)

    def set_dreg(self, reg: int, v: int, size: int):
        m = MASK[size]
        self.D[reg] = (self.D[reg] & ~m) | (v & m)

    # ------------------------------------------------------------------ exécution
    def push32(self, v: int):
        self.A[7] = (self.A[7] - 4) & M32
        self.w32(self.A[7], v)

    def pop32(self) -> int:
        v = self.r32(self.A[7])
        self.A[7] = (self.A[7] + 4) & M32
        return v

    def interrupt(self, level: int, vector: int):
        sr = self.sr
        self.A[7] = (self.A[7] - 4) & M32
        self.w32(self.A[7], self.pc)
        self.A[7] = (self.A[7] - 2) & M32
        self.w16(self.A[7], sr)
        self.sr = (sr & 0x00FF & ~0x0700) | 0x2000 | (level << 8)
        self.pc = self.r32(vector)

    def step(self):
        op = self.fetch16()
        self.icount += 1
        fn = self._ops.get(op)
        if fn is None:
            fn = self.decode(op)
            self._ops[op] = fn
        fn(op)

    def decode(self, op: int) -> Callable:
        top = op >> 12
        return getattr(self, f"grp_{top:x}")

    # --- groupe 0 : immédiats et bits ---
    def grp_0(self, op: int):
        if op & 0x100 or (op & 0xF00) == 0x800:
            # opérations sur bits
            if op & 0x100:
                bit = self.D[(op >> 9) & 7]
            else:
                bit = self.fetch16() & 0xFF
            mode, reg = (op >> 3) & 7, op & 7
            kind = (op >> 6) & 3
            if mode == 0:
                bit &= 31
                m = 1 << bit
                v = self.D[reg]
                self.sr = (self.sr & ~Z_) | (0 if v & m else Z_)
                if kind == 1: v ^= m
                elif kind == 2: v &= ~m
                elif kind == 3: v |= m
                self.D[reg] = v & M32
            else:
                bit &= 7
                m = 1 << bit
                a = self.ea_addr(mode, reg, 0)
                v = self.r8(a)
                self.sr = (self.sr & ~Z_) | (0 if v & m else Z_)
                if kind == 1: v ^= m
                elif kind == 2: v &= ~m
                elif kind == 3: v |= m
                if kind:
                    self.w8(a, v)
            return
        size = (op >> 6) & 3
        kind = (op >> 9) & 7
        mode, reg = (op >> 3) & 7, op & 7
        imm = self.fetch32() if size == 2 else (self.fetch16() & MASK[size])
        if mode == 7 and reg == 4:      # vers CCR / SR
            if kind == 0: self.sr |= imm
            elif kind == 1: self.sr &= imm | (0xFF00 if size == 0 else 0)
            elif kind == 5: self.sr ^= imm
            return
        if kind == 6:   # cmpi
            d = self.ea_read(mode, reg, size)
            self.flags_sub(imm, d, d - imm, size, x=False)
            return
        def fn(d):
            if kind == 0:
                r = d | imm; self.set_nz(r, size)
            elif kind == 1:
                r = d & imm; self.set_nz(r, size)
            elif kind == 2:
                r = d - imm; self.flags_sub(imm, d, r, size)
            elif kind == 3:
                r = d + imm; self.flags_add(imm, d, r, size)
            else:
                r = d ^ imm; self.set_nz(r, size)
            return r
        self.ea_rmw(mode, reg, size, fn)

    # --- move ---
    def _move(self, op: int, size: int):
        smode, sreg = (op >> 3) & 7, op & 7
        dmode, dreg = (op >> 6) & 7, (op >> 9) & 7
        v = self.ea_read(smode, sreg, size)
        if dmode == 1:
            self.A[dreg] = (sext(v, size) & M32) if size == 1 else v
            return
        self.set_nz(v, size)
        self.ea_write(dmode, dreg, size, v)

    def grp_1(self, op): self._move(op, 0)
    def grp_2(self, op): self._move(op, 2)
    def grp_3(self, op): self._move(op, 1)

    # --- groupe 4 : divers ---
    def grp_4(self, op: int):
        mode, reg = (op >> 3) & 7, op & 7
        if op & 0x100:
            kind = (op >> 6) & 7
            if kind == 7:            # lea
                self.A[(op >> 9) & 7] = self.ea_addr(mode, reg, 2)
                return
            if kind == 6:            # chk
                raise NotImplementedError("chk")
        hi = op & 0xFF00
        if hi == 0x4200:             # clr
            size = (op >> 6) & 3
            self.ea_write(mode, reg, size, 0)
            self.sr = (self.sr & ~(N_ | V_ | C_)) | Z_
            return
        if hi == 0x4400:             # neg / move to CCR
            size = (op >> 6) & 3
            if size == 3:
                self.sr = (self.sr & 0xFF00) | (self.ea_read(mode, reg, 1) & 0xFF)
                return
            def fn(d):
                r = (-d) & MASK[size]
                self.flags_sub(d, 0, r, size)
                return r
            self.ea_rmw(mode, reg, size, fn)
            return
        if hi == 0x4600:             # not / move to SR
            size = (op >> 6) & 3
            if size == 3:
                self.sr = self.ea_read(mode, reg, 1)
                return
            def fn(d):
                r = (~d) & MASK[size]
                self.set_nz(r, size)
                return r
            self.ea_rmw(mode, reg, size, fn)
            return
        if hi == 0x4400 or (op & 0xFFC0) == 0x44C0:   # move to CCR
            self.sr = (self.sr & 0xFF00) | (self.ea_read(mode, reg, 1) & 0xFF)
            return
        if (op & 0xFFC0) == 0x40C0:  # move from SR
            self.ea_write(mode, reg, 1, self.sr)
            return
        if hi == 0x4A00:             # tst
            size = (op >> 6) & 3
            if size == 3:
                raise NotImplementedError("tas")
            v = self.ea_read(mode, reg, size)
            self.set_nz(v, size)
            return
        if (op & 0xFFB8) == 0x4880 and mode == 0:  # ext
            if op & 0x40:
                self.D[reg] = sext(self.D[reg], 1) & M32
                self.set_nz(self.D[reg], 2)
            else:
                v = sext(self.D[reg], 0) & M16
                self.set_dreg(reg, v, 1)
                self.set_nz(v, 1)
            return
        if (op & 0xFFF8) == 0x4840:  # swap
            v = self.D[reg]
            v = ((v << 16) | (v >> 16)) & M32
            self.D[reg] = v
            self.set_nz(v, 2)
            return
        if (op & 0xFFC0) == 0x4840:  # pea
            self.push32(self.ea_addr(mode, reg, 2))
            return
        if (op & 0xFB80) == 0x4880:  # movem
            size = 2 if op & 0x40 else 1
            mask = self.fetch16()
            step = 4 if size == 2 else 2
            if op & 0x400:           # mémoire -> registres
                a = self.ea_addr(mode, reg, size) if mode != 3 else self.A[reg]
                for i in range(16):
                    if mask & (1 << i):
                        v = self.read(a, size)
                        if size == 1:
                            v = sext(v, 1) & M32
                        if i < 8:
                            self.D[i] = v
                        else:
                            self.A[i - 8] = v
                        a += step
                if mode == 3:
                    self.A[reg] = a & M32
            else:
                if mode == 4:
                    a = self.A[reg]
                    for i in range(16):
                        if mask & (1 << i):
                            r = 15 - i
                            v = self.D[r] if r < 8 else self.A[r - 8]
                            a -= step
                            self.write(a, v, size)
                    self.A[reg] = a & M32
                else:
                    a = self.ea_addr(mode, reg, size)
                    for i in range(16):
                        if mask & (1 << i):
                            v = self.D[i] if i < 8 else self.A[i - 8]
                            self.write(a, v, size)
                            a += step
            return
        if (op & 0xFFC0) == 0x4E80:  # jsr
            a = self.ea_addr(mode, reg, 2)
            self.push32(self.pc)
            self.pc = a
            return
        if (op & 0xFFC0) == 0x4EC0:  # jmp
            self.pc = self.ea_addr(mode, reg, 2)
            return
        if op == 0x4E75:             # rts
            self.pc = self.pop32()
            return
        if op == 0x4E73:             # rte
            self.sr = self.r16(self.A[7])
            self.A[7] = (self.A[7] + 2) & M32
            self.pc = self.pop32()
            return
        if op == 0x4E71:             # nop
            return
        if (op & 0xFFF0) == 0x4E60:  # move usp
            if op & 8:
                self.A[reg] = getattr(self, "usp", 0)
            else:
                self.usp = self.A[reg]
            return
        if (op & 0xFFF8) == 0x4E50:  # link
            self.push32(self.A[reg])
            self.A[reg] = self.A[7]
            self.A[7] = (self.A[7] + sext(self.fetch16(), 1)) & M32
            return
        if (op & 0xFFF8) == 0x4E58:  # unlk
            self.A[7] = self.A[reg]
            self.A[reg] = self.pop32()
            return
        if op == 0x4E70:             # reset
            return
        if op == 0x4E72:             # stop
            self.fetch16()
            self.halted = True
            return
        raise NotImplementedError(f"opcode {op:04x} à {self.pc - 2:06x}")

    # --- groupe 5 : addq/subq/scc/dbcc ---
    def grp_5(self, op: int):
        mode, reg = (op >> 3) & 7, op & 7
        size = (op >> 6) & 3
        if size == 3:
            cc = (op >> 8) & 0xF
            if mode == 1:            # dbcc
                disp = sext(self.fetch16(), 1)
                if not self.cond(cc):
                    v = (self.D[reg] - 1) & M16
                    self.set_dreg(reg, v, 1)
                    if v != 0xFFFF:
                        self.pc = (self.pc - 2 + disp) & M32
                return
            self.ea_write(mode, reg, 0, 0xFF if self.cond(cc) else 0)
            return
        n = (op >> 9) & 7 or 8
        if mode == 1:
            if op & 0x100:
                self.A[reg] = (self.A[reg] - n) & M32
            else:
                self.A[reg] = (self.A[reg] + n) & M32
            return
        if op & 0x100:
            def fn(d):
                r = d - n
                self.flags_sub(n, d, r, size)
                return r
        else:
            def fn(d):
                r = d + n
                self.flags_add(n, d, r, size)
                return r
        self.ea_rmw(mode, reg, size, fn)

    # --- groupe 6 : branchements ---
    def grp_6(self, op: int):
        cc = (op >> 8) & 0xF
        disp = sext(op, 0)
        base = self.pc
        if disp == 0:
            disp = sext(self.fetch16(), 1)
        elif disp == -1:
            disp = sext(self.fetch32(), 2)
        if cc == 1:                  # bsr
            self.push32(self.pc)
            self.pc = (base + disp) & M32
            return
        if self.cond(cc):
            self.pc = (base + disp) & M32

    def grp_7(self, op: int):        # moveq
        v = sext(op, 0) & M32
        self.D[(op >> 9) & 7] = v
        self.set_nz(v, 2)

    # --- or / sbcd ---
    def grp_8(self, op: int):
        mode, reg = (op >> 3) & 7, op & 7
        dn = (op >> 9) & 7
        size = (op >> 6) & 3
        if size == 3:
            raise NotImplementedError("divu/divs")
        if (op & 0x1F0) == 0x100:    # sbcd
            self._bcd(op, sub=True)
            return
        if op & 0x100:
            s = self.D[dn]
            def fn(d):
                r = d | s
                self.set_nz(r, size)
                return r
            self.ea_rmw(mode, reg, size, fn)
        else:
            s = self.ea_read(mode, reg, size)
            r = (self.D[dn] | s) & MASK[size]
            self.set_dreg(dn, r, size)
            self.set_nz(r, size)

    def _bcd(self, op: int, sub: bool):
        mode = 4 if op & 8 else 0
        rx, ry = (op >> 9) & 7, op & 7
        if mode == 0:
            s = self.D[ry] & 0xFF
            d = self.D[rx] & 0xFF
        else:
            sa = self.ea_addr(4, ry, 0)
            da = self.ea_addr(4, rx, 0)
            s = self.r8(sa)
            d = self.r8(da)
        x = 1 if self.sr & X_ else 0
        if not sub:
            lo = (d & 0xF) + (s & 0xF) + x
            hi = (d >> 4) + (s >> 4)
            if lo > 9:
                lo -= 10
                hi += 1
            c = 0
            if hi > 9:
                hi -= 10
                c = 1
        else:
            lo = (d & 0xF) - (s & 0xF) - x
            hi = (d >> 4) - (s >> 4)
            if lo < 0:
                lo += 10
                hi -= 1
            c = 0
            if hi < 0:
                hi += 10
                c = 1
        r = ((hi & 0xF) << 4) | (lo & 0xF)
        f = self.sr & ~(C_ | X_ | N_)
        if c:
            f |= C_ | X_
        if r != 0:
            f &= ~Z_
        if r & 0x80:
            f |= N_
        self.sr = f
        if mode == 0:
            self.set_dreg(rx, r, 0)
        else:
            self.w8(da, r)

    # --- sub / suba / subx ---
    def grp_9(self, op: int):
        self._addsub(op, sub=True)

    def grp_d(self, op: int):
        self._addsub(op, sub=False)

    def _addsub(self, op: int, sub: bool):
        mode, reg = (op >> 3) & 7, op & 7
        dn = (op >> 9) & 7
        size = (op >> 6) & 3
        if size == 3:                # adda / suba
            size = 2 if op & 0x100 else 1
            s = self.ea_read(mode, reg, size)
            if size == 1:
                s = sext(s, 1)
            if sub:
                self.A[dn] = (self.A[dn] - s) & M32
            else:
                self.A[dn] = (self.A[dn] + s) & M32
            return
        if (op & 0x130) == 0x100:    # addx/subx
            raise NotImplementedError("addx/subx")
        if op & 0x100:               # Dn op <ea> -> <ea>
            s = self.D[dn] & MASK[size]
            def fn(d):
                if sub:
                    r = d - s
                    self.flags_sub(s, d, r, size)
                else:
                    r = d + s
                    self.flags_add(s, d, r, size)
                return r
            self.ea_rmw(mode, reg, size, fn)
        else:
            s = self.ea_read(mode, reg, size)
            d = self.D[dn] & MASK[size]
            if sub:
                r = d - s
                self.flags_sub(s, d, r, size)
            else:
                r = d + s
                self.flags_add(s, d, r, size)
            self.set_dreg(dn, r, size)

    # --- cmp / cmpa / cmpm / eor ---
    def grp_b(self, op: int):
        mode, reg = (op >> 3) & 7, op & 7
        dn = (op >> 9) & 7
        size = (op >> 6) & 3
        if size == 3:                # cmpa
            size = 2 if op & 0x100 else 1
            s = self.ea_read(mode, reg, size)
            if size == 1:
                s = sext(s, 1) & M32
            d = self.A[dn]
            self.flags_sub(s, d, d - s, 2, x=False)
            return
        if op & 0x100:
            if mode == 1:            # cmpm
                s = self.read(self.ea_addr(3, reg, size), size)
                d = self.read(self.ea_addr(3, dn, size), size)
                self.flags_sub(s, d, d - s, size, x=False)
                return
            s = self.D[dn] & MASK[size]   # eor
            def fn(d):
                r = d ^ s
                self.set_nz(r, size)
                return r
            self.ea_rmw(mode, reg, size, fn)
            return
        s = self.ea_read(mode, reg, size)
        d = self.D[dn] & MASK[size]
        self.flags_sub(s, d, d - s, size, x=False)

    # --- and / abcd / mulu / exg ---
    def grp_c(self, op: int):
        mode, reg = (op >> 3) & 7, op & 7
        dn = (op >> 9) & 7
        size = (op >> 6) & 3
        if size == 3:
            s = self.ea_read(mode, reg, 1)
            d = self.D[dn] & M16
            if op & 0x100:           # muls
                r = (sext(s, 1) * sext(d, 1)) & M32
            else:
                r = (s * d) & M32
            self.D[dn] = r
            self.set_nz(r, 2)
            return
        if (op & 0x1F0) == 0x100:    # abcd
            self._bcd(op, sub=False)
            return
        if (op & 0x1F8) in (0x140, 0x148, 0x188):   # exg
            if (op & 0x1F8) == 0x140:
                self.D[dn], self.D[reg] = self.D[reg], self.D[dn]
            elif (op & 0x1F8) == 0x148:
                self.A[dn], self.A[reg] = self.A[reg], self.A[dn]
            else:
                self.D[dn], self.A[reg] = self.A[reg], self.D[dn]
            return
        if op & 0x100:
            s = self.D[dn] & MASK[size]
            def fn(d):
                r = d & s
                self.set_nz(r, size)
                return r
            self.ea_rmw(mode, reg, size, fn)
        else:
            s = self.ea_read(mode, reg, size)
            r = (self.D[dn] & s) & MASK[size]
            self.set_dreg(dn, r, size)
            self.set_nz(r, size)

    # --- décalages / rotations ---
    def grp_e(self, op: int):
        size = (op >> 6) & 3
        if size == 3:                # mémoire, 1 bit, mot
            kind = (op >> 9) & 3
            left = bool(op & 0x100)
            mode, reg = (op >> 3) & 7, op & 7
            a = self.ea_addr(mode, reg, 1)
            self.w16(a, self._shift(self.r16(a), 1, kind, left, 1))
            return
        kind = (op >> 3) & 3
        left = bool(op & 0x100)
        reg = op & 7
        if op & 0x20:
            n = self.D[(op >> 9) & 7] & 63
        else:
            n = (op >> 9) & 7 or 8
        v = self.D[reg] & MASK[size]
        self.set_dreg(reg, self._shift(v, n, kind, left, size), size)

    def _shift(self, v: int, n: int, kind: int, left: bool, size: int) -> int:
        bits = BITS[size]
        m = MASK[size]
        msb = MSB[size]
        f = self.sr & ~(N_ | Z_ | V_ | C_)
        x = bool(self.sr & X_)
        r = v
        if kind == 0 or kind == 1:   # asl/asr (0), lsl/lsr (1)
            if n == 0:
                c = 0
            elif left:
                vflag = False
                c = 0
                for _ in range(n):
                    c = (r & msb) != 0
                    nr = (r << 1) & m
                    if kind == 0 and ((nr & msb) != 0) != ((r & msb) != 0):
                        vflag = True
                    r = nr
                if vflag:
                    f |= V_
            else:
                c = 0
                for _ in range(n):
                    c = r & 1
                    if kind == 0:
                        r = (r >> 1) | (r & msb)
                    else:
                        r >>= 1
            if n:
                f = (f & ~X_) | ((C_ | X_) if c else 0)
        elif kind == 2:              # roxl/roxr
            for _ in range(n):
                if left:
                    c = (r & msb) != 0
                    r = ((r << 1) & m) | (1 if x else 0)
                else:
                    c = (r & 1) != 0
                    r = (r >> 1) | (msb if x else 0)
                x = c
            f = (f & ~X_) | ((C_ | X_) if x else 0)
        else:                        # rol/ror
            c = 0
            for _ in range(n):
                if left:
                    c = (r & msb) != 0
                    r = ((r << 1) & m) | (1 if c else 0)
                else:
                    c = (r & 1) != 0
                    r = (r >> 1) | (msb if c else 0)
            if c:
                f |= C_
        r &= m
        if r == 0:
            f |= Z_
        elif r & msb:
            f |= N_
        self.sr = f
        return r

    def grp_a(self, op): raise NotImplementedError("line A")
    def grp_f(self, op): raise NotImplementedError("line F")

    # ------------------------------------------------------------------ frames
    WAIT_PC = 0xF42            # boucle d'attente de sys42 : tst.w $ff96.w

    def run_until_wait(self, n0: int, max_instr: int):
        while not (self.pc == self.WAIT_PC and self.r16(0xFFFF96) != 0):
            self.step()
            if self.halted:
                raise RuntimeError("stop")
            if self.icount - n0 > max_instr:
                raise RuntimeError(f"pas d'attente V-int après {max_instr} instructions (pc={self.pc:06x})")

    def run_frame(self, pad: int, max_instr: int = 5_000_000) -> int:
        """Une frame : atteint l'attente de V-int, délivre l'interruption (qui
        lit la manette `pad`), puis exécute la logique jusqu'à la prochaine
        attente. L'état obtenu correspond à Game.step(pad) du port."""
        self.pad1 = pad & 0xFF
        n0 = self.icount
        self.run_until_wait(n0, max_instr)
        self.interrupt(6, 0x78)
        self.frames += 1
        sp = self.A[7]
        while not (self.pc == self.WAIT_PC and self.A[7] == sp + 6):
            self.step()
            if self.icount - n0 > max_instr:
                raise RuntimeError("V-int trop long")
        self.run_until_wait(n0, max_instr)
        return self.icount - n0


def load_rom(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


if __name__ == "__main__":
    import sys, time
    sys.path.insert(0, ".")
    from flicky.rom import find_rom
    m = Machine(load_rom(find_rom(sys.argv[1] if len(sys.argv) > 1 else None)))
    t = time.time()
    for f in range(int(sys.argv[2]) if len(sys.argv) > 2 else 300):
        n = m.run_frame(0x80 if f == 250 else 0)
        if f % 50 == 0 or f > 295:
            print(f"frame {f}: {n} instr, ffc0={m.r16(0xFFFFC0):04x} ff92={m.r16(0xFFFF92):04x} pc={m.pc:06x}")
    print(f"{m.icount} instructions en {time.time() - t:.1f}s")
