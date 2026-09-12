"""Machine à états et logique globale de Flicky (segment code FF0000).

`Game.step(pad)` avance d'une frame (un vblank). La logique est écrite sous
forme de générateurs : chaque `yield` correspond à `jsr $fb6c` (attente du
V-int) dans le code original, y compris au milieu des mises à jour d'objets.
"""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from .rom import Rom, font_tiles, nemesis_decode
from .data import Data, ram
from .obj import Obj, F_NOPHYS, F_HIDDEN, F_ANIMEND, F_XFLIP, s32, s16, hi, set_hi, clr_lo
from . import objects as ob
from .objects import (PLAYER, ITEMS, ENEMIES, CHIRPS, SPAWNERS, PAD_START, PAD_UP, PAD_DOWN,
                      R_ITEM, R_CHIRP, R_PLAYER, R_CAT, R_LIZARD, R_SPAWNER, R_NET, R_BCAT_L,
                      R_BCAT_R, R_BCHIRP, R_GAMEOVER, R_TITLE_CAST, R_PUSH_START, R_TITLE_LETTER,
                      R_INSTR, R_ENDING, R_FLAG, R_PAUSE, bcd_add8)

PLANE_A, PLANE_B = 0xC000, 0xE000
SCREEN_W, SCREEN_H = 256, 224


def bcd_add32(a: int, b: int) -> int:
    """Addition BCD sur 4 octets (abcd x4)."""
    carry = 0
    out = 0
    for i in range(4):
        x = (a >> (8 * i)) & 0xFF
        y = (b >> (8 * i)) & 0xFF
        lo = (x & 0xF) + (y & 0xF) + carry
        carry = 0
        if lo > 9:
            lo -= 10
            carry = 1
        h = (x >> 4) + (y >> 4) + carry
        carry = 0
        if h > 9:
            h -= 10
            carry = 1
        out |= ((h << 4) | lo) << (8 * i)
    return out


def bcd_to_int(v: int) -> int:
    n = 0
    m = 1
    while v:
        n += (v & 0xF) * m
        m *= 10
        v >>= 4
    return n


class Game:
    def __init__(self, rom_path: Optional[str] = None, overseas: bool = True, pal: bool = False):
        self.rom = Rom(rom_path)
        self.d = Data(self.rom)
        self.overseas = overseas
        self.pal = pal
        self.objs: List[Obj] = [Obj(0xC000 + 0x40 * i) for i in range(32)]
        # --- vidéo (pour le rendu uniquement) ---
        self.vram = bytearray(0x800 * 32)
        self.plane_a = [[0] * 32 for _ in range(32)]
        self.plane_b = [[0] * 32 for _ in range(32)]
        self.palette = [0] * 64          # f7e0
        self.palette_src = [0] * 64      # f860
        self.fade_level = 0x40           # 0x40 = pleine intensité (sys52)
        self.fade_mask = 0               # ffb8/ffbc : couleurs préservées
        self.sprites: List[Tuple[int, int, int, int]] = []
        self.display_on = True
        self.sound_log: List[Tuple[int, str, int]] = []
        self.music_queue: List[int] = []
        # --- entrées ---
        self.pad_raw = 0
        self.pad = 0          # ff8e
        self.pad_edge = 0     # ff8f
        self.vint_count = 0   # nombre total de frames
        self.reset_globals()
        self.load_base_art()
        self.gen = self.main_loop()
        next(self.gen)          # boot jusqu'à la première attente de V-int

    # ------------------------------------------------------------------
    def reset_globals(self):
        self.state_id = 0x40         # ffc0 : démarre sur l'écran SEGA (état 16)
        self.frame = 0               # ff92
        self.camx = 0                # ffa8.l
        self.camy = 0                # ffa4.l
        self.cam_vx = 0              # d004
        self.cam_vy = 0              # d008
        self.bonus_mode = 0          # d24e
        self.at_door = 0             # d24f
        self.held_item: Optional[Obj] = None   # d250
        self.door_y = 0              # d25c
        self.door_x0 = 0             # d25e
        self.door_x1 = 0             # d260
        self.score_add = 0           # d262 (BCD)
        self.time_min = 0            # d266
        self.time_sec = 0            # d267
        self.time_bonus_val = 0      # d268
        self.enemies_alive = 0       # d26c
        self.player_hit = 0          # d26d
        self.cat_jump_vx = 0         # d26e
        self.cat_jump_vy = 0         # d272
        self.run_speed = 0           # d276
        self.following = 0           # d27a
        self.freeze = 0              # d27b
        self.lizard_speed = 0        # d27c
        self.pal_counter = 0         # d280
        self.round_done = 0          # d281
        self.bonus_delays_ptr = 0    # d282
        self.bonus_launch_ptr = 0    # d286
        self.bonus_script_ptr = 0    # d28a
        self.bonus_caught = 0        # d28e
        self.bonus_caught_bcd = 0    # d28f
        self.bonus_score = 0         # d290 (BCD)
        self.spawn_delay = 0         # d294
        self.cat_speed = 0           # d296
        self.zero_score = 0          # d29a
        self.credit_line = 0         # d29c
        self.credit_timer = 0        # d29d
        self.ending_sub = 0          # d29e
        self.play_sub = 0            # d2a0
        self.hitstop = 0             # d2a2
        self.jingle = 0              # d2a4
        self.demo = 0                # d2a5
        self.bonus_sub = 0           # d2a6
        self.demo_pad = 0            # d2a8
        self.demo_ptr = 0            # d2aa
        self.demo_left = 0           # d2ac
        self.door_anim_state = [0, 0, 0]   # d258 : frame, timer, fini
        self.round_bcd = 0x01        # d82c
        self.round = 1               # d82d
        self.door_tx = 0             # d82e
        self.door_ty = 0             # d82f
        self.block_pos = [0] * 6     # d830..d835
        self.score = 0               # d87e (BCD)
        self.lives = 0               # d882
        self.chirps_left = 0         # d883
        self.text_base = 0x8000      # d884
        self.restore_chirps = 0      # d886
        self.extra_bits = 0          # d887
        self.t_min = 0               # d888
        self.t_sec = 0               # d889
        self.t_frame = 0             # d88a
        self.bonus_count = 0         # d88c
        self.reached = 0             # d88d
        self.font_color = 0          # d88e
        self.no_bonus = 0            # d88f
        self.demo_idx = 0            # d890
        self.hiscore = 0x00100000    # cc00 (BCD 100000)
        self.trail: List[Tuple[int, int]] = [(0, 0)] * 64        # d00e..
        self.trail_flags: List[int] = [0] * 64                   # d20e..
        self.cmap = bytearray(0x400)                             # c800..cbff (les marqueurs FF1608 peuvent dépasser cb7f)
        self.saved_chirps: List[Obj] = []                        # de00..
        # pointeurs de jeux de tuiles (d800..d828)
        self.floor_set = self.d.floor_sets[0]
        self.top_set = self.d.top_sets[0]
        self.bottom_set = self.d.bottom_sets[0]
        self.block_arts = [self.d.block0_art, self.d.block1_art, self.d.block2_art,
                           self.d.block3_sets[0], self.d.block4_sets[0], self.d.block5_sets[0]]
        self.item_frame = self.d.item_frames[0]

    # ------------------------------------------------------------------
    # accès objets / utilitaires 68000
    # ------------------------------------------------------------------
    def obj(self, addr: int) -> Obj:
        return self.objs[(addr - 0xC000) >> 6]

    def tile_to_px(self, tx: int, ty: int) -> Tuple[int, int]:
        """FF1674"""
        return ((tx & 0xFF) << 3) + 0x80, ((ty & 0xFF) << 3) + 0x80

    def timer_word(self) -> int:
        """d888.w = minutes:secondes BCD"""
        return (self.t_min << 8) | self.t_sec

    def probe(self, x: int, y: int) -> int:
        """FF157C : case de collision à (x, y) pixels, & 0xF."""
        x &= 0xFFFF
        if x < 0x80 or x >= 0x8000:
            x = (x + 0x100) & 0xFFFF
        if x >= 0x180 and x < 0x8000:
            x = (x - 0x100) & 0xFFFF
        y &= 0xFFFF
        idx = ((x - 0x80) >> 3) + (((y - 0x80) & 0xFFFF) >> 3) * 32
        idx &= 0xFFFF
        if idx >= 0x400:
            return 0
        return self.cmap[idx] & 0xF

    def probe_rel(self, o: Obj, dx: int, dy: int) -> int:
        """FF15C0 : octet complet de la case à (x+dx, y+dy)."""
        x = (o.xi + dx) & 0xFFFF
        y = (o.yi + dy) & 0xFFFF
        if x < 0x80 or x >= 0x8000:
            x = (x + 0x100) & 0xFFFF
        if x >= 0x180 and x < 0x8000:
            x = (x - 0x100) & 0xFFFF
        idx = ((x - 0x80) >> 3) + (((y - 0x80) & 0xFFFF) >> 3) * 32
        idx &= 0xFFFF
        if idx >= 0x400:
            return 0
        return self.cmap[idx]

    def collide(self, a: Obj, b: Obj) -> bool:
        """FF17C0 : test de boîtes (a0=a, a1=b)."""
        if b.routine == 0:
            return False
        ia, ib = a.hit_id, b.hit_id
        if ia == 0xFF or ib == 0xFF:
            return False
        ha = self.d.hitboxes[ia]
        hb = self.d.hitboxes[ib]
        d2 = s16(a.xs + ha[0])
        d3 = s16(d2 + ha[1])
        d4 = s16(b.xs + hb[0])
        d5 = s16(d4 + hb[1])
        if not ((d2 <= d4 <= d3) or (d2 <= d5 <= d3) or (d4 <= d2 <= d5) or (d4 <= d3 <= d5)):
            return False
        d2 = s16(a.yi + ha[2])
        d3 = s16(d2 + ha[3])
        d4 = s16(b.yi + hb[2])
        d5 = s16(d4 + hb[3])
        return (d2 <= d4 <= d3) or (d2 <= d5 <= d3) or (d4 <= d2 <= d5) or (d4 <= d3 <= d5)

    def add_score(self):
        """FF168A"""
        if self.demo:
            return
        self.score = bcd_add32(self.score, self.score_add)
        self.draw_score()
        if self.score > self.hiscore:
            self.hiscore = self.score
            self.draw_hiscore()

    def sfx(self, sid: int):
        """FF0D48 : effet sonore direct (sauf pendant le jingle de vie)."""
        if not self.jingle:
            self.sound_log.append((self.vint_count, "sfx", sid))

    def music(self, sid: int):
        """sys41 (0x1100) : commande son mise en file."""
        if len(self.music_queue) < 8:
            self.music_queue.append(sid)

    def timer_tick(self):
        """FF16BE"""
        self.t_frame = bcd_add8(self.t_frame, 1)
        if self.t_frame < 0x60:
            return
        self.t_frame = 0
        self.t_sec = bcd_add8(self.t_sec, 1)
        if self.t_sec < 0x60:
            return
        self.t_sec = 0
        self.t_min = bcd_add8(self.t_min, 1)

    def camera_step(self):
        """FF130C"""
        self.camx = s32(self.camx + self.cam_vx)
        self.camy = s32(self.camy + self.cam_vy)

    def physics(self, o: Obj):
        """FF105C"""
        if o.flags & F_NOPHYS:
            return
        d2 = s32(o.x + o.vx)
        if d2 < 0x800000:
            d2 = s32(d2 + 0x1000000)
        if d2 >= 0x1800000:
            d2 = s32(d2 - 0x1000000)
        o.x = d2
        d2 = (hi(d2) - hi(self.camx)) & 0xFFFF
        d2 = d2 - 0x10000 if d2 & 0x8000 else d2
        while d2 < 0x80:
            d2 += 0x100
        while d2 >= 0x180:
            d2 -= 0x100
        o.xs = d2
        o.y = s32(o.y + o.vy)

    def screen_x(self, o: Obj):
        """FF10BA : x écran depuis x monde (sans déplacement)."""
        d2 = s32(o.x - self.camx)
        while d2 < 0x800000:
            d2 = s32(d2 + 0x1000000)
        while d2 >= 0x1800000:
            d2 = s32(d2 - 0x1000000)
        o.xs = hi(d2) & 0xFFFF
        o.y = s32(o.y + o.vy)

    NULL_ANIM = None

    def animate(self, o: Obj):
        """FF1126"""
        if o.anim_table == 0:
            # objet effacé : la ROM lit la 'table' à l'adresse 0 -> long 0x00FFFF70
            # (cache des registres VDP en RAM : 04 34 30 2c 07 5f 00 00 ...)
            from .rom import Anim
            if Game.NULL_ANIM is None:
                cache = [0x04, 0x34, 0x30, 0x2C, 0x07, 0x5F, 0x00, 0x00, 0x00, 0x00]
                ptrs = [0x10000 | ((cache[2 + 2 * k] << 8) | cache[3 + 2 * k]) for k in range(4)]
                Game.NULL_ANIM = Anim(cache[0], cache[1], ptrs)
            table = [Game.NULL_ANIM]
        else:
            table = self.d.anim_table(o.anim_table)
        an = table[(o.anim >> 2) & 0xFF] if (o.anim >> 2) < len(table) else table[0]
        o.ftimer = (o.ftimer - 1) & 0xFF
        if o.ftimer & 0x80:
            o.ftimer = an.delay
            o.frame = (o.frame + 1) & 0xFF
        d0 = o.frame
        if d0 >= an.frames:
            o.frame = 0
            d0 = 0
            o.set_flag(F_ANIMEND)
        o.frame_ptr = an.ptrs[d0]

    # ------------------------------------------------------------------
    # attente V-int / entrées
    # ------------------------------------------------------------------
    def vblank(self):
        """sys42 (0x1114) + V-int (FF0EBA)."""
        self.music_queue.clear()
        yield
        self.vint_count += 1
        self.read_pad()

    def read_pad(self):
        """0xE12"""
        held = self.pad_raw & 0xFF
        old = self.pad
        self.pad = held
        self.pad_edge = (held ^ old) & held

    def step(self, pad: int = 0):
        """Avance d'une frame avec l'état de la manette donné (bits PAD_*)."""
        self.pad_raw = pad
        next(self.gen)

    # ------------------------------------------------------------------
    # vidéo
    # ------------------------------------------------------------------
    def load_tiles(self, tile: int, data: bytes):
        self.vram[tile * 32:tile * 32 + len(data)] = data

    def load_base_art(self):
        """FF00FC : art principal + fonts."""
        self.load_tiles(0x200, self.rom.nemesis(0x16E58))
        self.load_tiles(0x400, self.rom.nemesis(0x187D4))
        self.font_color = 1
        self.load_fonts()

    def load_fonts(self):
        """FF0126"""
        c = 0x20 + self.font_color
        fg, bg = c >> 4, c & 0xF
        self.load_tiles(0x20, font_tiles(self.rom, 0x2372, 0xB3, fg, bg))
        self.load_tiles(0x30, font_tiles(self.rom, 0x185FC, 0x2B, fg, bg))
        c = 0x30 + self.font_color
        fg, bg = c >> 4, c & 0xF
        self.load_tiles(0x120, font_tiles(self.rom, 0x2372, 0xB3, fg, bg))
        self.load_tiles(0x130, font_tiles(self.rom, 0x185FC, 0x2B, fg, bg))

    def load_title_art(self):
        """FF01A8"""
        self.load_tiles(0x640, self.rom.nemesis(0x1993E))
        self.load_tiles(0x693, self.rom.nemesis(0x18754))

    def clear_planes(self):
        for row in self.plane_a:
            for i in range(32):
                row[i] = 0
        for row in self.plane_b:
            for i in range(32):
                row[i] = 0

    def plane_write(self, vram: int, tile: int):
        """Écrit un mot de nametable à l'adresse VRAM (C000.. ou E000..)."""
        if vram >= PLANE_B:
            plane, off = self.plane_b, vram - PLANE_B
        else:
            plane, off = self.plane_a, vram - PLANE_A
        if 0 <= off < 0x800:
            plane[off >> 6][(off & 0x3F) >> 1] = tile & 0xFFFF

    def plane_addr(self, base: int, tx: int, ty: int) -> int:
        """FF0F24"""
        return base + (ty << 6) + (tx << 1)

    def draw_block(self, base: int, tx: int, ty: int, art: int, w: int, h: int):
        """FF0F70 : bloc de (w x h) tuiles lues dans la ROM à `art`."""
        a = art
        for j in range(h):
            for i in range(w):
                self.plane_write(self.plane_addr(base, tx + i, ty + j), self.rom.u16(a))
                a += 2

    def draw_tile(self, vram: int, tile: int):
        """FF0F94 : tuile avec base de texte d884."""
        if self.text_base == 0xFFFF:
            self.plane_write(vram, 0x8020)
        else:
            self.plane_write(vram, (tile + self.text_base) & 0xFFFF)

    def draw_text_list(self, addr: int):
        """FF0FAA : [adresse VRAM.w][chaîne 0-terminée]"""
        r = self.rom
        vram = r.u16(addr)
        a = addr + 2
        while True:
            c = r.u8(a)
            a += 1
            if c == 0:
                break
            self.draw_tile(vram, c)
            vram += 2

    def draw_text(self, vram: int, s: str):
        for c in s.encode("ascii"):
            self.draw_tile(vram, c)
            vram += 2

    def draw_bigtext_list(self, addr: int):
        """FF0FC0 : texte sur 2 rangées (font 0x640) via FF0DE8."""
        r = self.rom
        vram = r.u16(addr)
        a = addr + 2
        while True:
            c = r.u8(a)
            a += 1
            if c == 0:
                break
            top, bot = self.bigfont_map(c)
            self.draw_tile(vram, top - 0x20)
            self.draw_tile(vram + 0x40, bot - 0x20)
            vram += 2

    @staticmethod
    def bigfont_map(c: int) -> Tuple[int, int]:
        """FF0DE8"""
        d5 = 0
        d4 = (c - 0x20) & 0xFFFF
        if d4 & 0x8000:
            if d4 == 0xFFF3:
                d4 = 0x79
                d5 = 1
            else:
                d4 = (d4 + 0xC0) & 0xFFFF
        else:
            if d4 >= 0x40:
                d4 -= 0x40
                d1 = 0x40
                if d4 >= 0x50:
                    d4 -= 0x50
                    d1 = 0x77
                if d4 >= 0x37:
                    d5 = 1
                    if d4 >= 0x46:
                        if d4 >= 0x4B:
                            d5 = 2
                        else:
                            d4 += 5
                    d4 -= 0x32
                d4 += d1
        d4 = (d4 + 0x40) & 0xFFFF
        if d5:
            d5 += 0xAD
        d5 += 0x40
        return d4, d5

    def draw_bcd(self, value: int, nbytes: int, vram: int):
        """FF0FF4 : nombre BCD (nbytes octets, poids fort en premier)."""
        seen = False
        v = vram - 2
        for i in range(nbytes - 1, -1, -1):
            byte = (value >> (8 * i)) & 0xFF
            for nib in (byte >> 4, byte & 0xF):
                v += 2
                if nib:
                    seen = True
                    self.draw_tile(v, nib + 0x30)
                elif seen:
                    self.draw_tile(v, 0x30)
                elif self.zero_score:
                    self.draw_tile(v, 0)
        if not seen:
            self.draw_tile(v, 0x30)

    def draw_score(self):
        """FF1DC2"""
        self.draw_bcd(self.score, 4, 0xC04A)

    def draw_hiscore(self):
        """FF1DD4"""
        self.draw_bcd(self.hiscore, 4, 0xC068)

    def draw_round(self):
        """FF1DE6"""
        self.draw_bcd(self.round_bcd, 1, 0xC77A if self.pal else 0xC6BA)

    def draw_labels(self):
        """FF1E06 : 1UP / HI (texte FF1E46) puis FF1E1C."""
        self.draw_text_list(ram(0xFF1E4C if self.pal else 0xFF1E46))
        self.draw_block(PLANE_A, 0x24, 1, self.d.label_1up, 2, 1)
        self.draw_block(PLANE_A, 0x32, 1, self.d.label_hi, 3, 1)

    def draw_lives(self):
        """FF1D88"""
        n = self.lives
        if n < 2:
            return
        base = 0xC744 if self.pal else 0xC684
        for i in range(n - 1):
            self.plane_write(base + 2 * i, 0x4350)

    def load_palette_list(self, addr: int):
        """sys55 (0x1196)"""
        pal = self.rom.palette_list(addr)
        for i, c in enumerate(pal):
            if c or True:
                pass
        # la routine n'écrit que les entrées listées : on part de la liste décodée
        a = addr
        while True:
            w = self.rom.u16(a)
            a += 2
            idx = (w & 0x10) | (((w << 4) | (w >> 12)) & 0xF) | ((w & 0x100) >> 3)
            self.palette[idx] = w & 0xEEE
            if w & 1:
                break
        self.fade_level = 0x40

    def select_tilesets(self):
        """FF268E"""
        d = self.d
        k = self.round % 24
        self.floor_set = d.floor_sets[k >> 2]
        self.top_set = d.top_sets[k >> 2]
        self.bottom_set = d.bottom_sets[k >> 2]
        self.block_arts[4] = d.block4_sets[k >> 2]
        self.block_arts[5] = d.block5_sets[k >> 2]
        r = self.round
        while r > 0x20:
            r -= 0x20
        self.block_arts[3] = d.block3_sets[((r - 1) & 0xFF) >> 2]
        r = self.round
        while r > 0xF:
            r -= 0xF
        self.item_frame = d.item_frames[(r - 1) & 0xFF]
        self.block_arts[0] = d.block0_art
        self.block_arts[1] = d.block1_art
        self.block_arts[2] = d.block2_art

    def select_palettes(self):
        """FF2824"""
        k = self.round % 48
        pal = self.d.level_palettes[k >> 2]
        for i in range(16):
            self.palette[16 + i] = pal[i]
        r = self.round
        while r > 0xF:
            r -= 0xF
        pal = self.d.item_palettes[(r - 1) & 0xFF]
        for i in range(4):
            self.palette[60 + i] = pal[i]
        self.fade_level = 0x40

    def fade_out(self):
        """FF1784"""
        self.palette_src = list(self.palette)
        for level in range(0x3E, 0, -2):
            self.fade_level = level
            yield from self.vblank()

    # ------------------------------------------------------------------
    # sprites (FF1254 / FF1166)
    # ------------------------------------------------------------------
    def build_sprites(self):
        out = []
        for o in self.objs:
            if o.routine == 0 or (o.flags & F_HIDDEN):
                continue
            if o.frame_ptr == 0:
                o.hit_id = 0xFF        # mapping à l'adresse 0 : octet 1 = 0xFF
                continue
            fr = self.d.frame(o.frame_ptr)
            o.hit_id = fr.hitbox
            yi = o.yi & 0xFFFF
            if yi > 0x180:
                continue
            xflip = bool(o.flags & F_XFLIP)
            for p in fr.pieces:
                y = (yi + p.dy) & 0xFFFF
                pat = (p.pattern | (o.pal << 8)) & 0xFFFF
                if xflip:
                    pat ^= 0x0800
                    dx = p.dx_flip
                else:
                    dx = p.dx
                x = (o.xs + dx) & 0xFFFF
                if (x - 0x41) & 0xFFFF < 0x17F:
                    out.append((y, p.size, pat, x))
                    if len(out) >= 64:
                        self.sprites = out
                        return
        self.sprites = out

    # ------------------------------------------------------------------
    # exécution des objets (FF11E2 / FF11D4)
    # ------------------------------------------------------------------
    def run_obj(self, o: Obj):
        r = o.routine & 0x7FFC
        if r == 0:
            return
        h = ob.HANDLERS.get(r)
        if h is None:
            return
        if r in ob.GENERATORS:
            yield from h(self, o)
        else:
            h(self, o)

    def run_objects(self):
        """FF11E2"""
        if not self.bonus_mode:
            order = [0xC440] + [0xC200 + 0x40 * i for i in range(9)] + [0xC480 + 0x40 * i for i in range(14)] \
                    + [0xC000 + 0x40 * i for i in range(8)]
        else:
            order = [0xC580] + [0xC040 + 0x40 * i for i in range(21)] + [0xC5C0 + 0x40 * i for i in range(4)]
        for addr in order:
            yield from self.run_obj(self.obj(addr))
        self.build_sprites()

    def run_object_c000(self):
        """FF11D4"""
        yield from self.run_obj(self.obj(0xC000))
        self.build_sprites()

    def clear_objects(self):
        """FF10FE"""
        for o in self.objs:
            o.clear()

    # ------------------------------------------------------------------
    # niveau
    # ------------------------------------------------------------------
    def sys54(self):
        """0x872 : clr ff70..ffbf (registres VDP, manette, ff92, file son, caméra),
        ffc0 += 4, effacement VRAM (plans, sprites) et palette."""
        self.frame = 0
        self.pad = 0
        self.pad_edge = 0
        self.music_queue.clear()
        self.state_id = (self.state_id + 4) & 0xFFFF
        self.sprites = []
        self.palette = [0] * 64
        self.fade_level = 0x40
        self.clear_planes()
        self.camx = self.camy = 0

    def state_init_common(self):
        """FF00D4 : sys54 + clr D000..D7FF + objets + art titre."""
        self.sys54()
        self.cam_vx = self.cam_vy = 0
        self.trail = [(0, 0)] * 64
        self.trail_flags = [0] * 64
        # clr D000..D7FF (variables de jeu)
        self.bonus_mode = 0
        self.at_door = 0
        self.held_item = None
        self.door_y = self.door_x0 = self.door_x1 = 0
        self.score_add = 0
        self.time_min = self.time_sec = 0
        self.time_bonus_val = 0
        self.enemies_alive = 0
        self.player_hit = 0
        self.cat_jump_vx = self.cat_jump_vy = self.run_speed = 0
        self.following = 0
        self.freeze = 0
        self.lizard_speed = 0
        self.pal_counter = 0
        self.round_done = 0
        self.bonus_caught = self.bonus_caught_bcd = 0
        self.bonus_score = 0
        self.spawn_delay = self.cat_speed = 0
        self.zero_score = 0
        self.credit_line = self.credit_timer = self.ending_sub = 0
        self.play_sub = 0
        self.hitstop = self.jingle = 0
        self.demo = 0
        self.bonus_sub = 0
        self.door_anim_state = [0, 0, 0]
        self.clear_objects()
        self.text_base = 0x8000
        self.load_title_art()

    def clear_cmap(self):
        """FF13AC : 0xE0 longs = c800..cb7f (cb80..cbff n'est jamais effacé)"""
        for i in range(0x380):
            self.cmap[i] = 0

    def build_level(self):
        """FF2ABA"""
        self.chirps_left = 0
        self.select_tilesets()
        self.select_palettes()
        self.camx = set_hi(self.camx, 1)
        r = self.round
        while r > 0x30:
            r -= 0x30
        lvl = self.d.levels[(r - 1) & 0xFF]
        self.level = lvl
        self.load_level(lvl)                 # FF1422
        self.mark_specials(lvl)              # FF1608
        self.cat_jump_vx = lvl.cat_vx
        self.cat_jump_vy = lvl.cat_vy
        if self.restore_chirps:
            self.restore_chirps = 0
            self.restore_chirps_state()      # FF172C
        self.count_chirps()                  # FF2DE4
        self.draw_block(PLANE_B, self.door_tx, self.door_ty, self.d.door_block, 3, 3)   # FF1B60
        self.door_coords()                   # FF2D1A
        self.copy_spawn_positions()          # FF1700
        self.draw_labels()
        self.draw_score()
        self.draw_hiscore()
        self.draw_round()
        self.draw_lives()

    def load_level(self, lvl):
        """FF1422"""
        self.clear_cmap()
        for row in range(28):
            for col in range(32):
                if lvl.wallmap[row][col]:
                    self.cmap[row * 32 + col] = 1
        # FF148A
        self.door_tx, self.door_ty = lvl.door
        self.block_pos = [lvl.blocks[1][0][0], lvl.blocks[1][0][1], lvl.blocks[1][1][0], lvl.blocks[1][1][1],
                          lvl.blocks[2][0][0], lvl.blocks[2][0][1]]
        for t in range(6):
            for (tx, ty) in lvl.blocks[t]:
                self.draw_level_block(t, tx, ty)
        for i, (tx, ty) in enumerate(lvl.chicks):
            o = self.obj(ITEMS[i])
            o.routine = R_ITEM
            o.b3e, o.b3f = tx, ty
        slot = 0
        for (tx, ty) in lvl.cats:
            o = self.obj(0xC480 + 0x40 * slot)
            o.routine = R_CHIRP
            o.b3e, o.b3f = tx, ty
            o.b3a = 0
            slot += 1
        self.chirps_left = (self.chirps_left + len(lvl.cats)) & 0xFF
        for (tx, ty) in lvl.lizards:
            o = self.obj(0xC480 + 0x40 * slot)
            o.routine = R_CHIRP
            o.b3e, o.b3f = tx, ty
            o.b3a = 1
            slot += 1
        self.chirps_left = (self.chirps_left + len(lvl.lizards)) & 0xFF
        self.autotile()                      # FF19C0
        self.draw_borders()                  # FF194C / FF1976
        self.draw_door_sign()                # FF1B86
        self.mark_floor()                    # FF143A

    def draw_level_block(self, t: int, tx: int, ty: int):
        """FF1B16"""
        w, h = self.d.block_sizes[t]
        self.draw_block(PLANE_A, tx, ty, self.block_arts[t], w + 1, h + 1)

    def autotile(self):
        """FF19C0 : tuiles des murs / fond et masques de voisinage."""
        cm = self.cmap
        for i in range(0x300):
            p = 0x40 + i
            col = i & 0x1F
            row = p >> 5
            vram = PLANE_B + 0x80 + 2 * i
            if cm[p]:
                d4 = 0
                if cm[p - 0x20]:
                    d4 |= 1
                if cm[p + 0x20]:
                    d4 |= 2
                if col == 0:
                    if cm[p + 0x1F]:
                        d4 |= 4
                    if cm[p + 1]:
                        d4 |= 8
                elif col == 0x1F:
                    if cm[p - 1]:
                        d4 |= 4
                    if cm[p - 0x1F]:
                        d4 |= 8
                else:
                    if cm[p - 1]:
                        d4 |= 4
                    if cm[p + 1]:
                        d4 |= 8
                cm[p] = d4
                self.plane_write(vram, self.d.wall_tiles[d4])
            else:
                d4 = 0
                if col == 0:
                    if cm[p - 0x20]:
                        d4 |= 1
                    if cm[p - 1]:
                        d4 |= 2
                    if cm[p + 0x1F]:
                        d4 |= 4
                else:
                    if cm[p - 0x20]:
                        d4 |= 1
                    if cm[p - 0x21]:
                        d4 |= 2
                    if cm[p - 1]:
                        d4 |= 4
                self.plane_write(vram, self.floor_set[d4])
        # FF1A0C : rangée 2, cases vides -> tuile de type 3
        for col in range(32):
            if cm[0x40 + col] == 0:
                self.plane_write(PLANE_B + 0x80 + 2 * col, self.floor_set[3])

    def draw_borders(self):
        """FF194C (haut, E000) et FF1976 (bas, E680)"""
        for k in range(8):
            self.draw_block(PLANE_B, 4 * k, 0, self.top_set, 4, 2)
            self.draw_block(PLANE_B, 4 * k, 26, self.bottom_set, 4, 2)

    def draw_door_sign(self):
        """FF1B86"""
        art = self.d.door_sign_art_os if self.overseas else self.d.door_sign_art
        self.draw_block(PLANE_B, self.door_tx, (self.door_ty - 1) & 0xFF, art, 3, 1)

    def mark_floor(self):
        """FF143A"""
        cm = self.cmap
        for i in range(32):
            cm[i] = 0xC
        for i in range(0x340, 0x380):
            cm[i] = 0xC
        for i in range(32):
            if cm[0x40 + i]:
                cm[0x20 + i] = 3
                cm[i] = 0xE
        for i in range(32):
            if cm[0x320 + i]:
                cm[0x340 + i] = 0xD

    def mark_specials(self, lvl):
        """FF1608"""
        for (tx, ty) in lvl.special7:
            self.cmap[(tx + ty * 32) & 0x3FF] |= 0x80
        for (tx, ty) in lvl.special76:
            self.cmap[(tx + ty * 32) & 0x3FF] |= 0xC0
        for (tx, ty) in lvl.special5:
            self.cmap[(tx + ty * 32) & 0x3FF] |= 0x20

    def count_chirps(self):
        """FF2DE4"""
        n = 0
        for addr in CHIRPS:
            if self.obj(addr).routine:
                n += 1
        self.chirps_left = n

    def door_coords(self):
        """FF2D1A"""
        x, y = self.tile_to_px(self.door_tx, self.door_ty)
        self.door_x0 = x
        self.door_x1 = x + 0x17
        self.door_y = y + 0x18

    def copy_spawn_positions(self):
        """FF1700"""
        self.obj(PLAYER).b3e, self.obj(PLAYER).b3f = self.door_tx, self.door_ty
        b = self.block_pos
        for addr in (0xC380, 0xC680):
            self.obj(addr).b3e, self.obj(addr).b3f = b[0], b[1]
        for addr in (0xC3C0, 0xC6C0, 0xC400, 0xC700):
            self.obj(addr).b3e, self.obj(addr).b3f = b[2], b[3]

    def save_chirps(self):
        """FF1722 : C480..C67F -> DE00"""
        import copy
        self.saved_chirps = [copy.copy(self.obj(a)) for a in CHIRPS]

    def restore_chirps_state(self):
        """FF172C"""
        import copy
        for a, s in zip(CHIRPS, self.saved_chirps):
            o = self.obj(a)
            for k in Obj.__slots__:
                if k != "slot":
                    setattr(o, k, getattr(s, k))

    def spawn_enemies(self):
        """FF2D84"""
        o = self.obj
        if o(0xC380).routine == 0 and o(0xC680).routine == 0:
            e = o(0xC680)
            e.routine = R_SPAWNER
            e.init = False
        if o(0xC3C0).routine == 0 and o(0xC6C0).routine == 0 and o(0xC700).routine == 0:
            e = o(0xC6C0)
            e.routine = R_SPAWNER
            e.init = False
            e.b16 = 1
        if self.round >= 0xA and o(0xC400).routine == 0 and o(0xC700).routine == 0 and o(0xC6C0).routine == 0:
            e = o(0xC700)
            e.routine = R_SPAWNER
            e.init = False
            e.v3c = 4
            e.b16 = 2

    def set_round_params(self):
        """FF2E2E"""
        d1 = 0x136
        d2 = 0x14000
        n = min(self.round, 0x20)
        for _ in range(n + 1):
            d1 -= 5
            d2 += 0x200
        self.spawn_delay = d1 & 0xFFFF
        self.lizard_speed = d2
        self.cat_speed = 0x14000 if self.round <= 0x30 else 0x18000
        r = self.round
        while r > 0x30:
            r -= 0x30
        self.run_speed = self.d.levels[(r - 1) & 0xFF].lizard_vx

    def flash_text(self):
        """FF1740 : clignotement de la base de texte."""
        self.pal_counter = (self.pal_counter + 1) & 0xF
        self.text_base = (0x8100, 0x8000, 0xFFFF, 0x8000)[self.pal_counter >> 2]

    # ------------------------------------------------------------------
    # porte
    # ------------------------------------------------------------------
    def door_sign_anim(self):
        """FF1C3C : panneau au-dessus de la porte (FF137A)."""
        frames = self.d.door_sign_frames_os if self.overseas else self.d.door_sign_frames
        st = self.door_anim_state
        st[1] = (st[1] - 1) & 0xFF
        if st[1] & 0x80:
            st[1] = 4
            st[0] = (st[0] + 1) & 0xFF
        d0 = st[0]
        if d0 >= 4:
            st[0] = 0
            d0 = 0
            st[2] = 1
        art = self.d.door_sign_art_os if self.overseas else self.d.door_sign_art
        self.draw_block(PLANE_B, self.door_tx, (self.door_ty - 1) & 0xFF, frames[d0], 3, 1)

    def door_anim(self, frames: List[int], delay: int):
        """FF1D38 : animation 3x3 de la porte (plan A), bloquante."""
        self.freeze = 1
        st = [0, 0, 0]
        while True:
            # FF137A
            st[1] = (st[1] - 1) & 0xFF
            if st[1] & 0x80:
                st[1] = delay
                st[0] = (st[0] + 1) & 0xFF
            d0 = st[0]
            if d0 >= len(frames):
                st[0] = 0
                d0 = 0
                st[2] = 1
            self.draw_block(PLANE_A, self.door_tx, self.door_ty, frames[d0], 3, 3)
            if st[2]:
                break
            yield from self.run_objects()
            self.timer_tick()
            yield from self.vblank()
        self.freeze = 0

    # ------------------------------------------------------------------
    # affichages divers
    # ------------------------------------------------------------------
    def draw_round_clear_texts(self):
        """FF1E96 : GAME TIME / TIME BONUS ..."""
        if self.overseas:
            for a in (0xFF1F40, 0xFF1F4E, 0xFF1F56, 0xFF1F5E):
                self.draw_text_list(ram(a))
        else:
            for a in (0xFF1F04, 0xFF1F10, 0xFF1F1E):
                self.draw_text_list(ram(a))
        self.draw_text_list(ram(0xFF1F34 if self.time_min else 0xFF1F2C))

    def draw_round_clear_values(self):
        """FF1E52"""
        self.draw_bcd(self.time_min, 1, 0xC15C if self.overseas else 0xC160)
        self.draw_bcd(self.time_sec, 1, 0xC16C)
        if self.time_min == 0:
            self.draw_bcd(self.time_bonus_val, 4, 0xC260)

    def draw_bonus_count(self):
        """FF69D4 : marque les poussins attrapés."""
        for i in range(self.bonus_caught):
            self.plane_write(0xC14C + 2 * i, 0xE351)

    def bonus_final_score(self):
        """FF6988"""
        n = self.bonus_caught
        if n == 0:
            return
        for _ in range(n):
            self.score_add = 0x250
            self.bonus_score = bcd_add32(self.bonus_score, 0x250)
        self.score_add = self.bonus_score
        self.add_score()
        if n == 0x14:
            self.score_add = 0x10000
            self.add_score()

    def draw_bonus_result(self):
        """FF691C"""
        if self.bonus_caught:
            self.draw_text_list(ram(0xFF694C))
            if self.bonus_caught == 0x14:
                self.draw_text_list(ram(0xFF6964))
                self.draw_text_list(ram(0xFF6974))
        else:
            self.draw_text_list(ram(0xFF697C))

    def draw_bonus_values(self):
        """FF1F6C"""
        if self.bonus_caught == 0:
            return
        self.draw_bcd(self.bonus_caught_bcd, 1, 0xC248)
        self.draw_bcd(self.bonus_score & 0xFFFF, 2, 0xC266)     # d292/d293 : mot bas de d290
        if self.bonus_caught == 0x14:
            self.draw_bcd(0x00010000, 4, 0xC390)

    def check_extra_life(self):
        """FF2E90"""
        for i in range(5):
            if self.extra_bits & (1 << i):
                continue
            if self.score >= self.d.extra_life_thresholds[i]:
                self.extra_bits |= 1 << i
                self.jingle = 1
                self.sound_log.append((self.vint_count, "sfx", 0x97))
                self.lives = (self.lives + 1) & 0xFF
                self.draw_lives()
                return

    def hitstop_tick(self):
        """FF0D52"""
        if self.jingle:
            self.hitstop += 1
            if self.hitstop >= 0x1E:
                self.hitstop = 0
                self.jingle = 0

    def pause_loop(self):
        """FF2EF4"""
        self.sound_log.append((self.vint_count, "pause", 1))
        c0 = self.obj(0xC000)
        c0.routine = R_PAUSE
        c0.init = False
        while True:
            yield from self.run_object_c000()
            yield from self.vblank()
            if self.pad_edge & PAD_START:
                break
        self.sound_log.append((self.vint_count, "pause", 0))
        c0.routine = 0
        c0.init = False

    # ------------------------------------------------------------------
    # boucle principale et états (FF006C)
    # ------------------------------------------------------------------
    def main_loop(self):
        while True:
            st = (self.state_id & 0x7C) >> 2
            yield from STATES[st](self)
            self.frame = (self.frame + 1) & 0xFFFF

    # --- état 16/17 : écran SEGA (0x46E / 0x4DC) ---
    def st_sega(self):
        self.sys54()
        self.state_id = 0x44
        self.frame = 0
        self.clear_planes()
        self.palette = [0] * 64
        self.draw_text(0xC38C, "SEGA")
        self.palette[2] = 0xEEE
        # 0x480 : boucle de 4 frames par pas de palette, sortie quand d2 > 0x28 -> 88 frames
        for _ in range(88):
            yield from self.vblank()

    def st_sega_wait(self):
        if (self.pad_edge & PAD_START) or self.frame >= 0x78:
            self.state_id = 0
        yield from self.vblank()

    # --- état 0/1 : titre ---
    def st_title_init(self):
        """FF1FB0"""
        self.state_init_common()
        self.load_tiles(0x740, self.rom.nemesis(0x19EEE))
        self.font_color = 0
        self.load_fonts()
        self.load_palette_list(0x16DE8)
        for i in range(8):
            self.palette[48 + i] = self.d.title_palette[i]
        base = ram(0xFF209E if self.overseas else 0xFF2086)
        for i in range(6):
            self.draw_text_list(self.rom.u32(base + 4 * i))
        self.lives = 3
        self.round_bcd = 1
        self.round = 1
        self.no_bonus = 1
        for i in range(4):
            o = self.obj(0xC000 + 0x40 * i)
            o.routine = R_TITLE_CAST
            o.w38 = i
        self.obj(0xC100).routine = R_PUSH_START
        for i in range(6):
            o = self.obj(0xC140 + 0x40 * i)
            o.routine = R_TITLE_LETTER
            o.w38 = i
        if self.overseas:
            self.draw_bigtext_list(ram(0xFF211C))
        self.draw_block(PLANE_A, 0x24, 1, self.d.label_1up, 2, 1)
        self.draw_block(PLANE_A, 0x32, 1, self.d.label_hi, 3, 1)
        self.draw_score()
        self.draw_hiscore()
        yield from self.run_objects()
        self.frame = 0
        self.music(0x85)
        yield from self.vblank()
        yield from self.vblank()

    def st_title(self):
        """FF2122"""
        if self.pad_edge & PAD_START:
            yield from self.fade_out()
            self.sfx(0xE0)
            self.font_color = 1
            self.load_fonts()
            self.state_id = 0x08
        elif self.frame >= 0x400:
            yield from self.fade_out()
            self.sfx(0xE0)
            self.font_color = 1
            self.load_fonts()
            self.state_id = 0x38
        yield from self.run_objects()
        yield from self.vblank()

    # --- état 2/3 : instructions ---
    def st_instr_init(self):
        """FF228E"""
        for _ in range(8):
            yield from self.vblank()
        self.state_init_common()
        self.load_palette_list(0x16DE8)
        self.score = 0
        self.extra_bits = 0
        self.select_tilesets()
        self.select_palettes()
        # FF230A
        base = ram(0xFF23F0 if self.overseas else 0xFF2384)
        for i in range(6):
            self.draw_bigtext_list(self.rom.u32(base + 4 * i))
        self.door_tx, self.door_ty = (0xF if self.overseas else 0xE), 6
        self.draw_level_block(0, self.door_tx, self.door_ty)
        self.draw_door_sign()
        self.door_tx, self.door_ty = 5, 0x17
        self.draw_level_block(0, 5, 0x17)
        self.draw_door_sign()
        self.draw_borders()
        for i in range(0x16):
            self.plane_write(0xC48A + 2 * i, 0x220D)
        for i in range(0x14):
            o = self.obj(0xC000 + 0x40 * i)
            o.routine = R_INSTR
            o.w38 = i
        yield from self.run_objects()
        yield from self.vblank()
        yield from self.vblank()

    def st_instr(self):
        """FF22E0"""
        if self.pad_edge & PAD_START:
            self.state_id = 0x18
            if (self.pad & 0x7F) == 0x61:
                self.state_id = 0x10
            yield from self.fade_out()
        yield from self.vblank()

    # --- état 4/5 : sélection du round ---
    def st_select_init(self):
        """FF25BE"""
        self.state_init_common()
        self.load_palette_list(0x16DE8)
        self.draw_text_list(ram(0xFF25E8))
        self.lives = 3
        self.zero_score = 1
        yield from self.vblank()
        yield from self.vblank()

    def st_select(self):
        """FF25F2"""
        d1 = self.round_bcd
        e = self.pad_edge
        if e & PAD_UP:
            if d1 != 0x36:
                d1 = bcd_add8(d1, 1)
                self.round = (self.round + 1) & 0xFF
                self.round_bcd = d1
        elif e & PAD_DOWN:
            if d1 != 1:
                d1 = bcd_sub8(d1, 1)
                self.round = (self.round - 1) & 0xFF
                self.round_bcd = d1
        elif e & PAD_START:
            self.state_id = 0x18
        self.draw_bcd(self.round_bcd, 1, 0xC360)
        yield from self.vblank()

    # --- état 6/7 : début de partie ---
    def st_game_init(self):
        """FF2656"""
        self.state_init_common()
        self.load_palette_list(0x16DE8)
        self.t_min = self.t_sec = self.t_frame = 0
        self.reached = 0
        return          # rts direct : aucune attente de V-int
        yield           # (garde la fonction générateur)

    def st_round_or_bonus(self):
        """FF266E"""
        self.state_id = 0x20
        if (self.round & 3) == 3:
            self.state_id = 0x28
        yield from self.vblank()

    # --- état 8/9 : round ---
    def st_round_init(self):
        """FF2A94"""
        self.state_init_common()
        self.load_palette_list(0x16DE8)
        self.build_level()
        self.music(0x83)
        yield from self.round_intro()        # FF2E00
        self.set_round_params()              # FF2E2E
        yield from self.vblank()

    def round_intro(self):
        """FF2E00"""
        yield from self.run_objects()
        yield from self.vblank()
        for _ in range(0x3D):
            self.timer_tick()
            yield from self.vblank()
        yield from self.door_anim(self.d.door_open_start, 0xF)     # FF1CAA
        self.timer_tick()
        p = self.obj(PLAYER)
        p.routine = R_PLAYER
        p.init = False
        yield from self.run_objects()
        yield from self.vblank()
        yield from self.door_anim(self.d.door_close_start, 2)      # FF1CCA

    def st_round(self):
        """FF2B46"""
        sub = self.play_sub & 0x7C
        if sub == 0:
            yield from self.play_normal()
        elif sub == 4:
            yield from self.play_clear()
        elif sub == 8:
            yield from self.play_bonus_award()
        elif sub == 0xC:
            self.play_time_check()
        else:
            yield from self.play_game_over()
        if self.pad_edge & PAD_START:
            yield from self.pause_loop()
        self.check_extra_life()
        self.hitstop_tick()
        yield from self.vblank()

    def play_normal(self):
        """FF2B7E"""
        if self.cat_speed <= 0x1C000:
            self.cat_speed = s32(self.cat_speed + 7)
        self.spawn_enemies()
        yield from self.run_objects()
        self.timer_tick()

    def play_clear(self):
        """FF2B9A"""
        if not (self.play_sub & 0x8000):
            self.play_sub |= 0x8000
            while self.jingle:
                self.hitstop_tick()
                yield from self.vblank()
            self.music(0x82)
            self.text_base = 0x8000
            self.draw_round_clear_texts()
            self.frame = 0
            self.obj(0xC040).v3c = 4
        yield from self.run_objects()
        # FF2D42
        if self.frame <= 0xFA:
            self.flash_text()
            self.draw_round_clear_values()
            return
        self.next_round()

    def next_round(self):
        """FF2D56"""
        self.round = (self.round + 1) & 0xFF
        if self.round == 0:
            self.round = 1
        self.round_bcd = bcd_add8(self.round_bcd, 1)
        self.state_id = 0x18
        if self.round_bcd == 0x49:
            self.state_id = 0x30

    def play_bonus_award(self):
        """FF2BDC"""
        if not (self.play_sub & 0x8000):
            self.play_sub |= 0x8000
            self.frame = 0
            r = self.round
            while r > 0x30:
                r -= 0x30
            d1 = r & 0xFF                  # FF2BEE : numéro de round (1..48), pas l'index de niveau
            d0 = (self.round + 5) & 0xFF
            while d0 >= 0x30:
                d0 -= 0x30
            grp = d0 >> 3
            if self.d.special_levels[grp] != d1:      # FF2C04 -> FF2C74
                self.play_sub = 4
                return
            if self.no_bonus:                          # FF2C70 : clr d88f
                self.no_bonus = 0
                self.play_sub = 4
                return
            self.score_add = self.d.special_bonus[grp]
            for _ in range(0xB):
                yield from self.vblank()
            o = self.obj(0xC040)
            o.routine = R_FLAG
            o.init = False
            self.music(0xE1)
        # FF2C2E
        if self.frame == 8:
            self.frame = 0
            self.text_base = 0x8000
            self.add_score()
            self.sfx(0x98)
            self.bonus_count = (self.bonus_count + 1) & 0xFF
            if self.bonus_count == 0xA:
                self.bonus_count = 0
                self.reached = 0
                self.play_sub = 4
                return
        yield from self.run_objects()

    def play_time_check(self):
        """FF2C9A"""
        d0 = (self.round + 5) & 0xFF
        while d0 >= 0x30:
            d0 -= 0x30
        grp = d0 >> 3
        if self.timer_word() > self.d.time_thresholds[grp] or self.reached != 1:
            self.no_bonus = 1
        self.play_sub = 8

    def play_game_over(self):
        """FF2CDA"""
        if not (self.play_sub & 0x8000):
            self.play_sub |= 0x8000
            for _ in range(0x1F):
                yield from self.vblank()
            self.music(0x84)
            o = self.obj(0xC000)
            o.routine = R_GAMEOVER
            o.init = False
            self.restore_chirps = 0
        yield from self.run_object_c000()
        for _ in range(0xB5):
            yield from self.vblank()
        yield from self.fade_out()
        self.state_id = 0x40

    # --- état 10/11 : stage bonus ---
    def st_bonus_init(self):
        """FF2F30"""
        self.state_init_common()
        self.load_palette_list(0x16DE8)
        self.palette[0x27] = 0x2C
        self.clear_cmap()
        self.select_tilesets()
        self.select_palettes()
        self.bonus_mode = 1
        self.chirps_left = 0x14
        self.draw_borders()
        for i in range(32):
            self.cmap[0x2A0 + i] = 1
            self.plane_write(0xE540 + 2 * i, 0x220D)
        self.draw_text_list(ram(0xFF2FCC))
        self.draw_text_list(ram(0xFF2FD4))
        # FF303C
        p = self.obj(0xC580)
        p.routine = R_PLAYER
        p.w3e = 0x0D11
        self.obj(0xC040).routine = R_NET
        self.obj(0xC640).routine = R_BCAT_L
        self.obj(0xC680).routine = R_BCAT_L
        self.obj(0xC680).b16 = 1
        self.obj(0xC5C0).routine = R_BCAT_R
        self.obj(0xC600).routine = R_BCAT_R
        self.obj(0xC600).b16 = 1
        for i in range(0x14):
            o = self.obj(0xC080 + 0x40 * i)
            o.routine = R_BCHIRP
            o.b38 = i
            if i & 4:
                o.b39 = 1
        k = self.round % 48
        k = ((k - 3) & 0xFF) >> 2
        self.bonus_delays_ptr = self.d.bonus_delays[k]
        self.bonus_launch_ptr = self.d.bonus_launch[k]
        self.bonus_script_ptr = self.d.bonus_script_idx[k]
        self.draw_labels()
        self.draw_score()
        self.draw_hiscore()
        self.draw_round()
        self.draw_lives()
        self.music(0x81)
        yield from self.vblank()
        yield from self.vblank()

    def st_bonus(self):
        """FF2FDC"""
        sub = self.bonus_sub & 0x7C
        if sub == 0:
            yield from self.run_objects()
        else:
            if not (self.bonus_sub & 0x8000):
                self.bonus_sub |= 0x8000
                while self.jingle:
                    self.hitstop_tick()
                    yield from self.vblank()
                self.music(0x82)
                self.draw_bonus_result()
            yield from self.run_objects()
            # FF30D4
            self.freeze = 1
            if self.frame <= 0xFA:
                self.flash_text()
                self.draw_bonus_values()
            else:
                self.round = (self.round + 1) & 0xFF
                if self.round == 0:
                    self.round = 1
                self.round_bcd = bcd_add8(self.round_bcd, 1)
                self.state_id = 0x18
        if self.pad_edge & PAD_START:
            yield from self.pause_loop()
        self.check_extra_life()
        self.hitstop_tick()
        yield from self.vblank()

    # --- état 12/13 : fin ---
    def st_ending_init(self):
        """FF3110"""
        self.state_init_common()
        self.font_color = 0
        self.load_fonts()
        self.load_palette_list(0x16DE8)
        self.palette[0] = 0x800
        # FF3566 : 10 blocs de décor
        r = self.rom
        for i in range(10):
            vram = r.u16(ram(0xFF35D4) + 2 * i)
            art = r.word_ptr(ram(0xFF3598), i)
            w = r.u16(ram(0xFF35AC) + 4 * i) + 1
            h = r.u16(ram(0xFF35AE) + 4 * i) + 1
            base = PLANE_B if vram >= 0xE000 else PLANE_A
            tx, ty = ((vram - base) & 0x3F) >> 1, (vram - base) >> 6
            self.draw_block(base, tx, ty, art, w, h)
        self.music(0x81)
        self.frame = 0
        yield from self.vblank()
        yield from self.vblank()

    def st_ending(self):
        """FF3162"""
        sub = self.ending_sub & 0x7C
        if sub == 0:
            self.flash_text()
            self.draw_text_list(ram(0xFF31EC))
            self.draw_text_list(ram(0xFF3200))
            if self.frame == 0xC8:
                self.ending_sub = 4
                self.text_base = 0x8100
                self.palette[3] = 0xEEE
                self.draw_text_list(ram(0xFF31EC))
                self.draw_text_list(ram(0xFF3200))
                yield from self.fade_out()
                for row in self.plane_a:
                    for i in range(32):
                        row[i] = 0
        elif sub == 4:
            if not (self.ending_sub & 0x8000):
                self.ending_sub |= 0x8000
                self.load_palette_list(0x16DE8)
                self.palette[3] = 0xEEE
                self.cam_vy = 0x4000
                for i in range(5):
                    o = self.obj(0xC000 + 0x40 * i)
                    o.routine = R_ENDING
                    o.w38 = i
            self.camera_step()
            self.credit_timer = (self.credit_timer + 1) & 0xFF
            if self.credit_timer == 0x20:
                self.credit_timer = 0
                self.draw_credit_line()
                self.credit_line = (self.credit_line + 1) & 0xFF
                if self.credit_line == 0x5D:
                    self.ending_sub = 8
                    self.obj(0xC000).routine = R_PUSH_START
                    self.obj(0xC000).init = False
        else:
            if self.pad_edge & PAD_START:
                yield from self.fade_out()
                self.font_color = 1
                self.load_fonts()
                self.state_id = 0x18
        yield from self.run_objects()
        yield from self.vblank()

    def draw_credit_line(self):
        """FF328E"""
        d0 = ((hi(self.camy) & 0xFF) >> 3) - 2
        if d0 < 0:
            d0 += 0x20
        row = d0 & 0x1F
        # 32 mots effacés à partir de la colonne 4 (déborde sur les 4 premières colonnes de la ligne suivante)
        for i in range(32):
            cell = 4 + i
            self.plane_a[(row + (cell >> 5)) & 0x1F][cell & 0x1F] = 0
        text = self.d.credits[self.credit_line]
        r = self.rom
        vram = PLANE_A + (row << 6) + 8
        a = text
        while True:
            c = r.u8(a)
            a += 1
            if c == 0:
                break
            self.draw_tile(vram, c)
            vram += 2

    # --- état 14/15 : démo ---
    def st_demo_init(self):
        """FF39A2"""
        self.state_init_common()
        self.load_palette_list(0x16DE8)
        i = self.demo_idx & 3
        self.round = self.d.demo_rounds[i]
        self.round_bcd = self.d.demo_rounds_bcd[i]
        self.demo_ptr = self.d.demo_scripts[i]
        self.demo_pad = self.rom.u8(self.demo_ptr)
        self.demo_left = self.rom.u8(self.demo_ptr + 1)
        self.demo_idx = (self.demo_idx + 1) & 0xFFFF
        self.build_level()
        self.t_min = self.t_sec = self.t_frame = 0
        self.reached = 0
        self.demo = 1
        self.obj(0xC000).routine = R_PUSH_START
        yield from self.round_intro()
        self.set_round_params()
        yield from self.vblank()

    def st_demo(self):
        """FF3A18"""
        if self.pad_edge & PAD_START:
            yield from self.fade_out()
            self.state_id = 0
        # FF3A5E
        self.pad = self.rom.u8(self.demo_ptr)
        self.demo_left = (self.demo_left - 1) & 0xFF
        if self.demo_left == 0:
            self.demo_ptr += 2
            self.demo_pad = self.rom.u8(self.demo_ptr)
            self.demo_left = self.rom.u8(self.demo_ptr + 1)
        if self.cat_speed <= 0x1C000:
            self.cat_speed = s32(self.cat_speed + 7)
        self.spawn_enemies()
        yield from self.run_objects()
        self.timer_tick()
        if self.restore_chirps & 1:
            self.restore_chirps &= ~1
            yield from self.fade_out()
            self.state_id = 0x40
        yield from self.vblank()


def bcd_sub8(a: int, b: int) -> int:
    lo = (a & 0xF) - (b & 0xF)
    h = (a >> 4) - (b >> 4)
    if lo < 0:
        lo += 10
        h -= 1
    if h < 0:
        h += 10
    return ((h & 0xF) << 4) | lo


STATES: Dict[int, Callable] = {
    0: Game.st_title_init, 1: Game.st_title, 2: Game.st_instr_init, 3: Game.st_instr,
    4: Game.st_select_init, 5: Game.st_select, 6: Game.st_game_init, 7: Game.st_round_or_bonus,
    8: Game.st_round_init, 9: Game.st_round, 10: Game.st_bonus_init, 11: Game.st_bonus,
    12: Game.st_ending_init, 13: Game.st_ending, 14: Game.st_demo_init, 15: Game.st_demo,
    16: Game.st_sega, 17: Game.st_sega_wait,
}
