import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pytest
from flicky.rom import Rom, read_level, nemesis_decode
from flicky.data import Data

try:
    ROM = Rom()
except FileNotFoundError:
    ROM = None

pytestmark = pytest.mark.skipif(ROM is None, reason="ROM Flicky absente")


def test_header():
    assert ROM.data[0x100:0x104] == b"SEGA"


def test_levels_parse():
    d = Data(ROM)
    assert len(d.levels) == 48
    l0 = d.levels[0]
    assert l0.door == (15, 23)
    assert len(l0.chicks) == 6
    assert len(l0.cats) + len(l0.lizards) in range(4, 9)
    for lv in d.levels:
        assert 4 <= len(lv.cats) + len(lv.lizards) <= 8
        assert all(0 <= x < 32 and 0 <= y < 28 for x, y in lv.chicks)


def test_nemesis_sizes():
    assert len(ROM.nemesis(0x16E58)) == 343 * 32
    assert len(ROM.nemesis(0x187D4)) == 303 * 32


def test_tables():
    d = Data(ROM)
    assert d.chirp_door_scores == [0x100, 0x200, 0x300, 0x400, 0x500, 0x1000, 0x2000, 0x5000]
    assert d.extra_life_thresholds[0] == 0x30000
    assert d.wall_tiles[1] == 0x2206
