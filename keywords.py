"""关键词的纯计算层：能算准的部分全在这里，不劳烦大模型。

【职责划分——这是本文件存在的理由】
关键词规划里有两类活：
- **确定性的活**：切词根、去重、算趋势涨跌、匹配负向词规则、算跨来源重叠、
  预估点击与花费。这些有唯一正确答案，交给 Python。
- **语义判断的活**：这批词该怎么聚类、哪些长尾值得拓展、"平价跑鞋"算不算
  目标客群。这些没有唯一答案，交给大模型。

本文件只做第一类。不依赖 ADK、不碰网络，所以能单独跑测试验证。
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from .keywords_data import KeywordIdea, MonthlyVolume

# 趋势变化超过这个百分比，才认为是真的在涨/在跌，否则算正常波动
SIGNIFICANT_TREND_PCT = 20.0

# 趋势对比用的窗口：最近 N 个月 vs 之前 N 个月
TREND_WINDOW_MONTHS = 3

# 预估广告点击率。**这是假设值，不是 API 给的数据。**
# 真实点击率取决于排名、素材质量和竞争程度，这里只按竞争档位给一个粗略档次，
# 所以任何基于它的花费预估都必须标注"预估"，不能当成承诺。
ASSUMED_AD_CTR_BY_COMPETITION = {"LOW": 0.055, "MEDIUM": 0.038, "HIGH": 0.024}


def normalize(text: str) -> str:
    """统一关键词写法：去掉首尾空白、压缩内部空格、英文转小写。

    不做的事：不删中间的空格（"nike 跑鞋"和"nike跑鞋"在搜索里是两个词），
    不做同义词合并（那是语义判断，归模型管）。
    """
    return " ".join(text.split()).lower()


def dedupe(keywords: Iterable[str]) -> list[str]:
    """按归一化结果去重，保留第一次出现的原始写法和顺序。"""
    seen: set[str] = set()
    result: list[str] = []
    for keyword in keywords:
        key = normalize(keyword)
        if key and key not in seen:
            seen.add(key)
            result.append(keyword)
    return result


def find_root(text: str, cores: Sequence[str]) -> str | None:
    """从关键词里切出词根（即它讲的是哪个产品）。

    命中多个时取最长的那个：'婴儿推车' 比 '推车' 更具体，应该优先。
    一个都没命中就返回 None——这类词要单独拿给模型看，
    往往是拼写变体、竞品品牌词，或者压根不相关的词。
    """
    matched = [core for core in cores if core in text]
    return max(matched, key=len) if matched else None


def group_by_root(
    ideas: Iterable[KeywordIdea], cores: Sequence[str]
) -> dict[str, list[KeywordIdea]]:
    """按词根把关键词分组。这是给模型做语义聚类的**原料**，不是最终聚类结果。

    词根分组只能做到"字面上带同一个产品词"，
    做不到"这三个词其实是同一种用户需求"——后者要模型来判断。
    """
    groups: dict[str, list[KeywordIdea]] = {}
    for idea in ideas:
        root = find_root(idea.text, cores) or "未识别词根"
        groups.setdefault(root, []).append(idea)
    return groups


def match_negative_rules(text: str, rules: Iterable[dict]) -> list[dict]:
    """检查关键词是否命中负向词规则，返回命中的规则列表（可能命中多条）。"""
    normalized = normalize(text)
    return [rule for rule in rules if rule["word"] in normalized]


def _average(values: Sequence[int]) -> float | None:
    return sum(values) / len(values) if values else None


def summarize_trend(volumes: Sequence[MonthlyVolume]) -> dict:
    """把 12 个月的搜索量序列压成一句结论：在涨还是在跌、旺季是哪个月。

    对比方式是"最近 3 个月的均值 vs 之前 3 个月的均值"，
    不用单月对比——单月波动太大，容易把噪声当趋势。
    """
    if len(volumes) < TREND_WINDOW_MONTHS * 2:
        return {
            "direction": "unknown",
            "change_pct": None,
            "note": f"趋势对比至少需要 {TREND_WINDOW_MONTHS * 2} 个月数据。",
        }

    recent = [v.searches for v in volumes[-TREND_WINDOW_MONTHS:]]
    earlier = [v.searches for v in volumes[-TREND_WINDOW_MONTHS * 2 : -TREND_WINDOW_MONTHS]]
    recent_avg, earlier_avg = _average(recent), _average(earlier)

    change_pct = (
        round((recent_avg - earlier_avg) / earlier_avg * 100, 2) if earlier_avg else None
    )
    if change_pct is None:
        direction = "unknown"
    elif abs(change_pct) < SIGNIFICANT_TREND_PCT:
        direction = "flat"
    else:
        direction = "rising" if change_pct > 0 else "falling"

    peak = max(volumes, key=lambda v: v.searches)
    trough = min(volumes, key=lambda v: v.searches)
    return {
        "direction": direction,
        "change_pct": change_pct,
        "recent_avg": round(recent_avg) if recent_avg else None,
        "earlier_avg": round(earlier_avg) if earlier_avg else None,
        "peak_month": f"{peak.year}-{peak.month:02d}",
        "peak_searches": peak.searches,
        "trough_month": f"{trough.year}-{trough.month:02d}",
        "trough_searches": trough.searches,
        "seasonality_ratio": round(peak.searches / trough.searches, 2)
        if trough.searches
        else None,
    }


def estimate_cost(ideas: Iterable[KeywordIdea], share_of_voice: float = 1.0) -> dict:
    """预估这批词投出去大概能拿多少点击、要花多少钱。

    **这是预估，不是承诺。** 依赖两个假设，都会写进返回值让模型如实转达：
    1. 点击率按竞争档位取经验值（见 ASSUMED_AD_CTR_BY_COMPETITION）
    2. 单次点击价格取 Keyword Planner 给的平均 CPC

    Args:
        ideas: 要投的关键词。
        share_of_voice: 预期拿到的曝光占有率，1.0 表示该词的搜索全都能看到你的广告。
            预算有限时应该调低（比如 0.3），否则会高估点击量。
    """
    ideas = tuple(ideas)
    share = min(max(share_of_voice, 0.0), 1.0)

    total_searches = 0
    total_clicks = 0.0
    total_cost = 0.0
    for idea in ideas:
        ctr = ASSUMED_AD_CTR_BY_COMPETITION.get(idea.competition, 0.03)
        clicks = idea.avg_monthly_searches * share * ctr
        total_searches += idea.avg_monthly_searches
        total_clicks += clicks
        total_cost += clicks * idea.avg_cpc

    clicks_rounded = round(total_clicks)
    return {
        "keyword_count": len(ideas),
        "monthly_searches": total_searches,
        "share_of_voice": share,
        "estimated_monthly_clicks": clicks_rounded,
        "estimated_monthly_cost": round(total_cost, 2),
        "estimated_avg_cpc": round(total_cost / total_clicks, 2) if total_clicks else None,
        "assumptions": {
            "ctr_by_competition": ASSUMED_AD_CTR_BY_COMPETITION,
            "cpc_source": "Keyword Planner 给出的该词平均 CPC",
            "warning": (
                "点击率是按竞争档位取的经验假设值，不是你账户的真实数据。"
                "汇报时必须说明这是预估区间，实际结果取决于排名、素材和竞争变化。"
            ),
        },
    }


def compare_sets(mine: Iterable[str], theirs: Iterable[str]) -> dict:
    """对比两批关键词，算出重叠、只有我有、只有它有。

    用于三种场景：
    - 我 vs 竞品：只有它有的词 = 机会缺口
    - 我 vs SEO 词库：自然排名好但没投付费的词 = 可能白花钱，也可能值得防守
    - 我 vs GA4 转化词：真实转化过但没投的词 = 最值得优先补的词
    """
    mine_map = {normalize(k): k for k in mine if normalize(k)}
    theirs_map = {normalize(k): k for k in theirs if normalize(k)}
    mine_keys, theirs_keys = set(mine_map), set(theirs_map)

    return {
        "mine_count": len(mine_keys),
        "theirs_count": len(theirs_keys),
        "overlap": sorted(mine_map[k] for k in mine_keys & theirs_keys),
        "only_mine": sorted(mine_map[k] for k in mine_keys - theirs_keys),
        "only_theirs": sorted(theirs_map[k] for k in theirs_keys - mine_keys),
        "overlap_pct": round(len(mine_keys & theirs_keys) / len(mine_keys) * 100, 2)
        if mine_keys
        else None,
    }
