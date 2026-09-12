"""Compare le port avec le code ROM exécuté par l'interpréteur 68000 sur la
démo intégrée (validation bit à bit des objets et variables globales)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from flicky.objects import PAD_START

try:
    from flicky.rom import Rom
    Rom()
    HAVE_ROM = True
except FileNotFoundError:
    HAVE_ROM = False

pytestmark = pytest.mark.skipif(not HAVE_ROM, reason="ROM Flicky absente")


def test_demo0_lockstep():
    from tools.harness import Lockstep
    L = Lockstep()
    for f in range(1500):
        s = L.state()
        pad = 0
        if s == 17 and f > 10 and f % 30 == 0:
            pad = PAD_START
        if s == 1 and L.m.r16(0xFFFF92) < 0x3F0:
            L.poke_global("ff92", 0x3F0)
        L.step(pad)
        assert not L.check(), f"divergence à la frame {f}"
    assert L.state() == 15          # en démo
    assert L.g.round == 1 and L.g.following >= 0


def test_full_game_lockstep():
    """Partie réelle : fins de round (téléportation identique des deux côtés),
    bonus spécial, vie supplémentaire, stage bonus, game over."""
    from tools.harness import Lockstep
    from flicky.objects import PAD_RIGHT, PLAYER, CHIRPS
    L = Lockstep()
    g, m = L.g, L.m
    play_start = None
    prev = None
    seen = set()
    for f in range(4200):
        s = L.state()
        seen.add(s)
        if s != prev:
            prev = s
            if s != 9:
                play_start = None
        pad = 0
        if s == 17 and f > 10 and f % 30 == 0:
            pad = PAD_START
        if s in (1, 3) and m.r16(0xFFFF92) > 5 and f % 30 == 0:
            pad = PAD_START
        if s == 9 and g.play_sub == 0:
            if play_start is None:
                play_start = f
            k = f - play_start
            p = g.obj(PLAYER)
            if p.routine and p.state == 0 and not g.at_door and not g.freeze:
                if g.round == 4:
                    if g.lives > 1:
                        L.poke_global("lives", 1)
                elif g.following < g.chirps_left and k % 8 == 0 and k > 30 and g.player_hit == 0:
                    L.poke_obj(PLAYER, xi=g.door_x0 + 8, yi=g.door_y, vx=0, b38=0)
                    for a in CHIRPS:
                        c = g.obj(a)
                        if c.routine and c.state in (0, 8, 0xC):
                            L.poke_obj(a, xi=g.door_x0 + 8, yi=g.door_y, vx=0, vy=0)
        if s == 11 and g.bonus_sub == 0:
            pad = PAD_RIGHT if (f // 60) % 2 else 0
        L.step(pad)
        assert not L.check(), f"divergence à la frame {f} (état {s}, round {g.round})"
        if s == 16 and f > 3000:
            break
    assert {9, 10, 11, 16}.issubset(seen)
    assert g.round == 4 and g.lives == 0
