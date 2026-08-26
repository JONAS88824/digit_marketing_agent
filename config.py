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

SOURCE_ADS = "google_ads"
SOURCE_GA4 = "ga4"

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

_REQUIRED_BY_SOURCE = {SOURCE_ADS: _ADS_REQUIRED, SOURCE_GA4: _GA4_REQUIRED}

# 真实 API 需要的库，用于给出准确的安装提示
_PIP_PACKAGES = {SOURCE_ADS: "google-ads", SOURCE_GA4: "google-analytics-data"}

# 真实取数逻辑写完了没有。这是唯一的真相来源：
# data.py 实现完对应的 _fetch_*_live 之后，把这里改成 True。
FETCH_IMPLEMENTED = {SOURCE_ADS: False, SOURCE_GA4: False}

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
    optional_present = tuple(
        key for key in _ADS_OPTIONAL if source == SOURCE_ADS and _get(key)
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
    """返回该数据源缺失的 pip 包名；已安装则返回 None。"""
    import importlib.util

    module = {
        SOURCE_ADS: "google.ads.googleads",
        SOURCE_GA4: "google.analytics.data_v1beta",
    }[source]
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


def describe() -> dict:
    """汇总配置体检结果，供工具层返回给模型。不含任何凭证值。"""
    mode = data_source_mode()
    report = {}
    for source in (SOURCE_ADS, SOURCE_GA4):
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
