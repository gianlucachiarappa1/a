# Asset Forge: generatore di asset 3D in locale

Da un'immagine a un modello 3D texturizzato (GLB/OBJ/FBX) pronto per il motore di gioco,
tutto sul proprio PC con modelli open source. Primo obiettivo: funzionare su una
**RTX 5070 Laptop con 8 GB di VRAM** (Windows 11).

```
immagine ─► rimozione sfondo (rembg) ─► TripoSR (mesh) ─► bake texture ─► GLB/OBJ
                                                                  │
                                       blender/cleanup.py ◄───────┘
                              (decimazione, scala, pivot, export GLB/FBX)
```

## Requisiti

- Windows 11, driver NVIDIA aggiornato (serie 570 o successiva per le RTX 50)
- [Python 3.11](https://www.python.org/downloads/) con il "py launcher" e [Git](https://git-scm.com/)
- [Blender 4.2+](https://www.blender.org/download/), solo per la fase di pulizia
- Circa **15 GB liberi** su disco (PyTorch e modelli). Il PC al momento ha circa 60 GB liberi.

## Installazione

In PowerShell, nella cartella del progetto:

```powershell
powershell -ExecutionPolicy Bypass -File setup.ps1
```

Lo script crea `.venv`, installa PyTorch con CUDA 12.8 (obbligatorio per le RTX 50),
scarica TripoSR in `third_party/` e controlla che la GPU funzioni (`scripts/check_gpu.py`).

## Uso

```powershell
.\.venv\Scripts\activate

# immagine -> GLB texturizzato in output\chair\chair.glb
python generate.py third_party\TripoSR\examples\chair.png

# più immagini, personaggio alto 1,8 m, sia GLB che OBJ
python generate.py eroe.png nemico.png --height 1.8 --format glb obj

# pulizia per il motore: max 5000 triangoli, export FBX
blender -b -P blender\cleanup.py -- output\chair\chair.glb output\chair\chair_game.fbx --faces 5000
```

Al primo avvio i pesi di TripoSR (circa 1,7 GB) vengono scaricati da Hugging Face.

| Opzione | Effetto |
|---|---|
| `--mc-resolution 320` | Più dettaglio geometrico (default 256) |
| `--texture-resolution 2048` | Texture più nitida (default 1024) |
| `--no-texture` | Solo colori per vertice: più veloce, ma molti motori li ignorano |
| `--chunk-size 4096` | Meno VRAM, se compare "CUDA out of memory" |
| `--no-remove-bg` | L'immagine ha già sfondo grigio e soggetto centrato |

**Consigli per l'immagine di input:** un solo soggetto intero, ben illuminato, vista frontale
o di 3/4, senza tagli ai bordi. Uno sfondo semplice aiuta la rimozione automatica.

## Struttura

| File | Ruolo |
|---|---|
| `generate.py` | Pipeline principale: sfondo, TripoSR, bake texture, orientamento Y-up, export |
| `blender/cleanup.py` | Pulizia headless in Blender: merge, decimate, smooth, pivot a terra, GLB/FBX |
| `shims/torchmcubes/` | Sostituisce `torchmcubes` (da compilare, fragile su Windows e RTX 50) con scikit-image |
| `scripts/check_gpu.py` | Diagnostica di GPU, CUDA e VRAM |
| `setup.ps1` | Installazione per Windows |

## Note tecniche

- **Mesh pronte per il motore:** l'output è Y-up, centrato, appoggiato a terra (y = 0) e con normali verso l'esterno.
- **Bake texture:** su CUDA viene usata una versione corretta del bake di TripoSR, perché
  quella originale interroga il modello con tensori su CPU e fallisce sulla GPU.
- **Fallback:** se il bake fallisce (manca un contesto OpenGL), lo script passa ai colori per vertice.

## Roadmap

1. **Qualità superiore:** Hunyuan3D-2mini (forma, sta in 8 GB) e Hunyuan3D-2GP per la texture (con offload su RAM).
2. **Testo → 3D:** SDXL / FLUX quantizzato → immagine → questa pipeline.
3. **Rigging e animazione:** UniRig per l'auto-rig, retargeting di clip Mixamo in Blender.
4. **Interfaccia web:** frontend con anteprima three.js e coda di job, così chiunque nel team può generare asset.

## Licenze

TripoSR è MIT (VAST AI Research / Stability AI). Prima di usare commercialmente i modelli
della roadmap, verificate la licenza di ciascuno (Hunyuan3D ha una licenza propria con limitazioni).
