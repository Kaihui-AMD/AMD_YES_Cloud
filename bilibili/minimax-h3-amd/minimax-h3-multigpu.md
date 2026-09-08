## 原理

MiniMax H3 将文本、条件、音频和视频 token 打包成一条序列，由一个 56-head DiT 共同处理。

双卡序列并行的核心流程：

1. **模型按职责加载和裁剪。**
   rank 0 保留输入打包、文本 refinement、50 个主 Transformer blocks 和最终输出层；rank 1 只保留 50 个主 blocks。QKV 权重及 INT8 scale 按 attention heads 分片，每张卡只保存 28 个 heads；MLP、AdaLN、Norm 和 `out_proj` 在两卡保留。
2. **token 序列按 rank 切分。**
   每张卡处理一半 token 的 Norm、AdaLN、残差连接和 MLP，支持奇数 token 数量。
3. **交换 attention 所需的 token。**
   attention 前，两卡通过 RCCL 交换各自的 hidden states。本地 QKV 投影与 peer token 传输重叠执行，减少通信等待。
4. **每张卡计算 28 个 attention heads。**
   每张卡只计算一半 heads，但每个 head 都能看到完整 token 序列，因此 attention 没有被截断或近似。
5. **执行 head-to-sequence 交换。**
   attention 完成后，两卡交换 head 输出。每张卡最终获得本地 token 对应的完整 56 heads，再执行原始完整 `out_proj`，随后继续本地 MLP 和下一层。

该方案不会减少采样步数，不会跳过 Transformer block，不会增加额外量化，也不使用近似缓存。它保持原始 INT8 ConvRot 模型的计算语义。真实 INT8 attention block 对比测试结果为 `max_abs=0`。分布式运行可能受到浮点内核调度和视频编码非确定性的影响，但不会以牺牲生成质量换取速度。

## 模型文件

```text
models/
├── diffusion_models/
│   └── minimax_h3_fl2va_pruned_int8_convrot.safetensors
├── text_encoders/
│   └── qwen3vl_32b_minimax_h3_int8_convrot.safetensors
└── vae/
    ├── minimax_h3_video_vae_fp16.safetensors
    └── minimax_h3_audio_vae_fp32.safetensors
```

## 安装

上游实现：

```text
https://github.com/Kaihui-AMD/ComfyUI-MiniMaxH3-MultiGPU
```

本次测试使用 ComfyUI 0.30.0：

```
git -c http.sslVerify=false clone https://github.com/Comfy-Org/ComfyUI.git ComfyUI-h3-sp
cd ComfyUI-h3-sp
git checkout v0.30.0
pip install -r requirements.txt

cd ComfyUI/custom_nodes
git -c http.sslVerify=false clone https://github.com/Kaihui-AMD/ComfyUI-MiniMaxH3-MultiGPU.git
cp ComfyUI-MiniMaxH3-MultiGPU/examples/workflow_ui_2gpu.json ~/ComfyUI-h3-sp/user/default/workflows/
```

```
# 启动命令
cd ~/ComfyUI-h3-sp
env -u HIP_VISIBLE_DEVICES -u ROCR_VISIBLE_DEVICES \
CUDA_VISIBLE_DEVICES=0,1 \
MINIMAX_SP_DEVICES=0,1 \
python main.py \
  --port 8188 \
  --listen 127.0.0.1 \
  --enable-cors-header \
  --enable-compress-response-body \
  --cache-none
```

```
# 第二个终端打开暴露公网端口
/var/run/secrets/frp-self-service/install
$HOME/.local/bin/rc-tunnel expose --port 8188
```

```
#下载四个模型
hf download Comfy-Org/MiniMax-H3 \
  diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors \
  --local-dir /root/ComfyUI-h3-sp/models
hf download Comfy-Org/MiniMax-H3 \
  text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors \
  --local-dir /root/ComfyUI-h3-sp/models
hf download Comfy-Org/MiniMax-H3 \
  vae/minimax_h3_video_vae_fp16.safetensors \
  vae/minimax_h3_audio_vae_fp32.safetensors \
  --local-dir /root/ComfyUI-h3-sp/models
hf download Comfy-Org/MiniMax-H3 \
  loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors \
  --local-dir /root/ComfyUI-h3-sp/models
```
