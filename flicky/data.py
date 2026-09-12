"""Tables de données lues dans la ROM (adresses ROM 0x1xxxx du segment jeu).

Les adresses sont celles du désassemblage (disasm/flicky.asm) ; les données
elles-mêmes restent dans la ROM et sont lues à l'exécution.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

from .rom import Rom, Anim, Frame, read_anim, read_anim_table, read_frame, read_level, Level


def ram(addr: int) -> int:
    """Adresse FFxxxx -> offset ROM."""
    return addr - 0xFF0000 + 0x10000


class Data:
    """Toutes les tables constantes du jeu, extraites de la ROM."""

    def __init__(self, rom: Rom):
        self.rom = rom
        r = rom
        # --- tables d'animations (champ +8 de l'objet) ---
        self.anim_player = read_anim_table(r, 0x144AC, 4)      # FF44AC : marche, saut, saut avant, mort
        self.anim_chirp = read_anim_table(r, 0x14E12, 4)       # FF4E12
        self.anim_chirp2 = read_anim_table(r, 0x14E22, 4)      # FF4E22 (lunettes)
        self.anim_cat = read_anim_table(r, 0x154AE, 5)         # FF54AE
        self.anim_lizard = read_anim_table(r, 0x162BC, 8)      # FF62BC
        self.anim_item = read_anim_table(r, 0x14730, 15)       # FF4730 : 15 objets lançables
        self.anim_flag = read_anim_table(r, 0x14524, 1)        # FF4524 : objet FF44DC
        self.anim_puff = read_anim_table(r, 0x163E0, 1)        # FF63E0 : apparition ennemi
        self.anim_bonus_item = read_anim_table(r, 0x165AC, 1)  # FF65AC
        self.anim_bonus_cat = read_anim_table(r, 0x1669A, 2)   # FF669A
        self.anim_tables: Dict[int, List[Anim]] = {
            0x144AC: self.anim_player, 0x14E12: self.anim_chirp, 0x14E22: self.anim_chirp2,
            0x154AE: self.anim_cat, 0x162BC: self.anim_lizard, 0x14730: self.anim_item,
            0x14524: self.anim_flag, 0x163E0: self.anim_puff, 0x165AC: self.anim_bonus_item,
            0x1669A: self.anim_bonus_cat,
        }
        # --- boîtes de collision (FF1878) : 8 octets par id (x0,w,y0,h en mots) ---
        self.hitboxes: List[Tuple[int, int, int, int]] = []
        for i in range(19):
            a = ram(0xFF1878) + 8 * i
            self.hitboxes.append((r.s16(a), r.s16(a + 2), r.s16(a + 4), r.s16(a + 6)))
        # --- niveaux ---
        self.levels: List[Level] = [read_level(r, i) for i in range(48)]
        # --- tables de tuiles de décor (FF268E / FF2824) ---
        self.wall_tiles = [r.u16(ram(0xFF191C) + 2 * i) for i in range(16)]
        self.floor_sets = [[r.u16(r.u32(ram(0xFF2740) + 4 * k) + 2 * i) for i in range(8)] for k in range(6)]
        self.top_sets = [r.u32(ram(0xFF2758) + 4 * k) for k in range(6)]     # d808 : 8 blocs 4x2 (haut)
        self.bottom_sets = [r.u32(ram(0xFF2770) + 4 * k) for k in range(6)]  # d80c : 8 blocs 4x2 (bas)
        self.block3_sets = [r.u32(ram(0xFF2788) + 4 * k) for k in range(8)]  # d810 : bloc type 3 (2x3)
        self.block4_sets = [r.u32(ram(0xFF27B8) + 4 * k) for k in range(6)]  # d814 : type 4 (5x3)
        self.block5_sets = [r.u32(ram(0xFF27D0) + 4 * k) for k in range(6)]  # d818 : type 5 (4x4)
        self.item_frames = [r.u32(ram(0xFF27E8) + 4 * k) for k in range(15)]  # d828 : mapping objet lançable
        self.block0_art = 0x1A274   # d81c : porte 3x3
        self.block1_art = 0x1A292   # d820 : 2x2
        self.block2_art = 0x1A286   # d824 : 2x3
        self.block_sizes = [(2, 2), (1, 1), (1, 2), (1, 2), (4, 2), (3, 3)]   # FF1B3C (w-1, h-1)
        # palettes de niveau (FF2866 : 12 x 16 couleurs ; FF29FE : 16 x 4 couleurs)
        self.level_palettes = [[r.u16(r.word_ptr(ram(0xFF2866), k) + 2 * i) for i in range(16)] for k in range(12)]
        self.item_palettes = [[r.u16(r.word_ptr(ram(0xFF29FE), k) + 2 * i) for i in range(4)] for k in range(16)]
        # --- scores ---
        self.chirp_door_scores = [r.u32(ram(0xFF4AC0) + 4 * i) for i in range(8)]     # BCD
        self.item_hit_scores = [r.u32(ram(0xFF549E) + 4 * i) for i in range(4)]       # BCD chat
        self.item_hit_scores_liz = [r.u32(ram(0xFF62AC) + 4 * i) for i in range(4)]   # BCD lézard
        self.time_bonus = [r.u32(ram(0xFF4DFA) + 4 * i) for i in range(6)]            # BCD
        self.bonus_item_scores = [r.u32(ram(0xFF6588) + 4 * i) for i in range(9)]     # BCD
        self.extra_life_thresholds = [r.u32(ram(0xFF2EE0) + 4 * i) for i in range(5)]  # BCD
        self.special_levels = [r.u8(ram(0xFF2C7C) + i) for i in range(6)]
        self.special_bonus = [r.u32(ram(0xFF2C82) + 4 * i) for i in range(6)]
        self.time_thresholds = [r.u16(ram(0xFF2CCE) + 2 * i) for i in range(6)]
        # vitesses poussins dispersés
        self.scatter_speed0 = [r.s32(ram(0xFF4C4A) + 4 * i) for i in range(8)]
        self.scatter_speed1 = [r.s32(ram(0xFF4D32) + 4 * i) for i in range(8)]
        # offsets de la traînée du joueur (FF4A58 / FF4A6A) exprimés en index d'enregistrement
        self.trail_pos_idx = [(r.u16(ram(0xFF4A58) + 2 * i) - 0xD00E) // 8 for i in range(9)]
        self.trail_flag_idx = [r.u16(ram(0xFF4A6A) + 2 * i) - 0xD20E for i in range(9)]
        # --- mappings directs ---
        self.frame_cache: Dict[int, Frame] = {}
        # popups
        self.popup_combo = [r.word_ptr(ram(0xFF6450), i) for i in range(3)]
        self.popup_door = [r.word_ptr(ram(0xFF649E), i) for i in range(8)]
        self.popup_bonus = [r.word_ptr(ram(0xFF64DA), i) for i in range(9)]
        # --- stage bonus ---
        self.bonus_delays = [r.u32(ram(0xFF69F4) + 4 * k) for k in range(12)]
        self.bonus_launch = [r.u32(ram(0xFF6A9C) + 4 * k) for k in range(12)]
        self.bonus_script_idx = [r.u32(ram(0xFF6C34) + 4 * k) for k in range(12)]
        self.bonus_scripts = [r.u32(ram(0xFF6D18) + 4 * k) for k in range(9)]
        # --- démo ---
        self.demo_rounds = [r.u8(ram(0xFF3A08) + i) for i in range(4)]
        self.demo_rounds_bcd = [r.u8(ram(0xFF3A0C) + i) for i in range(4)]
        self.demo_scripts = [r.u16(ram(0xFF3A10) + 2 * i) | 0x10000 for i in range(4)]
        # --- titre / textes ---
        self.title_anim_tables = [r.u32(ram(0xFF21A4) + 4 * i) for i in range(4)]
        self.title_anim_ids = [r.u16(ram(0xFF21B4) + 2 * i) for i in range(4)]
        self.title_pos = [(r.u16(ram(0xFF21BC) + 4 * i), r.u16(ram(0xFF21BE) + 4 * i)) for i in range(4)]
        self.title_letters = [(r.u32(ram(0xFF225E) + 4 * i), r.u16(ram(0xFF2276) + 4 * i), r.u16(ram(0xFF2278) + 4 * i)) for i in range(6)]
        self.instr_flip = [r.u8(ram(0xFF24BA) + i) for i in range(20)]
        self.instr_frames = [r.u32(ram(0xFF24CE) + 4 * i) for i in range(20)]
        self.instr_pos = [(r.u16(ram(0xFF256E) + 4 * i), r.u16(ram(0xFF2570) + 4 * i)) for i in range(20)]
        self.ending_anims = [r.u32(ram(0xFF34F8) + 4 * i) for i in range(5)]
        self.ending_anim_ids = [r.u16(ram(0xFF350C) + 2 * i) for i in range(5)]
        self.ending_thresholds = [r.u8(ram(0xFF3516) + i) for i in range(5)]
        self.credits = [r.word_ptr(ram(0xFF32E0), i) for i in range(0x5E)]
        self.title_palette = [r.u16(ram(0xFF210C) + 2 * i) for i in range(8)]
        # porte
        self.door_open_start = [0x1A490, 0x1A46C, 0x1A47E, 0x1A490]              # FF1CB8 (delay 15)
        self.door_close_start = [0x1A274, 0x1A490, 0x1A47E, 0x1A46C]             # FF1CD4 (delay 2)
        self.door_open_enter = [ram(0xFF1D06), 0x1A46C, 0x1A47E, 0x1A490, 0x1A4A2]  # FF1CF0 (delay 2)
        self.door_close_enter = [0x1A274, 0x1A4A2, 0x1A490, 0x1A47E, 0x1A46C]    # FF1D22 (delay 1)
        self.door_sign_frames = [0x1A262, 0x1A26E, 0x1A268, 0x1A26E]             # FF1C74 (JP) ; overseas FF1C86
        self.door_sign_frames_os = [0x11C98, 0x11CA4, 0x11C9E, 0x11CA4]
        self.door_block = 0x1A4B4                                                # FF1B60 (3x3)
        self.door_sign_art = 0x1A262                                             # FF1B86 (3x1) ; overseas 0x11C98
        self.door_sign_art_os = 0x11C98
        self.label_1up = 0x1A4CA   # FF1E1C : 2 tuiles à C048
        self.label_hi = 0x1A4D2    # 3 tuiles à C064

    def frame(self, addr: int) -> Frame:
        f = self.frame_cache.get(addr)
        if f is None:
            f = read_frame(self.rom, addr)
            self.frame_cache[addr] = f
        return f

    def anim_table(self, addr: int) -> List[Anim]:
        t = self.anim_tables.get(addr)
        if t is None:
            # table inconnue : lire paresseusement 8 entrées
            t = read_anim_table(self.rom, addr, 8)
            self.anim_tables[addr] = t
        return t
