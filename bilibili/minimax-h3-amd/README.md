# AMD 显卡跑通 MiniMax H3：ComfyUI + GGUF 完整实战

这篇教程记录一套已经在 AMD Radeon Cloud 上实际跑通的 MiniMax H3 本地视频生成流程，包括：

- 在 AMD `gfx1100` 上安装 ComfyUI；
- 使用 `/opt/venv` 中的 ROCm PyTorch 环境；
- 快速下载约 32 GB 的模型文件；
- 将官方 MiniMax H3 Workflow 改为 GGUF；
- 使用 AMD 稳定启动参数；
- 通过 `rc-tunnel` 打开 ComfyUI；
- 记录实际生成速度与排错方法。

本文使用的是 **FL2VA** 模型，可用于：

- T2V：文字生成视频；
- I2V：首帧或首尾帧生成视频。

本文没有下载 REF2VA 模型，因此暂时不包含 Reference to Video。

## 一、实测环境

| 项目 | 实测配置 |
| --- | --- |
| GPU | AMD Radeon Graphics |
| GPU 架构 | `gfx1100` |
| 显存 | 48 GB |
| ROCm | 7.2 |
| PyTorch | `2.9.1+gitff65f5b` |
| ComfyUI | 0.32.0 |
| Python 环境 | `/opt/venv` |
| 操作系统 | Ubuntu 24.04 |

官方 MiniMax H3 模板默认使用：

```text
minimax_h3_fl2va_pruned_int8_convrot.safetensors
qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
```

这套组合更偏向 CUDA 环境。在 `gfx1100` 上可能遇到雪花、黑屏或量化算子兼容问题，所以本文改用：

```text
MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf
qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf
```

## 二、安装 ComfyUI

打开 Radeon Cloud 的 **Notebook Terminal**，执行：

```bash
cd /root
git -c http.sslVerify=false clone \
  https://github.com/comfyanonymous/ComfyUI.git
```

进入平台预装的虚拟环境并安装依赖：

```bash
source /opt/venv/bin/activate
pip install -r /root/ComfyUI/requirements.txt
```

Ubuntu 24.04 会限制系统 Python 的 `pip install`。Radeon Cloud 镜像已经提供 `/opt/venv`，不要使用系统 Python，也不需要添加 `--break-system-packages`。

## 三、安装 ComfyUI-GGUF

下载自定义节点：

```bash
git -c http.sslVerify=false clone \
  https://github.com/city96/ComfyUI-GGUF.git \
  /root/ComfyUI/custom_nodes/ComfyUI-GGUF
```

安装依赖：

```bash
source /opt/venv/bin/activate
pip install -r /root/ComfyUI/custom_nodes/ComfyUI-GGUF/requirements.txt
```

检查：

```bash
pip show gguf
```

本次实测使用 `gguf 0.18.0`。

## 四、需要下载哪些模型

本文使用四个文件：

| 文件 | 大小约 | 放置目录 |
| --- | ---: | --- |
| `MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf` | 11.6 GB | `/root/ComfyUI/models/unet/` |
| `qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf` | 14.6 GB | `/root/ComfyUI/models/clip/` |
| `minimax_h3_video_vae_fp16.safetensors` | 5.2 GB | `/root/ComfyUI/models/vae/` |
| `minimax_h3_audio_vae_fp32.safetensors` | 605 MB | `/root/ComfyUI/models/vae/` |

总下载量约 32 GB。

先创建目录：

```bash
mkdir -p \
  /root/ComfyUI/models/unet \
  /root/ComfyUI/models/clip \
  /root/ComfyUI/models/vae
```

## 五、快速下载模型

### 方法一：直接在 Notebook Terminal 使用 `hf download`

这是首选方法。Radeon Cloud 的 Notebook Terminal 可能已经注入专用 Hugging Face 镜像：

```bash
echo "$HF_ENDPOINT"
```

只要输出不是空的，`hf download` 会自动使用该镜像。普通 SSH 非登录 Shell 不一定继承这些变量，所以同一条命令可能在 Notebook Terminal 很快、在 SSH 中很慢或无法联网。

下载扩散模型：

```bash
source /opt/venv/bin/activate

hf download Abiray/MiniMax-H3-Pruned-GGUF \
  MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf \
  --local-dir /root/ComfyUI/models/unet
```

下载文本编码器：

```bash
hf download realrebelai/MiniMax-H3_GGUFs \
  qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf \
  --local-dir /root/ComfyUI/models/clip
```

下载两个 VAE：

```bash
hf download Comfy-Org/MiniMax-H3 \
  vae/minimax_h3_video_vae_fp16.safetensors \
  vae/minimax_h3_audio_vae_fp32.safetensors \
  --local-dir /root/ComfyUI/models
```

可以同时打开三个 Notebook Terminal 分别执行这三组命令，让扩散模型、文本编码器和 VAE 并行下载。

### 方法二：使用 aria2 多连接下载大文件

如果单连接下载只有几 MB/s，可以使用 `aria2`。

安装：

```bash
apt-get update
apt-get install -y aria2
```

确认 Notebook 已设置镜像：

```bash
test -n "$HF_ENDPOINT" && echo "$HF_ENDPOINT"
```

下载扩散模型：

```bash
aria2c \
  -c \
  -x 16 \
  -s 16 \
  -k 1M \
  --file-allocation=none \
  --auto-file-renaming=false \
  -d /root/ComfyUI/models/unet \
  -o MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf \
  "$HF_ENDPOINT/Abiray/MiniMax-H3-Pruned-GGUF/resolve/main/MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf"
```

下载文本编码器：

```bash
aria2c \
  -c \
  -x 16 \
  -s 16 \
  -k 1M \
  --file-allocation=none \
  --auto-file-renaming=false \
  -d /root/ComfyUI/models/clip \
  -o qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf \
  "$HF_ENDPOINT/realrebelai/MiniMax-H3_GGUFs/resolve/main/qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf"
```

下载视频 VAE：

```bash
aria2c \
  -c \
  -x 16 \
  -s 16 \
  -k 1M \
  --file-allocation=none \
  --auto-file-renaming=false \
  -d /root/ComfyUI/models/vae \
  -o minimax_h3_video_vae_fp16.safetensors \
  "$HF_ENDPOINT/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_video_vae_fp16.safetensors"
```

下载音频 VAE：

```bash
aria2c \
  -c \
  -x 16 \
  -s 16 \
  -k 1M \
  --file-allocation=none \
  --auto-file-renaming=false \
  -d /root/ComfyUI/models/vae \
  -o minimax_h3_audio_vae_fp32.safetensors \
  "$HF_ENDPOINT/Comfy-Org/MiniMax-H3/resolve/main/vae/minimax_h3_audio_vae_fp32.safetensors"
```

如果下载过程中部分 CDN 分片返回 `403`，按 `Ctrl+C` 停止，然后原样重新执行同一条 `aria2c` 命令。aria2 会读取同目录下的 `.aria2` 状态文件，只补齐未完成分片。

重要：

- aria2 第一次下载时必须从零开始；
- 或者只能续传由 aria2 自己创建的文件和 `.aria2` 状态；
- 不要把 `hf download` 的 `.incomplete` 临时文件移动出来交给 aria2 续传；
- 两种工具的临时文件布局不同，混用可能得到大小正确但 SHA-256 错误的模型。

### 下载完成后校验

最终目录：

```text
/root/ComfyUI/models/
├── unet/
│   └── MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf
├── clip/
│   └── qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf
└── vae/
    ├── minimax_h3_video_vae_fp16.safetensors
    └── minimax_h3_audio_vae_fp32.safetensors
```

执行：

```bash
sha256sum \
  /root/ComfyUI/models/unet/MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf \
  /root/ComfyUI/models/clip/qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf \
  /root/ComfyUI/models/vae/minimax_h3_video_vae_fp16.safetensors \
  /root/ComfyUI/models/vae/minimax_h3_audio_vae_fp32.safetensors
```

实测正确值：

```text
d74e644906fe95b8c7bf4837ba9d3f9392925f7301675a0993d419b62a4824a3  MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf
1bf75e038c5895b97b6ea16cc1e3d32076254b06ec3df10657650d86dc82279e  qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf
7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522  minimax_h3_video_vae_fp16.safetensors
8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48  minimax_h3_audio_vae_fp32.safetensors
```

哈希不一致时不要继续推理。删除错误文件后重新下载，否则雪花、黑屏和模型损坏会很难区分。

## 六、使用 AMD 稳定参数启动 ComfyUI

启动前先停止旧进程：

```bash
pkill -f '/root/ComfyUI/main.py' || true
```

后台启动：

```bash
nohup /opt/venv/bin/python /root/ComfyUI/main.py \
  --port 8188 \
  --listen 127.0.0.1 \
  --enable-cors-header \
  --enable-compress-response-body \
  --disable-smart-memory \
  --disable-async-offload \
  --cache-none \
  > /root/ComfyUI/comfyui.log 2>&1 &
```

参数作用：

- `--disable-smart-memory`：避免模型部分卸载和重新加载时出现异常；
- `--disable-async-offload`：避开异步卸载的设备兼容问题；
- `--cache-none`：减少中间节点缓存；
- 不建议加入 `--deterministic`。

检查服务：

```bash
curl --fail http://127.0.0.1:8188/
tail -f /root/ComfyUI/comfyui.log
```

日志中应看到类似：

```text
AMD arch: gfx1100
ROCm version: (7, 2)
Disabling smart memory management
ComfyUI-GGUF
Starting server
```

## 七、打开公网 ComfyUI

安装 Tunnel：

```bash
/var/run/secrets/frp-self-service/install
```

暴露 `8188`：

```bash
"$HOME/.local/bin/rc-tunnel" expose --port 8188
```

命令会返回临时公网地址，例如：

```text
https://rc-xxxxxxxxxxxxxxxx.radeon.firstdg.ai
```

检查：

```bash
"$HOME/.local/bin/rc-tunnel" status
```

旧地址失效时重新申请：

```bash
"$HOME/.local/bin/rc-tunnel" stop
"$HOME/.local/bin/rc-tunnel" expose --port 8188
```

ComfyUI 默认没有账号密码，不要公开分享 Tunnel 地址。

## 八、修改官方 MiniMax H3 Workflow

打开：

```text
Workflow Templates -> Video -> MiniMax H3 -> Image to Video
```

官方模板将加载器藏在 `Image to Video (MiniMax H3)` 子工作流中。点击该节点右上角的方框箭头进入内部。

### 替换扩散模型加载器

1. 删除原来的 `UNETLoader`；
2. 双击空白处，搜索 `Unet Loader (GGUF)`；
3. 选择 `MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf`；
4. 把紫色 `MODEL` 输出分别连接到：

```text
Basic Scheduler -> model
Basic Guider -> model
```

`Basic Scheduler` 和 `Basic Guider` 位于子工作流右侧的采样区域。缩小画布后向右移动即可找到。

### 替换文本编码器

1. 删除原来的 `CLIPLoader`；
2. 添加 `CLIPLoader (GGUF)`；
3. 选择 `qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf`；
4. 将 `type` 设置为 `minimax`；
5. 将黄色 `CLIP` 输出连接到：

```text
MiniMax H3 Image to Video -> clip
```

### VAE 不需要替换

两个 VAE 保持：

```text
minimax_h3_video_vae_fp16.safetensors
minimax_h3_audio_vae_fp32.safetensors
```

返回外层后，`unet_name` 可能仍显示 `undefined`，`clip_name` 也可能显示旧文件名。这没有关系，实际加载已经由子工作流内部的 GGUF 节点接管。

如果不连接 `first_frame` 和 `last_frame`，这套 I2V Workflow 也可以作为 T2V 使用。

## 九、第一次测试怎么设置

先用低规格验证：

```text
分辨率：608 x 352
帧数：39
帧率：24 FPS
采样步数：20
Sampler：res_multistep
Scheduler：simple
```

测试提示词：

```text
Cinematic wide shot of a red paper airplane gliding above a calm ocean
at sunrise, warm golden reflections, gentle tracking camera, realistic
motion. Audio: soft ocean waves and light wind. No text, no logo,
no watermark.
```

实测低规格结果：

```text
输出：39 帧，608 x 352
视频：H.264
音频：AAC，32 kHz，双声道
视频长度：1.625 秒
采样速度：约 3.0 秒/步
总执行时间：约 107.24 秒
```

在 ComfyUI 界面运行更完整的 MiniMax H3 Workflow，另一次成功生成耗时：

```text
628.71 秒，约 10 分 29 秒
```

实际时间取决于分辨率、帧数、参考图数量、首次模型加载和 ROCm Kernel 缓存。第一次运行通常更慢。

输出目录：

```text
/root/ComfyUI/output/video/
```

## 十、常见问题

### `unet_name` 显示 `undefined`

这是外层子工作流遗留的旧输入。只要内部的 `Unet Loader (GGUF)` 已正确连接，就不影响运行。

### 找不到 `Unet Loader (GGUF)`

检查：

```bash
test -d /root/ComfyUI/custom_nodes/ComfyUI-GGUF
source /opt/venv/bin/activate
pip show gguf
tail -100 /root/ComfyUI/comfyui.log
```

安装自定义节点后必须重启 ComfyUI。

### SSH 下载很慢，但 Notebook Terminal 很快

优先在 Notebook Terminal 下载，并检查：

```bash
echo "$HF_ENDPOINT"
```

SSH 非登录 Shell 可能没有继承平台注入的 Hugging Face 镜像变量。

### 生成雪花或黑屏

依次检查：

1. 四个文件的 SHA-256 是否完全一致；
2. 是否使用 GGUF Q4 模型，而不是模板默认 INT8/NVFP4；
3. 启动参数是否包含 `--disable-smart-memory`；
4. `CLIPLoader (GGUF)` 的 `type` 是否为 `minimax`；
5. 模型和 CLIP 连线是否正确。

### 运行约十分钟是不是异常

不一定。本次完整 Workflow 实测约 10 分 29 秒。分辨率、时长和首帧条件都会明显影响运行时间。

## 十一、本次跑通结论

在 `gfx1100 + ROCm 7.2 + 48 GB` 环境中，下面这套组合已经完成带音频视频生成：

```text
ComfyUI 0.32.0
ComfyUI-GGUF
MiniMax-H3-FL2VA-Pruned-Q4_K_M.gguf
qwen3vl-32B-MiniMax-H3-Q4_K_M.gguf
minimax_h3_video_vae_fp16.safetensors
minimax_h3_audio_vae_fp32.safetensors
--disable-smart-memory
--disable-async-offload
--cache-none
```

相比直接套用官方模板默认的 CUDA 偏好量化文件，这套 GGUF 路线更适合当前 AMD `gfx1100` 环境。
