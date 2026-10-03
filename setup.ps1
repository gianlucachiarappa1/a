# Setup per Windows 11 + GPU NVIDIA RTX serie 50 (Blackwell).
# Uso (PowerShell, nella cartella del progetto):
#   powershell -ExecutionPolicy Bypass -File setup.ps1
# Prerequisiti: Python 3.11 (python.org, "py" launcher), Git, driver NVIDIA aggiornato.

$ErrorActionPreference = "Stop"
$TripoSRCommit = "107cefdc244c39106fa830359024f6a2f1c78871"

function Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }

Step "Controllo prerequisiti"
& py -3.11 --version
if ($LASTEXITCODE -ne 0) { throw "Python 3.11 non trovato: installalo da python.org (spunta 'py launcher')." }
& git --version
if ($LASTEXITCODE -ne 0) { throw "Git non trovato: installalo da git-scm.com." }
& nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader
if ($LASTEXITCODE -ne 0) { throw "nvidia-smi non trovato: installa/aggiorna il driver NVIDIA." }

if (-not (Test-Path ".venv")) {
    Step "Creo l'ambiente virtuale .venv"
    & py -3.11 -m venv .venv
}
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --upgrade pip

Step "Installo PyTorch con CUDA 12.8 (necessario per RTX 50 / sm_120)"
& $py -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu128
if ($LASTEXITCODE -ne 0) { throw "Installazione di PyTorch fallita." }

if (-not (Test-Path "third_party\TripoSR")) {
    Step "Scarico TripoSR"
    & git clone https://github.com/VAST-AI-Research/TripoSR third_party/TripoSR
}
& git -C third_party/TripoSR checkout --quiet $TripoSRCommit

Step "Installo le dipendenze"
& $py -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw "Installazione delle dipendenze fallita." }

Step "Verifico la GPU"
& $py scripts/check_gpu.py
if ($LASTEXITCODE -ne 0) { throw "La GPU non e' utilizzabile da PyTorch (vedi messaggio sopra)." }

Write-Host "`nSetup completato. Prova:" -ForegroundColor Green
Write-Host "  .\.venv\Scripts\activate"
Write-Host "  python generate.py third_party\TripoSR\examples\chair.png"
