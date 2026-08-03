#!/usr/bin/env python3
"""Generate 4K video infographics for the AMD/NVIDIA GPU mapping guide."""

from __future__ import annotations

import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont


LOGICAL_WIDTH = 1920
LOGICAL_HEIGHT = 1080
OUTPUT_WIDTH = 3840
OUTPUT_HEIGHT = 2160

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "output" / "gpu_mapping_visuals"

FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_MONO = "/usr/share/fonts/truetype/ubuntu/UbuntuSansMono[wght].ttf"

AMD_RED = (239, 35, 52)
AMD_ORANGE = (255, 112, 34)
NVIDIA_GREEN = (118, 185, 0)
CYAN = (52, 232, 255)
BLUE = (42, 148, 255)
MAGENTA = (218, 73, 255)
YELLOW = (255, 202, 72)
WHITE = (235, 244, 255)
MUTED = (151, 171, 191)
GRID = (41, 71, 91)
PANEL = (12, 20, 30)
BLACK = (2, 5, 9)


def load_font(path: str, size: int, index: int = 2) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(path, size=size, index=index)
    except (OSError, ValueError):
        return ImageFont.truetype(FONT_REGULAR, size=size, index=2)


def f_bold(size: int) -> ImageFont.FreeTypeFont:
    return load_font(FONT_BOLD, size)


def f_regular(size: int) -> ImageFont.FreeTypeFont:
    return load_font(FONT_REGULAR, size)


def f_mono(size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(FONT_MONO, size=size)
    except OSError:
        return f_regular(size)


def rgba(color: tuple[int, int, int], alpha: int = 255) -> tuple[int, int, int, int]:
    return color[0], color[1], color[2], alpha


def lerp_color(
    left: tuple[int, int, int],
    right: tuple[int, int, int],
    amount: float,
) -> tuple[int, int, int]:
    return tuple(int(a + (b - a) * amount) for a, b in zip(left, right))


def background(
    seed: int,
    left_accent: tuple[int, int, int] = AMD_RED,
    right_accent: tuple[int, int, int] = CYAN,
) -> Image.Image:
    height, width = LOGICAL_HEIGHT, LOGICAL_WIDTH
    yy, xx = np.mgrid[0:height, 0:width]
    vertical = yy / max(1, height - 1)
    base = np.zeros((height, width, 3), dtype=np.float32)
    top = np.array((5, 9, 16), dtype=np.float32)
    bottom = np.array((2, 5, 9), dtype=np.float32)
    base[:] = top
    base += (bottom - top) * vertical[:, :, None]

    for color, cx, cy, radius, strength in (
        (left_accent, width * 0.16, height * 0.30, width * 0.44, 0.20),
        (right_accent, width * 0.84, height * 0.44, width * 0.48, 0.16),
    ):
        distance = ((xx - cx) ** 2 + ((yy - cy) * 1.25) ** 2) / (radius**2)
        halo = np.exp(-distance * 4.2) * strength
        base += halo[:, :, None] * np.array(color, dtype=np.float32)

    vignette = 1.0 - 0.50 * (
        ((xx - width / 2) / (width / 1.20)) ** 2
        + ((yy - height / 2) / (height / 1.05)) ** 2
    )
    base *= np.clip(vignette[:, :, None], 0.34, 1.0)
    image = Image.fromarray(np.uint8(np.clip(base, 0, 255)), "RGB").convert("RGBA")

    draw = ImageDraw.Draw(image, "RGBA")
    rng = random.Random(seed)
    for _ in range(155):
        x = rng.randrange(width)
        y = rng.randrange(height)
        radius = rng.choice((1, 1, 1, 2))
        alpha = rng.randrange(38, 128)
        color = lerp_color(MUTED, right_accent, rng.random() * 0.4)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=rgba(color, alpha))

    horizon = 790
    for x in range(-400, width + 401, 120):
        draw.line((width / 2, horizon, x, height), fill=rgba(GRID, 62), width=1)
    for index in range(16):
        z = index / 15
        y = horizon + z**2.2 * (height - horizon)
        draw.line((0, y, width, y), fill=rgba(GRID, int(25 + 52 * z)), width=1)
    for y in range(0, height, 4):
        draw.line((0, y, width, y), fill=(0, 0, 0, 8), width=1)
    return image


def neon_line(
    image: Image.Image,
    points: list[tuple[float, float]],
    color: tuple[int, int, int],
    width: int = 3,
    alpha: int = 220,
) -> None:
    layer = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(layer)
    draw.line(points, fill=rgba(color, alpha), width=width, joint="curve")
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(max(4, width * 3))))
    image.alpha_composite(layer)


def neon_rect(
    image: Image.Image,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    fill: tuple[int, int, int] = PANEL,
    fill_alpha: int = 205,
    width: int = 2,
    radius: int = 8,
) -> None:
    layer = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(layer)
    draw.rounded_rectangle(
        box,
        radius=radius,
        fill=rgba(fill, fill_alpha),
        outline=rgba(color, 205),
        width=width,
    )
    glow = Image.new("RGBA", image.size)
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.rounded_rectangle(box, radius=radius, outline=rgba(color, 95), width=width + 2)
    image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(12)))
    image.alpha_composite(layer)


def neon_circle(
    image: Image.Image,
    center: tuple[int, int],
    radius: int,
    color: tuple[int, int, int],
    fill_alpha: int = 40,
    width: int = 3,
) -> None:
    x, y = center
    box = (x - radius, y - radius, x + radius, y + radius)
    layer = Image.new("RGBA", image.size)
    draw = ImageDraw.Draw(layer)
    draw.ellipse(box, fill=rgba(color, fill_alpha), outline=rgba(color, 220), width=width)
    image.alpha_composite(layer.filter(ImageFilter.GaussianBlur(15)))
    image.alpha_composite(layer)


def text(
    image: Image.Image,
    xy: tuple[int, int],
    value: str,
    font: ImageFont.FreeTypeFont,
    color: tuple[int, int, int] = WHITE,
    anchor: str = "la",
    align: str = "left",
    shadow: bool = True,
    spacing: int = 6,
) -> None:
    draw = ImageDraw.Draw(image)
    if shadow:
        draw.multiline_text(
            (xy[0] + 3, xy[1] + 4),
            value,
            font=font,
            fill=(0, 0, 0, 190),
            anchor=anchor,
            align=align,
            spacing=spacing,
        )
    draw.multiline_text(
        xy,
        value,
        font=font,
        fill=rgba(color),
        anchor=anchor,
        align=align,
        spacing=spacing,
    )


def centered_title(image: Image.Image, title: str, subtitle: str, accent: tuple[int, int, int]) -> None:
    text(image, (960, 78), title, f_bold(62), WHITE, anchor="ma", align="center")
    text(image, (960, 157), subtitle, f_regular(26), MUTED, anchor="ma", align="center")
    neon_line(image, [(650, 205), (1270, 205)], accent, width=2, alpha=170)


def chip_icon(
    image: Image.Image,
    center: tuple[int, int],
    size: int,
    color: tuple[int, int, int],
    label: str = "",
) -> None:
    x, y = center
    half = size // 2
    neon_rect(image, (x - half, y - half, x + half, y + half), color, fill=(8, 15, 22), width=2)
    draw = ImageDraw.Draw(image, "RGBA")
    inner = int(size * 0.27)
    draw.rectangle(
        (x - inner, y - inner, x + inner, y + inner),
        fill=rgba(color, 38),
        outline=rgba(color, 210),
        width=2,
    )
    for offset in range(-half + 15, half - 5, max(18, size // 7)):
        draw.line((x - half - 12, y + offset, x - half, y + offset), fill=rgba(color, 190), width=3)
        draw.line((x + half, y + offset, x + half + 12, y + offset), fill=rgba(color, 190), width=3)
        draw.line((x + offset, y - half - 12, x + offset, y - half), fill=rgba(color, 190), width=3)
        draw.line((x + offset, y + half, x + offset, y + half + 12), fill=rgba(color, 190), width=3)
    if label:
        text(image, center, label, f_bold(max(17, size // 8)), color, anchor="mm", align="center")


def gpu_card(
    image: Image.Image,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    fans: int = 2,
) -> None:
    x0, y0, x1, y1 = box
    neon_rect(image, box, color, fill=(9, 15, 22), fill_alpha=235, width=2, radius=7)
    draw = ImageDraw.Draw(image, "RGBA")
    draw.polygon(
        [(x0 + 22, y1), (x1 - 28, y1), (x1 - 10, y1 + 13), (x0 + 40, y1 + 13)],
        fill=rgba(YELLOW, 165),
    )
    fan_radius = min((y1 - y0) * 0.31, (x1 - x0) / (fans * 3.0))
    gap = (x1 - x0) / (fans + 1)
    for index in range(fans):
        cx = x0 + gap * (index + 1)
        cy = (y0 + y1) / 2
        draw.ellipse(
            (cx - fan_radius, cy - fan_radius, cx + fan_radius, cy + fan_radius),
            outline=rgba(color, 215),
            width=3,
            fill=(2, 7, 10, 230),
        )
        for blade in range(8):
            angle = blade * math.tau / 8
            draw.line(
                (
                    cx + math.cos(angle) * fan_radius * 0.20,
                    cy + math.sin(angle) * fan_radius * 0.20,
                    cx + math.cos(angle + 0.38) * fan_radius * 0.82,
                    cy + math.sin(angle + 0.38) * fan_radius * 0.82,
                ),
                fill=rgba(color, 145),
                width=3,
            )


def server_node(
    image: Image.Image,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    chips: int = 8,
) -> None:
    neon_rect(image, box, color, fill=(8, 14, 22), fill_alpha=235, width=2, radius=5)
    x0, y0, x1, y1 = box
    draw = ImageDraw.Draw(image, "RGBA")
    cell_gap = 12
    cell_width = (x1 - x0 - 50 - cell_gap * (chips - 1)) / chips
    for index in range(chips):
        cx0 = x0 + 25 + index * (cell_width + cell_gap)
        draw.rounded_rectangle(
            (cx0, y0 + 28, cx0 + cell_width, y1 - 28),
            radius=4,
            fill=rgba(color, 34),
            outline=rgba(color, 170),
            width=2,
        )
    for index in range(5):
        draw.ellipse((x1 - 29 - index * 12, y0 + 9, x1 - 23 - index * 12, y0 + 15), fill=rgba(color, 190))


def rack(
    image: Image.Image,
    box: tuple[int, int, int, int],
    color: tuple[int, int, int],
    rows: int = 10,
) -> None:
    x0, y0, x1, y1 = box
    neon_rect(image, box, color, fill=(6, 11, 17), fill_alpha=235, width=2, radius=4)
    draw = ImageDraw.Draw(image, "RGBA")
    top = y0 + 22
    available = y1 - y0 - 44
    row_height = available / rows
    for index in range(rows):
        ry0 = top + index * row_height
        draw.rectangle(
            (x0 + 18, ry0 + 3, x1 - 18, ry0 + row_height - 4),
            fill=rgba(color, 25 + index * 2),
            outline=rgba(color, 130),
            width=1,
        )
        draw.ellipse((x1 - 35, ry0 + 10, x1 - 29, ry0 + 16), fill=rgba(CYAN, 190))


def arrow(
    image: Image.Image,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int],
    width: int = 3,
) -> None:
    neon_line(image, [start, end], color, width=width)
    angle = math.atan2(end[1] - start[1], end[0] - start[0])
    size = 14
    points = [
        end,
        (
            end[0] - math.cos(angle - 0.52) * size,
            end[1] - math.sin(angle - 0.52) * size,
        ),
        (
            end[0] - math.cos(angle + 0.52) * size,
            end[1] - math.sin(angle + 0.52) * size,
        ),
    ]
    ImageDraw.Draw(image, "RGBA").polygon(points, fill=rgba(color, 235))


def label_pill(
    image: Image.Image,
    center: tuple[int, int],
    label: str,
    color: tuple[int, int, int],
    width: int,
    font_size: int = 24,
) -> None:
    x, y = center
    height = 52
    neon_rect(image, (x - width // 2, y - height // 2, x + width // 2, y + height // 2), color, fill_alpha=222)
    text(image, center, label, f_bold(font_size), color, anchor="mm", align="center")


def save_4k(image: Image.Image, filename: str) -> Path:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    image = image.convert("RGB").resize((OUTPUT_WIDTH, OUTPUT_HEIGHT), Image.Resampling.LANCZOS)
    path = OUTPUT_DIR / filename
    image.save(path, quality=96, optimize=True)
    return path


def frame_product_map() -> Image.Image:
    image = background(101, AMD_RED, NVIDIA_GREEN)
    centered_title(
        image,
        "AMD GPU 与 NVIDIA GPU 产品地图",
        "按市场定位理解对应关系 · 对应不等于性能完全相同",
        AMD_ORANGE,
    )
    text(image, (430, 245), "AMD", f_bold(42), AMD_RED, anchor="mm")
    text(image, (1490, 245), "NVIDIA", f_bold(42), NVIDIA_GREEN, anchor="mm")
    rows = [
        ("消费级", "Radeon RX 9000", "GeForce RTX 50", "游戏 · 创作 · 本地 AI", 365),
        ("专业级", "Radeon PRO / AI PRO", "RTX PRO Blackwell", "工作站 · 专业应用 · 本地模型", 590),
        ("数据中心", "Instinct MI300–MI455", "Hopper · Blackwell · Rubin", "训练 · 推理 · HPC · 机架级 AI", 815),
    ]
    for index, (category, amd, nvidia, usage, y) in enumerate(rows):
        left_color = lerp_color(AMD_RED, AMD_ORANGE, index * 0.28)
        right_color = lerp_color(NVIDIA_GREEN, CYAN, index * 0.25)
        neon_rect(image, (120, y - 72, 770, y + 72), left_color, fill_alpha=210)
        neon_rect(image, (1150, y - 72, 1800, y + 72), right_color, fill_alpha=210)
        neon_circle(image, (960, y), 82, lerp_color(left_color, right_color, 0.5), fill_alpha=24)
        text(image, (160, y - 20), amd, f_bold(34), left_color, anchor="lm")
        text(image, (160, y + 31), usage, f_regular(21), MUTED, anchor="lm")
        text(image, (1760, y - 20), nvidia, f_bold(34), right_color, anchor="rm")
        text(image, (1760, y + 31), usage, f_regular(21), MUTED, anchor="rm")
        text(image, (960, y - 8), category, f_bold(28), WHITE, anchor="mm")
        text(image, (960, y + 31), "近似对位", f_regular(18), MUTED, anchor="mm")
        neon_line(image, [(770, y), (878, y)], left_color, width=2)
        neon_line(image, [(1042, y), (1150, y)], right_color, width=2)
    text(
        image,
        (960, 1015),
        "对比时关注工作负载、显存、软件兼容性和实测性能",
        f_regular(23),
        WHITE,
        anchor="mm",
    )
    return image


def frame_hardware_mapping() -> Image.Image:
    image = background(202, AMD_ORANGE, CYAN)
    centered_title(
        image,
        "硬件单元如何对应",
        "名称和作用相近，但不能直接比较核心数量",
        CYAN,
    )
    chip_icon(image, (960, 570), 260, MAGENTA, "GPU")
    rows = [
        ("Stream Processor", "CUDA Core", "通用计算 / 着色", 315, AMD_RED, NVIDIA_GREEN),
        ("Compute Unit · CU", "SM", "计算资源组织单元", 475, AMD_ORANGE, CYAN),
        ("AI Accelerator", "Tensor Core", "矩阵与低精度 AI", 665, MAGENTA, BLUE),
        ("Ray Accelerator", "RT Core", "光线与几何相交", 825, YELLOW, NVIDIA_GREEN),
    ]
    for left, right, purpose, y, left_color, right_color in rows:
        neon_rect(image, (90, y - 60, 690, y + 60), left_color, fill_alpha=218)
        neon_rect(image, (1230, y - 60, 1830, y + 60), right_color, fill_alpha=218)
        text(image, (390, y - 14), left, f_bold(31), left_color, anchor="mm", align="center")
        text(image, (390, y + 29), "AMD", f_mono(17), MUTED, anchor="mm")
        text(image, (1530, y - 14), right, f_bold(31), right_color, anchor="mm", align="center")
        text(image, (1530, y + 29), "NVIDIA", f_mono(17), MUTED, anchor="mm")
        text(image, (960, y), purpose, f_regular(21), WHITE, anchor="mm", align="center")
        neon_line(image, [(690, y), (810, y)], left_color, width=2)
        neon_line(image, [(1110, y), (1230, y)], right_color, width=2)
    label_pill(image, (960, 1010), "概念对应 ≠ 数量等价", AMD_RED, 470, 27)
    return image


def frame_gaming_features() -> Image.Image:
    image = background(303, AMD_RED, NVIDIA_GREEN)
    centered_title(
        image,
        "游戏与图形功能对应",
        "五组常见功能，一眼看懂两套命名",
        NVIDIA_GREEN,
    )
    gpu_card(image, (120, 280, 560, 500), AMD_RED, fans=2)
    gpu_card(image, (1360, 280, 1800, 500), NVIDIA_GREEN, fans=2)
    text(image, (340, 535), "AMD Radeon", f_bold(27), AMD_RED, anchor="mm")
    text(image, (1580, 535), "NVIDIA GeForce", f_bold(27), NVIDIA_GREEN, anchor="mm")
    pairs = [
        ("FSR", "DLSS", "超分辨率 / 帧生成"),
        ("Anti-Lag", "Reflex", "降低系统延迟"),
        ("AFMF", "Smooth Motion", "驱动级帧生成"),
        ("FreeSync", "G-SYNC", "可变刷新率"),
        ("Adrenalin", "NVIDIA App", "驱动与游戏管理"),
    ]
    start_y = 615
    for index, (left, right, purpose) in enumerate(pairs):
        y = start_y + index * 80
        label_pill(image, (420, y), left, AMD_ORANGE, 340, 25)
        label_pill(image, (1500, y), right, NVIDIA_GREEN, 340, 25)
        text(image, (960, y), purpose, f_regular(22), WHITE, anchor="mm")
        neon_line(image, [(590, y), (805, y)], AMD_ORANGE, width=2)
        neon_line(image, [(1115, y), (1330, y)], NVIDIA_GREEN, width=2)
        neon_circle(image, (960, y), 8, CYAN, fill_alpha=160, width=2)
    return image


def frame_workload_decision() -> Image.Image:
    image = background(404, AMD_RED, CYAN)
    centered_title(
        image,
        "先判断：训练还是推理",
        "两类工作负载关注的硬件指标完全不同",
        MAGENTA,
    )
    neon_circle(image, (960, 350), 112, MAGENTA, fill_alpha=38)
    text(image, (960, 330), "AI 工作负载", f_bold(34), WHITE, anchor="mm")
    text(image, (960, 377), "模型 · 数据 · 并发 · 上下文", f_regular(18), MUTED, anchor="mm")
    arrow(image, (870, 420), (610, 515), AMD_ORANGE, 4)
    arrow(image, (1050, 420), (1310, 515), CYAN, 4)
    text(image, (485, 500), "训练 / 微调", f_bold(42), AMD_ORANGE, anchor="mm")
    text(image, (1435, 500), "推理 / 服务", f_bold(42), CYAN, anchor="mm")

    training = [
        ("LoRA / QLoRA", "显存 · 激活 · 框架兼容", 625),
        ("全参数训练", "HBM · GPU 互连 · RCCL", 755),
        ("多节点预训练", "网络 · 扩展效率 · 容错", 885),
    ]
    inference = [
        ("本地交互", "模型能否放入内存", 625),
        ("在线高并发", "TTFT · TPOT · KV Cache", 755),
        ("批量推理", "吞吐 · 带宽 · 能效", 885),
    ]
    for title_value, detail, y in training:
        neon_rect(image, (120, y - 48, 780, y + 48), AMD_ORANGE, fill_alpha=205)
        text(image, (165, y - 7), title_value, f_bold(27), AMD_ORANGE, anchor="lm")
        text(image, (735, y + 4), detail, f_regular(20), MUTED, anchor="rm")
    for title_value, detail, y in inference:
        neon_rect(image, (1140, y - 48, 1800, y + 48), CYAN, fill_alpha=205)
        text(image, (1185, y - 7), title_value, f_bold(27), CYAN, anchor="lm")
        text(image, (1755, y + 4), detail, f_regular(20), MUTED, anchor="rm")
    label_pill(image, (485, 1010), "Radeon AI PRO → Instinct 集群", AMD_RED, 650, 23)
    label_pill(image, (1435, 1010), "本地 Radeon → Instinct 服务", BLUE, 650, 23)
    return image


def frame_memory_ladder() -> Image.Image:
    image = background(505, AMD_ORANGE, CYAN)
    centered_title(
        image,
        "先算显存，再谈性能",
        "权重只是起点：还要预留激活、KV Cache、临时张量与通信缓冲区",
        YELLOW,
    )
    formulas = [
        ("BF16 / FP16", "参数量 × 2 bytes", AMD_RED),
        ("FP8 / INT8", "参数量 × 1 byte", AMD_ORANGE),
        ("INT4 / FP4", "参数量 × 0.5 byte", CYAN),
    ]
    for index, (precision, formula, color) in enumerate(formulas):
        x = 310 + index * 480
        neon_rect(image, (x - 190, 250, x + 190, 335), color, fill_alpha=210)
        text(image, (x, 276), precision, f_bold(24), color, anchor="mm")
        text(image, (x, 310), formula, f_regular(19), WHITE, anchor="mm")

    headers = [("模型", 160), ("BF16", 430), ("FP8", 665), ("4-bit", 900)]
    for value, x in headers:
        text(image, (x, 400), value, f_bold(23), MUTED, anchor="mm")
    rows = [
        ("8B", "16–24GB", "10–16GB", "6–10GB"),
        ("14B", "30–40GB", "18–24GB", "10–16GB"),
        ("32B", "70–90GB", "40–55GB", "20–30GB"),
        ("70B", "155–190GB", "85–110GB", "45–65GB"),
        ("405B", "900GB+", "450GB+", "230–320GB"),
    ]
    for index, row in enumerate(rows):
        y = 475 + index * 105
        neon_rect(image, (65, y - 39, 1040, y + 39), GRID, fill=(8, 14, 21), fill_alpha=220, width=1)
        text(image, (160, y), row[0], f_bold(27), WHITE, anchor="mm")
        text(image, (430, y), row[1], f_mono(23), AMD_RED, anchor="mm")
        text(image, (665, y), row[2], f_mono(23), AMD_ORANGE, anchor="mm")
        text(image, (900, y), row[3], f_mono(23), CYAN, anchor="mm")

    text(image, (1450, 395), "AMD GPU 显存容量", f_bold(28), WHITE, anchor="mm")
    capacities = [
        ("RX 9070 XT", 16, AMD_RED),
        ("R9700", 32, AMD_ORANGE),
        ("MI210", 64, YELLOW),
        ("MI300X", 192, BLUE),
        ("MI325X", 256, CYAN),
        ("MI355X", 288, MAGENTA),
        ("MI455X", 432, NVIDIA_GREEN),
    ]
    base_y = 965
    chart_top = 440
    max_height = base_y - chart_top
    bar_width = 72
    gap = 30
    start_x = 1110
    draw = ImageDraw.Draw(image, "RGBA")
    for index, (name, capacity, color) in enumerate(capacities):
        x0 = start_x + index * (bar_width + gap)
        height = max(24, int(capacity / 432 * max_height))
        draw.rounded_rectangle(
            (x0, base_y - height, x0 + bar_width, base_y),
            radius=5,
            fill=rgba(color, 112),
            outline=rgba(color, 225),
            width=2,
        )
        text(image, (x0 + bar_width / 2, base_y - height - 30), f"{capacity}GB", f_mono(18), color, anchor="mm")
        text(image, (x0 + bar_width / 2, 1002), name, f_regular(16), WHITE, anchor="mm", align="center")
    draw.line((1080, base_y, 1840, base_y), fill=rgba(MUTED, 130), width=2)
    return image


def frame_training_stack() -> Image.Image:
    image = background(606, AMD_RED, MAGENTA)
    centered_title(
        image,
        "训练软件栈：从单卡开发到多节点集群",
        "硬件、ROCm、框架、通信和运维必须作为同一个系统验证",
        AMD_RED,
    )
    layers = [
        ("训练框架", "Primus · TorchTitan · Megatron-LM · FSDP", MAGENTA, 285),
        ("计算与算子", "PyTorch · AITER · hipBLASLt · Composable Kernel", AMD_ORANGE, 410),
        ("分布式通信", "RCCL · DeepEP · RDMA", CYAN, 535),
        ("平台与工具", "ROCm · Profiler · AMD SMI · RDC", BLUE, 660),
    ]
    for title_value, detail, color, y in layers:
        neon_rect(image, (310, y - 48, 1610, y + 48), color, fill_alpha=218)
        text(image, (365, y), title_value, f_bold(28), color, anchor="lm")
        text(image, (1555, y), detail, f_regular(24), WHITE, anchor="rm")
    for y in (348, 473, 598):
        arrow(image, (960, y + 15), (960, y + 47), WHITE, 2)

    gpu_card(image, (105, 810, 500, 958), AMD_RED, fans=2)
    server_node(image, (675, 800, 1245, 950), CYAN, chips=8)
    rack(image, (1510, 760, 1785, 970), MAGENTA, rows=8)
    text(image, (302, 995), "单卡开发 / LoRA", f_bold(24), AMD_RED, anchor="mm")
    text(image, (960, 995), "8× Instinct 单节点训练", f_bold(24), CYAN, anchor="mm")
    text(image, (1647, 995), "多节点预训练", f_bold(24), MAGENTA, anchor="mm")
    arrow(image, (520, 880), (640, 880), AMD_ORANGE, 4)
    arrow(image, (1270, 880), (1470, 880), MAGENTA, 4)
    return image


def frame_inference_stack() -> Image.Image:
    image = background(707, AMD_ORANGE, CYAN)
    centered_title(
        image,
        "推理软件栈：本地体验与企业服务是两条路线",
        "同一个模型，在低并发桌面与高并发数据中心需要不同工具链",
        CYAN,
    )
    neon_line(image, [(960, 250), (960, 1000)], MUTED, width=2, alpha=80)
    text(image, (480, 270), "本地低并发", f_bold(40), AMD_ORANGE, anchor="mm")
    text(image, (1440, 270), "企业级在线服务", f_bold(40), CYAN, anchor="mm")

    gpu_card(image, (250, 345, 710, 555), AMD_RED, fans=2)
    text(image, (480, 590), "Ryzen AI Max / Radeon / R9700", f_bold(25), WHITE, anchor="mm")
    local_stack = [
        ("模型格式", "GGUF / 量化模型"),
        ("运行工具", "llama.cpp · Ollama · LM Studio"),
        ("关注指标", "能否放下 · 首 token · 单用户速度"),
    ]
    for index, (label, value) in enumerate(local_stack):
        y = 685 + index * 105
        neon_rect(image, (160, y - 40, 800, y + 40), AMD_ORANGE, fill_alpha=205)
        text(image, (205, y), label, f_bold(22), AMD_ORANGE, anchor="lm")
        text(image, (755, y), value, f_regular(21), WHITE, anchor="rm")

    server_node(image, (1110, 345, 1770, 555), CYAN, chips=8)
    text(image, (1440, 590), "MI300X / MI325X / MI355X", f_bold(25), WHITE, anchor="mm")
    enterprise_stack = [
        ("服务框架", "vLLM · SGLang"),
        ("性能组件", "AITER · Quark · RCCL"),
        ("关注指标", "TTFT · TPOT · tokens/s · KV Cache"),
    ]
    for index, (label, value) in enumerate(enterprise_stack):
        y = 685 + index * 105
        neon_rect(image, (1120, y - 40, 1760, y + 40), CYAN, fill_alpha=205)
        text(image, (1165, y), label, f_bold(22), CYAN, anchor="lm")
        text(image, (1715, y), value, f_regular(21), WHITE, anchor="rm")
    return image


def frame_scale_out() -> Image.Image:
    image = background(808, AMD_RED, CYAN)
    centered_title(
        image,
        "从验证到生产：四级硬件规模",
        "先建立单卡基线，再扩展到节点和机架",
        AMD_ORANGE,
    )
    stages = [
        ("01", "工作站", "Radeon AI PRO", "模型验证 · LoRA · 本地推理", AMD_RED, 230),
        ("02", "单张加速器", "MI300X / MI325X / MI355X", "70B 推理 · 单卡基线", AMD_ORANGE, 650),
        ("03", "8-GPU 节点", "Instinct Platform", "全参数微调 · 单节点训练", CYAN, 1070),
        ("04", "机架级系统", "Helios · 72× MI455X", "Frontier 训练与大规模推理", MAGENTA, 1490),
    ]
    for index, (number, title_value, product, usage, color, x) in enumerate(stages):
        if index == 0:
            gpu_card(image, (x - 150, 355, x + 150, 515), color, fans=2)
        elif index == 1:
            chip_icon(image, (x, 435), 180, color, "MI")
        elif index == 2:
            server_node(image, (x - 220, 355, x + 220, 515), color, chips=8)
        else:
            rack(image, (x - 125, 310, x + 125, 545), color, rows=10)
        neon_circle(image, (x, 670), 42, color, fill_alpha=60)
        text(image, (x, 670), number, f_mono(22), color, anchor="mm")
        text(image, (x, 750), title_value, f_bold(32), color, anchor="mm")
        text(image, (x, 805), product, f_bold(24), WHITE, anchor="mm", align="center")
        text(image, (x, 875), usage, f_regular(20), MUTED, anchor="mm", align="center")
        if index < len(stages) - 1:
            next_x = stages[index + 1][5]
            arrow(image, (x + 155, 670), (next_x - 155, 670), lerp_color(color, stages[index + 1][4], 0.5), 4)
    label_pill(image, (960, 1000), "正确性 → 单卡性能 → 多卡通信 → 集群扩展 → 可靠性", WHITE, 1180, 24)
    return image


def frame_rocm_versions() -> Image.Image:
    image = background(909, AMD_RED, CYAN)
    centered_title(
        image,
        "ROCm 版本不能一刀切",
        "按 GPU 产品线选择官方兼容矩阵和已验证容器",
        YELLOW,
    )
    lanes = [
        (
            "Instinct 数据中心",
            "MI200 · MI300 · MI350",
            "ROCm 7.14 BKC",
            "官方容器 · PyTorch · Primus · vLLM/SGLang",
            AMD_ORANGE,
            355,
        ),
        (
            "Radeon / Ryzen 本地 AI",
            "RX 9000 · R9700 · Ryzen AI",
            "Radeon/Ryzen ROCm 7.2.1",
            "专用支持矩阵 · 对应 PyTorch 环境",
            CYAN,
            600,
        ),
        (
            "MI455X / Helios",
            "CDNA 5 · HBM4 · 72-GPU Rack",
            "OEM / 云平台专用 BKC",
            "使用 AMD 或整机厂已验证镜像",
            MAGENTA,
            845,
        ),
    ]
    for title_value, products, version, detail, color, y in lanes:
        neon_rect(image, (125, y - 85, 1795, y + 85), color, fill_alpha=215)
        chip_icon(image, (245, y), 105, color)
        text(image, (340, y - 31), title_value, f_bold(30), color, anchor="lm")
        text(image, (340, y + 25), products, f_regular(21), MUTED, anchor="lm")
        text(image, (1120, y - 25), version, f_bold(29), WHITE, anchor="mm")
        text(image, (1120, y + 25), detail, f_regular(20), MUTED, anchor="mm")
        label_pill(image, (1650, y), "独立验证", color, 205, 21)
    label_pill(image, (960, 1010), "驱动 + ROCm + 框架 + 容器必须成套验证", YELLOW, 760, 25)
    return image


def make_contact_sheet(paths: list[Path]) -> Path:
    thumbs: list[Image.Image] = []
    for path in paths:
        image = Image.open(path).convert("RGB")
        image.thumbnail((620, 335), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (640, 360), rgba(BLACK))
        canvas.paste(image, ((640 - image.width) // 2, 5))
        text(
            canvas,
            (20, 342),
            path.stem,
            f_mono(16),
            MUTED,
            anchor="ls",
            shadow=False,
        )
        thumbs.append(canvas.convert("RGB"))

    sheet = Image.new("RGB", (1920, 1080), BLACK)
    for index, thumb in enumerate(thumbs):
        x = (index % 3) * 640
        y = (index // 3) * 360
        sheet.paste(thumb, (x, y))
    path = OUTPUT_DIR / "gpu_mapping_visuals_contact_sheet.jpg"
    sheet.save(path, quality=92, optimize=True)
    return path


def main() -> None:
    frames = [
        ("01_product_landscape.png", frame_product_map),
        ("02_hardware_mapping.png", frame_hardware_mapping),
        ("03_gaming_features.png", frame_gaming_features),
        ("04_training_vs_inference.png", frame_workload_decision),
        ("05_memory_ladder.png", frame_memory_ladder),
        ("06_training_stack.png", frame_training_stack),
        ("07_inference_stack.png", frame_inference_stack),
        ("08_deployment_scale.png", frame_scale_out),
        ("09_rocm_version_lanes.png", frame_rocm_versions),
    ]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    paths = []
    for filename, renderer in frames:
        path = save_4k(renderer(), filename)
        paths.append(path)
        print(path)
    print(make_contact_sheet(paths))


if __name__ == "__main__":
    main()
