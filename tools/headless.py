"""Exécution sans affichage : boot, titre, puis démo ROM ou partie scriptée.

Usage: python tools/headless.py [--frames N] [--demo] [--verbose]
"""
import argparse, sys, os, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flicky.game import Game, bcd_to_int
from flicky.objects import PAD_START, PAD_BUTTONS, PAD_LEFT, PAD_RIGHT, PLAYER, CHIRPS, ENEMIES

ap = argparse.ArgumentParser()
ap.add_argument('--frames', type=int, default=3000)
ap.add_argument('--demo', action='store_true', help='laisse tourner la démo intégrée')
ap.add_argument('--verbose', action='store_true')
ap.add_argument('--round', type=int, default=0)
args = ap.parse_args()

g = Game()
def st(): return (g.state_id & 0x7C) >> 2
pad = 0
last_state = None
try:
    for f in range(args.frames):
        s = st()
        if s != last_state:
            print(f"[{f:5d}] state {last_state} -> {s} (round {g.round}, lives {g.lives})")
            last_state = s
        pad = 0
        if not args.demo:
            pulse = (f % 30 == 0)                             # appui d'une frame
            if s == 17 and f > 10 and pulse: pad = PAD_START  # écran SEGA -> titre
            if s == 1 and g.frame > 5 and pulse: pad = PAD_START   # titre -> instructions
            if s == 3 and g.frame > 5 and pulse: pad = PAD_START   # instructions -> jeu
            if s == 9:
                # joueur : va à droite, saute périodiquement
                pad = PAD_RIGHT | (PAD_BUTTONS if (f // 40) % 3 == 0 else 0)
        else:
            if s == 17 and f > 10: pad = PAD_START
            if s == 1 and f > 200: g.frame = 0x400            # force la démo
        g.step(pad)
        if args.verbose and s in (9, 15) and f % 60 == 0:
            p = g.obj(PLAYER if not g.bonus_mode else 0xC580)
            en = [(e.routine, e.state, e.xi, e.yi) for e in (g.obj(a) for a in ENEMIES) if e.routine]
            print(f"  f{f} t={g.t_min:02x}:{g.t_sec:02x} sub={g.play_sub&0x7C:x} player {p} follow={g.following} left={g.chirps_left} score={bcd_to_int(g.score)} en={en} spr={len(g.sprites)}")
except Exception:
    traceback.print_exc()
    print("state", st(), "frame", f, "objs:")
    for o in g.objs:
        if o.routine: print("  ", o)
    sys.exit(1)
print("OK", args.frames, "frames ; score", bcd_to_int(g.score), "round", g.round, "sounds", len(g.sound_log))
