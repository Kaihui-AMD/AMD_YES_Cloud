# 面向 Helios GPU 的教学型 GEMM 优化阶梯

<!--
Copyright (c) 2026 Advanced Micro Devices, Inc. (AMD)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
-->

AMD Helios 将成为重要的 AI 平台。每颗 Helios GPU 配备 432 GB HBM4，HBM 带宽达到
23 TB/s，并提供 40 PFLOPS 的 FP4 算力
（参见 [AMD Instinct MI455X GPU 产品简介](https://www.amd.com/content/dam/amd/en/documents/products/accelerators/instinct/amd-instinct-mi455x_brochure.pdf)）。
这些能力对于大型前沿模型和长上下文智能体工作负载尤其有价值。

本文将重点介绍 Helios 架构的多项特性，并构建一套教学型 BF16 通用矩阵乘法
（General Matrix Multiplication，GEMM）内核优化阶梯，逐级利用这些硬件能力。
这套优化阶梯受到 Simon Boehm 的 CUDA GEMM 优化工作日志
[How to Optimize a CUDA Matmul Kernel for cuBLAS-like Performance: a Worklog](https://siboehm.com/articles/22/CUDA-MMM)
启发，旨在帮助内核开发者理解 Helios 的新硬件特性如何影响内核设计。

## HipKittens 简介

本文的内核实现和优化阶梯都使用 HipKittens。开始深入分析之前，先列出主要参考资料：
[HipKittens: Fast and Furious AMD Kernels](https://arxiv.org/abs/2511.08083)
介绍了该框架，[HipKittens 代码仓库](https://github.com/HazyResearch/HipKittens)
则包含源代码和内核示例。

## Helios 特性概览

一颗 Helios GPU 包含 256 个工作组处理器（Workgroup Processor，WGP），分布在
8 个加速器复合裸片（Accelerator Complex Die，XCD）上。每个 WGP 配备 320 KB
本地数据共享存储（Local Data Share，LDS），每个 wave 可使用 1,024 个 32 位寄存器。
GPU 配备 432 GB HBM4，峰值带宽为 23 TB/s。Helios 的纵向扩展域在每个机架中包含
72 颗 GPU，互连带宽为 3.6 TB/s，并提供统一虚拟内存抽象，从而简化节点内存访问。

| 硬件单元 | 说明 |
| --- | --- |
| 单指令多数据处理器（SIMD） | 由 32 条 lane 组成，每条 lane 都有自己对应的一组向量通用寄存器（VGPR）。 |
| 工作组处理器（WGP） | GPU 中 256 个处理器之一；在较早的 AMD GPU 世代中称为计算单元（CU）。每个 WGP 包含两对 SIMD，共 4 个 SIMD。 |
| 着色器引擎（Shader Engine，SE） | 由 16 个物理位置相邻的 WGP 组成。 |
| 加速器复合裸片（XCD） | 一个 chiplet，由 32 个物理位置相邻的 WGP 组成。 |
| I/O 裸片（IOD） | 基础裸片，其上堆叠 4 个 XCD。每个 IOD 包含 96 MiB 一致性 L2 缓存。 |
| GPU | 一颗 AMD Instinct MI455X GPU 由两个 IOD 组成。 |

<p align="center">表 1：CDNA 5 Helios GPU 的物理计算层次结构。</p>

| 执行单元 | 说明 |
| --- | --- |
| 线程（Thread） | GPU 上最小的执行单元。 |
| Wave | 由 32 个锁步执行的线程组成。较早的 AMD GPU 每个 wave 包含 64 个线程。 |
| 工作组（Workgroup） | 一组在同一 WGP 上协同调度的 wave。 |
| 工作组集群（Workgroup cluster） | 一组在同一着色器引擎上并发运行的工作组。 |
| 网格（Grid） | 一次内核启动所包含的全部工作组或工作组集群。 |

<p align="center">表 2：CDNA 5 上的 HIP 逻辑执行层次结构。</p>

| 存储层级 | 说明 |
| --- | --- |
| VGPR | SIMD 作用域的向量寄存器文件：包含 1,024 个寄存器，每个寄存器由 32 条 lane 上的 32 位值组成。 |
| LDS/L1 | 每个 WGP 有 6 个 64 KB 硬件分区。其中最多 5 个（320 KB）可分配给 LDS，并至少保留 1 个作为 L1。 |
| L2 | 两个一致性的 96 MB 半区，每个 IOD 一个，每个设备合计 192 MB。 |
| 高带宽内存（HBM） | 8 组 54 GB HBM4 堆栈，合计 432 GB。 |

<p align="center">表 3：CDNA 5 Helios GPU 的物理存储层次结构。</p>

存储层次结构各级的关键变化包括：

- **分区式 LDS。** 每个 WGP 有 5 个 64 KB LDS 分区。LDS 仍采用 bank 组织，因此数据布局必须避免
  bank 冲突。LDS 由两条每周期 256 字节的数据通路提供服务，每对 SIMD 对应一条通路。
  对同一分区的并发访问可能产生分区冲突，因此高带宽内核既要考虑分区内部的 bank 布局，
  也要考虑数据在不同分区之间的位置。仅一条每周期 256 字节的通路便足以使矩阵核心达到饱和。
- **缓存结构、NUMA 效应与内存预取。** 较早的 AMD GPU 同时使用每 XCD 的 L2 缓存和全局末级缓存
  （Last-Level Cache，LLC）。Helios 将该层次简化为单级 L2 缓存，在物理上由每颗 GPU
  两个一致性的 96 MB 半区组成。距离某个处理器更近的半区带宽明显高于远端半区
  （近端 L2 超过 40 TB/s，远端 L2 约为 20 TB/s）。GPU 的 8 个 XCD 中，每 4 个 XCD
  位于一个本地 L2 NUMA 域。内核开发者可通过缓存提示管理 L2 行为，包括从设备端或主机端
  将全局内存预取至 L2。
- **面向全局 HBM 的张量数据搬运（Tensor Data Movement，TDM）。** TDM 提供 HBM 与 LDS 之间
  类似 DMA 的传输路径，支持 scatter-gather 访问模式，并在 ISA 中公开其描述符架构。
  与硬件 swizzle 加载不同，TDM 不会在搬运过程中即时重排 LDS 数据，因此仍需通过填充
  （padding）或布局设计来避免 bank 冲突。

执行模型的关键变化包括：

- **Wave 大小。** Helios 的每个 wave 包含 32 个线程，而此前 AMD GPU 的每个 wave 包含
  64 个线程。在较早的架构中，一个 64 线程 wave 要在 16 条物理 SIMD lane 上执行，
  lane 的数据归属与内存访问模式因而不够规则，内核开发者在优化内存布局时必须专门处理这些问题
  （参见 [AMD GPUs go brrr](https://hazyresearch.stanford.edu/blog/2025-11-09-amd-brr)）。[^1]
  Helios 将 32 线程 wave 与 32 条物理 SIMD lane 一一对应，使 lane 的数据归属更规整，
  也简化了内存布局优化。
- **工作组集群启动与多播。** Helios 能够保证最多 16 个工作组以集群方式协同放置在相邻 WGP 上，
  从而支持集群内的数据共享与同步。无需让每个工作组独立请求同一份数据，一次加载即可多播至多个
  WGP，通过缓存复用提高有效带宽。

下面开始实际运用这些特性。

[^1]: 在 AMD Instinct MI355X GPU 上，一个 tile 由包含 64 个线程的 wave 共同持有，
    HipKittens 必须决定每个线程负责哪些元素。当这些线程发出 LDS 操作时，并不会简单地按照
    线程 0 到线程 63 的顺序同时访问 LDS。不同的 `ds_*` 指令会将 wave 拆分成不同且有时并非
    连续的阶段。例如，HipKittens 观察到 `ds_read_b128` 与 `ds_write_b64` 的行为并不相同。

## 教学型 GEMM 优化阶梯

受 Simon Boehm 的 GEMM 工作日志启发，我们面向 Helios GPU 提出一套教学型 GEMM 优化阶梯。
图 1 展示 MI455X 的硬件层次结构，以及 GEMM tile 如何映射到该结构上。

![MI455X 从 HBM、XCD 到 WGP、SIMD、wave 和线程的硬件层次结构](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/mi455x-hardware-hierarchy.svg)

![A、B 矩阵 tile 映射到负责累加 C 输出 tile 的 MI455X WGP](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/mi455x-gemm-tile-mapping.svg)

<p align="center">图 1：MI455X 的层次结构从 GPU 逐级细化为 XCD、WGP、SIMD、wave 和线程（上图）。
在 GEMM 中，A、B 的 tile 会映射至负责累加 C 输出 tile 的 WGP（下图）。</p>

对于大规模 GEMM，可将输出矩阵划分为能够独立计算的 tile。每个工作组由一组协同调度到同一 WGP
的 wave 组成，并负责计算一个输出 tile。每个 WGP 都有自己的寄存器文件和 LDS，以及执行矩阵乘法、
指数运算和其他算术运算的电路，支持 BF16、FP8、FP6、FP4 等数据类型。所有 WGP 还可访问 GPU
共享的缓存层次和 HBM。图 2 汇总了整个优化阶梯的实测性能。

![GEMM 优化阶梯各级的平均相对 BF16 性能](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/ladder-performance.svg)

<p align="center">图 2：GEMM 优化阶梯各级内核的平均性能，以 HipKittens MI355X 内核为基准归一化。</p>

即使仅优化到阶梯中段，内核性能也已经超过充分优化的 MI355X GEMM 内核；最终的 Helios 内核
则接近其两倍性能。这些测试运行在早期样片 GPU 上，其固件和软件仍在持续获得显著改进。

每一级都计算 $C=AB$，其中 $A \in \mathbb{R}^{M \times K}$、
$B \in \mathbb{R}^{K \times N}$、$C \in \mathbb{R}^{M \times N}$。
输入和输出均使用 BF16 精度，内核通过
[HipKittens: Fast and Furious AMD Kernels](https://github.com/HazyResearch/HipKittens)
编写。对于每个内核，本文报告 $M=N=K=8192$ 时达到的 PFLOP/s：先执行 500 次预热迭代，
再执行 100 次计时迭代，并在测试中清空 L2 缓存。完整基准测试脚本可在 HipKittens 仓库中获取。

对于每一级，本文还展示内核热循环，也就是沿 GEMM 的 K 维执行的循环。跟踪数据使用
[ROCm Systems 仓库](https://github.com/ROCm/rocm-systems)中的分析工具，通过 AMD Advanced
Thread Trace（ATT）采集。在这些可视化图中，每一行表示一个 wave 随时间执行指令的情况，
多行组成的一组则展示 WGP 的一个或多个 SIMD 上的执行过程。

### Level 0：朴素基线（[gemm_naive.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/00_gemm_naive.cpp#L58-L82)）

每个工作组使用 4 个 wave 计算一个 $64 \times 64$ 输出 tile。wave 按 $2 \times 2$
网格排列，每个 wave 计算输出 tile 中一个 $32 \times 32$ 区域，并维护对应的寄存器 tile
用于累加。内核以 32 为步长沿 K 维迭代。在每次迭代中，所有线程协作地将 A、B 的
$64 \times 32$ tile 从全局内存加载到 LDS。同步之后，每个 wave 将自己负责的 A、B 子 tile
从 LDS 加载到寄存器，执行矩阵乘法，并将结果累加至输出 tile。

该基线只为 A 和 B 使用一组 LDS 缓冲区，数据搬运与计算之间没有重叠。因此，每次 K 维迭代
都完全串行地执行：先把 A、B 从全局内存加载至 LDS，完成同步，再从 LDS 加载至寄存器并计算，
再次同步，然后才能开始加载下一个 K tile。由于每次迭代都要复用同一 LDS 缓冲区，所以第二次
同步不可省略。最终，数据搬运期间矩阵单元处于空闲状态，计算期间内存流水线也没有得到充分利用。
下图展示了这种串行调度。

![朴素 GEMM 内核中串行执行的数据搬运与矩阵计算](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level0-naive-diagram.svg)

<p align="center">图 3：Level 0 依次串行执行全局加载、LDS 暂存、寄存器加载和 WMMA。</p>

#### Level 0 API

| API | 用途 |
| --- | --- |
| [`load(A_LDS, A_global)`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/memory/tile/global_to_register.cuh#L29-L98) | 使用向量 lane 将全局内存 tile 经由寄存器复制到 LDS。 |
| [`load(A_reg, A_LDS)`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/memory/tile/shared_to_register.cuh#L845-L914) | 将一个 wave 的 LDS 分片加载到寄存器。 |
| [`sync::fence()`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/sync/barrier.cuh#L180-L216) | 在发布或复用 LDS 之前，等待内存传输全部完成。 |
| [`sync::sync()`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/sync/barrier.cuh#L156-L170) | 在工作组屏障处等待所有 wave。 |
| [`mma_ABt(C, A_reg, B_reg)`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/register/tile/mma.cuh#L280-L308) | 计算 BF16 的 $AB^T$，并将结果累加到 FP32 寄存器。 |
| [`store(C_global, C_acc)`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/memory/tile/global_to_register.cuh#L127-L196) | 转换 FP32 累加结果，并直接写入全局内存中的 C tile。 |

#### Level 0 伪代码

```cpp
for each K tile:
    load(A_LDS, A_global);       // A：全局内存 -> 暂存寄存器 -> LDS
    load(B_LDS, B_global);       // B：全局内存 -> 暂存寄存器 -> LDS
    sync::fence();               // 等待全局内存到 LDS 的传输完成
    sync::sync();                // 等待同组 wave 发布 LDS 数据
    load(A_reg, A_LDS);          // A：LDS -> 寄存器
    load(B_reg, B_LDS);          // B：LDS -> 寄存器
    mma_ABt(C, A_reg, B_reg);    // 累加 C += A * B^T
    sync::fence();               // 等待 LDS 读取完成
    sync::sync();                // 复用 LDS 前等待
```

图 4 展示一个 SIMD 上来自不同工作组的 12 条驻留 wave 轨迹；调度器会在它们之间自动切换，
以最大化资源利用率。

![朴素 GEMM 内核的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level0-naive-trace.png)

<p align="center">图 4：Level 0 在 SIMD 0 上的 ATT 轨迹。12 条轨迹来自不同工作组的驻留 wave；
经由寄存器的数据填充和同步使矩阵计算指令显得十分稀疏。</p>

在 SIMD 0 的 wave 槽位 0 上，前段绿色 VALU 指令来自经由寄存器完成的 A/B 数据填充和地址计算。
周期 1,218 到 1,620 之间的 4 条紫色 WMMA 指令对应 `mma_ABt`。较长的黄色区间与发布和复用阶段
的同步相符，不过仅凭颜色无法确定具体是哪一种屏障。

### Level 1：LDS 双缓冲（[gemm_double_buf.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/01_gemm_double_buf.cpp#L65-L89)）

- **性能：** 相比 Level 0 提升不到 1%（图 2 中相对于 MI355X 基线由 25.3% 提升至 25.4%）。

前一个内核严重低估了每个 WGP 可用的 320 KB LDS。对于 $64 \times 64$ 输出 tile 和
`BLOCK_K=32`，Level 0 的单级缓冲仅占用 8.5 KB，即总容量的 2.7%。两级缓冲需要 17 KB，
也只占 5.3%，因此双缓冲是顺理成章的下一步。

该内核为 A、B 分别分配两组 LDS 缓冲区，并将 K 循环改造成两级软件流水线。首先，序言阶段加载
并发布第一组 A/B tile；随后，每次迭代一边向非活动缓冲区发起 HBM 加载，一边让 WMMA 使用当前
缓冲区。末尾的工作组屏障可确保下一缓冲区已经可读，同时当前缓冲区能够安全覆写，然后再交换两者。

**为何有效：** 双缓冲让内存加载与计算重叠，提升指令级并行度。此处实测增幅依然很小，因为数据填充
仍需经过寄存器，而且每个 K block 在交接前仍会完全排空。Level 2 保留相同的分级缓冲结构，
但改用异步直达 LDS 的复制；双缓冲的收益将在那一级真正体现出来。

![将下一次全局加载与当前计算重叠的 LDS 双缓冲流水线](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level1-double-buffer-diagram.svg)

<p align="center">图 5：Level 1 在当前 K tile 为 WMMA 供数的同时，暂存下一个 K tile。</p>

#### Level 1 API

| API | 用途 |
| --- | --- |
| [`allocate_in<segment<0>, Tile, 2>()`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/common/util.cuh#L478-L501) | 为当前和下一个操作数 tile 预留两个紧密排列的 LDS 槽位。 |
| [`sync::wait_ds<0>()`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/sync/barrier.cuh#L206-L216) | 在内核退出前等待最后的 LDS 读取全部完成。 |

#### Level 1 伪代码

```cpp
A_LDS[2];
B_LDS[2];

load(A_LDS[current], A_global);
load(B_LDS[current], B_global);
sync::fence();
sync::arrive();
sync::wait();                    // 发布第一级 LDS 数据

for each K tile:
    load(A_LDS[next], A_global_clamped);
    load(B_LDS[next], B_global_clamped);

    load(A_reg, A_LDS[current]);
    load(B_reg, B_LDS[current]);
    mma_ABt(C, A_reg, B_reg);

    sync::fence();               // 等待数据填充和读取完成
    sync::arrive();
    sync::wait();                // 完成一次工作组屏障交接
    swap(current, next);
```

图 6 展示调度器在此级别如何交错执行驻留 wave。

![LDS 双缓冲 GEMM 内核的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level1-double-buffer-trace.png)

<p align="center">图 6：Level 1 在 SIMD 0 上的 ATT 轨迹。调度器交错执行 12 条驻留 wave
轨迹，但经由寄存器的全局内存到 LDS 搬运仍占据大部分 VALU 发射。</p>

与朴素内核相同，调度器在来自不同工作组的 12 个 wave 之间切换。SIMD 的大量时间仍用于绿色
VALU 工作，因为向量 lane 既要从全局内存把数据加载到寄存器，又要将寄存器写入 LDS。
矩阵计算指令依然稀疏。

### Level 2：异步 HBM 加载（[gemm_async.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/02_gemm_async.cpp#L59-L83)）

- **性能：** 相比 Level 1 提升 48%。

AMD Instinct MI455X GPU 可以将全局内存直接复制到 LDS，无需让数据经过寄存器文件。
异步复制采用发出后即继续执行的方式，并通过 `asynccnt` 完成退休。只有当数据真正成为依赖时，
wave 才会检查该计数器，因此数据填充无需放在每次迭代的开头，也无需以覆盖全部操作的排空作为结尾。

| 级别 | 数据填充路径 | 每个 K block |
| --- | --- | --- |
| 朴素基线 | 经由寄存器 | 两次完整屏障、两次 LDS 排空、两次全局加载排空 |
| 双缓冲 | 经由寄存器 | 一次完整屏障、一次 LDS 排空、一次全局加载排空 |
| 异步加载 | 直达 LDS | 一次拆分屏障、一次 LDS 排空、一次异步复制排空 |

直达 LDS 的加载无需通过 VGPR 暂存，从而降低寄存器压力，并为后续级别引入的更大输出 tile
释放寄存器空间。同时，它还消除了从寄存器存储并回写 LDS 的路径。

**为何有效：** 异步加载将数据从全局内存直接搬运到 LDS，避免在向量寄存器文件中往返。
下图展示直达 LDS 的复制如何与流水线其余部分重叠。

![与矩阵计算并行执行的全局内存直达 LDS 异步加载](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level2-async-diagram.svg)

<p align="center">图 7：Level 2 在后台执行全局内存直达 LDS 的复制，直至到达数据就绪关口。</p>

#### Level 2 API

| API | 用途 |
| --- | --- |
| [`load_async(A_LDS[next], A_global)`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/memory/tile/global_to_shared.cuh#L375-L441) | 在不使用 VGPR 的情况下启动全局内存直达 LDS 的复制。 |
| [`sync::wait_async<0>()`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/sync/barrier.cuh#L229-L239) | 在流水级交接前，等待无序异步复制全部完成。 |
| [`sync::arrive()` / `sync::wait()`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/sync/barrier.cuh#L136-L155) | 将工作组屏障的到达通知与等待操作分离。 |
| [`sched::compiler_fence()`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/sched/sched.cuh#L199-L214) | 阻止编译器将操作移动到流水级交接点的另一侧。 |

#### Level 2 伪代码

```cpp
load_async(A_LDS[current], A_global);
load_async(B_LDS[current], B_global);
sync::wait_async<0>();
sched::compiler_fence();
sync::arrive();
sync::wait();                    // 发布第一级 LDS 数据
sched::compiler_fence();

for each K tile:
    load(A_reg, A_LDS[current]);
    load(B_reg, B_LDS[current]);

    load_async(A_LDS[next], A_global_clamped);
    load_async(B_LDS[next], B_global_clamped);

    sync::wait_ds<0>();          // 等待当前 LDS 读取完成
    mma_ABt(C, A_reg, B_reg);
    sync::wait_async<0>();       // 等待下一批全局内存到 LDS 的填充完成
    sched::compiler_fence();
    sync::arrive();
    sync::wait();
    sched::compiler_fence();
    swap(current, next);
```

图 8 中有 9 条驻留 wave 轨迹。与前几级相比，等待向量操作的时间显著减少，因为向量 lane
只需发起直达 LDS 的加载，随后便可从 LDS 中读取更大的数据块。

![异步加载 GEMM 内核的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level2-async-trace.png)

<p align="center">图 8：Level 2 在 SIMD 0 上的 ATT 轨迹。将寄存器暂存替换为直达 LDS 的异步加载后，
9 条驻留 wave 轨迹中的 VALU 数据填充工作明显减少。</p>

### Level 3：将输出 tile 扩大到 128 x 128（[gemm_128x128.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/03_gemm_128x128.cpp#L58-L82)）

- **性能：** 相比 Level 2 提升 80%。

对于一个输出 tile，GEMM 的算术强度为：

$$
\frac{2MNK}{MK + KN + MN}.
$$

当 $M=N=K$ 时，该式可简化为 $2N/3$。因此，计算量随 tile 大小呈立方增长，
而所需数据搬运量只呈平方增长。GEMM 设计的一项核心原则，就是在寄存器和 LDS 容量允许的范围内，
尽可能增大每个 WGP 负责的输出 tile。

更大的 tile 还能提高数据复用。4 个 WGP 若分别计算相邻的 $64 \times 64$ 输出 tile，
必须重复加载共享的 A、B panel；若由一个 WGP 计算同一片 $128 \times 128$ 输出区域，
则每个 panel 只需加载一次，随后便可在更大的 tile 内复用，从而减少整个存储层次中的数据流量。
代价是：对于小规模问题，更大的 tile 可能会降低 WGP 占用率。

Level 3 让每个 WGP 计算一个 $128 \times 128$ 输出 tile。每个 wave 仍负责一个
$32 \times 32$ 输出 tile，因此每个工作组启动 16 个 wave。

**为何有效：** 增大输出 tile 可提高算术强度，并通过增强 WGP 内部的数据复用减少内存流量。
图 9 展示了更大 WGP 输出 tile 的调度方式。

![面向 128 x 128 WGP 输出 tile 的异步双缓冲 GEMM 调度](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level3-128x128-diagram.svg)

<p align="center">图 9：Level 3 在保留异步双缓冲 K 级流水线的同时，扩大了 WGP 输出 tile。</p>

图 10 中，每个 wave 包含更多矩阵指令，因为每个 WGP 现在负责更大的输出 tile。

![将输出 tile 扩大到 128 x 128 后的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level3-128x128-trace.png)

<p align="center">图 10：Level 3 在 SIMD 0 上的 ATT 轨迹。将 WGP 输出 tile 扩大到
$128 \times 128$ 后，每个 wave 发出的矩阵指令数量随之增加。</p>

### Level 4：将输出 tile 扩大到 256 x 256（[gemm_256x256.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/04_gemm_256x256.cpp#L62-L86)）

- **性能：** 相比 Level 3 提升 25%。

该内核让每个 WGP 计算一个 $256 \times 256$ 输出 tile。每个 wave 负责一个
$64 \times 32$ 输出 tile，每个工作组启动 16 个 wave，即每个 SIMD 运行 4 个 wave。
这样可进一步提高 LDS 中 WGP 级别的数据复用。

#### Level 4 配置

```cpp
BLOCK_M = BLOCK_N = 256;
WARPS_M = WARPS_N = 4;
rt_fl<64, 64> C_acc;

// 异步双缓冲 K 循环的其余部分保持不变。
```

图 11 展示采用 $256 \times 256$ WGP 输出 tile 时的调度。

![面向 256 x 256 WGP 输出 tile 的异步双缓冲 GEMM 调度](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level4-256x256-diagram.svg)

<p align="center">图 11：Level 4 将 WGP 输出 tile 扩大到 $256 \times 256$，
同时保留概念上相同的 K 级流水线。</p>

图 12 的开头是异步加载发射，随后是大段 LDS 读取，接着出现密集的紫色 WMMA 指令组。
这些指令组反映了每个 wave 增加的矩阵计算量。

![将输出 tile 扩大到 256 x 256 后的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level4-256x256-trace.png)

<p align="center">图 12：Level 4 在 SIMD 0 上的 ATT 轨迹。$256 \times 256$ WGP 输出 tile
产生了更加密集的 WMMA 指令组。</p>

### Level 5：加深 WMMA 指令的 K 维步长（[gemm_deepk.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/05_gemm_deepk.cpp#L62-L86)）

- **性能：** 相比 Level 4 提升 19%。

Level 1 在 HBM 与 LDS 之间引入了双缓冲，但 GEMM 内核仍可能在数据从 LDS 搬运到寄存器时停顿。
Level 5 为这条路径增加两级寄存器缓冲。现在，从 HBM 到 LDS 的加载会搬入
$256 \times 128$ 的 A tile 和 $128 \times 256$ 的 B tile，不再是 Level 4 使用的
$256 \times 32$ 与 $32 \times 256$ tile。

在外层 K 循环内部，还有一个包含 4 个 K=32 子步的内层循环。在每个子步中，wave 一边将
$64 \times 32$ 的 A tile 和 $32 \times 64$ 的 B tile 加载到一个寄存器缓冲槽位，
一边使用另一个槽位执行矩阵乘法。这样，除了已有的 HBM 与 LDS 搬运重叠之外，
LDS 到寄存器的搬运也能与计算重叠。

**为何有效：** 更深的 K 循环构造出粒度更细的流水级，为 LDS 读取与矩阵计算重叠创造更多机会。
下图展示由 4 个子步组成的寄存器流水线。

![将 LDS 读取与 WMMA 指令重叠的四子步 K 流水线](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level5-deepk-diagram.svg)

<p align="center">图 13：Level 5 在由 4 个子步组成的 K=128 流水线中提前读取数据。</p>

#### Level 5 伪代码

```cpp
load_async(A_LDS[current], A_global);
load_async(B_LDS[current], B_global);
sync::wait_async<0>();
sched::compiler_fence();
sync::arrive();
sync::wait();
sched::compiler_fence();

for each K stage:
    load(A_reg[0], A_LDS[current][0]);
    load(B_reg[0], B_LDS[current][0]);

    load_async(A_LDS[next], A_global_clamped);
    load_async(B_LDS[next], B_global_clamped);

    for substep = 0 .. 2:
        load(A_reg[next_reg], A_LDS[current][substep + 1]);
        load(B_reg[next_reg], B_LDS[current][substep + 1]);
        sync::wait_ds<DS_SUB>();
        mma_ABt(C, A_reg[current_reg], B_reg[current_reg]);
        swap(current_reg, next_reg);

    sync::wait_ds<0>();
    mma_ABt(C, A_reg[current_reg], B_reg[current_reg]);
    sync::wait_async<0>();
    sched::compiler_fence();
    sync::arrive();
    sync::wait();
    sched::compiler_fence();
    swap(current, next);
```

图 14 显示 4 条驻留 wave 轨迹。现在不再是大块、串行的 LDS 读取与计算，而是在每个子步中，
将下一子步的非矩阵操作与当前子步的矩阵计算交错执行。

![深 K 流水线的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level5-deepk-trace.png)

<p align="center">图 14：Level 5 在 SIMD 0 上的 ATT 轨迹。4 个 K=32 子步将下一子步的
LDS 读取与当前子步的 WMMA 执行交错起来。</p>

### Level 6：适配分区式 LDS（[gemm_segment.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/06_gemm_segment.cpp#L64-L88)）

- **性能：** 对本次基准测试的矩阵形状没有可测得的变化。

即使 LDS 访问不存在 bank 冲突，当不同 SIMD 对上的 wave 同时访问同一个 64 KB LDS 分区时，
仍可能因分区冲突而发生串行化。WGP 的 5 个 LDS 分区由两条每周期 256 字节的数据通路服务，
每对 SIMD 对应一条通路。Level 6 将 A、B 环形缓冲区放在不同分区中，使同时发生的操作数读取
能够避免分区冲突，并同时利用两条通路。

如需深入了解分区式 LDS 的组织方式及其冲突行为，请参阅
[深入解析 AMD Instinct MI450 GPU 上的 LDS 优化](https://rocm.blogs.amd.com/software-tools-optimization/mi450-lds-optimization/README.html)。

此级别只改变内存分配方式：所有 A 子 tile 放在同一个连续数组中，所有 B 子 tile 随后放入另一个
分区。K 循环以及其中的一次拆分屏障与 Level 5 保持一致。图 15 对比了 Level 5 与 Level 6
的 LDS 分配顺序。

![278 KiB 操作数环形缓冲在五个 64 KiB LDS 分区中的比例分布](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level6-partition-diagram.svg)

<p align="center">图 15：操作数环形缓冲共 278 KiB，跨越 5 个 64 KiB 分区。Level 6 仅改变
<code>segment&lt;0&gt;</code> 中的分配顺序：由
<code>[A0][B0][A1][B1]...</code> 改为
<code>[A0][A1]...[B0][B1]...</code>，从而让 A₀、B₀ 这类配对操作数位于不同物理分区。</p>

图 16 表明执行顺序没有变化。

![将 A、B 操作数环形缓冲置于不同 LDS 分区后保留的深 K 调度](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level6-segmented-lds-diagram.svg)

<p align="center">图 16：Level 6 保留 Level 5 的四子步执行顺序；优化只改变 A、B 环形缓冲
在 LDS 中的存放位置。</p>

**为何有效：** 虽然这一级没有改善实测的 $8192^3$ BF16 GEMM 性能，但面向分区的布局方式
能够降低其他矩阵形状、工作负载和更低精度数据类型中的串行化。

#### Level 6 伪代码

```cpp
// A、B 流水级分配在不同的 LDS 分区中。
load_async(A_LDS[current], A_global);
load_async(B_LDS[current], B_global);
sync::wait_async<0>();
sched::compiler_fence();
sync::arrive();
sync::wait();
sched::compiler_fence();

for each K stage:
    load(A_reg[0], A_LDS[current][0]);
    load(B_reg[0], B_LDS[current][0]);

    load_async(A_LDS[next], A_global_clamped);
    load_async(B_LDS[next], B_global_clamped);

    for substep = 0 .. 2:
        load(A_reg[next_reg], A_LDS[current][substep + 1]);
        load(B_reg[next_reg], B_LDS[current][substep + 1]);
        sync::wait_ds<DS_SUB>();
        mma_ABt(C, A_reg[current_reg], B_reg[current_reg]);
        swap(current_reg, next_reg);

    sync::wait_ds<0>();
    mma_ABt(C, A_reg[current_reg], B_reg[current_reg]);
    sync::wait_async<0>();
    sched::compiler_fence();
    sync::arrive();
    sync::wait();
    sched::compiler_fence();
    swap(current, next);
```

图 17 展示没有变化的四组 WMMA 执行顺序。

![分区式 LDS GEMM 内核的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level6-segmented-trace.png)

<p align="center">图 17：Level 6 在 SIMD 0 上的 ATT 轨迹。面向分区的 LDS 布局只改变地址，
不会改变 Level 5 的四组 WMMA 指令顺序。</p>

在 SIMD 0 的 wave 槽位 3 上，周期 2,531 到 2,941、3,051 到 3,642、3,746 到 4,293
以及 4,385 到 4,771 的 4 组紫色 WMMA 指令，分别对应 Level 5 的 4 个 `mma_ABt` 子步。
面向分区的布局改变了 LDS 地址，但没有改变矩阵操作顺序。该跟踪无法显示某次 LDS 访问实际使用了
哪个 64 KB 分区。

### Level 7：使用 TDM 加载（[gemm_tdm.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/07_gemm_tdm.cpp#L61-L85)）

- **性能：** 相比 Level 6 提升 38%。

张量数据搬运器（Tensor Data Mover，TDM）是每个 WGP 都可使用的异步数据引擎。
设备端 TDM 描述符能够描述最多 5 个维度的仿射访问模式，并指示引擎将数据加载到 LDS，
或将数据存回全局内存。这会把地址生成和加载指令发射工作从向量 lane 卸载出去。

TDM 根据设备端构建的描述符一次搬运整个 panel。只有两个负责发射的 wave 提交 A、B 传输，
其他 wave 可以继续计算。wave 0 提交 A 描述符，wave 1 提交 B 描述符，使两次传输使用不同的
引擎奇偶通道。寄存器环形缓冲保持不变，但原来的异步复制排空改由 `tensorcnt` 管理，并使用一个
深 panel 取代 4 个分别填充的子 tile。由于采用两级 LDS 缓冲，`wait_tdm<S-2>` 就是
`wait_tdm<0>`，即等待全部 TDM 操作完成。

该内核还使用带填充的 LDS 布局来实现无 bank 冲突访问，而不是在填充过程中消耗向量指令重排数据。
绝大多数逐 lane 加载、地址生成和布局处理工作都被消除，因此 TDM 独立填充下一级数据时，
可以为矩阵指令留出更多发射带宽。

**为何有效：**

1. 只有两个 wave 发出张量加载，其他 wave 可以继续执行，直至数据真正成为依赖。
2. 每个 wave 可以请求一次大型二维传输，无需发出大量 128 位的全局内存到 LDS 加载。
3. 启动引擎只需两条发射指令，分别来自两个发射 wave。
4. 地址生成、填充、必要时的转置以及零填充都卸载到专用功能单元。
5. 更简单的冒险结构便于编译器优化，同时能够降低寄存器压力。

下图展示由描述符驱动的 TDM 流水线。

![TDM panel 填充 LDS 时寄存器读取和矩阵计算继续执行](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level7-tdm-diagram.svg)

<p align="center">图 18：Level 7 以描述符驱动的 TDM panel 传输取代由 lane 发起的异步复制，
同时保留深寄存器流水线。</p>

#### Level 7 API

| API | 用途 |
| --- | --- |
| [`tdm::load_async(...)`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/memory/tile/tdm.cuh#L201-L257) | 提交一次由描述符驱动的全局内存到 LDS panel 传输。 |
| [`sync::wait_tdm<0>()`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/sync/barrier.cuh#L241-L252) | 在发布或复用 LDS 流水级之前，等待两次 TDM 传输全部完成。 |

#### Level 7 伪代码

```cpp
if (wave_id == 0)
    tdm::load_async(A_LDS[current], A_global);
if (wave_id == 1)
    tdm::load_async(B_LDS[current], B_global);
sync::wait_tdm<0>();
sched::compiler_fence();
sync::arrive();
sync::wait();
sched::compiler_fence();

for each K stage:
    load(A_reg[0], A_LDS[current][0]);
    load(B_reg[0], B_LDS[current][0]);

    if (wave_id == 0)
        tdm::load_async(A_LDS[next], A_global, count_or_zero);
    if (wave_id == 1)
        tdm::load_async(B_LDS[next], B_global, count_or_zero);

    for substep = 0 .. 2:
        load(A_reg[next_reg], A_LDS[current][substep + 1]);
        load(B_reg[next_reg], B_LDS[current][substep + 1]);
        sync::wait_ds<DS_SUB>();
        mma_ABt(C, A_reg[current_reg], B_reg[current_reg]);
        swap(current_reg, next_reg);

    sync::wait_ds<0>();
    mma_ABt(C, A_reg[current_reg], B_reg[current_reg]);
    sync::wait_tdm<0>();
    sched::compiler_fence();
    sync::arrive();
    sync::wait();
    sched::compiler_fence();
    swap(current, next);
```

图 19 展示由 lane 发起的数据填充工作得到明显削减。

![TDM GEMM 内核的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level7-tdm-trace.png)

<p align="center">图 19：Level 7 在 SIMD 0 上的 ATT 轨迹。TDM 消除了大部分由 lane 发起的
数据填充工作，使矩阵指令组成为主要活动。</p>

在 SIMD 0 的 wave 槽位 0 上，周期 289 到 533、638 到 1,145、1,249 到 1,732
的已解码 WMMA 指令组对应内层循环中的 3 次 `mma_ABt` 调用；周期 1,826 到 2,192
对应最后一次调用。开头较短的绿色区段是用于构建 TDM 描述符和偏移量的普通 VALU 工作。
由描述符驱动的 panel 搬运消除了大范围由 lane 发起的数据填充，使矩阵指令组成为主要颜色。
物理槽位标签不能用于判断源码中的 `wave_id`。

### Level 8：使用拆分屏障（[gemm_split_bar.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/08_gemm_split_bar.cpp#L71-L95)）

- **性能：** 相比 Level 7 提升 4%。

工作组屏障通常用于防止某个 wave 在另一个 wave 仍在读取 LDS 缓冲区时将其覆写。
使用传统屏障时，每个 wave 发出完成信号后会立即等待，先到达的 wave 因而会保持空闲，
直到最慢的 wave 到达。

拆分屏障将信号与等待分离。wave 完成最后一次 LDS 读取后，其操作数已经安全地保存在寄存器中，
因此可以先发出允许释放 LDS 缓冲区的信号。随后，该 wave 在等待同组 wave 之前，
先完成最后一次只使用寄存器的 WMMA。编译器屏障可确保 WMMA 位于这段区间内；
如果将它移到信号和等待区间之外，数值结果仍然正确，但预期的执行重叠会丢失。

**为何有效：** 拆分屏障让最后一个 K 子步与其他 wave 到达屏障的过程重叠，
以有效计算隐藏部分同步延迟。下图展示位于屏障到达和等待之间的矩阵计算。

![位于拆分屏障到达与等待操作之间的最后一段矩阵计算](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level8-split-barrier-diagram.svg)

<p align="center">图 20：Level 8 在同组 wave 到达屏障期间执行最后一个 K 子步。</p>

#### Level 8 的核心调度变化

```cpp
sync::wait_ds<0>();
sync::wait_tdm<0>();
sync::arrive();                  // 释放 LDS 流水级
mma_ABt(C, A_reg[final], B_reg[final]);
sync::wait();                    // 等待同组 wave
```

图 21 展示这一调度区间。

![拆分屏障 GEMM 内核的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level8-split-barrier-trace.png)

<p align="center">图 21：Level 8 在 SIMD 0 上的 ATT 轨迹。最后一组 WMMA 在拆分屏障的
信号与等待之间执行。</p>

在 SIMD 0 的 wave 槽位 0 上，屏障信号在周期 1,649 发出，随后在周期 1,653 到 1,776
之间执行 16 条 WMMA 指令，并在周期 1,784 等待屏障。槽位 1 在周期 1,923 到 2,058
重复相同的“信号、WMMA、等待”序列。最后一个紫色区块就是被有意放入拆分屏障窗口的矩阵计算。

### Level 9：使用工作组集群与多播（[gemm_wgc_multicast.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/09_gemm_wgc_multicast.cpp#L80-L109)）

- **性能：** 相比 Level 8 提升 7%。

一个工作组集群最多可以包含 16 个并发启动的工作组。集群内的工作组可以声明，
它们会与集群中的其他 WGP 共享指定数据。随后，对 L2 的重复请求可通过多播进行去重。

该内核将工作组组织成 $4 \times 4$ 集群。每个 A panel 沿集群的一列共享，
每个 B panel 沿集群的一行共享。因此，4 个工作组可以共同使用一次 L2 返回，
无需发出 4 个独立请求。方形集群可以同时对两个操作数的流量去重。
多播掩码必须包含请求方，且目标数不得超过 5 个；行掩码或列掩码不正确会直接导致结果错误。
图 22 展示集群共享 A、B panel 的方式。

| 一个 panel 由集群的一行使用 | 在行和列之间多播 panel |
| :---: | :---: |
| ![4 x 4 集群网格中的一行使用同一个 panel](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level9-cluster-source-grid.svg) | ![4 x 4 集群网格中的行列多播](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level9-cluster-broadcast-grid.svg) |

<p align="center">图 22：$4 \times 4$ 集群沿列复用 A panel、沿行复用 B panel，
从而减少重复的 L2 请求。</p>

现在，流水级交接需要同时使用工作组屏障和集群屏障。最后一次 WMMA 仍位于两个拆分屏障窗口之内：
wave 0 发出集群到达信号，随后每个 wave 再进入等待。

**为何有效：** 工作组集群和多播可从 L2 向多个工作组广播共享 panel，从而提高有效 L2 带宽。

下图展示流水线中的集群作用域同步。

![采用工作组与集群拆分屏障交接的 TDM 多播调度](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level9-multicast-diagram.svg)

<p align="center">图 23：Level 9 在最后一个矩阵子步前后加入集群作用域的到达与等待操作，
同时使用 TDM 多播下一组操作数 panel。</p>

#### Level 9 API

| API | 用途 |
| --- | --- |
| [`__cluster_dims__(4, 4, 1)`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/09_gemm_wgc_multicast.cpp#L74-L83) | 在内核上声明一个 $4 \times 4$ 工作组集群。 |
| [`cluster::sync()` / `arrive()` / `wait()`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/cluster/cluster.cuh#L56-L87) | 在集群范围内发布序言阶段的数据，并保护后续流水级交接。 |

#### Level 9 伪代码

```cpp
maskA = cluster::mask(0x1111 << cluster_x);
maskB = cluster::mask(0x000F << (4 * cluster_y));

if (wave_id == 0)
    tdm::load_async(A_LDS[current], A_global, maskA);
if (wave_id == 1)
    tdm::load_async(B_LDS[current], B_global, maskB);
sync::wait_tdm<0>();
cluster::sync();

for each K stage:
    load(A_reg[0], A_LDS[current][0]);
    load(B_reg[0], B_LDS[current][0]);

    if (wave_id == 0)
        tdm::load_async(A_LDS[next], A_global, maskA, count_or_zero);
    if (wave_id == 1)
        tdm::load_async(B_LDS[next], B_global, maskB, count_or_zero);

    for substep = 0 .. 2:
        load(A_reg[next_reg], A_LDS[current][substep + 1]);
        load(B_reg[next_reg], B_LDS[current][substep + 1]);
        sync::wait_ds<DS_SUB>();
        mma_ABt(C, A_reg[current_reg], B_reg[current_reg]);
        swap(current_reg, next_reg);

    sync::wait_ds<0>();
    sync::wait_tdm<0>();
    sync::arrive();              // 发出工作组屏障信号
    if (wave_id == 0)
        cluster::arrive();       // 发出集群屏障信号
    mma_ABt(C, A_reg[current_reg], B_reg[current_reg]);
    sync::wait();
    cluster::wait();
    swap(current, next);
```

图 24 展示最后一组 WMMA 位于两个屏障窗口之内。

![工作组集群多播 GEMM 内核的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level9-multicast-trace.png)

<p align="center">图 24：Level 9 在 SIMD 0 上的 ATT 轨迹。TDM 等待结束后，最后一组 WMMA
在工作组和集群两个屏障窗口内执行。</p>

SIMD 0 的 wave 槽位 0 在大约周期 1,600 到 2,050 之间出现宝蓝色 `TDM_WAIT` 区间。
排空完成后，工作组信号在周期 2,069 发出，集群信号在周期 2,082 发出，最后一次 `mma_ABt`
对应的 16 条 WMMA 指令在周期 2,101 到 2,221 执行。因此，蓝色区间之后的紫色计算位于
两个屏障窗口之内。物理槽位标签不能判断哪个 wave 发出 A 描述符；描述符提交者由源码中的
`wave_id` 而非槽位编号决定。

### Level 10：高效的 GEMM 尾声（[gemm_epilogue.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/10_gemm_epilogue.cpp#L132-L156)）

- **性能：** 相比 Level 9 提升 8%。

Level 10 在将 C tile 写回全局内存之前，先通过 LDS 进行暂存。LDS 会把 wave 局部、
按列主序组织的累加器布局转换成按行主序排列的 tile，从而支持更宽且合并良好的存储操作。

**为何有效：** 在内核末尾通过 LDS 打包 C tile，可以形成更高效的全局内存写入模式。

下图展示经 LDS 暂存的输出尾声。

![GEMM 流水线及其后经 LDS 暂存并合并写入的输出尾声](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level10-epilogue-diagram.svg)

<p align="center">图 25：Level 10 先通过别名复用的 LDS 暂存 C，再将其写入全局内存。</p>

#### Level 10 API

| API | 用途 |
| --- | --- |
| [`sched::lock_simd()`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/sched/sched.cuh#L100-L124) | 让一个 wave 在同一 SIMD 上连续发出 WMMA。 |
| [`store(C_LDS, C_acc)`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/memory/tile/shared_to_register.cuh#L595-L635) | 将分散的累加器值暂存到 LDS。 |
| [`store(C_global, C_LDS)`](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/include/cdna5/ops/warp/memory/tile/global_to_shared.cuh#L218-L274) | 以更宽且连续合并的方式写出组装完成的 C tile。 |

#### Level 10 伪代码

```cpp
sched::lock_simd();

for each K stage:
    // 与 Level 9 相同的 TDM、多播和拆分屏障流水线。

sync::wait_ds<0>();
sync::wait_tdm<0>();
sync::arrive();
sync::wait();

store(C_LDS, C_acc);             // C：寄存器 -> LDS
sync::wait_ds<0>();
sync::arrive();
sync::wait();
store(C_global, C_LDS);          // 合并写入 C：LDS -> 全局内存
```

图 26 在相同时间尺度下对比两种尾声。

| Level 9 直接写回尾声 | Level 10 经 LDS 暂存的尾声 |
| :---: | :---: |
| ![Level 9 直接写回输出尾声的 ATT 轨迹](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level10-epilogue-direct-trace.png) | ![Level 10 经 LDS 暂存输出尾声的 ATT 轨迹](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level10-epilogue-staged-trace.png) |
| 最后的矩阵计算结束后，窄存储仍表现为分散的逐列事务。 | wave 组装数据并以更宽、合并更好的存储流写出时，绿色和橙色活动仍保持交错。 |

<p align="center">图 26：相同时间尺度下的直接写回 GEMM 尾声与 LDS 暂存 GEMM 尾声。</p>

Level 10 的尾声用显式的“寄存器到 LDS 再到全局内存”聚集与流式写出路径，取代每个 wave
直接写回的方式。LDS 在全局写入前重组 wave 局部的累加器分片，从而形成更规整、更宽的存储流。

### Level 11：每个 SIMD 一个 wave（[gemm_one_wave.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/11_gemm_one_wave.cpp#L90-L114)）

- **性能：** 相比 Level 10 提升 6%。

Level 11 保留 $256 \times 256$ 的工作组 tile，但将 $4 \times 4$ wave 网格替换为
$2 \times 2$ 网格。现在，4 个 wave 中的每一个都负责一个 $128 \times 128$ 输出 tile，
即每个 SIMD 上放置一个 wave。该设计以降低占用率为代价，提高每个 wave 内部的操作数复用。

寄存器操作数流水线由两个槽位扩展为三个。第一次 WMMA 之前先预取两个 K=32 子步，
这样即使没有其他驻留 wave 用于隐藏延迟，后续 LDS 加载仍能与矩阵操作交错执行。
对于每个 K block，wave 首先等待当前 TDM 流水级完成，将子步 0 和 1 预取到两个寄存器槽位，
随后一边为子步 0 执行 WMMA，一边把更靠后的子步加载到空闲槽位；接着让三槽环形缓冲轮转经过
全部 4 个子步，在最后一次 WMMA 前后发出屏障信号并等待，最后进入下一个流水级。

**为何有效：** 更大的 wave 局部 tile 提高了寄存器和 LDS 层级的数据复用。
每个子步可以发出 64 条 WMMA 指令，同时三槽流水线维持数据搬运与计算的重叠。

下图展示每个 SIMD 一个 wave 的调度方式。

![每个 SIMD 一个 wave 且每个 K 子步包含 64 条 WMMA 指令的流水线](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level11-one-wave-diagram.svg)

<p align="center">图 27：Level 11 使用三槽寄存器流水线，每个 SIMD 上驻留一个 wave。</p>

#### Level 11 伪代码

```cpp
sched::lock_simd();

if (wave_id == 0)
    tdm::load_async(A_LDS[current], A_global, maskA);
if (wave_id == 1)
    tdm::load_async(B_LDS[current], B_global, maskB);
sync::wait_tdm<0>();
cluster::sync();

for each K stage:
    load(A_reg[0], A_LDS[current][0]);
    load(B_reg[0], B_LDS[current][0]);
    load(A_reg[1], A_LDS[current][1]);
    load(B_reg[1], B_LDS[current][1]);

    if (wave_id == 0)
        tdm::load_async(A_LDS[next], A_global, maskA, count_or_zero);
    if (wave_id == 1)
        tdm::load_async(B_LDS[next], B_global, maskB, count_or_zero);

    for substep = 0 .. 2:
        if substep + 2 < 4:
            load(A_reg[(substep + 2) % 3],
                 A_LDS[current][substep + 2]);
            load(B_reg[(substep + 2) % 3],
                 B_LDS[current][substep + 2]);
        sync::wait_ds<DS_SUB>();
        mma_ABt(C, A_reg[substep % 3], B_reg[substep % 3]);

    sync::wait_ds<0>();
    sync::wait_tdm<0>();
    sync::arrive();
    if (wave_id == 0)
        cluster::arrive();
    mma_ABt(C, A_reg[final], B_reg[final]);
    sync::wait();
    cluster::wait();
    swap(current, next);
```

图 28 中，周期 100 到 350 附近的橙色 LDS 活动为寄存器环形缓冲装入初始数据。
周期 328 到 787、901 到 1,353、1,368 到 1,865 的 3 个长紫色区段，
分别包含内层循环一次 `mma_ABt` 所产生的 64 条已解码 WMMA 指令。
周期 1,869 到 2,100 的宝蓝色区段是 TDM 排空。发出两次屏障信号后，
最后一组包含 64 条指令的 WMMA 在周期 2,150 到 2,596 之间执行，然后才进入等待。

![一个 SIMD 上驻留一个 wave 的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level11-one-wave-trace.png)

<p align="center">图 28：Level 11 在 SIMD 0 上的 ATT 轨迹。每个 SIMD 上的单个 wave
在 TDM 排空前后发出由 64 条指令组成的 WMMA 指令组。</p>

### Level 12：每个 SIMD 两个 wave（[gemm_two_waves.cpp](https://github.com/HazyResearch/HipKittens/blob/1602364f4f40b5caeec0ccbbaf9ca31f784f1599/kernels/cdna5/gemm/bf16fp32/gfx1250/12_gemm_two_waves.cpp#L119-L143)）

- **性能：** 相比 Level 11 提升 6%。

最后一级保留 $256 \times 256$ 工作组 tile，并将 Level 11 的 $2 \times 2$ wave 网格
替换为 $4 \times 2$ 网格。每个 wave 负责一个 $64 \times 128$ 输出 tile，
工作组由 4 个 wave 增加到 8 个 wave，每个 SIMD 上运行两个 wave。

$64 \times 128$ 累加器需要 256 个寄存器，而不是 512 个。由于现在有 256 个线程，
每条 lane 可用的寄存器由 1,024 个降为 512 个，因此操作数环形缓冲从三个槽位缩减为两个。
Level 11 需要第三个槽位来维持加载在途；在 Level 12 中，第二个驻留 wave 可以更有效地隐藏
这部分延迟。

操作数供给使用 `sched_group_barrier`，而不是 `compiler_fence`。该机制要求先执行 6 次 LDS
读取，再执行 8 次矩阵操作，并将这个过程重复 4 次，以覆盖一个子步中的 24 次读取和 32 次矩阵操作。

**为何有效：** 两个同时驻留的 wave 让硬件调度器可以在其中一个 wave 等待数据时，
发出另一个 wave 的工作，从而在保持矩阵单元利用率的同时增强延迟隐藏能力。

下图展示这一调度方式。

![每个 SIMD 两个 wave 且交错执行 LDS 读取和矩阵指令的调度](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/svg/level12-two-waves-diagram.svg)

<p align="center">图 29：Level 12 将最后一个子步拆分到工作组等待与集群等待的两侧。</p>

#### Level 12 辅助函数

| 辅助函数 | 用途 |
| --- | --- |
| `mma_ABt_base(...)` | 计算一个输出分片，使最后一次 MMA 可以拆分为分别包含 12 条和 20 条指令的两组。 |
| `pin_interleave(...)` | 对 `sched_group_barrier` 的内核级封装，用于将 LDS 读取和 WMMA 操作固定为指定的发射顺序。 |

#### Level 12 伪代码

```cpp
sched::lock_simd();

if (wave_id == 0)
    tdm::load_async(A_LDS[current], A_global, maskA);
if (wave_id == 1)
    tdm::load_async(B_LDS[current], B_global, maskB);
sync::wait_tdm<0>();
cluster::sync();

load(A_reg[0], A_LDS[current][0]);
load(B_reg[0], B_LDS[current][0]);

for each K stage:
    if (wave_id == 0)
        tdm::load_async(A_LDS[next], A_global, maskA, count_or_zero);
    if (wave_id == 1)
        tdm::load_async(B_LDS[next], B_global, maskB, count_or_zero);

    for substep = 0 .. 2:
        load(A_reg[(substep + 1) % 2],
             A_LDS[current][substep + 1]);
        load(B_reg[(substep + 1) % 2],
             B_LDS[current][substep + 1]);
        mma_ABt(C, A_reg[substep % 2], B_reg[substep % 2]);
        pin_interleave();

    mma_ABt_base(...) x 12;
    sync::wait_ds<0>();
    sync::wait_tdm<0>();
    sync::arrive();
    if (wave_id == 0)
        cluster::arrive();
    sync::wait();

    load(A_reg[0], A_LDS[next][0]);
    load(B_reg[0], B_LDS[next][0]);
    mma_ABt_base(...) x 20;
    pin_interleave<5, 6>();
    cluster::wait();
    swap(current, next);
```

图 30 显示，WGP 能够清晰地交错执行同一 SIMD 上两个驻留 wave 的指令。轨迹首先交错执行
TDM 描述符设置与发射，随后是两个 wave 交替执行的大段 WMMA 和 LDS 操作。这既保持了
Level 11 的高 WMMA 利用率，也让调度器可以通过切换 wave 获得更多隐藏延迟的机会。

![一个 SIMD 上驻留两个 wave 的 Advanced Thread Trace](https://raw.githubusercontent.com/ROCm/rocm-blogs/release/blogs/software-tools-optimization/hipkittens-gemm-ladder/images/level12-two-waves-trace.png)

<p align="center">图 30：Level 12 在 SIMD 0 上的 ATT 轨迹。两个同时驻留的 wave
交错执行 TDM 设置、LDS 读取和 WMMA 发射。</p>

## 总结

许多曾在 AMD Instinct MI350 和 MI355X GPU 上实现高性能的内核调度模式，都可以直接迁移到
Helios，包括 4 wave 交错，以及 8 wave 或 16 wave 的乒乓调度。尽管本文介绍的架构已经发生变化，
内核开发者仍可保留早期 AMD GPU 世代的核心调度思想，同时利用分区式 LDS、TDM 和工作组多播。

作者计划继续更新 [HipKittens](https://github.com/HazyResearch/HipKittens)，加入更多 Helios
内核、优化方案和技术讨论。测试由作者在早期样片硬件上完成；实际结果可能因配置、使用方式、
软件版本、固件和优化策略而异。

## 测试配置

- GPU：AMD Instinct MI455X GPU
- 工作负载：BF16 GEMM，$M=N=K=8192$
- 测试方法：500 次预热迭代和 100 次计时迭代，并清空 L2 缓存
- 内核实现：HipKittens HIP/C++
- 性能分析：AMD Advanced Thread Trace 与 ROCm Systems Profiler

## 致谢

最后，作者感谢 AMD University Partnerships 团队对本项工作的支持，包括 Hugo Andrade、
Preethi Jayadev 和 Tom Papatheodore，并感谢 AMD 的 Triton 与 HipBLASLt/TensileLite 团队。
作者还感谢 AMD 同事 Lei Zhang、Stanley Winata、Xiaohu Guo、Kumar Deepak、Bryant Nelson、
Alex Brown、Brad Nemanich、Brian Shi、Majed Sujon、Ahmed Eltantawy 和 Kyle Wang
为本项工作提供反馈与支持。

## 免责声明

本文所述信息仅供参考，其中可能包含技术错误、遗漏或排版错误。本文信息可能发生变化，
并可能因多种原因而变得不准确，包括但不限于产品及路线图变更、组件和主板版本变更、
新型号和/或新产品发布、不同制造商之间的产品差异、软件变更、BIOS 刷写、固件升级等。
任何计算机系统都存在无法彻底预防或消除的安全漏洞风险。AMD 不承担更新、更正或修订本文信息
的义务，但保留随时修订本文信息及更改其内容的权利，且无义务将此类修订或更改通知任何人。

本文信息按“原样”提供。AMD 不就本文内容作出任何陈述或保证，也不对其中可能出现的任何不准确、
错误或遗漏承担责任。AMD 明确否认对不侵权、适销性或特定用途适用性的任何默示保证。
在任何情况下，对于任何人因使用本文所含信息而产生的任何依赖损失、直接损失、间接损失、
特殊损失或其他后果性损害，即使 AMD 已被明确告知可能发生此类损害，AMD 也不承担责任。
AMD、AMD 箭头标识及其组合是 Advanced Micro Devices, Inc. 的商标。本文使用的其他产品名称
仅用于识别目的，可能是其各自所属公司的商标。© 2026 Advanced Micro Devices, Inc.
保留所有权利。

第三方内容由拥有该内容的第三方直接向您许可，并非由 AMD 向您许可。所有链接的第三方内容均按
“原样”提供，不附带任何形式的保证。是否使用此类第三方内容完全由您自行决定；在任何情况下，
AMD 均不对第三方内容承担责任。您应自行承担全部风险，并对使用第三方内容可能造成的任何损失
承担全部责任。

> 说明：本中文译本仅为方便阅读而提供。如中文译文与英文原文或其许可、免责声明存在歧义，
> 应以英文原文为准。

## 参考资料

- 原文：[An Educational GEMM Ladder for Helios GPUs](https://rocm.blogs.amd.com/software-tools-optimization/hipkittens-gemm-ladder/README.html)
- 发布日期：2026 年 9 月 14 日
- 作者：Muhammad Osama、Simran Arora、Ryan Swann、William Hu、Sean Siddens、Drew Wadsworth、Julia Zhang、Alex Underwood、Alex Dutu、Dylan Lim
