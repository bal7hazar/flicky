import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from flicky.game import Game, bcd_add32, bcd_to_int
from flicky.objects import PAD_START, PAD_RIGHT, PAD_LEFT, PAD_A, PLAYER

try:
    from flicky.rom import Rom
    Rom()
    HAVE_ROM = True
except FileNotFoundError:
    HAVE_ROM = False

pytestmark = pytest.mark.skipif(not HAVE_ROM, reason="ROM Flicky absente")


def test_bcd():
    assert bcd_add32(0x00009999, 0x1) == 0x00010000
    assert bcd_to_int(0x00012345) == 12345


def state(g):
    return (g.state_id & 0x7C) >> 2


def boot_to_round(g):
    """SEGA -> titre -> instructions -> round 1."""
    for f in range(2000):
        s = state(g)
        pad = 0
        pulse = f % 30 == 0          # appui d'une seule frame (le front est lu par le V-int)
        if s == 17 and f > 10 and pulse: pad = PAD_START
        if s == 1 and g.frame > 5 and pulse: pad = PAD_START
        if s == 3 and g.frame > 5 and pulse: pad = PAD_START
        g.step(pad)
        if s == 9:
            return f
    raise AssertionError("round 1 non atteint")


def test_boot_and_play():
    g = Game()
    boot_to_round(g)
    for _ in range(200):          # intro du round (porte, 61 frames...)
        g.step(0)
    p = g.obj(PLAYER)
    assert p.routine == 0x0C
    assert g.round == 1 and g.lives == 3
    x0 = p.xi
    for _ in range(30):
        g.step(PAD_RIGHT)
    assert p.xi != x0
    # saut
    y0 = p.yi
    g.step(PAD_A)
    for _ in range(10):
        g.step(0)
    assert p.yi < y0


def test_determinism():
    def run(seed_inputs):
        g = Game()
        boot_to_round(g)
        for i in range(600):
            g.step(seed_inputs[i % len(seed_inputs)])
        p = g.obj(PLAYER)
        return (p.x, p.y, g.score, g.following, tuple(o.routine for o in g.objs))
    inputs = [PAD_RIGHT] * 40 + [PAD_RIGHT | PAD_A] * 5 + [PAD_LEFT] * 30 + [0] * 10
    assert run(inputs) == run(inputs)
