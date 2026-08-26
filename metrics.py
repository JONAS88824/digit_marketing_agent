"""纯计算层：把原始指标聚合成 CTR / CPC / 转化率，并做区间对比。

【为什么单独一个文件】
数字计算必须精确，不能交给大模型口算。所以"算"的部分全部放这里，
用 Python 算好、算准，再把结论交给模型去"解读"。
本文件不依赖 ADK，也不碰任何 API，因此可以单独跑测试验证。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .data import AdsRow, Ga4Row

# 变化超过这个百分比，才认为"值得关注"，否则算正常波动
SIGNIFICANT_CHANGE_PCT = 15.0

# 每个指标"涨"意味着好还是坏。
# 花费(cost)标成 neutral：预算主动加投时上涨是正常的，不能一律判为变差。
_DIRECTION = {
    "impressions": "higher_better",
    "clicks": "higher_better",
    "conversions": "higher_better",
    "sessions": "higher_better",
    "users": "higher_better",
    "revenue": "higher_better",
    "ctr": "higher_better",
    "cvr": "higher_better",
    "cpc": "lower_better",
    "cpa": "lower_better",
    "cost": "neutral",
}


def safe_divide(numerator: float, denominator: float) -> float | None:
    """除法。分母为 0 时返回 None，而不是抛异常或返回 0。

    返回 None 是有意的：0 次点击时"CPC 等于 0"是错的说法，
    正确说法是"没有点击，算不出 CPC"。
    """
    if not denominator:
        return None
    return numerator / denominator


def _pct(value: float | None) -> float | None:
    """把 0.0412 这样的比率转成 4.12（百分比数值），便于人和模型阅读。"""
    return None if value is None else round(value * 100, 2)


def _round2(value: float | None) -> float | None:
    return None if value is None else round(value, 2)


def aggregate_ads(rows: Iterable[AdsRow]) -> dict:
    """把多行 Ads 数据加总，并算出 CTR / CPC / 转化率 / 单次转化成本。

    重要：CTR 必须"先加总再相除"（总点击/总曝光），
    不能把每天的 CTR 求平均——那样小流量的日子会被过度放大。
    """
    rows = tuple(rows)
    impressions = sum(r.impressions for r in rows)
    clicks = sum(r.clicks for r in rows)
    cost = round(sum(r.cost for r in rows), 2)
    conversions = sum(r.conversions for r in rows)
    return {
        "days": len({r.day for r in rows}),
        "impressions": impressions,
        "clicks": clicks,
        "cost": cost,
        "conversions": conversions,
        "ctr_pct": _pct(safe_divide(clicks, impressions)),
        "cpc": _round2(safe_divide(cost, clicks)),
        "cvr_pct": _pct(safe_divide(conversions, clicks)),
        "cpa": _round2(safe_divide(cost, conversions)),
    }


def aggregate_ga4(rows: Iterable[Ga4Row]) -> dict:
    """把多行 GA4 数据加总，并算出会话转化率与客单价。"""
    rows = tuple(rows)
    sessions = sum(r.sessions for r in rows)
    users = sum(r.users for r in rows)
    conversions = sum(r.conversions for r in rows)
    revenue = round(sum(r.revenue for r in rows), 2)
    return {
        "days": len({r.day for r in rows}),
        "sessions": sessions,
        "users": users,
        "conversions": conversions,
        "revenue": revenue,
        "cvr_pct": _pct(safe_divide(conversions, sessions)),
        "aov": _round2(safe_divide(revenue, conversions)),
    }



def _base_metric_name(key: str) -> str:
    """把 'ctr_pct' 这类字段名还原成 'ctr'，用于查涨跌方向。"""
    for suffix in ("_pct",):
        if key.endswith(suffix):
            return key[: -len(suffix)]
    return key


def compare_metric(name: str, current: float | None, previous: float | None) -> dict:
    """对比单个指标的本期与上期，给出变化幅度和"变好/变差"判断。"""
    metric = _base_metric_name(name)
    direction = _DIRECTION.get(metric, "neutral")

    if current is None or previous is None:
        return {
            "metric": name,
            "current": current,
            "previous": previous,
            "change_pct": None,
            "verdict": "unknown",
            "needs_attention": False,
            "note": "本期或上期缺少可计算的数据（例如没有点击），无法对比。",
        }

    change_pct = safe_divide(current - previous, abs(previous))
    change_pct = None if change_pct is None else round(change_pct * 100, 2)

    if change_pct is None:
        verdict = "unknown"
    elif abs(change_pct) < SIGNIFICANT_CHANGE_PCT:
        verdict = "stable"
    elif direction == "neutral":
        verdict = "changed"
    elif (change_pct > 0) == (direction == "higher_better"):
        verdict = "improved"
    else:
        verdict = "worsened"

    return {
        "metric": name,
        "current": current,
        "previous": previous,
        "change_pct": change_pct,
        "verdict": verdict,
        # 只有"明显变差"才提请关注，避免把好消息也报成警告
        "needs_attention": verdict == "worsened",
    }


def compare_aggregates(
    current: dict, previous: dict, metric_keys: Sequence[str]
) -> dict:
    """对比两个聚合结果里的一组指标，返回逐指标对比 + 需要关注的清单。"""
    comparisons = [
        compare_metric(key, current.get(key), previous.get(key)) for key in metric_keys
    ]
    return {
        "comparisons": comparisons,
        "attention_metrics": [c["metric"] for c in comparisons if c["needs_attention"]],
    }
