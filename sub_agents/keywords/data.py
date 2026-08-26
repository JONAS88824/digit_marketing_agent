"""关键词取数入口：mock / live 分流 + 四个真实 API 的接缝。

覆盖四个来源，每个都留了真实 API 接缝：
1. Google Ads Keyword Planner —— 关键词创意、搜索量趋势、CPC 区间
2. 第三方竞品情报 —— 竞品在投的词（厂商中立接口）
3. Google Search Console —— 自然搜索词库
4. GA4 —— 实际带来转化的搜索词

【设计要点：数据源接缝】
fetch_* 是唯一的取数入口，它们按 .env 里的 DATA_SOURCE_MODE 决定
走演示数据还是真实 API。真实接入时只需要填 _fetch_*_live 的函数体，
返回 schema.py 定义的同样形状，上层 metrics.py 和 tools.py 一行都不用动。

三个文件的分工：schema.py 定形状，mock.py 造演示数据，本文件管"从哪儿取"。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from . import mock
from .schema import (
    CompetitorKeyword,
    ConvertingSearchTerm,
    KeywordIdea,
    MonthlyVolume,
    SeoQuery,
)

# 转出给上层用，省得 tools.py 同时 import 三个模块
INDUSTRY_CORES = mock.INDUSTRY_CORES
CORE_TO_INDUSTRY = mock.CORE_TO_INDUSTRY
KEYWORD_UNIVERSE = mock.KEYWORD_UNIVERSE
NEGATIVE_KEYWORD_RULES = mock.NEGATIVE_KEYWORD_RULES
COMPETITOR_KEYWORDS = mock.COMPETITOR_KEYWORDS
COMPETITORS = mock.COMPETITORS
SEO_QUERIES = mock.SEO_QUERIES
CONVERTING_TERMS = mock.CONVERTING_TERMS
TREND_MONTHS = mock.TREND_MONTHS


class KeywordSourceNotReady(RuntimeError):
    """真实关键词 API 该用却用不了时抛出（缺库、缺凭证、接入未完成）。

    和 data.py 的 DataSourceNotReady 同一个思路：宁可明确报错，
    也不能把演示数据当成真实的市场数据交出去——关键词规划一旦用错数据，
    错的是整个季度的预算分配。
    """


def _blocker(source: str) -> str:
    """拼出"这个源现在为什么不能用 + 还差几步"的说明。"""
    from ... import config

    steps = config.remaining_work(source)
    return f"{source} 现在还取不到真实数据。待办：" + "；".join(
        f"({i}) {step}" for i, step in enumerate(steps, 1)
    )


def _is_live(source: str) -> bool:
    from ... import config

    return config.is_live(source) and config.FETCH_IMPLEMENTED[source]


def fetch_keyword_ideas(
    industry: str | None = None,
    product: str | None = None,
    intents: Sequence[str] | None = None,
) -> tuple[KeywordIdea, ...]:
    """按行业 / 产品筛出关键词创意及其搜索量、CPC、竞争度与 12 个月趋势。"""
    from ... import config

    if _is_live(config.SOURCE_KEYWORD_PLANNER):
        return _fetch_keyword_ideas_live(industry, product, intents)

    cores = mock.INDUSTRY_CORES.get(industry, ()) if industry else ()
    return tuple(
        idea
        for idea in mock.KEYWORD_UNIVERSE
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
    from ... import config

    raise KeywordSourceNotReady(_blocker(config.SOURCE_KEYWORD_PLANNER))


def fetch_competitor_keywords(competitor: str | None = None) -> tuple[CompetitorKeyword, ...]:
    """取竞品在投的关键词。不指定竞品则返回全部竞品。"""
    from ... import config

    if _is_live(config.SOURCE_COMPETITOR):
        return _fetch_competitor_keywords_live(competitor)
    return tuple(
        row
        for row in mock.COMPETITOR_KEYWORDS
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
    from ... import config

    raise KeywordSourceNotReady(_blocker(config.SOURCE_COMPETITOR))


def fetch_seo_queries(limit: int = 200) -> tuple[SeoQuery, ...]:
    """取 Search Console 的自然搜索词，按点击量从高到低。"""
    from ... import config

    if _is_live(config.SOURCE_SEARCH_CONSOLE):
        return _fetch_seo_queries_live(limit)
    ordered = sorted(mock.SEO_QUERIES, key=lambda row: -row.clicks)
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
    from ... import config

    raise KeywordSourceNotReady(_blocker(config.SOURCE_SEARCH_CONSOLE))


def fetch_converting_terms(limit: int = 200) -> tuple[ConvertingSearchTerm, ...]:
    """取 GA4 里实际带来转化的搜索词，按转化数从高到低。"""
    from ... import config

    if _is_live(config.SOURCE_GA4) and config.FETCH_IMPLEMENTED[config.SOURCE_GA4]:
        return _fetch_converting_terms_live(limit)
    ordered = sorted(mock.CONVERTING_TERMS, key=lambda row: -row.conversions)
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
    from ... import config

    raise KeywordSourceNotReady(_blocker(config.SOURCE_GA4))
