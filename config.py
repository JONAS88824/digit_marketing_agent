"""凭证与数据源配置：把敏感信息全部关在 .env 里，代码只读键名。

【安全底线】
本模块对外只回答"这个凭证配好了没有"，**永远不返回凭证的值**。
因为返回值会被送进大模型的上下文，凭证一旦进上下文就等于泄露了。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# 本 agent 自己的 .env。ADK 启动时也会加载它，
# 这里再加载一次是为了让脚本、测试单独运行时也能读到配置。
_ENV_FILE = Path(__file__).parent / ".env"

MODE_MOCK = "mock"
MODE_LIVE = "live"

# ===== 图像生成的独立开关 =====
# 单独一个开关，不跟 DATA_SOURCE_MODE 共用，原因是它们的风险完全不同：
# 取数是只读的，最多浪费点配额；**生成图片是按张收费的真花钱**。
# 所以默认 mock（本地画占位图，零成本），要真出图必须显式打开。
IMAGE_MODE_ENV = "IMAGE_GENERATION_MODE"
IMAGE_MODEL_ENV = "IMAGE_MODEL"
IMAGE_MAX_PER_CALL_ENV = "IMAGE_MAX_PER_CALL"

# 默认模型。已用账号实测确认可用（client.models.list()）：
# 该账号下**没有任何 imagen-* 模型**，Imagen 系列已在 Gemini API 下线，
# 可用的是这批 Gemini 原生图像模型，且它们只支持 generateContent，
# 不支持 Imagen 的 predict/generate_images 接口。
DEFAULT_IMAGE_MODEL = "gemini-3.1-flash-image"

# 实测该账号可用的图像模型，按"便宜→贵"排列
AVAILABLE_IMAGE_MODELS = (
    "gemini-3.1-flash-lite-image",
    "gemini-2.5-flash-image",
    "gemini-3.1-flash-image",
    "gemini-3-pro-image",
)

# 单次调用最多出几张图。硬上限，防止一句话烧掉一笔钱。
DEFAULT_IMAGE_MAX_PER_CALL = 3
IMAGE_HARD_CAP_PER_CALL = 6

SOURCE_ADS = "google_ads"
SOURCE_GA4 = "ga4"
# 关键词规划走 Keyword Planner，它属于 Google Ads API，凭证与 SOURCE_ADS 共用，
# 但"取数逻辑写没写"是独立的一件事，所以单列一个数据源。
SOURCE_KEYWORD_PLANNER = "keyword_planner"
SOURCE_SEARCH_CONSOLE = "search_console"
# 竞品投放词只能买第三方情报（SEMrush / Ahrefs / DataForSEO 等）。
# 这里做成厂商中立：只认一个 base_url + api_key，换厂商不用改架构。
SOURCE_COMPETITOR = "competitor_intel"

# 调真实 Google Ads API 必须齐备的凭证
_ADS_REQUIRED = (
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_CUSTOMER_ID",
)
# 选填：只有通过 MCC 经理账号访问子账号时才需要
_ADS_OPTIONAL = ("GOOGLE_ADS_LOGIN_CUSTOMER_ID",)

# 调真实 GA4 Data API 必须齐备的配置。
# 已核对官方 quickstart 与已安装的 google-analytics-data 0.23.0：
# GA4 只需要"媒体资源 ID"+"服务账号密钥文件"两样，没有第三样。
_GA4_REQUIRED = ("GA4_PROPERTY_ID", "GA4_CREDENTIALS_JSON_PATH")

# Search Console 需要"查哪个站点"+"用什么身份查"。
# siteUrl 有两种写法：URL 前缀属性 https://example.com/ ，
# 或域名属性 sc-domain:example.com（覆盖全部子域与协议）。
_SEARCH_CONSOLE_REQUIRED = ("SEARCH_CONSOLE_SITE_URL", "SEARCH_CONSOLE_CREDENTIALS_JSON_PATH")

# 第三方竞品情报：厂商中立，只要端点和密钥
_COMPETITOR_REQUIRED = ("COMPETITOR_INTEL_API_KEY", "COMPETITOR_INTEL_BASE_URL")

_REQUIRED_BY_SOURCE = {
    SOURCE_ADS: _ADS_REQUIRED,
    SOURCE_GA4: _GA4_REQUIRED,
    # Keyword Planner 是 Google Ads API 的一部分，凭证要求完全一致
    SOURCE_KEYWORD_PLANNER: _ADS_REQUIRED,
    SOURCE_SEARCH_CONSOLE: _SEARCH_CONSOLE_REQUIRED,
    SOURCE_COMPETITOR: _COMPETITOR_REQUIRED,
}

# 所有数据源，按体检报告里的展示顺序
ALL_SOURCES = (
    SOURCE_ADS,
    SOURCE_GA4,
    SOURCE_KEYWORD_PLANNER,
    SOURCE_SEARCH_CONSOLE,
    SOURCE_COMPETITOR,
)

# 真实 API 需要的库，用于给出准确的安装提示。
# 竞品情报只是 HTTP 调用，不需要专用库，所以是 None。
_PIP_PACKAGES = {
    SOURCE_ADS: "google-ads",
    SOURCE_GA4: "google-analytics-data",
    SOURCE_KEYWORD_PLANNER: "google-ads",
    SOURCE_SEARCH_CONSOLE: "google-api-python-client",
    SOURCE_COMPETITOR: None,
}

# 用来判断库装没装的导入路径
_IMPORT_PATHS = {
    SOURCE_ADS: "google.ads.googleads",
    SOURCE_GA4: "google.analytics.data_v1beta",
    SOURCE_KEYWORD_PLANNER: "google.ads.googleads",
    SOURCE_SEARCH_CONSOLE: "googleapiclient.discovery",
    SOURCE_COMPETITOR: None,
}

# 真实取数逻辑写完了没有。这是唯一的真相来源：
# 实现完对应的 _fetch_*_live 之后，把这里改成 True。
FETCH_IMPLEMENTED = {
    SOURCE_ADS: False,
    SOURCE_GA4: False,
    SOURCE_KEYWORD_PLANNER: False,
    SOURCE_SEARCH_CONSOLE: False,
    SOURCE_COMPETITOR: False,
}

# 各数据源剩余工作的落地位置，直接告诉用户"后期怎么做"
_IMPLEMENTATION_HINTS = {
    SOURCE_ADS: (
        "在 data.py 的 _fetch_ads_rows_live 里用 GoogleAdsClient.load_from_dict() "
        "建客户端，再用 GAQL 查 campaign 报表。注意 developer_token 之外还必须传 "
        "use_proto_plus=True（库的硬性要求），customer_id 不是客户端配置、"
        "而是 search_stream() 的调用参数。"
    ),
    SOURCE_GA4: (
        "在 data.py 的 _fetch_ga4_rows_live 里用 "
        "service_account.Credentials.from_service_account_file(GA4_CREDENTIALS_JSON_PATH) "
        "建凭证，传给 BetaAnalyticsDataClient(credentials=...)，"
        "再用 run_report() 查 property=properties/<GA4_PROPERTY_ID>。"
    ),
    SOURCE_KEYWORD_PLANNER: (
        "在 keywords_data.py 的 _fetch_keyword_ideas_live 里用 "
        "client.get_service('KeywordPlanIdeaService').generate_keyword_ideas()，"
        "请求里填 keyword_seed（或 url_seed / site_seed）+ geo_target_constants + language，"
        "结果的 keyword_idea_metrics 带 avg_monthly_searches、competition、"
        "average_cpc_micros 和 monthly_search_volumes（12 个月趋势）。"
        "所有 micros 字段都要除以 1_000_000。"
    ),
    SOURCE_SEARCH_CONSOLE: (
        "在 keywords_data.py 的 _fetch_seo_queries_live 里用 "
        "build('searchconsole', 'v1', credentials=...)，调 "
        "searchanalytics().query(siteUrl=..., body={'dimensions': ['query'], ...})。"
        "注意返回的 ctr 是 0~1 的小数不是百分比；rowLimit 上限 25000，"
        "超过要用 startRow 翻页。"
    ),
    SOURCE_COMPETITOR: (
        "在 keywords_data.py 的 _fetch_competitor_keywords_live 里用 requests 或 httpx "
        "调 COMPETITOR_INTEL_BASE_URL，带上 COMPETITOR_INTEL_API_KEY，"
        "把返回结果转成 CompetitorKeyword。厂商换了只改这一个函数，"
        "上层不用动——这也是为什么这里不绑定具体厂商。"
    ),
}


@dataclass(frozen=True)
class SourceStatus:
    """某个数据源的配置体检结果。只含键名和判断，不含任何凭证值。"""

    source: str
    configured: bool
    missing_keys: tuple[str, ...]
    optional_keys_present: tuple[str, ...]


def load() -> None:
    """把 .env 读进环境变量。已存在的环境变量优先，不会被文件覆盖。"""
    if _ENV_FILE.exists():
        load_dotenv(_ENV_FILE, override=False)


def _get(key: str) -> str:
    """读一个配置项，去掉首尾空格。缺失或空串都返回空串。"""
    return (os.environ.get(key) or "").strip()


def data_source_mode() -> str:
    """当前数据源模式：mock（内置假数据）或 live（真实 API）。

    只要不是明确写了 live，都按 mock 处理——宁可用假数据，
    也不要在配置不全的情况下发出真实 API 请求。
    """
    load()
    return MODE_LIVE if _get("DATA_SOURCE_MODE").lower() == MODE_LIVE else MODE_MOCK


def source_status(source: str) -> SourceStatus:
    """检查某个数据源的凭证是否配齐。"""
    load()
    required = _REQUIRED_BY_SOURCE[source]
    missing = tuple(key for key in required if not _get(key))
    uses_ads_credentials = source in (SOURCE_ADS, SOURCE_KEYWORD_PLANNER)
    optional_present = tuple(
        key for key in _ADS_OPTIONAL if uses_ads_credentials and _get(key)
    )
    return SourceStatus(
        source=source,
        configured=not missing,
        missing_keys=missing,
        optional_keys_present=optional_present,
    )


def is_live(source: str) -> bool:
    """这个数据源现在是否真的走真实 API。

    两个条件同时满足才算：模式是 live，且凭证已配齐。
    凭证不全时自动退回 mock，而不是发一个注定失败的请求。
    """
    return data_source_mode() == MODE_LIVE and source_status(source).configured


def missing_package(source: str) -> str | None:
    """返回该数据源缺失的 pip 包名；已安装或不需要专用库则返回 None。"""
    import importlib.util

    module = _IMPORT_PATHS[source]
    if module is None:  # 纯 HTTP 调用，不需要专用库
        return None
    try:
        installed = importlib.util.find_spec(module) is not None
    except ModuleNotFoundError:
        installed = False
    return None if installed else _PIP_PACKAGES[source]


def remaining_work(source: str) -> list[str]:
    """列出这个数据源还差哪几步才能真正取到数，按该做的顺序排列。"""
    steps: list[str] = []
    package = missing_package(source)
    if package:
        steps.append(f"安装依赖库：pip install {package}")

    status = source_status(source)
    if status.missing_keys:
        steps.append(
            f".env 里填上这些配置项：{'、'.join(status.missing_keys)}"
        )

    if not FETCH_IMPLEMENTED[source]:
        steps.append(f"实现真实取数逻辑：{_IMPLEMENTATION_HINTS[source]}")

    if not steps:
        steps.append(
            f"已就绪，把 .env 的 DATA_SOURCE_MODE 改成 {MODE_LIVE} 即可用真实数据。"
        )
    return steps


def image_generation_mode() -> str:
    """图像生成是 mock（本地占位图）还是 live（真调模型、真花钱）。

    只有明确写 live 才算 live。宁可给占位图，也不要在用户没预期的时候扣费。
    """
    load()
    return MODE_LIVE if _get(IMAGE_MODE_ENV).lower() == MODE_LIVE else MODE_MOCK


def image_model() -> str:
    """要用哪个图像模型。没配就用默认的。"""
    load()
    return _get(IMAGE_MODEL_ENV) or DEFAULT_IMAGE_MODEL


def image_max_per_call() -> int:
    """单次调用允许出几张图。读不到或读到非法值就用默认值，并受硬上限约束。"""
    load()
    raw = _get(IMAGE_MAX_PER_CALL_ENV)
    try:
        value = int(raw) if raw else DEFAULT_IMAGE_MAX_PER_CALL
    except ValueError:
        value = DEFAULT_IMAGE_MAX_PER_CALL
    return max(1, min(value, IMAGE_HARD_CAP_PER_CALL))


def image_generation_status() -> dict:
    """图像生成的配置体检。不返回 API key 本身，只说配没配。"""
    load()
    has_key = bool(_get("GOOGLE_API_KEY"))
    mode = image_generation_mode()
    model = image_model()
    return {
        "mode": mode,
        "model": model,
        "model_is_known_available": model in AVAILABLE_IMAGE_MODELS,
        "api_key_configured": has_key,
        "max_images_per_call": image_max_per_call(),
        "effective_mode": MODE_LIVE if (mode == MODE_LIVE and has_key) else MODE_MOCK,
        "cost_warning": (
            "live 模式按张收费，且免费额度不覆盖图像生成，需要账号已开通付费。"
            "mock 模式在本地画占位图，零成本。"
        ),
        "available_models": list(AVAILABLE_IMAGE_MODELS),
    }


def describe() -> dict:
    """汇总配置体检结果，供工具层返回给模型。不含任何凭证值。"""
    mode = data_source_mode()
    report = {}
    for source in ALL_SOURCES:
        status = source_status(source)
        package = missing_package(source)
        report[source] = {
            "credentials_configured": status.configured,
            "missing_keys": list(status.missing_keys),
            "library_installed": package is None,
            "missing_package": package,
            "fetch_implemented": FETCH_IMPLEMENTED[source],
            "ready_for_live": (
                status.configured and package is None and FETCH_IMPLEMENTED[source]
            ),
            "effective_mode": MODE_LIVE if is_live(source) else MODE_MOCK,
            "remaining_work": remaining_work(source),
        }
    return {
        "requested_mode": mode,
        "sources": report,
        "env_file_found": _ENV_FILE.exists(),
        "note": (
            "凭证的值不会显示在这里，只显示键名和是否已配置。"
            "要改配置请编辑 digital_marketing_agent/.env。"
        ),
    }
