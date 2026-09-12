"""Lance le jeu : python -m flicky [chemin/vers/rom]

Touches : flèches = déplacement, Z/X/C ou Espace = saut/lancer, Entrée = Start,
          Échap = quitter, F1 = ralenti, F2 = accéléré.
"""
import sys
import time

import pygame

from .game import Game
from .objects import PAD_UP, PAD_DOWN, PAD_LEFT, PAD_RIGHT, PAD_A, PAD_B, PAD_C, PAD_START
from .render import Renderer


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    rom = argv[0] if argv else None
    pygame.init()
    g = Game(rom)
    r = Renderer(g, scale=3)
    clock = pygame.time.Clock()
    fps = 60
    running = True
    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif ev.key == pygame.K_F1:
                    fps = 15
                elif ev.key == pygame.K_F2:
                    fps = 240
                elif ev.key == pygame.K_F3:
                    fps = 60
        k = pygame.key.get_pressed()
        pad = 0
        if k[pygame.K_UP]: pad |= PAD_UP
        if k[pygame.K_DOWN]: pad |= PAD_DOWN
        if k[pygame.K_LEFT]: pad |= PAD_LEFT
        if k[pygame.K_RIGHT]: pad |= PAD_RIGHT
        if k[pygame.K_z] or k[pygame.K_SPACE]: pad |= PAD_A
        if k[pygame.K_x]: pad |= PAD_B
        if k[pygame.K_c]: pad |= PAD_C
        if k[pygame.K_RETURN]: pad |= PAD_START
        g.step(pad)
        r.render()
        clock.tick(fps)
    pygame.quit()


if __name__ == "__main__":
    main()
