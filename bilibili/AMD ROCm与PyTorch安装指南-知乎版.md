# AMD GPU怎么跑PyTorch？从查gfx到跑通第一个Tensor（ROCm 7.14实战）

> 上游来源：[AMD-AIM/zhihu_rednote_articles](https://github.com/AMD-AIM/zhihu_rednote_articles/blob/main/zhihu/AMD%20ROCm%E4%B8%8EPyTorch%E5%AE%89%E8%A3%85%E6%8C%87%E5%8D%97-%E7%9F%A5%E4%B9%8E%E7%89%88.md)
>
> 同步日期：2026-08-07。ROCm、PyTorch、操作系统和 GPU 支持范围会持续变化，实际安装前请再次核对文末官方资料。

如果你第一次接触 AMD GPU 跑 AI，大概率会遇到这些问题：

我的 RX 7800 XT 支持 ROCm 吗？
为什么网上都说先查 gfx？
ROCm 装完后，怎么确认真的在调用 GPU？
torch.cuda.is_available() 为什么还是 False？
Windows 和 WSL2 到底选哪个？

我会按照自己从零搭建 ROCm 环境的顺序，带你完成下面这件事：

从查显卡 gfx 代号开始，到安装ROCm，到安装 PyTorch，最后让 GPU 成功完成第一次 Tensor 计算。

我以 ROCm Core SDK 7.14.0 与 PyTorch 2.12.0 为主线，重点写原生 Linux，也保留 Windows、WSL2、Docker 和官方表外显卡的分流。硬件、系统和版本信息已按 2026-08-04 的官方页面复核；建议读者打开[文末参考资料](#参考资料)按自己的完整型号再查一次。

## ROCm安装的所有路径
ROCm安装前，先确定你属于哪一类用户

事实上 ROCm 不只有一种安装方式。

① Linux 用户适合：PyTorch 开发、模型训练、长期使用。

② Docker 用户适合：不想污染系统环境、需要复现依赖环境。Docker 只能隔离 Python 等用户态依赖，不能代替宿主机显卡驱动。

③ Windows 用户适合：ROCm 7.14 官方支持表中明确列出的部分 Radeon AI PRO 和 RX 9000 型号；安装前必须按完整型号确认。

④ WSL2 用户适合：想保留 Windows 桌面、同时使用 Linux 开发环境。前提是显卡、Windows 驱动和 Ubuntu 版本都在官方支持范围内。

⑤ 官方未支持显卡可尝试：TheRock Nightly，但这是实验路线，稳定性和兼容性需要自行验证。

ROCm 安装不是只分显卡型号。完整判断条件是具体 SKU × 操作系统 × 内核或驱动 × 框架版本。下面先列出全部常见路径，再决定该复制哪一段命令。

| 路径 | 状态与验证 | 适合什么 | 主要代价或边界 |
| --- | --- | --- | --- |
| 原生 Linux + pip | 官方；须在兼容性矩阵核对具体型号、发行版、内核与驱动 | 日常 PyTorch 开发、训练、编译扩展 | 需要先让内核驱动和设备权限正常 |
| 原生 Linux + Docker | 官方；AMD 提供 ROCm PyTorch 镜像 | 希望环境可复现，或不想把 Python 依赖装进系统 | 容器不能替代宿主机驱动，宿主机仍须识别 GPU |
| 原生 Windows + pip 或 tarball | 官方；仅限矩阵中列出的具体 SKU 与 Windows 版本 | 在 Windows 上运行受支持的 Python 工作负载 | 不要套用 Linux 的 amdgpu 驱动命令 |
| WSL2 + Ubuntu | 官方但按具体 SKU 验证 | 需要 Windows 桌面与 Linux Python 工作流共存 | Windows 主机驱动、WSL 发行版和 GPU 型号缺一不可 |
| TheRock nightly | AMD 上游 nightly；有编译产物不等于发布版验证 | 官方表外显卡的个人验证 | 没有发布版 SLA，版本可能回归 |
| DirectML 或 Vulkan | 替代后端，不属于 ROCm 官方 PyTorch 路径 | Windows 或老卡上的本地推理，尤其是 llama.cpp 一类程序 | 训练、自定义 HIP 算子与算子覆盖不能按 ROCm 预期 |

我的建议是：官方支持的设备优先在原生 Linux 中通过 pip 安装或者使用官方 Docker 镜像隔离环境。先核对显卡型号、系统、内核、驱动和 PyTorch 安装参数；官方路径仍无法满足需求，再尝试 TheRock 等社区构建。即使 gfx 相同，Windows、WSL2 与 Linux 的支持状态也可能不同，, 后文会讲到。

## 先查完整 gfx：device extra 从这里取值

可参考过往 [文章](https://zhuanlan.zhihu.com/p/2067663713826612548) 找到 gfx代号，再到后面的 device extra 表中取安装标签。

### gfx 到 device extra

安装命令中写的是 device extra。两者一一对应，在后面会用到：

| gfx | device extra |
| --- | --- |
| gfx950 | device-gfx950 |
| gfx942 | device-gfx942 |
| gfx90a | device-gfx90a |
| gfx908 | device-gfx908 |
| gfx1201 | device-gfx1201 |
| gfx1200 | device-gfx1200 |
| gfx1100 | device-gfx1100 |
| gfx1101 | device-gfx1101 |
| gfx1102 | device-gfx1102 |
| gfx1030 | device-gfx1030 |
| gfx1151 | device-gfx1151 |
| gfx1150 | device-gfx1150 |
| gfx1152 | device-gfx1152 |
| gfx1153 | device-gfx1153 |
| gfx1103 | device-gfx1103 |
| 所有发布版架构 | device-all |

## 安装ROCm

光靠gfx号不能推出安装的环境要求, 需要根据下面这张表查询。
下表按 ROCm 7.14.0 分支的[安装选择器](https://rocm.docs.amd.com/en/docs-7.14.0/install/rocm.html)整理。最后仍要在 [兼容性矩阵](https://rocm.docs.amd.com/en/docs-7.14.0/compatibility/compatibility-matrix.html) 选择完整 SKU 复核。完整型号决定设备支持，操作系统、驱动和 WSL2 状态还要单独核对。

安装rocm过程在[安装选择器](https://rocm.docs.amd.com/en/docs-7.14.0/install/rocm.html)查询。

| GPU 或 APU | Linux | Windows | WSL2 |
| --- | --- | --- | --- |
| Instinct 系列 | 按 MI SKU 查询；各型号的发行版与内核不同 | ❌ | ❌ |
| Radeon AI PRO R9700S、R9700，gfx1201 | Ubuntu 22.04.5、24.04.4、26.04；RHEL 9.8、10.2 | ✅ Windows 11 25H2 | ✅ |
| Radeon AI PRO R9600D，gfx1201 | Ubuntu 22.04.5、24.04.4、26.04；RHEL 9.8、10.2 | ✅ Windows 11 25H2 | ❌ |
| Radeon RX 9070 XT、9070 GRE、9070，gfx1201 | Ubuntu 22.04.5、24.04.4、26.04；RHEL 9.8、10.2 | ✅ Windows 11 25H2 | ✅ |
| Radeon RX 9060 XT、RX 9060，gfx1200 | Ubuntu 22.04.5、24.04.4、26.04；RHEL 9.8、10.2 | ✅ Windows 11 25H2 | ✅ |
| Radeon RX 9060 XT LP，gfx1200 | Ubuntu 22.04.5、24.04.4、26.04；RHEL 9.8、10.2 | ✅ Windows 11 25H2 | ❌ |
| gfx1100 的 PRO W7900、W7800 与 RX 7900 系列 | Ubuntu 22.04.5、24.04.4、26.04；RHEL 9.8、10.2 | ✅ Windows 11 25H2 | ✅ |
| PRO W7700、RX 7800 XT，gfx1101 | Ubuntu 22.04.5、24.04.4、26.04；RHEL 9.8、10.2 | ✅ Windows 11 25H2 | ✅ |
| RX 7700 XT、RX 7700 XE、RX 7700，gfx1101 | Ubuntu 22.04.5、24.04.4、26.04；RHEL 9.8、10.2 | ✅ Windows 11 25H2 | ❌ |
| PRO V710，gfx1101 | Ubuntu 22.04.5、24.04.4、26.04；RHEL 9.8、10.2 | ❌ | ❌ |
| RX 7600，gfx1102 | Ubuntu 22.04.5、24.04.4、26.04；RHEL 9.8、10.2 | ✅ Windows 11 25H2 | ❌ |
| PRO W6800、PRO V620，gfx1030 | Ubuntu 22.04.5、24.04.4、26.04；RHEL 9.8、10.2 | ❌ | ❌ |
| 全部官方 gfx1151 Ryzen AI Max 型号 | Ubuntu 26.04；Ubuntu 24.04.4 HWE 6.17 | ✅ Windows 11 25H2 | ✅ |
| Ryzen AI 7 445、AI 5 435、430、AI 5 PRO 435，gfx1153 | Ubuntu 26.04；Ubuntu 24.04.4 HWE 6.17 | ✅ Windows 11 25H2 | ✅ |
| Ryzen AI 9 HX PRO 475、470；AI 9 PRO 465；AI 9 HX 475、470；AI 9 465、AI 9 HX 375、370、AI 9 365，gfx1150 | Ubuntu 26.04；Ubuntu 24.04.4 HWE 6.17 | ✅ Windows 11 25H2 | ✅ |
| Ryzen AI 9 HX PRO 375、370，gfx1150 | Ubuntu 26.04；Ubuntu 24.04.4 HWE 6.17 | ✅ Windows 11 25H2 | ❌ |
| Ryzen AI 7 PRO 450、AI 5 PRO 440、AI 7 450，gfx1152 | Ubuntu 26.04；Ubuntu 24.04.4 HWE 6.17 | ✅ Windows 11 25H2 | ✅ |
| Ryzen AI 7 PRO 350、AI 5 PRO 340、AI 7 350、345、AI 5 340、330，gfx1152 | Ubuntu 26.04；Ubuntu 24.04.4 HWE 6.17 | ✅ Windows 11 25H2 | ❌ |
| Ryzen 200，gfx1103 | Ubuntu 26.04；Ubuntu 24.04.4 HWE 6.17 | ✅ Windows 11 25H2 | ❌ |

注意：

1. R9700 与 R9600D 同为 gfx1201，WSL2 结论相反(一个支持WSL2，一个不支持WSL2)。
2. RX 9060 XT 与 RX 9060 XT LP 同为 gfx1200，WSL2 结论相反。
3. Ryzen AI 9 HX PRO 375 与 475 同为 gfx1150，WSL2 结论相反。

## 安装PyTorch前

一个 ROCm PyTorch 环境至少有四层：

1. 具体 GPU 和操作系统组合属于支持范围；
2. 内核驱动已创建可计算的 GPU 设备；
3. Python 环境安装了与 gfx 对应的 device 代码；
4. PyTorch 的版本组合与 Python 版本匹配。

pip 安装成功，只代表 Python 包和部分依赖已装好，不代表 ROCm 已经能使用 GPU。
我会先在 Linux 终端收集这四项：

    lspci -nn | grep -Ei 'vga|3d|display'
    cat /etc/os-release
    uname -r
    python3 --version

上面的 gfx 表决定安装标签，OS 表决定环境边界。这四项只能确认型号、系统、内核与 Python 版本；驱动装好后，再用 rocminfo 确认 ROCm 是否识别到计算设备，再到 [PyTorch 安装页](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html) 选对应版本。

### 第一步：创建隔离的 Python 环境

ROCm 7.14.0 的官方 PyTorch 页面支持 Python 3.11 到 3.14。

Ubuntu 先补齐虚拟环境与运行库：

    sudo apt update
    sudo apt install python3-venv libatomic1 libquadmath0

再创建项目专用环境：

    python3 --version
    mkdir -p ~/venvs/pytorch-rocm
    cd ~/venvs/pytorch-rocm
    python3 -m venv .venv
    . .venv/bin/activate
    python -m pip install --upgrade pip

看到 .venv 且 python --version 在 3.11 到 3.14 范围内，就可以继续。以后使用前先进入该虚拟环境。

### 第二步：安装与 gfx 匹配的 PyTorch

ROCm 7.14.0 的 Python 仓库采用 multi-arch。索引地址不再区分 gfx，device-gfxXXXX extra 才决定下载哪份 GPU kernel。

我用 gfx1100 演示。将两处 gfx1100 换成前表查到的值。

    python -m pip install --index-url https://repo.amd.com/rocm/whl-multi-arch/ \
        'torch[device-gfx1100]==2.12.0+rocm7.14.0' \
        'torchvision[device-gfx1100]==0.27.0+rocm7.14.0' \
        'torchaudio==2.11.0+rocm7.14.0'

这三个版本号必须成组使用，不要根据包名或 gfx 自行凑版本。

下表来自[官方安装页](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html)。较旧组合不一定覆盖每个 gfx 和操作系统，最终以安装页选择器为准。

| torch | torchvision | torchaudio | 使用边界 |
| --- | --- | --- | --- |
| 2.12.0 | 0.27.0 | 2.11.0 | 本文默认示例，优先选官方当前组合 |
| 2.11.0 | 0.26.0 | 2.11.0 | 仅当官方安装页在你的 gfx 和 OS 组合下明确列出这组版本时使用 |
| 2.10.0 | 0.25.0 | 2.10.0 | 较早的 ROCm 7.14 组合，仍须由安装页确认 |

我建议只记住三点：

- torch 与 torchvision 必须带 device-gfxXXXX，才能拉到对应架构的 device 代码。
- torchaudio 不带 device extra。

### device-all 什么时候才值得装

单机开发只装自己显卡对应的 device-gfxXXXX。这样下载更小，依赖也更少。

| 安装方式 | 包含的 GPU 架构 | 适用场景 |
| --- | --- | --- |
| device-gfxXXXX | 一种 gfx | 单机、单卡开发，推荐 |
| 多个 device-gfxXXXX | 指定的多种 gfx | 一个 Docker 镜像要跑在几种已知 AMD GPU 上 |
| device-all | 当前索引中的全部 gfx | 通用镜像、无法预先确定目标显卡 |

## PyTorch验证：用两个检查确认不是空装

安装后，我先在 Linux 环境确认 device 包存在：

    python -m pip freeze | grep -E 'amd-torch-device|rocm-sdk-device'

输出应包含目标 gfx，例如 amd-torch-device-gfx1100。再检查 ROCm 实际报告的目标：

    rocminfo | grep -oE 'gfx[0-9a-z]+' | sort -u

笔记本、APU 加独显和虚拟化环境可能列出多个 gfx。先确认用于计算的 GPU 对应哪个 gfx；安装完成后，再用 torch.cuda.get_device_name(0) 确认 PyTorch 实际使用的设备。

最后运行一次最小张量计算。它验证 GPU 执行，不代表性能测试：

    python - <<'PY'
    import torch

    print('torch:', torch.__version__)
    print('HIP:', torch.version.hip)
    print('available:', torch.cuda.is_available())

    if not torch.cuda.is_available():
        raise SystemExit('ROCm device is unavailable')

    print('device:', torch.cuda.get_device_name(0))
    x = torch.randn((2048, 2048), device='cuda')
    y = x @ x
    torch.cuda.synchronize()
    print('result:', y.device, y.shape, float(y[0, 0]))
    PY

我只看三个结果：

1. available 显示 True；
2. HIP 显示非空版本；
3. result 的设备为 cuda:0，且矩阵乘法正常返回。

ROCm 沿用 torch.cuda 和 cuda:0 以兼容 PyTorch API，这不表示程序在调用 NVIDIA GPU。

## Docker：想隔离 Python 依赖时的官方路径

Docker 只能隔离用户态依赖，不能替宿主机安装 AMD GPU 驱动。本节假设原生 Linux 的驱动已正常工作，且系统存在 /dev/kfd 和 /dev/dri/renderD* 等设备节点；不满足时，先按 [ROCm 安装页](https://rocm.docs.amd.com/en/docs-7.14.0/install/rocm.html) 完成驱动与权限配置，再继续使用 Docker。

以下镜像来自官方 PyTorch 安装页，组合为 ROCm 7.14、Ubuntu 24.04、Python 3.12 与 PyTorch 2.12.0：

    docker pull rocm/pytorch:rocm7.14_ubuntu24.04_py3.12_pytorch_release_2.12.0

按官方示例启动：

    docker run --rm -it \
        --device=/dev/kfd \
        --device=/dev/dri \
        --network=host \
        --group-add=video \
        --ipc=host \
        --cap-add=SYS_PTRACE \
        --security-opt seccomp=unconfined \
        rocm/pytorch:rocm7.14_ubuntu24.04_py3.12_pytorch_release_2.12.0 bash

进入容器后先做最小检查：

    python -c 'import torch; print(torch.__version__); print(torch.cuda.is_available())'

## Windows 和 WSL2：同一个 gfx 也要重新核对

### 原生 Windows

命令如下：
    py -3.12 -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install --upgrade pip
    python -m pip install --index-url https://repo.amd.com/rocm/whl-multi-arch/ 'torch[device-gfx1201]==2.12.0+rocm7.14.0' 'torchvision[device-gfx1201]==0.27.0+rocm7.14.0' 'torchaudio==2.11.0+rocm7.14.0'

### WSL2

我会把 WSL2 安装分为 Windows 主机和 在 Windows 中通过 WSL2 安装并打开的 Ubuntu 两部分：

1. 先在 ROCm 兼容性矩阵中确认完整 GPU 型号是否支持 WSL2；
2. 在 Windows 主机安装该型号对应的 AMD 驱动；
3. 在 Windows 中按 [ROCm 7.14.0 安装页](https://rocm.docs.amd.com/en/docs-7.14.0/install/rocm.html) 的 [WSL2 步骤](https://learn.microsoft.com/en-us/windows/wsl/install)安装 WSL2 和官方支持的 Ubuntu 发行版；
4. 进入 Ubuntu 后，按官方页面安装 Python 和 python3-venv或者 Docker ，必要系统库，例如 libatomic、libquadmath等前置组件。若该路径要求 ROCDXG，再在 Ubuntu 中按 [librocdxg Quickstart](https://github.com/ROCm/librocdxg) 安装。

## 官方表外的显卡：TheRock nightly 路径

如果显卡不在 ROCm 7.14.0 官方硬件表中，可以查询 TheRock 的 nightly 构建。它提供更多 gfx 的编译产物，适合在新的虚拟环境中验证。

下表来自 [TheRock RELEASES.md](https://github.com/ROCm/TheRock/blob/54d14392b27167b862bf5747f1d8cd1b13a4b23c/RELEASES.md)。

| nightly device extra | 覆盖的卡或 iGPU | 边界 |
| --- | --- | --- |
| device-gfx1031 | RX 6750 XT、RX 6700 XT | RDNA 2，非发布版支持 |
| device-gfx1032 | RX 6600 XT、RX 6600、PRO W6600 | RDNA 2，非发布版支持 |
| device-gfx1033 | Van Gogh iGPU | 非发布版支持 |
| device-gfx1034 | RX 6500 XT | RDNA 2，非发布版支持 |
| device-gfx1035 | Radeon 680M iGPU | 非发布版支持 |
| device-gfx1036 | Raphael iGPU | 非发布版支持 |
| device-gfx1030 | RX 6900 XT、RX 6800 XT | 发布版官方 gfx1030 只覆盖 PRO W6800、PRO V620 |
| device-gfx1010 | RX 5700、RX 5700 XT | RDNA 1，非发布版支持 |
| device-gfx1011 | PRO V520 | RDNA 1，非发布版支持 |
| device-gfx1012 | PRO W5500 | RDNA 1，非发布版支持 |
| device-gfx906 | MI60、MI50、Radeon VII、Radeon Pro VII | 较旧卡，非发布版支持 |
| device-gfx900 | MI25 | 较旧卡，非发布版支持 |

以下命令以 device-gfx1031 为例，对应 RX 6750 XT、RX 6700 XT。请在新的 venv 中执行，并将两处 device-gfx1031 一起替换为自己的目标：

    python -m pip install --index-url https://rocm.nightlies.amd.com/whl-multi-arch/ \
        'torch[device-gfx1031]' \
        'torchvision[device-gfx1031]' \
        torchaudio

## 非 ROCm 备选路径：DirectML 与 llama.cpp Vulkan

- Windows 上可评估 [PyTorch with DirectML](https://github.com/microsoft/DirectML)。它是 Microsoft 的 DirectX 12 后端，不属于 ROCm。DirectML 已进入维护模式，PyTorch 版本和算子覆盖有限；推理、训练和性能都应按项目单独验证。
- 对 llama.cpp 等本地大模型推理程序，可评估 llama.cpp 的 [Vulkan 后端](https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md)。它适合本地推理，不是通用 PyTorch 后端，也不能替代 HIP 自定义算子或 PyTorch 训练。

只有项目确实需要长期训练、定制算子和官方支持时，我才会最后考虑硬件升级。购买仍按完整 SKU 和目标系统判断，不只看 gfx。

## 常见问题：先按环境判断根因

| 适用环境 | 现象 | 更可能的根因 | 最小处理方式 |
| --- | --- | --- | --- |
| 原生 Linux | torch.cuda.is_available 为 False | 漏装 device extra、设备权限异常或驱动未正常工作 | 先查 device 包，再查 /dev/kfd、render 与 video 组 |
| 原生 Linux | 没有 /dev/kfd | 驱动、内核、Secure Boot 或系统组合不对 | 回到宿主机驱动与兼容性矩阵，不要重装 Python 包 |
| Linux、Windows、WSL2 | 出现 no kernel image 一类错误 | 安装了错误 gfx 的 device 包 | 对照实际 GPU 的 gfx 与 device-gfxXXXX，在新 venv 中重装 |
| 原生 Windows | torch.cuda.is_available 为 False | GPU 型号、Windows 版本、AMD 驱动或 PyTorch wheel 不匹配 | 按兼容性矩阵核对型号与驱动；不要检查 /dev/kfd |
| WSL2 | torch.cuda.is_available 为 False | GPU 型号、Windows 驱动、Ubuntu 版本或 ROCDXG 路径不匹配 | 按 WSL2 选择器逐项核对；仅在官方路径要求时安装 ROCDXG |
| 原生 Linux | 导入时提示缺少 libnuma | 缺少系统 NUMA 库 | Ubuntu 执行 sudo apt install libnuma1，再重新打开 venv |
| 所有环境 | pip 找不到 wheel | Python、版本组合、索引地址或 device extra 不匹配 | 确认 Python 为 3.11 到 3.14，并按官方页面使用完整安装命令 |

原生 Linux 排查时，我会收集完整型号、系统版本、uname -r、rocminfo 的 gfx 输出和 device 包名。原生 Windows 则重点检查型号、系统版本、AMD 驱动与 wheel；WSL2 还要检查 Ubuntu 发行版和官方是否要求 ROCDXG。

## 小结

我把流程压缩成三步：

1. 先查显卡完整型号，再查对应的 gfx。

2. 安装 PyTorch 时，必须使用与自身架构对应的 device-gfxXXXX。

3. 不要只看 pip install 成功；必须确认 torch.cuda.is_available() == True，并完成一次 Tensor 计算。

这只能证明基础 GPU 执行链路已经打通，不代表显存容量和性能足以满足实际模型。后续应根据模型大小、量化精度、上下文长度和 batch 大小，选择量化、offload 或合适的推理框架。Docker 只用于隔离依赖，不能增加显存；软件方案仍不能满足需求时，再考虑升级硬件。

## 参考资料

- [ROCm 7.14.0 Release Notes 与官方硬件支持表](https://rocm.docs.amd.com/en/docs-7.14.0/about/release-notes.html)
- [ROCm 7.14.0 兼容性矩阵](https://rocm.docs.amd.com/en/docs-7.14.0/compatibility/compatibility-matrix.html)
- [安装 AMD ROCm 7.14.0](https://rocm.docs.amd.com/en/docs-7.14.0/install/rocm.html)
- [ROCm 7.14.0 的 PyTorch 安装页，滚动页面](https://rocm.docs.amd.com/projects/ai-ecosystem/en/latest/frameworks/pytorch/install.html)
- [TheRock supported GPUs，2026-08-04 快照](https://github.com/ROCm/TheRock/blob/54d14392b27167b862bf5747f1d8cd1b13a4b23c/SUPPORTED_GPUS.md)
- [TheRock RELEASES.md，2026-08-04 快照](https://github.com/ROCm/TheRock/blob/54d14392b27167b862bf5747f1d8cd1b13a4b23c/RELEASES.md)

## 名词解释

- SKU（Stock Keeping Unit）是厂商实际拿出来卖的那一个具体型号，比架构更细一层。同一个架构下有好几个 SKU：例如同为 gfx1200 的 RX 9060 XT 与 RX 9060 XT LP，官方 WSL2 支持状态不同。用rocm-smi --showproductname查询，其中Card SKU:xxxx，是 AMD 板卡的内部编号。
- 用户态依赖：是普通程序运行时使用的库和工具，不直接控制硬件。包括Python 与 venv；PyTorch、torchvision、torchaudio；ROCm 的 HIP、rocBLAS 等用户态库；模型代码和 Python 依赖。相对的是内核态驱动，例如 amdgpu、KFD。它负责直接管理 GPU、创建 /dev/kfd 等设备节点，必须装在宿主机系统里。
- ROCDXG：WSL 内的 ROCm 桥接库，用于让 Ubuntu 中的 ROCm 程序使用 Windows 主机的 AMD GPU 驱动。
- SLA：Service Level Agreement，服务级别协议或服务承诺。nightly 不享受官方发布版的稳定性、兼容性、修复和问题响应承诺，更新后可能出现回归。

### 我会为大家持续更新AMD GPU,ROCm和本地AI相关内容哦~
