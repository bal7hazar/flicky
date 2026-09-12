"""Lecture de la ROM Flicky : décompression Nemesis, palettes, font, mappings
de sprites, animations et données de niveaux.

Toutes les adresses sont des offsets ROM. Les données du segment jeu sont
référencées dans le code original par des adresses ROM 0x1xxxx (le segment est
copié en RAM 0xFF0000 mais les tables de données sont lues en place).
"""
from __future__ import annotations

import glob
import os
import struct
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple

ROM_SIZE = 0x20000


def find_rom(path: str | None = None) -> str:
    """Localise la ROM : argument, variable FLICKY_ROM, ou Flicky*.md à la racine."""
    candidates = []
    if path:
        candidates.append(path)
    if os.environ.get("FLICKY_ROM"):
        candidates.append(os.environ["FLICKY_ROM"])
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for d in (here, os.getcwd(), os.path.dirname(here)):
        candidates += sorted(glob.glob(os.path.join(d, "Flicky*.md")))
        candidates += sorted(glob.glob(os.path.join(d, "Flicky*.bin")))
    for c in candidates:
        if c and os.path.isfile(c):
            return c
    raise FileNotFoundError(
        "ROM Flicky introuvable : placez 'Flicky (USA, Europe).md' à la racine du "
        "dépôt ou définissez FLICKY_ROM.")


class Rom:
    def __init__(self, path: str | None = None):
        self.path = find_rom(path)
        with open(self.path, "rb") as f:
            self.data = f.read()
        if self.data[0x100:0x104] != b"SEGA" or b"FLICKY" not in self.data[0x120:0x130]:
            raise ValueError("Ce fichier n'est pas la ROM Mega Drive de Flicky")

    # accès bruts -------------------------------------------------------
    def u8(self, a: int) -> int:
        return self.data[a]

    def s8(self, a: int) -> int:
        v = self.data[a]
        return v - 0x100 if v & 0x80 else v

    def u16(self, a: int) -> int:
        return struct.unpack_from(">H", self.data, a)[0]

    def s16(self, a: int) -> int:
        return struct.unpack_from(">h", self.data, a)[0]

    def u32(self, a: int) -> int:
        return struct.unpack_from(">I", self.data, a)[0]

    def s32(self, a: int) -> int:
        return struct.unpack_from(">i", self.data, a)[0]

    def ram_ptr(self, a: int) -> int:
        """Adresse RAM 0xFFxxxx du segment jeu -> offset ROM (0x1xxxx)."""
        if 0xFF0000 <= a < 0xFFC000:
            return a - 0xFF0000 + 0x10000
        return a

    def word_ptr(self, table: int, index: int) -> int:
        """Table de mots 'adresse basse' (moveq #-1,d1 ; move.w (a0,d0),d1)."""
        return 0x10000 | self.u16(table + 2 * index)

    # ------------------------------------------------------------------
    def nemesis(self, addr: int) -> bytes:
        """Décompresse un bloc Nemesis (routine ROM 0xAD4). Retourne les tiles
        4bpp (32 octets par tile)."""
        return nemesis_decode(self.data, addr)

    def palette_list(self, addr: int) -> List[int]:
        """Liste de palettes (routine 0x1196) : mots (index, couleur) jusqu'au
        mot dont le bit 0 est levé. Retourne 64 couleurs 9 bits (format VDP)."""
        pal = [0] * 64
        a = addr
        while True:
            w = self.u16(a)
            a += 2
            idx = (w & 0x10) | (((w << 4) | (w >> 12)) & 0xF) | ((w & 0x100) >> 3)
            pal[idx] = w & 0xEEE
            if w & 1:
                break
        return pal


# ---------------------------------------------------------------------------
# Nemesis
# ---------------------------------------------------------------------------
def nemesis_decode(rom: bytes, addr: int) -> bytes:
    pos = addr
    header = struct.unpack_from(">H", rom, pos)[0]
    pos += 2
    xor_mode = bool(header & 0x8000)
    n_longs = (header & 0x7FFF) * 8

    # table des codes : indexée par les 8 prochains bits du flux
    table: Dict[int, Tuple[int, int, int]] = {}  # prefix -> (len, repeat, nibble)
    nibble = 0
    while True:
        b = rom[pos]
        pos += 1
        if b == 0xFF:
            break
        if b & 0x80:
            nibble = b & 0xF
            continue
        repeat = (b >> 4) & 7
        length = b & 0xF
        code = rom[pos]
        pos += 1
        if length == 8:
            table[code] = (8, repeat, nibble)
        else:
            base = code << (8 - length)
            for k in range(1 << (8 - length)):
                table[base + k] = (length, repeat, nibble)

    out = bytearray()
    bitbuf = 0
    bitcnt = 0
    prev = 0
    cur = 0
    ncur = 0
    remaining = n_longs

    def need(n: int):
        nonlocal bitbuf, bitcnt, pos
        while bitcnt < n:
            bitbuf = (bitbuf << 8) | (rom[pos] if pos < len(rom) else 0)
            pos += 1
            bitcnt += 8

    while remaining > 0:
        need(8)
        peek = (bitbuf >> (bitcnt - 8)) & 0xFF
        if peek >= 0xFC:
            # code inline : 6 bits de préfixe puis 3 bits repeat + 4 bits nibble
            bitcnt -= 6
            need(7)
            v = (bitbuf >> (bitcnt - 7)) & 0x7F
            bitcnt -= 7
            repeat, nib = v >> 4, v & 0xF
        else:
            length, repeat, nib = table[peek]
            bitcnt -= length
        bitbuf &= (1 << bitcnt) - 1 if bitcnt else 0
        for _ in range(repeat + 1):
            cur = ((cur << 4) | nib) & 0xFFFFFFFF
            ncur += 1
            if ncur == 8:
                if xor_mode:
                    prev ^= cur
                    out += struct.pack(">I", prev)
                else:
                    out += struct.pack(">I", cur)
                cur = 0
                ncur = 0
                remaining -= 1
                if remaining == 0:
                    break
    return bytes(out)


def tile_pixels(tiles: bytes, index: int) -> List[List[int]]:
    """Tile 8x8 4bpp -> matrice de 8 lignes de 8 indices de couleur."""
    base = index * 32
    rows = []
    for y in range(8):
        row = []
        for x in range(4):
            b = tiles[base + y * 4 + x]
            row.append(b >> 4)
            row.append(b & 0xF)
        rows.append(row)
    return rows


def font_tiles(rom: Rom, addr: int, count: int, fg: int, bg: int) -> bytes:
    """Font 1 bpp (8 octets/caractère) -> tiles 4bpp (routine 0xCC0)."""
    out = bytearray()
    for i in range(count):
        for y in range(8):
            b = rom.u8(addr + i * 8 + y)
            v = 0
            for bit in range(7, -1, -1):
                v = (v << 4) | (fg if (b >> bit) & 1 else bg)
            out += struct.pack(">I", v)
    return bytes(out)


def vdp_color_to_rgb(c: int) -> Tuple[int, int, int]:
    r = (c & 0xE) * 255 // 14
    g = ((c >> 4) & 0xE) * 255 // 14
    b = ((c >> 8) & 0xE) * 255 // 14
    return (r, g, b)


# ---------------------------------------------------------------------------
# Mappings de sprites (FF1166) et animations (FF1126)
# ---------------------------------------------------------------------------
@dataclass
class Piece:
    dy: int       # déplacement y (signé)
    size: int     # octet taille VDP (bits 2-3 : largeur-1, bits 0-1 : hauteur-1)
    pattern: int  # mot pattern (priorité/palette/flips/index)
    dx: int       # déplacement x normal
    dx_flip: int  # déplacement x si sprite retourné

    @property
    def width(self) -> int:
        return ((self.size >> 2) & 3) + 1

    @property
    def height(self) -> int:
        return (self.size & 3) + 1


@dataclass
class Frame:
    hitbox: int          # index dans la table des boîtes de collision (0xFF = aucune)
    pieces: List[Piece]


def read_frame(rom: Rom, addr: int) -> Frame:
    n = rom.u8(addr) + 1
    hitbox = rom.u8(addr + 1)
    pieces = []
    a = addr + 2
    for _ in range(n):
        pieces.append(Piece(rom.s8(a), rom.u8(a + 1), rom.u16(a + 2), rom.s8(a + 4), rom.s8(a + 5)))
        a += 6
    return Frame(hitbox, pieces)


@dataclass
class Anim:
    frames: int
    delay: int
    ptrs: List[int]   # adresses ROM des frames (mappings)


def read_anim(rom: Rom, addr: int) -> Anim:
    n = rom.u8(addr)
    delay = rom.u8(addr + 1)
    ptrs = [rom.word_ptr(addr + 2, i) for i in range(n)]
    return Anim(n, delay, ptrs)


def read_anim_table(rom: Rom, addr: int, count: int) -> List[Anim]:
    """Table de longs -> animations (champ +8 de l'objet, index = +6/4)."""
    return [read_anim(rom, rom.u32(addr + 4 * i)) for i in range(count)]


# ---------------------------------------------------------------------------
# Niveaux
# ---------------------------------------------------------------------------
LEVEL_TABLE = 0x1AD92        # 48 mots : offsets bas des données de niveau
SPECIAL_TABLE = 0x15508      # 48 mots : cases spéciales (FF1608)
CAT_SPEED_TABLE = 0x15B94    # 48 x (vx.l, vy.l) chats (d26e/d272)
LIZARD_SPEED_IDX = 0x15D28   # 48 octets -> index dans LIZARD_SPEEDS
LIZARD_SPEEDS = 0x15D14      # 5 longs (d276)
N_LEVELS = 48


@dataclass
class Level:
    index: int
    walls: List[Tuple[int, int, int]]      # (col, row, len) — segments décodés
    wallmap: List[List[int]]               # 28x32 : 1 = mur
    door: Tuple[int, int]                  # (col, row) de la porte (d82e/d82f)
    blocks: List[List[Tuple[int, int]]]    # 6 listes de blocs (types 0..5) pos tuiles
    chicks: List[Tuple[int, int]]          # 6 positions (tuiles)
    cats: List[Tuple[int, int]]            # ennemis type 0 (Tiger)
    lizards: List[Tuple[int, int]]         # ennemis type 1 (Iggy)
    special7: List[Tuple[int, int]]        # cases bit7
    special76: List[Tuple[int, int]]       # cases bit7|bit6
    special5: List[Tuple[int, int]]        # cases bit5
    cat_vx: int
    cat_vy: int
    lizard_vx: int


def read_level(rom: Rom, index: int) -> Level:
    a = rom.word_ptr(LEVEL_TABLE, index)
    wallmap = [[0] * 32 for _ in range(28)]
    walls = []
    # FF13E4 : décodage RLE des murs à partir de la ligne 2 (C840)
    p = 0x40
    while True:
        b = rom.u8(a)
        a += 1
        if b == 0:
            break
        if not b & 0x80:
            p += b
            continue
        n = b & 0x3F
        if b & 0x40:
            walls.append((p % 32, p // 32, -n))
            for k in range(n):
                q = p + 0x20 * k
                wallmap[q // 32][q % 32] = 1
            p += 1
        else:
            walls.append((p % 32, p // 32, n))
            for k in range(n):
                q = p + k
                wallmap[q // 32][q % 32] = 1
            p += n
    # FF148A : la porte est la position du bloc de type 0 (non consommée séparément)
    door = (rom.u8(a), rom.u8(a + 1))

    def read_list(count):
        nonlocal a
        lst = []
        for _ in range(count):
            lst.append((rom.u8(a), rom.u8(a + 1)))
            a += 2
        return lst

    blocks = [[] for _ in range(6)]
    blocks[0] += read_list(1)          # type 0 : porte (d82e/d82f)
    blocks[1] += read_list(2)          # type 1 : 2 blocs (d830, d832)
    blocks[2] += read_list(1)          # type 2 : 1 bloc (d834)
    n = rom.u8(a); a += 1
    if n:
        blocks[3] += read_list(n)
    n = rom.u8(a); a += 1
    if n:
        blocks[4] += read_list(n)
    n = rom.u8(a); a += 1
    if n:
        blocks[5] += read_list(n)
    chicks = read_list(6)
    n = rom.u8(a); a += 1
    cats = read_list(n)
    n = rom.u8(a); a += 1
    lizards = read_list(n)

    # FF1608 : cases spéciales
    s = rom.word_ptr(SPECIAL_TABLE, index)
    specials = []
    for _ in range(3):
        n = rom.u8(s); s += 1
        lst = []
        for _ in range(n):
            lst.append((rom.u8(s), rom.u8(s + 1)))
            s += 2
        specials.append(lst)

    cat_vx = rom.s32(CAT_SPEED_TABLE + 8 * index)
    cat_vy = rom.s32(CAT_SPEED_TABLE + 8 * index + 4)
    lizard_vx = rom.s32(LIZARD_SPEEDS + 4 * rom.u8(LIZARD_SPEED_IDX + index))
    return Level(index, walls, wallmap, door, blocks, chicks, cats, lizards,
                 specials[0], specials[1], specials[2], cat_vx, cat_vy, lizard_vx)
