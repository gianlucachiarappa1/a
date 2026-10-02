# pipeline_creatura.py

Dal GLB di TRELLIS a un `.glb` rigged e animato per Godot 4, seguendo `CLAUDE.md`.

```
# con Blender installato (consigliato: 4.2+ / 5.x)
blender --background --factory-startup --python strumenti/pipeline_creatura.py -- \
    --glb trellis.glb --categoria quadrupede --nome lupo --out out/
# oppure con il modulo bpy
pip install bpy && python strumenti/pipeline_creatura.py --glb trellis.glb --categoria quadrupede --nome lupo --out out/
```

Categorie: `pesce` (Shark), `quadrupede` (Wolf), `quadrupede_basic`, `felino` (Cat), `equino` (Horse),
`volatile` (Bird), `bipede` (Human), `bipede_basic`.

Output in `out/<nome>/`: `<nome>.glb`, `<nome>.blend`, `report.json`. Se la checklist fallisce **non viene esportato nulla**
(`--forza-export` aggira il blocco, da non usare per asset definitivi).

Opzioni utili: `--ruota-z GRADI` (la creatura deve guardare -Y), `--salva-prefit` (salva il `.blend` dopo il fit del meta-rig
per sistemare le ossa a mano), `--nome-locomozione` (default: `trot`/`walk`/`fly`/`swim` per categoria),
`--altezza-aria` (quota di partenza del KO e quota dei clip per volanti/pesci, in multipli dell'altezza).

## Cosa fa e cosa verifica
Import GLB → fit del meta-rig (scala uniforme sulla lunghezza, o altezza per i bipedi) → `Generate Rig` → skinning automatico
con fallback sul segmento d'osso piu' vicino per i vertici senza peso → smoothing dei pesi (4 iterazioni, max 4 influenze)
→ limiti di rotazione sugli arti superiori FK → 5 azioni NLA (Bezier + `AUTO_CLAMPED`, stesse ossa chiavate in tutte) →
validazione → export GLB (`NLA_TRACKS`, solo ossa di deformazione, `export_extra_animations=False`) → riapertura del GLB.

Controlli automatici: UV identiche (hash prima/dopo e dopo la riapertura del GLB), tracce obbligatorie, interpolazione,
`faint` senza loop, transform applicate, pesi, materiale opaco con Base Color da texture, nessun vertice sotto `Z=0`
(tolleranza 2,5% dell'altezza) in ogni azione, trotto diagonale (correlazione), nessun arto che attraversa il piano mediano.
Densita' di vertici ai giunti: solo **avviso** euristico, la topologia va guardata a mano.

## Limiti noti (stato collaudato)
- Collaudata solo con **mesh sintetiche** (cilindri attorno al meta-rig + UV + texture) e con `bpy` 5.0.1 su Linux, non con
  mesh reali di TRELLIS ne' in Godot. 7 preset su 8 passano la checklist; `quadrupede_basic` sfora di pochi cm sotto Z=0
  in `run`/`attack_1`/`faint` e quindi **non esporta**: usa `quadrupede` (Wolf).
- Il fit del meta-rig e' automatico e grossolano: su creature con proporzioni diverse dal preset rifinisci a mano (`--salva-prefit`).
- Le ampiezze delle animazioni sono parametriche e proporzionali all'altezza/lunghezza delle zampe; vanno giudicate a occhio
  (non e' stato possibile renderizzarle qui). Il controllo automatico garantisce coerenza, non bellezza.
- I limiti di rotazione sono valori generici (±100°/±60°/±60° locali) sulle FK delle radici degli arti.
- Volanti e pesci: i clip `idle/fly|swim/run/attack_1` sono chiavati a una quota (`--altezza-aria`) cosi' le ali/pinne non
  scendono sotto `Z=0`; `faint` parte da quella quota e atterra a `Z=0`.
- glTF non ha il concetto di loop: in Godot imposta `loop_mode = Animation.LOOP_LINEAR` su `idle`, locomozione e `run`
  (nel `.blend` le azioni ciclica hanno la proprieta' personalizzata `loop=True`). I cicli esportati non duplicano il frame finale.
- Orientamento: Blender -Y (fronte) esce in glTF come +Z; in Godot la creatura "guarda" +Z, ruotala di 180° nel nodo se serve.
