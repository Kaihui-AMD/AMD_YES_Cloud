#!/usr/bin/env bash
set -Eeuo pipefail

COMFY_DIR="${COMFY_DIR:-/root/ComfyUI}"
VENV_DIR="${VENV_DIR:-/opt/venv}"
PORT="${PORT:-8188}"
START_TUNNEL="${START_TUNNEL:-1}"
SKIP_DOWNLOAD="${SKIP_DOWNLOAD:-0}"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="${COMFY_DIR}/comfyui.log"
PID_FILE="${COMFY_DIR}/comfyui.pid"
WORKFLOW_NAME="COMFY_ORG_OFFICIAL_MiniMax_H3_INT8_AMD.json"

DIFFUSION_REL="diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors"
TEXT_ENCODER_REL="text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
VIDEO_VAE_REL="vae/minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE_REL="vae/minimax_h3_audio_vae_fp32.safetensors"
TURBO_LORA_REL="loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors"

declare -A EXPECTED_SIZE=(
  ["${DIFFUSION_REL}"]=20970379616
  ["${TEXT_ENCODER_REL}"]=27141342152
  ["${VIDEO_VAE_REL}"]=5207808496
  ["${AUDIO_VAE_REL}"]=605254808
  ["${TURBO_LORA_REL}"]=1956193000
)

declare -A EXPECTED_SHA=(
  ["${DIFFUSION_REL}"]=e889202c41dafb67b10d67b97f0d8541508036a6090af23425a5c2615d03c47a
  ["${TEXT_ENCODER_REL}"]=bc2ced0fbea64757fa9acddccfc0b3f4819d1dcf1da6c124d690d368be283923
  ["${VIDEO_VAE_REL}"]=7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522
  ["${AUDIO_VAE_REL}"]=8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48
  ["${TURBO_LORA_REL}"]=2339acdf19bfe123f46b971ea35d367a84adb85de43627e1eceafa5a5b2b111e
)

log() {
  printf '\n[%s] %s\n' "$(date '+%F %T')" "$*"
}

die() {
  printf '\nERROR: %s\n' "$*" >&2
  exit 1
}

require_root() {
  [[ "$(id -u)" == "0" ]] || die "请使用 root 用户运行此脚本"
  [[ -x "${VENV_DIR}/bin/python" ]] || die "找不到 ${VENV_DIR}/bin/python"
  [[ -x "${VENV_DIR}/bin/pip" ]] || die "找不到 ${VENV_DIR}/bin/pip"
}

load_notebook_environment() {
  if [[ -r /proc/1/environ ]]; then
    while IFS= read -r -d '' item; do
      case "$item" in
        HF_ENDPOINT=*|HF_TOKEN=*|HUGGING_FACE_HUB_TOKEN=*|FRP_*=*|RC_*=*)
          export "$item"
          ;;
      esac
    done </proc/1/environ
  fi
}

clone_or_update_comfyui() {
  if [[ -d "${COMFY_DIR}/.git" ]]; then
    log "检测到现有 ComfyUI，切换 origin 到 Comfy-Org 并尝试快进更新"
    local branch
    branch="$(git -C "${COMFY_DIR}" branch --show-current)"
    git -C "${COMFY_DIR}" remote set-url origin \
      https://github.com/Comfy-Org/ComfyUI.git
    git -c http.sslVerify=false -C "${COMFY_DIR}" fetch origin
    git -C "${COMFY_DIR}" pull --ff-only origin "${branch}" ||
      log "现有仓库无法快进，保留当前代码继续安装"
  elif [[ -e "${COMFY_DIR}" ]]; then
    die "${COMFY_DIR} 已存在但不是 Git 仓库，请先备份或设置其他 COMFY_DIR"
  else
    log "下载 Comfy-Org/ComfyUI"
    git -c http.sslVerify=false clone --depth 1 \
      https://github.com/Comfy-Org/ComfyUI.git \
      "${COMFY_DIR}"
  fi
}

disable_custom_nodes() {
  local custom_dir="${COMFY_DIR}/custom_nodes"
  local backup_dir="${COMFY_DIR}/custom_nodes_disabled_$(date '+%Y%m%d_%H%M%S')"
  local moved=0

  mkdir -p "${custom_dir}"

  while IFS= read -r -d '' path; do
    local name
    name="$(basename "$path")"
    case "$name" in
      example_node.py.example|websocket_image_save.py|__pycache__)
        continue
        ;;
    esac
    if [[ "$moved" == "0" ]]; then
      mkdir -p "${backup_dir}"
    fi
    mv "$path" "${backup_dir}/"
    moved=1
  done < <(find "${custom_dir}" -mindepth 1 -maxdepth 1 -print0)

  if [[ "$moved" == "1" ]]; then
    log "已将第三方 custom nodes 移到 ${backup_dir}"
  else
    log "未发现需要禁用的第三方 custom nodes"
  fi
}

install_dependencies() {
  log "安装 ComfyUI 官方依赖"
  "${VENV_DIR}/bin/pip" install -r "${COMFY_DIR}/requirements.txt"

  if [[ ! -x "${VENV_DIR}/bin/hf" ]]; then
    log "安装 Hugging Face CLI"
    "${VENV_DIR}/bin/pip" install "huggingface_hub[cli]"
  fi
}

download_models() {
  local models_dir="${COMFY_DIR}/models"

  mkdir -p \
    "${models_dir}/diffusion_models" \
    "${models_dir}/text_encoders" \
    "${models_dir}/vae" \
    "${models_dir}/loras"

  if [[ "${SKIP_DOWNLOAD}" == "1" ]]; then
    log "SKIP_DOWNLOAD=1，跳过模型下载"
    return
  fi

  log "下载 Comfy-Org 官方 MiniMax H3 模型，支持断点续传"
  if [[ -n "${HF_ENDPOINT:-}" ]]; then
    log "使用 HF_ENDPOINT=${HF_ENDPOINT}"
  fi

  "${VENV_DIR}/bin/hf" download Comfy-Org/MiniMax-H3 \
    "${DIFFUSION_REL}" \
    "${TEXT_ENCODER_REL}" \
    "${VIDEO_VAE_REL}" \
    "${AUDIO_VAE_REL}" \
    "${TURBO_LORA_REL}" \
    --local-dir "${models_dir}"
}

verify_models() {
  local rel

  log "校验模型文件大小和 SHA-256"
  for rel in \
    "${DIFFUSION_REL}" \
    "${TEXT_ENCODER_REL}" \
    "${VIDEO_VAE_REL}" \
    "${AUDIO_VAE_REL}" \
    "${TURBO_LORA_REL}"; do
    local path="${COMFY_DIR}/models/${rel}"
    local size
    local sha

    [[ -f "$path" ]] || die "模型不存在: ${path}"
    size="$(stat -c %s "$path")"
    [[ "$size" == "${EXPECTED_SIZE[$rel]}" ]] ||
      die "文件大小错误: ${path}, got=${size}, expected=${EXPECTED_SIZE[$rel]}"

    sha="$(sha256sum "$path" | awk '{print $1}')"
    [[ "$sha" == "${EXPECTED_SHA[$rel]}" ]] ||
      die "SHA-256错误: ${path}"

    printf 'OK  %s\n' "$path"
  done
}

install_workflows() {
  local workflow_dir="${COMFY_DIR}/user/default/workflows"

  mkdir -p "${workflow_dir}"

  "${VENV_DIR}/bin/python" - \
    "${workflow_dir}/${WORKFLOW_NAME}" <<'PY'
import json
import site
import sys
from pathlib import Path

gui_output = Path(sys.argv[1])

template = None
for package_dir in map(Path, site.getsitepackages()):
    candidate = (
        package_dir
        / "comfyui_workflow_templates_json"
        / "templates"
        / "video_minimax_h3_t2v.json"
    )
    if candidate.exists():
        template = candidate
        break

if template is None:
    raise SystemExit("找不到官方 video_minimax_h3_t2v.json 模板")

data = json.loads(template.read_text(encoding="utf-8"))

old_encoder = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
new_encoder = "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"

def replace(value):
    if isinstance(value, dict):
        return {key: replace(child) for key, child in value.items()}
    if isinstance(value, list):
        return [replace(child) for child in value]
    if isinstance(value, str):
        return value.replace(old_encoder, new_encoder)
    return value

data = replace(data)
gui_output.write_text(
    json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8",
)
PY

  "${VENV_DIR}/bin/python" -m json.tool "${workflow_dir}/${WORKFLOW_NAME}" >/dev/null

  log "已安装工作流 ${WORKFLOW_NAME}"
}

stop_existing_comfyui() {
  local pid
  pid="$(
    pgrep -f "^${VENV_DIR}/bin/python(3(\\.12)?)? (.*[/])?main.py --port ${PORT}( |$)" |
      head -1 || true
  )"
  if [[ -n "$pid" ]]; then
    log "停止端口 ${PORT} 的旧 ComfyUI，PID=${pid}"
    kill "$pid" || true
    for _ in $(seq 1 30); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    kill -0 "$pid" 2>/dev/null && kill -9 "$pid" || true
  fi
}

start_comfyui() {
  log "启动纯官方 ComfyUI，保留默认 smart memory"
  stop_existing_comfyui

  cd "${COMFY_DIR}"
  ulimit -n 65536
  nohup "${VENV_DIR}/bin/python" main.py \
    --port "${PORT}" \
    --listen 127.0.0.1 \
    --enable-cors-header \
    --enable-compress-response-body \
    --cache-none \
    >"${LOG_FILE}" 2>&1 </dev/null &

  echo "$!" >"${PID_FILE}"

  for _ in $(seq 1 120); do
    if curl -fsS "http://127.0.0.1:${PORT}/system_stats" >/dev/null 2>&1; then
      log "ComfyUI 已启动，PID=$(cat "${PID_FILE}")"
      return
    fi
    sleep 2
  done

  tail -160 "${LOG_FILE}" >&2 || true
  die "ComfyUI 启动失败"
}

verify_official_nodes() {
  local result
  result="$(
    curl -fsS "http://127.0.0.1:${PORT}/object_info" |
      "${VENV_DIR}/bin/python" -c '
import json, sys
d = json.load(sys.stdin)
required = [
    "UNETLoader",
    "CLIPLoader",
    "MiniMaxH3ImageToVideo",
    "VAEDecode",
    "VAEDecodeAudio",
    "CreateVideo",
    "SaveVideo",
]
missing = [x for x in required if x not in d]
third_party = [x for x in d if "GGUF" in x or "CCTech" in x]
if missing:
    raise SystemExit("missing nodes: " + ", ".join(missing))
if third_party:
    raise SystemExit("third-party nodes loaded: " + ", ".join(third_party))
print("official nodes verified")
'
  )"
  log "$result"
}

start_tunnel() {
  PUBLIC_URL=""

  if [[ "${START_TUNNEL}" != "1" ]]; then
    PUBLIC_URL="http://127.0.0.1:${PORT}"
    return
  fi

  [[ -x /var/run/secrets/frp-self-service/install ]] ||
    die "找不到 Radeon Cloud rc-tunnel 安装器"

  log "安装并启动 Radeon Cloud 公网隧道"
  /var/run/secrets/frp-self-service/install

  "${HOME}/.local/bin/rc-tunnel" stop >/dev/null 2>&1 || true

  local output
  output="$("${HOME}/.local/bin/rc-tunnel" expose --port "${PORT}" 2>&1)"
  printf '%s\n' "$output"

  PUBLIC_URL="$(printf '%s\n' "$output" | grep -oE 'https://[^[:space:]]+' | head -1)"
  [[ -n "$PUBLIC_URL" ]] || die "未能解析公网地址"

  for _ in $(seq 1 30); do
    local code
    code="$(curl -L -sS --max-time 10 -o /dev/null -w '%{http_code}' "${PUBLIC_URL}/" || true)"
    [[ "$code" == "200" ]] && return
    sleep 2
  done

  die "公网隧道未通过 HTTP 检查"
}

print_summary() {
  printf '\n============================================================\n'
  printf '安装完成\n'
  printf 'ComfyUI目录: %s\n' "${COMFY_DIR}"
  printf '公网地址: %s\n' "${PUBLIC_URL}"
  printf '工作流: %s\n' "${WORKFLOW_NAME}"

  printf '日志: %s\n' "${LOG_FILE}"
  printf '============================================================\n'
}

main() {
  require_root
  load_notebook_environment
  clone_or_update_comfyui
  disable_custom_nodes
  install_dependencies
  download_models
  verify_models
  install_workflows
  start_comfyui
  verify_official_nodes
  start_tunnel
  print_summary
}

main "$@"
