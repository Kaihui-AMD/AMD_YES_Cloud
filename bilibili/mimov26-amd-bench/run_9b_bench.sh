#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_ROOT="${LLAMA_ROOT:-$ROOT_DIR/llama.cpp}"
BUILD_DIR="${BUILD_DIR:-$LLAMA_ROOT/build-rocm}"
MODEL="${MODEL:-$ROOT_DIR/models/MiMo-V2.6-Distill-Qwen-9B-Q8_0.gguf}"
GPU="${GPU:-0}"
REPETITIONS="${REPETITIONS:-5}"

export LD_LIBRARY_PATH="$BUILD_DIR/bin:/opt/rocm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ROCR_VISIBLE_DEVICES="$GPU"
# Qwen3.5 decode and larger prefill were unstable with HIP graphs on this host.
export GGML_CUDA_DISABLE_GRAPHS=1

COMMON_ARGS=(
    -m "$MODEL"
    -ngl 99
    -sm none
    -mg 0
    -dev ROCm0
    -fa on
    -t 96
    --progress
)

"$BUILD_DIR/bin/llama-bench" "${COMMON_ARGS[@]}" \
    -b 512 -ub 512 -p 512 -n 0 -r "$REPETITIONS"

"$BUILD_DIR/bin/llama-bench" "${COMMON_ARGS[@]}" \
    -b 512 -ub 512 -p 2048 -n 0 -r "$REPETITIONS"

"$BUILD_DIR/bin/llama-bench" "${COMMON_ARGS[@]}" \
    -b 64 -ub 64 -p 0 -n 128 -r "$REPETITIONS"
