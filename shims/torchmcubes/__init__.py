"""Drop-in replacement for `torchmcubes.marching_cubes`, backed by scikit-image.

TripoSR imports `torchmcubes`, which has to be compiled from source against the
local CUDA toolkit. On Windows with an RTX 50 (Blackwell, sm_120) GPU that build
is fragile, so we replace it with scikit-image. Marching cubes runs once per
asset on a 256^3 grid, so running it on the CPU costs about a second.

Contract matched from torchmcubes: `marching_cubes(volume, threshold)` returns
`(verts, faces)` as torch tensors, with vertex coordinates in (x, y, z) order,
where x indexes the *last* axis of `volume`. TripoSR then swaps them back with
`v_pos[..., [2, 1, 0]]`.
"""

import numpy as np
import torch
from skimage import measure


def marching_cubes(volume: torch.Tensor, threshold: float):
    vol = volume.detach().float().cpu().numpy()
    try:
        verts, faces, _, _ = measure.marching_cubes(vol, level=threshold)
    except (ValueError, RuntimeError):
        # No surface crosses the threshold (e.g. empty/degenerate prediction).
        return (
            torch.zeros((0, 3), dtype=torch.float32),
            torch.zeros((0, 3), dtype=torch.long),
        )
    verts = np.ascontiguousarray(verts[:, ::-1])
    return (
        torch.from_numpy(verts.astype(np.float32)),
        torch.from_numpy(faces.astype(np.int64)),
    )
