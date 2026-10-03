"""Image -> textured 3D asset (GLB/OBJ) with TripoSR, sized to run on an 8 GB GPU.

Usage (from the project folder, with the venv active):
    python generate.py examples/chair.png
    python generate.py img1.png img2.jpg --height 1.8 --format glb obj
    python generate.py photo.png --no-texture        # vertex colours only, faster

Results land in output/<image-name>/.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

import numpy as np
import trimesh
from PIL import Image

ROOT = Path(__file__).resolve().parent
TRIPOSR_DIR = ROOT / "third_party" / "TripoSR"
# The shim must come first so `from torchmcubes import ...` inside TripoSR resolves to it.
sys.path.insert(0, str(TRIPOSR_DIR))
sys.path.insert(0, str(ROOT / "shims"))

log = logging.getLogger("generate")


def finalize_mesh(mesh: trimesh.Trimesh, height: float | None = None) -> trimesh.Trimesh:
    """Make a raw TripoSR mesh game-ready: outward normals, Y-up, feet on the ground, centred."""
    if len(mesh.faces) and mesh.volume < 0:
        mesh.invert()
    # TripoSR outputs Z-up; glTF/engines expect Y-up facing +Z (same transform as TripoSR's viewer).
    mesh.apply_transform(trimesh.transformations.rotation_matrix(-np.pi / 2, [1, 0, 0]))
    mesh.apply_transform(trimesh.transformations.rotation_matrix(np.pi / 2, [0, 1, 0]))
    if height:
        extent_y = mesh.bounds[1][1] - mesh.bounds[0][1]
        if extent_y > 0:
            mesh.apply_scale(height / extent_y)
    (min_x, min_y, min_z), (max_x, _, max_z) = mesh.bounds
    mesh.apply_translation([-(min_x + max_x) / 2, -min_y, -(min_z + max_z) / 2])
    return mesh


def bake_texture(mesh, model, scene_code, resolution: int) -> trimesh.Trimesh:
    """UV-unwrap the mesh and bake TripoSR's colour field into a texture.

    Re-implements tsr.bake_texture.bake_texture's colour lookup so it works on CUDA
    (upstream queries the triplane with CPU tensors).
    """
    import torch
    from tsr.bake_texture import make_atlas, rasterize_position_atlas

    padding = round(max(2, resolution / 256))
    atlas = make_atlas(mesh, resolution, padding)
    positions = rasterize_position_atlas(
        mesh, atlas["vmapping"], atlas["indices"], atlas["uvs"], resolution, padding
    ).reshape(-1, 4)
    with torch.no_grad():
        xyz = torch.from_numpy(positions[:, :3].astype(np.float32)).to(scene_code.device)
        rgb = model.renderer.query_triplane(model.decoder, xyz, scene_code)["color"]
    rgb = rgb.float().cpu().numpy()
    rgb[positions[:, 3] == 0] = 0
    texture = (np.clip(rgb, 0, 1).reshape(resolution, resolution, 3) * 255).astype(np.uint8)
    # Rasterised with GL (row 0 = bottom); trimesh expects a top-down image with OBJ-style UVs.
    image = Image.fromarray(texture).transpose(Image.FLIP_TOP_BOTTOM)
    return trimesh.Trimesh(
        vertices=mesh.vertices[atlas["vmapping"]],
        faces=atlas["indices"],
        visual=trimesh.visual.TextureVisuals(uv=atlas["uvs"], image=image),
        process=False,
    )


def prepare_image(path: Path, rembg_session, foreground_ratio: float, remove_bg: bool) -> Image.Image:
    from tsr.utils import remove_background, resize_foreground

    image = Image.open(path)
    if not remove_bg:
        return image.convert("RGB")
    image = resize_foreground(remove_background(image, rembg_session), foreground_ratio)
    arr = np.asarray(image).astype(np.float32) / 255.0
    arr = arr[:, :, :3] * arr[:, :, 3:4] + (1 - arr[:, :, 3:4]) * 0.5  # grey background, as TripoSR was trained
    return Image.fromarray((arr * 255.0).astype(np.uint8))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="Genera asset 3D da immagini con TripoSR.")
    p.add_argument("images", nargs="+", type=Path, help="Immagini di input (png/jpg).")
    p.add_argument("--output-dir", type=Path, default=ROOT / "output")
    p.add_argument("--format", nargs="+", choices=["glb", "obj"], default=["glb"])
    p.add_argument("--model", default="stabilityai/TripoSR", help="ID Hugging Face o cartella locale con i pesi.")
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--mc-resolution", type=int, default=256, help="Risoluzione marching cubes (più alta = più dettagli).")
    p.add_argument("--chunk-size", type=int, default=8192, help="Più basso = meno VRAM, più lento.")
    p.add_argument("--no-texture", action="store_true", help="Usa colori per vertice invece di bakeare una texture.")
    p.add_argument("--texture-resolution", type=int, default=1024)
    p.add_argument("--height", type=float, default=None, help="Altezza finale in metri (es. 1.8 per un personaggio).")
    p.add_argument("--no-remove-bg", action="store_true", help="L'immagine ha già sfondo grigio e soggetto centrato.")
    p.add_argument("--foreground-ratio", type=float, default=0.85)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(format="%(asctime)s  %(message)s", level=logging.INFO, datefmt="%H:%M:%S")

    if not (TRIPOSR_DIR / "tsr").is_dir():
        sys.exit(f"TripoSR non trovato in {TRIPOSR_DIR}. Esegui prima setup.ps1.")

    import torch
    from tsr.system import TSR

    device = args.device if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        log.warning("CUDA non disponibile: uso la CPU (molto lento). Lancia scripts/check_gpu.py.")

    t0 = time.time()
    model = TSR.from_pretrained(args.model, config_name="config.yaml", weight_name="model.ckpt")
    model.renderer.set_chunk_size(args.chunk_size)
    model.to(device)
    log.info("Modello caricato in %.1fs", time.time() - t0)

    rembg_session = None
    if not args.no_remove_bg:
        import rembg

        rembg_session = rembg.new_session()

    for path in args.images:
        out_dir = args.output_dir / path.stem
        out_dir.mkdir(parents=True, exist_ok=True)
        log.info("== %s", path.name)
        t0 = time.time()

        image = prepare_image(path, rembg_session, args.foreground_ratio, not args.no_remove_bg)
        image.save(out_dir / "input.png")

        with torch.no_grad():
            scene_codes = model([image], device=device)
        mesh = model.extract_mesh(scene_codes, not args.no_texture, resolution=args.mc_resolution)[0]
        if len(mesh.faces) == 0:
            log.error("Nessuna superficie estratta per %s: prova un'immagine con soggetto più netto.", path.name)
            continue

        if not args.no_texture:
            try:
                mesh = bake_texture(mesh, model, scene_codes[0], args.texture_resolution)
            except Exception as exc:  # moderngl needs an OpenGL context; fall back to vertex colours
                log.warning("Bake texture fallito (%s): uso i colori per vertice.", exc)
                mesh = model.extract_mesh(scene_codes, True, resolution=args.mc_resolution)[0]

        mesh = finalize_mesh(mesh, args.height)
        for fmt in args.format:
            target = out_dir / f"{path.stem}.{fmt}"
            mesh.export(target)
            log.info("Salvato %s", target)
        log.info("%d triangoli, %.1fs", len(mesh.faces), time.time() - t0)

        if device.startswith("cuda"):
            torch.cuda.empty_cache()


if __name__ == "__main__":
    main()
