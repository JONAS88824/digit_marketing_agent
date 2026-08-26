"""图片侧的纯计算层：用 Pillow 算出客观的画面指标。

【这一层和模型的分工】
"这张图好不好看"是审美判断，只有模型（或人）能答。
但"主体够不够突出""对比度够不够""文字放哪儿不挡主体"这些是可以量化的：
把图切成 3×3 九宫格，算每格的边缘能量，就能知道视觉重心在哪、哪块区域最空。

所以本文件只输出**客观数字**，不下"好看/不好看"的结论。
结论由 creative_agent 结合这些数字 + 它自己看到的画面来下。

不依赖 numpy，只用 Pillow，所以装起来轻、测起来快。
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageStat

# 九宫格的行列数。3×3 对应摄影里的三分法，足够定位视觉重心
GRID = 3

# 主体突出度的判定阈值：最强格子的能量占比超过这个值，才算"主体明确"
SUBJECT_PROMINENCE_THRESHOLD = 0.18

# 对比度（灰度标准差）的经验区间。低于下限画面发灰，高于上限容易刺眼
LOW_CONTRAST_STDDEV = 38.0
HIGH_CONTRAST_STDDEV = 92.0

# WCAG 正文文字的最低对比度要求。广告图上叠字建议不低于这个值
MIN_TEXT_CONTRAST_RATIO = 4.5

# 支持读取的图片格式
SUPPORTED_FORMATS = ("PNG", "JPEG", "WEBP")


@dataclass(frozen=True)
class GridCell:
    """九宫格里的一格及其边缘能量。"""

    row: int
    col: int
    label: str
    energy: float
    energy_share: float


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    """按 WCAG 公式算相对亮度，用于计算对比度比值。"""
    channels = []
    for value in rgb[:3]:
        srgb = value / 255
        channels.append(srgb / 12.92 if srgb <= 0.04045 else ((srgb + 0.055) / 1.055) ** 2.4)
    red, green, blue = channels
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(color_a: tuple[int, int, int], color_b: tuple[int, int, int]) -> float:
    """两个颜色之间的 WCAG 对比度比值，范围 1:1 ~ 21:1。

    用来判断"这个颜色的文字叠在这块背景上看得清吗"。
    正文建议 ≥ 4.5，大号标题可放宽到 ≥ 3。
    """
    lum_a, lum_b = _relative_luminance(color_a), _relative_luminance(color_b)
    lighter, darker = max(lum_a, lum_b), min(lum_a, lum_b)
    return round((lighter + 0.05) / (darker + 0.05), 2)


_CELL_LABELS = (
    ("左上", "中上", "右上"),
    ("左中", "正中", "右中"),
    ("左下", "中下", "右下"),
)


def _grid_energy(image: Image.Image) -> list[GridCell]:
    """把图切成九宫格，算每格的边缘能量（越高说明细节/主体越集中在那儿）。"""
    edges = image.convert("L").filter(ImageFilter.FIND_EDGES)
    width, height = edges.size
    cell_w, cell_h = width // GRID, height // GRID

    raw: list[tuple[int, int, float]] = []
    for row in range(GRID):
        for col in range(GRID):
            box = (
                col * cell_w,
                row * cell_h,
                width if col == GRID - 1 else (col + 1) * cell_w,
                height if row == GRID - 1 else (row + 1) * cell_h,
            )
            raw.append((row, col, ImageStat.Stat(edges.crop(box)).mean[0]))

    total = sum(energy for _, _, energy in raw) or 1.0
    return [
        GridCell(
            row=row,
            col=col,
            label=_CELL_LABELS[row][col],
            energy=round(energy, 2),
            energy_share=round(energy / total, 4),
        )
        for row, col, energy in raw
    ]


def _dominant_colors(image: Image.Image, count: int = 5) -> list[dict]:
    """取画面里占比最高的几个颜色。用于核对是否符合品牌主色。"""
    small = image.convert("RGB").resize((120, 120))
    quantized = small.quantize(colors=count, method=Image.Quantize.FASTOCTREE)
    palette = quantized.getpalette() or []
    counts = sorted(quantized.getcolors() or [], key=lambda item: -item[0])
    total = sum(n for n, _ in counts) or 1

    colors: list[dict] = []
    for pixels, index in counts[:count]:
        rgb = tuple(palette[index * 3 : index * 3 + 3])
        if len(rgb) < 3:
            continue
        colors.append(
            {
                "hex": "#{:02X}{:02X}{:02X}".format(*rgb),
                "rgb": list(rgb),
                "share_pct": round(pixels / total * 100, 2),
            }
        )
    return colors


def _aspect_ratio_label(width: int, height: int) -> str:
    """把宽高转成 '1.91:1' 这种可读比例。"""
    if not height:
        return "unknown"
    return f"{round(width / height, 2)}:1"


def analyze_image(path: str | pathlib.Path) -> dict:
    """算出一张图的客观指标：尺寸、对比度、主色、视觉重心、可叠字区域。

    **本函数不判断好不好看。** 它只给数字，审美结论由模型看图后自己下。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 不是支持的图片格式。
    """
    file_path = pathlib.Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"图片不存在：{file_path}")

    with Image.open(file_path) as image:
        image.load()
        image_format = (image.format or "").upper()
        if image_format not in SUPPORTED_FORMATS:
            raise ValueError(
                f"不支持的图片格式 {image_format or '未知'}，"
                f"仅支持：{'、'.join(SUPPORTED_FORMATS)}。"
            )

        width, height = image.size
        grayscale = image.convert("L")
        stat = ImageStat.Stat(grayscale)
        brightness = round(stat.mean[0], 2)
        contrast_stddev = round(stat.stddev[0], 2)

        cells = _grid_energy(image)
        colors = _dominant_colors(image)

    strongest = max(cells, key=lambda c: c.energy_share)
    emptiest = min(cells, key=lambda c: c.energy_share)

    # 视觉重心：按能量加权的格子中心位置，换算成 0~1 的相对坐标
    total_share = sum(c.energy_share for c in cells) or 1.0
    focal_x = sum((c.col + 0.5) / GRID * c.energy_share for c in cells) / total_share
    focal_y = sum((c.row + 0.5) / GRID * c.energy_share for c in cells) / total_share

    # 上/中/下三带的能量分布，看画面重心是偏上还是偏下
    band_energy = {
        "上三分之一": round(sum(c.energy_share for c in cells if c.row == 0), 4),
        "中三分之一": round(sum(c.energy_share for c in cells if c.row == 1), 4),
        "下三分之一": round(sum(c.energy_share for c in cells if c.row == 2), 4),
    }

    if contrast_stddev < LOW_CONTRAST_STDDEV:
        contrast_verdict = "偏低，画面容易发灰、不抓眼"
    elif contrast_stddev > HIGH_CONTRAST_STDDEV:
        contrast_verdict = "偏高，可能过于刺眼或噪点明显"
    else:
        contrast_verdict = "在常见的舒适区间内"

    return {
        "file": str(file_path),
        "format": image_format,
        "width": width,
        "height": height,
        "aspect_ratio": _aspect_ratio_label(width, height),
        "file_size_kb": round(file_path.stat().st_size / 1024, 1),
        "brightness_mean": brightness,
        "contrast_stddev": contrast_stddev,
        "contrast_verdict": contrast_verdict,
        "dominant_colors": colors,
        "subject": {
            "strongest_cell": strongest.label,
            "strongest_share": strongest.energy_share,
            "is_prominent": strongest.energy_share >= SUBJECT_PROMINENCE_THRESHOLD,
            "note": (
                "主体明确，视觉焦点集中"
                if strongest.energy_share >= SUBJECT_PROMINENCE_THRESHOLD
                else "细节分布均匀、没有明显主体，画面容易显得平淡"
            ),
        },
        "focal_point": {
            "x_ratio": round(focal_x, 3),
            "y_ratio": round(focal_y, 3),
            "description": _describe_focal(focal_x, focal_y),
        },
        "band_energy": band_energy,
        "text_overlay_suggestion": {
            "emptiest_cell": emptiest.label,
            "emptiest_share": emptiest.energy_share,
            "advice": f"文案建议放在「{emptiest.label}」区域，那里细节最少、最不会压住主体。",
        },
        "grid_energy": [
            {"cell": c.label, "energy": c.energy, "share": c.energy_share} for c in cells
        ],
        "reminder": (
            "以上都是客观测量值，不代表画面好看或不好看。"
            "视觉吸引力和图文匹配度需要看图判断。"
        ),
    }


def _describe_focal(x_ratio: float, y_ratio: float) -> str:
    """把视觉重心坐标翻译成人话。只报偏离的那个方向，两个都居中才说居中。"""
    horizontal = "偏左" if x_ratio < 0.42 else ("偏右" if x_ratio > 0.58 else "")
    vertical = "偏上" if y_ratio < 0.42 else ("偏下" if y_ratio > 0.58 else "")
    if not horizontal and not vertical:
        return "视觉重心居中"
    if horizontal and vertical:
        # '偏右' + '偏上' 读起来别扭，合成 '偏右上'
        return "视觉重心" + horizontal + vertical[1:]
    return "视觉重心" + horizontal + vertical


def check_size_compliance(width: int, height: int, target_ratio: str) -> dict:
    """核对图片比例是否符合目标广告位要求。

    Args:
        width: 图片宽度像素。
        height: 图片高度像素。
        target_ratio: 目标比例，形如 '1.91' 或 '1.0'（宽 ÷ 高）。
    """
    actual = width / height if height else 0
    target = float(target_ratio)
    # 允许 2% 误差：裁剪时的取整会带来极小偏差
    tolerance = 0.02
    deviation = abs(actual - target) / target if target else 1.0
    return {
        "actual_ratio": round(actual, 3),
        "target_ratio": target,
        "deviation_pct": round(deviation * 100, 2),
        "compliant": deviation <= tolerance,
    }
