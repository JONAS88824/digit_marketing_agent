"""关键词数据源（当前是 mock 数据）。

覆盖四个来源，每个来源都留了真实 API 接缝：
1. Google Ads Keyword Planner —— 关键词创意、搜索量趋势、CPC 区间
2. 第三方竞品情报 —— 竞品在投的词（厂商中立接口）
3. Google Search Console —— 自然搜索词库
4. GA4 —— 实际带来转化的搜索词

【mock 数据怎么造出来的】
不是随手编一堆词，而是按"词根 × 修饰词"组合生成，每个修饰词带用户意图标签。
意图决定这个词的搜索量、CPC 和转化倾向——就像真实市场里那样：
"跑鞋怎么选"搜的人多但不买，"跑鞋官方旗舰店"搜的人少但转化高。
这样大模型做语义聚类、长尾拓展、负向词筛选时才有真实的素材可练。
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

# 生成多少个月的搜索量趋势
TREND_MONTHS = 12

_SEED = 20260826


@dataclass(frozen=True)
class MonthlyVolume:
    """某个月的搜索量。对应 Keyword Planner 的 MonthlySearchVolume。"""

    year: int
    month: int
    searches: int


@dataclass(frozen=True)
class KeywordIdea:
    """一个关键词创意及其指标。

    字段对齐 Google Ads v25 的 KeywordPlanHistoricalMetrics，
    区别是这里把 micros 都换算成了元（真实 API 返回的是百万分之一单位）。
    """

    text: str
    intent: str  # transactional / commercial / informational / navigational / negative_signal
    core: str  # 词根，即这个词属于哪个产品
    avg_monthly_searches: int
    competition: str  # LOW / MEDIUM / HIGH
    competition_index: int  # 0-100
    avg_cpc: float  # 元
    low_top_of_page_bid: float  # 元，首页展示出价区间下限
    high_top_of_page_bid: float  # 元，区间上限
    monthly_volumes: tuple[MonthlyVolume, ...]


@dataclass(frozen=True)
class CompetitorKeyword:
    """竞品在投的一个词。第三方情报工具给的通常就是这种粒度。"""

    competitor: str
    text: str
    estimated_position: float  # 估算平均排名，1.0 最好
    visibility_pct: float  # 该词上竞品的曝光占有率
    estimated_cpc: float  # 元


@dataclass(frozen=True)
class SeoQuery:
    """Search Console 的一条自然搜索词记录。字段对齐 searchanalytics.query 的返回。"""

    query: str
    clicks: int
    impressions: int
    ctr_pct: float
    position: float  # 平均排名


@dataclass(frozen=True)
class ConvertingSearchTerm:
    """GA4 里实际带来转化的搜索词。"""

    term: str
    sessions: int
    conversions: int
    revenue: float


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


# ===== 取数入口（mock / live 分流）=====


class KeywordSourceNotReady(RuntimeError):
    """真实关键词 API 该用却用不了时抛出（缺库、缺凭证、接入未完成）。

    和 data.py 的 DataSourceNotReady 同一个思路：宁可明确报错，
    也不能把演示数据当成真实的市场数据交出去——关键词规划一旦用错数据，
    错的是整个季度的预算分配。
    """


def _blocker(source: str) -> str:
    """拼出"这个源现在为什么不能用 + 还差几步"的说明。"""
    from . import config

    steps = config.remaining_work(source)
    return f"{source} 现在还取不到真实数据。待办：" + "；".join(
        f"({i}) {step}" for i, step in enumerate(steps, 1)
    )


def _is_live(source: str) -> bool:
    from . import config

    return config.is_live(source) and config.FETCH_IMPLEMENTED[source]


def fetch_keyword_ideas(
    industry: str | None = None,
    product: str | None = None,
    intents: Sequence[str] | None = None,
) -> tuple[KeywordIdea, ...]:
    """按行业 / 产品筛出关键词创意及其搜索量、CPC、竞争度与 12 个月趋势。"""
    from . import config

    if _is_live(config.SOURCE_KEYWORD_PLANNER):
        return _fetch_keyword_ideas_live(industry, product, intents)

    cores = INDUSTRY_CORES.get(industry, ()) if industry else ()
    return tuple(
        idea
        for idea in KEYWORD_UNIVERSE
        if (not cores or idea.core in cores)
        and (product is None or product in idea.text)
        and (intents is None or idea.intent in intents)
    )


def _fetch_keyword_ideas_live(
    industry: str | None, product: str | None, intents: Sequence[str] | None
) -> tuple[KeywordIdea, ...]:
    """从真实 Keyword Planner 取关键词创意。【待实现：只差这个函数体】

    依赖库 google-ads 已安装。以下字段名对照已安装的 v25 版本核对过：

    1. 建客户端同 data.py 的 Ads 部分（developer_token + OAuth + use_proto_plus=True）
    2. 调用：
           service = client.get_service("KeywordPlanIdeaService")
           request = client.get_type("GenerateKeywordIdeasRequest")
           request.customer_id = os.environ["GOOGLE_ADS_CUSTOMER_ID"]
           request.language = "languageConstants/1018"      # 1018 = 简体中文
           request.geo_target_constants = ["geoTargetConstants/2156"]   # 2156 = 中国
           request.keyword_seed.keywords.extend([product or industry])
           response = service.generate_keyword_ideas(request=request)
    3. 每个 result 有 text 和 keyword_idea_metrics，后者的字段是：
           avg_monthly_searches          月均搜索量
           competition / competition_index  竞争档位(LOW/MEDIUM/HIGH) 与 0-100 指数
           average_cpc_micros            平均 CPC
           low_top_of_page_bid_micros    首页出价区间下限
           high_top_of_page_bid_micros   首页出价区间上限
           monthly_search_volumes        逐月搜索量，元素含 year / month / monthly_searches
    4. 三个坑：
       - 所有 micros 字段除以 1_000_000 才是元
       - competition 是枚举，要用 .name 取字符串
       - intent（用户意图）**API 不提供**，得靠大模型判断，
         或用本文件的修饰词规则近似标注

    另外两个同服务的方法，将来可能用得上：
       generate_keyword_historical_metrics()  已知词查历史指标
       generate_keyword_forecast_metrics()    按出价预测点击/花费（要先搭 forecast campaign）

    实现完成后把 config.py 的 FETCH_IMPLEMENTED[SOURCE_KEYWORD_PLANNER] 改成 True。
    """
    from . import config

    raise KeywordSourceNotReady(_blocker(config.SOURCE_KEYWORD_PLANNER))


def fetch_competitor_keywords(competitor: str | None = None) -> tuple[CompetitorKeyword, ...]:
    """取竞品在投的关键词。不指定竞品则返回全部竞品。"""
    from . import config

    if _is_live(config.SOURCE_COMPETITOR):
        return _fetch_competitor_keywords_live(competitor)
    return tuple(
        row
        for row in COMPETITOR_KEYWORDS
        if competitor is None or row.competitor == competitor
    )


def _fetch_competitor_keywords_live(competitor: str | None) -> tuple[CompetitorKeyword, ...]:
    """从第三方情报接口取竞品投放词。【待实现：只差这个函数体】

    竞品投放词 Google 官方不提供——Ads API 只能看你自己的账户。
    所以只能买第三方数据（SEMrush / Ahrefs / SpyFu / DataForSEO 等）。

    实现方式（刻意不绑定厂商）：
        import httpx
        resp = httpx.get(
            f"{os.environ['COMPETITOR_INTEL_BASE_URL']}/paid-keywords",
            params={"domain": competitor},
            headers={"Authorization": f"Bearer {os.environ['COMPETITOR_INTEL_API_KEY']}"},
            timeout=30,
        )
        resp.raise_for_status()
        把每条转成 CompetitorKeyword 返回

    要提醒使用者的两件事：
    1. 第三方数据是**估算**，不是竞品账户的真实数据。位置和 CPC 都有误差，
       只能用来判断方向（它在抢哪类词），不能当精确数字用。
    2. 这类接口普遍按调用次数计费，别在循环里逐词查。
    """
    from . import config

    raise KeywordSourceNotReady(_blocker(config.SOURCE_COMPETITOR))


def fetch_seo_queries(limit: int = 200) -> tuple[SeoQuery, ...]:
    """取 Search Console 的自然搜索词，按点击量从高到低。"""
    from . import config

    if _is_live(config.SOURCE_SEARCH_CONSOLE):
        return _fetch_seo_queries_live(limit)
    ordered = sorted(SEO_QUERIES, key=lambda row: -row.clicks)
    return tuple(ordered[:limit])


def _fetch_seo_queries_live(limit: int) -> tuple[SeoQuery, ...]:
    """从真实 Search Console 取自然搜索词。【待实现：只差这个函数体】

    依赖库 google-api-python-client 已安装。以下已对照官方文档核对：

    1. 建客户端（service 名是 searchconsole / v1，不是旧的 webmasters / v3）：
           from googleapiclient.discovery import build
           from google.oauth2 import service_account
           creds = service_account.Credentials.from_service_account_file(
               os.environ["SEARCH_CONSOLE_CREDENTIALS_JSON_PATH"],
               scopes=["https://www.googleapis.com/auth/webmasters.readonly"],
           )
           service = build("searchconsole", "v1", credentials=creds)
    2. 查数据：
           service.searchanalytics().query(
               siteUrl=os.environ["SEARCH_CONSOLE_SITE_URL"],
               body={
                   "startDate": "...", "endDate": "...",   # YYYY-MM-DD，太平洋时间
                   "dimensions": ["query"],
                   "rowLimit": min(limit, 25000),
                   "startRow": 0,
               },
           ).execute()
       返回的每行有 keys（维度值）和 clicks / impressions / ctr / position。
    3. 四个必须知道的坑：
       - **ctr 是 0~1 的小数，不是百分比**，要 ×100 才对得上 SeoQuery.ctr_pct
       - rowLimit 上限 25000（默认只有 1000），更多数据要用 startRow 翻页
       - 数据有 2~3 天延迟，最近几天是预备数据还会变；
         想拿最新数据要传 dataState: "all"，并检查 metadata.first_incomplete_date
       - **匿名化查询**：搜索量太少的词 Google 会隐去词本身以保护隐私。
         所以把所有 query 行的点击加起来，永远小于站点总点击——
         这不是翻页没翻完，是拿不到，翻页也补不回来。关键词研究的完整性到此为止。
    4. 服务账号能不能用于 Search Console，官方文档并未说明。社区做法是把服务账号
       邮箱加为站点用户，但未经官方确认——真接的时候要留验证时间，
       必要时改用普通 OAuth 用户授权流程。

    实现完成后把 config.py 的 FETCH_IMPLEMENTED[SOURCE_SEARCH_CONSOLE] 改成 True。
    """
    from . import config

    raise KeywordSourceNotReady(_blocker(config.SOURCE_SEARCH_CONSOLE))


def fetch_converting_terms(limit: int = 200) -> tuple[ConvertingSearchTerm, ...]:
    """取 GA4 里实际带来转化的搜索词，按转化数从高到低。"""
    from . import config

    if _is_live(config.SOURCE_GA4) and config.FETCH_IMPLEMENTED[config.SOURCE_GA4]:
        return _fetch_converting_terms_live(limit)
    ordered = sorted(CONVERTING_TERMS, key=lambda row: -row.conversions)
    return tuple(ordered[:limit])


def _fetch_converting_terms_live(limit: int) -> tuple[ConvertingSearchTerm, ...]:
    """从真实 GA4 取带来转化的搜索词。【待实现：只差这个函数体】

    维度和指标名已对照 GA4 Data API v1beta 的官方 schema 核对：

    1. 客户端同 data.py 的 GA4 部分（显式传 service_account 凭证）
    2. 维度选哪个，取决于你要看的是"哪种搜索词"：
           sessionGoogleAdsKeyword  带来这次会话的 Google Ads 关键词（你出价的词）
           sessionGoogleAdsQuery    带来这次会话的**用户真实搜索词**（更接近意图）
           searchTerm               用户在**你自己站内**搜索框输入的词
                                    （来自 search_term 事件参数，仅事件级，没有会话级版本）
           sessionManualTerm        来自 utm_term 的手动标记词
       **GA4 没有任何自然搜索关键词维度**——自然搜索的词只能从 Search Console 拿，
       这也是为什么本项目要同时接这两个源。
    3. 指标要用新名字。**`conversions` 已废弃**，2024-05 起改名：
           conversions          →  keyEvents
           sessionConversionRate →  sessionKeyEventRate
           isConversionEvent    →  isKeyEvent（维度）
       收入用 totalRevenue（含订阅与广告收入）或 purchaseRevenue（只算购买）。
    4. 四个坑：
       - keyEvents 是**所有关键事件的合计**，不是某一个转化。
         要针对单个转化，得加 eventName 维度 + dimensionFilter，
         或改用 sessionKeyEventRate:<事件名>（该事件必须已登记为关键事件，否则请求失败）
       - 没打通 Google Ads 关联或没开自动标记时，Ads 维度会大量返回 (not set)
       - **阈值过滤**：用户数太少的搜索词行会被整行隐去（看 subjectToThresholding）
       - **高基数**：关键词是典型的高基数维度，长尾行会被并进 (other)，
         要检查 dataLossFromOtherRow
    5. 拿不准维度和指标能不能组合时，先调 properties.checkCompatibility 验证，
       组合不兼容的请求会直接失败。

    实现完成后把 config.py 的 FETCH_IMPLEMENTED[SOURCE_GA4] 改成 True。
    """
    from . import config

    raise KeywordSourceNotReady(_blocker(config.SOURCE_GA4))
