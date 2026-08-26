r"""metrics.py 的自检测试（不需要 pytest，也不需要联网）。

运行方式：
    .venv\Scripts\python.exe -m digital_marketing_agent.test_metrics

为什么要测这一层：CTR / CPC / 转化率是给老板看的数字，算错一位就是错误决策。
模型不会帮你验算，只有测试会。
"""

import json
import os
import pathlib
from datetime import date, timedelta

from .. import config
from ..sub_agents.performance import data, metrics, tools
from .test_runner import run



def _restore_env(key: str, saved: str | None) -> None:
    """把环境变量还原成测试前的样子，避免测试之间互相污染。"""
    if saved is None:
        os.environ.pop(key, None)
    else:
        os.environ[key] = saved


def test_safe_divide_returns_none_when_denominator_is_zero():
    assert metrics.safe_divide(10, 0) is None
    assert metrics.safe_divide(10, 5) == 2


def test_aggregate_ads_sums_before_dividing():
    """CTR 必须"先加总再相除"，不能把每天的 CTR 求平均。"""
    day = date(2026, 1, 1)
    rows = [
        # 第一天：1 次点击 / 100 次曝光 = 1%
        data.AdsRow(day, "A", impressions=100, clicks=1, cost=2.0, conversions=1),
        # 第二天：90 次点击 / 900 次曝光 = 10%
        data.AdsRow(day + timedelta(days=1), "A", 900, 90, 180.0, 9),
    ]
    result = metrics.aggregate_ads(rows)

    assert result["impressions"] == 1000
    assert result["clicks"] == 91
    # 正确口径：91/1000 = 9.1%；如果错误地平均每日 CTR 会得到 (1+10)/2 = 5.5%
    assert result["ctr_pct"] == 9.1
    assert result["cpc"] == round(182.0 / 91, 2)
    assert result["cvr_pct"] == round(10 / 91 * 100, 2)
    assert result["days"] == 2


def test_aggregate_ads_handles_zero_clicks():
    """0 次点击时 CPC 应该是 None（算不出），而不是 0。"""
    rows = [data.AdsRow(date(2026, 1, 1), "A", 500, 0, 0.0, 0)]
    result = metrics.aggregate_ads(rows)
    assert result["ctr_pct"] == 0.0
    assert result["cpc"] is None
    assert result["cvr_pct"] is None


def test_compare_metric_direction_awareness():
    """涨跌的"好坏"要看指标本身：CTR 涨是好事，CPC 涨是坏事。"""
    ctr_up = metrics.compare_metric("ctr_pct", current=5.0, previous=4.0)
    assert ctr_up["change_pct"] == 25.0
    assert ctr_up["verdict"] == "improved"
    assert ctr_up["needs_attention"] is False

    cpc_up = metrics.compare_metric("cpc", current=4.0, previous=2.0)
    assert cpc_up["change_pct"] == 100.0
    assert cpc_up["verdict"] == "worsened"
    assert cpc_up["needs_attention"] is True

    cpc_down = metrics.compare_metric("cpc", current=1.0, previous=2.0)
    assert cpc_down["verdict"] == "improved"


def test_compare_metric_small_change_is_stable():
    """小于 15% 的变化算正常波动，不该报警。"""
    result = metrics.compare_metric("ctr_pct", current=4.2, previous=4.0)
    assert result["change_pct"] == 5.0
    assert result["verdict"] == "stable"
    assert result["needs_attention"] is False


def test_compare_metric_cost_is_neutral():
    """花费上涨可能是主动加预算，不能一律判为变差。"""
    result = metrics.compare_metric("cost", current=2000.0, previous=1000.0)
    assert result["verdict"] == "changed"
    assert result["needs_attention"] is False


def test_compare_metric_handles_missing_data():
    result = metrics.compare_metric("cpc", current=None, previous=2.0)
    assert result["verdict"] == "unknown"
    assert result["change_pct"] is None
    assert result["needs_attention"] is False


def test_window_ends_yesterday_and_includes_both_ends():
    """最近 7 天 = 昨天往前数 7 天，含首尾。"""
    start, end = tools._window(7)
    assert end == date.today() - timedelta(days=1)
    assert (end - start).days == 6

    # 环比窗口要紧挨着当期窗口，不重叠、不留空隙
    prev_start, prev_end = tools._window(7, offset_days=7)
    assert prev_end == start - timedelta(days=1)
    assert (prev_end - prev_start).days == 6


def test_clamp_days_bounds():
    assert tools._clamp_days(0) == 1
    assert tools._clamp_days(7) == 7
    assert tools._clamp_days(9999) == tools.MAX_DAYS


def test_unknown_campaign_returns_error_not_crash():
    """名字写错时要返回清晰错误，并告诉模型有哪些可选，而不是抛异常。"""
    result = tools.get_ads_metrics(days=7, campaign="不存在的系列")
    assert result["status"] == "error"
    assert "可用广告系列" in result["error_message"]


def test_unknown_trend_metric_returns_error():
    result = tools.get_daily_trend(metric="roas", days=7)
    assert result["status"] == "error"
    assert "不支持的指标" in result["error_message"]


def test_ads_tools_run_end_to_end_on_mock_data():
    """跑通取数 → 算数 → 返回的完整链路。"""
    snapshot = tools.get_ads_metrics(days=7)
    assert snapshot["status"] == "success"
    assert snapshot["metrics"]["days"] == 7
    assert snapshot["metrics"]["ctr_pct"] > 0

    comparison = tools.compare_ads_metrics(window_days=7)
    assert comparison["status"] == "success"
    assert len(comparison["comparisons"]) == len(tools._ADS_COMPARE_KEYS)

    trend = tools.get_daily_trend(metric="cpc", days=14)
    assert trend["status"] == "success"
    assert len(trend["series"]) == 14


def test_ga4_tools_run_end_to_end_on_mock_data():
    snapshot = tools.get_ga4_metrics(days=7)
    assert snapshot["status"] == "success"
    assert snapshot["metrics"]["sessions"] > 0

    comparison = tools.compare_ga4_metrics(window_days=7, channel="Paid Search")
    assert comparison["status"] == "success"
    assert comparison["channel"] == "Paid Search"


def test_seeded_anomaly_is_detectable():
    """mock 数据里埋的异常必须能被环比抓出来，否则演示时看不到效果。"""
    result = tools.compare_ads_metrics(window_days=7, campaign=data.ANOMALY_CAMPAIGN)
    assert result["status"] == "success"
    assert "cpc" in result["attention_metrics"], result["comparisons"]
    assert "ctr_pct" in result["attention_metrics"], result["comparisons"]


def test_healthy_campaign_reports_no_alert():
    """没埋异常的广告系列不该被报警，避免"什么都在变差"的假警报。"""
    result = tools.compare_ads_metrics(window_days=7, campaign="品牌词-搜索")
    assert result["status"] == "success"
    assert result["attention_metrics"] == [], result["comparisons"]


def test_mock_is_the_default_mode():
    """没有明确写 live 时必须走假数据，不能悄悄发真实请求。"""
    saved = os.environ.get("DATA_SOURCE_MODE")
    try:
        os.environ["DATA_SOURCE_MODE"] = "mock"
        assert config.data_source_mode() == config.MODE_MOCK
        assert config.is_live(config.SOURCE_ADS) is False

        os.environ["DATA_SOURCE_MODE"] = "随便写点什么"
        assert config.data_source_mode() == config.MODE_MOCK
    finally:
        _restore_env("DATA_SOURCE_MODE", saved)


def test_source_status_lists_missing_keys():
    """凭证没填时要精确报出缺哪几项，而不是笼统说"没配好"。"""
    status = config.source_status(config.SOURCE_ADS)
    assert status.configured is False
    assert "GOOGLE_ADS_DEVELOPER_TOKEN" in status.missing_keys


def test_ga4_needs_exactly_two_settings():
    """已核对官方文档：GA4 取数只要"媒体资源 ID"和"服务账号密钥路径"两样。"""
    assert config._GA4_REQUIRED == ("GA4_PROPERTY_ID", "GA4_CREDENTIALS_JSON_PATH")


def test_client_libraries_are_installed():
    """两个真实 API 的库都装好了，所以待办里不该再出现"安装依赖"。"""
    for source in (config.SOURCE_ADS, config.SOURCE_GA4):
        assert config.missing_package(source) is None, source
        assert not any("pip install" in step for step in config.remaining_work(source))


def test_remaining_work_lists_credentials_and_implementation():
    """待办清单要说清还差什么：凭证 + 取数逻辑，一步都不能漏。"""
    for source in (config.SOURCE_ADS, config.SOURCE_GA4):
        steps = config.remaining_work(source)
        assert any(".env" in step for step in steps), source
        assert any("取数逻辑" in step for step in steps), source


def test_describe_reports_readiness_breakdown():
    """体检报告要把"库/凭证/取数逻辑"三项分开列，而不是笼统一个 false。"""
    report = config.describe()
    for source in (config.SOURCE_ADS, config.SOURCE_GA4):
        block = report["sources"][source]
        assert block["library_installed"] is True
        assert block["credentials_configured"] is False
        assert block["fetch_implemented"] is False
        assert block["ready_for_live"] is False
        assert block["effective_mode"] == "mock"


def test_describe_never_leaks_credential_values():
    """体检报告里绝不能出现凭证的值——它会被送进模型上下文。"""
    saved = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    secret = "SECRET-TOKEN-DO-NOT-LEAK"
    try:
        os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"] = secret
        report = json.dumps(config.describe(), ensure_ascii=False)
        assert secret not in report
        tool_report = json.dumps(tools.check_data_source_config(), ensure_ascii=False)
        assert secret not in tool_report
    finally:
        _restore_env("GOOGLE_ADS_DEVELOPER_TOKEN", saved)


def test_live_mode_without_credentials_falls_back_to_mock():
    """模式写了 live 但凭证不全时，退回假数据而不是发失败请求。"""
    saved = os.environ.get("DATA_SOURCE_MODE")
    try:
        os.environ["DATA_SOURCE_MODE"] = "live"
        assert config.data_source_mode() == config.MODE_LIVE
        # 凭证不全 → is_live 为假 → 取数仍然走 mock，不抛异常
        assert config.is_live(config.SOURCE_ADS) is False
        result = tools.get_ads_metrics(days=7)
        assert result["status"] == "success"
    finally:
        _restore_env("DATA_SOURCE_MODE", saved)


def test_live_fetch_raises_clear_error_when_unimplemented():
    """凭证配齐但真实取数还没写时，必须明确报错，不能返回假数据充数。"""
    start, end = tools._window(7)
    try:
        data._fetch_ads_rows_live(start, end, None)
    except data.DataSourceNotReady as exc:
        message = str(exc)
        # 库已安装，所以拦路原因应该是"缺凭证"和"取数逻辑没写"
        assert ".env" in message and "取数逻辑" in message, message
    else:
        raise AssertionError("应该抛出 DataSourceNotReady")


def test_safe_fetch_turns_source_failure_into_error_dict():
    """数据源故障要变成一句人话返回给模型，不能让对话崩掉。"""

    def broken(*_args):
        raise data.DataSourceNotReady("凭证不完整")

    rows, error = tools._safe_fetch(broken, None, None, None)
    assert rows == ()
    assert error["status"] == "error"
    assert "凭证不完整" in error["error_message"]


def test_list_data_sources_reports_mock_mode():
    """必须让模型知道当前数字是演示数据，否则会当成真实投放汇报。"""
    result = tools.list_data_sources()
    assert result["google_ads_mode"] == "mock"
    assert result["ga4_mode"] == "mock"
    assert "mock" in result["note"]


def test_env_example_contains_no_values():
    """.env.example 会被提交到 git，里面必须一个值都没有。"""
    template = pathlib.Path(__file__).parents[1] / ".env.example"
    assert template.exists(), "缺少 .env.example 模板"
    for line in template.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        key, value = line.split("=", 1)
        # 非敏感的开关允许带默认值，凡是凭证/密钥/路径一律必须为空
        allowed_defaults = {
            "DATA_SOURCE_MODE": "mock",
            "IMAGE_GENERATION_MODE": "mock",
            "IMAGE_MAX_PER_CALL": "3",
            "IMAGE_DEFAULT_TIER": "standard",
            "ADS_WRITE_MODE": "mock",
        }
        assert value == allowed_defaults.get(key, ""), f"{key} 在模板里带了值：{value}"


if __name__ == "__main__":
    raise SystemExit(run(globals()))
