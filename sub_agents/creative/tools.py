"""文案工具：RSA 标题与描述的卖点原料、多版本撰写支持、字符与合规校验。

【为什么和视觉工具分开】
文案和出图是两件不相干的事：文案只算字符和规则，出图要装 Pillow、要调模型、
要花钱。混在一个文件里，改文案校验时要翻过几百行图片代码，
而且读文案逻辑的人被迫看见一堆和他无关的依赖。

最关键的一条：**字符数必须由代码数，绝不能让模型自己声称数过了。**
模型看到的是 token 不是字符，而中文全角字符在 Google Ads 眼里算两个，
它一定会数错；数错的素材提交给 API 会被直接拒绝。
"""

from __future__ import annotations

from google.adk.tools import ToolContext

from ... import config
from ...session_state import remember
from . import data as creative_data
from . import metrics as creative

# 一次最多返回多少条卖点，避免塞爆上下文
MAX_USPS_RETURNED = 30


def list_creative_scope() -> dict:
    """查询能做哪些产品的创意、有哪些品牌风格、支持哪些广告尺寸，以及图像生成当前是什么模式。

    开始写文案或出图前先调用本工具，确认产品名、风格名的准确写法，
    并确认图像生成是 mock 还是 live（live 会真花钱）。

    注意：本工具不需要任何参数。
    """
    return {
        "status": "success",
        "products_with_usp": list(creative_data.PRODUCTS_WITH_USP),
        "usp_angles": creative_data.USP_ANGLES,
        "brand_styles": {
            name: {
                "palette": list(style.palette),
                "mood": style.mood,
                "composition": style.composition,
            }
            for name, style in creative_data.BRAND_STYLES.items()
        },
        "ad_sizes": {
            key: {
                "label": spec.label,
                "target_ratio": spec.ratio_label,
                "pixels": f"{spec.width}x{spec.height}",
                "usage": spec.usage,
                "model_ratio": spec.imagen_ratio,
                "needs_crop": spec.needs_crop,
            }
            for key, spec in creative_data.AD_SIZE_SPECS.items()
        },
        "image_generation": config.image_generation_status(),
        "rsa_limits": {
            "headline_max_units": creative.HEADLINE_MAX_UNITS,
            "description_max_units": creative.DESCRIPTION_MAX_UNITS,
            "headline_count": f"{creative.HEADLINE_MIN_COUNT}~{creative.HEADLINE_MAX_COUNT}",
            "description_count": (
                f"{creative.DESCRIPTION_MIN_COUNT}~{creative.DESCRIPTION_MAX_COUNT}"
            ),
            "cjk_note": (
                "限额单位是半角字符数。中日韩全角字符**每个算 2 个单位**，"
                "所以纯中文标题实际只能写 15 个字、描述 45 个字。"
                "不要自己数，写完一定调 validate_ad_copy 校验。"
            ),
        },
    }


def get_product_usps(
    product: str, angle: str | None = None, tool_context: ToolContext = None
) -> dict:
    """取某个产品的卖点原料（客观事实），供你写文案时引用。

    这里给的是**事实**，不是文案。你的活是把事实写成有吸引力的短句，
    不要发明这里没有的事实——编出来的卖点会导致落地页不符、被拒审。

    Args:
        product: 产品名，如 '跑鞋'。不确定写法先调 list_creative_scope。
        angle: 只看某个卖点维度，可选 pain_point / offer / trust /
            service / feature / scenario。不填则全都要。
    """
    if product not in creative_data.PRODUCTS_WITH_USP:
        return {
            "status": "error",
            "error_message": (
                f"没有 {product} 的卖点库。"
                f"可用产品：{'、'.join(creative_data.PRODUCTS_WITH_USP)}。"
            ),
        }
    if angle and angle not in creative_data.USP_ANGLES:
        return {
            "status": "error",
            "error_message": (
                f"没有 {angle} 这个卖点维度。"
                f"可选：{'、'.join(creative_data.USP_ANGLES)}。"
            ),
        }

    usps = [
        u
        for u in creative_data.PRODUCT_USPS
        if u.product == product and (angle is None or u.angle == angle)
    ]
    if not usps:
        return {
            "status": "error",
            "error_message": f"{product} 没有 {angle} 维度的卖点，换个维度试试。",
        }

    by_angle: dict[str, list[dict]] = {}
    for usp in usps[:MAX_USPS_RETURNED]:
        by_angle.setdefault(usp.angle, []).append(
            {"fact": usp.fact, "proof": usp.proof}
        )

    remember(tool_context, current_product=product)
    return {
        "status": "success",
        "product": product,
        "angle_meanings": creative_data.USP_ANGLES,
        "usps_by_angle": by_angle,
        "covered_angles": sorted(by_angle),
        "missing_angles": sorted(set(creative_data.USP_ANGLES) - set(by_angle)),
        "hint": (
            "RSA 靠 Google 自动组合不同标题去试探哪个组合转化好，"
            "所以标题必须**多角度铺开**——15 个标题全是优惠角度，系统就没得试探了。"
            "有 proof 的卖点优先写进文案，可信度更高。"
        ),
    }


def validate_ad_copy(
    headlines: list[str],
    descriptions: list[str],
    paths: list[str] | None = None,
    tool_context: ToolContext = None,
) -> dict:
    """校验 RSA 文案：字符宽度、数量、重复、合规规则。提交给 Google Ads 前必须过这一关。

    **写完文案一定要调本工具，不要自己数字符。**
    中文全角字符每个算 2 个单位，标题额度 30 个单位（即 15 个汉字），
    描述 90 个单位（即 45 个汉字）。

    返回里 ready_to_submit 为 false 时，看 over_limit_texts 知道哪条超了几个单位，
    改完再调一次，直到通过。

    Args:
        headlines: 标题列表，建议 8 条以上，上限 15 条。
        descriptions: 描述列表，2~4 条。
        paths: 展示路径，最多 2 段，每段 15 个单位。不填则不校验。
    """
    if not headlines or not descriptions:
        return {
            "status": "error",
            "error_message": "标题和描述都不能为空。",
        }

    result = creative.validate_rsa(headlines, descriptions, paths)

    # 把最需要行动的信息提到最前面，省得模型在长 JSON 里找
    fix_instructions: list[str] = []
    for item in result["over_limit_texts"]:
        kind_label = {"headline": "标题", "description": "描述", "path": "路径"}[item["kind"]]
        cjk_over = -(-item["over_by_units"] // 2)  # 向上取整
        fix_instructions.append(
            f"{kind_label}「{item['text']}」超了 {item['over_by_units']} 个单位，"
            f"约需删掉 {cjk_over} 个汉字。"
        )
    for group_key, label in (("headlines", "标题"), ("descriptions", "描述"), ("paths", "路径")):
        for asset in result[group_key]:
            for issue in asset["content_issues"]:
                if issue["severity"] == "error":
                    fix_instructions.append(
                        f"{label}「{asset['text']}」违反「{issue['rule']}」：{issue['detail']}"
                    )

    remember(
        tool_context,
        current_headlines=headlines if result["ready_to_submit"] else None,
        current_descriptions=descriptions if result["ready_to_submit"] else None,
    )

    return {
        "status": "success" if result["ready_to_submit"] else "needs_fix",
        "ready_to_submit": result["ready_to_submit"],
        "must_fix": fix_instructions,
        "structure_issues": result["structure_issues"],
        "warnings": result["warnings"],
        "summary": {
            "headline_count": result["headline_count"],
            "description_count": result["description_count"],
            "over_limit_count": result["over_limit_count"],
            "invalid_count": result["invalid_count"],
        },
        "headline_details": [
            {
                "text": a["text"],
                "width_units": a["width_units"],
                "limit_units": a["limit_units"],
                "remaining_cjk_chars": a["remaining_cjk_chars"],
                "within_limit": a["within_limit"],
                "issues": [i["rule"] for i in a["content_issues"]],
            }
            for a in result["headlines"]
        ],
        "description_details": [
            {
                "text": a["text"],
                "width_units": a["width_units"],
                "limit_units": a["limit_units"],
                "remaining_cjk_chars": a["remaining_cjk_chars"],
                "within_limit": a["within_limit"],
                "issues": [i["rule"] for i in a["content_issues"]],
            }
            for a in result["descriptions"]
        ],
        "next_step": (
            "全部通过，可以提交。"
            if result["ready_to_submit"]
            else "按 must_fix 逐条改完，再调一次本工具确认。"
        ),
    }
