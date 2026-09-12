# Flicky — port Python (étape 1 vers une version Cairo/Starknet)

Réimplémentation en Python de la logique du jeu **Flicky** (Sega Mega Drive, 1991),
obtenue par désassemblage de la ROM.

* `disasm/` : outils et notes de rétro-ingénierie (`tools/disasm.py` produit
  `disasm/flicky.asm`, `disasm/NOTES.md` décrit la mémoire, les objets et les
  états).
* `flicky/rom.py` : lecture de la ROM (décompression Nemesis, palettes, font,
  mappings de sprites, animations, données des 48 niveaux).
* `flicky/data.py` : tables constantes extraites de la ROM.
* `flicky/obj.py`, `flicky/objects.py` : objets (joueur, poussins, chats,
  lézards, objets lançables, popups, stage bonus, écrans).
* `flicky/game.py` : machine à états (titre, instructions, choix du round,
  rounds, stage bonus, fin, démo), niveau, HUD, score, timer.
* `flicky/render.py`, `flicky/__main__.py` : affichage pygame et clavier.

La ROM n'est pas incluse : placez `Flicky (USA, Europe).md` à la racine (ou
définissez `FLICKY_ROM`). Les graphismes et données de niveaux sont lus dans la
ROM à l'exécution ; le dépôt ne contient que la logique réécrite.

```bash
python3 -m venv .venv && .venv/bin/pip install pygame capstone pytest
.venv/bin/python -m flicky            # jouer
.venv/bin/python tools/headless.py    # exécution sans affichage
.venv/bin/python -m pytest tests      # tests
```

Le jeu est entièrement déterministe (aucun générateur aléatoire n'est utilisé
par le code original) : une suite d'entrées manette frame par frame reproduit
exactement une partie, ce qui est la base de la future vérification on-chain.

## Validation contre la ROM

`tools/m68k.py` est un petit interpréteur 68000 qui exécute le vrai code de la
ROM (VDP et son en stubs). `tools/harness.py` fait tourner la ROM et le port en
parallèle avec les mêmes entrées et compare à chaque frame les 32 objets
(position 16.16, vitesses, états, animations) et les variables globales (score,
timer, caméra, compteurs). Les quatre démos intégrées, une partie complète
(rounds, bonus, pause, vie supplémentaire, game over) et la fin du jeu sont
identiques bit à bit :

```bash
.venv/bin/python tools/compare.py --demo --demo-index 1 --skip-title --frames 4000
.venv/bin/python tools/scenario.py
.venv/bin/python tools/scenario_ending.py
```

Non porté : le son (les commandes sont journalisées dans `Game.sound_log`),
l'écran SEGA animé, et les variantes PAL / console japonaise (textes).
