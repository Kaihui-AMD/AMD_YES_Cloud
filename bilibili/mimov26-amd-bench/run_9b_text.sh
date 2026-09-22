#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LLAMA_ROOT="${LLAMA_ROOT:-$ROOT_DIR/llama.cpp}"
BUILD_DIR="${BUILD_DIR:-$LLAMA_ROOT/build-rocm}"
MODEL="${MODEL:-$ROOT_DIR/models/MiMo-V2.6-Distill-Qwen-9B-Q8_0.gguf}"
GPU="${GPU:-0}"
PROMPT="${1:-请用 Python 实现一个线程安全的 LRU Cache，要求 get 和 put 平均 O(1)，容量为 0 时行为正确。先简要说明设计，再给出完整代码和三个覆盖边界条件的测试。回答尽量简洁。}"

export LD_LIBRARY_PATH="$BUILD_DIR/bin:/opt/rocm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
export ROCR_VISIBLE_DEVICES="$GPU"
export GGML_CUDA_DISABLE_GRAPHS=1

exec "$BUILD_DIR/bin/llama-cli" \
    -m "$MODEL" \
    -ngl 99 \
    -sm none \
    -mg 0 \
    -dev ROCm0 \
    -fa off \
    -c 8192 \
    -b 512 \
    -ub 64 \
    -t 96 \
    -n 1024 \
    -st \
    --reasoning on \
    --reasoning-format none \
    --reasoning-budget 256 \
    --temp 0.6 \
    --top-p 0.95 \
    --no-display-prompt \
    --no-warmup \
    --simple-io \
    -p "$PROMPT"
