"""演示词库的生成规则与数据。

【mock 数据怎么造出来的】
不是随手编一堆词，而是按"词根 × 修饰词"组合生成，每个修饰词带用户意图标签。
意图决定这个词的搜索量、CPC 和转化倾向——就像真实市场里那样：
"跑鞋怎么选"搜的人多但不买，"跑鞋官方旗舰店"搜的人少但转化高。
这样大模型做语义聚类、长尾拓展、负向词筛选时才有真实的素材可练。

【为什么和 data.py 分开】
本文件是"假数据的内容"，data.py 是"取数的入口"。
真实 API 接上之后 data.py 要一直留着，而本文件可以整个删掉——
删除边界清晰，这就是分开的价值。

数据按"今天"往前推，所以任何时候运行都有最近的数据；
随机种子固定，每次运行结果一致，方便复现问题。
"""

from __future__ import annotations

import random
from datetime import date

from .schema import (
    CompetitorKeyword,
    ConvertingSearchTerm,
    KeywordIdea,
    MonthlyVolume,
    SeoQuery,
)

# 生成多少个月的搜索量趋势
TREND_MONTHS = 12

_SEED = 20260826


# ===== 关键词宇宙的生成规则 =====

# 每个行业的核心产品词（词根）。真实场景里这些来自你自己的商品目录。
INDUSTRY_CORES = {
    "运动户外": ("跑鞋", "冲锋衣", "登山包", "瑜伽垫"),
    "美妆个护": ("精华液", "面膜", "防晒霜", "洗发水"),
    "数码家电": ("蓝牙耳机", "扫地机器人", "空气净化器", "投影仪"),
    "母婴用品": ("纸尿裤", "奶瓶", "婴儿推车", "辅食机"),
}

# 修饰词按用户意图分组。第二个数字是搜索量倍数——
# 信息类的词搜的人多，交易类的词搜的人少但值钱。
_MODIFIERS = {
    "transactional": (("价格", 0.9), ("多少钱", 0.7), ("官方旗舰店", 0.5), ("优惠券", 0.6), ("包邮", 0.4)),
    "commercial": (("推荐", 1.4), ("哪个好", 1.1), ("排行榜", 0.9), ("测评", 0.7), ("对比", 0.5)),
    "informational": (("怎么选", 1.8), ("怎么保养", 1.0), ("尺码表", 0.8), ("是什么", 0.6)),
    "navigational": (("官网", 0.7), ("旗舰店", 0.5)),
    "negative_signal": (("免费", 1.0), ("二手", 0.8), ("维修", 0.6), ("招聘", 0.3), ("图片", 0.9)),
}

# 各意图的经济画像：CPC 倍数、转化倾向、竞争强度基准
_INTENT_PROFILE = {
    "transactional": {"cpc": 1.00, "cvr": 1.00, "competition": 82},
    "commercial": {"cpc": 0.70, "cvr": 0.55, "competition": 64},
    "informational": {"cpc": 0.35, "cvr": 0.12, "competition": 31},
    "navigational": {"cpc": 0.50, "cvr": 0.90, "competition": 45},
    "negative_signal": {"cpc": 0.30, "cvr": 0.02, "competition": 18},
}

# 每个词根的基准月搜索量与基准 CPC（元）
_CORE_BASE = {
    "跑鞋": (74000, 3.20), "冲锋衣": (41000, 2.80), "登山包": (18000, 2.10), "瑜伽垫": (26000, 1.60),
    "精华液": (68000, 4.50), "面膜": (95000, 2.40), "防晒霜": (72000, 3.10), "洗发水": (58000, 1.90),
    "蓝牙耳机": (120000, 2.70), "扫地机器人": (54000, 5.80), "空气净化器": (33000, 4.90), "投影仪": (61000, 4.20),
    "纸尿裤": (49000, 2.30), "奶瓶": (37000, 1.80), "婴儿推车": (44000, 3.60), "辅食机": (15000, 2.90),
}

# 月度季节性系数：11 月双11、6 月618 是电商大促，交易类词会明显冲高
_SEASONALITY = {
    1: 0.88, 2: 0.76, 3: 0.95, 4: 1.00, 5: 1.06, 6: 1.34,
    7: 0.98, 8: 0.94, 9: 1.02, 10: 1.10, 11: 1.62, 12: 1.14,
}


def _competition_label(index: int) -> str:
    """把 0-100 的竞争指数转成 Keyword Planner 的三档标签。"""
    if index >= 67:
        return "HIGH"
    if index >= 34:
        return "MEDIUM"
    return "LOW"


def _recent_months(count: int) -> list[tuple[int, int]]:
    """返回最近 count 个月的 (年, 月)，从最早到最近。"""
    today = date.today()
    months: list[tuple[int, int]] = []
    year, month = today.year, today.month
    for _ in range(count):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        months.append((year, month))
    return list(reversed(months))


def _build_keyword_universe() -> tuple[KeywordIdea, ...]:
    rng = random.Random(_SEED)
    months = _recent_months(TREND_MONTHS)
    ideas: list[KeywordIdea] = []

    for cores in INDUSTRY_CORES.values():
        for core in cores:
            base_volume, base_cpc = _CORE_BASE[core]

            # 词根本身也是一个词（头部大词）：量远超任何长尾词，竞争也最激烈
            candidates: list[tuple[str, str, float]] = [(core, "commercial", 2.8)]
            for intent, modifiers in _MODIFIERS.items():
                for suffix, volume_ratio in modifiers:
                    candidates.append((f"{core}{suffix}", intent, volume_ratio))

            for text, intent, volume_ratio in candidates:
                profile = _INTENT_PROFILE[intent]
                jitter = 1 + rng.uniform(-0.18, 0.18)
                volume = max(30, int(base_volume * volume_ratio * jitter * 0.42))
                cpc = round(base_cpc * profile["cpc"] * (1 + rng.uniform(-0.12, 0.12)), 2)
                index = min(100, max(1, int(profile["competition"] * (1 + rng.uniform(-0.15, 0.15)))))

                # 竞争越激烈，首页出价区间越宽、上限越高
                spread = 0.35 + index / 100 * 0.9
                ideas.append(
                    KeywordIdea(
                        text=text,
                        intent=intent,
                        core=core,
                        avg_monthly_searches=volume,
                        competition=_competition_label(index),
                        competition_index=index,
                        avg_cpc=cpc,
                        low_top_of_page_bid=round(cpc * 0.72, 2),
                        high_top_of_page_bid=round(cpc * (1 + spread), 2),
                        monthly_volumes=tuple(
                            MonthlyVolume(
                                year=year,
                                month=month,
                                searches=max(
                                    10,
                                    int(
                                        volume
                                        # 交易类词吃满大促季节性，信息类词几乎不受影响
                                        * (1 + (_SEASONALITY[month] - 1) * profile["cvr"])
                                        * (1 + rng.uniform(-0.08, 0.08))
                                    ),
                                ),
                            )
                            for year, month in months
                        ),
                    )
                )
    return tuple(ideas)


KEYWORD_UNIVERSE = _build_keyword_universe()

# 词根 → 所属行业，反查用
CORE_TO_INDUSTRY = {
    core: industry for industry, cores in INDUSTRY_CORES.items() for core in cores
}


# ===== 负向词规则库 =====
# 这是"确定能判"的那部分：命中即可判定，不需要大模型思考。
# 语义模糊的词（比如"平价跑鞋"到底算不算目标客群）才交给模型判断。
NEGATIVE_KEYWORD_RULES = (
    {"word": "免费", "category": "无购买意图", "reason": "找免费资源的人不会付费购买"},
    {"word": "破解", "category": "无购买意图", "reason": "寻找盗版/破解，非目标客群"},
    {"word": "二手", "category": "渠道不符", "reason": "我们只卖新品，二手需求转化不了"},
    {"word": "维修", "category": "售后需求", "reason": "售后咨询应走客服，不该消耗投放预算"},
    {"word": "招聘", "category": "求职意图", "reason": "求职者不是买家"},
    {"word": "图片", "category": "找素材", "reason": "找图片素材的流量几乎不转化"},
    {"word": "自制", "category": "DIY 意图", "reason": "想自己做的人不会买成品"},
    {"word": "批发", "category": "客群不符", "reason": "面向零售，批发询价不适配"},
)


def _build_competitor_keywords() -> tuple[CompetitorKeyword, ...]:
    """造竞品投放词。竞品只投有商业价值的词，不会投负向词。"""
    rng = random.Random(_SEED + 7)
    competitors = ("竞品A-悦动运动", "竞品B-山野户外", "竞品C-轻蜂数码")
    worth_bidding = [
        idea
        for idea in KEYWORD_UNIVERSE
        if idea.intent in ("transactional", "commercial", "navigational")
    ]
    rows: list[CompetitorKeyword] = []
    for competitor in competitors:
        # 每个竞品只投其中一部分词，这样才会出现"我投了它没投"的差集
        picked = rng.sample(worth_bidding, k=len(worth_bidding) // 4)
        for idea in picked:
            rows.append(
                CompetitorKeyword(
                    competitor=competitor,
                    text=idea.text,
                    estimated_position=round(rng.uniform(1.1, 4.6), 1),
                    visibility_pct=round(rng.uniform(4.0, 38.0), 1),
                    estimated_cpc=round(idea.avg_cpc * (1 + rng.uniform(-0.15, 0.25)), 2),
                )
            )
    return tuple(rows)


def _build_seo_queries() -> tuple[SeoQuery, ...]:
    """造 Search Console 自然搜索词。

    自然流量的分布和付费很不一样：信息类词占大头（内容能排上去），
    交易类词排名靠后（首页被广告和大站占了）。
    """
    rng = random.Random(_SEED + 13)
    rows: list[SeoQuery] = []
    for idea in KEYWORD_UNIVERSE:
        # 自然搜索里，信息类词更容易拿到曝光
        exposure = {"informational": 0.55, "commercial": 0.32, "navigational": 0.22}.get(
            idea.intent, 0.10
        )
        impressions = int(idea.avg_monthly_searches * exposure * rng.uniform(0.7, 1.3))
        if impressions < 40:
            continue
        position = round(
            rng.uniform(1.5, 8.0) if idea.intent == "informational" else rng.uniform(6.0, 28.0),
            1,
        )
        # 排名越靠前点击率越高，这是搜索结果页的普遍规律
        ctr = max(0.004, 0.31 / position) * rng.uniform(0.75, 1.25)
        clicks = max(1, int(impressions * ctr))
        rows.append(
            SeoQuery(
                query=idea.text,
                clicks=clicks,
                impressions=impressions,
                ctr_pct=round(clicks / impressions * 100, 2),
                position=position,
            )
        )
    return tuple(rows)


def _build_converting_terms() -> tuple[ConvertingSearchTerm, ...]:
    """造 GA4 里实际带来转化的搜索词。

    这是四个数据源里最有价值的一个：前三个都是"预估/机会"，
    只有它是"已经发生的事实"——真金白银换来的转化记录。
    所以关键词规划应该以它为锚，而不是只看搜索量。
    """
    rng = random.Random(_SEED + 23)
    rows: list[ConvertingSearchTerm] = []
    for idea in KEYWORD_UNIVERSE:
        profile = _INTENT_PROFILE[idea.intent]
        # 只有一小部分搜索会点进我们的站
        sessions = int(idea.avg_monthly_searches * 0.012 * rng.uniform(0.6, 1.4))
        if sessions < 12:
            continue
        # 转化率跟着意图走：交易意图的词转化好，信息类的词几乎不转化
        cvr = 0.052 * profile["cvr"] * rng.uniform(0.7, 1.3)
        conversions = round(sessions * cvr)
        if conversions == 0:
            continue
        rows.append(
            ConvertingSearchTerm(
                term=idea.text,
                sessions=sessions,
                conversions=conversions,
                revenue=round(conversions * rng.uniform(180, 420), 2),
            )
        )
    return tuple(rows)


COMPETITOR_KEYWORDS = _build_competitor_keywords()
SEO_QUERIES = _build_seo_queries()
CONVERTING_TERMS = _build_converting_terms()

COMPETITORS = tuple(sorted({row.competitor for row in COMPETITOR_KEYWORDS}))
