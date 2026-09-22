#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_ROOT="${LLAMA_ROOT:-$ROOT_DIR/llama.cpp}"
BUILD_DIR="${BUILD_DIR:-$LLAMA_ROOT/build-rocm}"
MODEL="${MODEL:-$ROOT_DIR/models/MiMo-V2.6-Distill-Qwen-9B-Q8_0.gguf}"
MMPROJ="${MMPROJ:-$ROOT_DIR/models/mmproj-MiMo-V2.6-Distill-Qwen-9B-Q8_0.gguf}"
GPU="${GPU:-0}"
IMAGE="${1:?usage: $0 IMAGE [PROMPT]}"
PROMPT="${2:-请准确读取并概括图片中的主要信息。}"

export LD_LIBRARY_PATH="$BUILD_DIR/bin:/opt/rocm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ROCR_VISIBLE_DEVICES="$GPU"
export GGML_CUDA_DISABLE_GRAPHS=1

exec "$BUILD_DIR/bin/llama-cli" \
    -m "$MODEL" \
    -mm "$MMPROJ" \
    --image "$IMAGE" \
    --mmproj-offload \
    -mmdev ROCm0 \
    -ngl 99 \
    -sm none \
    -mg 0 \
    -dev ROCm0 \
    -fa off \
    -c 8192 \
    -b 512 \
    -ub 64 \
    -t 96 \
    -n 384 \
    -st \
    --reasoning off \
    --reasoning-format none \
    --temp 0.2 \
    --top-p 0.95 \
    --no-display-prompt \
    --no-warmup \
    --simple-io \
    -p "$PROMPT"
