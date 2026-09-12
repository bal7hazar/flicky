"""Scénario : sélection de round (A+C+Haut+Start), stage bonus du round 47,
round 48 puis la fin (générique) et le retour au jeu."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.harness import Lockstep
from flicky.objects import PAD_START, PAD_UP, PAD_A, PAD_C, PAD_RIGHT, PLAYER, CHIRPS

L = Lockstep()
g, m = L.g, L.m
t0 = time.time()
stop_after = int(sys.argv[1]) if len(sys.argv) > 1 else 6
max_frames = int(sys.argv[2]) if len(sys.argv) > 2 else 12000
prev_state = None
play_start = None
ups = 0
poked47 = False
for f in range(max_frames):
    s = L.state()
    if s != prev_state:
        print(f"[{f:5d}] état {prev_state} -> {s}  round {g.round} (bcd {g.round_bcd:02x}) vies {g.lives} score {g.score:08x} ({time.time()-t0:.0f}s)")
        prev_state = s
        if s != 9: play_start = None
    pad = 0
    if s == 17 and f > 10 and f % 30 == 0: pad = PAD_START
    if s == 1 and m.r16(0xFFFF92) > 5 and f % 30 == 0: pad = PAD_START
    if s == 3 and m.r16(0xFFFF92) > 5:
        pad = PAD_A | PAD_C | PAD_UP | (PAD_START if f % 30 == 0 else 0)   # code du choix de round
    if s == 5:
        if ups < 2 and f % 10 == 0:
            pad = PAD_UP; ups += 1
        elif ups >= 2 and f % 30 == 0:
            pad = PAD_START
    if s == 6 and not poked47 and g.round == 3:
        # sauter au round 47 (stage bonus) pour atteindre 48 puis la fin
        m.w8(0xFFD82D, 47); m.w8(0xFFD82C, 0x47); g.round = 47; g.round_bcd = 0x47
        poked47 = True
    if s == 9 and g.play_sub == 0:
        if play_start is None: play_start = f
        k = f - play_start
        p = g.obj(PLAYER)
        if p.routine and p.state == 0 and not g.at_door and not g.freeze:
            if g.following < g.chirps_left and k % 8 == 0 and k > 30 and g.player_hit == 0:
                L.poke_obj(PLAYER, xi=g.door_x0 + 8, yi=g.door_y, vx=0, b38=0)
                for a in CHIRPS:
                    c = g.obj(a)
                    if c.routine and c.state in (0, 8, 0xC):
                        L.poke_obj(a, xi=g.door_x0 + 8, yi=g.door_y, vx=0, vy=0)
    if s == 11 and g.bonus_sub == 0:
        pad = PAD_RIGHT if (f // 60) % 2 else 0
    if s == 13 and g.ending_sub & 0x7C == 8 and f % 30 == 0:
        pad = PAD_START
    L.step(pad)
    if L.check(label=f"round {g.round} sub {g.play_sub:x} end {g.ending_sub:x}"):
        if L.bad >= stop_after:
            break
    if s == 9 and g.round == 49 and g.play_sub == 0 and g.obj(PLAYER).routine and play_start and f - play_start > 300:
        print("round 49 en cours après la fin : scénario terminé")
        break
print(f"fin: {L.frame} frames, {L.bad} divergentes, première {L.first_bad}, {time.time()-t0:.0f}s")
