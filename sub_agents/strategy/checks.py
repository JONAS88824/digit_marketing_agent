r"""风控检查：全部是确定性判断，不碰网络、不依赖 ADK、不需要模型。

【为什么这一层要独立出来】
和 metrics.py 的道理一样，只是赌注更大：预算阀门算错一位，就是几千块的差别。
把判断收在这里，就能不联网、不花钱、单独跑测试验证对错。

【这一层能判什么、不能判什么】
能判的是有唯一正确答案的事：数值有没有越界、词表有没有命中、
正负向词有没有自相矛盾、消耗速率有没有超。
判不了的是语义：一句文案算不算"夸大宣传"、一个词和产品搭不搭。
那些留给模型（见 agent.py 的指令），本模块只在返回值里明确标出来。
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Sequence

from ..keywords import metrics as keyword_metrics
from ..performance import metrics as perf_metrics
from ..performance.data import AdsRow
from . import rules
from .schema import AdGroupDraft

# ===== 冷启动熔断阈值 =====
# 【为什么写死在代码里而不是 .env】
# 预算和出价是"每个账号不同"的商业决策，所以可配置；
# 这几条是"什么叫异常"的判断标准，属于方法论，改它应该走代码评审。
COLD_START_DAYS = 2  # 冷启动护航窗口：新广告上线前 48 小时
SPEND_RATE_TRIP_RATIO = 1.5  # 单日消耗 ≥ 日预算的 1.5 倍 → 熔断
SPEND_RATE_WARN_RATIO = 1.1  # ≥ 1.1 倍 → 预警（Google 允许一定超投，但不该持续）
CTR_NEAR_ZERO_PCT = 0.2  # CTR 低于 0.2% 视为"几乎没人点"
MIN_IMPRESSIONS_FOR_CTR = 1000  # 曝光不够时 CTR 没有统计意义，不判
CPC_SPIKE_RATIO = 2.0  # CPC 涨到基线的 2 倍 → 熔断
ZERO_CONVERSION_CPA_MULTIPLE = 3.0  # 花掉 3 倍目标 CPA 仍零转化 → 熔断
ZERO_CONVERSION_BUDGET_MULTIPLE = 2.0  # 没有目标 CPA 时，退回用日预算的倍数判


def _check(
    name: str,
    label: str,
    passed: bool,
    message: str,
    severity: str = "error",
    actual=None,
    limit=None,
) -> dict:
    """统一的检查结果形状。

    每条都带上 actual 和 limit，是为了让模型能说出"超了多少"而不是只说"超了"——
    用户听到「日预算 5000 元，超出上限 300 元的 16 倍」才知道该怎么改。
    """
    return {
        "check": name,
        "label": label,
        "passed": passed,
        "severity": None if passed else severity,
        "actual": actual,
        "limit": limit,
        "message": message,
    }


def _fold(text: str) -> str:
    """为敏感词匹配做的更狠的归一化：全角转半角、去掉空白与分隔符、转小写。

    比 keyword_metrics.normalize 多做两件事，因为这里防的是**刻意规避**：
    "Ｎｏ.１"、"最 佳"、"1 0 0%" 都是绕词表的常见手法。
    关键词归一化不能这么做（词里的空格是有意义的），所以两套不能共用。
    规则表里的词也要过同一个函数，否则 "#1"、"no.1" 这类带符号的词永远匹配不上。
    """
    folded = unicodedata.normalize("NFKC", text).lower()
    return "".join(ch for ch in folded if not ch.isspace() and ch not in "-_·.、")


def _is_ascii_word(word: str) -> bool:
    """规则词是不是纯英文单词。是的话要按词边界匹配，否则会误伤。

    典型误伤：'cure' 会命中 'secure'、'ban' 会命中 'banner'。
    中文没有词边界，只能子串匹配，也不存在这个问题。
    """
    return word.replace(" ", "").isascii() and word.replace(" ", "").isalpha()


def _hits_in_text(text: str) -> list[dict]:
    """扫一段文本命中了哪些敏感词规则，返回命中的规则（可能多条）。"""
    folded = _fold(text)
    normalized = keyword_metrics.normalize(text)
    hits: list[dict] = []
    for rule in rules.SENSITIVE_WORD_RULES:
        word = rule["word"]
        if _is_ascii_word(word):
            # 英文用"两侧不是 ASCII 字母"当边界，而不是 \b。
            # 原因：\b 基于 Unicode \w，CJK 也算 \w，所以 \bcure\b 匹配不了
            # "cure你的病"（cure 和"你"之间没有 \w→非\w 边界）。
            # 改用 ASCII 字母边界后：'secure' 里 cure 前是 e→不匹配（正确），
            # 'cure你的病' 里 cure 前是词首、后是非字母'你'→匹配（正确）。
            matched = (
                re.search(rf"(?<![a-z]){re.escape(word.lower())}(?![a-z])", normalized)
                is not None
            )
        else:
            matched = _fold(word) in folded
        if matched:
            hits.append(rule)
    return hits


def scan_sensitive_words(sections: dict[str, Sequence[str]]) -> dict:
    """扫描各个部位的文本有没有命中敏感词表。

    Args:
        sections: 键是部位名（如 '标题' / '描述' / '关键词'），值是该部位的文本列表。

    返回里 blocking_hits 是必须改的（severity=error），
    warning_hits 是要人来定的（可能有资质、有条款支撑）。
    """
    all_hits: list[dict] = []
    for section, texts in sections.items():
        for text in texts or ():
            for rule in _hits_in_text(text):
                all_hits.append(
                    {
                        "section": section,
                        "text": text,
                        "word": rule["word"],
                        "category": rule["category"],
                        "severity": rule["severity"],
                        "reason": rule["reason"],
                    }
                )

    blocking = [h for h in all_hits if h["severity"] == "error"]
    warnings = [h for h in all_hits if h["severity"] != "error"]
    return {
        "total_hits": len(all_hits),
        "blocking_hits": blocking,
        "warning_hits": warnings,
        "categories_hit": sorted({h["category"] for h in all_hits}),
        "passed": not blocking,
        "not_covered": (
            "词表只能抓字面硬伤。**夸大宣传、与落地页不符、语气过度承诺**"
            "这三类抓不到，必须由你逐条读一遍文案自己判断。"
        ),
    }


def review_guardrails(
    daily_budget: float,
    bidding_strategy: str,
    limits: dict[str, float],
    target_cpa: float | None = None,
    target_roas: float | None = None,
    max_cpc: float | None = None,
    ad_group_max_cpcs: Sequence[tuple[str, float]] = (),
    other_campaigns_daily_budget: float = 0.0,
) -> dict:
    """预算与出价的全部阀门校验。一个入口，返回逐条结果。

    Args:
        daily_budget: 本广告系列的单日预算（元）。
        bidding_strategy: 出价策略名，见 rules.BIDDING_STRATEGIES。
        limits: config.risk_limits() 的返回值。
        ad_group_max_cpcs: [(广告组名, 该组的 max_cpc)]，组级出价也要过同一道阀门。
        other_campaigns_daily_budget: 账户里其它广告系列的日预算合计，
            用来算账户总预算有没有超。不传则只校验单系列。
    """
    checks: list[dict] = []

    # ---- 预算 ----
    checks.append(
        _check(
            "daily_budget_positive",
            "日预算是正数",
            daily_budget > 0,
            f"日预算是 {daily_budget}，必须大于 0。",
            actual=daily_budget,
            limit="> 0",
        )
    )
    cap = limits["max_daily_budget"]
    over = round(daily_budget - cap, 2)
    checks.append(
        _check(
            "daily_budget_cap",
            "日预算硬上限",
            daily_budget <= cap,
            f"日预算 {daily_budget} 元超出上限 {cap} 元（多了 {over} 元）。"
            f"确实要投这么多，请改 .env 的 RISK_MAX_DAILY_BUDGET，不要绕过校验。",
            actual=daily_budget,
            limit=cap,
        )
    )
    account_total = round(daily_budget + max(other_campaigns_daily_budget, 0.0), 2)
    account_cap = limits["max_account_daily_budget"]
    checks.append(
        _check(
            "account_budget_cap",
            "账户日预算合计上限",
            account_total <= account_cap,
            f"加上其它广告系列，账户日预算合计 {account_total} 元，"
            f"超出上限 {account_cap} 元。",
            actual=account_total,
            limit=account_cap,
        )
    )
    # 预算太小同样是问题：建了却买不到量，等于白建一个空系列
    min_viable = round(limits["min_cpc"] * 10, 2)
    checks.append(
        _check(
            "daily_budget_viable",
            "日预算够不够买到量",
            daily_budget >= min_viable,
            f"日预算 {daily_budget} 元，按出价下限 {limits['min_cpc']} 元算"
            f"一天买不到 10 次点击，数据量不足以判断好坏。",
            severity="warning",
            actual=daily_budget,
            limit=f">= {min_viable}",
        )
    )
    return _finish_guardrails(
        checks,
        daily_budget,
        bidding_strategy,
        limits,
        target_cpa,
        target_roas,
        max_cpc,
        ad_group_max_cpcs,
    )


def _range_check(
    name: str, label: str, value: float | None, low: float, high: float, unit: str
) -> dict:
    """出价类阀门都是"落在区间内"的形状，抽出来省得写四遍。

    上下限都要卡：出价过高会竞价失控烧钱，过低则完全没有曝光——
    后者不烧钱但同样是失败，而且更难发现（看起来一切正常，就是没有量）。
    """
    inside = value is not None and low <= value <= high
    if value is None:
        message = f"{label}没填。"
    elif value < low:
        message = f"{label} {value}{unit} 低于下限 {low}{unit}，会几乎没有曝光。"
    elif value > high:
        message = f"{label} {value}{unit} 高于上限 {high}{unit}，有竞价失控风险。"
    else:
        message = f"{label} {value}{unit} 在允许区间 {low}~{high}{unit} 内。"
    return _check(name, label, inside, message, actual=value, limit=f"{low}~{high}{unit}")


def _finish_guardrails(
    checks: list[dict],
    daily_budget: float,
    bidding_strategy: str,
    limits: dict[str, float],
    target_cpa: float | None,
    target_roas: float | None,
    max_cpc: float | None,
    ad_group_max_cpcs: Sequence[tuple[str, float]],
) -> dict:
    """接着 review_guardrails 校验出价部分，然后把所有结论汇总。"""
    spec = rules.BIDDING_STRATEGIES.get(bidding_strategy)
    checks.append(
        _check(
            "bidding_strategy_known",
            "出价策略是否受支持",
            spec is not None,
            f"不认识出价策略 {bidding_strategy!r}。可选："
            f"{'、'.join(rules.BIDDING_STRATEGIES)}。",
            actual=bidding_strategy,
            limit=list(rules.BIDDING_STRATEGIES),
        )
    )

    provided = {"target_cpa": target_cpa, "target_roas": target_roas, "max_cpc": max_cpc}
    if spec is not None:
        # 必填字段有没有填
        for field_name in spec["needs"]:
            checks.append(
                _check(
                    f"bidding_requires_{field_name}",
                    f"{spec['label']} 必须填 {field_name}",
                    provided[field_name] is not None,
                    f"出价策略 {bidding_strategy}（{spec['label']}）必须填 {field_name}，"
                    f"现在是空的。",
                    actual=provided[field_name],
                    limit="必填",
                )
            )
        # 填了但这个策略用不上的字段：不拦，只提醒，否则模型会反复试
        allowed = set(spec["needs"]) | set(spec["optional"])
        for field_name, value in provided.items():
            if value is not None and field_name not in allowed:
                checks.append(
                    _check(
                        f"bidding_ignores_{field_name}",
                        f"{field_name} 在此策略下不生效",
                        False,
                        f"{bidding_strategy} 用不到 {field_name}（填了 {value}），"
                        f"这个值不会生效，建议删掉以免误解。",
                        severity="warning",
                        actual=value,
                    )
                )
        if bidding_strategy == "MAXIMIZE_CONVERSIONS":
            checks.append(
                _check(
                    "maximize_conversions_budget_is_the_only_brake",
                    "自动出价的刹车只有日预算",
                    False,
                    "MAXIMIZE_CONVERSIONS 会把日预算花完为止，没有出价上限可依赖。"
                    "上线后 48 小时必须跟 monitor_new_campaign 盯消耗。",
                    severity="warning",
                    actual=daily_budget,
                )
            )

    # 只校验这个策略真正会用到的出价字段，避免给 tCPA 方案报 max_cpc 的错
    relevant = set(spec["needs"]) | set(spec["optional"]) if spec else set()
    if "max_cpc" in relevant or max_cpc is not None:
        checks.append(
            _range_check(
                "max_cpc_range", "手动出价 max_cpc", max_cpc,
                limits["min_cpc"], limits["max_cpc"], "元",
            )
        )
    if "target_cpa" in relevant or target_cpa is not None:
        checks.append(
            _range_check(
                "target_cpa_range", "目标 CPA", target_cpa,
                limits["min_cpc"], limits["max_target_cpa"], "元",
            )
        )
        if target_cpa is not None and daily_budget > 0 and target_cpa > daily_budget:
            checks.append(
                _check(
                    "target_cpa_vs_budget",
                    "目标 CPA 与日预算是否自相矛盾",
                    False,
                    f"目标 CPA {target_cpa} 元高于日预算 {daily_budget} 元，"
                    f"一天连一次转化都买不起，系统学不到东西。",
                    severity="warning",
                    actual=target_cpa,
                    limit=daily_budget,
                )
            )
    if "target_roas" in relevant or target_roas is not None:
        checks.append(
            _range_check(
                "target_roas_range", "目标 ROAS", target_roas,
                limits["min_target_roas"], limits["max_target_roas"], " 倍",
            )
        )

    # 广告组级出价走同一道阀门——组级出价会覆盖系列级，漏检等于阀门白装
    for group_name, group_cpc in ad_group_max_cpcs:
        result = _range_check(
            f"ad_group_max_cpc:{group_name}",
            f"广告组「{group_name}」的 max_cpc",
            group_cpc,
            limits["min_cpc"],
            limits["max_cpc"],
            "元",
        )
        checks.append(result)

    blocking = [c for c in checks if not c["passed"] and c["severity"] == "error"]
    warnings = [c for c in checks if not c["passed"] and c["severity"] == "warning"]
    return {
        "checks": checks,
        "blocking": blocking,
        "warnings": warnings,
        "passed": not blocking,
        "limits_applied": dict(limits),
    }


def check_logic(
    ad_groups: Sequence[AdGroupDraft],
    account_negative_keywords: Iterable[str] = (),
) -> dict:
    """逻辑自相矛盾校验：正负向词冲突、跨组重复、空组。

    【为什么这类错误必须机器查】
    这些冲突在界面上不报错，广告能正常创建，只是**永远拿不到量**——
    一个词同时是正向和负向，负向优先，等于把它屏蔽了。
    人工核对几十个词的交叉关系几乎必错，模型也数不准，只有代码能算对。

    Args:
        ad_groups: 已解析的广告组列表。
        account_negative_keywords: 账户级/系列级负向词，会作用到所有广告组。
    """
    issues: list[dict] = []
    account_negatives = {keyword_metrics.normalize(k) for k in account_negative_keywords}

    # ---- 组内：同一个词既投放又排除 ----
    for group in ad_groups:
        positives = {keyword_metrics.normalize(k): k for k in group.keywords}
        negatives = {keyword_metrics.normalize(k) for k in group.negative_keywords}
        for key in sorted(positives.keys() & negatives):
            issues.append(
                {
                    "type": "positive_negative_conflict",
                    "severity": "error",
                    "ad_group": group.name,
                    "keyword": positives[key],
                    "detail": (
                        f"「{positives[key]}」同时在投放词和负向词里。"
                        f"负向词优先，这个词实际投不出去。"
                    ),
                }
            )
        # ---- 账户级负向词把本组的投放词屏蔽掉 ----
        for key in sorted(positives.keys() & account_negatives):
            issues.append(
                {
                    "type": "blocked_by_account_negative",
                    "severity": "error",
                    "ad_group": group.name,
                    "keyword": positives[key],
                    "detail": (
                        f"「{positives[key]}」被系列级负向词屏蔽，"
                        f"这个词加了也不会有曝光。"
                    ),
                }
            )
        if not group.keywords:
            issues.append(
                {
                    "type": "empty_ad_group",
                    "severity": "error",
                    "ad_group": group.name,
                    "keyword": None,
                    "detail": "这个广告组没有关键词，建出来是个空壳。",
                }
            )

    # ---- 跨组：同一个词出现在多个组，两个组会互相抢同一次拍卖 ----
    owner: dict[str, str] = {}
    original: dict[str, str] = {}
    for group in ad_groups:
        for keyword in group.keywords:
            key = keyword_metrics.normalize(keyword)
            if key in owner and owner[key] != group.name:
                issues.append(
                    {
                        "type": "cross_group_duplicate",
                        "severity": "warning",
                        "ad_group": group.name,
                        "keyword": keyword,
                        "detail": (
                            f"「{original[key]}」也在广告组「{owner[key]}」里。"
                            f"同账户同词只会有一个进入拍卖，另一个白占预算管理成本。"
                        ),
                    }
                )
            owner.setdefault(key, group.name)
            original.setdefault(key, keyword)

    blocking = [i for i in issues if i["severity"] == "error"]
    return {
        "issues": issues,
        "blocking": blocking,
        "warnings": [i for i in issues if i["severity"] != "error"],
        "passed": not blocking,
        "ad_group_count": len(ad_groups),
        "total_keywords": len(owner),
    }


def _trip(rule: str, severity: str, detail: str, actual=None, limit=None) -> dict:
    """一条熔断/预警记录。severity=critical 才算熔断触发。"""
    return {
        "rule": rule,
        "severity": severity,
        "actual": actual,
        "limit": limit,
        "detail": detail,
    }


def evaluate_cold_start(
    rows: Sequence[AdsRow],
    daily_budget: float,
    target_cpa: float | None = None,
    window_days: int = COLD_START_DAYS,
) -> dict:
    """新广告冷启动护航：判断上线头 48 小时有没有异常，该不该熔断。

    【为什么只看头两天】
    新广告没有历史数据，系统在摸索期，出价和消耗都不稳。
    这段时间烧钱最快、也最容易因为定向或素材填错而白烧，
    过了学习期再看就晚了。

    【返回值里没有任何"已执行"的动作】
    本函数只判断和建议。真要暂停必须走 tools.pause_campaign，
    那个工具挂了人工确认——这是本项目的硬约束：零自动写操作。

    Args:
        rows: 该广告系列的按天数据，通常来自 performance.data.fetch_ads_rows。
        daily_budget: 这个系列的日预算（元），消耗速率以它为分母。
        target_cpa: 目标 CPA（元）。有它才能判"花了多少还零转化"，没有就退回用日预算判。
        window_days: 护航窗口天数，默认 2 天（≈48 小时）。
    """
    rows = tuple(sorted(rows, key=lambda r: r.day))
    if not rows:
        return {
            "status": "no_data",
            "circuit_breaker_tripped": False,
            "severity": "unknown",
            "tripped_rules": [],
            "message": "这个广告系列还没有任何投放数据，可能刚建还没跑起来。",
        }

    days = sorted({r.day for r in rows})
    window_days = max(1, window_days)
    window_start = days[-window_days] if len(days) >= window_days else days[0]
    window = [r for r in rows if r.day >= window_start]
    baseline = [r for r in rows if r.day < window_start]

    window_metrics = perf_metrics.aggregate_ads(window)
    baseline_metrics = perf_metrics.aggregate_ads(baseline) if baseline else None

    per_day = []
    for day in sorted({r.day for r in window}):
        day_rows = [r for r in window if r.day == day]
        day_metrics = perf_metrics.aggregate_ads(day_rows)
        per_day.append(
            {
                "day": day.isoformat(),
                "cost": day_metrics["cost"],
                "spend_ratio": perf_metrics.safe_divide(day_metrics["cost"], daily_budget),
                "impressions": day_metrics["impressions"],
                "clicks": day_metrics["clicks"],
                "ctr_pct": day_metrics["ctr_pct"],
                "cpc": day_metrics["cpc"],
                "conversions": day_metrics["conversions"],
            }
        )

    tripped: list[dict] = []

    # ---- 规则一：单日消耗速率 ----
    worst = max(per_day, key=lambda d: d["spend_ratio"] or 0.0)
    worst_ratio = worst["spend_ratio"] or 0.0
    if daily_budget > 0 and worst_ratio >= SPEND_RATE_TRIP_RATIO:
        tripped.append(
            _trip(
                "spend_rate",
                "critical",
                f"{worst['day']} 消耗 {worst['cost']} 元，是日预算 {daily_budget} 元的"
                f"{round(worst_ratio, 2)} 倍。超投这么多说明预算或定向填错了。",
                actual=round(worst_ratio, 2),
                limit=SPEND_RATE_TRIP_RATIO,
            )
        )
    elif daily_budget > 0 and worst_ratio >= SPEND_RATE_WARN_RATIO:
        tripped.append(
            _trip(
                "spend_rate",
                "warning",
                f"{worst['day']} 消耗是日预算的 {round(worst_ratio, 2)} 倍。"
                f"Google 允许少量超投，但连续几天这样要查原因。",
                actual=round(worst_ratio, 2),
                limit=SPEND_RATE_WARN_RATIO,
            )
        )

    # ---- 规则二：CTR 接近零（曝光够了才判，否则没有统计意义）----
    ctr = window_metrics["ctr_pct"]
    if window_metrics["impressions"] >= MIN_IMPRESSIONS_FOR_CTR and ctr is not None:
        if ctr < CTR_NEAR_ZERO_PCT:
            tripped.append(
                _trip(
                    "ctr_near_zero",
                    "critical",
                    f"窗口内曝光 {window_metrics['impressions']} 次，CTR 只有 {ctr}%，"
                    f"几乎没人点。通常是素材与关键词不匹配，或者投错了人群。",
                    actual=ctr,
                    limit=CTR_NEAR_ZERO_PCT,
                )
            )

    # ---- 规则三：CPC 相对基线飙升 ----
    if baseline_metrics and baseline_metrics["cpc"] and window_metrics["cpc"]:
        spike = window_metrics["cpc"] / baseline_metrics["cpc"]
        if spike >= CPC_SPIKE_RATIO:
            tripped.append(
                _trip(
                    "cpc_spike",
                    "critical",
                    f"CPC 从基线 {baseline_metrics['cpc']} 元涨到 {window_metrics['cpc']} 元"
                    f"（{round(spike, 2)} 倍），竞价可能已经失控。",
                    actual=round(spike, 2),
                    limit=CPC_SPIKE_RATIO,
                )
            )

    # ---- 规则四：花了不少钱但零转化 ----
    if window_metrics["conversions"] == 0 and window_metrics["cost"] > 0:
        if target_cpa:
            threshold = round(target_cpa * ZERO_CONVERSION_CPA_MULTIPLE, 2)
            basis = f"目标 CPA {target_cpa} 元的 {ZERO_CONVERSION_CPA_MULTIPLE} 倍"
        else:
            threshold = round(daily_budget * ZERO_CONVERSION_BUDGET_MULTIPLE, 2)
            basis = f"日预算 {daily_budget} 元的 {ZERO_CONVERSION_BUDGET_MULTIPLE} 倍"
        if window_metrics["cost"] >= threshold:
            tripped.append(
                _trip(
                    "zero_conversion_spend",
                    "critical",
                    f"窗口内花了 {window_metrics['cost']} 元、转化 0 次，"
                    f"已超过{basis}（{threshold} 元）。",
                    actual=window_metrics["cost"],
                    limit=threshold,
                )
            )

    critical = [t for t in tripped if t["severity"] == "critical"]
    severity = "critical" if critical else ("warning" if tripped else "ok")
    return {
        "status": "success",
        "window_days": len({r.day for r in window}),
        "window_start": window_start.isoformat(),
        "daily_budget": daily_budget,
        "window_metrics": window_metrics,
        "baseline_metrics": baseline_metrics,
        "per_day": per_day,
        "tripped_rules": tripped,
        "circuit_breaker_tripped": bool(critical),
        "severity": severity,
        "recommended_action": (
            "建议立即暂停这个广告系列止损。**但暂停不会自动执行**——"
            "把触发的规则原样告诉用户，问清是否暂停，用户同意后再调 pause_campaign，"
            "那一步还会再弹一次确认。"
            if critical
            else (
                "有预警但未达熔断线：继续盯，明天再看一次，先不动账号。"
                if tripped
                else "冷启动表现正常，没有需要处理的异常。"
            )
        ),
    }
