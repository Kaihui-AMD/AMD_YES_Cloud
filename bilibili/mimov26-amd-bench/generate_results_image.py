#!/usr/bin/env python3
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parent
SUMMARY = ROOT / "results" / "summary.json"
OUTPUT = ROOT / "assets" / "mimov26-9b-r9700-results.png"

FONT_REGULAR = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
FONT_BOLD = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"

BG = "#F4F6F8"
INK = "#171A1F"
MUTED = "#65707C"
LINE = "#D7DDE3"
RED = "#E62B1E"
TEAL = "#078A83"
AMBER = "#C98200"
WHITE = "#FFFFFF"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REGULAR, size)


def text(draw: ImageDraw.ImageDraw, xy, value, size, color=INK, bold=False):
    draw.text(xy, value, font=font(size, bold), fill=color)


def metric(draw, x, y, label, value, unit, accent):
    draw.rounded_rectangle((x, y, x + 510, y + 154), radius=8, fill=WHITE)
    draw.rectangle((x, y, x + 8, y + 154), fill=accent)
    text(draw, (x + 34, y + 25), label, 28, MUTED)
    text(draw, (x + 34, y + 66), value, 54, INK, True)
    text(draw, (x + 350, y + 90), unit, 24, MUTED)


def main() -> None:
    data = json.loads(SUMMARY.read_text())
    bench = data["synthetic_benchmark"]
    text_smoke = data["text_smoke"]
    vision_smoke = data["vision_smoke"]

    image = Image.new("RGB", (1920, 1080), BG)
    draw = ImageDraw.Draw(image)

    text(draw, (92, 68), "MiMo-V2.6 Distill 9B", 58, INK, True)
    text(draw, (92, 142), "Radeon AI PRO R9700 本地实测", 38, MUTED)
    text(
        draw,
        (92, 198),
        "Q8_0 · ROCm 7.2 · llama.cpp b275 · 单卡 33/33 层 GPU offload",
        25,
        MUTED,
    )
    draw.line((92, 246, 1828, 246), fill=LINE, width=2)

    text(draw, (92, 294), "合成吞吐", 34, INK, True)
    metric(
        draw,
        92,
        350,
        "Prompt 512",
        f'{bench["pp512"]["tokens_per_second_mean"]:.2f}',
        "tok/s",
        RED,
    )
    metric(
        draw,
        705,
        350,
        "Prompt 2048",
        f'{bench["pp2048"]["tokens_per_second_mean"]:.2f}',
        "tok/s",
        TEAL,
    )
    metric(
        draw,
        1318,
        350,
        "Generate 128",
        f'{bench["tg128"]["tokens_per_second_mean"]:.2f}',
        "tok/s",
        AMBER,
    )

    text(draw, (92, 552), "真实任务", 34, INK, True)
    draw.rounded_rectangle((92, 610, 930, 852), radius=8, fill=WHITE)
    draw.rectangle((92, 610, 100, 852), fill=RED)
    text(draw, (128, 638), "中文代码问答", 31, INK, True)
    text(
        draw,
        (128, 704),
        f'生成 {text_smoke["generation_tokens_per_second"]:.1f} tok/s',
        45,
        RED,
        True,
    )
    text(draw, (128, 772), "显存 8.61GiB · GPU 100% · 192W", 27, MUTED)
    text(draw, (128, 812), "质量观察：生成的 LRU 边界测试失败", 24, MUTED)

    draw.rounded_rectangle((990, 610, 1828, 852), radius=8, fill=WHITE)
    draw.rectangle((990, 610, 998, 852), fill=TEAL)
    text(draw, (1026, 638), "图表理解", 31, INK, True)
    text(
        draw,
        (1026, 704),
        f'生成 {vision_smoke["generation_tokens_per_second"]:.1f} tok/s',
        45,
        TEAL,
        True,
    )
    text(draw, (1026, 772), "六个数值全部识别正确", 27, MUTED)
    text(draw, (1026, 812), "MTP 提升率 72.8% / 62.4% 均正确", 24, MUTED)

    draw.line((92, 918, 1828, 918), fill=LINE, width=2)
    text(
        draw,
        (92, 948),
        "测试日期 2026-09-22 · pp/tg 为 llama-bench 吞吐，不含分词与采样耗时",
        24,
        MUTED,
    )
    text(
        draw,
        (92, 992),
        "复现：./run_9b_bench.sh",
        24,
        INK,
        True,
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image.save(OUTPUT, quality=95)
    print(OUTPUT)


if __name__ == "__main__":
    main()
