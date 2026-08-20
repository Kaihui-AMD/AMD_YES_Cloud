## 1.安装命令

安装配置主要就是安装

1. comfyui (GitHub最新安装包)
2. rc-tunnel (云平台端口转发)
3. 模型下载 (从终端命令行下载)

### comfyui 网页打开方式

打开 Radeon Cloud 的 Notebook Terminal：

```
# 下载源码
cd /root
git -c http.sslVerify=false clone \
  https://github.com/Comfy-Org/ComfyUI.git

# 激活云平台环境和安装依赖
source /opt/venv/bin/activate
pip install -r /root/ComfyUI/requirements.txt

# 暴露公网端口
/var/run/secrets/frp-self-service/install
$HOME/.local/bin/rc-tunnel expose --port 8188

# 启动ComfyUI
cd /root/ComfyUI
python main.py \
  --port 8188 \
  --listen 127.0.0.1 \
  --enable-cors-header \
  --enable-compress-response-body \
  --cache-none
```

## 2. 打开官方默认模板

进入 ComfyUI：

```text
Workflow Templates
→ Video
→ MiniMax H3
→ Text to Video
```

或者打开本文提供的 AMD 版本：

```text
COMFY_ORG_OFFICIAL_MiniMax_H3_INT8_AMD.json
```

它与官方模板的唯一区别是文本编码器选择：

```text
qwen3vl_32b_minimax_h3_int8_convrot.safetensors
```

## 3. 下载模型

在第一步安装命令结束之后打开的comfyui模型尚未下载好，我们需要下载模型

点开模板后看到一些错误这些错误都是模型未加载我们需要在命令行下载好放到

```
cd /root/ComfyUI/models
```

下的对应文件夹里。



激活环境（ssh方式一般需要）

```bash
source /opt/venv/bin/activate
```

下载扩散模型：

```bash
hf download Comfy-Org/MiniMax-H3 \
  diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors \
  --local-dir /root/ComfyUI/models
```

下载 AMD 使用的 INT8 文本编码器：

```bash
hf download Comfy-Org/MiniMax-H3 \
  text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors \
  --local-dir /root/ComfyUI/models
```

下载两个 VAE和turbo lora：

```bash
hf download Comfy-Org/MiniMax-H3 \
  vae/minimax_h3_video_vae_fp16.safetensors \
  vae/minimax_h3_audio_vae_fp32.safetensors \
  --local-dir /root/ComfyUI/models
  
hf download Comfy-Org/MiniMax-H3 \
  loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors \
  --local-dir /root/ComfyUI/models
```

![image-20260820114546339](C:\Users\katang\AppData\Roaming\Typora\typora-user-images\image-20260820114546339.png)

---

## 要注意的点

1. ssh
2. 完整comfyui操作步骤

## 1. 放置模型文件

扩散模型放到：

```
/root/ComfyUI/models/diffusion_models/
```

文件名：

```
minimax_h3_fl2va_pruned_int8_convrot.safetensors
```

文本编码器放到：

```
/root/ComfyUI/models/text_encoders/
```

文件名：

```
qwen3vl_32b_minimax_h3_int8_convrot.safetensors
```

确认文件：

```
ls -lh \
  /root/ComfyUI/models/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors \
  /root/ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3_int8_convrot.safetensors
```

## 2. 打开官方工作流

进入纯官方 ComfyUI 页面后：

```
Workflows
→ COMFY_ORG_OFFICIAL_MiniMax_H3_INT8_AMD.json
```

如果使用 ComfyUI 自带模板：

```
Workflow Templates
→ Video
→ MiniMax H3
→ Text to Video
```

## 3. 进入子图

默认工作流中间有一个大节点：

```
Image to Video (MiniMax H3)
```

或者：

```
Text to Video (MiniMax H3)
```

点击节点底部的：

```
Enter Subgraph
```

进入内部节点图。

### 4. 删除旧 Load CLIP

点击截图中的：

```
Load CLIP
```

按：

```
Revove
```

只删除这个节点，不要删除右边的：

```
MiniMax H3 Image to Video
```

### 5. 添加新的原生 CLIP Loader

在空白处双击，搜索：

```
Load CLIP
```

或者：

```
CLIPLoader
```

找到：

```
Load Diffusion Model
```

节点类型是：

```
UNETLoader
```

下拉框选择：

```
minimax_h3_fl2va_pruned_int8_convrot.safetensors
```

第二个选项保持：

```
weight_dtype = default
```

### 6. 设置新节点

在新 `Load CLIP` 节点里选择：

```
clip_name:
qwen3vl_32b_minimax_h3_int8_convrot.safetensors

type:
minimax

device:
default
```

新添加的节点不会被子图外部参数锁住，因此下拉框应该可以正常使用。

从新 `Load CLIP` 节点右侧黄色输出：

```
CLIP
```

连接到：

```
MiniMax H3 Image to Video
└── clip
```

也就是截图中右侧节点最上面的黄色圆点。

## 7. 返回主工作流

点击顶部面包屑或：

```
Exit Subgraph
```

回到主工作流。

建议另存为：

```
MiniMax_H3_Official_INT8_AMD.json
```

避免覆盖 ComfyUI 自带模板。

## 8. 下拉框找不到模型

先刷新浏览器：看看右边第四个图标下的文件夹里有没有模型

```
Ctrl + Shift + R
```

仍然找不到就重启 ComfyUI：

```
pkill -f '^/opt/venv/bin/python main.py'

cd /root/ComfyUI

/opt/venv/bin/python main.py \
  --port 8188 \
  --listen 127.0.0.1 \
  --enable-cors-header \
  --enable-compress-response-body \
  --cache-none
```

注意纯官方 INT8 组合不要使用：

```
--disable-smart-memory
```

最终节点应当是：

```
UNETLoader
└── minimax_h3_fl2va_pruned_int8_convrot.safetensors

CLIPLoader
├── qwen3vl_32b_minimax_h3_int8_convrot.safetensors
├── type: minimax
└── device: default
```

---

