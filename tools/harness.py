"""Exécution en parallèle du port Python et de la ROM (interpréteur 68000) avec
comparaison de l'état à chaque frame et 'pokes' identiques des deux côtés."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.m68k import Machine, load_rom
from flicky.game import Game
from flicky.obj import set_hi


def norm(v):
    if (v & 0xFFFF0000) in (0xFFFF0000, 0x00FF0000):
        return 0x10000 | (v & 0xFFFF)
    return v


class Lockstep:
    def __init__(self):
        self.g = Game()
        self.m = Machine(load_rom(self.g.rom.path))
        self.frame = 0
        self.bad = 0
        self.first_bad = None
        self.log = []

    # --- accès ---
    def state(self):
        return (self.m.r16(0xFFFFC0) & 0x7C) >> 2

    def step(self, pad):
        self.m.run_frame(pad)
        self.g.step(pad)
        self.frame += 1

    def obj_fields(self, i):
        m, o = self.m, self.g.objs[i]
        b = 0xFFC000 + 0x40 * i
        return [
            ("routine", m.r16(b), o.routine | (0x8000 if o.init else 0)),
            ("flags", m.r8(b + 2), o.flags), ("hit_id", m.r8(b + 4), o.hit_id), ("hit", m.r8(b + 5), o.hit),
            ("anim", m.r16(b + 6), o.anim), ("anim_table", norm(m.r32(b + 8)), o.anim_table),
            ("frame_ptr", norm(m.r32(b + 0xC)), o.frame_ptr), ("frame", m.r8(b + 0x10), o.frame),
            ("ftimer", m.r8(b + 0x11), o.ftimer), ("pal", m.r8(b + 0x13), o.pal), ("b16", m.r8(b + 0x16), o.b16),
            ("xs", m.r16(b + 0x20), o.xs & 0xFFFF), ("y", m.r32(b + 0x24), o.y & 0xFFFFFFFF),
            ("vy", m.r32(b + 0x2C), o.vy & 0xFFFFFFFF), ("x", m.r32(b + 0x30), o.x & 0xFFFFFFFF),
            ("vx", m.r32(b + 0x34), o.vx & 0xFFFFFFFF), ("w38", m.r16(b + 0x38), o.w38),
            ("w3a", m.r16(b + 0x3A), o.w3a), ("v3c", m.r16(b + 0x3C), o.v3c), ("w3e", m.r16(b + 0x3E), o.w3e),
        ]

    def globals_fields(self):
        m, g = self.m, self.g
        return [
            ("ffc0 state", m.r16(0xFFFFC0), g.state_id), ("ff92 frame", m.r16(0xFFFF92), g.frame),
            ("ff8e pad", m.r8(0xFFFF8E), g.pad), ("ffa8 camx", m.r32(0xFFFFA8), g.camx & 0xFFFFFFFF),
            ("ffa4 camy", m.r32(0xFFFFA4), g.camy & 0xFFFFFFFF),
            ("d004 camvx", m.r32(0xFFD004), g.cam_vx & 0xFFFFFFFF), ("d24e bonusmode", m.r8(0xFFD24E), g.bonus_mode),
            ("d24f atdoor", m.r8(0xFFD24F), g.at_door), ("d26c enemies", m.r8(0xFFD26C), g.enemies_alive),
            ("d26d hit", m.r8(0xFFD26D), g.player_hit), ("d27a following", m.r8(0xFFD27A), g.following),
            ("d27b freeze", m.r8(0xFFD27B), g.freeze), ("d27c lizspeed", m.r32(0xFFD27C), g.lizard_speed & 0xFFFFFFFF),
            ("d281 rounddone", m.r8(0xFFD281), g.round_done), ("d28e bcaught", m.r8(0xFFD28E), g.bonus_caught),
            ("d290 bscore", m.r32(0xFFD290), g.bonus_score), ("d294 spawndelay", m.r16(0xFFD294), g.spawn_delay),
            ("d296 catspeed", m.r32(0xFFD296), g.cat_speed & 0xFFFFFFFF), ("d2a0 playsub", m.r16(0xFFD2A0), g.play_sub),
            ("d2a4 jingle", m.r8(0xFFD2A4), g.jingle), ("d2a6 bonussub", m.r16(0xFFD2A6), g.bonus_sub),
            ("d82c roundbcd", m.r8(0xFFD82C), g.round_bcd), ("d82d round", m.r8(0xFFD82D), g.round),
            ("d87e score", m.r32(0xFFD87E), g.score), ("d882 lives", m.r8(0xFFD882), g.lives),
            ("d883 chirps", m.r8(0xFFD883), g.chirps_left), ("d886 restore", m.r8(0xFFD886), g.restore_chirps),
            ("d887 extra", m.r8(0xFFD887), g.extra_bits),
            ("d888 timer", (m.r8(0xFFD888), m.r8(0xFFD889), m.r8(0xFFD88A)), (g.t_min, g.t_sec, g.t_frame)),
            ("d88c bcount", m.r8(0xFFD88C), g.bonus_count), ("d88d reached", m.r8(0xFFD88D), g.reached),
            ("d88f nobonus", m.r8(0xFFD88F), g.no_bonus), ("cc00 hiscore", m.r32(0xFFCC00), g.hiscore),
        ]

    def diff(self, skip_objects=False):
        out = []
        for name, a, b in self.globals_fields():
            if a != b:
                out.append(f"  {name}: rom={a if not isinstance(a, int) else hex(a)} port={b if not isinstance(b, int) else hex(b)}")
        cm = self.m.ram[0xC800:0xCC00]
        if bytes(cm) != bytes(self.g.cmap):
            n = sum(1 for a, b in zip(cm, self.g.cmap) if a != b)
            first = next(i for i, (a, b) in enumerate(zip(cm, self.g.cmap)) if a != b)
            out.append(f"  cmap: {n} cases différentes, première c{0x800 + first:03X} rom={cm[first]:02x} port={self.g.cmap[first]:02x}")
        if not skip_objects:
            for i in range(32):
                for name, a, b in self.obj_fields(i):
                    if a != b:
                        out.append(f"  obj C{0x40*i:03X} {name}: rom={a:x} port={b:x}")
        return out

    def check(self, label="", max_lines=20):
        s = self.state()
        prev = getattr(self, "_prev_state", None)
        self._prev_state = s
        d = self.diff(skip_objects=(s in (16, 17)) or (prev in (16, 17)))
        if d:
            self.bad += 1
            if self.first_bad is None:
                self.first_bad = self.frame
            print(f"--- frame {self.frame} état {s} {label}: {len(d)} différences")
            for line in d[:max_lines]:
                print(line)
        return bool(d)

    # --- pokes (identiques des deux côtés) ---
    def poke_obj(self, addr, **fields):
        m = self.m
        o = self.g.obj(addr)
        b = 0xFF0000 | addr
        for k, v in fields.items():
            if k == "xi":
                m.w16(b + 0x30, v & 0xFFFF); o.xi = v
            elif k == "yi":
                m.w16(b + 0x24, v & 0xFFFF); o.yi = v
            elif k == "x":
                m.w32(b + 0x30, v & 0xFFFFFFFF); o.x = v
            elif k == "y":
                m.w32(b + 0x24, v & 0xFFFFFFFF); o.y = v
            elif k == "vx":
                m.w32(b + 0x34, v & 0xFFFFFFFF); o.vx = v
            elif k == "vy":
                m.w32(b + 0x2C, v & 0xFFFFFFFF); o.vy = v
            elif k == "b38":
                m.w8(b + 0x38, v); o.b38 = v
            elif k == "b39":
                m.w8(b + 0x39, v); o.b39 = v
            elif k == "routine":
                m.w16(b, v); o.routine = v & 0x7FFF; o.init = bool(v & 0x8000)
            else:
                raise KeyError(k)

    def poke_global(self, name, v):
        m, g = self.m, self.g
        if name == "lives":
            m.w8(0xFFD882, v); g.lives = v
        elif name == "score":
            m.w32(0xFFD87E, v); g.score = v
        elif name == "demo_idx":
            m.w16(0xFFD890, v); g.demo_idx = v
        elif name == "ff92":
            m.w16(0xFFFF92, v); g.frame = v
        else:
            raise KeyError(name)
