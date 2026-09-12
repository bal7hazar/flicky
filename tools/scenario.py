"""Scénario complet ROM/port : rounds réels avec fin de round (téléportation
identique des deux côtés), stage bonus, pause, vie supplémentaire, game over."""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.harness import Lockstep
from flicky.objects import PAD_START, PAD_RIGHT, PAD_A, PLAYER, CHIRPS

L = Lockstep()
g, m = L.g, L.m
rom = g.rom
demo = g.d.demo_scripts[0]
t0 = time.time()

def demo_pad(k):
    a = demo
    while True:
        pad, n = rom.u8(a), rom.u8(a + 1)
        if n == 0: return 0
        if k < n: return pad
        k -= n; a += 2

stop_after = int(sys.argv[1]) if len(sys.argv) > 1 else 6
max_frames = int(sys.argv[2]) if len(sys.argv) > 2 else 15000
prev_state = None
play_start = None
paused_done = False
extra_done = False
for f in range(max_frames):
    s = L.state()
    if s != prev_state:
        print(f"[{f:5d}] état {prev_state} -> {s}  round {g.round} vies {g.lives} score {g.score:08x} ({time.time()-t0:.0f}s)")
        prev_state = s
        if s != 9: play_start = None
    pad = 0
    if s == 17 and f > 10 and f % 30 == 0: pad = PAD_START
    if s == 1 and m.r16(0xFFFF92) > 5 and f % 30 == 0: pad = PAD_START
    if s == 3 and m.r16(0xFFFF92) > 5 and f % 30 == 0: pad = PAD_START
    if s == 9 and g.play_sub == 0:
        if play_start is None: play_start = f
        k = f - play_start
        p = g.obj(PLAYER)
        if p.routine and p.state == 0 and not g.at_door and not g.freeze:
            if g.round == 1 and g.lives == 3 and k < 600:
                pad = demo_pad(k)          # jeu réel avec les entrées de la démo (lancers d'objets, chats)
            elif g.round == 4:
                if g.lives > 1: L.poke_global("lives", 1)
                pad = 0                    # attendre qu'un chat touche Flicky
            else:
                if g.round == 2 and not paused_done and k == 120:
                    pad = PAD_START        # pause
                if g.round == 2 and not paused_done and k == 200:
                    pad = PAD_START        # reprise
                    paused_done = True
                if g.round == 2 and not extra_done and k == 260:
                    L.poke_global("score", 0x00029990)   # vie supplémentaire à 30000
                    extra_done = True
                # téléporter joueur + poussins à la porte : ramassage puis livraison
                if g.following < g.chirps_left and k % 8 == 0 and k > 30 and g.player_hit == 0:
                    L.poke_obj(PLAYER, xi=g.door_x0 + 8, yi=g.door_y, vx=0, b38=0)
                    for a in CHIRPS:
                        c = g.obj(a)
                        if c.routine and c.state in (0, 8, 0xC):
                            L.poke_obj(a, xi=g.door_x0 + 8, yi=g.door_y, vx=0, vy=0)
                    pad = 0
    if s == 11 and g.bonus_sub == 0:
        pad = PAD_RIGHT if (f // 60) % 2 else 0   # stage bonus : va-et-vient
    L.step(pad)
    if L.check(label=f"round {g.round} sub {g.play_sub:x}"):
        if L.bad >= stop_after:
            break
    if s == 16 and f > 3000:
        print("retour écran SEGA : fin du scénario")
        break
print(f"fin: {L.frame} frames, {L.bad} divergentes, première {L.first_bad}, {time.time()-t0:.0f}s")
