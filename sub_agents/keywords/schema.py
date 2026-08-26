"""关键词数据的形状定义。

【为什么单独一个文件】
这些 dataclass 是**契约**：mock 数据按它生成，真实 API 也要转成它。
两边共用同一套形状，所以谁都不该独占它——单独放，双方都 import。
将来把 mock.py 整个删掉，本文件和 data.py 照样成立。

字段命名对齐各家 API 的原始字段，只把 micros 这类单位换算成了元。
"""

from __future__ import annotations

from dataclasses import dataclass


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
