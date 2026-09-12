# Flicky (Mega Drive) — notes de rétro-ingénierie

## Mémoire
- ROM 0x00000-0x0FFFF : bibliothèque résidente (VDP, DMA, Nemesis, pad, son). Table d'appels système à ROM 0x22FC (58 mots) -> stubs `jmp` en RAM 0xFFFA70+6n.
- ROM 0x10000-0x1BFFF : code + données du jeu, copié en RAM 0xFF0000 (exécuté en RAM). Les données sont référencées via adresses ROM 0x1xxxx.
- ROM 0x1C000-0x1FFFF : padding 0xFF.
- Mode vidéo H32 : écran 256x224. Le monde fait 256 px de large et boucle (x ∈ [0x80,0x180)).

## Syscalls utiles
- sys3 (0xAD4) Nemesis -> VRAM ; sys4 (0xAE6) Nemesis -> RAM
- sys5 (0xCC0) copie tiles/plane ; sys14/15 DMA ; sys47 (0xF10) set VRAM addr
- sys27 (0xDC0) lecture manettes ; sys38 (0x10A6) chargement Z80 (son) ; sys32/33/34 son

## Variables RAM (préfixe 0xFF....)
- ffc0.w : état de jeu (index*4), dispatch table FF0084 :
  0 FF1FB0, 1 FF2122, 2 FF228E, 3 FF22E0, 4 FF25BE, 5 FF25F2, 6 FF2656, 7 FF266E,
  8 FF2A94, 9 FF2B46, 10 FF2F30, 11 FF2FDC, 12 FF3110, 13 FF3162, 14 FF39A2, 15 FF3A18, 16 jmp $46e, 17 jmp $4dc
- ff92.w : compteur de frames global ; ff96.w : flag vblank (bits 2-3 -> action vint)
- ffa8.l : caméra x (16.16) ; ffa4.l : caméra y ; d004/d008 : vitesse caméra
- ff71.b : bits registre VDP #1 (display on/off)
- f7e0 : table sprites (buffer), f860 : copie précédente
- d000.w : ptr sprite courant ; d002.w : n° sprite (link)
- d00c.b, d00d.b : flags temp
- d24e.b : mode "objets alternatifs" (rendu C440/C200/C480/C000 vs C580/C040/C5C0)
- d280.b : compteur de palette ; d884.w : offset tile HUD
- d82d.b : numéro de round ; d82e/d82f : position (x,y) tuile de la porte ? (utilisé pour dessiner 3x? tiles à e000 ...)
- d830.. : autres pos
- d883.b : nombre d'ennemis du round
- d888/d889/d88a : timer BCD (minutes? centièmes 0-59)
- d87e.l : score (BCD 8 chiffres) ; d266.. : incrément score BCD ; cc00.l : high score
- d2a4.b/d2a2.w : pause/hit-stop ? (30 frames)
- d2a5.b : flag "pas de score" (démo ?)

## Objets : 32 slots de 0x40 octets à 0xFFC000 (C000..C7FF)
- C000 : joueur (Flicky) ; C040..C1FF : 7 slots (bonus/objets lancés ?) ; C200..C37F : 6 poussins (routine 4)
- C380..C47F ? ; C480..C7FF : 14 ennemis (routine 8) ; C440, C580, C5C0 spéciaux
- +00.w routine (0 = libre ; &0x7FFC index table FF12B0)
- +02.b flags : bit0 = pas de physique, bit1 = invisible, bit2 = anim terminée, bit7 = flip X
- +04.b piece courante (mapping) ; +06.w anim id ; +08.l table d'anims ; +0C.l frame courante
- +10.b frame index ; +11.b timer frame ; +13.b bits palette/priorité
- +20.w x écran (x - cam, wrap [0x80,0x180)) ; +24.l y (16.16) ; +2C.l vy ; +30.l x (16.16) ; +34.l vx
- +3A.b sous-type (ennemi: 0 chat, 1 lézard) ; +3E/+3F.b position initiale (tuiles)
- table routines FF12B0 : 1 FF452E, 2 FF483E, 3 FF3E70, 4 FF4EC6, 5 FF5D58, 6 FF6312, 7 FF6422, 8 FF6456,
  9 FF64AE, 10 FF64EC, 11 FF6648, 12 FF65BA, 13 FF6600, 14 FF66C6, 15 FF6DAA, 16 FF2172, 17 FF21CC,
  18 FF223E, 19 FF2476, 20 FF34BC, 21 FF44DC, 22 FF6DCC

## Physique/anim (FF105C)
- si !(flags&1): x += vx ; wrap x dans [0x80,0x180) ; xscreen = wrap(x - camx) ; y += vy
- FF1126 anim : anim table[+6] -> frames ; chaque frame = (nframes, delay, ptr...) ; bit2 flags set en fin d'anim

## Collision map : 0xFFC800, 32 colonnes x 28 lignes (octet par case 8x8)
- index = ((x-0x80)>>3) + ((y-0x80)>>3)*32 ; valeur &0xF = type
- rangée 0 (C800) et rangées 26-27 (CB40..CB7F) = 0x0C (sol/plafond)
- décodage niveau FF13E4 (a6 = données) : octet 0 = fin ; b7=0 : saut n ; b7=1,b6=0 : n cases =1 horizontal ; b7=1,b6=1 : n cases =1 vertical (pas 0x20)
- FF143A : cases non nulles => -0x20 (au-dessus) = 3, -0x40 = 0xE ; CB20 (ligne 25) non nul => ligne 26 = 0xD
- FF1608 : listes (x,y) de cases spéciales : bit7 ; bit7|bit6 ; bit5
- FF157C(d7=x,d6=y) -> d4 = case & 0xF ; FF15C0 idem relatif à l'objet a0, retourne l'octet complet
- FF1674 : tuile -> pixel (x*8+0x80)

## Chargement d'un round (FF1422, a6 = ptr données niveau)
1. FF13E4 : murs
2. FF148A : d82e/d82f = 2 octets ; puis listes de (x,y) pour types 0,1,1,2 puis 3,4,5 (comptes) -> FF1B16 dessine des tuiles (table FF1B3C tailles, FF1B54 ptrs d810.. art)
   ensuite 6 poussins (C200+, routine 4, +3E/+3F = x,y) ; n1 ennemis type 0 puis n2 ennemis type 1 (C480+, routine 8)
3. FF19C0 : auto-tiling des murs (voisinage -> tuile 0x220d+..), sol = tuile via table d800
4. FF194C/FF1976 : dessine 8 blocs (d808/d80c) à e000/e680 (bordures ?)
5. FF1B86 : porte/sortie à (d82e, d82f-1) art 1a262 (ou 11c98 si pad bit7 ??)
6. FF143A : marquage sol

## Collision objets FF17C0 (a0,a1) : boîtes via table FF1878 (index = +4 piece*8 : dx,w,dy,h)

## Corrections / précisions après lecture complète
- sys54 (0x872) fait `addq.w #4,$ffc0` : les états pairs (init) passent automatiquement à l'état impair suivant.
- États : 0/1 titre, 2/3 instructions, 4/5 choix du round (A+C+Haut+Start), 6/7 init partie -> round (8/9) ou bonus (10/11) si round&3==3,
  12/13 fin (après round 48), 14/15 démo (4 scripts d'entrées FF3A10), 16/17 écran SEGA.
- Le joueur en jeu est l'objet C440 (routine 0xC). C000 = texte GAME OVER/PAUSE. C200..C340 = 6 objets lançables (routine 4).
  C380/C3C0/C400 = ennemis (chat routine 0x10, lézard 0x14 à partir du round 10) créés par les "spawners" C680/C6C0/C700 (routine 0x18)
  qui apparaissent en (0x88,0x90) (coin haut gauche). C480..C640 = 8 poussins max (routine 8, +3A=0 normal / 1 lunettes).
  C740/C780/C7C0 = objet bonus lâché par un ennemi KO (routine 0x28). C000..C1C0 = popups de score.
- Aucun aléa : pas d'appel au RNG 0xF4A. Jeu 100% déterministe (entrées + frames).
- Timer : d88a frames BCD 0..59, d889 secondes BCD, d888 minutes BCD.
- Score BCD 8 chiffres d87e ; ajout via d262 (BCD) + FF168A ; vies d882 ; extra life à 30000, 80000, 160000, 240000, 320000.
- Carte collision : cases mur = masque voisins (b0 haut, b1 bas, b2 gauche, b3 droite) ; 0xC sol/plafond ; b7/b6/b5 cases spéciales
  (points de saut des chats, points de transition du lézard).
- Console : bit7 $A10001 (overseas) choisit les textes anglais ; bit6 (PAL) décale l'affichage (V30). Port : overseas=1, PAL=0.

## Validation (tools/)
- `tools/m68k.py` : interpréteur 68000 minimal (VDP/Z80 en stubs, V-int délivré à l'attente de sys42). Exécute le vrai code
  de la ROM ; une frame = `Machine.run_frame(pad)`.
- `tools/harness.py` : exécution en parallèle ROM/port avec comparaison bit à bit des 32 objets et des variables globales,
  et 'pokes' identiques des deux côtés.
- `tools/compare.py --demo --demo-index N` : rejoue les 4 démos intégrées (rounds 1, 10, 20, 24). 0 divergence.
- `tools/scenario.py` : partie réelle (entrées de la démo, pause, vie supplémentaire, fins de round 1 et 2 avec bonus spécial,
  stage bonus, game over). 0 divergence sur ~4000 frames.
- `tools/scenario_ending.py` : choix du round, stage bonus 47, round 48, générique de fin, reprise au round 49.

## Bizarreries reproduites (registres non initialisés, etc.)
- FF49D0 : après la livraison d'un poussin, d1 (flags de pose) vaut -1 (compteur dbra) -> pose 'saut, vers la droite'.
- FF6834 : le poussin du stage bonus attrapé est effacé puis animé avec la table à l'adresse 0 (cache VDP ff70) ->
  frame_ptr 0xFFFF075F sur un objet mort. Émulé par Game.NULL_ANIM.
- FF4928 : à la mort du joueur, la pose des poussins dispersés dépend d'un d1 résiduel (non émulé : effet visuel d'une frame,
  aucun effet de jeu car le joueur est en train de mourir).
- FF4688 / FF5EA8.. : les positions sont réalignées à partir des coordonnées de sonde (y+1, x±4, y±4), pas de la position.
