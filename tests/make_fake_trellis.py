"""Crea un GLB finto stile TRELLIS (mesh a cilindri attorno al meta-rig + UV + texture) per testare la pipeline.
Solo test: la UV qui e' generata con smart_project perche' non c'e' TRELLIS; la pipeline vera non lo fa mai."""
import sys, math, bpy, addon_utils, bmesh
from mathutils import Vector
preset, out, stretch = sys.argv[sys.argv.index("--") + 1:][:3]
stretch = float(stretch)
bpy.ops.wm.read_factory_settings(use_empty=True)
addon_utils.enable("rigify", default_set=True)
getattr(bpy.ops.object, f"armature_{preset}_metarig_add")()
meta = bpy.context.object
skip = ("lid", "brow", "lip", "nose", "cheek", "teeth", "tongue", "chin", "jaw", "eye", "ear", "r_", "f_", "palm", "pinky", "ring", "middle", "index", "thumb", "t_", "feather", "mane")
bm = bmesh.new()
for b in meta.data.bones:
    if any(k in b.name for k in skip):
        continue
    h, t = Vector(b.head_local), Vector(b.tail_local)
    L = (t - h).length
    if L < 1e-3:
        continue
    r = max(0.14 * L, 0.012)
    mid = (h + t) / 2
    rot = (t - h).to_track_quat("Z", "Y").to_matrix().to_4x4()
    M = __import__("mathutils").Matrix.Translation(mid) @ rot
    bmesh.ops.create_cone(bm, cap_ends=True, segments=int(__import__("os").environ.get("SEG","10")), radius1=r, radius2=r * 0.8, depth=L * 1.02, matrix=M)
me = bpy.data.meshes.new("fake")
bm.to_mesh(me)
obj = bpy.data.objects.new("fake", me)
bpy.context.scene.collection.objects.link(obj)
obj.scale = (1, stretch, 1)
bpy.data.objects.remove(meta)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.uv.smart_project()
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.object.transform_apply(scale=True)
img = bpy.data.images.new("tex", 128, 128)
img.generated_type = "UV_GRID"
img.pack()
mat = bpy.data.materials.new("m")
mat.use_nodes = True
nt = mat.node_tree
tex = nt.nodes.new("ShaderNodeTexImage")
tex.image = img
nt.links.new(tex.outputs["Color"], nt.nodes["Principled BSDF"].inputs["Base Color"])
obj.data.materials.append(mat)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=False)
print("fake ok", len(me.vertices))
