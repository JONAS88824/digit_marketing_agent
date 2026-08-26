"""数据分析 Agent 的工具层：模型能调用的"数据接口"。

这一层负责三件事：
1. 把"最近 7 天"这种人话翻译成具体日期区间；
2. 调 data.py 取数、调 metrics.py 算数；
3. 把结果整理成模型看得懂的 dict（带 status，出错时带 error_message）。

【为什么用"最近 N 天"而不是让模型传日期】
大模型算日期很容易错（算错月末、忘记闰年）。
所以工具只接收 days 这种相对天数，具体日期由 Python 算，模型不碰日期。
"""

from __future__ import annotations

from datetime import date, timedelta

from google.adk.tools import ToolContext

from ... import config
from ...session_state import remember
from . import data, metrics

# 单次查询允许的最大天数，防止模型一次拉光全部数据
MAX_DAYS = data.HISTORY_DAYS

# 对比 Ads 时关注的指标（顺序即汇报顺序）
_ADS_COMPARE_KEYS = ("ctr_pct", "cpc", "cvr_pct", "cpa", "cost", "conversions")

# 对比 GA4 时关注的指标
_GA4_COMPARE_KEYS = ("sessions", "cvr_pct", "conversions", "revenue")

# 可以看逐日趋势的指标
_TREND_METRICS = ("ctr", "cpc", "cvr", "clicks", "cost", "conversions", "impressions")


def _window(days: int, offset_days: int = 0) -> tuple[date, date]:
    """算出一个日期窗口（含首尾）。

    Args:
        days: 窗口长度（天）。
        offset_days: 往前平移多少天。0 表示"最近 days 天"，
            传 days 表示"再往前推一个同样长度的窗口"（用于环比）。

    数据只到昨天为止（今天的数据通常还没结算），所以窗口从昨天往前算。
    """
    end = date.today() - timedelta(days=1 + offset_days)
    start = end - timedelta(days=days - 1)
    return start, end


def _clamp_days(days: int) -> int:
    """把天数限制在 1..MAX_DAYS，防止 0 天或超出数据范围。"""
    return max(1, min(int(days), MAX_DAYS))


def _safe_fetch(fetch, *args) -> tuple[tuple, dict | None]:
    """取数，并把数据源故障翻译成模型能读懂的错误字典。

    返回 (数据行, 错误字典)。错误字典为 None 表示取数成功。
    真实 API 缺库/缺凭证时会抛 DataSourceNotReady，
    这里拦下来变成一句人话，而不是让整个对话崩掉。
    """
    try:
        return fetch(*args), None
    except data.DataSourceNotReady as exc:
        return (), {"status": "error", "error_message": str(exc)}


def _validate_campaign(campaign: str | None) -> dict | None:
    """广告系列名不认识就返回错误字典，并告诉模型有哪些可选。"""
    if campaign and campaign not in data.CAMPAIGNS:
        return {
            "status": "error",
            "error_message": (
                f"没有名为 {campaign} 的广告系列。"
                f"可用广告系列：{'、'.join(data.CAMPAIGNS)}。"
            ),
        }
    return None


def _validate_channel(channel: str | None) -> dict | None:
    """渠道名不认识就返回错误字典，并告诉模型有哪些可选。"""
    if channel and channel not in data.GA4_CHANNELS:
        return {
            "status": "error",
            "error_message": (
                f"没有名为 {channel} 的流量渠道。"
                f"可用渠道：{'、'.join(data.GA4_CHANNELS)}。"
            ),
        }
    return None


def list_data_sources() -> dict:
    """查询当前能分析哪些广告系列、哪些流量渠道，以及数据覆盖的日期范围。

    开始任何分析之前先调用本工具，确认名称写法和可用时间范围，
    不要凭猜测填广告系列名。

    注意：本工具不需要任何参数。
    """
    earliest, latest = data.data_date_range()
    ads_mode = "live" if config.is_live(config.SOURCE_ADS) else "mock"
    ga4_mode = "live" if config.is_live(config.SOURCE_GA4) else "mock"
    return {
        "status": "success",
        "google_ads_campaigns": list(data.CAMPAIGNS),
        "ga4_channels": list(data.GA4_CHANNELS),
        "data_from": earliest.isoformat(),
        "data_to": latest.isoformat(),
        "google_ads_mode": ads_mode,
        "ga4_mode": ga4_mode,
        "note": (
            "数据到昨天为止，今天的数据尚未结算。"
            "mode 为 mock 表示这是内置演示数据，不是真实投放数据，"
            "汇报时必须向用户说明这一点。"
        ),
    }


def get_ads_metrics(
    days: int = 7, campaign: str | None = None, tool_context: ToolContext = None
) -> dict:
    """查询 Google Ads 最近 N 天的表现：曝光、点击、花费、转化，以及 CTR、CPC、转化率、单次转化成本。

    Args:
        days: 往前看多少天，默认 7 天，最多 90 天。
        campaign: 广告系列名称。不填则统计全部广告系列的合计。
    """
    error = _validate_campaign(campaign)
    if error:
        return error

    days = _clamp_days(days)
    start, end = _window(days)
    rows, fetch_error = _safe_fetch(data.fetch_ads_rows, start, end, campaign)
    if fetch_error:
        return fetch_error
    if not rows:
        return {
            "status": "error",
            "error_message": f"{start} 到 {end} 区间没有 Google Ads 数据。",
        }

    remember(tool_context, current_campaign=campaign, current_days=days)
    return {
        "status": "success",
        "source": "google_ads",
        "campaign": campaign or "全部广告系列",
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "metrics": metrics.aggregate_ads(rows),
        "metric_units": {
            "ctr_pct": "百分比（点击数/曝光数）",
            "cvr_pct": "百分比（转化数/点击数）",
            "cpc": "元/次点击",
            "cpa": "元/次转化",
            "cost": "元",
        },
    }


def compare_ads_metrics(
    window_days: int = 7, campaign: str | None = None, tool_context: ToolContext = None
) -> dict:
    """对比 Google Ads 本期与上期的表现变化（环比），找出 CTR、CPC、转化率哪些指标明显恶化。

    例如 window_days=7 表示拿"最近 7 天"和"再往前 7 天"做对比。
    变化超过 15% 才算显著；attention_metrics 里列出的是明显变差的指标，要重点解释原因。

    Args:
        window_days: 每个对比窗口的长度（天），默认 7 天。
        campaign: 广告系列名称。不填则对比全部广告系列的合计。
    """
    error = _validate_campaign(campaign)
    if error:
        return error

    window_days = _clamp_days(window_days)
    current_start, current_end = _window(window_days)
    previous_start, previous_end = _window(window_days, offset_days=window_days)

    current_rows, fetch_error = _safe_fetch(
        data.fetch_ads_rows, current_start, current_end, campaign
    )
    if fetch_error:
        return fetch_error
    previous_rows, fetch_error = _safe_fetch(
        data.fetch_ads_rows, previous_start, previous_end, campaign
    )
    if fetch_error:
        return fetch_error
    if not current_rows or not previous_rows:
        return {
            "status": "error",
            "error_message": (
                f"数据不足，无法做 {window_days} 天环比对比，请缩短 window_days 后重试。"
            ),
        }

    current = metrics.aggregate_ads(current_rows)
    previous = metrics.aggregate_ads(previous_rows)
    result = metrics.compare_aggregates(current, previous, _ADS_COMPARE_KEYS)

    remember(tool_context, current_campaign=campaign, current_days=window_days)
    return {
        "status": "success",
        "source": "google_ads",
        "campaign": campaign or "全部广告系列",
        "current_period": f"{current_start} ~ {current_end}",
        "previous_period": f"{previous_start} ~ {previous_end}",
        "current_metrics": current,
        "previous_metrics": previous,
        "comparisons": result["comparisons"],
        "attention_metrics": result["attention_metrics"],
        "hint": (
            "verdict 含义：improved 变好、worsened 变差、stable 波动不显著、"
            "changed 有变化但好坏要结合预算判断。"
            "attention_metrics 为空说明本期没有明显恶化的指标。"
        ),
    }


def get_ga4_metrics(
    days: int = 7, channel: str | None = None, tool_context: ToolContext = None
) -> dict:
    """查询 GA4 最近 N 天的站内表现：会话数、用户数、转化数、收入，以及会话转化率和客单价。

    Args:
        days: 往前看多少天，默认 7 天，最多 90 天。
        channel: 流量渠道名称，如 'Paid Search'。不填则统计全部渠道合计。
    """
    error = _validate_channel(channel)
    if error:
        return error

    days = _clamp_days(days)
    start, end = _window(days)
    rows, fetch_error = _safe_fetch(data.fetch_ga4_rows, start, end, channel)
    if fetch_error:
        return fetch_error
    if not rows:
        return {
            "status": "error",
            "error_message": f"{start} 到 {end} 区间没有 GA4 数据。",
        }

    remember(tool_context, current_channel=channel, current_days=days)
    return {
        "status": "success",
        "source": "ga4",
        "channel": channel or "全部渠道",
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "metrics": metrics.aggregate_ga4(rows),
        "metric_units": {
            "cvr_pct": "百分比（转化数/会话数）",
            "aov": "元/单（客单价）",
            "revenue": "元",
        },
    }


def compare_ga4_metrics(
    window_days: int = 7, channel: str | None = None, tool_context: ToolContext = None
) -> dict:
    """对比 GA4 本期与上期的站内表现变化（环比），看会话数和转化率是升还是降。

    用于区分问题出在"广告端"还是"站内"：
    如果 Ads 的点击没减少、但 GA4 的会话数掉了，说明落地页或跳转链路有问题。

    Args:
        window_days: 每个对比窗口的长度（天），默认 7 天。
        channel: 流量渠道名称。不填则对比全部渠道合计。
    """
    error = _validate_channel(channel)
    if error:
        return error

    window_days = _clamp_days(window_days)
    current_start, current_end = _window(window_days)
    previous_start, previous_end = _window(window_days, offset_days=window_days)

    current_rows, fetch_error = _safe_fetch(
        data.fetch_ga4_rows, current_start, current_end, channel
    )
    if fetch_error:
        return fetch_error
    previous_rows, fetch_error = _safe_fetch(
        data.fetch_ga4_rows, previous_start, previous_end, channel
    )
    if fetch_error:
        return fetch_error
    if not current_rows or not previous_rows:
        return {
            "status": "error",
            "error_message": f"数据不足，无法做 {window_days} 天环比对比。",
        }

    current = metrics.aggregate_ga4(current_rows)
    previous = metrics.aggregate_ga4(previous_rows)
    result = metrics.compare_aggregates(current, previous, _GA4_COMPARE_KEYS)

    remember(tool_context, current_channel=channel, current_days=window_days)
    return {
        "status": "success",
        "source": "ga4",
        "channel": channel or "全部渠道",
        "current_period": f"{current_start} ~ {current_end}",
        "previous_period": f"{previous_start} ~ {previous_end}",
        "current_metrics": current,
        "previous_metrics": previous,
        "comparisons": result["comparisons"],
        "attention_metrics": result["attention_metrics"],
    }


def get_daily_trend(
    metric: str = "cpc",
    days: int = 14,
    campaign: str | None = None,
    tool_context: ToolContext = None,
) -> dict:
    """查询某个 Google Ads 指标的逐日数值，用来定位"变化是从哪天开始的"。

    环比只能告诉你"变差了"，逐日趋势才能告诉你"哪天开始变差"，
    从而对上那天做过的改动（调了出价、换了素材、对手加了预算）。

    Args:
        metric: 要看的指标，可选 ctr、cpc、cvr、clicks、cost、conversions、impressions。
        days: 往前看多少天，默认 14 天，最多 90 天。
        campaign: 广告系列名称。不填则看全部广告系列合计。
    """
    if metric not in _TREND_METRICS:
        return {
            "status": "error",
            "error_message": f"不支持的指标 {metric}。可选：{'、'.join(_TREND_METRICS)}。",
        }
    error = _validate_campaign(campaign)
    if error:
        return error

    days = _clamp_days(days)
    start, end = _window(days)
    rows, fetch_error = _safe_fetch(data.fetch_ads_rows, start, end, campaign)
    if fetch_error:
        return fetch_error
    if not rows:
        return {
            "status": "error",
            "error_message": f"{start} 到 {end} 区间没有 Google Ads 数据。",
        }

    # 先按天分组，同一天的多个广告系列要先加总再算派生指标，不能逐行平均
    by_day: dict[date, list[data.AdsRow]] = {}
    for row in rows:
        by_day.setdefault(row.day, []).append(row)

    # 原始指标直接取，派生指标（ctr/cvr）取百分比字段
    field = {
        "ctr": "ctr_pct",
        "cvr": "cvr_pct",
        "cpc": "cpc",
    }.get(metric, metric)

    series = [
        {"day": day.isoformat(), "value": metrics.aggregate_ads(by_day[day])[field]}
        for day in sorted(by_day)
    ]

    remember(tool_context, current_campaign=campaign, current_metric=metric)
    return {
        "status": "success",
        "source": "google_ads",
        "metric": metric,
        "unit": "百分比" if metric in ("ctr", "cvr") else "原始数值",
        "campaign": campaign or "全部广告系列",
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "series": series,
        "hint": "在序列里找拐点：从哪一天起数值明显偏离了前面的水平。",
    }


def get_current_context(tool_context: ToolContext) -> dict:
    """查询当前对话正在分析的对象：广告系列、渠道、时间窗口、指标。

    当用户用了省略说法（如"那上周呢"、"换成展示看看"）而没有重复说明分析对象时，
    调用本工具从会话记忆里找回上一轮的分析对象。

    注意：本工具不需要任何参数。
    """
    state = tool_context.state if tool_context else {}
    return {
        "status": "success",
        "current_campaign": state.get("current_campaign"),
        "current_channel": state.get("current_channel"),
        "current_days": state.get("current_days"),
        "current_metric": state.get("current_metric"),
        "hint": "如果用户说的是刚才分析的对象，沿用这里的值继续分析。",
    }


def check_data_source_config() -> dict:
    """检查 Google Ads 与 GA4 的接入配置：模式是 mock 还是 live、哪些凭证还没填。

    当用户问"为什么还是演示数据""我还缺什么凭证""接真实数据要配什么"时调用本工具。

    出于安全，本工具只返回配置项的名字和"是否已填"，
    绝不会返回凭证的内容。

    注意：本工具不需要任何参数。
    """
    report = config.describe()
    report["status"] = "success"
    report["how_to_fix"] = (
        "编辑 digital_marketing_agent/.env，填上 missing_keys 里列出的项，"
        "并把 DATA_SOURCE_MODE 改成 live；"
        "若 missing_package 不为空，还要先 pip install 对应的库。"
    )
    return report
