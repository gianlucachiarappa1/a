"""Clean up a generated asset in Blender (headless) and export it for a game engine.

    blender -b -P blender/cleanup.py -- output/chair/chair.glb output/chair/chair_game.glb --faces 5000
    blender -b -P blender/cleanup.py -- in.glb out.fbx --faces 8000 --height 1.8

Steps: merge duplicate vertices, decimate to a triangle budget, smooth shading,
origin at the bottom centre, optional rescale to a height in metres, export GLB or FBX.
"""

import argparse
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1 :] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="cleanup.py")
    p.add_argument("input", type=Path)
    p.add_argument("output", type=Path, help="Estensione .glb o .fbx")
    p.add_argument("--faces", type=int, default=5000, help="Numero massimo di triangoli.")
    p.add_argument("--height", type=float, default=None, help="Altezza finale in metri.")
    p.add_argument("--merge-distance", type=float, default=1e-5)
    p.add_argument("--smooth-angle", type=float, default=40.0, help="Gradi per lo smooth by angle.")
    return p.parse_args(argv)


def import_mesh(path: Path):
    ext = path.suffix.lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    else:
        sys.exit(f"Formato non supportato: {ext}")
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        sys.exit("Nessuna mesh trovata nel file.")
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    # Drop empties/armature-less parents left by the importer, keeping the world transform.
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return obj


def triangle_count(obj) -> int:
    obj.data.calc_loop_triangles()
    return len(obj.data.loop_triangles)


def main():
    args = parse_args()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    obj = import_mesh(args.input)
    before = triangle_count(obj)

    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=args.merge_distance)
    bpy.ops.mesh.delete_loose()
    bpy.ops.object.mode_set(mode="OBJECT")

    tris = triangle_count(obj)
    if tris > args.faces:
        mod = obj.modifiers.new("Decimate", "DECIMATE")
        mod.ratio = args.faces / tris
        bpy.ops.object.modifier_apply(modifier=mod.name)

    try:  # Blender >= 4.1
        bpy.ops.object.shade_smooth_by_angle(angle=args.smooth_angle * 3.14159265 / 180)
    except AttributeError:
        bpy.ops.object.shade_smooth()

    if args.height:
        size_z = obj.dimensions.z
        if size_z > 0:
            obj.scale *= args.height / size_z
            bpy.ops.object.transform_apply(scale=True)

    # Origin at the bottom centre of the bounding box, object placed at world origin.
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    pivot = Vector(
        (
            (min(c.x for c in corners) + max(c.x for c in corners)) / 2,
            (min(c.y for c in corners) + max(c.y for c in corners)) / 2,
            min(c.z for c in corners),
        )
    )
    bpy.context.scene.cursor.location = pivot
    bpy.ops.object.origin_set(type="ORIGIN_CURSOR")
    obj.location = (0, 0, 0)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    ext = args.output.suffix.lower()
    if ext == ".glb":
        bpy.ops.export_scene.gltf(filepath=str(args.output), export_format="GLB", use_selection=True)
    elif ext == ".fbx":
        bpy.ops.export_scene.fbx(
            filepath=str(args.output), use_selection=True, path_mode="COPY", embed_textures=True
        )
    else:
        sys.exit(f"Formato di output non supportato: {ext}")

    d = obj.dimensions
    print(f"OK: {before} -> {triangle_count(obj)} triangoli, {d.x:.2f} x {d.y:.2f} x {d.z:.2f} m -> {args.output}")


if __name__ == "__main__":
    main()
