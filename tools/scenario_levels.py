"""Charge les 48 niveaux (rounds 1..48 via poke du numéro de round) et joue
~90 frames de chaque, en comparant ROM et port (carte de collision incluse)."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.harness import Lockstep
from flicky.objects import PAD_START, PAD_RIGHT, PAD_A, PLAYER

L = Lockstep(); g, m = L.g, L.m
t0 = time.time()
prev = None; play_start = None; next_round = 1; done = set()
for f in range(40000):
    s = L.state()
    if s != prev:
        if s in (8, 10): print(f"[{f:5d}] round {g.round} -> état {s} ({time.time()-t0:.0f}s)")
        prev = s
        if s != 9: play_start = None
    pad = 0
    if s == 17 and f > 10 and f % 30 == 0: pad = PAD_START
    if s == 1 and m.r16(0xFFFF92) > 5 and f % 30 == 0: pad = PAD_START
    if s == 3 and m.r16(0xFFFF92) > 5 and f % 30 == 0: pad = PAD_START
    def force_round(r):
        bcd = ((r // 10) << 4) | (r % 10)
        m.w8(0xFFD82D, r); m.w8(0xFFD82C, bcd); g.round = r; g.round_bcd = bcd
        m.w16(0xFFFFC0, 0x18); g.state_id = 0x18          # retour à l'init de partie (état 6)
    if s == 9 and g.play_sub == 0:
        if play_start is None: play_start = f
        k = f - play_start
        pad = PAD_RIGHT | (PAD_A if k % 40 < 5 else 0)
        if k == 90:
            done.add(g.round)
            if g.round >= 48: break
            force_round(g.round + 1)
    if s == 11 and g.bonus_sub == 0 and g.frame > 90:
        done.add(g.round)
        force_round(g.round + 1)
    L.step(pad)
    if L.check(label=f"round {g.round}"):
        if L.bad >= 6: break
print(f"fin: {len(done)} rounds chargés, {L.frame} frames, {L.bad} divergentes, première {L.first_bad}, {time.time()-t0:.0f}s")
