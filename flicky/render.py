"""Rendu pygame : plans A/B (32x32 tuiles, défilement horizontal), sprites VDP
et palette. Les tuiles proviennent de la VRAM reconstituée par Game (art lu
dans la ROM de l'utilisateur)."""
from __future__ import annotations

from typing import Dict, Tuple

import pygame

from .game import Game, SCREEN_W, SCREEN_H
from .obj import hi
from .rom import vdp_color_to_rgb


class Renderer:
    def __init__(self, game: Game, scale: int = 3):
        self.g = game
        self.scale = scale
        self.screen = pygame.display.set_mode((SCREEN_W * scale, SCREEN_H * scale))
        pygame.display.set_caption("Flicky (port Python)")
        self.frame_surf = pygame.Surface((SCREEN_W, SCREEN_H))
        self.tile_cache: Dict[Tuple[int, int, int], pygame.Surface] = {}
        self.pal_key = None
        self.rgb = [(0, 0, 0)] * 64

    def update_palette(self):
        g = self.g
        key = (tuple(g.palette), g.fade_level)
        if key == self.pal_key:
            return
        self.pal_key = key
        self.tile_cache.clear()
        lv = g.fade_level
        out = []
        for i, c in enumerate(g.palette):
            if lv < 0x40:
                # sys52 : chaque composante * lv / 64
                r = ((c & 0xE) * lv) >> 6
                gg = (((c >> 4) & 0xE) * lv) >> 6
                b = (((c >> 8) & 0xE) * lv) >> 6
                c = (b << 8) | (gg << 4) | r
            out.append(vdp_color_to_rgb(c))
        self.rgb = out

    def tile(self, index: int, pal_line: int, hflip: bool, vflip: bool) -> pygame.Surface:
        key = (index, pal_line, (hflip << 1) | vflip)
        s = self.tile_cache.get(key)
        if s is not None:
            return s
        s = pygame.Surface((8, 8))
        s.set_colorkey((1, 2, 3))
        vram = self.g.vram
        base = index * 32
        for y in range(8):
            for x in range(4):
                b = vram[base + y * 4 + x]
                for k, c in ((0, b >> 4), (1, b & 0xF)):
                    px = x * 2 + k
                    if c == 0:
                        col = (1, 2, 3)
                    else:
                        col = self.rgb[pal_line * 16 + c]
                        if col == (1, 2, 3):
                            col = (1, 2, 4)
                    s.set_at((px, y), col)
        if hflip or vflip:
            s = pygame.transform.flip(s, hflip, vflip)
            s.set_colorkey((1, 2, 3))
        self.tile_cache[key] = s
        return s

    def draw_sprites(self, prio: bool):
        surf = self.frame_surf
        for (y, size, pat, x) in reversed(self.g.sprites):
            if bool(pat >> 15) != prio:
                continue
            w = ((size >> 2) & 3) + 1
            h = (size & 3) + 1
            idx = pat & 0x7FF
            pal = (pat >> 13) & 3
            hf = bool(pat & 0x800)
            vf = bool(pat & 0x1000)
            sx = (x & 0x1FF) - 0x80
            sy = (y & 0x1FF) - 0x80
            for i in range(w):
                for j in range(h):
                    t = self.tile(idx + i * h + j, pal, hf, vf)
                    dx = (w - 1 - i) if hf else i
                    dy = (h - 1 - j) if vf else j
                    surf.blit(t, (sx + dx * 8, sy + dy * 8))

    def render(self):
        g = self.g
        self.update_palette()
        self.frame_surf.fill(self.rgb[0])
        if g.display_on:
            camx = -hi(g.camx) & 0xFFFF
            xs = camx if camx < 0x8000 else camx - 0x10000
            camy = hi(g.camy) & 0xFF
            rows_a = set(range(2, 26))
            rows_b = set(range(0, 28))
            # ordre VDP : B basse prio, A basse prio, sprites basse prio, B haute, A haute, sprites haute
            self.draw_plane_simple(g.plane_b, rows_b, xs, 0, False)
            self.draw_plane_simple(g.plane_a, rows_a, xs, camy, False)
            self.draw_sprites(False)
            self.draw_plane_simple(g.plane_b, rows_b, xs, 0, True)
            self.draw_plane_simple(g.plane_a, rows_a, xs, camy, True)
            self.draw_sprites(True)
        pygame.transform.scale(self.frame_surf, self.screen.get_size(), self.screen)
        pygame.display.flip()

    def draw_plane_simple(self, plane, scroll_rows, xscroll: int, yscroll: int, prio: bool):
        surf = self.frame_surf
        for row in range(29):
            ry = (row + (yscroll >> 3)) & 0x1F
            dy = -(yscroll & 7)
            sx = xscroll if row in scroll_rows else 0
            fine = sx & 7
            for col in range(-1, 33):
                cx = (col - (sx >> 3)) & 0x1F
                w = plane[ry][cx]
                if (w >> 15) != prio:
                    continue
                idx = w & 0x7FF
                if idx == 0:
                    continue
                t = self.tile(idx, (w >> 13) & 3, bool(w & 0x800), bool(w & 0x1000))
                surf.blit(t, (col * 8 + fine, row * 8 + dy))
