# AMD 双卡运行 MiniMax H3：原理、复现与实测

本文记录如何在两张 AMD Radeon AI PRO R9700 上运行 ComfyUI MiniMax H3，
以及如何通过 CFG 双分支让两张显卡真正同时参与同一个视频的采样。

测试日期：2026-09-07。

配套 GUI 工作流：

[下载 MiniMax H3 双卡 CFG GUI 工作流](./default_gui_workflows/MiniMax_H3_Dual_GPU_CFG_AMD.json)

## 一、结论先行

MiniMax H3 官方工作流使用 `BasicGuider`，每个采样步骤只有一次模型
forward。直接添加 `MultiGPU CFG Split` 会在第二张卡上复制完整模型，但不会
产生第二个可并行的 conditioning work unit。

实测默认 H3 工作流：

```text
GPU 0：100% 左右利用率
GPU 1：约 3% 利用率
```

双卡模式下两张卡都占用了模型显存，但采样速度没有提升：

| 模式 | 124 帧、20 steps 采样时间 | 每步耗时 |
| --- | ---: | ---: |
| 官方 BasicGuider，单卡 | 240.4 秒 | 12.02 秒 |
| BasicGuider + MultiGPU，双卡 | 240.2 秒 | 12.01 秒 |

为了产生两个可以并行执行的 work unit，本工作流加入：

1. `Conditioning Zero Out`，从正向 conditioning 构造零化 negative conditioning；
2. `CFGGuider`，设置 `CFG = 2.0`；
3. `MultiGPU CFG Split`，设置 `max_gpus = 2`。

这样每步包含两个独立 forward：

```text
GPU 0：positive forward
GPU 1：negative forward
GPU 0：汇总 CFG 结果
```

在相同 CFG 计算条件下，实测加速比为 **1.87x**：

| 模式 | 864×480、22 帧、20 steps 中位耗时 |
| --- | ---: |
| 单卡 CFG 2.0 | 56.063 秒 |
| 双卡 CFG 2.0 | 29.990 秒 |
| 加速比 | 1.87x |

需要特别说明：

> 这个工作流加速的是“完整 CFG 双分支推理”。它不会比只执行一次 forward 的
> 官方 BasicGuider 再快一倍，而是让原本接近两倍耗时的 CFG 推理恢复到接近
> BasicGuider 的速度。

## 二、测试环境

| 项目 | 配置 |
| --- | --- |
| GPU | 2 × AMD Radeon AI PRO R9700 |
| 单卡显存 | 32 GB |
| GPU 架构 | `gfx1201` |
| ROCm | 7.2.4 |
| PyTorch | `2.10.0+rocm7.2.4` |
| ComfyUI | `0.34.0` |
| comfy-kitchen | `0.2.31` |
| 操作系统 | Ubuntu 24.04 |
| 容器镜像 | `rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.10.0` |

测试使用两张卡的固定 UUID：

```text
GPU-b5ab24f2dc5d81ac
GPU-b11d6bcf3a61a551
```

使用 UUID 而不是数字序号，是因为 HSA agent 顺序和 `rocm-smi` 显示的 GPU
序号不一定一致。

## 三、模型文件

全部模型来自：

```text
https://huggingface.co/Comfy-Org/MiniMax-H3
```

需要以下四个文件：

| 类型 | 文件 | 字节数 |
| --- | --- | ---: |
| Diffusion | `minimax_h3_fl2va_pruned_int8_convrot.safetensors` | 20,970,379,616 |
| Text Encoder | `qwen3vl_32b_minimax_h3_int8_convrot.safetensors` | 27,141,342,152 |
| Video VAE | `minimax_h3_video_vae_fp16.safetensors` | 5,207,808,496 |
| Audio VAE | `minimax_h3_audio_vae_fp32.safetensors` | 605,254,808 |

目标目录：

```text
ComfyUI/models/
├── diffusion_models/
│   └── minimax_h3_fl2va_pruned_int8_convrot.safetensors
├── text_encoders/
│   └── qwen3vl_32b_minimax_h3_int8_convrot.safetensors
└── vae/
    ├── minimax_h3_video_vae_fp16.safetensors
    └── minimax_h3_audio_vae_fp32.safetensors
```

下载命令：

```bash
HF_XET_HIGH_PERFORMANCE=1 hf download Comfy-Org/MiniMax-H3 \
  diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors \
  text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors \
  vae/minimax_h3_video_vae_fp16.safetensors \
  vae/minimax_h3_audio_vae_fp32.safetensors \
  --local-dir ./models
```

SHA-256：

```text
e889202c41dafb67b10d67b97f0d8541508036a6090af23425a5c2615d03c47a
  minimax_h3_fl2va_pruned_int8_convrot.safetensors

bc2ced0fbea64757fa9acddccfc0b3f4819d1dcf1da6c124d690d368be283923
  qwen3vl_32b_minimax_h3_int8_convrot.safetensors

7c1f131492e7eddacaac9069a61b81bdd39de5cc96561e677c5eab1cdce5e522
  minimax_h3_video_vae_fp16.safetensors

8e505d95dd1561d47abd43d4238fd40d9bb1ae9e147ed0a4cba778d76ae4db48
  minimax_h3_audio_vae_fp32.safetensors
```

## 四、启动双卡 ComfyUI

建议使用 GPU UUID 精确绑定：

```bash
ROCR_VISIBLE_DEVICES=GPU-b5ab24f2dc5d81ac,GPU-b11d6bcf3a61a551 \
python main.py \
  --listen 0.0.0.0 \
  --port 8188
```

进程内设备重新编号为：

```text
物理 GPU-b5ab... → cuda:0
物理 GPU-b11d... → cuda:1
```

Docker 启动示例：

```bash
docker run --rm \
  --network host \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  --ipc=host \
  --security-opt seccomp=unconfined \
  -e ROCR_VISIBLE_DEVICES=GPU-b5ab24f2dc5d81ac,GPU-b11d6bcf3a61a551 \
  -v "$PWD:/workspace/ComfyUI" \
  -w /workspace/ComfyUI \
  rocm/pytorch:rocm7.2.4_ubuntu24.04_py3.12_pytorch_release_2.10.0 \
  python main.py --listen 0.0.0.0 --port 8188
```

不要同时设置数字形式的 `HIP_VISIBLE_DEVICES`，否则在部分环境里可能再次重排
已经筛选过的 HSA 设备。

## 五、ROCm 多卡同步补丁

测试基于一个尚未提交上游的本地正确性补丁。它只影响 AMD/ROCm，多卡 worker
将结果复制回主卡后，先等待目标设备完成 peer copy，再由主线程聚合。

在 `comfy/multigpu.py` 中添加：

```python
def synchronize_multigpu_result(device: torch.device):
    """Wait for ROCm peer copies before another thread consumes the result."""
    if comfy.model_management.is_amd() and comfy.model_management.is_device_cuda(device):
        torch.cuda.synchronize(device)
```

在 `comfy/samplers.py` 的多卡 `_handle_batch()` 中，将模型输出先复制到
`output_device`，所有当前 worker 的 batch 完成后同步：

```python
output = output.to(output_device)
output = output.chunk(batch_chunks)
results.append(
    thread_result(output, mult, area, batch_chunks, cond_or_uncond)
)

# 放在当前 worker 的 batch 循环之后
comfy.multigpu.synchronize_multigpu_result(output_device)
```

NVIDIA 路径不调用这个同步函数。

## 六、为什么直接添加 MultiGPU 节点没有加速

官方 H3 工作流的采样部分是：

```text
MiniMaxH3ImageToVideo
        ↓ positive conditioning
BasicGuider
        ↓
SamplerCustomAdvanced
```

`BasicGuider` 只生成一组需要执行的 conditioning：

```text
Model(latent, timestep, positive)
```

而 `MultiGPU CFG Split` 的机制是把多个 conditioning work units 分配给不同
模型副本。它不是：

- Tensor Parallel；
- 模型层切分；
- 显存池化；
- 单次 forward 内的矩阵乘法拆分。

只有一个 work unit 时，调度结果自然是：

```text
GPU 0：执行唯一的 positive forward
GPU 1：没有任务
```

实测添加 `MultiGPU CFG Split` 后：

```text
GPU 0 利用率：约 100%
GPU 1 利用率：约 3%
```

显存则是：

```text
GPU 0：约 27.6 GB
GPU 1：约 21.5 GB
```

也就是说 GPU 1 加载了完整模型，却没有实际分担采样。

## 七、有效方案：构造双分支 CFG

CFG 的计算形式为：

```text
positive = Model(latent, timestep, positive_conditioning)
negative = Model(latent, timestep, negative_conditioning)

result = negative + CFG * (positive - negative)
```

positive 和 negative 在合并之前互不依赖，可以分配给两张 GPU。

本工作流使用如下结构：

```text
MiniMaxH3ImageToVideo
        │
        ├──────────────────────── positive ──────────────┐
        │                                                │
        └─ Conditioning Zero Out ── negative ────────────┤
                                                         ↓
UNETLoader → MultiGPU CFG Split(max_gpus=2) → CFGGuider(CFG=2.0)
                                                         ↓
                                              SamplerCustomAdvanced
```

其中：

- `Conditioning Zero Out` 保留 H3 conditioning 的结构和附加字段；
- 文本 embedding 和 pooled output 被清零，作为 negative conditioning；
- `CFGGuider` 强制每步执行 positive 和 negative 两次 forward；
- `MultiGPU CFG Split` 把这两次 forward 分到不同 GPU；
- 两张卡的结果返回主卡后执行 CFG 合并。

采样阶段分配：

```text
GPU 0：positive forward
GPU 1：negative forward
GPU 0：CFG 聚合和 latent 更新
```

## 八、如何修改官方 GUI 工作流

从官方 `video_minimax_h3_t2v` 工作流开始，进入
`Image to Video (MiniMax H3)` 子图。

### 1. 添加 MultiGPU CFG Split

原连接：

```text
UNETLoader → BasicScheduler
UNETLoader → BasicGuider
```

修改为：

```text
UNETLoader
    ↓
MultiGPU CFG Split
    ├─→ BasicScheduler
    └─→ CFGGuider
```

设置：

```text
max_gpus = 2
```

### 2. 创建 negative conditioning

连接：

```text
MiniMaxH3ImageToVideo.positive
    ↓
Conditioning Zero Out
    ↓
CFGGuider.negative
```

同时保留：

```text
MiniMaxH3ImageToVideo.positive
    ↓
CFGGuider.positive
```

### 3. 替换 Guider

删除或绕过 `BasicGuider`，使用：

```text
CFGGuider
```

设置：

```text
CFG = 2.0
```

`CFG` 必须大于 `1.0`。设置为 `1.0` 时，ComfyUI 会优化掉 negative forward，
第二张卡会再次空闲。

## 九、实测数据

### 9.1 官方 BasicGuider

设置：

```text
864 × 480
124 帧
5.167 秒视频
24 FPS
20 steps
res_multistep
simple scheduler
```

| 模式 | 采样时间 | 每步耗时 | 端到端时间 |
| --- | ---: | ---: | ---: |
| 单卡 BasicGuider | 240.4 秒 | 12.02 秒 | 280.3 秒 |
| BasicGuider + MultiGPU | 240.2 秒 | 12.01 秒 | 261.3 秒 |

采样加速比只有：

```text
1.0008x
```

端到端时间的差异受到模型缓存和测试顺序影响，不能视为双卡采样加速。

### 9.2 双分支 CFG

为了快速重复测试，使用：

```text
864 × 480
22 帧
0.917 秒视频
20 steps
CFG 2.0
```

单卡 CFG 三次：

```text
56.066 秒
56.063 秒
56.063 秒
```

中位数：

```text
56.063 秒
```

双卡 CFG：

```text
首次创建模型副本：389.660 秒
热运行 1：30.129 秒
热运行 2：29.851 秒
```

热运行平均：

```text
29.990 秒
```

加速比：

```text
56.063 / 29.990 = 1.87x
```

延迟降低：

```text
46.5%
```

采样日志：

```text
单卡 CFG：约 2.61 秒/步
双卡 CFG：约 1.31 秒/步
```

视频输出经过检查：

```text
864 × 480
24 FPS
H.264
AAC 32kHz stereo
```

单卡和双卡中间帧视觉一致，没有黑帧、花屏或结构损坏。由于不同设备上的浮点
执行顺序不同，不应要求逐像素完全相同。

## 十、失败方案：组件流水线分卡

还测试了以下分配：

```text
Diffusion Model → GPU 0
Text Encoder    → GPU 1
Video VAE       → GPU 1
Audio VAE       → GPU 1
```

对应节点：

```text
Select Model Device
Select CLIP Device
Select VAE Device
```

测试结果：

| 模式 | 冷启动 | 22 帧、20 steps 热运行 |
| --- | ---: | ---: |
| 官方默认分配 | 713.1 秒（22 帧、2 steps） | 30.034 秒 |
| 组件流水线分卡 | 1452.4 秒（22 帧、2 steps） | 30.037 秒 |

流水线分卡没有改善热运行速度，冷启动反而明显变慢。原因包括：

- `Select*Device` 需要创建新的模型副本；
- 32B 文本编码器接近占满一张 32GB GPU；
- 解码前仍然需要卸载文本编码器并加载 VAE；
- ComfyUI 图执行是串行依赖，不会同时执行文本编码和扩散采样。

因此该方案没有保留。

## 十一、显存和冷启动注意事项

双卡 CFG 会在每张卡上保存一份完整扩散模型：

```text
GPU 0：约 20GB 模型 + positive 分支 + 主 latent
GPU 1：约 20GB 模型 + negative 分支
```

这不是显存合并。每张卡仍需独立容纳完整模型。

第一次运行需要创建第二份模型，实测首次双卡 CFG 调用约：

```text
389.7 秒
```

后续模型副本保持热状态后，才能达到约 30 秒的测试结果。

## 十二、适用场景

推荐使用本工作流：

- 需要 CFG 引导；
- 希望 positive 和 negative 分支同时计算；
- 连续生成多个视频，可以摊薄首次模型副本加载成本；
- 每张 GPU 都能独立容纳约 20GB 的扩散模型。

不推荐使用本工作流：

- 只需要官方 `BasicGuider`；
- CFG 设置为 `1.0`；
- 只生成一次短视频；
- 希望两张显卡合并显存；
- 希望把单次 H3 forward 本身拆成两半。

如果只追求最高吞吐量，最简单可靠的方法仍然是运行两个独立 ComfyUI 实例，
每张 GPU 各生成一个视频。

## 十三、监控方法

运行过程中执行：

```bash
watch -n 1 rocm-smi
```

有效的双分支 CFG 应看到两张卡同时出现较高利用率。

如果看到：

```text
GPU 0：接近 100%
GPU 1：约 0%～3%
```

通常说明当前工作流只有一个 conditioning work unit，第二张卡只是加载了模型
副本，并没有参与 forward。

## 十四、复现文件

GUI 工作流：

```text
default_gui_workflows/MiniMax_H3_Dual_GPU_CFG_AMD.json
```

导入 ComfyUI 后，确认子图中存在：

```text
MultiGPU CFG Split
Conditioning Zero Out
CFGGuider
```

推荐初始设置：

```text
max_gpus = 2
CFG = 2.0
steps = 20
duration = 5
```

首次测试可以把 duration 调低到接近 1 秒，确认两张 GPU 都有负载后，再生成完整
5 秒视频。

## 十五、最终判断

MiniMax H3 的官方 BasicGuider 每步只有一次 forward，当前 ComfyUI 无法通过
工作流把这一次 forward 拆到两张 GPU 上。

但当工作流需要 CFG 时，positive 和 negative 是天然独立的两个 forward。
`MultiGPU CFG Split` 可以将它们分配到两张卡，使完整 CFG 推理获得约
`1.87x` 加速。

因此，本方案的准确定位是：

> 用接近官方单分支的耗时，运行具有完整 positive/negative CFG 的 MiniMax H3
> 双分支推理。
