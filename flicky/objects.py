"""Handlers d'objets (table FF12B0). Chaque handler est un générateur : un
`yield` correspond à une attente de vblank (jsr $fb6c) du code original, ce qui
permet de reproduire les boucles bloquantes au milieu d'une mise à jour.

Convention : `g` est l'instance de Game, `o` l'objet courant (a0).
Les commentaires citent l'adresse du code original.
"""
from __future__ import annotations

from .obj import (Obj, F_NOPHYS, F_HIDDEN, F_ANIMEND, F_XFLIP, s32, hi, set_hi, clr_lo)

# Routines (mot +0, sans le bit 15) -> index FF12B0
R_ITEM, R_CHIRP, R_PLAYER, R_CAT, R_LIZARD, R_SPAWNER = 0x04, 0x08, 0x0C, 0x10, 0x14, 0x18
R_POPUP_COMBO, R_POPUP_DOOR, R_POPUP_BONUS, R_BONUS_ITEM = 0x1C, 0x20, 0x24, 0x28
R_NET, R_BCAT_L, R_BCAT_R, R_BCHIRP, R_GAMEOVER = 0x2C, 0x30, 0x34, 0x38, 0x3C
R_TITLE_CAST, R_PUSH_START, R_TITLE_LETTER, R_INSTR, R_ENDING, R_FLAG, R_PAUSE = 0x40, 0x44, 0x48, 0x4C, 0x50, 0x54, 0x58

# adresses d'objets remarquables
PLAYER = 0xC440
ITEMS = [0xC200 + 0x40 * i for i in range(6)]
ENEMIES = [0xC380, 0xC3C0, 0xC400]
CHIRPS = [0xC480 + 0x40 * i for i in range(8)]
SPAWNERS = [0xC680, 0xC6C0, 0xC700]

PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT = 0x01, 0x02, 0x04, 0x08
PAD_B, PAD_C, PAD_A, PAD_START = 0x10, 0x20, 0x40, 0x80
PAD_BUTTONS = 0x70


# ---------------------------------------------------------------------------
# utilitaires partagés
# ---------------------------------------------------------------------------
def facing_from_vx(o: Obj):
    """FF3F10 / FF4884 / FF4F2E : +39 = 1 si vx<0, 0 si vx>0, inchangé si 0."""
    if o.vx:
        o.b39 = 1 if o.vx < 0 else 0


def xflip_from_vx(o: Obj):
    """bclr #7 ; si vx<0 bset #7."""
    o.clr_flag(F_XFLIP)
    if o.vx < 0:
        o.set_flag(F_XFLIP)


def xflip_from_b39(o: Obj):
    o.clr_flag(F_XFLIP)
    if o.b39:
        o.set_flag(F_XFLIP)


def snap_land(o: Obj, yi: int):
    """andi #$fff8 ; clr.w +26 ; move.w -> +24 (atterrissage)."""
    o.y = set_hi(o.y, yi & 0xFFF8)
    o.y = clr_lo(o.y)


def fling_physics(g, o: Obj):
    """FF4688 : physique d'un objet projeté (chat/lézard KO, objet lancé)."""
    d7 = o.vx
    d6 = o.vy
    xflip_from_vx(o)
    g.animate(o)
    if o.b38 == 0:
        d7 = s32(d7 + 0x800) if d7 < 0 else s32(d7 - 0x800)
    else:
        d6 = s32(d6 + 0x1000)
    o.vx = d7
    o.vy = d6
    g.physics(o)
    x, y = o.xi, o.yi
    y += 1                       # addq.w #1,d6 : la position ajustée est (y+1)&~7
    if g.probe(x, y):
        o.vy = 0
        o.b38 = 0
        snap_land(o, y)
    else:
        o.b38 = 1
    x, y = o.xi, o.yi
    y -= 4
    if o.vx < 0:
        if g.probe(x - 4, y):
            o.vx = s32(-o.vx)
    else:
        if g.probe(x + 4, y):
            o.vx = s32(-o.vx)


# ---------------------------------------------------------------------------
# Joueur (FF3E70)
# ---------------------------------------------------------------------------
def player_main(g, o: Obj):
    if o.first():
        o.anim_table = 0x144AC
        x, y = g.tile_to_px(o.b3e, o.b3f)
        o.xi = x + 0xC
        o.yi = y + 0x18
        o.b3a = 3
    if g.freeze:
        return
    if not g.at_door:
        st = o.state
        if st == 0:
            yield from player_normal(g, o)
        elif st == 4:
            player_dying(g, o)
        elif st == 8:
            yield from player_dead(g, o)
    if o.state < 4 and not g.at_door:
        player_enemy_check(g, o)                                  # FF4476
    player_record_trail(g, o)                                     # FF4272
    if not g.bonus_mode:
        g.door_sign_anim()                                        # FF1C3C


def player_normal(g, o: Obj):
    """FF3EEA"""
    o.hit = 0x1E
    player_input(g, o)                                            # FF3F26
    yield from player_door_check(g, o)                            # FF42D6
    if not g.at_door:
        g.camera_step()                                           # FF130C
    g.physics(o)
    player_vertical(g, o)                                         # FF407E
    player_horizontal(g, o)                                       # FF4128
    player_anim(g, o)                                             # FF4318
    facing_from_vx(o)


def player_input(g, o: Obj):
    """FF3F26"""
    pad = g.pad
    d = pad & 0xC
    if d == 0:
        d1 = o.vx
        if o.b38 == 0 and d1 != 0:
            d1 = s32(d1 + 0x600) if d1 < 0 else s32(d1 - 0x600)
    elif d & PAD_RIGHT:
        d1 = o.vx
        d1 = 0x18000 if d1 >= 0x18000 else s32(d1 + 0x1800)
    else:
        d1 = o.vx
        d1 = -0x18000 if d1 <= -0x18000 else s32(d1 - 0x1800)
    # FF3F42
    o.vx = d1
    if not g.bonus_mode:
        g.cam_vx = d1
    player_throw(g, o)                                            # FF4038
    if o.b38:
        # FF400A : en l'air
        if o.vy < 0x30000:
            o.vy = s32(o.vy + 0x1000)
        if not (pad & PAD_BUTTONS):
            o.b3a = 3
        return
    if o.b3a & 1 and (pad & PAD_BUTTONS):
        g.sfx(0x91)
        o.b38 = 1
        o.vy = -0x29000
        o.b3a &= ~3
    if not (pad & PAD_BUTTONS):
        o.b3a = 3


def player_throw(g, o: Obj):
    """FF4038 : lance l'objet porté."""
    if not (o.b3a & 2):
        return
    if not (g.pad & PAD_BUTTONS):
        return
    if o.b3b == 0:
        return
    it = g.held_item
    it.vx = set_hi(it.vx, 4)
    if o.b39:
        it.vx = set_hi(it.vx, -4)
    it.state = 8
    it.x = o.x
    o.b3b = 0
    o.b3a &= ~2


def player_vertical(g, o: Obj):
    """FF407E : sol / plafond."""
    x, y = o.xi, o.yi
    if o.b38 == 0:
        if not g.probe(x, y + 1):
            o.b38 = 1
        return
    if o.vx == 0:
        if o.vy < 0:
            if g.probe(x, y - 0xE):
                o.vy = 0
        else:
            if g.probe(x, y):
                o.b38 = 0
                o.vy = 0
                snap_land(o, y)
        return
    if o.vy < 0:
        y -= 0xE
        if g.probe(x + 4, y) or g.probe(x - 4, y):
            o.vy = 0
        return
    if g.probe(x - 4, y) or g.probe(x + 4, y):
        o.b38 = 0
        o.vy = 0
        snap_land(o, y)


def player_horizontal(g, o: Obj):
    """FF4128 : murs."""
    x, y = o.xi, o.yi
    vx = o.vx
    if o.b38 == 0:
        y -= 0xA
        if vx == 0:
            return
        if vx < 0:
            if g.probe(x - 6, y):
                d0 = s32(vx - 0x3000)
                if d0 < -0x1FE00:
                    d0 = -0x1FE00
                o.vx = s32(-d0)
        else:
            if g.probe(x + 6, y):
                d0 = s32(vx + 0x3000)
                if d0 > 0x1FE00:
                    d0 = 0x1FE00
                o.vx = s32(-d0)
        return
    y -= 8
    if vx == 0:
        # FF4248
        if g.probe(x + 6, y):
            o.vx = -0xC000
        elif g.probe(x - 6, y):
            o.vx = 0xC000
        return
    if vx < 0:
        cell = g.probe(x - 6, y)
        if not cell:
            return
        if cell & 2 or cell & 1:
            d0 = s32(vx - 0x3000)
            if d0 < -0x1FE00:
                d0 = -0x1FE00
            o.vx = s32(-d0)
            return
    else:
        cell = g.probe(x + 6, y)
        if not cell:
            return
        if cell & 2 or cell & 1:
            d0 = s32(vx + 0x3000)
            if d0 > 0x1FE00:
                d0 = 0x1FE00
            o.vx = s32(-d0)
            return
    # FF4212 : plateforme fine
    if o.vy < 0:
        if (y & 7) >= 3:
            o.yi = y + 0x10
            o.vy = 0
        return
    o.y = set_hi(o.y, y & 0xFFF8)
    o.y = clr_lo(o.y)
    o.vy = 0
    o.b38 = 0


def player_anim(g, o: Obj):
    """FF4318"""
    o.clr_flag(F_XFLIP)
    d0 = o.vx
    pad = g.pad
    if o.b38 == 0:
        if d0 == 0:
            o.frame_ptr = 0x1A898
            return
        if d0 < 0:
            o.set_flag(F_XFLIP)
            if pad & PAD_LEFT:
                o.anim = 0
                g.animate(o)
                return
        else:
            if pad & PAD_RIGHT:
                o.anim = 0
                g.animate(o)
                return
        o.frame_ptr = 0x1A8A0
        return
    if d0 != 0:
        o.anim = 8
        if d0 < 0:
            o.set_flag(F_XFLIP)
        g.animate(o)
    else:
        o.anim = 4
        g.animate(o)


def player_door_check(g, o: Obj):
    """FF42D6 : arrivée à la porte avec des poussins."""
    if g.following == 0 or o.b38 != 0:
        return
    x, y = o.xi, o.yi
    if y != g.door_y or x < g.door_x0 or x > g.door_x1:
        return
    g.at_door = 1
    o.vx = 0
    g.cam_vx = 0
    g.reached = (g.reached + 1) & 0xFF
    yield from g.door_anim(g.d.door_open_enter, 2)                # FF1CE6


def player_enemy_check(g, o: Obj):
    """FF4476 : contact avec un ennemi (C380..C400, bit0 de +5)."""
    for addr in ENEMIES:
        e = g.obj(addr)
        if not (e.hit & 1):
            continue
        if g.collide(o, e):
            o.state = 4
            g.player_hit = 1
            return


def player_record_trail(g, o: Obj):
    """FF4272 : historique des positions pour les poussins."""
    t = g.trail
    t.pop()
    t.insert(0, (o.x, o.y))
    f = g.trail_flags
    f.pop()
    d0 = 0
    if o.b38:
        d0 |= 0x80
    if o.vx:
        d0 |= 2 if o.vx < 0 else 1
    f.insert(0, d0)


def player_dying(g, o: Obj):
    """FF438C"""
    if o.sub_init():
        g.music(0x87)
        o.hit = 0
        o.vx = 0
        o.anim = 0xC
    o.vy = s32(o.vy + 0x1000)
    g.physics(o)
    x, y = o.xi, o.yi
    if g.probe(x, y):
        o.vy = 0
        snap_land(o, y)
        o.state = 8
        return
    if o.vy < 0 and g.probe(x, y - 8):
        o.vy = 0
    g.animate(o)


def player_dead(g, o: Obj):
    """FF43FC"""
    if o.sub_init():
        o.hit = 0
        o.frame = 0
        o.clr_flag(F_ANIMEND)
        o.b39 = 3
    g.physics(o)
    g.animate(o)
    if o.has(F_ANIMEND):
        o.clr_flag(F_ANIMEND)
        o.b39 = (o.b39 - 1) & 0xFF
        for addr in ENEMIES:                                      # FF4464
            g.obj(addr).routine = 0
            g.obj(addr).init = False
    if o.b39 != 0:
        return
    g.lives = (g.lives - 1) & 0xFF
    if g.lives == 0:
        g.play_sub = 0x10
        return
    g.restore_chirps = 1
    g.save_chirps()                                               # FF1722
    g.state_id = 0x20
    for _ in range(0x3D):
        g.timer_tick()
        yield from g.vblank()


# ---------------------------------------------------------------------------
# Poussin (FF483E)
# ---------------------------------------------------------------------------
def chirp_main(g, o: Obj):
    if o.first():
        o.anim_table = 0x14E22 if o.b3a else 0x14E12
        x, y = g.tile_to_px(o.b3e, o.b3f)
        o.xi = x + 8
        o.yi = y + 0x10
    if g.freeze:
        return
    st = o.state
    if st == 0:
        chirp_idle(g, o)
    elif st == 4:
        yield from chirp_follow(g, o)
    elif st == 8:
        chirp_scatter(g, o)
    else:
        chirp_land(g, o)
    facing_from_vx(o)


def chirp_idle(g, o: Obj):
    """FF48AA"""
    if g.at_door:
        return
    if o.sub_init():
        o.b3b = 0x30
        o.vy = -0x2000
    o.anim = 0
    o.b3b = (o.b3b - 1) & 0xFF
    if o.b3b == 0:
        o.vy = s32(-o.vy)
        o.b3b = 0x30
    p = g.obj(PLAYER)
    if g.collide(o, p):
        g.sfx(0x90)
        o.state = 4
        g.following = (g.following + 1) & 0xFF
        o.b38 = g.following
        g.score_add = 0x10
        g.add_score()
    g.animate(o)
    g.physics(o)


def chirp_follow(g, o: Obj):
    """FF4918"""
    if o.sub_init():
        o.vx = 0
        o.vy = 0
    if g.player_hit:
        o.b38 = 0
        g.following = (g.following - 1) & 0xFF
        o.state = 8
        d1 = 0
        chirp_pose(g, o, d1)
        return
    order = o.b38
    idx = g.d.trail_pos_idx[order]
    px, py = g.trail[idx]
    o.x = px
    o.y = py
    g.screen_x(o)                                                 # FF10BA
    d1 = g.trail_flags[g.d.trail_flag_idx[order]]
    if not g.at_door:
        chirp_enemy_check(g, o)                                   # FF4AF0
    if g.at_door:
        p = g.obj(PLAYER)
        if p.xi == o.xi and p.yi == o.yi:
            g.sfx(0x94)
            o.routine = 0                                         # clr.w (a0)
            o.init = False
            chirp_door_score(g, o)                                # FF4A7C
            g.chirps_left = (g.chirps_left - 1) & 0xFF
            if g.chirps_left == 0:
                g.round_done = 1
                g.frame = 0
                g.time_min = g.t_min
                g.time_sec = g.t_sec
                chirp_time_bonus(g)                               # FF4DD4
            for _ in range(3):
                yield from g.vblank()
            d1 = 0xFFFF          # FF49D0 : d1 sert de compteur de boucle (dbra) -> -1
            o.b38 = 0
            g.following = (g.following - 1) & 0xFF
            if g.following == 0:
                g.at_door = 0
                yield from g.door_anim(g.d.door_close_enter, 1)   # FF1D18
    # FF49F2
    if g.round_done:
        g.at_door = 1
        g.play_sub = 0xC
        if g.reached != 1:
            g.no_bonus = 1
    chirp_pose(g, o, d1)


def chirp_pose(g, o: Obj, d1: int):
    """FF4A12"""
    o.clr_flag(F_XFLIP)
    o.b39 = 0
    if (d1 & 3) == 0:
        o.anim = 0
    else:
        if not (d1 & 1):
            o.set_flag(F_XFLIP)
            o.b39 = 1
        o.anim = 4 if (d1 & 0x80) else 8
    g.animate(o)
    g.screen_x(o)


def chirp_enemy_check(g, o: Obj):
    """FF4AF0 : un ennemi touche un poussin -> dispersion de la file."""
    for addr in ENEMIES[:2]:
        e = g.obj(addr)
        if not (e.hit & 2):
            continue
        if not g.collide(o, e):
            continue
        d0 = o.b38
        for ca in CHIRPS:
            c = g.obj(ca)
            if d0 <= c.b38:
                c.b38 = 0
                g.following = (g.following - 1) & 0xFF
                c.state = 8
        return


def chirp_door_score(g, o: Obj):
    """FF4A7C"""
    order = o.b38
    g.score_add = g.d.chirp_door_scores[order - 1]
    g.add_score()
    pop = g.obj(0xC100 + 0x40 * ((order - 1) & 3))    # table FF4AE0 : C100,C140,C180,C1C0 (x2)
    pop.routine = R_POPUP_DOOR
    pop.init = False
    pop.b3a = order
    pop.xi = g.obj(PLAYER).xi


def chirp_time_bonus(g):
    """FF4DD4"""
    g.time_bonus_val = 0
    if g.time_min != 0:
        return
    v = g.d.time_bonus[(g.time_sec >> 4) & 0xF] if (g.time_sec >> 4) < 6 else 0
    g.time_bonus_val = v
    g.score_add = v
    g.add_score()


def chirp_scatter(g, o: Obj):
    """FF4B42 / FF4C6A"""
    slot = (o.slot - 0xC480) // 0x40
    if o.b3a == 0:
        if o.sub_init():
            o.vx = g.d.scatter_speed0[slot]
            if o.b39:
                o.vx = s32(-o.vx)
            o.anim = 8
        g.physics(o)
        if o.vy == 0:
            x, y = o.xi, o.yi
            y += 1
            if not g.probe(x, y):
                o.vy = s32(o.vy + 0x1000)
                o.anim = 4
            else:
                if o.vx == 0:
                    o.vx = 0
                    o.state = 0xC
                else:
                    if o.b39 == 0:
                        o.vx = s32(o.vx - 0x400)
                    else:
                        o.vx = s32(o.vx + 0x400)
                    y -= 6
                    d0 = 4 if o.vx >= 0 else -4
                    if g.probe(x + d0, y):
                        o.vx = s32(-o.vx)
        else:
            x, y = o.xi, o.yi
            if g.probe(x, y):
                o.vy = 0
                snap_land(o, y)
                o.anim = 8
            else:
                o.vy = s32(o.vy + 0x1000)
                o.anim = 4
    else:
        if o.sub_init():
            o.vx = g.d.scatter_speed1[slot]
            if o.b39:
                o.vx = s32(-o.vx)
            o.anim = 8
        g.physics(o)
        if o.vy == 0:
            x, y = o.xi, o.yi
            y += 1
            if not g.probe(x, y):
                o.vy = s32(o.vy + 0x1000)
                o.anim = 4
            else:
                y -= 6
                d0 = 4 if o.vx >= 0 else -4
                if g.probe(x + d0, y):
                    o.vx = s32(-o.vx)
        else:
            x, y = o.xi, o.yi
            if g.probe(x, y):
                o.vy = 0
                snap_land(o, y)
                o.anim = 8
            else:
                o.vy = s32(o.vy + 0x1000)
                o.anim = 4
    xflip_from_vx(o)
    g.animate(o)
    chirp_player_check(g, o)                                      # FF4D52


def chirp_player_check(g, o: Obj):
    """FF4D52 : le joueur récupère un poussin dispersé."""
    p = g.obj(PLAYER)
    if p.state != 0:
        return
    if g.collide(o, p):
        g.sfx(0x90)
        o.state = 4
        g.following = (g.following + 1) & 0xFF
        o.b38 = g.following


def chirp_land(g, o: Obj):
    """FF4D86"""
    g.physics(o)
    if o.sub_init():
        o.clr_flag(F_ANIMEND)
        o.anim = 0xC
        o.frame = 0
    g.physics(o)
    xflip_from_b39(o)
    g.animate(o)
    if o.has(F_ANIMEND):
        o.clr_flag(F_ANIMEND)
        o.b39 ^= 1
        o.state = 8
    chirp_player_check(g, o)


# ---------------------------------------------------------------------------
# Chat "Tiger" (FF4EC6)
# ---------------------------------------------------------------------------
CAT_STATES = {}


def cat_main(g, o: Obj):
    if o.first():
        x, y = g.tile_to_px(o.b3e, o.b3f)
        o.xi = x + 8
        o.yi = y + 0x10
        o.anim_table = 0x154AE
        o.vx = 0
        o.vy = 0
    if g.freeze or g.at_door or g.player_hit:
        return
    st = o.state
    CAT_STATES[st](g, o)
    st = o.state
    if st != 0x14 and st != 0x1C:
        cat_item_check(g, o)                                      # FF540A
    facing_from_vx(o)


def cat_appear(g, o: Obj):
    """FF4F64"""
    if o.sub_init():
        o.anim = 0
        o.clr_flag(F_ANIMEND)
        o.frame = 0
        o.hit = 6
    g.physics(o)
    g.animate(o)
    if not o.has(F_ANIMEND):
        return
    o.clr_flag(F_ANIMEND)
    o.state = 8
    p = g.obj(PLAYER)
    o.b39 = 0
    if p.xs <= o.xs:
        o.b39 = 1
    if g.timer_word() > 0x30:
        return
    if g.round > 0x31:
        return
    o.b39 = 0
    if o.b16:
        o.b39 = 1


def cat_crouch(g, o: Obj):
    """FF4FD2 : accroupi avant de bondir."""
    if o.sub_init():
        o.hit = 7
        o.vx = 0
        o.b3b = 0x14
        o.frame_ptr = 0x1A918
        xflip_from_b39(o)
    g.physics(o)
    p = g.obj(PLAYER)
    if p.yi != o.yi:
        o.b3a = 2
        o.state = 0xC
        return
    if o.b39 == 0:
        if p.xs > o.xs:
            o.b3a = 1
            o.state = 0xC
        else:
            o.state = 0x10
    else:
        if p.xs < o.xs:
            o.b3a = 1
            o.state = 0xC
        else:
            o.state = 0x10


def cat_walk(g, o: Obj):
    """FF5068"""
    if o.sub_init():
        o.hit = 7
        o.vx = g.cat_speed
        if o.b16:
            o.vx = 0x14000
        if o.b39:
            o.vx = s32(-o.vx)
    g.physics(o)
    x, y = o.xi, o.yi
    y -= 8
    if g.probe(x + (-8 if o.vx < 0 else 8), y):
        o.vx = s32(-o.vx)
    d4 = g.probe_rel(o, 0, 1)
    if not (d4 & 0x80):
        if o.vx < 0:
            if not (d4 & 4):
                o.state = 4
        else:
            if not (d4 & 8):
                o.state = 4
    else:
        go = False
        if o.b39 == 0:
            go = not (d4 & 0x40)
        else:
            go = bool(d4 & 0x40)
        if go:
            p = g.obj(PLAYER)
            if o.yi < p.yi:
                pass
            elif o.yi == p.yi:
                # FF5132 : le joueur est derrière le chat -> demi-tour et bond
                if g.timer_word() > 0x30:
                    if o.b39:
                        if not (p.xs < o.xs):
                            o.state = 0x18
                    else:
                        if not (p.xs > o.xs):
                            o.state = 0x18
            else:
                o.state = 0x18
    xflip_from_vx(o)
    o.anim = 4
    g.animate(o)


def cat_jump(g, o: Obj):
    """FF515A"""
    if o.b3b:
        o.b3b = (o.b3b - 1) & 0xFF
        g.physics(o)
        return
    if o.sub_init():
        o.hit = 7
        d0 = o.b3a
        if d0 == 0:
            o.vx = g.cat_jump_vx
            o.vy = g.cat_jump_vy
        elif d0 == 1:
            o.vx = 0x1A000
            o.vy = -0x10000
        else:
            o.vx = g.run_speed
            o.vy = -0x8000
        if o.b39:
            o.vx = s32(-o.vx)
    o.vy = s32(o.vy + 0x1000)
    g.physics(o)
    x, y = o.xi, o.yi
    if g.probe(x, y):
        o.vy = 0
        snap_land(o, y)
        o.state = 8
    else:
        y -= 8
        if g.probe(x + (-8 if o.vx < 0 else 8), y):
            o.vx = s32(-o.vx)
        elif o.vy < 0:
            x, y = o.xi, o.yi
            if g.probe(x, y - 0xD):
                o.vy = 0
    o.frame_ptr = 0x1A970 if o.vy < 0 else 0x1A97E
    xflip_from_b39(o)


def cat_turn(g, o: Obj):
    """FF5256"""
    if o.b3b:
        o.b3b = (o.b3b - 1) & 0xFF
        g.physics(o)
        return
    if o.sub_init():
        o.hit = 7
        o.clr_flag(F_ANIMEND)
        o.anim = 0xC
        o.frame = 0
    g.physics(o)
    xflip_from_b39(o)
    g.animate(o)
    if o.has(F_ANIMEND):
        o.clr_flag(F_ANIMEND)
        o.b39 ^= 1
        o.state = 8


def cat_hit(g, o: Obj):
    """FF52B4 : touché par un objet."""
    if o.sub_init():
        g.sfx(0x93)
        if o.b16 == 0:
            g.cat_speed = s32(g.cat_speed + 0x1000)
        o.hit = 0
        o.anim = 8
        g.enemies_alive = (g.enemies_alive - 1) & 0xFF
    fling_physics(g, o)
    if o.vx == 0:
        o.state = 0x1C


def cat_ready(g, o: Obj):
    """FF52F6"""
    if o.sub_init():
        o.hit = 7
        o.vx = 0
        o.b3b = 0x14
        o.frame_ptr = 0x1A918
        xflip_from_b39(o)
    g.physics(o)
    p = g.obj(PLAYER)
    if p.yi != o.yi:
        if p.yi > o.yi:
            o.b3a = 2
        else:
            o.b3a = 0
        o.state = 0xC
        return
    if o.b39 == 0:
        if p.xs > o.xs:
            o.b3a = 1
            o.state = 0xC
        else:
            o.state = 0x10
    else:
        if p.xs < o.xs:
            o.b3a = 1
            o.state = 0xC
        else:
            o.state = 0x10


def cat_ko(g, o: Obj):
    """FF53A4"""
    if o.sub_init():
        o.hit = 0
        o.clr_flag(F_ANIMEND)
        o.anim = 0x10
        o.frame = 0
        o.vy = -0x4000
    g.physics(o)
    g.animate(o)
    if not o.has(F_ANIMEND):
        return
    if (g.t_frame & 0xF0) == 0:
        b = g.obj(0xC780 if o.b16 else 0xC740)
        b.xi = o.xi
        b.yi = o.yi
        b.routine = R_BONUS_ITEM
        b.init = False
    o.clear_keep_pos()


def cat_item_check(g, o: Obj):
    """FF540A : un objet lancé touche le chat."""
    for ia in ITEMS:
        it = g.obj(ia)
        if not (it.hit & 8):
            continue
        if not g.collide(o, it):
            continue
        o.state = 0x14
        o.hit = 0
        o.vx = it.vx
        o.vy = it.vy
        it.b3b = (it.b3b + 1) & 0xFF
        g.score_add = g.d.item_hit_scores[min(it.b3b - 1, 3)]
        g.add_score()
        spawn_popup_combo(g, o, it.b3b)
        return


def spawn_popup_combo(g, o: Obj, combo: int):
    """FF545A : popup de score sur C0C0/C080/C040/C000."""
    for addr in (0xC0C0, 0xC080, 0xC040, 0xC000):
        p = g.obj(addr)
        if p.init or (p.routine >> 8) & 0xFF:      # tst.b (a2) : octet haut (bit 7 = initialisé)
            continue
        p.routine = R_POPUP_COMBO
        p.init = False
        p.b3a = combo
        p.xi = o.xi
        p.yi = o.yi - 8
        return


CAT_STATES.update({0: cat_appear, 4: cat_crouch, 8: cat_walk, 0xC: cat_jump, 0x10: cat_turn,
                   0x14: cat_hit, 0x18: cat_ready, 0x1C: cat_ko})


# ---------------------------------------------------------------------------
# Lézard "Iggy" (FF5D58)
# ---------------------------------------------------------------------------
def lizard_main(g, o: Obj):
    if o.first():
        x, y = g.tile_to_px(o.b3e, o.b3f)
        o.xi = x + 8
        o.yi = y + 0x10
        o.anim_table = 0x162BC
        o.vx = 0
        o.vy = 0
    if g.freeze or g.at_door or g.player_hit:
        return
    st = o.state
    if st == 0:
        lizard_appear(g, o)
    elif st == 4:
        lizard_crawl(g, o)
    elif st == 8:
        lizard_hop(g, o)
    elif st == 0xC:
        lizard_hit(g, o)
    else:
        lizard_ko(g, o)
    st = o.state
    if st != 0xC and st != 0x10:
        lizard_item_check(g, o)                                   # FF6218


def lizard_appear(g, o: Obj):
    """FF5DD6"""
    if o.sub_init():
        o.hit = 4
        o.frame_ptr = 0x1AB74
        o.b3b = 0xA
    g.physics(o)
    o.b3b = (o.b3b - 1) & 0xFF
    if o.b3b == 0:
        o.state = 4


def lizard_crawl(g, o: Obj):
    """FF5E04 : rampe le long des surfaces (+3A = direction)."""
    if o.sub_init():
        o.hit = 5
    d = o.b3a & 7
    spd = g.lizard_speed
    if d == 0:
        # FF5E40 : vers la droite sur le sol
        o.anim = 0
        o.clr_flag(F_XFLIP)
        o.vx = spd
        o.vy = 0
        g.physics(o)
        x, y = o.xi, o.yi
        if not g.probe(x, y):
            o.b3a = 6
            o.x = set_hi(o.x, (x & 0xFFF8) - 1)
            o.x = clr_lo(o.x)
            o.frame_ptr = 0x1AC04
            return
        if g.probe(x + 4, y - 4):
            o.b3a = 5
            o.x = set_hi(o.x, (x + 4) & 0xFFF8)          # d7 = x+4 (FF5EA8)
            o.x = clr_lo(o.x)
            o.xs = (o.xs + 4) & 0xFFFF
            o.y = set_hi(o.y, ((y - 4) & 0xFFF8) + 7)    # d6 = y-4
            o.y = clr_lo(o.y)
            o.frame_ptr = 0x1ABCC
            return
        if g.probe_rel(o, 0, -4):
            o.state = 8
            o.frame_ptr = 0x1AC4C
            return
        g.animate(o)
    elif d in (1, 2, 3):
        # FF5EE6 : vers la gauche (plafond)
        o.anim = 4
        o.set_flag(F_XFLIP)
        o.vx = s32(-spd)
        o.vy = 0
        g.physics(o)
        x, y = o.xi, o.yi
        if not g.probe(x, y):
            o.b3a = 5
            o.x = set_hi(o.x, (x & 0xFFF8) + 8)
            o.x = clr_lo(o.x)
            o.frame_ptr = 0x1AC20
            o.clr_flag(F_XFLIP)
            return
        if g.probe(x - 4, y + 4):
            o.b3a = 6
            o.x = set_hi(o.x, ((x - 4) & 0xFFF8) + 7)    # d7 = x-4 (FF5F5A)
            o.x = clr_lo(o.x)
            o.xs = (o.xs - 4) & 0xFFFF
            o.y = set_hi(o.y, (y + 4) & 0xFFF8)          # d6 = y+4
            o.y = clr_lo(o.y)
            o.frame_ptr = 0x1ABE8
            o.clr_flag(F_XFLIP)
            return
        if g.probe_rel(o, 0, 4):
            o.state = 8
            o.frame_ptr = 0x1AC64
            return
        g.animate(o)
    elif d in (4, 5):
        # FF5F9E : monte
        o.anim = 8
        o.clr_flag(F_XFLIP)
        o.vx = 0
        o.vy = s32(-spd)
        g.physics(o)
        x, y = o.xi, o.yi
        if not g.probe(x, y):
            o.b3a = 0
            o.y = set_hi(o.y, (y & 0xFFF8) + 8)
            o.y = clr_lo(o.y)
            o.frame_ptr = 0x1AC2E
            o.clr_flag(F_XFLIP)
            return
        if g.probe(x - 4, y - 4):
            o.b3a = 3
            o.x = set_hi(o.x, ((x - 4) & 0xFFF8) + 7)    # FF6004 : coordonnées de sonde
            o.x = clr_lo(o.x)
            o.y = set_hi(o.y, ((y - 4) & 0xFFF8) + 7)
            o.y = clr_lo(o.y)
            o.frame_ptr = 0x1ABDA
            o.clr_flag(F_XFLIP)
            return
        g.animate(o)
    elif d == 6:
        # FF6036 : descend
        o.anim = 0xC
        o.set_flag(F_XFLIP)
        o.vx = 0
        o.vy = spd
        g.physics(o)
        x, y = o.xi, o.yi
        if not g.probe(x, y):
            o.b3a = 3
            o.y = set_hi(o.y, (y & 0xFFF8) - 1)
            o.y = clr_lo(o.y)
            o.frame_ptr = 0x1AC12
            o.clr_flag(F_XFLIP)
            return
        if g.probe(x + 4, y + 4):
            o.b3a = 0
            o.x = set_hi(o.x, (x + 4) & 0xFFF8)          # FF609A : coordonnées de sonde
            o.x = clr_lo(o.x)
            o.y = set_hi(o.y, (y + 4) & 0xFFF8)
            o.y = clr_lo(o.y)
            o.frame_ptr = 0x1ABF6
            o.clr_flag(F_XFLIP)
            return
        g.animate(o)
    else:
        lizard_hop(g, o)


def lizard_hop(g, o: Obj):
    """FF60C8 : transit vertical entre plateformes."""
    if o.sub_init():
        o.hit = 5
    spd = g.lizard_speed
    if not (o.b3a & 2):
        o.anim = 0x10
        o.vx = 0
        o.vy = s32(-spd)
        g.physics(o)
        x, y = o.xi, o.yi
        y -= 8
        if not g.probe(x, y):
            g.animate(o)
            return
        o.state = 4
        o.b3a ^= 3
        o.y = set_hi(o.y, (y & 0xFFF8) + 7)
        o.y = clr_lo(o.y)
        o.frame_ptr = 0x1AC64
    else:
        o.anim = 0x14
        o.vx = 0
        o.vy = spd
        g.physics(o)
        x, y = o.xi, o.yi
        y += 8
        if not g.probe(x, y):
            g.animate(o)
            return
        o.state = 4
        o.b3a ^= 3
        o.y = set_hi(o.y, y & 0xFFF8)
        o.y = clr_lo(o.y)
        o.frame_ptr = 0x1AC4C


def lizard_hit(g, o: Obj):
    """FF6188"""
    if o.sub_init():
        g.sfx(0x93)
        o.anim = 0x18
        g.enemies_alive = (g.enemies_alive - 1) & 0xFF
        o.hit = 0
    fling_physics(g, o)
    if o.vx == 0:
        o.state = 0x10


def lizard_ko(g, o: Obj):
    """FF61BC"""
    if o.sub_init():
        o.clr_flag(F_ANIMEND)
        o.anim = 0x1C
        o.frame = 0
        o.vy = -0x4000
        o.hit = 0
    g.physics(o)
    g.animate(o)
    if not o.has(F_ANIMEND):
        return
    if (g.t_frame & 0xF0) == 0:
        b = g.obj(0xC7C0)
        b.xi = o.xi
        b.yi = o.yi
        b.routine = R_BONUS_ITEM
        b.init = False
    o.clear_keep_pos()


def lizard_item_check(g, o: Obj):
    """FF6218"""
    for ia in ITEMS:
        it = g.obj(ia)
        if not (it.hit & 0x10):
            continue
        if not g.collide(o, it):
            continue
        o.state = 0xC
        o.hit = 0
        o.vx = it.vx
        o.vy = it.vy
        it.b3b = (it.b3b + 1) & 0xFF
        g.score_add = g.d.item_hit_scores_liz[min(it.b3b - 1, 3)]
        g.add_score()
        spawn_popup_combo(g, o, it.b3b)
        return


# ---------------------------------------------------------------------------
# Objet lançable (FF452E)
# ---------------------------------------------------------------------------
def item_main(g, o: Obj):
    if o.first():
        o.frame_ptr = g.item_frame
        o.pal = 0x60
        x, y = g.tile_to_px(o.b3e, o.b3f)
        o.xi = x + 8
        o.yi = y + 8
    if g.freeze or g.at_door or g.player_hit:
        return
    st = o.state
    if st == 0:
        item_ground(g, o)
    elif st == 4:
        item_carried(g, o)
    else:
        item_thrown(g, o)


def item_ground(g, o: Obj):
    """FF4588"""
    o.hit = 1
    p = g.obj(PLAYER)
    if p.vy >= 0 and g.collide(o, p) and p.b3b == 0:
        o.state = 4
        p.b3b = 1
        g.held_item = o
    g.physics(o)


def item_carried(g, o: Obj):
    """FF45BC"""
    if o.sub_init():
        g.sfx(0x92)
    o.hit = 0
    p = g.obj(PLAYER)
    x, y = p.x, p.y
    if p.b38:
        y = s32(y + 0x60000)
    elif p.b39 == 0:
        x = s32(x + 0x80000)
    else:
        x = s32(x - 0x80000)
    o.x = x
    o.y = y
    g.physics(o)


def item_thrown(g, o: Obj):
    """FF4610"""
    if o.sub_init():
        g.sfx(0x96)
        o.hit = 0x18
        o.anim_table = 0x14730
        o.b3b = 0
        d0 = g.round
        while d0 > 0xF:
            d0 -= 0xF
        o.anim = ((d0 - 1) & 0xFF) * 4
    fling_physics(g, o)
    if o.vx == 0:
        o.routine = 0
        o.init = False
    # FF4662 : trop loin du joueur -> disparaît
    p = g.obj(PLAYER)
    d5 = (p.xs - o.xs) & 0xFFFF
    d6 = (o.xs - p.xs) & 0xFFFF
    d5 = d5 - 0x10000 if d5 & 0x8000 else d5
    d6 = d6 - 0x10000 if d6 & 0x8000 else d6
    if d5 >= 0x7C or d6 >= 0x7C:
        o.routine = 0
        o.init = False


# ---------------------------------------------------------------------------
# Apparition d'un ennemi (FF6312)
# ---------------------------------------------------------------------------
def spawner_main(g, o: Obj):
    if o.first():
        x, y = g.tile_to_px(o.b3e, o.b3f)
        o.xi = x + 8
        o.yi = y + 0x10
        if g.enemies_alive:
            o.w38 = g.spawn_delay & 0xFFFF
    o.anim_table = 0x163E0
    if g.at_door or g.freeze:
        return
    if o.state == 0:
        if o.sub_init():
            g.enemies_alive = (g.enemies_alive + 1) & 0xFF
            o.set_flag(F_HIDDEN)
        g.physics(o)
        if o.w38 == 0:
            o.clr_flag(F_HIDDEN)
            o.state = 4
        else:
            o.w38 -= 1
    else:
        if o.sub_init():
            o.clr_flag(F_ANIMEND)
            o.frame = 0
            o.anim = 0
        g.physics(o)
        g.animate(o)
        if o.has(F_ANIMEND):
            o.clr_flag(F_ANIMEND)
            e = g.obj(o.slot - 0x300)
            e.routine = R_LIZARD if o.b16 == 2 else R_CAT
            e.init = False
            e.b16 = o.b16
            o.clear_keep_pos()


# ---------------------------------------------------------------------------
# Popups de score et objet bonus
# ---------------------------------------------------------------------------
def popup_combo_main(g, o: Obj):
    """FF6422"""
    if o.first():
        o.frame_ptr = g.d.popup_combo[min((o.b3a - 1) & 0xFF, 2)]
        o.w38 = 0x3C
    g.physics(o)
    o.w38 -= 1
    if o.w38 == 0:
        o.routine = 0
        o.init = False


def popup_door_main(g, o: Obj):
    """FF6456"""
    if o.first():
        idx = (o.b3a - 1) & 0xFF
        o.frame_ptr = g.d.popup_door[idx & 7]
        d0 = idx * 8            # lsl #1 puis lsl #2
        d6 = g.door_y
        if d6 >= 0xF0:
            d6 = d6 - d0 - 0x18
        else:
            d6 = d6 + d0 + 8
        o.yi = d6
        o.w38 = 0x1E
    g.physics(o)
    o.w38 -= 1
    if o.w38 == 0:
        o.routine = 0
        o.init = False


def popup_bonus_main(g, o: Obj):
    """FF64AE"""
    if o.first():
        o.frame_ptr = g.d.popup_bonus[min(o.b3a, 8)]
        o.w38 = 0x3C
    g.physics(o)
    o.w38 -= 1
    if o.w38 == 0:
        o.routine = 0
        o.init = False


def bonus_item_main(g, o: Obj):
    """FF64EC : objet lâché par un ennemi KO."""
    if o.first():
        o.hit = 0
        o.vx = 0
        o.vy = 0
        o.yi = o.yi + 7
        o.anim_table = 0x165AC
        o.anim = 0
        o.w38 = 0x12C
        o.clr_flag(F_XFLIP)
    g.physics(o)
    g.animate(o)
    p = g.obj(PLAYER)
    if g.collide(o, p):
        g.sfx(0x98)
        for addr in (0xC0C0, 0xC080, 0xC040, 0xC000):
            pp = g.obj(addr)
            if pp.routine:
                continue
            pp.xi = o.xi
            pp.yi = o.yi - 8
            pp.b3a = g.following
            pp.routine = R_POPUP_BONUS
            pp.init = False
            g.score_add = g.d.bonus_item_scores[min(g.following, 8)]
            g.add_score()
            o.clear_keep_pos()
            return
    o.w38 -= 1
    if o.w38 == 0:
        o.clear_keep_pos()


# ---------------------------------------------------------------------------
# Objet drapeau de fin de round (FF44DC) et textes-sprites
# ---------------------------------------------------------------------------
def flag_main(g, o: Obj):
    if o.first():
        x, y = g.tile_to_px(g.block_pos[4], g.block_pos[5])
        o.xi = x + 8
        o.yi = y + 0x18
        o.anim_table = 0x14524
    if o.state == 0:
        g.animate(o)
    g.physics(o)


def gameover_main(g, o: Obj):
    """FF6DAA"""
    if o.first():
        o.xs = 0xD8
        o.yi = 0x118
        o.frame_ptr = 0x1ACA4
        g.freeze = 1


def pause_main(g, o: Obj):
    """FF6DCC"""
    if o.first():
        o.frame_ptr = 0x1AD32
        o.xs = 0xF0
        o.yi = 0x108


# ---------------------------------------------------------------------------
# Stage bonus
# ---------------------------------------------------------------------------
def net_main(g, o: Obj):
    """FF6648 : filet suivant Flicky (C580)."""
    p = g.obj(0xC580)
    o.x = p.x
    o.y = p.y
    o.yi = o.yi + 0xA
    if p.b39:
        o.clr_flag(F_XFLIP)
        o.xi = o.xi - 8
    else:
        o.set_flag(F_XFLIP)
        o.xi = o.xi + 8
    g.physics(o)
    o.frame_ptr = 0x1AAE4 if p.vx else 0x1AAD6


def bcat_left_main(g, o: Obj):
    """FF65BA"""
    if o.first():
        o.xi = 0x140
        o.clr_flag(F_XFLIP)
        if o.b16:
            o.xi = 0xC0
            o.set_flag(F_XFLIP)
        o.yi = 0x150
        o.anim_table = 0x1669A
        o.anim = 0
    if not g.freeze:
        g.physics(o)
        g.animate(o)


def bcat_right_main(g, o: Obj):
    """FF6600"""
    if o.first():
        o.xi = 0x130
        o.clr_flag(F_XFLIP)
        if o.b16:
            o.xi = 0xD0
            o.set_flag(F_XFLIP)
        o.yi = 0x150
        o.anim_table = 0x1669A
        o.anim = 4
    if not g.freeze:
        g.physics(o)
        g.animate(o)


def bchirp_main(g, o: Obj):
    """FF66C6 : poussin lancé par les chats dans le stage bonus."""
    r = g.rom
    if o.first():
        o.set_flag(F_HIDDEN)
        o.anim_table = 0x14E12
        o.w3a = r.u16(g.bonus_delays_ptr + 2 * o.b38)
    st = o.state
    if st == 0:
        bchirp_wait(g, o)
    elif st == 4:
        bchirp_fly(g, o)
    else:
        bchirp_fall(g, o)
    g.animate(o)


def bchirp_wait(g, o: Obj):
    """FF6708"""
    if o.w3a:
        o.w3a -= 1
        g.physics(o)
        return
    if o.sub_init():
        o.clr_flag(F_HIDDEN)
        o.anim = 4
        o.yi = 0x150
        o.xi = 0x80
        o.vx = 0x8000
        o.clr_flag(F_XFLIP)
        if o.b39:
            o.xi = 0x17F
            o.vx = -0x8000
            o.set_flag(F_XFLIP)
    g.physics(o)
    cat = g.obj(0xC640 if o.b39 else 0xC680)
    if g.collide(o, cat):
        o.state = 4


def bchirp_load_script(g, o: Obj):
    """FF6892"""
    r = g.rom
    k = r.u8(g.bonus_script_ptr + o.b38)
    script = g.d.bonus_scripts[k]
    e = script + 4 * o.b3e
    o.w3a = r.u16(e)
    d7 = r.s8(e + 2) << 8
    d6 = r.s8(e + 3) << 12
    if o.b39:
        d7 = -d7
        d6 = -d6
    o.l18 = s32(d7)
    o.l1c = s32(d6)


def bchirp_script_step(g, o: Obj):
    """FF6854"""
    while True:
        d0 = o.w3a
        if d0 == 0xFFFF:
            return
        d0 -= 1
        if d0 == 0:
            o.b3e = (o.b3e + 1) & 0xFF
            bchirp_load_script(g, o)
            continue
        o.w3a = d0
        d7 = o.vx
        d6 = o.l1c
        if d6 >= 0:
            if d7 < d6:
                d7 = s32(d7 + o.l18)
        else:
            if d7 > d6:
                d7 = s32(d7 + o.l18)
        o.vx = d7
        return


def bchirp_fly(g, o: Obj):
    """FF6782"""
    r = g.rom
    if o.sub_init():
        a = g.bonus_launch_ptr + 2 * o.b38
        d7 = r.s8(a) << 12
        d6 = r.s8(a + 1) << 12
        o.vx = s32(d7)
        o.vy = s32(d6)
        bchirp_load_script(g, o)
    o.vy = s32(o.vy + 0x1000)
    if o.vy == 0:
        o.state = 8
    bchirp_script_step(g, o)
    g.physics(o)
    g.animate(o)                 # FF67D0 (en plus de FF66F6)


def bchirp_fall(g, o: Obj):
    """FF67D6"""
    if o.sub_init():
        o.anim = 0
        d7 = o.vx
        if d7 < 0:
            d7 = -((-d7) >> 1)
        else:
            d7 >>= 1
        o.vx = s32(d7)
        if o.w3a != 0xFFFF:
            o.b3e = (o.b3e + 1) & 0xFF
            bchirp_load_script(g, o)
    if o.vy <= 0x18000:
        o.vy = s32(o.vy + 0x400)
    bchirp_script_step(g, o)
    g.physics(o)
    # FF68E2 : attrapé par le filet ?
    net = g.obj(0xC040)
    if g.collide(o, net):
        g.sfx(0x90)
        o.clear()
        g.chirps_left = (g.chirps_left - 1) & 0xFF
        g.bonus_caught = (g.bonus_caught + 1) & 0xFF
        g.bonus_caught_bcd = bcd_add8(g.bonus_caught_bcd, 1)
        g.draw_bonus_count()                                      # FF69D4
    elif o.yi >= 0x180:
        o.clear()
        g.chirps_left = (g.chirps_left - 1) & 0xFF
    g.animate(o)                 # FF6834 (même sur un objet effacé)
    if g.chirps_left == 0:
        g.frame = 0
        g.round_done = 1
        g.bonus_sub = 4
        g.bonus_final_score()                                     # FF6988


def bcd_add8(a: int, b: int) -> int:
    """abcd sur un octet."""
    lo = (a & 0xF) + (b & 0xF)
    hi_ = (a >> 4) + (b >> 4)
    if lo > 9:
        lo -= 10
        hi_ += 1
    if hi_ > 9:
        hi_ -= 10
    return ((hi_ & 0xF) << 4) | lo


# ---------------------------------------------------------------------------
# Écran titre / instructions / fin
# ---------------------------------------------------------------------------
def title_cast_main(g, o: Obj):
    """FF2172 : les 4 personnages du titre."""
    if o.first():
        o.set_flag(F_XFLIP)
        i = o.w38
        o.anim = g.d.title_anim_ids[i]
        o.anim_table = g.d.title_anim_tables[i]
        o.xs = g.d.title_pos[i][0]
        o.yi = g.d.title_pos[i][1]
    g.animate(o)


def push_start_main(g, o: Obj):
    """FF21CC : PUSH START BUTTON clignotant."""
    if o.first():
        o.frame_ptr = 0x1ACDC
        o.xs = 0xF0
        o.yi = 0x120
    if o.state == 0:
        if o.sub_init():
            o.clr_flag(F_HIDDEN)
            o.w3a = 0x3C
        o.w3a -= 1
        if o.w3a == 0:
            o.state = 4
    else:
        if o.sub_init():
            o.set_flag(F_HIDDEN)
            o.w3a = 0x14
        o.w3a -= 1
        if o.w3a == 0:
            o.state = 0


def title_letter_main(g, o: Obj):
    """FF223E : lettres FLICKY."""
    if o.first():
        f, x, y = g.d.title_letters[o.w38]
        o.frame_ptr = f
        o.xs = x
        o.yi = y


def instr_main(g, o: Obj):
    """FF2476 : sprites de l'écran d'instructions."""
    if o.first():
        i = o.w38
        o.clr_flag(F_XFLIP)
        if g.d.instr_flip[i]:
            o.set_flag(F_XFLIP)
        o.frame_ptr = g.d.instr_frames[i]
        o.xs, y = g.d.instr_pos[i]
        o.yi = y


def ending_main(g, o: Obj):
    """FF34BC : personnages défilant dans la fin."""
    if o.first():
        o.set_flag(F_HIDDEN)
        i = o.w38
        o.b3a = g.d.ending_thresholds[i]
        o.anim = g.d.ending_anim_ids[i]
        o.anim_table = g.d.ending_anims[i]
    if o.state == 0:
        if g.credit_line == o.b3a:
            o.state = 4
    else:
        if o.sub_init():
            o.xi = 0xE4
            o.yi = 0x178
            o.vy = -0x4000
            o.clr_flag(F_HIDDEN)
        g.physics(o)
        if o.yi <= 0x78:
            o.clear()
        g.animate(o)


HANDLERS = {
    R_ITEM: item_main, R_CHIRP: chirp_main, R_PLAYER: player_main, R_CAT: cat_main,
    R_LIZARD: lizard_main, R_SPAWNER: spawner_main, R_POPUP_COMBO: popup_combo_main,
    R_POPUP_DOOR: popup_door_main, R_POPUP_BONUS: popup_bonus_main, R_BONUS_ITEM: bonus_item_main,
    R_NET: net_main, R_BCAT_L: bcat_left_main, R_BCAT_R: bcat_right_main, R_BCHIRP: bchirp_main,
    R_GAMEOVER: gameover_main, R_TITLE_CAST: title_cast_main, R_PUSH_START: push_start_main,
    R_TITLE_LETTER: title_letter_main, R_INSTR: instr_main, R_ENDING: ending_main,
    R_FLAG: flag_main, R_PAUSE: pause_main,
}
GENERATORS = {R_CHIRP, R_PLAYER}   # handlers qui peuvent bloquer (yield)
