"""文案侧的纯计算层：字符宽度、RSA 校验、卖点覆盖统计。

【为什么字符计数必须由代码做】
Google Ads 的标题上限是 30 个字符——但中文、日文、韩文这类**全角字符算两个**。
所以"限时直降六百元包邮"这 10 个汉字，在 Google 眼里是 20 个字符。
大模型数不准字符数（它看到的是 token，不是字符），一定会超限；
超限的素材提交给 API 会被直接拒绝。

所以这里的做法是：**代码算，模型改**。模型写文案，代码判超没超、超了几个单位，
把结果退回给模型让它压缩。绝不让模型自己声称"我数过了，没超"。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence

# ===== Google Ads RSA 的额度上限 =====
# 单位是"半角字符数"。中日韩全角字符每个占 2 个单位，
# 因此纯中文标题实际能写 15 个汉字（15 × 2 = 30）。
# 这种算法对中英混排也天然正确：'Nike跑鞋' = 4 + 2×2 = 8 个单位。
HEADLINE_MAX_UNITS = 30
DESCRIPTION_MAX_UNITS = 90
PATH_MAX_UNITS = 15

# 一条 RSA 能放多少素材
HEADLINE_MIN_COUNT = 3
HEADLINE_MAX_COUNT = 15
DESCRIPTION_MIN_COUNT = 2
DESCRIPTION_MAX_COUNT = 4

# 标题数量的建议下限。**这是本项目的建议，不是 Google 的硬性要求**——
# 官方只说"尽可能多写不重复的标题，上限 15 条"，没有给具体数字。
# 取 8 是因为系统需要足够的素材量才能做组合试探。
HEADLINE_RECOMMENDED_COUNT = 8

# ===== 内容规则 =====
# 分两类，因为来源不同，严重程度也不同：
#
# 【官方明令禁止】命中会被拒审。已核对 Google Ads 政策页面：
#   - 连续重复标点（'flowers!!'）
#   - 滥用大写（FLOWERS / FlOwErS）
#   - 逐字母加点（F.L.O.W.E.R.S）
#   - 文案里写电话号码
#   - 素材文本重复（同一广告组/广告series/账户内重复都算）
MAX_REPEATED_PUNCTUATION = 1

# 【本项目的保守偏好，不是 Google 政策】
# "标题不用感叹号、整条最多一个感叹号"是 AdWords 时代的旧指南，
# 在现行官方政策里**查不到**，广泛流传于代理商博客。
# 现行政策只禁止连续重复（'！！'），单个感叹号并不违规。
# 这里仍然保留限制，是因为"标点未按预期用途使用"是一条自由裁量的兜底条款，
# 少用感叹号更稳妥。所以严重程度标为 warning 而非 error，不阻塞提交。
MAX_EXCLAMATION_IN_HEADLINE = 0
MAX_EXCLAMATION_TOTAL = 1

# 全角字符的 East Asian Width 分类。W = Wide（汉字、假名），F = Fullwidth（全角标点数字）
_DOUBLE_WIDTH_CATEGORIES = frozenset({"W", "F"})


def char_width(char: str) -> int:
    """单个字符占几个单位。全角算 2，其余算 1。

    判断依据是 Unicode 的 East Asian Width 属性：
    W（Wide，汉字/假名/韩文）和 F（Fullwidth，全角标点与全角数字）算 2。
    A（Ambiguous，如希腊字母、部分符号）按 1 算——这类字符在不同环境下
    宽度不一致，Google 官方未说明如何计，取保守但常见的处理。
    """
    return 2 if unicodedata.east_asian_width(char) in _DOUBLE_WIDTH_CATEGORIES else 1


def display_width(text: str) -> int:
    """一段文本占几个单位。这是判断有没有超限的唯一依据。"""
    return sum(char_width(c) for c in text)


def truncate_to_width(text: str, max_units: int) -> str:
    """把文本裁到不超过 max_units 个单位。裁的时候不切半个字符。

    注意：这个函数只用于**展示预览**，不建议直接拿裁剪结果当文案——
    机械裁剪会把句子切得莫名其妙。正确做法是把超限信息退给模型重写。
    """
    used = 0
    kept: list[str] = []
    for char in text:
        width = char_width(char)
        if used + width > max_units:
            break
        kept.append(char)
        used += width
    return "".join(kept)


# 允许的全大写缩写白名单：这些不算"滥用大写"
_ALLOWED_UPPERCASE = frozenset({"ASAP", "DIY", "UV", "SPF", "LED", "USB", "PRO", "MAX", "XL", "XXL"})

# 看起来像电话号码的数字串（Google Ads 不允许在文案里写电话）
_PHONE_LIKE_MIN_DIGITS = 7

_ASSET_LIMITS = {
    "headline": HEADLINE_MAX_UNITS,
    "description": DESCRIPTION_MAX_UNITS,
    "path": PATH_MAX_UNITS,
}


def _count_repeated_punctuation(text: str) -> list[str]:
    """找出连续重复的标点，如 '！！'、'。。。'。返回命中的片段。"""
    hits: list[str] = []
    run_char, run_len = "", 0
    for char in text:
        is_punct = unicodedata.category(char).startswith("P")
        if is_punct and char == run_char:
            run_len += 1
        else:
            run_char, run_len = (char, 1) if is_punct else ("", 0)
        if run_len > MAX_REPEATED_PUNCTUATION:
            segment = char * run_len
            if segment not in hits:
                hits.append(segment)
    return hits


def _has_letter_spaced_word(text: str) -> bool:
    """检测 'F.L.O.W.E.R.S' 这种把单词逐字母打点的写法。"""
    letters_with_dots = 0
    for i in range(len(text) - 1):
        if text[i].isalpha() and text[i + 1] in ".·":
            letters_with_dots += 1
    return letters_with_dots >= 3


def _has_abusive_uppercase(text: str) -> bool:
    """检测滥用全大写。连续 4 个及以上大写字母且不在缩写白名单里算滥用。"""
    word = ""
    for char in text + " ":
        if char.isalpha():
            word += char
        else:
            if len(word) >= 4 and word.isupper() and word not in _ALLOWED_UPPERCASE:
                return True
            word = ""
    return False


def _has_phone_number(text: str) -> bool:
    """检测像电话号码的数字串（连续数字，或用 - 空格分隔的长数字串）。"""
    digits_run = 0
    for char in text:
        if char.isdigit():
            digits_run += 1
            if digits_run >= _PHONE_LIKE_MIN_DIGITS:
                return True
        elif char in "- ":
            continue  # 分隔符不打断，'400-123-4567' 也要能抓到
        else:
            digits_run = 0
    return False


def check_content_rules(text: str, kind: str) -> list[dict]:
    """检查文案的合规硬规则，返回命中的问题列表。空列表 = 没问题。

    只查**有明确规则**的项。语义层面的问题（夸大宣传、与落地页不符）
    规则查不出来，要靠人和模型判断。
    """
    issues: list[dict] = []

    exclamations = text.count("!") + text.count("！")
    if kind == "headline" and exclamations > MAX_EXCLAMATION_IN_HEADLINE:
        issues.append(
            {
                "rule": "标题不使用感叹号",
                "detail": f"标题里有 {exclamations} 个感叹号，建议去掉。",
                "severity": "warning",
            }
        )

    repeated = _count_repeated_punctuation(text)
    if repeated:
        issues.append(
            {
                "rule": "标点不可连续重复",
                "detail": f"出现连续重复标点：{'、'.join(repeated)}。这会被判为滥用标点。",
                "severity": "error",
            }
        )

    if _has_abusive_uppercase(text):
        issues.append(
            {
                "rule": "不滥用全大写",
                "detail": "出现连续全大写单词（如 SALE、FREE），会被判为滥用大写。",
                "severity": "error",
            }
        )

    if _has_letter_spaced_word(text):
        issues.append(
            {
                "rule": "不逐字母加标点",
                "detail": "出现 'F.L.O.W.E.R.S' 这类写法，会被判为滥用标点。",
                "severity": "error",
            }
        )

    if _has_phone_number(text):
        issues.append(
            {
                "rule": "文案里不写电话号码",
                "detail": "检测到疑似电话号码。电话要用来电附加信息，不能写在文案里。",
                "severity": "error",
            }
        )

    return issues


def validate_asset(text: str, kind: str) -> dict:
    """校验单条素材：字符宽度是否超限 + 内容规则是否命中。

    Args:
        text: 素材文本。
        kind: 'headline'（标题）/ 'description'（描述）/ 'path'（展示路径）。
    """
    if kind not in _ASSET_LIMITS:
        raise ValueError(f"未知素材类型 {kind}，可选：{'、'.join(_ASSET_LIMITS)}")

    limit = _ASSET_LIMITS[kind]
    width = display_width(text.strip())
    issues = check_content_rules(text, kind)
    over_by = max(0, width - limit)

    return {
        "text": text,
        "kind": kind,
        "width_units": width,
        "limit_units": limit,
        "over_by_units": over_by,
        "within_limit": over_by == 0 and bool(text.strip()),
        # 中文按 2 个单位算，这里换算成"还能再写几个汉字"，方便模型调整
        "remaining_cjk_chars": max(0, (limit - width) // 2),
        "content_issues": issues,
        "is_valid": over_by == 0
        and bool(text.strip())
        and not any(i["severity"] == "error" for i in issues),
    }


def _duplicate_texts(texts: Iterable[str]) -> list[str]:
    """找出重复的素材文本（忽略首尾空白）。RSA 里重复标题会被判为无意义重复。"""
    seen: set[str] = set()
    duplicates: list[str] = []
    for text in texts:
        key = text.strip()
        if key in seen and key not in duplicates:
            duplicates.append(key)
        seen.add(key)
    return duplicates


def validate_rsa(
    headlines: Sequence[str],
    descriptions: Sequence[str],
    paths: Sequence[str] | None = None,
) -> dict:
    """整条 RSA 的完整校验：数量、每条素材的字符与合规、重复项、整体感叹号。

    这是提交给 Google Ads API 之前的最后一道关。
    只要 ready_to_submit 为 false，就不要提交——提交也会被拒。
    """
    paths = list(paths or [])
    headline_results = [validate_asset(t, "headline") for t in headlines]
    description_results = [validate_asset(t, "description") for t in descriptions]
    path_results = [validate_asset(t, "path") for t in paths]

    structure_issues: list[str] = []
    if len(headlines) < HEADLINE_MIN_COUNT:
        structure_issues.append(
            f"标题只有 {len(headlines)} 条，至少需要 {HEADLINE_MIN_COUNT} 条。"
        )
    if len(headlines) > HEADLINE_MAX_COUNT:
        structure_issues.append(
            f"标题有 {len(headlines)} 条，超过上限 {HEADLINE_MAX_COUNT} 条。"
        )
    if len(descriptions) < DESCRIPTION_MIN_COUNT:
        structure_issues.append(
            f"描述只有 {len(descriptions)} 条，至少需要 {DESCRIPTION_MIN_COUNT} 条。"
        )
    if len(descriptions) > DESCRIPTION_MAX_COUNT:
        structure_issues.append(
            f"描述有 {len(descriptions)} 条，超过上限 {DESCRIPTION_MAX_COUNT} 条。"
        )
    if len(paths) > 2:
        structure_issues.append(f"展示路径最多 2 段，现在有 {len(paths)} 段。")

    duplicate_headlines = _duplicate_texts(headlines)
    duplicate_descriptions = _duplicate_texts(descriptions)
    if duplicate_headlines:
        structure_issues.append(f"标题有重复：{'、'.join(duplicate_headlines)}。")
    if duplicate_descriptions:
        structure_issues.append(f"描述有重复：{'、'.join(duplicate_descriptions)}。")

    total_exclamations = sum(
        t.count("!") + t.count("！") for t in list(headlines) + list(descriptions)
    )
    if total_exclamations > MAX_EXCLAMATION_TOTAL:
        structure_issues.append(
            f"整条广告有 {total_exclamations} 个感叹号，建议最多 {MAX_EXCLAMATION_TOTAL} 个。"
        )

    all_results = headline_results + description_results + path_results
    invalid = [r for r in all_results if not r["is_valid"]]
    over_limit = [r for r in all_results if r["over_by_units"] > 0]

    warnings: list[str] = []
    if len(headlines) < HEADLINE_RECOMMENDED_COUNT and not structure_issues:
        warnings.append(
            f"标题只有 {len(headlines)} 条。Google 的组合优化需要素材量，"
            f"建议补到 {HEADLINE_RECOMMENDED_COUNT} 条以上。"
        )

    return {
        "headline_count": len(headlines),
        "description_count": len(descriptions),
        "path_count": len(paths),
        "headlines": headline_results,
        "descriptions": description_results,
        "paths": path_results,
        "structure_issues": structure_issues,
        "over_limit_count": len(over_limit),
        "over_limit_texts": [
            {"text": r["text"], "over_by_units": r["over_by_units"], "kind": r["kind"]}
            for r in over_limit
        ],
        "invalid_count": len(invalid),
        "warnings": warnings,
        "ready_to_submit": not structure_issues and not invalid,
    }
