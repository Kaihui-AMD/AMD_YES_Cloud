#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_ROOT="${LLAMA_ROOT:-$ROOT_DIR/llama.cpp}"
BUILD_DIR="${BUILD_DIR:-$LLAMA_ROOT/build-rocm}"
MODEL="${MODEL:-$ROOT_DIR/models/MiMo-V2.6-Distill-Qwen-9B-Q8_0.gguf}"
MMPROJ="${MMPROJ:-$ROOT_DIR/models/mmproj-MiMo-V2.6-Distill-Qwen-9B-Q8_0.gguf}"
GPU="${GPU:-0}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8080}"
CTX="${CTX:-8192}"
PARALLEL="${PARALLEL:-1}"
ALIAS="${ALIAS:-mimo-v2.6-distill-9b}"

export LD_LIBRARY_PATH="$BUILD_DIR/bin:/opt/rocm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ROCR_VISIBLE_DEVICES="$GPU"
export GGML_CUDA_DISABLE_GRAPHS=1

exec "$BUILD_DIR/bin/llama-server" \
    -m "$MODEL" \
    -mm "$MMPROJ" \
    --mmproj-offload \
    -mmdev ROCm0 \
    -ngl 99 \
    -sm none \
    -mg 0 \
    -dev ROCm0 \
    -fa on \
    -c "$CTX" \
    -b 512 \
    -ub 64 \
    -t 96 \
    -np "$PARALLEL" \
    --host "$HOST" \
    --port "$PORT" \
    --alias "$ALIAS" \
    --jinja \
    --reasoning-format deepseek \
    --reasoning auto \
    --metrics
