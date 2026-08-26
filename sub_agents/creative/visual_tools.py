"""视觉工具：图像 prompt 构筑、多比例批量出图、素材质量诊断。

【和文案工具分开的另一个原因】
本文件是唯一会**花钱**的地方（真出图按张计费），也是唯一依赖 Pillow 和
图像模型的地方。单独成文件后，成本护栏都集中在这里，一眼能审完：
默认 mock、单次张数上限、占位图明确标注不可投放。
"""

from __future__ import annotations

import base64
import pathlib

from google.adk.tools import ToolContext

from ... import config
from ...session_state import remember
from . import data as creative_data
from . import image_quality

# 生成的图片存在这里（已 gitignore，不进版本库）。
# parents[2] 是 agent 包根目录：creative → sub_agents → digital_marketing_agent。
# 重构目录时这一行最容易被漏掉，有测试盯着它落在包根的 generated/ 下。
OUTPUT_DIR = pathlib.Path(__file__).parents[2] / "generated"


def _compose_prompt(
    theme: str, style: creative_data.BrandStyle, spec: creative_data.AdSizeSpec
) -> str:
    """把营销主题 + 品牌风格 + 尺寸用途拼成一条图像生成 prompt。

    两个刻意的选择：
    1. **用英文写**。图像模型对英文的色彩词、材质词、光线词理解得细得多，
       中文 prompt 出来的画面经常偏离。
    2. **明确要求画面里不要有文字**。广告文案由投放系统叠加，
       生成的图只做背景；而且图像模型渲染中文字经常出错字。
    """
    avoid_clause = ", ".join(style.avoid)
    return (
        f"{theme}. "
        f"Style: {style.mood}. "
        f"Lighting: {style.lighting}. "
        f"Composition: {style.composition}. "
        f"Color palette: {', '.join(style.palette)}. "
        f"Intended use: {spec.usage}. "
        f"Clean advertising banner background with no text, no letters, no watermark. "
        f"Avoid: {avoid_clause}."
    )


def build_visual_prompts(
    theme: str,
    brand_style: str,
    sizes: list[str] | None = None,
    tool_context: ToolContext = None,
) -> dict:
    """把营销主题转成图像生成 prompt，并给出每个尺寸的生成参数。

    本工具**不出图、不花钱**，只产出 prompt。确认 prompt 满意后再调
    render_visual_assets 真正生成。

    Args:
        theme: 画面主题的描述。**请用英文写**，例如
            'a pair of running shoes on a wet rubber track at dawn, dew reflecting light'。
            图像模型对英文的材质、光线、色彩词理解得细得多，中文描述出来的画面
            经常偏离。写得越具体越好：主体是什么、在什么环境、什么状态。
        brand_style: 品牌风格名，如 '科技感'。先调 list_creative_scope 看可选值。
        sizes: 要哪些尺寸，可选 square / landscape / vertical。不填则三个都要。
    """
    style = creative_data.BRAND_STYLES.get(brand_style)
    if not style:
        return {
            "status": "error",
            "error_message": (
                f"没有 {brand_style} 这个品牌风格。"
                f"可选：{'、'.join(creative_data.BRAND_STYLES)}。"
            ),
        }

    size_keys = sizes or list(creative_data.AD_SIZE_SPECS)
    unknown = [k for k in size_keys if k not in creative_data.AD_SIZE_SPECS]
    if unknown:
        return {
            "status": "error",
            "error_message": (
                f"没有 {'、'.join(unknown)} 这些尺寸。"
                f"可选：{'、'.join(creative_data.AD_SIZE_SPECS)}。"
            ),
        }

    plans = []
    for key in size_keys:
        spec = creative_data.AD_SIZE_SPECS[key]
        plans.append(
            {
                "size_key": key,
                "label": spec.label,
                "target_ratio": spec.ratio_label,
                "target_pixels": f"{spec.width}x{spec.height}",
                "model_aspect_ratio": spec.imagen_ratio,
                "needs_crop": spec.needs_crop,
                "crop_note": (
                    f"图像模型不支持 {spec.ratio_label}，会先按 {spec.imagen_ratio} 生成"
                    f"再居中裁剪到 {spec.ratio_label}。主体和留白要避开上下边缘，"
                    f"否则裁剪时会被切掉。"
                )
                if spec.needs_crop
                else "模型原生支持该比例，无需裁剪。",
                "prompt": _compose_prompt(theme, style, spec),
            }
        )

    remember(tool_context, current_theme=theme, current_brand_style=brand_style)
    return {
        "status": "success",
        "theme": theme,
        "brand_style": brand_style,
        "style_params": {
            "palette": list(style.palette),
            "mood": style.mood,
            "lighting": style.lighting,
            "composition": style.composition,
            "avoid": list(style.avoid),
        },
        "plans": plans,
        "notes": [
            "prompt 用英文写，因为图像模型对英文的色彩/材质/光线词理解更细。",
            "prompt 里明确要求画面无文字：广告文案由投放系统叠加，"
            "而且图像模型渲染中文经常出错字。",
            "**负向 prompt 已失效**：当前这代图像模型不再支持单独的 negative prompt，"
            "所以不要投放的元素是写进正向 prompt 的 Avoid 从句里的。",
            "本工具不花钱。真正出图要调 render_visual_assets。",
        ],
    }


def _crop_to_ratio(image, target_ratio: float):
    """居中裁剪到目标宽高比。用于图像模型不支持的比例（如 1.91:1）。"""
    from PIL import Image  # 局部导入：只有真的要处理图片时才需要 Pillow

    assert isinstance(image, Image.Image)
    width, height = image.size
    current = width / height
    if abs(current - target_ratio) < 0.005:
        return image
    if current > target_ratio:
        # 太宽，裁掉左右
        new_width = int(height * target_ratio)
        offset = (width - new_width) // 2
        return image.crop((offset, 0, offset + new_width, height))
    # 太高，裁掉上下
    new_height = int(width / target_ratio)
    offset = (height - new_height) // 2
    return image.crop((0, offset, width, offset + new_height))


def _draw_placeholder(spec: creative_data.AdSizeSpec, style: creative_data.BrandStyle, prompt: str):
    """mock 模式下本地画一张占位图：带比例、品牌色块和 prompt 摘要。

    刻意画得"像个占位图"而不是像真素材——避免有人误把它当成生成结果去投放。
    """
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (spec.width, spec.height), style.palette[0].split()[-1])
    draw = ImageDraw.Draw(image)

    # 品牌色块，用来直观核对风格是否一致
    swatch = max(40, spec.width // 12)
    for index, color in enumerate(style.palette):
        hex_code = color.split()[-1]
        draw.rectangle(
            [index * swatch, 0, (index + 1) * swatch, swatch],
            fill=hex_code,
        )

    # 对角线 + 文字，一眼看出是占位图
    draw.line([(0, 0), (spec.width, spec.height)], fill="#999999", width=2)
    draw.line([(0, spec.height), (spec.width, 0)], fill="#999999", width=2)
    lines = [
        "PLACEHOLDER / 占位图（未真实生成）",
        f"{spec.label} {spec.ratio_label}  {spec.width}x{spec.height}",
        f"style: {style.name}",
        prompt[:120] + ("..." if len(prompt) > 120 else ""),
    ]
    draw.multiline_text(
        (swatch // 2, swatch + 20),
        "\n".join(lines),
        fill="#333333",
        spacing=8,
    )
    return image


def render_visual_assets(
    theme: str,
    brand_style: str,
    sizes: list[str] | None = None,
    quality: str | None = None,
    tool_context: ToolContext = None,
) -> dict:
    """生成广告视觉素材图片，按尺寸各出一张，保存到本地并返回路径。

    **成本提醒**：当 IMAGE_GENERATION_MODE=live 时，每张图都要按张付费，
    且免费额度不覆盖图像生成。默认是 mock 模式，本地画占位图、零成本，
    用来跑通流程和验证尺寸裁剪。

    调用前建议先用 build_visual_prompts 确认 prompt 满意，避免反复出图浪费钱。

    Args:
        theme: 画面主题描述，**用英文写**（原因见 build_visual_prompts）。
        brand_style: 品牌风格名，如 '科技感'。
        sizes: 要哪些尺寸，可选 square / landscape / vertical。不填则三个都要。
        quality: 生图档位，按用途选，不填用 standard：
            - 'draft'（Nano Banana 2 Lite）最便宜、可高并发。
              用于社媒缩略图批量制作、多方案快速草稿预览、大规模自动化素材测试。
            - 'standard'（Nano Banana 2）**主力推荐**，速度与质量平衡。
              用于生产环境的标准营销 Banner、电商产品背景替换、响应式广告素材。
            - 'premium'（Nano Banana Pro）顶级视觉效果，也最贵。
              用于品牌主海报、需高精修的产品宣发图、对文字排版与逼真度要求极高的精品素材。
            先出草稿再挑一版升到 premium，比一上来就用 premium 省得多。
    """
    plan_result = build_visual_prompts(theme, brand_style, sizes, tool_context)
    if plan_result["status"] != "success":
        return plan_result

    status = config.image_generation_status()
    tier = config.image_tier(quality)
    plans = plan_result["plans"]
    cap = status["max_images_per_call"]
    if len(plans) > cap:
        return {
            "status": "error",
            "error_message": (
                f"一次要生成 {len(plans)} 张，超过单次上限 {cap} 张。"
                f"请分批调用，或调高 .env 里的 IMAGE_MAX_PER_CALL（硬上限 "
                f"{config.IMAGE_HARD_CAP_PER_CALL}）。"
            ),
        }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    style = creative_data.BRAND_STYLES[brand_style]
    live = status["effective_mode"] == config.MODE_LIVE

    assets = []
    for plan in plans:
        spec = creative_data.AD_SIZE_SPECS[plan["size_key"]]
        try:
            if live:
                image = _generate_live_image(plan["prompt"], spec, tier["model"])
            else:
                image = _draw_placeholder(spec, style, plan["prompt"])

            target_ratio = spec.width / spec.height
            image = _crop_to_ratio(image, target_ratio)
            if image.size != (spec.width, spec.height):
                from PIL import Image as PILImage

                image = image.resize((spec.width, spec.height), PILImage.LANCZOS)

            filename = f"{brand_style}_{plan['size_key']}_{spec.width}x{spec.height}.png"
            path = OUTPUT_DIR / filename
            image.save(path, format="PNG")
            assets.append(
                {
                    "size_key": plan["size_key"],
                    "label": spec.label,
                    "ratio": spec.ratio_label,
                    "pixels": f"{spec.width}x{spec.height}",
                    "file": str(path),
                    "was_cropped": spec.needs_crop,
                    "is_placeholder": not live,
                }
            )
        except Exception as exc:  # noqa: BLE001 - 要把失败原因如实告诉模型
            assets.append(
                {
                    "size_key": plan["size_key"],
                    "label": spec.label,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    succeeded = [a for a in assets if "file" in a]
    return {
        "status": "success" if succeeded else "error",
        "mode": status["effective_mode"],
        "quality_tier": tier["tier"],
        "model": tier["model"] if live else "本地占位图（未调用模型）",
        "model_display_name": tier["display_name"],
        "tier_note": (
            f"档位 {tier['tier']}（{tier['display_name']}）：{tier['positioning']}。"
            + (
                f" 你传的 '{tier['requested']}' 不是有效档位，已回退到默认档。"
                if tier["fell_back"]
                else ""
            )
        ),
        "images_generated": len(succeeded),
        "assets": assets,
        "cost_note": (
            f"live 模式：本次生成 {len(succeeded)} 张，按张计费。"
            if live
            else "mock 模式：本地画的占位图，**不是真实素材，不能拿去投放**，零成本。"
        ),
        "next_step": (
            "可以调 inspect_visual_asset 对生成的图做质量诊断（主体突出度、"
            "对比度、视觉焦点、可叠字区域），并检查图文是否匹配。"
        ),
    }


def _generate_live_image(prompt: str, spec: creative_data.AdSizeSpec, model: str):
    """真调 Gemini 图像模型出一张图。【live 模式，按张计费】

    ==== 已用本账号实测确认的关键事实 ====
    1. **Imagen 系列已在 Gemini API 全部下线**。用 client.models.list() 查本账号，
       一个 imagen-* 都没有。所以 client.models.generate_images()（Imagen 的
       predict 接口）在这里根本调不通。
    2. 实测可用的是 Gemini 原生图像模型，它们只支持 generateContent：
       gemini-3.1-flash-lite-image / gemini-2.5-flash-image /
       gemini-3.1-flash-image / gemini-3-pro-image
    3. 所以正确的调用方式是 generate_content + response_modalities=["IMAGE"]，
       比例通过 image_config.aspect_ratio 传。
    4. **没有 1.91:1 这个比例**。支持的是 1:1 / 3:4 / 4:3 / 9:16 / 16:9 这类，
       横版 banner 只能用 16:9 生成再裁剪——这就是 needs_crop 的由来。
    """
    import io
    import os

    from google import genai
    from google.genai import types
    from PIL import Image

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY 没配置，无法调用图像模型。")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(aspect_ratio=spec.imagen_ratio),
        ),
    )

    for candidate in response.candidates or []:
        for part in (candidate.content.parts if candidate.content else []) or []:
            blob = part.inline_data
            if blob and blob.data and (blob.mime_type or "").startswith("image/"):
                raw = blob.data
                if isinstance(raw, str):  # 某些传输路径会给 base64 字符串
                    raw = base64.b64decode(raw)
                return Image.open(io.BytesIO(raw)).convert("RGB")

    raise RuntimeError(
        "模型没有返回图片。常见原因：prompt 触发了安全过滤，或该模型不支持图像输出。"
    )


async def inspect_visual_asset(
    image_path: str,
    ad_copy: str | None = None,
    target_size: str | None = None,
    tool_context: ToolContext = None,
) -> dict:
    """诊断一张素材图：客观指标 + 把图交给你亲眼看，用于判断吸引力和图文匹配。

    本工具做两件事：
    1. **算客观指标**：对比度、主体突出度、视觉焦点位置、主色、最适合叠字的区域、
       比例是否达标。这些是量化结果，你直接引用。
    2. **把图存成 artifact**，然后你要调 load_artifacts 把它读进来**亲眼看**，
       才能判断视觉吸引力和图文匹配度——这两项没有公式可算。

    Args:
        image_path: 图片路径。render_visual_assets 返回的 file 字段可直接用。
        ad_copy: 配这张图的广告文案。填了才能做图文匹配度检查。
        target_size: 目标广告位，可选 square / landscape / vertical。
            填了会核对比例是否达标。
    """
    try:
        metrics = image_quality.analyze_image(image_path)
    except FileNotFoundError as exc:
        return {"status": "error", "error_message": str(exc)}
    except ValueError as exc:
        return {"status": "error", "error_message": str(exc)}

    compliance = None
    if target_size:
        spec = creative_data.AD_SIZE_SPECS.get(target_size)
        if not spec:
            return {
                "status": "error",
                "error_message": (
                    f"没有 {target_size} 这个广告位。"
                    f"可选：{'、'.join(creative_data.AD_SIZE_SPECS)}。"
                ),
            }
        compliance = image_quality.check_size_compliance(
            metrics["width"], metrics["height"], str(round(spec.width / spec.height, 3))
        )
        compliance["target_label"] = f"{spec.label} {spec.ratio_label}"

    # 叠字可读性：拿最空区域的主色和白/黑字算对比度
    palette = metrics["dominant_colors"]
    legibility = None
    if palette:
        background = tuple(palette[0]["rgb"])
        legibility = {
            "dominant_background": palette[0]["hex"],
            "white_text_contrast": image_quality.contrast_ratio(background, (255, 255, 255)),
            "black_text_contrast": image_quality.contrast_ratio(background, (0, 0, 0)),
            "min_required": image_quality.MIN_TEXT_CONTRAST_RATIO,
        }
        legibility["recommended_text_color"] = (
            "白字" if legibility["white_text_contrast"] >= legibility["black_text_contrast"]
            else "黑字"
        )
        legibility["passes"] = (
            max(legibility["white_text_contrast"], legibility["black_text_contrast"])
            >= image_quality.MIN_TEXT_CONTRAST_RATIO
        )

    # 存成 artifact，让模型能真的看到这张图
    artifact_name = pathlib.Path(image_path).name
    artifact_saved = False
    artifact_error = None
    if tool_context:
        try:
            from google.genai import types

            data = pathlib.Path(image_path).read_bytes()
            await tool_context.save_artifact(
                artifact_name,
                types.Part.from_bytes(data=data, mime_type="image/png"),
            )
            artifact_saved = True
        except Exception as exc:  # noqa: BLE001 - artifact 服务可能没配，不该让诊断失败
            artifact_error = f"{type(exc).__name__}: {exc}"

    remember(tool_context, current_asset=image_path)
    return {
        "status": "success",
        "objective_metrics": metrics,
        "size_compliance": compliance,
        "text_legibility": legibility,
        "ad_copy_for_comparison": ad_copy,
        "artifact_name": artifact_name if artifact_saved else None,
        "artifact_error": artifact_error,
        "your_turn": (
            f"以上是客观测量值。现在请调 load_artifacts 读入「{artifact_name}」亲眼看这张图，"
            "然后判断两件没有公式可算的事："
            "(1) 视觉吸引力——主体是否一眼抓住注意力、画面是否显得廉价或杂乱；"
            "(2) 图文匹配度——画面的语义和情感基调与广告文案是否一致，"
            "有没有'文案说高端、画面显廉价'这类割裂。"
            + ("" if ad_copy else " 想做图文匹配检查的话，请把广告文案传进 ad_copy 参数。")
        )
        if artifact_saved
        else (
            "客观指标已给出，但图片没能存成 artifact（见 artifact_error），"
            "所以你看不到画面，无法判断吸引力和图文匹配。"
            "请让用户把图片直接发到对话里。"
        ),
    }
