#!/usr/bin/env bash
# Esegue la pipeline su mesh finte (una per preset Rigify) e riassume i risultati.
# Richiede: python3.11 con `pip install bpy` (oppure Blender: sostituisci PY con "blender -b --python-exit-code 1 --python").
set -u
PY=${PY:-python3}
OUT=${OUT:-/tmp/pipeline_test}
mkdir -p "$OUT"
for spec in "wolf quadrupede" "cat felino" "horse equino" "bird volatile" "shark pesce" "human bipede" "basic_human bipede_basic" "basic_quadruped quadrupede_basic"; do
  set -- $spec
  $PY tests/make_fake_trellis.py -- "$1" "$OUT/$1.glb" 1.0 >/dev/null 2>&1
  if $PY strumenti/pipeline_creatura.py --glb "$OUT/$1.glb" --categoria "$2" --nome "$1" --out "$OUT/out" >"$OUT/$1.log" 2>&1; then
    echo "PASS $1"
  else
    echo "FAIL $1 ($(grep -c '\] FAIL' "$OUT/$1.log") controlli) - vedi $OUT/$1.log"
  fi
done
