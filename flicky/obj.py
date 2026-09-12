"""Objet de jeu : image Python des 0x40 octets d'un slot objet (0xFFC000 + 0x40*n).

Les champs gardent les noms d'offsets du code original quand leur rôle varie
selon l'objet ; les alias mot/octet (+38/+39, +3A/+3B, +3E/+3F) sont rendus par
des propriétés pour reproduire les accès 68000.
"""
from __future__ import annotations


def s32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - 0x100000000 if v & 0x80000000 else v


def s16(v: int) -> int:
    v &= 0xFFFF
    return v - 0x10000 if v & 0x8000 else v


def hi(v: int) -> int:
    """Mot de poids fort (partie entière) d'un long 16.16, signé."""
    return s16((v >> 16) & 0xFFFF)


def set_hi(v: int, w: int) -> int:
    """Écrit la partie entière (move.w -> +0) en gardant la fraction."""
    return s32(((w & 0xFFFF) << 16) | (v & 0xFFFF))


def clr_lo(v: int) -> int:
    """clr.w +2 : efface la fraction."""
    return s32(v & 0xFFFF0000)


# bits du champ flags (+2)
F_NOPHYS = 0x01     # bit0 : pas de déplacement (FF105C)
F_HIDDEN = 0x02     # bit1 : pas de sprite
F_ANIMEND = 0x04    # bit2 : animation terminée (FF1126)
F_XFLIP = 0x80      # bit7 : sprite retourné horizontalement


class Obj:
    __slots__ = ("slot", "routine", "init", "flags", "hit_id", "hit", "anim", "anim_table",
                 "frame_ptr", "frame", "ftimer", "pal", "b16", "l18", "l1c", "xs", "y", "vy",
                 "x", "vx", "w38", "w3a", "v3c", "w3e")

    def __init__(self, slot: int):
        self.slot = slot          # adresse RAM (0xC000 + 0x40*n), pour les tests d'adresse
        self.clear()

    def clear(self):
        """clr 0x40 octets (FF10F0)."""
        self.routine = 0          # +0.w  (bit 15 = initialisé)
        self.init = False
        self.flags = 0            # +2.b
        self.hit_id = 0           # +4.b  id de boîte de collision (copié depuis le mapping)
        self.hit = 0              # +5.b  bits de collision actifs
        self.anim = 0             # +6.w  index d'animation (multiple de 4)
        self.anim_table = 0       # +8.l
        self.frame_ptr = 0        # +C.l  mapping courant
        self.frame = 0            # +10.b
        self.ftimer = 0           # +11.b
        self.pal = 0              # +13.b bits OR sur l'octet haut du pattern
        self.b16 = 0              # +16.b sous-identifiant
        self.l18 = 0              # +18.l (stage bonus : accélération)
        self.l1c = 0              # +1C.l (stage bonus : vitesse cible)
        self.xs = 0               # +20.w x écran
        self.y = 0                # +24.l
        self.vy = 0               # +2C.l
        self.x = 0                # +30.l
        self.vx = 0               # +34.l
        self.w38 = 0              # +38.w
        self.w3a = 0              # +3A.w
        self.v3c = 0              # +3C.w (bit 15 = sous-état initialisé)
        self.w3e = 0              # +3E.w

    def clear_keep_pos(self):
        """FF1118 : efface 0x3E octets (garde +3E/+3F)."""
        w3e = self.w3e
        self.clear()
        self.w3e = w3e

    # --- alias octets ---
    @property
    def b38(self): return (self.w38 >> 8) & 0xFF
    @b38.setter
    def b38(self, v): self.w38 = ((v & 0xFF) << 8) | (self.w38 & 0xFF)
    @property
    def b39(self): return self.w38 & 0xFF
    @b39.setter
    def b39(self, v): self.w38 = (self.w38 & 0xFF00) | (v & 0xFF)
    @property
    def b3a(self): return (self.w3a >> 8) & 0xFF
    @b3a.setter
    def b3a(self, v): self.w3a = ((v & 0xFF) << 8) | (self.w3a & 0xFF)
    @property
    def b3b(self): return self.w3a & 0xFF
    @b3b.setter
    def b3b(self, v): self.w3a = (self.w3a & 0xFF00) | (v & 0xFF)
    @property
    def b3e(self): return (self.w3e >> 8) & 0xFF
    @b3e.setter
    def b3e(self, v): self.w3e = ((v & 0xFF) << 8) | (self.w3e & 0xFF)
    @property
    def b3f(self): return self.w3e & 0xFF
    @b3f.setter
    def b3f(self, v): self.w3e = (self.w3e & 0xFF00) | (v & 0xFF)

    # --- sous-état +3C ---
    @property
    def state(self) -> int:
        return self.v3c & 0x7C

    @state.setter
    def state(self, v: int):
        self.v3c = v & 0xFFFF

    def sub_init(self) -> bool:
        """bset #7,$3c(a0) ; retourne True la première fois."""
        if self.v3c & 0x8000:
            return False
        self.v3c |= 0x8000
        return True

    def first(self) -> bool:
        """bset #7,(a0) : True la première fois que la routine s'exécute."""
        if self.init:
            return False
        self.init = True
        return True

    # --- positions entières ---
    @property
    def xi(self) -> int: return hi(self.x)
    @xi.setter
    def xi(self, w: int): self.x = set_hi(self.x, w)
    @property
    def yi(self) -> int: return hi(self.y)
    @yi.setter
    def yi(self, w: int): self.y = set_hi(self.y, w)

    def set_flag(self, f: int): self.flags |= f
    def clr_flag(self, f: int): self.flags &= ~f & 0xFF
    def has(self, f: int) -> bool: return bool(self.flags & f)
    @property
    def xflip(self) -> bool: return bool(self.flags & F_XFLIP)

    def __repr__(self):
        return (f"Obj({self.slot:04X} r={self.routine:02X} st={self.state:02X} x={self.x/65536:.2f} "
                f"y={self.y/65536:.2f} vx={self.vx/65536:.3f} vy={self.vy/65536:.3f})")
