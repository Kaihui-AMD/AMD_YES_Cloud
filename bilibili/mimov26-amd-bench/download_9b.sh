#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODEL_DIR="$ROOT_DIR/models"
REPO_URL="https://huggingface.co/ggml-org/MiMo-V2.6-Distill-Qwen-9B-GGUF/resolve/main"

mkdir -p "$MODEL_DIR"

download_file() {
    local filename="$1"
    local expected_sha="$2"
    local target="$MODEL_DIR/$filename"

    if [[ -f "$target" ]] && [[ "$(sha256sum "$target" | cut -d' ' -f1)" == "$expected_sha" ]]; then
        printf 'Already verified: %s\n' "$filename"
        return
    fi

    curl -L --fail --retry 5 --retry-delay 3 --continue-at - \
        --output "$target" \
        "$REPO_URL/$filename"
}

download_file \
    "MiMo-V2.6-Distill-Qwen-9B-Q8_0.gguf" \
    "e4956751699c607007c0e10d13a0e1f3ac251f38fc7f67bde5da90d4614a62f6"

download_file \
    "mmproj-MiMo-V2.6-Distill-Qwen-9B-Q8_0.gguf" \
    "9886d16a1fba868e55f1df0da6ccfce1f39dea61a4f9428379c7fae810a070e3"

(
    cd "$MODEL_DIR"
    sha256sum -c SHA256SUMS.9b
)
