# Regole BASE e OBBLIGATORIE per asset 2D, 3D, concept, animazioni e design

Pipeline di riferimento: Concept 2D → TRELLIS (ComfyUI) → Rigify (Blender) → NLA → `.glb` per Godot 4.
Il kit di test del metodo è in `test_metodo_3d.zip` (ricetta ComfyUI/TRELLIS.2, script Blender, `modelli.json`).
Nessun asset va esportato prima di aver superato la checklist di validazione (sezione 5).

## FASE 1 — Concept 2D e mesh (TRELLIS)
1. Genera il concept 2D della creatura e **attendi l'approvazione visiva** dell'utente.
2. Solo dopo l'OK: genera mesh 3D + texture coordinata con TRELLIS.
3. **Preservazione texture**: niente nuovo unwrap, niente `Smart UV Project`. La UV generata da TRELLIS è definitiva e non va alterata (anche durante rigging e skinning).

## FASE 2 — Rigging con Rigify (script Python Blender)
Attiva l'add-on Rigify e carica il Meta-Rig in base all'anatomia:

| Categoria | Preset Rigify |
|---|---|
| Pesci / marine / anguille | `Shark` (catena dorsale per nuoto sinusoidale + pinne) |
| Quadrupedi (cani, lupi, mostri a 4 zampe) | `Wolf` o `Basic Quadruped` |
| Felini | `Cat` |
| Equini / ungulati | `Horse` |
| Volatili / alati | `Bird` (ali articolate + piume) |
| Bipedi / umani | `Human` o `Basic Human` |

- Scala e posiziona le ossa del Meta-Rig sui volumi della mesh, poi `Generate Rig`.
- Applica i pesi di deformazione **senza toccare le UV**.

## FASE 3 — Animazioni (NLA Strips)
Azioni obbligatorie per ogni creatura, come tracce NLA: `idle`, `walk`/`trot`/`swim`/`fly`, `run`, `attack_1`, `faint`.

- **Locomozione**
  - Quadrupedi: passo diagonale a due tempi (anteriore SX + posteriore DX, poi invertiti, sfasati al 50%). Mai passo sincrono sullo stesso lato.
  - Pesci: onda sinusoidale lungo la colonna, pinne pettorali in controtempo.
  - Volanti: downstroke deciso con ala estesa, upstroke con ala parzialmente piegata; punte alari e coda in ritardo di 1–2 frame sulle spalle (overlapping); busto in controfase verticale.
  - Bipedi: braccia alternate alle gambe, spostamento del peso del bacino sulla gamba d'appoggio, flessione della caviglia al contatto (no foot sliding).
- **`run`**: ciclo dinamico con flessione/estensione dorsale; quadrupedi = galoppo con fase di sospensione aerea.
- **Vertical bobbing** (quadrupedi): `Root/Hips` sale quando le zampe passano sotto il corpo, scende all'impatto, mai sotto `Z = 0`.
- **`attack_1`**: caricamento, colpo sul posto, recupero.
- **`faint`/`die`** (35 frame, **niente loop**, niente rotazione rigida del corpo su un lato):
  1. Frame 1–10: stordimento/rinculo, testa che ciondola.
  2. Frame 11–25: cedimento articolare. Quadrupedi: prima le ginocchia, poi il torace a terra. Bipedi: gambe piegate, bacino che scende dritto, schiena curva. Volanti: ali perdono portanza, caduta al suolo.
  3. Frame 26–35: contatto a `Z = 0`, micro-rimbalzo del torace, ritardo di 2–3 frame per coda, orecchie, zampe.
- **Interpolazione**: tutte le F-Curve `BEZIER` con maniglie `AUTO_CLAMPED`. Niente movimenti lineari rigidi.

## FASE 4 — Packaging ed export glTF (Godot 4)
- Texture TRELLIS collegata al **Base Color** di un materiale opaco.
- Tutte le animazioni come tracce nell'NLA Editor.
- Un solo `.glb` binario per creatura, con:
  - Export Selected Objects Only ✅
  - Export NLA Strips ✅
  - Export All Animation Actions ❌
  - Export Deformation Bones Only ✅ (esclude i controlli Rigify)
  - Materials: Export ✅
  - Apply All Transforms (posizione, rotazione, scala uniforme 1.0) prima dell'export.

## 5. Checklist di validazione (prima di ogni export)
- **Topologia/skinning**: edge-loop sufficienti su spalle, gomiti, ginocchia, radici alari; pesi sfumati (smooth) tra busto e arti; nessuna compenetrazione (limiti di rotazione su braccia/zampe contro il torace).
- **Transform**: tutto applicato, scala 1.0.
- **UV**: identiche a quelle generate da TRELLIS.
- **Animazioni**: presenti tutte e 5 le tracce NLA; regole di locomozione per categoria rispettate; `faint` non in loop; F-Curve tutte Bezier/auto_clamped; nessun punto sotto `Z = 0`.
- **Export**: impostazioni della FASE 4 verificate; il `.glb` va riaperto/importato per controllo, non basta il codice di uscita.

## Note operative
- Se un passo non è verificabile nell'ambiente (es. Blender/GPU assenti), dichiaralo; non dire "validato" senza averlo eseguito.
- Dichiara sempre ogni scostamento dalle regole sopra.

## Strumenti nel repo
- `strumenti/pipeline_creatura.py`: FASE 2–4 automatizzate (rig Rigify, skinning, 5 azioni NLA, validazione, export). Vedi `strumenti/README_pipeline.md` per uso e limiti noti.
- `tests/run_tests.sh`: collaudo della pipeline su mesh sintetiche (non sostituisce la prova su mesh reali TRELLIS).
- Ambiente cloud: Blender si puo' usare come modulo (`pip install bpy`), niente GPU quindi niente TRELLIS: quella fase gira sul PC dell'utente.
