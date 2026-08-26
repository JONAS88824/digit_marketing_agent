r"""关键词规划层的自检测试（不需要 pytest、不需要联网）。

运行方式：
    .venv\Scripts\python.exe -m digital_marketing_agent.test_keywords

重点测什么：**确定性计算的正确性**。
语义聚类那部分是大模型干的活，没法用断言测；
但"趋势算得对不对""负向词有没有漏""成本预估的数学对不对"必须测——
这些错了，模型再聪明也会给出错的方案。
"""

from . import config, keyword_tools, keywords, keywords_data
from .test_runner import run


def test_normalize_collapses_whitespace_and_lowercases():
    assert keywords.normalize("  Nike   跑鞋  ") == "nike 跑鞋"
    # 中间空格要保留：'nike 跑鞋' 和 'nike跑鞋' 在搜索里是两个不同的词
    assert keywords.normalize("nike 跑鞋") != keywords.normalize("nike跑鞋")


def test_dedupe_keeps_first_spelling_and_order():
    result = keywords.dedupe(["跑鞋", "  跑鞋  ", "Nike", "nike", "冲锋衣"])
    assert result == ["跑鞋", "Nike", "冲锋衣"]


def test_find_root_prefers_longest_match():
    cores = ["推车", "婴儿推车", "跑鞋"]
    # '婴儿推车' 比 '推车' 更具体，必须优先
    assert keywords.find_root("婴儿推车推荐", cores) == "婴儿推车"
    assert keywords.find_root("完全无关的词", cores) is None


def test_match_negative_rules_can_hit_multiple():
    hits = keywords.match_negative_rules("免费二手跑鞋", keywords_data.NEGATIVE_KEYWORD_RULES)
    words = {h["word"] for h in hits}
    assert words == {"免费", "二手"}
    assert keywords.match_negative_rules("跑鞋推荐", keywords_data.NEGATIVE_KEYWORD_RULES) == []


def _volumes(searches: list[int]) -> tuple[keywords_data.MonthlyVolume, ...]:
    """造一段月度搜索量序列，年月只是占位，测试只看数值。"""
    return tuple(
        keywords_data.MonthlyVolume(year=2026, month=(i % 12) + 1, searches=v)
        for i, v in enumerate(searches)
    )


def test_summarize_trend_detects_rising():
    # 前 3 个月均值 100，后 3 个月均值 200 → 涨 100%
    result = keywords.summarize_trend(_volumes([100, 100, 100, 200, 200, 200]))
    assert result["change_pct"] == 100.0
    assert result["direction"] == "rising"


def test_summarize_trend_detects_falling():
    result = keywords.summarize_trend(_volumes([200, 200, 200, 100, 100, 100]))
    assert result["change_pct"] == -50.0
    assert result["direction"] == "falling"


def test_summarize_trend_small_change_is_flat():
    """小于 20% 的变化算正常波动，不该报成趋势。"""
    result = keywords.summarize_trend(_volumes([100, 100, 100, 110, 110, 110]))
    assert result["change_pct"] == 10.0
    assert result["direction"] == "flat"


def test_summarize_trend_reports_peak_and_seasonality():
    result = keywords.summarize_trend(_volumes([100, 500, 100, 100, 100, 100]))
    assert result["peak_searches"] == 500
    assert result["trough_searches"] == 100
    assert result["seasonality_ratio"] == 5.0


def test_summarize_trend_needs_enough_months():
    result = keywords.summarize_trend(_volumes([100, 200]))
    assert result["direction"] == "unknown"
    assert result["change_pct"] is None


def _idea(text: str, searches: int, cpc: float, competition: str) -> keywords_data.KeywordIdea:
    return keywords_data.KeywordIdea(
        text=text,
        intent="transactional",
        core="跑鞋",
        avg_monthly_searches=searches,
        competition=competition,
        competition_index=50,
        avg_cpc=cpc,
        low_top_of_page_bid=cpc * 0.7,
        high_top_of_page_bid=cpc * 1.5,
        monthly_volumes=_volumes([searches] * 12),
    )


def test_estimate_cost_math_is_correct():
    """点击 = 搜索量 × 占有率 × 假设点击率；花费 = 点击 × CPC。"""
    idea = _idea("跑鞋价格", searches=10000, cpc=3.0, competition="LOW")
    ctr = keywords.ASSUMED_AD_CTR_BY_COMPETITION["LOW"]  # 0.055

    result = keywords.estimate_cost([idea], share_of_voice=1.0)
    expected_clicks = 10000 * 1.0 * ctr
    assert result["estimated_monthly_clicks"] == round(expected_clicks)
    assert result["estimated_monthly_cost"] == round(expected_clicks * 3.0, 2)
    assert result["estimated_avg_cpc"] == 3.0


def test_estimate_cost_scales_with_share_of_voice():
    idea = _idea("跑鞋价格", searches=10000, cpc=3.0, competition="LOW")
    full = keywords.estimate_cost([idea], share_of_voice=1.0)
    third = keywords.estimate_cost([idea], share_of_voice=0.3)
    assert third["estimated_monthly_clicks"] == round(full["estimated_monthly_clicks"] * 0.3)


def test_estimate_cost_clamps_share_of_voice():
    """占有率不能超过 1 也不能为负，否则会算出荒谬的点击量。"""
    idea = _idea("跑鞋价格", searches=10000, cpc=3.0, competition="LOW")
    assert keywords.estimate_cost([idea], share_of_voice=5.0)["share_of_voice"] == 1.0
    assert keywords.estimate_cost([idea], share_of_voice=-2.0)["share_of_voice"] == 0.0


def test_estimate_cost_always_carries_assumption_warning():
    """成本预估必须自带"这是假设值"的警告，防止被当成承诺转达。"""
    idea = _idea("跑鞋价格", searches=10000, cpc=3.0, competition="HIGH")
    result = keywords.estimate_cost([idea])
    assert "warning" in result["assumptions"]
    assert "预估" in result["assumptions"]["warning"]
    assert result["assumptions"]["ctr_by_competition"] == keywords.ASSUMED_AD_CTR_BY_COMPETITION


def test_higher_competition_means_fewer_assumed_clicks():
    """竞争越激烈，假设能拿到的点击率越低——这是经验规律，不能反过来。"""
    low = keywords.estimate_cost([_idea("a", 10000, 3.0, "LOW")])
    high = keywords.estimate_cost([_idea("b", 10000, 3.0, "HIGH")])
    assert low["estimated_monthly_clicks"] > high["estimated_monthly_clicks"]


def test_compare_sets_finds_gaps_both_ways():
    result = keywords.compare_sets(["跑鞋", "跑鞋价格"], ["跑鞋", "冲锋衣"])
    assert result["overlap"] == ["跑鞋"]
    assert result["only_mine"] == ["跑鞋价格"]
    assert result["only_theirs"] == ["冲锋衣"]
    assert result["overlap_pct"] == 50.0


def test_compare_sets_is_case_and_space_insensitive():
    result = keywords.compare_sets(["Nike 跑鞋"], ["  nike   跑鞋 "])
    assert result["only_mine"] == []
    assert len(result["overlap"]) == 1


def test_keyword_universe_head_term_dominates():
    """头部大词的搜索量必须明显高于它的长尾词，否则演示数据不真实。"""
    runner_words = [i for i in keywords_data.KEYWORD_UNIVERSE if i.core == "跑鞋"]
    head = next(i for i in runner_words if i.text == "跑鞋")
    longest_tail = max(
        (i for i in runner_words if i.text != "跑鞋"), key=lambda i: i.avg_monthly_searches
    )
    assert head.avg_monthly_searches > longest_tail.avg_monthly_searches


def test_transactional_keywords_cost_more_than_informational():
    """交易意图的词更值钱，CPC 必须高于信息类的词——这是投放的基本常识。"""
    same_core = [i for i in keywords_data.KEYWORD_UNIVERSE if i.core == "跑鞋"]
    transactional = [i.avg_cpc for i in same_core if i.intent == "transactional"]
    informational = [i.avg_cpc for i in same_core if i.intent == "informational"]
    assert min(transactional) > max(informational)


def test_competitors_never_bid_on_negative_signal_words():
    """竞品不会去投"免费""招聘"这类词，演示数据要符合这个常识。"""
    negative_texts = {
        i.text for i in keywords_data.KEYWORD_UNIVERSE if i.intent == "negative_signal"
    }
    bid_texts = {row.text for row in keywords_data.COMPETITOR_KEYWORDS}
    assert bid_texts & negative_texts == set()


def test_plan_keywords_rejects_unknown_industry_and_intent():
    bad_industry = keyword_tools.plan_keywords(industry="不存在的行业")
    assert bad_industry["status"] == "error"
    assert "可用行业" in bad_industry["error_message"]

    bad_intent = keyword_tools.plan_keywords(intent="随便写的意图")
    assert bad_intent["status"] == "error"
    assert "不支持的意图" in bad_intent["error_message"]


def test_plan_keywords_returns_sorted_and_capped_results():
    result = keyword_tools.plan_keywords(industry="运动户外")
    assert result["status"] == "success"
    volumes = [k["avg_monthly_searches"] for k in result["keywords"]]
    assert volumes == sorted(volumes, reverse=True), "必须按搜索量降序"
    assert len(result["keywords"]) <= keyword_tools.MAX_KEYWORDS_RETURNED


def test_plan_keywords_min_searches_filter_works():
    threshold = 30000
    result = keyword_tools.plan_keywords(min_monthly_searches=threshold)
    assert result["status"] == "success"
    assert all(k["avg_monthly_searches"] >= threshold for k in result["keywords"])


def test_forecast_keywords_reports_unknown_words_instead_of_silently_dropping():
    """词库里没有的词要如实报出来，不能悄悄忽略——否则预算会被低估。"""
    result = keyword_tools.forecast_keywords(["跑鞋价格", "这个词根本不存在"])
    assert result["status"] == "success"
    assert "这个词根本不存在" in result["unknown_keywords"]
    assert result["cost_forecast"]["keyword_count"] == 1


def test_forecast_keywords_rejects_empty_and_all_unknown():
    assert keyword_tools.forecast_keywords([])["status"] == "error"
    all_unknown = keyword_tools.forecast_keywords(["不存在A", "不存在B"])
    assert all_unknown["status"] == "error"
    assert "查不到搜索量" in all_unknown["error_message"]


def test_competitor_gap_analysis_requires_my_keywords():
    """不传我方词表就没有缺口分析——缺口是对比出来的，不能凭空生成。"""
    without = keyword_tools.get_competitor_keywords()
    assert without["status"] == "success"
    assert "gap_analysis" not in without

    with_mine = keyword_tools.get_competitor_keywords(my_keywords=["跑鞋", "跑鞋价格"])
    assert "gap_analysis" in with_mine
    assert with_mine["gap_analysis"]["my_coverage_pct"] is not None


def test_competitor_tool_rejects_unknown_competitor():
    result = keyword_tools.get_competitor_keywords(competitor="不存在的竞品")
    assert result["status"] == "error"
    assert "可选" in result["error_message"]


def test_competitor_result_always_carries_estimate_caveat():
    """第三方数据是估算，这个提醒不能少，否则会被当成竞品真实数据引用。"""
    result = keyword_tools.get_competitor_keywords()
    assert "估算" in result["data_caveat"]


def test_seo_queries_respect_impression_threshold():
    result = keyword_tools.get_seo_queries(min_impressions=5000)
    assert result["status"] == "success"
    assert all(q["impressions"] >= 5000 for q in result["queries"])
    # 匿名化提醒必须在，这是关键词研究完整性的硬上限
    assert "匿名化" in result["data_caveat"]


def test_seo_queries_too_high_threshold_returns_clear_error():
    result = keyword_tools.get_seo_queries(min_impressions=99_999_999)
    assert result["status"] == "error"
    assert "调低" in result["error_message"]


def test_converting_terms_computes_cvr_and_carries_caveat():
    result = keyword_tools.get_converting_search_terms()
    assert result["status"] == "success"
    first = result["terms"][0]
    # 转化率由工具算，不让模型口算
    expected = round(first["conversions"] / first["sessions"] * 100, 2)
    assert first["cvr_pct"] == expected
    assert "阈值过滤" in result["data_caveat"]


def test_converting_terms_sorted_by_conversions():
    result = keyword_tools.get_converting_search_terms()
    conversions = [t["conversions"] for t in result["terms"]]
    assert conversions == sorted(conversions, reverse=True)


def test_analyze_structure_separates_deterministic_from_semantic():
    """工具只给确定性结果，并明确把语义判断交回给模型。"""
    result = keyword_tools.analyze_keyword_structure(
        ["跑鞋价格", "跑鞋价格", "跑鞋免费", "婴儿推车推荐", "完全无关的词"]
    )
    assert result["status"] == "success"
    assert result["duplicates_removed"] == 1
    assert "跑鞋" in result["root_groups"]
    assert "婴儿推车" in result["root_groups"]
    assert "完全无关的词" in result["keywords_without_known_root"]

    hit_words = [h["keyword"] for h in result["negative_rule_hits"]]
    assert "跑鞋免费" in hit_words
    # 必须把语义活儿交回模型，而不是假装自己聚好了类
    assert "语义判断" in result["your_turn"]


def test_analyze_structure_rejects_empty_input():
    assert keyword_tools.analyze_keyword_structure([])["status"] == "error"


def test_record_plan_rejects_empty_clusters_and_rationale():
    assert keyword_tools.record_keyword_plan({}, [], "有理由")["status"] == "error"
    blank = keyword_tools.record_keyword_plan({"组A": ["跑鞋"]}, [], "   ")
    assert blank["status"] == "error"
    assert "rationale" in blank["error_message"]


def test_record_plan_catches_cross_group_duplicates():
    """同一个词被塞进两个组，说明聚类没想清楚，必须报警。"""
    result = keyword_tools.record_keyword_plan(
        clusters={"购买意图": ["跑鞋价格"], "比价意图": ["跑鞋价格"]},
        negative_keywords=[],
        rationale="测试跨组重复",
    )
    assert result["status"] == "warning"
    assert result["cross_group_duplicates"][0]["keyword"] == "跑鞋价格"


def test_record_plan_catches_contradictions():
    """一个词既要投又要排除，是自相矛盾，必须拦住。"""
    result = keyword_tools.record_keyword_plan(
        clusters={"购买意图": ["跑鞋价格"]},
        negative_keywords=["跑鞋价格"],
        rationale="测试自相矛盾",
    )
    assert result["status"] == "warning"
    assert "跑鞋价格" in result["contradictions"]


def test_record_plan_success_and_readable_back():
    """方案存进会话后要能读回来，支撑"这批词要花多少钱"这类追问。"""

    class FakeContext:
        def __init__(self):
            self.state: dict = {}

    ctx = FakeContext()
    saved = keyword_tools.record_keyword_plan(
        clusters={"购买意图-跑鞋": ["跑鞋价格", "跑鞋官方旗舰店"], "比价意图": ["跑鞋哪个好"]},
        negative_keywords=["跑鞋免费", "跑鞋招聘"],
        rationale="按购买意图与比价意图分组，排除无购买意图的流量。",
        tool_context=ctx,
    )
    assert saved["status"] == "success"
    assert saved["cluster_count"] == 2
    assert saved["cluster_sizes"]["购买意图-跑鞋"] == 2
    assert saved["negative_count"] == 2

    context = keyword_tools.get_keyword_context(tool_context=ctx)
    assert context["has_saved_plan"] is True
    assert context["saved_plan_summary"]["cluster_count"] == 2
    assert "购买意图-跑鞋" in context["saved_plan_summary"]["cluster_names"]


def test_keyword_context_survives_no_plan():
    class FakeContext:
        def __init__(self):
            self.state: dict = {}

    context = keyword_tools.get_keyword_context(tool_context=FakeContext())
    assert context["status"] == "success"
    assert context["has_saved_plan"] is False
    assert context["saved_plan_summary"] is None


def test_all_five_sources_have_libraries_installed():
    """五个数据源的依赖库都装好了，待办里不该再出现"安装依赖"。"""
    assert len(config.ALL_SOURCES) == 5
    for source in config.ALL_SOURCES:
        assert config.missing_package(source) is None, source
        assert not any("pip install" in step for step in config.remaining_work(source))


def test_keyword_planner_shares_ads_credentials():
    """Keyword Planner 属于 Google Ads API，凭证要求必须完全一致。"""
    ads = config.source_status(config.SOURCE_ADS)
    planner = config.source_status(config.SOURCE_KEYWORD_PLANNER)
    assert ads.missing_keys == planner.missing_keys


def test_new_sources_require_their_own_settings():
    sc = config.source_status(config.SOURCE_SEARCH_CONSOLE)
    assert "SEARCH_CONSOLE_SITE_URL" in sc.missing_keys
    assert "SEARCH_CONSOLE_CREDENTIALS_JSON_PATH" in sc.missing_keys

    intel = config.source_status(config.SOURCE_COMPETITOR)
    assert "COMPETITOR_INTEL_API_KEY" in intel.missing_keys


def test_live_keyword_fetches_raise_actionable_errors():
    """真实取数没实现时必须明确报错，且说清还差哪几步。"""
    for func, args in (
        (keywords_data._fetch_keyword_ideas_live, (None, None, None)),
        (keywords_data._fetch_competitor_keywords_live, (None,)),
        (keywords_data._fetch_seo_queries_live, (10,)),
        (keywords_data._fetch_converting_terms_live, (10,)),
    ):
        try:
            func(*args)
        except keywords_data.KeywordSourceNotReady as exc:
            message = str(exc)
            assert ".env" in message and "取数逻辑" in message, message
        else:
            raise AssertionError(f"{func.__name__} 应该抛 KeywordSourceNotReady")


if __name__ == "__main__":
    raise SystemExit(run(globals()))
