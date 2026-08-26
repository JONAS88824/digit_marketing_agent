"""Google Ads / GA4 的数据源（当前是 mock 数据）。

【设计要点：数据源接缝】
fetch_ads_rows / fetch_ga4_rows 是唯一的取数入口，
它们根据 .env 里的 DATA_SOURCE_MODE 决定走假数据还是真实 API。
真实接入时只需要填好 _fetch_ads_rows_live / _fetch_ga4_rows_live 的函数体，
让它们返回同样结构的 AdsRow / Ga4Row，上层 metrics.py 和 tools.py 一行都不用动。

数据按"今天"往前推 90 天生成，所以任何时候运行都有最近的数据。
其中最近 7 天给"春季新品-搜索"埋了一段异常（CPC 上涨、CTR 下滑），
用来验证 agent 能不能自己把变化找出来。
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from . import config

# 生成多少天的历史数据
HISTORY_DAYS = 90

# 固定随机种子：每次运行数据都一样，方便复现问题
_SEED = 20260826

# 埋异常的广告系列与天数
ANOMALY_CAMPAIGN = "春季新品-搜索"
ANOMALY_DAYS = 7


@dataclass(frozen=True)
class AdsRow:
    """Google Ads 里"某一天 + 某个广告系列"的原始指标。

    只放 API 直接给的原始数字（曝光/点击/花费/转化），
    CTR、CPC、转化率这些是算出来的，不存在这里——算的活交给 metrics.py。
    """

    day: date
    campaign: str
    impressions: int
    clicks: int
    cost: float  # 单位：元
    conversions: int


@dataclass(frozen=True)
class Ga4Row:
    """GA4 里"某一天 + 某个流量渠道"的原始指标。"""

    day: date
    channel: str
    sessions: int
    users: int
    conversions: int
    revenue: float  # 单位：元


# 每个广告系列的基准表现（真实场景里这些数字来自 API）
_ADS_BASE = {
    "春季新品-搜索": {"impressions": 52000, "ctr": 0.041, "cpc": 2.60, "cvr": 0.032},
    "品牌词-搜索": {"impressions": 18000, "ctr": 0.115, "cpc": 1.10, "cvr": 0.081},
    "再营销-展示": {"impressions": 210000, "ctr": 0.006, "cpc": 0.70, "cvr": 0.011},
}

# 每个 GA4 渠道的基准表现
_GA4_BASE = {
    "Paid Search": {"sessions": 9800, "cvr": 0.028, "aov": 210.0},
    "Organic Search": {"sessions": 14200, "cvr": 0.021, "aov": 198.0},
    "Direct": {"sessions": 6100, "cvr": 0.035, "aov": 245.0},
    "Social": {"sessions": 4300, "cvr": 0.012, "aov": 165.0},
}

CAMPAIGNS = tuple(_ADS_BASE)
GA4_CHANNELS = tuple(_GA4_BASE)


def _jitter(rng: random.Random, pct: float) -> float:
    """生成一个 1 附近的随机波动系数，模拟真实数据的每日抖动。"""
    return 1 + rng.uniform(-pct, pct)


def _build_ads_rows() -> tuple[AdsRow, ...]:
    rng = random.Random(_SEED)
    today = date.today()
    rows: list[AdsRow] = []
    # offset=HISTORY_DAYS 是最早那天，offset=1 是昨天（今天数据通常还没跑完，不生成）
    for offset in range(HISTORY_DAYS, 0, -1):
        day = today - timedelta(days=offset)
        in_anomaly_window = offset <= ANOMALY_DAYS
        for campaign, base in _ADS_BASE.items():
            impressions = int(base["impressions"] * _jitter(rng, 0.10))
            ctr = base["ctr"] * _jitter(rng, 0.08)
            cpc = base["cpc"] * _jitter(rng, 0.08)
            cvr = base["cvr"] * _jitter(rng, 0.12)
            if in_anomaly_window and campaign == ANOMALY_CAMPAIGN:
                cpc *= 1.45  # 竞争加剧，点击成本上涨
                ctr *= 0.78  # 素材疲劳，点击率下滑
                cvr *= 0.85  # 落地页转化同步走低
            clicks = max(1, round(impressions * ctr))
            rows.append(
                AdsRow(
                    day=day,
                    campaign=campaign,
                    impressions=impressions,
                    clicks=clicks,
                    cost=round(clicks * cpc, 2),
                    conversions=round(clicks * cvr),
                )
            )
    return tuple(rows)


def _build_ga4_rows() -> tuple[Ga4Row, ...]:
    rng = random.Random(_SEED + 1)
    today = date.today()
    rows: list[Ga4Row] = []
    for offset in range(HISTORY_DAYS, 0, -1):
        day = today - timedelta(days=offset)
        in_anomaly_window = offset <= ANOMALY_DAYS
        for channel, base in _GA4_BASE.items():
            sessions = int(base["sessions"] * _jitter(rng, 0.12))
            cvr = base["cvr"] * _jitter(rng, 0.15)
            if in_anomaly_window and channel == "Paid Search":
                # 与 Ads 端的异常呼应：付费流量变少、转化变差
                sessions = int(sessions * 0.82)
                cvr *= 0.85
            conversions = round(sessions * cvr)
            rows.append(
                Ga4Row(
                    day=day,
                    channel=channel,
                    sessions=sessions,
                    users=round(sessions * 0.78),
                    conversions=conversions,
                    revenue=round(conversions * base["aov"] * _jitter(rng, 0.10), 2),
                )
            )
    return tuple(rows)


# 模块加载时一次性生成，之后只读
ADS_ROWS = _build_ads_rows()
GA4_ROWS = _build_ga4_rows()


class DataSourceNotReady(RuntimeError):
    """真实 API 该用但用不了时抛出（缺库、缺凭证、接入未完成）。

    故意抛异常而不是悄悄退回假数据：拿假数据当真实投放数据汇报，
    比直接报错危险得多。
    """


def _live_blocker(source: str) -> str | None:
    """检查真实 API 能不能用。能用返回 None，不能用就返回一句给人看的原因。

    只报第一个拦路的问题，并附上完整的待办清单，
    这样用户一眼能看到"现在卡在哪"和"总共还差几步"。
    """
    steps = config.remaining_work(source)
    if config.is_live(source) and config.FETCH_IMPLEMENTED[source]:
        return None
    return f"{source} 现在还取不到真实数据。待办：" + "；".join(
        f"({i}) {step}" for i, step in enumerate(steps, 1)
    )


def _fetch_ads_rows_mock(
    start: date, end: date, campaign: str | None
) -> tuple[AdsRow, ...]:
    return tuple(
        row
        for row in ADS_ROWS
        if start <= row.day <= end and (campaign is None or row.campaign == campaign)
    )


def _fetch_ga4_rows_mock(
    start: date, end: date, channel: str | None
) -> tuple[Ga4Row, ...]:
    return tuple(
        row
        for row in GA4_ROWS
        if start <= row.day <= end and (channel is None or row.channel == channel)
    )


def _fetch_ads_rows_live(
    start: date, end: date, campaign: str | None
) -> tuple[AdsRow, ...]:
    """从真实 Google Ads API 取数。【待实现：只差这个函数体】

    依赖库 google-ads 已安装。以下步骤已对照库源码核对：

    1. 建客户端（键名来自 google.ads.googleads.config 的 _REQUIRED_KEYS 等）：
           client = GoogleAdsClient.load_from_dict({
               "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
               "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
               "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
               "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
               "use_proto_plus": True,          # 库强制要求，不填会报错
               # 经理账号(MCC)访问子账号时再加：
               # "login_customer_id": os.environ["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
           })
    2. 查数据（customer_id 是调用参数，不是客户端配置）：
           service = client.get_service("GoogleAdsService")
           service.search_stream(
               customer_id=os.environ["GOOGLE_ADS_CUSTOMER_ID"],
               query=gaql,
           )
       GAQL 语句：
           SELECT campaign.name, segments.date, metrics.impressions,
                  metrics.clicks, metrics.cost_micros, metrics.conversions
           FROM campaign
           WHERE segments.date BETWEEN '<start>' AND '<end>'
    3. 逐行转成 AdsRow，注意三个坑：
       - cost_micros 要除以 1_000_000 才是元
       - conversions 是浮点数，要 round() 成整数
       - customer_id 必须是 10 位纯数字，带横线会报错

    实现完成后，把 config.py 里 FETCH_IMPLEMENTED[SOURCE_ADS] 改成 True。
    """
    raise DataSourceNotReady(_live_blocker(config.SOURCE_ADS))


def _fetch_ga4_rows_live(
    start: date, end: date, channel: str | None
) -> tuple[Ga4Row, ...]:
    """从真实 GA4 Data API 取数。【待实现：只差这个函数体】

    依赖库 google-analytics-data 已安装。GA4 取数只需要两样东西
    （已核对官方 quickstart 与库的 from_service_account_file 方法）：
    ① GA4_PROPERTY_ID  ② GA4_CREDENTIALS_JSON_PATH（服务账号密钥文件）

    1. 建客户端时把密钥路径显式传进去，不要依赖全局的
       GOOGLE_APPLICATION_CREDENTIALS 环境变量——那个变量会影响进程里
       所有 Google 客户端，将来若把 ADK 切到 Vertex 模式会互相干扰：
           from google.oauth2 import service_account
           creds = service_account.Credentials.from_service_account_file(
               os.environ["GA4_CREDENTIALS_JSON_PATH"]
           )
           client = BetaAnalyticsDataClient(credentials=creds)
    2. 查数据（property 要拼成 properties/<纯数字 ID>）：
           client.run_report(RunReportRequest(
               property=f"properties/{os.environ['GA4_PROPERTY_ID']}",
               dimensions=[Dimension(name="date"),
                           Dimension(name="sessionDefaultChannelGroup")],
               metrics=[Metric(name="sessions"), Metric(name="totalUsers"),
                        Metric(name="keyEvents"), Metric(name="totalRevenue")],
               date_ranges=[DateRange(start_date=..., end_date=...)],
           ))
    3. 逐行转成 Ga4Row，注意四个坑：
       - 返回值全是字符串，要自己转 int / float
       - 服务账号必须在 GA4 后台加为"查看者"，否则报 403 而不是空数据
       - **指标名 `conversions` 已废弃**（2024-05 起改名 `keyEvents`），
         同批改名的还有 sessionConversionRate → sessionKeyEventRate。
         旧名字暂时还能调，但已进入弃用期，新代码一律用 keyEvents。
       - keyEvents 是**所有关键事件的合计**，不是某一个转化。要看单个转化，
         得加 eventName 维度 + dimensionFilter

    实现完成后，把 config.py 里 FETCH_IMPLEMENTED[SOURCE_GA4] 改成 True。
    """
    raise DataSourceNotReady(_live_blocker(config.SOURCE_GA4))


def fetch_ads_rows(
    start: date, end: date, campaign: str | None = None
) -> tuple[AdsRow, ...]:
    """取指定日期区间（含首尾）的 Google Ads 数据。

    走真实 API 还是假数据，由 .env 的 DATA_SOURCE_MODE 决定。
    """
    if config.is_live(config.SOURCE_ADS):
        return _fetch_ads_rows_live(start, end, campaign)
    return _fetch_ads_rows_mock(start, end, campaign)


def fetch_ga4_rows(
    start: date, end: date, channel: str | None = None
) -> tuple[Ga4Row, ...]:
    """取指定日期区间（含首尾）的 GA4 数据。

    走真实 API 还是假数据，由 .env 的 DATA_SOURCE_MODE 决定。
    """
    if config.is_live(config.SOURCE_GA4):
        return _fetch_ga4_rows_live(start, end, channel)
    return _fetch_ga4_rows_mock(start, end, channel)


def data_date_range() -> tuple[date, date]:
    """返回内置假数据的最早/最晚日期，方便 agent 告诉用户"我能看到哪段时间"。"""
    return ADS_ROWS[0].day, ADS_ROWS[-1].day
