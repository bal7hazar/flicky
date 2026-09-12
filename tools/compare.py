"""Compare frame par frame le port Python et le code ROM exécuté par
l'interpréteur 68000 (tools/m68k.py), avec les mêmes entrées manette.

Usage: python tools/compare.py [--frames N] [--demo] [--play] [--stop-after K]
"""
import argparse, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.m68k import Machine, load_rom
from flicky.game import Game
from flicky.objects import PAD_START, PAD_RIGHT, PAD_LEFT, PAD_A

ap = argparse.ArgumentParser()
ap.add_argument('--frames', type=int, default=3000)
ap.add_argument('--demo', action='store_true')
ap.add_argument('--stop-after', type=int, default=8, help="nb de frames divergentes affichées avant arrêt")
ap.add_argument('--skip-title', action='store_true', help="force la démo dès le titre (ff92=0x3ff)")
ap.add_argument('--quiet-fields', default='', help="champs à ignorer, séparés par des virgules")
ap.add_argument('--demo-index', type=int, default=0, help="numéro de démo (d890)")
args = ap.parse_args()

g = Game()
m = Machine(load_rom(g.rom.path))
ignore = set(args.quiet_fields.split(',')) if args.quiet_fields else set()

def norm(v):
    """pointeur RAM FFFFxxxx (sign-étendu) -> adresse ROM 1xxxx équivalente"""
    if (v & 0xFFFF0000) == 0xFFFF0000 or (v & 0xFFFF0000) == 0x00FF0000:
        return 0x10000 | (v & 0xFFFF)
    return v

OBJ_FIELDS = [
    ("routine", lambda r, o: (r.r16(o), (g.objs[(o - 0xFFC000) >> 6].routine | (0x8000 if g.objs[(o - 0xFFC000) >> 6].init else 0)))),
    ("flags", lambda r, o: (r.r8(o + 2), g.objs[(o - 0xFFC000) >> 6].flags)),
    ("hit_id", lambda r, o: (r.r8(o + 4), g.objs[(o - 0xFFC000) >> 6].hit_id)),
    ("hit", lambda r, o: (r.r8(o + 5), g.objs[(o - 0xFFC000) >> 6].hit)),
    ("anim", lambda r, o: (r.r16(o + 6), g.objs[(o - 0xFFC000) >> 6].anim)),
    ("anim_table", lambda r, o: (norm(r.r32(o + 8)), g.objs[(o - 0xFFC000) >> 6].anim_table)),
    ("frame_ptr", lambda r, o: (norm(r.r32(o + 0xC)), g.objs[(o - 0xFFC000) >> 6].frame_ptr)),
    ("frame", lambda r, o: (r.r8(o + 0x10), g.objs[(o - 0xFFC000) >> 6].frame)),
    ("ftimer", lambda r, o: (r.r8(o + 0x11), g.objs[(o - 0xFFC000) >> 6].ftimer)),
    ("pal", lambda r, o: (r.r8(o + 0x13), g.objs[(o - 0xFFC000) >> 6].pal)),
    ("b16", lambda r, o: (r.r8(o + 0x16), g.objs[(o - 0xFFC000) >> 6].b16)),
    ("xs", lambda r, o: (r.r16(o + 0x20), g.objs[(o - 0xFFC000) >> 6].xs & 0xFFFF)),
    ("y", lambda r, o: (r.r32(o + 0x24), g.objs[(o - 0xFFC000) >> 6].y & 0xFFFFFFFF)),
    ("vy", lambda r, o: (r.r32(o + 0x2C), g.objs[(o - 0xFFC000) >> 6].vy & 0xFFFFFFFF)),
    ("x", lambda r, o: (r.r32(o + 0x30), g.objs[(o - 0xFFC000) >> 6].x & 0xFFFFFFFF)),
    ("vx", lambda r, o: (r.r32(o + 0x34), g.objs[(o - 0xFFC000) >> 6].vx & 0xFFFFFFFF)),
    ("w38", lambda r, o: (r.r16(o + 0x38), g.objs[(o - 0xFFC000) >> 6].w38)),
    ("w3a", lambda r, o: (r.r16(o + 0x3A), g.objs[(o - 0xFFC000) >> 6].w3a)),
    ("v3c", lambda r, o: (r.r16(o + 0x3C), g.objs[(o - 0xFFC000) >> 6].v3c)),
    ("w3e", lambda r, o: (r.r16(o + 0x3E), g.objs[(o - 0xFFC000) >> 6].w3e)),
]
GLOBALS = [
    ("ffc0 state", lambda: (m.r16(0xFFFFC0), g.state_id)),
    ("ff92 frame", lambda: (m.r16(0xFFFF92), g.frame)),
    ("ff8e pad", lambda: (m.r8(0xFFFF8E), g.pad)),
    ("ffa8 camx", lambda: (m.r32(0xFFFFA8), g.camx & 0xFFFFFFFF)),
    ("d004 camvx", lambda: (m.r32(0xFFD004), g.cam_vx & 0xFFFFFFFF)),
    ("d24e bonusmode", lambda: (m.r8(0xFFD24E), g.bonus_mode)),
    ("d24f atdoor", lambda: (m.r8(0xFFD24F), g.at_door)),
    ("d26c enemies", lambda: (m.r8(0xFFD26C), g.enemies_alive)),
    ("d26d hit", lambda: (m.r8(0xFFD26D), g.player_hit)),
    ("d27a following", lambda: (m.r8(0xFFD27A), g.following)),
    ("d27b freeze", lambda: (m.r8(0xFFD27B), g.freeze)),
    ("d27c lizspeed", lambda: (m.r32(0xFFD27C), g.lizard_speed & 0xFFFFFFFF)),
    ("d281 rounddone", lambda: (m.r8(0xFFD281), g.round_done)),
    ("d294 spawndelay", lambda: (m.r16(0xFFD294), g.spawn_delay)),
    ("d296 catspeed", lambda: (m.r32(0xFFD296), g.cat_speed & 0xFFFFFFFF)),
    ("d2a0 playsub", lambda: (m.r16(0xFFD2A0), g.play_sub)),
    ("d2a4 jingle", lambda: (m.r8(0xFFD2A4), g.jingle)),
    ("d82d round", lambda: (m.r8(0xFFD82D), g.round)),
    ("d87e score", lambda: (m.r32(0xFFD87E), g.score)),
    ("d882 lives", lambda: (m.r8(0xFFD882), g.lives)),
    ("d883 chirps", lambda: (m.r8(0xFFD883), g.chirps_left)),
    ("d888 timer", lambda: ((m.r8(0xFFD888), m.r8(0xFFD889), m.r8(0xFFD88A)), (g.t_min, g.t_sec, g.t_frame))),
    ("d88d reached", lambda: (m.r8(0xFFD88D), g.reached)),
    ("d88f nobonus", lambda: (m.r8(0xFFD88F), g.no_bonus)),
]

def diff_frame(prev_state=None):
    out = []
    for name, fn in GLOBALS:
        if name.split()[1] in ignore: continue
        a, b = fn()
        if a != b:
            out.append(f"  {name}: rom={a if not isinstance(a,int) else hex(a)} port={b if not isinstance(b,int) else hex(b)}")
    if state_rom() in (16, 17) or prev_state in (16, 17):   # écran SEGA : C3E0.. sert de tampon Enigma
        return out
    for i in range(32):
        base = 0xFFC000 + 0x40 * i
        for name, fn in OBJ_FIELDS:
            if name in ignore: continue
            a, b = fn(m, base)
            if a != b:
                out.append(f"  obj C{0x000 + 0x40*i:03X} {name}: rom={a:x} port={b:x}")
    return out

def state_rom(): return (m.r16(0xFFFFC0) & 0x7C) >> 2

t0 = time.time()
bad = 0
first_bad = None
for f in range(args.frames):
    s = state_rom()
    pad = 0
    if f == 5 and args.demo_index:        # après l'effacement de la RAM au boot
        m.w16(0xFFD890, args.demo_index); g.demo_idx = args.demo_index
    if s == 17 and f > 10 and f % 30 == 0: pad = PAD_START
    if args.demo:
        if s == 1 and args.skip_title and m.r16(0xFFFF92) < 0x3F0:
            m.w16(0xFFFF92, 0x3F0); g.frame = 0x3F0
    else:
        if s == 1 and m.r16(0xFFFF92) > 5 and f % 30 == 0: pad = PAD_START
        if s == 3 and m.r16(0xFFFF92) > 5 and f % 30 == 0: pad = PAD_START
        if s == 9:
            k = f // 45
            pad = [PAD_RIGHT, PAD_RIGHT | PAD_A, PAD_LEFT, PAD_LEFT | PAD_A, 0, PAD_A, PAD_RIGHT][k % 7]
    m.run_frame(pad)
    g.step(pad)
    d = diff_frame(s)
    if d:
        bad += 1
        if first_bad is None: first_bad = f
        print(f"--- frame {f} (état {s}, rom ffc0={m.r16(0xFFFFC0):x} pad={pad:02x}) : {len(d)} différences")
        for line in d[:25]: print(line)
        if bad >= args.stop_after:
            break
    elif f % 200 == 0:
        print(f"frame {f} ok (état {s}, round {g.round}, t={g.t_min:02x}:{g.t_sec:02x}, {m.icount} instr, {time.time()-t0:.0f}s)")
print(f"fin: {f+1} frames, {bad} divergentes, première: {first_bad}, {time.time()-t0:.0f}s")
