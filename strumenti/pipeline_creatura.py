"""Pipeline creatura: GLB TRELLIS -> Rigify -> skinning -> 5 animazioni NLA -> validazione -> GLB Godot 4.

Regole implementate: vedi CLAUDE.md (FASE 2, 3, 4 e checklist). Le UV di TRELLIS non vengono mai toccate:
si calcola un hash delle UV prima e dopo e la validazione fallisce se differisce.

Uso (Blender reale):
  blender --background --factory-startup --python strumenti/pipeline_creatura.py -- \
      --glb creatura_trellis.glb --categoria quadrupede --nome lupo --out out/
Uso (modulo bpy da pip):
  python strumenti/pipeline_creatura.py --glb ... --categoria ... --nome ... --out ...

Convenzione: la creatura guarda verso -Y (Blender), Z in alto. Se il GLB e' orientato diversamente usa --ruota-z.
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys

import bpy
import addon_utils
import numpy as np
from mathutils import Euler, Matrix, Vector

# categoria -> (preset Rigify, famiglia animazione)
CATEGORIE = {
    "pesce": ("shark", "fish"),
    "quadrupede": ("wolf", "quad"),
    "quadrupede_basic": ("basic_quadruped", "quad"),
    "felino": ("cat", "quad"),
    "equino": ("horse", "quad"),
    "volatile": ("bird", "bird"),
    "bipede": ("human", "biped"),
    "bipede_basic": ("basic_human", "biped"),
}
LOCOMOZIONE = {"fish": "swim", "quad": "trot", "bird": "fly", "biped": "walk"}
FWD = Vector((0, -1, 0))
UP = Vector((0, 0, 1))
LIMB_KEYS = ("thigh", "shin", "foot", "toe", "upper_arm", "forearm", "hand", "palm", "f_", "r_", "t_", "hoof",
             "paw", "claw", "finger", "wing", "feather", "fin", "lower_leg", "heel", "pinky", "ring", "middle",
             "index", "thumb", "shoulder", "ear", "tail")
FPS = 30


def log(*a):
    print("[pipeline]", *a, flush=True)


# ----------------------------------------------------------------------------- utilita'

def smooth(a, b, x):
    t = min(max((x - a) / (b - a), 0.0), 1.0) if b != a else 1.0
    return t * t * (3 - 2 * t)


def deselect_all():
    for o in bpy.context.scene.objects:
        o.select_set(False)


def activate(obj, select_only=True):
    if select_only:
        deselect_all()
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def mesh_coords(obj):
    me = obj.data
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    return co.reshape(-1, 3)


def action_fcurves(act):
    if hasattr(act, "fcurves"):
        return list(act.fcurves)
    out = []
    for layer in act.layers:
        for strip in layer.strips:
            for cb in strip.channelbags:
                out += list(cb.fcurves)
    return out


def uv_set_hash(obj):
    """Hash dell'insieme delle UV uniche: resta uguale anche se l'export spezza i vertici sulle cuciture."""
    layer = obj.data.uv_layers.active
    uv = np.empty(len(layer.data) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", uv)
    u = np.unique(np.round(uv.reshape(-1, 2), 4), axis=0)
    return hashlib.sha256(u.tobytes()).hexdigest()


def uv_signature(obj):
    layer = obj.data.uv_layers.active
    if layer is None:
        return None
    uv = np.empty(len(layer.data) * 2, dtype=np.float32)
    layer.data.foreach_get("uv", uv)
    return {"layer": layer.name, "n": len(layer.data), "sha256": hashlib.sha256(uv.tobytes()).hexdigest(), "set": uv_set_hash(obj)}


# ----------------------------------------------------------------------------- fase 1: import

def importa_glb(path, ruota_z):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    addon_utils.enable("rigify", default_set=True)
    bpy.ops.import_scene.gltf(filepath=path)
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    assert meshes, "Nessuna mesh nel GLB"
    for o in list(bpy.context.scene.objects):
        if o.type != "MESH":
            continue
        o.parent = None  # la trasformazione viene fissata dopo con apply
    for o in list(bpy.context.scene.objects):
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True)
    for o in meshes:
        o.data = o.data.copy() if o.data.users > 1 else o.data
    deselect_all()
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = meshes[0]
    if len(meshes) > 1:
        bpy.ops.object.join()
    mesh = bpy.context.view_layer.objects.active
    if ruota_z:
        mesh.rotation_euler.rotate_axis("Z", math.radians(ruota_z))
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    co = mesh_coords(mesh)
    mn, mx = co.min(0), co.max(0)
    mesh.location = (-(mn[0] + mx[0]) / 2, -(mn[1] + mx[1]) / 2, -mn[2])
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    return mesh


# ----------------------------------------------------------------------------- fase 2: meta-rig, rig, skin

def aggiungi_zampe_anteriori(meta):
    """Adattamento del meta-rig Bird: duplica la catena della zampa posteriore (limbs.paw) all'altezza delle spalle,
    cosi' una creatura alata a 4 zampe (es. volpe-pipistrello) ha anche gli arti anteriori."""
    bpy.context.view_layer.objects.active = meta
    bpy.ops.object.mode_set(mode="EDIT")
    eb = meta.data.edit_bones
    sh = eb["shoulder.L"]
    dy = sh.head.y - eb["thigh.L"].head.y  # sposta indietro->avanti (-Y) fino alla spalla
    dy = -abs(dy) - 0.01 * (eb["thigh.L"].head.z)
    parent = eb["spine.003"] if "spine.003" in eb else eb["spine.004"]
    chain = ["thigh", "shin", "foot", "toe", "toes_parent"]
    nuove = []
    for side in ("L", "R"):
        for n in chain:
            src = eb.get(f"{n}.{side}")
            if src is None:
                continue
            b = eb.new(f"front_{n}.{side}")
            b.head, b.tail, b.roll = src.head.copy(), src.tail.copy(), src.roll
            b.head.y += dy
            b.tail.y += dy
            nuove.append((b.name, f"{n}.{side}"))
        for n in chain:
            if f"front_{n}.{side}" not in eb:
                continue
            src = eb[f"{n}.{side}"]
            b = eb[f"front_{n}.{side}"]
            b.parent = eb[f"front_{src.parent.name.split('.')[0]}.{side}"] if src.parent and f"front_{src.parent.name.split('.')[0]}.{side}" in eb else parent
            b.use_connect = src.use_connect
    bpy.ops.object.mode_set(mode="POSE")
    for nuovo, orig in nuove:
        pb_n, pb_o = meta.pose.bones[nuovo], meta.pose.bones[orig]
        pb_n.rigify_type = pb_o.rigify_type
        if pb_o.rigify_type:
            for prop in pb_o.rigify_parameters.bl_rna.properties:
                if prop.identifier == "rna_type":
                    continue
                try:
                    setattr(pb_n.rigify_parameters, prop.identifier, getattr(pb_o.rigify_parameters, prop.identifier))
                except Exception:
                    pass
    bpy.ops.object.mode_set(mode="OBJECT")
    log(f"aggiunte zampe anteriori: {[n for n, _ in nuove]}")


def crea_e_adatta_metarig(mesh, preset, fam, zampe_anteriori=False):
    getattr(bpy.ops.object, f"armature_{preset}_metarig_add")()
    meta = bpy.context.object
    meta.name = "metarig"
    if zampe_anteriori:
        assert preset == "bird", "--zampe-anteriori vale solo per la categoria volatile"
        aggiungi_zampe_anteriori(meta)

    def bounds(arm):
        pts = []
        for b in arm.data.bones:
            pts += [arm.matrix_world @ b.head_local, arm.matrix_world @ b.tail_local]
        a = np.array([[p.x, p.y, p.z] for p in pts])
        return a.min(0), a.max(0)

    mn, mx = bounds(meta)
    co = mesh_coords(mesh)
    cmn, cmx = co.min(0), co.max(0)
    md, cd = mx - mn, cmx - cmn
    s = cd[2] / md[2] if fam == "biped" else cd[1] / md[1]
    sz = s
    if fam in ("quad", "fish"):
        sz = s * min(max((cd[2] / md[2]) / s, 0.7), 1.4)
    meta.scale = (s, s, sz)
    activate(meta)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    mn, mx = bounds(meta)
    meta.location = ((cmn[0] + cmx[0]) / 2 - (mn[0] + mx[0]) / 2,
                     (cmn[1] + cmx[1]) / 2 - (mn[1] + mx[1]) / 2,
                     cmn[2] - mn[2])
    bpy.ops.object.transform_apply(location=True, rotation=False, scale=False)
    log(f"metarig {preset}: scala uniforme {s:.3f}, scala Z {sz:.3f}")
    return meta


def genera_rig(meta, nome):
    activate(meta)
    bpy.ops.pose.rigify_generate()
    rig = bpy.data.objects["rig"]
    rig.name = f"{nome}_rig"
    rig.data.name = f"{nome}_rig"
    bpy.data.objects.remove(meta, do_unlink=True)
    return rig


def pesi_matrice(mesh):
    names = [vg.name for vg in mesh.vertex_groups]
    W = np.zeros((len(mesh.data.vertices), len(names)), dtype=np.float32)
    for v in mesh.data.vertices:
        for g in v.groups:
            W[v.index, g.group] = g.weight
    return names, W


def scrivi_pesi(mesh, names, W, max_inf=4):
    n = W.shape[0]
    for vg in mesh.vertex_groups:
        vg.remove(range(n))
    top = np.argsort(-W, axis=1)[:, :max_inf]
    vgs = mesh.vertex_groups
    for i in range(n):
        ws = W[i, top[i]]
        tot = ws.sum()
        if tot <= 0:
            continue
        for g, w in zip(top[i], ws):
            if w > 1e-4:
                vgs[int(g)].add([i], float(w / tot), "REPLACE")


def smooth_weights(mesh, W, iters=4, factor=0.5):
    me = mesh.data
    e = np.empty(len(me.edges) * 2, dtype=np.int32)
    me.edges.foreach_get("vertices", e)
    e = e.reshape(-1, 2)
    deg = np.bincount(e.ravel(), minlength=W.shape[0]).astype(np.float32)
    deg[deg == 0] = 1
    for _ in range(iters):
        S = np.zeros_like(W)
        np.add.at(S, e[:, 0], W[e[:, 1]])
        np.add.at(S, e[:, 1], W[e[:, 0]])
        W = (1 - factor) * W + factor * S / deg[:, None]
    return W


def skin(mesh, rig):
    deselect_all()
    mesh.select_set(True)
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    names, W = pesi_matrice(mesh)
    unweighted = np.where(W.sum(1) < 1e-4)[0]
    log(f"skinning auto: {len(names)} gruppi, {len(unweighted)} vertici senza peso")
    if len(unweighted):
        co = mesh_coords(mesh)
        for gi, name in enumerate(names):
            pass
        segs = []
        for n in names:
            b = rig.data.bones[n]
            segs.append((np.array(b.head_local), np.array(b.tail_local)))
        for vi in unweighted:
            p = co[vi]
            best, bd = 0, 1e9
            for gi, (a, b) in enumerate(segs):
                ab = b - a
                t = np.clip(np.dot(p - a, ab) / max(np.dot(ab, ab), 1e-9), 0, 1)
                d = np.linalg.norm(p - (a + t * ab))
                if d < bd:
                    best, bd = gi, d
            W[vi, best] = 1.0
    W = smooth_weights(mesh, W)
    W /= np.maximum(W.sum(1, keepdims=True), 1e-9)
    scrivi_pesi(mesh, names, W)
    names, W = pesi_matrice(mesh)
    return names, W


def limiti_rotazione(rig):
    pat = re.compile(r"^((front_)?(thigh|upper_arm)_fk|shoulder)\.[LR]$")
    n = 0
    for pb in rig.pose.bones:
        if pat.match(pb.name):
            c = pb.constraints.new("LIMIT_ROTATION")
            c.owner_space = "LOCAL"
            c.use_limit_x = c.use_limit_y = c.use_limit_z = True
            c.min_x, c.max_x = math.radians(-100), math.radians(100)
            c.min_y, c.max_y = math.radians(-60), math.radians(60)
            c.min_z, c.max_z = math.radians(-60), math.radians(60)
            c.name = "limite_rotazione"
            n += 1
    log(f"limiti di rotazione su {n} ossa")


# ----------------------------------------------------------------------------- rilevamento controlli

class Ctx:
    pass


def climb_effector(pb):
    b = pb
    while b is not None:
        n = b.name
        if (not n.startswith(("MCH", "ORG", "DEF")) and re.search(r"_ik\.[LR]$", n)
                and not any(k in n for k in ("heel", "toe", "spin", "pole", "target", "VIS"))):
            return b
        b = b.parent
    return None


def prepara_ctx(rig, mesh, fam, args):
    c = Ctx()
    c.rig, c.mesh, c.fam, c.args = rig, mesh, fam, args
    co = mesh_coords(mesh)
    c.H = float(co[:, 2].max() - co[:, 2].min())
    c.Ly = float(co[:, 1].max() - co[:, 1].min())
    c.pb = rig.pose.bones
    limbs = {}
    for b in c.pb:
        for k in b.constraints:
            if k.type == "IK" and k.subtarget and not k.pole_subtarget:
                t = c.pb.get(k.subtarget)
                if not t:
                    continue
                for kk in t.constraints:
                    if kk.type == "COPY_LOCATION" and kk.subtarget:
                        e = climb_effector(c.pb[kk.subtarget])
                        root = b.parent if k.chain_count >= 2 and b.parent else b
                        if e and e.name not in limbs:
                            eh = Vector(rig.data.bones[e.name].head_local)
                            rh = Vector(rig.data.bones[root.name].head_local)
                            limbs[e.name] = dict(name=e.name, side=1 if e.name.endswith(".L") else -1,
                                                 head=eh, root=rh, length=max((rh - eh).length, 1e-3))
    cy = (co[:, 1].max() + co[:, 1].min()) / 2
    groups = {}
    rys = [l["root"].y for l in limbs.values()] or [0.0]
    thr = (min(rys) + max(rys)) / 2  # spalle (avanti, -Y) vs anche: soglia a meta' tra le radici estreme
    for l in limbs.values():
        if fam == "biped":
            l["kind"] = "leg" if l["root"].z < 0.65 * c.H else "arm"
        else:
            l["kind"] = "front" if l["root"].y < thr else "hind"
        groups.setdefault((l["kind"], l["side"]), []).append(l)
    c.limbs = []
    for (kind, side), cand in sorted(groups.items()):
        # piu' controlli IK per arto (anca, piede, punta): l'effettore e' quello piu' distale
        best = min(cand, key=lambda l: l["head"].z) if kind != "arm" else max(cand, key=lambda l: abs(l["head"].x))
        c.limbs.append(best)
    c.Lm = float(np.mean([l["length"] for l in c.limbs])) if c.limbs else c.H * 0.5
    # catene di controlli
    def has(n):
        return n in c.pb

    def ordered(pattern):
        names = [b.name for b in c.pb if re.match(pattern, b.name)]
        return sorted(names, key=lambda n: rig.data.bones[n].head_local.y)  # fronte (-Y) -> coda (+Y)

    c.spine = ordered(r"^(chest|spine(\.\d+)?|hips)$")
    c.tail = [n for n in ordered(r"^tail\.\d+$")]
    c.neck = [n for n in ("neck", "head") if has(n)]
    c.ears = [n for n in ("ear.L", "ear.R") if has(n)]
    c.torso = "torso" if has("torso") else c.spine[0]
    c.wings = {s: [n for n in (f"Wing.{s}", f"Wing.001.{s}", f"Wing.002.{s}") if has(n)] for s in ("L", "R")}
    c.sidefins = {s: [n for n in (f"side_fin.{s}", f"side_fin.{s}.001") if has(n)] for s in ("L", "R")}
    c.fins = [n for n in ("top_fin", "top_fin.001") if has(n)]
    # trunk (per calibrare il contatto a terra del KO)
    names, W = pesi_matrice(mesh)
    dom = np.array([names[i] for i in W.argmax(1)])
    limb_mask = np.array([any(k in d.lower() for k in LIMB_KEYS) for d in dom])
    c.trunk = np.where(~limb_mask)[0]
    log(f"limbs: {[(l['name'], l['kind']) for l in c.limbs]} | trunk vertici: {len(c.trunk)}")
    return c


# ----------------------------------------------------------------------------- posa

def local_loc(rig, bone, delta):
    M = rig.data.bones[bone].matrix_local.to_3x3()
    return M.inverted() @ delta


def local_rot(rig, bone, eul):
    M = rig.data.bones[bone].matrix_local.to_3x3()
    R = M.inverted() @ eul.to_matrix() @ M
    return R.to_euler("XYZ")


class Pose:
    """Accumula contributi in spazio armatura/mondo per osso."""

    def __init__(self):
        self.loc, self.rot = {}, {}

    def add_loc(self, bone, v):
        self.loc[bone] = self.loc.get(bone, Vector()) + Vector(v)

    def add_rot(self, bone, x=0.0, y=0.0, z=0.0):
        e = self.rot.get(bone, Vector())
        self.rot[bone] = e + Vector((x, y, z))


def applica_posa(c, pose):
    for pb in c.pb:
        pb.location = (0, 0, 0)
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0, 0, 0)
    for b, v in pose.loc.items():
        c.pb[b].location = local_loc(c.rig, b, v)
    for b, v in pose.rot.items():
        c.pb[b].rotation_euler = local_rot(c.rig, b, Euler(v, "XYZ"))
    bpy.context.view_layer.update()


def trunk_minz(c):
    dg = bpy.context.evaluated_depsgraph_get()
    ev = c.mesh.evaluated_get(dg)
    me = ev.to_mesh()
    co = np.empty(len(me.vertices) * 3, dtype=np.float32)
    me.vertices.foreach_get("co", co)
    ev.to_mesh_clear()
    co = co.reshape(-1, 3)
    return float(co[:, 2].min()), float(co[c.trunk, 2].min())


# ----------------------------------------------------------------------------- generatori di animazione
# Ogni generatore restituisce (n_frame, loop, fn) con fn(frame_index_0based) -> Pose.

def foot_traj(u, A, lift, duty, toe):
    """u in [0,1): stance (contatto, piede indietro rispetto al corpo) poi swing. -> (avanti, su, beccheggio)."""
    u = u % 1.0
    if u < duty:
        s = u / duty
        return A * (1 - 2 * s), 0.0, toe * (-0.6 * (1 - smooth(0, 0.25, s)) + smooth(0.75, 1.0, s))
    s = (u - duty) / (1 - duty)
    return -A + 2 * A * smooth(0, 1, s), lift * math.sin(math.pi * s), toe * (1 - s) * 0.4


def aggiungi_piede(p, l, y, z, pitch, side_spread=0.0):
    p.add_loc(l["name"], FWD * y + UP * z + Vector((l["side"] * side_spread, 0, 0)))
    p.add_rot(l["name"], x=pitch)


def coda_ritardata(c, p, value_fn, frame_fn_delay):
    """Applica rotazioni alla coda con ritardo crescente (overlapping action)."""
    for i, n in enumerate(c.tail):
        p.add_rot(n, x=value_fn(frame_fn_delay * (i + 1)))


def anim_idle(c):
    N = 60
    H = c.H

    def fn(f):
        u = f / N
        p = Pose()
        br = math.sin(2 * math.pi * u)
        p.add_loc(c.torso, UP * (0.004 * H * br))
        for n in c.spine[:1]:
            p.add_rot(n, x=math.radians(1.2) * br)
        for n in c.neck:
            p.add_rot(n, x=math.radians(2) * math.sin(2 * math.pi * u - 0.8), z=math.radians(3) * math.sin(2 * math.pi * u * 1 + 1.2))
        for i, n in enumerate(c.tail):
            p.add_rot(n, z=math.radians(6) * math.sin(2 * math.pi * u - 0.5 * (i + 1)))
        for n in c.ears:
            p.add_rot(n, x=math.radians(3) * math.sin(2 * math.pi * u - 1.0))
        if c.fam == "biped":
            hang(c, p, 0.0)
        if c.fam == "bird":
            for s, w in c.wings.items():
                sg = 1 if s == "L" else -1
                for n in w[:1]:
                    p.add_rot(n, y=sg * math.radians(2) * br)
        if c.fam == "fish":
            body_wave(c, p, u, 0.5, 0.35)
            fins_flap(c, p, u, 8, 1.0)
        return p
    return N, True, fn


def hang(c, p, swing_phase_u, swing=0.0, raise_hands=0.0, only_side=None):
    """Braccia lungo i fianchi (il meta-rig umano e' in T-pose), con oscillazione avanti/indietro."""
    for l in c.limbs:
        if l["kind"] != "arm":
            continue
        L = l["length"]
        y = swing * L * math.cos(2 * math.pi * (swing_phase_u + (0.5 if l["side"] > 0 else 0.0)))
        d = Vector((-l["side"] * 0.85 * L, 0, -0.95 * L + raise_hands * L))
        p.add_loc(l["name"], d + FWD * y)


def body_wave(c, p, u, amp, wavelen, turns=1.0):
    chain = [n for n in c.neck[-1:]] + c.spine + c.tail
    chain = sorted(set(chain), key=lambda n: c.rig.data.bones[n].head_local.y)
    k = len(chain)
    for i, n in enumerate(chain):
        pos = i / max(k - 1, 1)
        a = amp * (0.15 + 0.85 * pos) * 0.5
        p.add_rot(n, z=a * math.sin(2 * math.pi * (u * turns - pos * wavelen)))


def fins_flap(c, p, u, deg, phase):
    for s, names in c.sidefins.items():
        sg = 1 if s == "L" else -1
        for i, n in enumerate(names):
            p.add_rot(n, y=sg * math.radians(deg) * math.sin(2 * math.pi * (u + 0.5 * phase) - 0.5 * i))
    for i, n in enumerate(c.fins):
        p.add_rot(n, z=math.radians(5) * math.sin(2 * math.pi * u - 0.7 - 0.4 * i))


def anim_locomozione(c, run=False):
    fam, H = c.fam, c.H
    if fam == "quad":
        return anim_quad(c, run)
    if fam == "biped":
        return anim_biped(c, run)
    if fam == "bird":
        return anim_bird(c, run)
    return anim_fish(c, run)


def anim_quad(c, run):
    H = c.Lm  # ampiezze proporzionali alla lunghezza reale delle zampe
    N = 16 if run else 24
    phase = {}
    for l in c.limbs:
        front, left = l["kind"] == "front", l["side"] > 0
        if not run:
            # trotto: diagonali sfasati al 50% (anteriore SX + posteriore DX insieme)
            phase[l["name"]] = 0.0 if (front == left) else 0.5
        else:
            phase[l["name"]] = (0.0 if front else 0.45) + (0.0 if left else 0.06)
    A = (0.30 if run else 0.18) * H
    lift = (0.30 if run else 0.16) * H
    duty = 0.38 if run else 0.5

    def fn(f):
        u = f / N
        p = Pose()
        for l in c.limbs:
            y, z, pit = foot_traj(u - phase[l["name"]], A, lift, duty, math.radians(7))
            aggiungi_piede(p, l, y, z + 0.06 * H * max(math.sin(pit), 0.0), pit)
        if not run:
            bob = 0.035 * H * (0.5 - 0.5 * math.cos(4 * math.pi * u))
            p.add_loc(c.torso, UP * (-0.05 * H + bob))
            sw = math.radians(3) * math.sin(2 * math.pi * u)
            for n in c.spine:
                p.add_rot(n, z=sw * (1 if n == "chest" else -1))
        else:
            bump = 0.5 + 0.5 * math.cos(2 * math.pi * (u - 0.87))
            p.add_loc(c.torso, UP * (-0.06 * H + 0.14 * H * bump) + FWD * (0.0))
            flex = math.radians(9) * math.sin(2 * math.pi * (u - 0.15))
            for n in c.spine:  # estensione/flessione dorsale
                p.add_rot(n, x=flex * (1 if n.startswith("chest") else -1 if n == "hips" else 0.4))
        for n in c.neck:
            p.add_rot(n, x=-math.radians(4) * math.sin(4 * math.pi * u if not run else 2 * math.pi * u))
        for i, n in enumerate(c.tail):
            p.add_rot(n, z=math.radians(8) * math.sin(2 * math.pi * u * (2 if not run else 1) - 0.6 * (i + 1)),
                      x=math.radians(4) * math.sin(2 * math.pi * u * 2 - 0.5 * (i + 1)))
        for n in c.ears:
            p.add_rot(n, x=math.radians(5) * math.sin(4 * math.pi * u - 1.0))
        return p
    return N, True, fn


def anim_biped(c, run):
    H = c.H
    N = 20 if run else 32
    A = (0.20 if run else 0.13) * H
    lift = (0.20 if run else 0.07) * H
    duty = 0.38 if run else 0.55

    def fn(f):
        u = f / N
        p = Pose()
        for l in c.limbs:
            if l["kind"] != "leg":
                continue
            ph = 0.0 if l["side"] > 0 else 0.5
            y, z, pit = foot_traj(u - ph, A, lift, duty, math.radians(22 if run else 16))
            aggiungi_piede(p, l, y, z, pit)
        hang(c, p, u, swing=0.40 if run else 0.30, raise_hands=0.25 if run else 0.0)
        if run:
            bump = 0.5 + 0.5 * math.cos(4 * math.pi * (u - 0.19))
            p.add_loc(c.torso, UP * (-0.06 * H + 0.08 * H * bump))
            lean = math.radians(9)
        else:
            bob = 0.025 * H * (0.5 - 0.5 * math.cos(4 * math.pi * u))
            p.add_loc(c.torso, UP * (-0.03 * H + bob) + Vector((0.025 * H * math.sin(2 * math.pi * u), 0, 0)))
            lean = math.radians(2)
        p.add_rot(c.torso, x=lean, z=-math.radians(4) * math.sin(2 * math.pi * u))
        for n in c.spine:
            if n == "chest":
                p.add_rot(n, z=math.radians(6 if run else 4) * math.sin(2 * math.pi * u))
        for n in c.neck:
            p.add_rot(n, x=-lean * 0.6)
        return p
    return N, True, fn


def anim_bird(c, run):
    H, N = c.H, (14 if run else 20)
    amp_up, amp_dn = math.radians(38), math.radians(32)

    def wing_angle(u):  # >0 = verso il basso. downstroke u<0.45 (esteso), upstroke piegato
        if u < 0.45:
            t = smooth(0, 1, u / 0.45)
            return -amp_up + (amp_up + amp_dn) * t, 0.0
        t = smooth(0, 1, (u - 0.45) / 0.55)
        return amp_dn - (amp_up + amp_dn) * t, math.sin(math.pi * t)  # piega sul risalita

    def fn(f):
        u = f / N
        p = Pose()
        for s, names in c.wings.items():
            sg = 1 if s == "L" else -1
            for i, n in enumerate(names):
                uu = (u - i * 1.5 / N) % 1.0  # ritardo 1-2 frame verso le punte (overlapping)
                ang, fold = wing_angle(uu)
                extra = math.radians(28 + 14 * i) * fold * (1 if i else 0.4)
                p.add_rot(n, y=sg * (ang * (1.0 if i == 0 else 0.45) + extra))
        ang0, _ = wing_angle(u)
        bz = 0.09 * H * (ang0 / amp_dn) * 0.5 if not run else 0.12 * H * (ang0 / amp_dn) * 0.5
        p.add_loc(c.torso, UP * bz)
        p.add_rot(c.torso, x=math.radians(8 if run else 3) + math.radians(2.5) * (ang0 / amp_dn))
        for i, n in enumerate(c.tail or c.spine[-1:]):
            p.add_rot(n, x=math.radians(7) * -((wing_angle((u - 2 / N * (i + 1)) % 1.0)[0]) / amp_dn))
        for l in c.limbs:  # zampe raccolte in volo
            p.add_loc(l["name"], UP * (0.22 * H) + FWD * (-0.05 * H))
        for n in c.neck:
            p.add_rot(n, x=-math.radians(3) * (ang0 / amp_dn))
        return p
    return N, True, fn


def anim_fish(c, run):
    H, N = c.H, (24 if run else 40)
    amp = 0.55 if run else 0.38

    def fn(f):
        u = f / N
        p = Pose()
        body_wave(c, p, u, amp, 0.85)
        fins_flap(c, p, u, 30 if not run else 18, 1.0)
        p.add_loc(c.torso, UP * (0.02 * H * math.sin(4 * math.pi * u)))
        return p
    return N, True, fn


def anim_attack(c):
    N, H = 30, c.H

    def env(f):  # 0 neutro -> -1 caricamento (1-10) -> +1 colpo (11-16) -> 0 recupero (17-30)
        if f < 10:
            return -smooth(0, 9, f)
        if f < 16:
            return -1 + 2 * smooth(10, 15, f)
        return 1 - smooth(16, 29, f)

    def fn(f):
        e = env(f)
        p = Pose()
        charge, hit = max(-e, 0.0), max(e, 0.0)
        if c.fam == "biped":
            hang(c, p, 0.0)
            for l in c.limbs:
                if l["kind"] == "arm" and l["side"] < 0:
                    L = l["length"]
                    p.add_loc(l["name"], Vector((l["side"] * -0.1 * L * 0, 0, 0)) + UP * (0.85 * L * (charge * 0.5 + hit)) + FWD * (-0.35 * L * charge + 1.05 * L * hit) + Vector((0.55 * L, 0, 0)))
            p.add_rot(c.torso, z=math.radians(22) * charge - math.radians(25) * hit, x=math.radians(10) * hit)
            p.add_loc(c.torso, UP * (-0.05 * H * charge) + FWD * (0.06 * H * hit))
        else:
            Lm = c.Lm if c.fam == "quad" else H
            p.add_loc(c.torso, UP * (-0.06 * Lm * charge) + (-FWD) * (0.10 * Lm * charge) + FWD * (0.20 * Lm * hit))
            for n in c.spine:
                p.add_rot(n, x=-math.radians(10) * charge + math.radians(8) * hit)
            for n in c.neck:
                p.add_rot(n, x=-math.radians(18) * charge + math.radians(28) * hit)
            if c.fam == "bird":
                for s, names in c.wings.items():
                    sg = 1 if s == "L" else -1
                    for n in names[:1]:
                        p.add_rot(n, y=sg * (-math.radians(55) * charge + math.radians(15) * hit))
            if c.fam == "fish":
                body_wave(c, p, charge * 0.25 + hit * 0.05, 0.9 * charge + 0.2 * hit, 0.5)
            for i, n in enumerate(c.tail):
                p.add_rot(n, x=math.radians(10) * charge + math.radians(5) * hit, z=math.radians(10) * math.sin(0.4 * f - i))
        return p
    return N, False, fn


def anim_faint(c, D, hover, kz=0.5):
    """35 frame, 3 fasi: 1-10 stordimento, 11-25 cedimento, 26-35 impatto + assestamento. No loop."""
    N, H = 35, c.H
    fam = c.fam

    def drop(f):  # frazione di caduta 0..1 (fase 2), con micro-rimbalzo in fase 3
        if f < 10:
            return 0.0
        if f <= 25:
            return smooth(10, 25, f) if fam != "bird" else (smooth(10, 25, f)) ** 1.6
        return 1.0

    def bounce(f):  # micro-rimbalzi decrescenti del torace dopo il contatto (frame 26-35), mai sotto terra
        if f < 25:
            return 0.0
        t = (f - 25) / 10.0
        return 0.03 * H * abs(math.sin(math.pi * t * 1.5)) * (1 - t) ** 1.5

    def fn(f):
        p = Pose()
        dr = drop(f)
        stun = 1 - smooth(8, 12, f)  # fase 1 (stordimento)
        recoil = math.sin(math.pi * min(f / 10.0, 1.0))
        wob = math.sin(f * 1.1) * stun * recoil
        z = hover * (1 - dr) - D * dr + bounce(f)
        y = (0.07 * H * recoil if f < 14 else 0.07 * H * (1 - smooth(10, 25, f)) * recoil)
        p.add_loc(c.torso, UP * z + (-FWD) * (y))
        lag = lambda k: max(f - k, 0)  # ritardo 2-3 frame per coda/orecchie/zampe
        if fam == "biped":
            p.add_rot(c.torso, x=math.radians(8) * dr)
            for n in c.spine:
                if n == "chest":
                    p.add_rot(n, x=-math.radians(10) * recoil * stun + math.radians(38) * dr, z=math.radians(10) * wob)
            for n in c.neck:
                p.add_rot(n, x=math.radians(20) * dr, z=math.radians(22) * wob)
            for l in c.limbs:
                if l["kind"] == "arm":
                    L = l["length"]
                    p.add_loc(l["name"], Vector((-l["side"] * 0.85 * L, 0, -0.95 * L)) + FWD * (0.3 * L * dr) + UP * (-0.1 * L * dr) * 0)
                else:
                    p.add_loc(l["name"], Vector((l["side"] * 0.04 * H * dr, 0, 0)) + FWD * (0.10 * H * dr) + UP * (kz * D * dr))
        else:
            for n in c.spine:
                p.add_rot(n, x=-math.radians(12) * recoil * stun + (math.radians(10) * dr if n == "chest" else math.radians(-4) * dr))
            for n in c.neck:
                p.add_rot(n, x=-math.radians(10) * recoil * stun + math.radians(18) * dr, z=math.radians(20) * wob)
            for l in c.limbs:
                if fam == "quad" and kz < 0:  # arti stesi a terra: avanti (anteriori) / indietro (posteriori)
                    h = max(l["root"].z - D, 0.02 * H)
                    reach = math.sqrt(max(l["length"] ** 2 - h * h, 0.0)) * 0.9
                    dirv = Vector((l["side"] * 0.5, -1.0 if l["kind"] == "front" else 1.0, 0)).normalized()
                    p.add_loc(l["name"], dirv * (reach * dr))
                    continue
                sp = (0.10 if fam == "quad" else 0.05) * H * dr
                p.add_loc(l["name"], Vector((l["side"] * sp, 0, 0)) + (UP * (hover * (1 - dr) * 0.9) if fam != "quad" else UP * (kz * D * dr)))
            if fam == "bird":
                for s, names in c.wings.items():
                    sg = 1 if s == "L" else -1
                    for i, n in enumerate(names):
                        k = lag(i * 1)
                        p.add_rot(n, y=sg * (math.radians(25) * smooth(8, 25, k) + math.radians(35 + 10 * i) * smooth(12, 28, k)),
                                  z=sg * math.radians(15) * dr)
            if fam == "fish":
                body_wave(c, p, f / 35.0, 0.5 * (1 - dr) + 0.1, 0.5, turns=2.0)
                for s, names in c.sidefins.items():
                    for n in names:
                        p.add_rot(n, y=(1 if s == "L" else -1) * math.radians(35) * smooth(12, 28, lag(2)))
        # secondarie in ritardo: coda, orecchie, (zampe nel bounce)
        for i, n in enumerate(c.tail):
            k = lag(2 + i)
            p.add_rot(n, x=math.radians(18) * smooth(10, 25, k) - 1.2 * (bounce(k) / max(H, 1e-6)) * 3, z=math.radians(10) * math.sin(0.5 * k) * (1 - smooth(10, 35, k)))
        for n in c.ears:
            p.add_rot(n, x=math.radians(20) * smooth(10, 25, lag(3)) + 2.0 * bounce(lag(3)) / H)
        return p
    return N, False, fn


# ----------------------------------------------------------------------------- baking, NLA

def bake(c, name, N, loop, fn, bones_all=()):
    rig = c.rig
    ad = rig.animation_data_create()
    act = bpy.data.actions.new(name)
    ad.action = act
    last = N + (1 if loop else 0) - 1
    for f in range(0, last + 1):
        pose = fn(f)
        applica_posa(c, pose)
        fr = 1 + f
        for b in set(pose.loc) | set(pose.rot) | set(bones_all):
            pb = c.pb[b]
            pb.keyframe_insert("location", frame=fr, group=b)
            pb.keyframe_insert("rotation_euler", frame=fr, group=b)
    for fc in action_fcurves(act):
        for kp in fc.keyframe_points:
            kp.interpolation = "BEZIER"
            kp.handle_left_type = "AUTO_CLAMPED"
            kp.handle_right_type = "AUTO_CLAMPED"
        fc.update()
    act.use_frame_range = True
    act.frame_start = 1
    act.frame_end = N if loop else N  # i cicli: frame N+1 (duplicato del primo) resta fuori range
    act["loop"] = bool(loop)
    ad.action = None
    for pb in c.pb:
        pb.location = (0, 0, 0)
        pb.rotation_euler = (0, 0, 0)
    return act


def push_nla(rig, act, name):
    ad = rig.animation_data_create()
    tr = ad.nla_tracks.new()
    tr.name = name
    st = tr.strips.new(name, 1, act)
    st.name = name
    return tr


def calibra_caduta(c, hover):
    """Bisezione sulla discesa D del torace (tronco a terra a fine KO), poi sceglie quanto raccogliere le zampe
    in modo che nessun vertice finisca sotto Z=0."""
    H = c.H
    flyer = c.fam in ("bird", "fish")
    lo, hi = (-0.5 * H if flyer else 0.0), 0.95 * H
    target = (0.015 if flyer else 0.004) * H

    def minz(D, k=0.5, idx=0 if flyer else 1):
        _, _, fn = anim_faint(c, D, hover, k)
        m = 1e9
        for fr in (18, 24, 28, 34):  # discesa, contatto, rimbalzo, assestamento
            applica_posa(c, fn(fr))
            m = min(m, trunk_minz(c)[idx])
        return m
    if minz(hi) > target:
        D = hi
    else:
        for _ in range(18):
            mid = (lo + hi) / 2
            if minz(mid) > target:
                lo = mid
            else:
                hi = mid
        D = lo
    k = 1.0
    for kk in ((1.0,) if flyer else (0.3, 0.45, 0.6, 0.8)):
        k = kk
        if minz(D, kk, 0) >= -0.008 * H or flyer:
            return D, k
    if c.fam == "quad":  # il raccoglimento non basta: arti stesi a terra
        return D, -1.0
    return D, 1.0


def crea_animazioni(c):
    fam = c.fam
    hover = (c.args.altezza_aria * c.H) if fam in ("bird", "fish") else 0.0
    D, kz = calibra_caduta(c, hover)
    log(f"KO: discesa torace D={D:.3f} (H={c.H:.3f}), zampe raccolte k={kz}, quota iniziale {hover:.3f}")
    nome_loc = c.args.nome_locomozione or LOCOMOZIONE[fam]
    specs = [
        ("idle", anim_idle(c)),
        (nome_loc, anim_locomozione(c, False)),
        ("run", anim_locomozione(c, True)),
        ("attack_1", anim_attack(c)),
        ("faint", anim_faint(c, D, hover, kz)),
    ]
    def con_quota(fn):
        if not hover:
            return fn

        def g(f):
            p = fn(f)
            p.add_loc(c.torso, UP * hover)
            for l in c.limbs:
                p.add_loc(l["name"], UP * hover)
            return p
        return g
    specs = [(n, (N, lp, fn if n == "faint" else con_quota(fn))) for n, (N, lp, fn) in specs]
    acts = {}
    union = set()
    for _, (N, loop, fn) in specs:  # ogni azione deve chiavare lo stesso insieme di ossa (niente pose residue)
        for fr in (0, N // 3, N - 1):
            ps = fn(fr)
            union |= set(ps.loc) | set(ps.rot)
    for name, (N, loop, fn) in specs:
        acts[name] = bake(c, name, N, loop, fn, union)
        push_nla(c.rig, acts[name], name)
        log(f"azione {name}: {N} frame, loop={loop}")
    c.rig.animation_data.action = None
    bpy.context.view_layer.update()
    return list(acts), D


# ----------------------------------------------------------------------------- materiale

def prepara_materiale(mesh):
    rep = []
    for slot in mesh.material_slots:
        m = slot.material
        if not m or not m.use_nodes:
            rep.append("materiale senza nodi")
            continue
        bsdf = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            rep.append("manca Principled BSDF")
            continue
        for l in list(bsdf.inputs["Alpha"].links):
            m.node_tree.links.remove(l)
        bsdf.inputs["Alpha"].default_value = 1.0
        try:
            m.surface_render_method = "DITHERED"
        except Exception:
            pass
        link = bsdf.inputs["Base Color"].links
        img = link[0].from_node if link else None
        rep.append(f"{m.name}: base color <- {img.image.name if img is not None and img.type == 'TEX_IMAGE' and img.image else 'NON COLLEGATA A UNA TEXTURE'}")
    return rep


# ----------------------------------------------------------------------------- validazione

def valida(c, uv0, azioni, D):
    rig, mesh, H = c.rig, c.mesh, c.H
    res = []

    def chk(nome, ok, dett="", bloccante=True):
        res.append({"controllo": nome, "ok": bool(ok) or not bloccante, "avviso": not ok and not bloccante, "dettaglio": dett})
        log(("PASS " if ok else "FAIL " if bloccante else "WARN ") + nome + (f" - {dett}" if dett else ""))

    uv1 = uv_signature(mesh)
    chk("UV invariate rispetto a TRELLIS", uv0 == uv1, f"{uv1['sha256'][:12]}" if uv1 else "nessuna UV")
    req = {"idle", "run", "attack_1", "faint", c.args.nome_locomozione or LOCOMOZIONE[c.fam]}
    tracks = {t.name for t in rig.animation_data.nla_tracks}
    chk("tracce NLA obbligatorie", req <= tracks, f"mancano {sorted(req - tracks)}" if not req <= tracks else sorted(tracks))
    bad = 0
    tot = 0
    for name in azioni:
        for fc in action_fcurves(bpy.data.actions[name]):
            for kp in fc.keyframe_points:
                tot += 1
                if not (kp.interpolation == "BEZIER" and kp.handle_left_type == "AUTO_CLAMPED" and kp.handle_right_type == "AUTO_CLAMPED"):
                    bad += 1
    chk("F-Curve Bezier + auto_clamped", bad == 0 and tot > 0, f"{tot} keyframe, {bad} non conformi")
    chk("faint senza loop", not bpy.data.actions["faint"].get("loop") and not any(m.type == "CYCLES" for fc in action_fcurves(bpy.data.actions["faint"]) for m in fc.modifiers))
    chk("transform applicate (scala 1.0)", all(tuple(round(v, 6) for v in o.scale) == (1, 1, 1) and all(abs(v) < 1e-6 for v in o.rotation_euler) for o in (mesh, rig)))
    chk("pesi: max 4 influenze, normalizzati", all(len(v.groups) <= 4 for v in mesh.data.vertices) and
        all(abs(sum(g.weight for g in v.groups) - 1) < 1e-2 for v in mesh.data.vertices if len(v.groups)))
    mat = prepara_materiale(mesh)
    chk("materiale opaco con Base Color da texture", mat and all("NON COLLEGATA" not in m and "manca" not in m and "senza" not in m for m in mat), "; ".join(mat))
    # campionamento delle animazioni: contatto col suolo, diagonali, attraversamento arti
    ad = rig.animation_data
    tol = 0.025 * H
    for name in azioni:
        act = bpy.data.actions[name]
        trk = next(t for t in ad.nla_tracks if t.name == name)
        for t in ad.nla_tracks:
            t.mute = t.name != name
        f0, f1 = int(act.frame_range[0]), int(act.frame_end)
        mins, effs = [], {l["name"]: [] for l in c.limbs}
        for f in range(f0, f1 + 1, 1):
            bpy.context.scene.frame_set(f)
            bpy.context.view_layer.update()
            mins.append(trunk_minz(c)[0])
            rev = rig.evaluated_get(bpy.context.evaluated_depsgraph_get())
            for l in c.limbs:
                effs[l["name"]].append((rev.matrix_world @ rev.pose.bones[l["name"]].head).copy())
        floor = min(mins)
        chk(f"{name}: nessun vertice sotto Z=0", floor >= -tol, f"min Z={floor:.4f} (tol {-tol:.4f})")
        if c.fam == "quad" and name == (c.args.nome_locomozione or LOCOMOZIONE["quad"]):
            fl = [l for l in c.limbs if l["kind"] == "front" and l["side"] > 0]
            hr = [l for l in c.limbs if l["kind"] == "hind" and l["side"] < 0]
            fr = [l for l in c.limbs if l["kind"] == "front" and l["side"] < 0]
            if fl and hr and fr:
                a = np.array([e.y for e in effs[fl[0]["name"]]])
                b = np.array([e.y for e in effs[hr[0]["name"]]])
                d = np.array([e.y for e in effs[fr[0]["name"]]])
                ca, cd = np.corrcoef(a, b)[0, 1], np.corrcoef(a, d)[0, 1]
                chk("trotto diagonale (ant.SX~post.DX, ant.SX!~ant.DX)", ca > 0.9 and cd < -0.5, f"corr diag={ca:.2f}, corr laterale={cd:.2f}")
            else:
                chk("trotto diagonale: 4 arti rilevati", False, f"limbs={[(l['name'], l['kind']) for l in c.limbs]}")
        if c.fam in ("quad", "biped") and name != "faint":
            cross = 0.0
            for l in c.limbs:
                if l["kind"] in ("leg", "front", "hind"):
                    xs = np.array([e.x for e in effs[l["name"]]]) * l["side"]
                    cross = max(cross, float(-xs.min()))
            chk(f"{name}: nessun arto attraversa il piano mediano", cross < 0.04 * H, f"max {cross:.4f}")
    for t in ad.nla_tracks:
        t.mute = False
    bpy.context.scene.frame_set(1)
    # densita' vertici alle giunture (euristica: la topologia vera va guardata a mano)
    co = mesh_coords(mesh)
    giunti = [b for b in rig.data.bones if b.name.startswith("DEF-") and re.search(r"(shin|forearm|lower_leg|thigh|upper_arm)", b.name) and not re.search(r"\.\d+$", b.name)]
    poveri = []
    for b in giunti:
        n = int((np.linalg.norm(co - np.array(b.head_local), axis=1) < 0.08 * H).sum())
        if n < 40:
            poveri.append((b.name, n))
    chk("densita' vertici ai giunti (euristica, ricontrolla a mano)", not poveri, str(poveri[:6]), bloccante=False)
    return res


# ----------------------------------------------------------------------------- export

def esporta(c, out_dir, nome):
    os.makedirs(out_dir, exist_ok=True)
    deselect_all()
    c.mesh.select_set(True)
    c.rig.select_set(True)
    bpy.context.view_layer.objects.active = c.rig
    c.rig.animation_data.action = None
    path = os.path.join(out_dir, f"{nome}.glb")
    bpy.ops.export_scene.gltf(
        filepath=path, export_format="GLB", use_selection=True,
        export_animations=True, export_animation_mode="NLA_TRACKS", export_extra_animations=False,
        export_def_bones=True, export_materials="EXPORT", export_skins=True, export_apply=False,
        export_force_sampling=True, export_optimize_animation_size=False, export_yup=True)
    return path


def verifica_glb(path, atteso, uv_set):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=path)
    arm = [o for o in bpy.data.objects if o.type == "ARMATURE"]
    anims = sorted({a.name.split("|")[-1] for a in bpy.data.actions})
    ctl = [b.name for o in arm for b in o.data.bones if b.name.startswith(("MCH", "ORG", "VIS"))]
    mesh = max((o for o in bpy.data.objects if o.type == "MESH"), key=lambda o: len(o.data.vertices))
    imgs = [i.name for i in bpy.data.images]
    r = {"animazioni": anims, "ossa_controllo_residue": len(ctl), "ossa": sum(len(o.data.bones) for o in arm),
         "texture": imgs, "mesh_verts": len(mesh.data.vertices), "uv_identiche": uv_set_hash(mesh) == uv_set}
    ok = set(atteso) <= set(anims) and not ctl and bool(imgs) and r["uv_identiche"]
    log("riapertura GLB:", r, "OK" if ok else "PROBLEMA")
    return ok, r


# ----------------------------------------------------------------------------- main

def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--glb", required=True)
    ap.add_argument("--categoria", required=True, choices=list(CATEGORIE))
    ap.add_argument("--nome", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--ruota-z", type=float, default=0.0, dest="ruota_z")
    ap.add_argument("--nome-locomozione", default=None, dest="nome_locomozione")
    ap.add_argument("--altezza-aria", type=float, default=0.5, dest="altezza_aria",
                    help="quota iniziale del KO per volanti/pesci, in multipli dell'altezza")
    ap.add_argument("--zampe-anteriori", action="store_true", dest="zampe_anteriori",
                    help="solo volatile: aggiunge due zampe anteriori al meta-rig Bird (creature alate a 4 zampe)")
    ap.add_argument("--salva-prefit", action="store_true", help="salva .blend dopo il fit del meta-rig e si ferma")
    ap.add_argument("--forza-export", action="store_true", help="esporta anche se la validazione fallisce (sconsigliato)")
    args = ap.parse_args(argv)
    preset, fam = CATEGORIE[args.categoria]
    out = os.path.join(args.out, args.nome)
    os.makedirs(out, exist_ok=True)

    mesh = importa_glb(args.glb, args.ruota_z)
    mesh.name = mesh.data.name = args.nome
    uv0 = uv_signature(mesh)
    log("UV TRELLIS:", uv0)
    meta = crea_e_adatta_metarig(mesh, preset, fam, args.zampe_anteriori)
    if args.salva_prefit:
        bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, f"{args.nome}_prefit.blend"))
        log("salvato prefit: adatta le ossa a mano e rilancia con il .blend")
        return 0
    rig = genera_rig(meta, args.nome)
    skin(mesh, rig)
    limiti_rotazione(rig)
    c = prepara_ctx(rig, mesh, fam, args)
    azioni, D = crea_animazioni(c)
    res = valida(c, uv0, azioni, D)
    ok = all(r["ok"] for r in res)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.join(out, f"{args.nome}.blend"))
    report = {"nome": args.nome, "categoria": args.categoria, "preset": preset, "validazione": res, "ok": ok}
    if ok or args.forza_export:
        glb = esporta(c, out, args.nome)
        ok2, r2 = verifica_glb(glb, azioni, uv0["set"])
        report.update({"glb": glb, "riapertura": r2, "riapertura_ok": ok2})
        ok = ok and ok2
    else:
        log("VALIDAZIONE FALLITA: nessun export (regola: nessun asset esportato prima della checklist)")
    report["ok"] = ok
    with open(os.path.join(out, "report.json"), "w") as f:
        json.dump(report, f, indent=1, default=str)
    return 0 if ok else 2


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    sys.exit(main(argv))
