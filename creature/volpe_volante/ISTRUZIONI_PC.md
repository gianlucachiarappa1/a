# Volpe volante: cosa fare sul tuo PC (fase TRELLIS)

Prerequisiti: ComfyUI + pesi installati come da `test_metodo_3d/PROMPT_AMICO.md` (non ancora provato su RTX 5070 8 GB).

1. Immagine di input: `volpe_volante.png` = concept approvato, **senza fumo e con sfondo trasparente**, in alta risoluzione
   (scaricala da Canva, vedi il link nella chat). Copiala in `ComfyUI/input/volpe_volante.png`.
2. Invia `workflow_api_volpe.json` a ComfyUI (`POST /prompt` come campo `prompt`, oppure caricalo nell'interfaccia).
   E' la ricetta originale della casa con due soli cambi: immagine (nodo 122) e prefisso di salvataggio (nodo 322).
   Se va fuori memoria sugli 8 GB, usa le varianti elencate nel prompt dell'amico (colore 2048, normali 1024, AO 512/32, remesh inferiore)
   e annota quale hai usato.
3. Prendi il `.glb` generato (cartella `ComfyUI/output/creature/`).
4. Pipeline Blender (Blender 5.x oppure `pip install bpy`):

```
blender --background --factory-startup --python strumenti/pipeline_creatura.py -- \
  --glb PERCORSO/volpe_volante_prova1.glb --categoria volatile --zampe-anteriori \
  --nome volpe_volante --out out/
```
   - La creatura deve guardare -Y: se nel GLB guarda altrove aggiungi `--ruota-z 90|180|-90`.
   - Prima volta consigliato `--salva-prefit`: apri il `.blend`, adatta a mano le ossa (ali da pipistrello, zampe anteriori, coda), poi rilancia.
   - Il fumo della coda NON e' nella mesh: va aggiunto in Godot come `GPUParticles3D` viola agganciato alla punta della coda.
5. Mandami `out/volpe_volante/report.json` (o il log): se la checklist fallisce non c'e' export e si corregge.
