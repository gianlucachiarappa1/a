"""Verifica che PyTorch veda la GPU e supporti la sua architettura (RTX 50 = sm_120)."""

import sys

import torch

print(f"PyTorch {torch.__version__}  (CUDA build: {torch.version.cuda})")
if not torch.cuda.is_available():
    sys.exit("ERRORE: CUDA non disponibile. Aggiorna il driver NVIDIA e reinstalla torch con setup.ps1.")

name = torch.cuda.get_device_name(0)
major, minor = torch.cuda.get_device_capability(0)
vram = torch.cuda.get_device_properties(0).total_memory / 1024**3
print(f"GPU: {name}  |  compute capability {major}.{minor}  |  VRAM {vram:.1f} GB")

arch = f"sm_{major}{minor}"
if arch not in torch.cuda.get_arch_list():
    sys.exit(
        f"ERRORE: questa build di PyTorch non include {arch}. "
        "Per le RTX 50 serve torch >= 2.7 con CUDA 12.8 (index-url .../whl/cu128)."
    )

x = torch.randn(2048, 2048, device="cuda")
torch.cuda.synchronize()
print(f"Test matmul OK ({(x @ x).sum().item():.1f}).")
if vram < 7.5:
    print("Attenzione: meno di 8 GB di VRAM, usa --chunk-size 4096 se finisci la memoria.")
print("Tutto pronto.")
