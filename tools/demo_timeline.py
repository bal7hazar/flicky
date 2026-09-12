"""Rejoue la démo intégrée n°N et affiche les événements (pour valider le port)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flicky.game import Game
from flicky.objects import PAD_START, PLAYER, CHIRPS, ENEMIES
n = int(sys.argv[1]) if len(sys.argv) > 1 else 0
frames = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
g = Game()
g.demo_idx = n
st = lambda: (g.state_id & 0x7C) >> 2
prev = {}
def snapshot():
    p = g.obj(PLAYER)
    return dict(follow=g.following, left=g.chirps_left, atdoor=g.at_door, pst=p.state, lives=g.lives,
                en=tuple((e.routine, e.state) for e in (g.obj(a) for a in ENEMIES)),
                ch=tuple(g.obj(a).state for a in CHIRPS), held=(g.obj(PLAYER).b3b), state=st(), round=g.round)
t0 = None
for f in range(frames):
    s = st(); pad = 0
    if s == 17 and f > 10 and f % 30 == 0: pad = PAD_START
    if s == 1 and f > 200: g.frame = 0x400
    g.step(pad)
    if s == 15 and t0 is None: t0 = f
    if t0 is not None:
        cur = snapshot()
        for k, v in cur.items():
            if prev.get(k) != v:
                p = g.obj(PLAYER)
                print(f"f{f-t0:5d} t={g.t_min:02x}:{g.t_sec:02x}.{g.t_frame:02x} {k}: {prev.get(k)} -> {v}   player x={p.xi} y={p.yi} vx={p.vx/65536:.3f} pad={g.pad:02x} demo@{g.demo_ptr:#x}")
        prev = cur
    if t0 is not None and st() == 16:
        break
