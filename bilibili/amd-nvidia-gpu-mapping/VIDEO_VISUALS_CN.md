# AMD/NVIDIA GPU 对照视频配图使用表

全部图片为 3840×2160 PNG，适合 16:9 的 4K 视频。图片目录：

[`output/gpu_mapping_visuals/`](output/gpu_mapping_visuals/)

## 推荐镜头顺序

| 顺序 | 图片 | 建议时长 | 对应口播内容 |
|---|---|---:|---|
| 1 | `01_product_landscape.png` | 8-12 秒 | Radeon RX 对应 GeForce RTX，Radeon PRO 对应 RTX PRO，Instinct 对应 NVIDIA 数据中心 GPU |
| 2 | `10_amd_advantages.png` | 10-15 秒 | 社区视角总结 AMD 在内存、开放软件栈、HIP、FSR、Linux 和开放互连方面的优势 |
| 3 | `02_hardware_mapping.png` | 8-10 秒 | Stream Processor、CU、AI Accelerator 和 Ray Accelerator 的概念对应 |
| 4 | `03_gaming_features.png` | 8-12 秒 | FSR/DLSS、Anti-Lag/Reflex、AFMF/Smooth Motion、FreeSync/G-SYNC |
| 5 | `04_training_vs_inference.png` | 10-14 秒 | 解释训练与推理关注的指标不同 |
| 6 | `05_memory_ladder.png` | 12-18 秒 | 解释不同精度的模型权重和显存容量估算 |
| 7 | `09_rocm_version_lanes.png` | 10-14 秒 | 区分 Instinct、Radeon/Ryzen 和 MI455X 的软件版本路线 |
| 8 | `06_training_stack.png` | 10-14 秒 | 训练栈：PyTorch、Primus、RCCL、AITER、Profiler |
| 9 | `07_inference_stack.png` | 10-14 秒 | 本地 llama.cpp/Ollama 与企业 vLLM/SGLang 两条推理路线 |
| 10 | `08_deployment_scale.png` | 10-14 秒 | 从工作站、单卡、8-GPU 节点扩展到 Helios 机架系统 |

## 剪辑建议

- 标题和核心结论应停留至少 2 秒后再开始移动镜头；
- 信息密集的显存图建议停留 12 秒以上，或拆成两次推拉镜头；
- 可以对静态图使用 103%-108% 的缓慢推近，不要快速缩放；
- 产品地图适合从中间向左右展开，训练/推理图适合从中心向两侧移动；
- 显存图可以先展示左侧模型表，再平移到右侧 GPU 容量柱状图；
- 软件栈图按从下到上的顺序讲解：硬件、ROCm、通信、框架；
- 画面已经保留四周安全区，不建议再叠加大面积字幕条；
- 字幕建议放在底部 8%-12% 的区域，并使用半透明黑色底。

## 一键重新生成

```bash
cd bilibili/amd-nvidia-gpu-mapping
python3 generate_gpu_mapping_visuals.py
```

脚本会重新生成 10 张 4K PNG 和一张总览预览图：

`gpu_mapping_visuals_contact_sheet.jpg`
