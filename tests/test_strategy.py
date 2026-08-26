r"""投放策略与风控的自检测试。不联网、不需要凭证、不消耗任何配额。

【为什么这套测试比别的更要紧】
其它模块算错只是看错一眼数据，这个模块算错是真花钱：
预算阀门放过一个 5000 元的日预算，或者敏感词漏掉一个违禁词导致封号，
代价都不是改一行代码能挽回的。所以这里连边界值都要单独测。

运行方式：
    .venv\Scripts\python.exe -m digital_marketing_agent.tests.test_strategy
"""

import os
from datetime import date, timedelta

from .. import config
from ..sub_agents.performance.data import AdsRow
from ..sub_agents.strategy import checks, data as strategy_data, payload, rules, schema, tools
from .test_runner import run

# 测试用的固定阀门。刻意不读 .env——用户改了配置不该让测试变红。
LIMITS = {
    "max_daily_budget": 300.0,
    "max_account_daily_budget": 3000.0,
    "max_cpc": 15.0,
    "min_cpc": 0.5,
    "max_target_cpa": 200.0,
    "min_target_roas": 1.5,
    "max_target_roas": 20.0,
}

HEADLINES = ["轻量缓震跑鞋", "透气网面跑鞋", "官方正品保障", "马拉松训练之选"]
DESCRIPTIONS = [
    "轻量缓震设计，长距离跑步更省力，官方正品发货。",
    "透气网面材质，日常通勤与训练都合适。",
]


class FakeContext:
    """假的 ToolContext：只需要一个 state 字典就够 remember() 用。"""

    def __init__(self):
        self.state = {}


def _tool_name(tool) -> str:
    """取工具名。裸函数只有 __name__，FunctionTool 包装后暴露 .name。"""
    return getattr(tool, "name", None) or getattr(tool, "__name__", str(tool))


def ad_group(
    name="跑鞋-购买意图",
    keywords=("男士跑鞋", "缓震跑鞋"),
    negatives=(),
    headlines=None,
    descriptions=None,
    **extra,
):
    return {
        "name": name,
        "keywords": list(keywords),
        "negative_keywords": list(negatives),
        "headlines": list(headlines or HEADLINES),
        "descriptions": list(descriptions or DESCRIPTIONS),
        "final_url": "https://example.com/running-shoes",
        **extra,
    }


def guardrails(daily_budget=200.0, strategy="MANUAL_CPC", **kwargs):
    kwargs.setdefault("max_cpc", 3.0)
    return checks.review_guardrails(
        daily_budget=daily_budget, bidding_strategy=strategy, limits=LIMITS, **kwargs
    )


def blocked_names(result):
    return {c["check"] for c in result["blocking"]}


def warned_names(result):
    return {c["check"] for c in result["warnings"]}


# ===== 预算阀门 =====


def test_budget_within_cap_passes():
    result = guardrails(daily_budget=200.0)
    assert result["passed"], result["blocking"]


def test_budget_over_cap_is_blocked_and_says_how_much_over():
    result = guardrails(daily_budget=500.0)
    assert not result["passed"]
    assert "daily_budget_cap" in blocked_names(result)
    message = next(c["message"] for c in result["blocking"] if c["check"] == "daily_budget_cap")
    assert "200" in message, f"没说清超了多少：{message}"


def test_budget_exactly_at_cap_passes():
    """边界值单独测：写成 < 而不是 <= 是最容易犯的一位之差。"""
    result = guardrails(daily_budget=LIMITS["max_daily_budget"])
    assert "daily_budget_cap" not in blocked_names(result)


def test_zero_budget_is_blocked():
    result = guardrails(daily_budget=0.0)
    assert "daily_budget_positive" in blocked_names(result)


def test_negative_budget_is_blocked():
    result = guardrails(daily_budget=-50.0)
    assert "daily_budget_positive" in blocked_names(result)


def test_account_total_over_cap_is_blocked_even_when_single_campaign_is_fine():
    """单系列没超但账户合计超了，同样要拦——这是"拆成几个小系列"绕阀门的堵法。"""
    result = guardrails(daily_budget=250.0, other_campaigns_daily_budget=2900.0)
    assert "account_budget_cap" in blocked_names(result)
    assert "daily_budget_cap" not in blocked_names(result)


def test_too_small_budget_is_warning_not_block():
    result = guardrails(daily_budget=3.0)
    assert "daily_budget_viable" in warned_names(result)
    assert "daily_budget_viable" not in blocked_names(result)


# ===== 出价阀门 =====


def test_unknown_bidding_strategy_is_blocked():
    result = guardrails(strategy="AUTO_MAGIC")
    assert "bidding_strategy_known" in blocked_names(result)


def test_target_cpa_strategy_requires_target_cpa():
    result = guardrails(strategy="TARGET_CPA", max_cpc=None)
    assert "bidding_requires_target_cpa" in blocked_names(result)


def test_manual_cpc_requires_max_cpc():
    result = guardrails(strategy="MANUAL_CPC", max_cpc=None)
    assert "bidding_requires_max_cpc" in blocked_names(result)


def test_max_cpc_above_cap_is_blocked():
    result = guardrails(max_cpc=40.0)
    assert "max_cpc_range" in blocked_names(result)


def test_max_cpc_below_floor_is_blocked():
    """出价过低不烧钱，但完全没有曝光，是另一种失败，也要拦。"""
    result = guardrails(max_cpc=0.1)
    assert "max_cpc_range" in blocked_names(result)


def test_target_cpa_above_cap_is_blocked():
    result = guardrails(daily_budget=300.0, strategy="TARGET_CPA", max_cpc=None, target_cpa=500.0)
    assert "target_cpa_range" in blocked_names(result)


def test_target_roas_below_floor_is_blocked():
    result = guardrails(strategy="TARGET_ROAS", max_cpc=None, target_roas=1.1)
    assert "target_roas_range" in blocked_names(result)


def test_target_roas_above_cap_is_blocked():
    result = guardrails(strategy="TARGET_ROAS", max_cpc=None, target_roas=50.0)
    assert "target_roas_range" in blocked_names(result)


def test_bid_field_irrelevant_to_strategy_is_warning_only():
    """给 TARGET_CPA 方案填了 max_cpc：提醒它不生效，但不拦——拦了模型会反复试。"""
    result = guardrails(strategy="TARGET_CPA", max_cpc=3.0, target_cpa=80.0)
    assert "bidding_ignores_max_cpc" in warned_names(result)
    assert result["passed"], result["blocking"]


def test_target_cpa_higher_than_daily_budget_is_warning():
    result = guardrails(daily_budget=60.0, strategy="TARGET_CPA", max_cpc=None, target_cpa=120.0)
    assert "target_cpa_vs_budget" in warned_names(result)


def test_maximize_conversions_warns_that_budget_is_the_only_brake():
    result = guardrails(strategy="MAXIMIZE_CONVERSIONS", max_cpc=None)
    assert "maximize_conversions_budget_is_the_only_brake" in warned_names(result)


def test_ad_group_level_bid_goes_through_the_same_gate():
    """组级出价会覆盖系列级，漏检等于阀门白装。"""
    result = guardrails(ad_group_max_cpcs=(("跑鞋组", 99.0),))
    assert "ad_group_max_cpc:跑鞋组" in blocked_names(result)


# ===== 敏感词与合规 =====


def test_absolute_superlative_is_blocking():
    result = checks.scan_sensitive_words({"标题": ["全网最佳跑鞋"]})
    assert not result["passed"]
    assert any(h["word"] == "最佳" for h in result["blocking_hits"])


def test_fullwidth_and_spacing_evasion_is_caught():
    """刻意规避是常态：加空格、用全角、加点号。折叠归一化就是为它准备的。"""
    for text in ["最 佳 跑鞋", "Ｎｏ.１ 跑鞋品牌", "1 0 0% 有效"]:
        result = checks.scan_sensitive_words({"标题": [text]})
        assert not result["passed"], f"没抓到规避写法：{text}"


def test_ascii_rule_word_does_not_match_inside_another_word():
    """'cure' 不该命中 'secure'——英文按词边界匹配，不然误伤一片。"""
    result = checks.scan_sensitive_words({"描述": ["secure checkout by bank"]})
    hits = result["blocking_hits"] + result["warning_hits"]
    assert not any(h["word"] == "cure" for h in hits), hits


def test_ascii_rule_word_matches_when_standalone():
    result = checks.scan_sensitive_words({"描述": ["this will cure your pain"]})
    assert any(h["word"] == "cure" for h in result["warning_hits"] + result["blocking_hits"])


def test_ascii_rule_word_matches_when_glued_to_chinese():
    """'cure你的病'——英文违禁词紧贴中文，也要抓到（\\b 抓不到，ASCII 边界能）。"""
    result = checks.scan_sensitive_words({"描述": ["cure你的失眠"]})
    assert any(h["word"] == "cure" for h in result["warning_hits"] + result["blocking_hits"])


def test_warning_level_word_does_not_block():
    result = checks.scan_sensitive_words({"标题": ["行业唯一授权服务商"]})
    assert result["passed"], "warning 级别的词不该拦下提交"
    assert result["warning_hits"]


def test_clean_copy_has_no_hits():
    result = checks.scan_sensitive_words({"标题": HEADLINES, "描述": DESCRIPTIONS})
    assert result["total_hits"] == 0, result["blocking_hits"] + result["warning_hits"]
    assert result["passed"]


def test_categories_and_section_are_reported():
    """报出"哪个部位命中了哪一类"，用户才知道该改哪。"""
    result = checks.scan_sensitive_words({"关键词": ["高仿运动鞋"]})
    hit = result["blocking_hits"][0]
    assert hit["section"] == "关键词"
    assert hit["category"] == "侵权仿品"
    assert "侵权仿品" in result["categories_hit"]


def test_every_sensitive_rule_can_match_its_own_word():
    """词表自检：每条规则至少能命中它自己的词。防止手写词表时打错字。"""
    for rule in rules.SENSITIVE_WORD_RULES:
        result = checks.scan_sensitive_words({"标题": [f"促销 {rule['word']} 上市"]})
        assert result["total_hits"] >= 1, f"规则词命中不了自己：{rule['word']}"


# ===== 逻辑自相矛盾 =====


def parse_groups(*raw_groups):
    errors = []
    groups = [schema.parse_ad_group(g, i, errors) for i, g in enumerate(raw_groups)]
    assert not errors, errors
    return groups


def test_same_keyword_as_positive_and_negative_is_blocking():
    groups = parse_groups(ad_group(keywords=("男士跑鞋",), negatives=("男士跑鞋",)))
    result = checks.check_logic(groups)
    assert not result["passed"]
    assert result["blocking"][0]["type"] == "positive_negative_conflict"


def test_campaign_level_negative_blocking_a_positive_is_blocking():
    groups = parse_groups(ad_group(keywords=("二手跑鞋",)))
    result = checks.check_logic(groups, account_negative_keywords=["二手跑鞋"])
    assert not result["passed"]
    assert result["blocking"][0]["type"] == "blocked_by_account_negative"


def test_cross_group_duplicate_is_warning_only():
    groups = parse_groups(
        ad_group(name="A组", keywords=("男士跑鞋",)),
        ad_group(name="B组", keywords=("男士跑鞋",)),
    )
    result = checks.check_logic(groups)
    assert result["passed"], "跨组重复只是浪费，不该拦下提交"
    assert result["warnings"][0]["type"] == "cross_group_duplicate"


def test_clean_groups_pass_logic_check():
    groups = parse_groups(
        ad_group(name="A组", keywords=("男士跑鞋",), negatives=("免费",)),
        ad_group(name="B组", keywords=("女士跑鞋",)),
    )
    result = checks.check_logic(groups)
    assert result["passed"]
    assert result["total_keywords"] == 2


def test_duplicate_ad_group_names_are_a_shape_error():
    draft, errors = schema.parse_campaign(
        campaign_name="测试系列",
        daily_budget=200.0,
        bidding_strategy="MANUAL_CPC",
        ad_groups=[ad_group(name="同名"), ad_group(name="同名", keywords=("女士跑鞋",))],
        max_cpc=3.0,
    )
    assert draft is None
    assert any("重复" in e for e in errors)


# ===== Mutate 结构构造 =====


def build_draft(**overrides):
    args = {
        "campaign_name": "跑鞋-春季-搜索",
        "daily_budget": 200.0,
        "bidding_strategy": "MANUAL_CPC",
        "ad_groups": [ad_group(negatives=("免费",))],
        "max_cpc": 3.0,
    }
    args.update(overrides)
    draft, errors = schema.parse_campaign(**args)
    assert draft is not None, errors
    return draft


def test_operations_follow_dependency_order():
    """顺序错了会留半成品垃圾数据，这是本模块最不能错的一条。"""
    ops = payload.build_operations(build_draft())
    order_of = {}
    for op in ops:
        order_of.setdefault(op.resource, op.order)

    assert order_of["campaign_budget"] < order_of["campaign"], "预算必须先建"
    assert order_of["campaign"] < order_of["ad_group"], "广告系列必须在广告组之前"
    assert order_of["ad_group"] < order_of["ad_group_criterion"], "广告组必须先于关键词"
    assert order_of["ad_group"] < order_of["ad_group_ad"], "广告组必须先于广告素材"


def test_every_dependency_is_created_before_it_is_used():
    ops = payload.build_operations(build_draft())
    created = set()
    for op in sorted(ops, key=lambda o: o.order):
        for needed in op.depends_on:
            assert needed in created, f"第 {op.order} 步依赖了还没创建的 {needed}"
        if op.temp_id is not None:
            created.add(op.temp_id)


def test_temp_ids_are_unique_and_negative():
    ops = payload.build_operations(
        build_draft(
            ad_groups=[
                ad_group(name="A组", keywords=("男士跑鞋", "缓震跑鞋"), negatives=("免费",)),
                ad_group(name="B组", keywords=("女士跑鞋",)),
            ]
        )
    )
    temp_ids = [op.temp_id for op in ops if op.temp_id is not None]
    assert len(temp_ids) == len(set(temp_ids)), "临时 ID 撞号了，会互相覆盖"
    assert all(t < 0 for t in temp_ids), "临时资源 ID 必须是负数"


def test_amounts_are_converted_to_micros():
    """300 元要写成 300000000。差一位就是十倍预算。"""
    ops = payload.build_operations(build_draft(daily_budget=300.0))
    budget_op = next(op for op in ops if op.resource == "campaign_budget")
    assert budget_op.payload["amount_micros"] == 300_000_000
    assert payload.to_micros(2.5) == 2_500_000


def test_new_campaign_is_created_paused():
    """创建本身不该开始花钱——要不要开投是另一次人工决定。"""
    ops = payload.build_operations(build_draft())
    campaign_op = next(op for op in ops if op.resource == "campaign")
    assert campaign_op.payload["status"] == "PAUSED"


def test_bidding_fields_match_the_chosen_strategy():
    """同一个 campaign 上放两种出价策略，API 会直接报错。"""
    manual = next(
        op for op in payload.build_operations(build_draft()) if op.resource == "campaign"
    )
    assert "manual_cpc" in manual.payload
    assert "target_cpa" not in manual.payload

    tcpa_draft = build_draft(bidding_strategy="TARGET_CPA", max_cpc=None, target_cpa=80.0)
    tcpa = next(
        op for op in payload.build_operations(tcpa_draft) if op.resource == "campaign"
    )
    assert tcpa.payload["target_cpa"]["target_cpa_micros"] == 80_000_000
    assert "manual_cpc" not in tcpa.payload


def test_negative_keywords_are_marked_negative():
    ops = payload.build_operations(build_draft())
    criteria = [op for op in ops if op.resource == "ad_group_criterion"]
    negatives = [op for op in criteria if op.payload.get("negative")]
    assert len(negatives) == 1
    assert negatives[0].payload["keyword"]["text"] == "免费"


def test_payload_contains_no_real_customer_id():
    """payload 会进模型上下文，账号 ID 不该出现在里面。"""
    ops = payload.build_operations(build_draft())
    for op in ops:
        text = str(op.payload)
        assert "{customer_id}" in text or "customers/" not in text


def test_token_is_stable_for_the_same_plan():
    first = payload.submission_token(payload.build_operations(build_draft()))
    second = payload.submission_token(payload.build_operations(build_draft()))
    assert first == second, "同一套方案算出两个 token，幂等就失效了"


def test_token_changes_when_the_plan_changes():
    base = payload.submission_token(payload.build_operations(build_draft()))
    changed = payload.submission_token(
        payload.build_operations(build_draft(daily_budget=250.0))
    )
    assert base != changed, "改了预算 token 却没变，等于放过了偷改方案"


def test_summary_flags_that_images_are_not_submitted():
    draft = build_draft(
        ad_groups=[ad_group(image_urls=["https://example.com/banner.png"], negatives=("免费",))]
    )
    summary = payload.summarize(draft, payload.build_operations(draft))
    assert summary["image_urls_recorded"] == ["https://example.com/banner.png"]
    assert any("AssetService" in note for note in summary["not_covered"])


# ===== 工具层：构造、提交、幂等 =====


def assemble(ctx=None, **overrides):
    args = {
        "campaign_name": "跑鞋-春季-搜索",
        "daily_budget": 200.0,
        "bidding_strategy": "MANUAL_CPC",
        "ad_groups": [ad_group(negatives=("免费",))],
        "max_cpc": 3.0,
    }
    args.update(overrides)
    return tools.assemble_campaign_payload(tool_context=ctx or FakeContext(), **args)


def test_clean_plan_gets_a_submission_token():
    result = assemble()
    assert result["status"] == "success", result
    assert result["submission_token"]


def test_blocked_plan_gets_no_token():
    """没 token 就提交不了——这是「校验没过就发不出去」的机制本身。"""
    result = assemble(daily_budget=99999.0)
    assert result["status"] == "blocked"
    assert result["submission_token"] is None
    assert result["blocking"]


def test_sensitive_word_in_copy_blocks_assembly():
    result = assemble(ad_groups=[ad_group(headlines=["全网最佳跑鞋"] + HEADLINES)])
    assert result["status"] == "blocked"
    assert any("最佳" in item for item in result["blocking"])


def test_shape_errors_are_reported_apart_from_risk_blocks():
    """字段没填齐是模型填错了，和「预算超标」是两回事，不能混着报。"""
    result = assemble(ad_groups=[{"name": "缺东西的组"}])
    assert result["status"] == "error"
    assert result["shape_errors"]
    assert "blocking" not in result


def test_missing_ad_groups_is_a_shape_error():
    result = assemble(ad_groups=[])
    assert result["status"] == "error"
    assert any("广告组" in e for e in result["shape_errors"])


def test_submit_without_a_pending_plan_is_refused():
    strategy_data.reset_ledger()
    result = tools.submit_campaign_payload("deadbeef", tool_context=FakeContext())
    assert result["status"] == "error"
    assert "assemble_campaign_payload" in result["error_message"]


def test_submit_refuses_a_mismatched_token():
    strategy_data.reset_ledger()
    ctx = FakeContext()
    assemble(ctx)
    result = tools.submit_campaign_payload("0000000000000000", tool_context=ctx)
    assert result["status"] == "error"
    assert "令牌不匹配" in result["error_message"]


def test_submit_refuses_when_the_plan_was_edited_after_assembly():
    """偷改会话里的方案再提交，必须被 token 重算挡下。"""
    strategy_data.reset_ledger()
    ctx = FakeContext()
    token = assemble(ctx)["submission_token"]
    ctx.state["pending_submission"]["args"]["daily_budget"] = 250.0
    result = tools.submit_campaign_payload(token, tool_context=ctx)
    assert result["status"] == "error"
    assert "对不上" in result["error_message"]


def test_mock_receipt_says_nothing_was_committed():
    strategy_data.reset_ledger()
    ctx = FakeContext()
    token = assemble(ctx)["submission_token"]
    result = tools.submit_campaign_payload(token, tool_context=ctx)
    assert result["status"] == "success"
    assert result["committed"] is False
    assert "演练" in result["receipt"]["note"]


def test_submitting_twice_does_not_create_twice():
    strategy_data.reset_ledger()
    ctx = FakeContext()
    token = assemble(ctx)["submission_token"]
    first = tools.submit_campaign_payload(token, tool_context=ctx)
    second = tools.submit_campaign_payload(token, tool_context=ctx)
    assert first["receipt"]["idempotent_replay"] is False
    assert second["receipt"]["idempotent_replay"] is True
    assert second["receipt"]["created_resources"] == first["receipt"]["created_resources"]


def test_live_requested_but_not_ready_raises_instead_of_pretending():
    """要求真落盘却条件不齐时，必须报错——拿演练冒充「已提交」比报错危险得多。"""
    strategy_data.reset_ledger()
    draft = build_draft()
    ops = payload.build_operations(draft)
    token = payload.submission_token(ops)
    original = os.environ.get(config.ADS_WRITE_MODE_ENV)
    os.environ[config.ADS_WRITE_MODE_ENV] = config.MODE_LIVE
    try:
        raised = False
        try:
            strategy_data.submit_operations(draft, ops, token)
        except strategy_data.AdsWriteNotReady as exc:
            raised = True
            assert "待办" in str(exc)
        assert raised, "条件不齐却没抛异常，等于悄悄降级成演练"
    finally:
        if original is None:
            os.environ.pop(config.ADS_WRITE_MODE_ENV, None)
        else:
            os.environ[config.ADS_WRITE_MODE_ENV] = original


def test_pause_requires_a_reason():
    result = tools.pause_campaign("春季新品-搜索", "", tool_context=FakeContext())
    assert result["status"] == "error"


def test_pause_in_mock_mode_does_not_actually_pause():
    result = tools.pause_campaign(
        "春季新品-搜索", "消耗速率 1.8 倍触发熔断", tool_context=FakeContext()
    )
    assert result["status"] == "success"
    assert result["committed"] is False
    assert "并没有被真的暂停" in result["result"]["note"]


def test_risk_decision_needs_a_rationale():
    assert (
        tools.record_risk_decision("approved", "", tool_context=FakeContext())["status"]
        == "error"
    )
    assert (
        tools.record_risk_decision("随便", "理由", tool_context=FakeContext())["status"]
        == "error"
    )
    ctx = FakeContext()
    ok = tools.record_risk_decision("blocked", "文案与落地页不符", tool_context=ctx)
    assert ok["status"] == "success"
    assert ctx.state["last_risk_decision"]["decision"] == "blocked"


def test_context_tool_surfaces_upstream_artifacts():
    ctx = FakeContext()
    ctx.state["current_headlines"] = HEADLINES
    ctx.state["keyword_plan"] = {
        "clusters": {"跑鞋": ["男士跑鞋"]},
        "negative_keywords": ["免费"],
    }
    result = tools.get_strategy_context(ctx)
    assert result["upstream"]["validated_headlines"] == HEADLINES
    assert result["upstream"]["keyword_plan_clusters"] == ["跑鞋"]
    assert result["strategy_state"]["has_pending_submission"] is False


# ===== 冷启动熔断 =====


def cold_start_rows(campaign="新广告", days=9, spend_ratio=0.6, ctr=0.03, cvr=0.02):
    """造一段按天的投放数据，方便调出各种冷启动异常。

    最后 COLD_START_DAYS 天是"新广告窗口"，前面的天是基线。
    """
    today = date.today()
    rows = []
    for offset in range(days, 0, -1):
        day = today - timedelta(days=offset)
        in_window = offset <= checks.COLD_START_DAYS
        daily_budget = 100.0
        cost = daily_budget * (spend_ratio if in_window else 0.6)
        this_ctr = ctr if in_window else 0.03
        this_cvr = cvr if in_window else 0.02
        impressions = 5000
        clicks = max(1, round(impressions * this_ctr))
        rows.append(
            AdsRow(
                day=day,
                campaign=campaign,
                impressions=impressions,
                clicks=clicks,
                cost=round(cost, 2),
                conversions=round(clicks * this_cvr),
            )
        )
    return rows


def test_normal_cold_start_does_not_trip():
    result = checks.evaluate_cold_start(cold_start_rows(), daily_budget=100.0)
    assert not result["circuit_breaker_tripped"], result["tripped_rules"]
    assert result["severity"] == "ok"


def test_runaway_spend_trips_the_breaker():
    rows = cold_start_rows(spend_ratio=1.8)
    result = checks.evaluate_cold_start(rows, daily_budget=100.0)
    assert result["circuit_breaker_tripped"]
    assert any(t["rule"] == "spend_rate" for t in result["tripped_rules"])


def test_mild_overspend_is_warning_not_trip():
    rows = cold_start_rows(spend_ratio=1.15)
    result = checks.evaluate_cold_start(rows, daily_budget=100.0)
    assert not result["circuit_breaker_tripped"]
    assert result["severity"] == "warning"


def test_near_zero_ctr_trips_the_breaker():
    rows = cold_start_rows(ctr=0.001)
    result = checks.evaluate_cold_start(rows, daily_budget=100.0)
    assert result["circuit_breaker_tripped"]
    assert any(t["rule"] == "ctr_near_zero" for t in result["tripped_rules"])


def test_zero_conversion_after_heavy_spend_trips():
    rows = cold_start_rows(spend_ratio=0.9, cvr=0.0)
    result = checks.evaluate_cold_start(rows, daily_budget=100.0, target_cpa=20.0)
    assert result["circuit_breaker_tripped"]
    assert any(t["rule"] == "zero_conversion_spend" for t in result["tripped_rules"])


def test_no_data_does_not_crash_and_does_not_trip():
    result = checks.evaluate_cold_start([], daily_budget=100.0)
    assert not result["circuit_breaker_tripped"]
    assert result["status"] == "no_data"


def test_monitor_result_carries_no_executed_action():
    """熔断只产出待批动作。返回值里不该有任何"已执行的写操作"。"""
    rows = cold_start_rows(spend_ratio=1.8)
    result = checks.evaluate_cold_start(rows, daily_budget=100.0)
    assert result["circuit_breaker_tripped"]
    assert "committed" not in result
    assert "暂停不会自动执行" in result["recommended_action"]


# ===== 硬约束：零自动写操作、不外泄凭证 =====


def test_both_write_tools_require_confirmation():
    """守本项目的硬约束：submit 和 pause 必须挂 require_confirmation。

    谁哪天不小心把 FunctionTool 包装解开了，这条立刻变红。
    包装过的工具暴露 .name，没包装的裸函数只有 __name__，两者都要认。
    """
    from ..sub_agents.strategy import strategy_agent

    by_name = {_tool_name(t): t for t in strategy_agent.tools}
    for write_tool in ("submit_campaign_payload", "pause_campaign"):
        tool = by_name[write_tool]
        assert getattr(tool, "_require_confirmation", False) is True, (
            f"{write_tool} 的人工确认被关掉了，零自动写操作这条约束破了"
        )


def test_read_and_review_tools_do_not_require_confirmation():
    """只有写操作要确认。给读操作也挂确认会把用户烦死，属于另一种错。"""
    from ..sub_agents.strategy import strategy_agent

    for tool in strategy_agent.tools:
        if _tool_name(tool) not in ("submit_campaign_payload", "pause_campaign"):
            assert getattr(tool, "_require_confirmation", False) is False, (
                f"{_tool_name(tool)} 是读/审查操作，不该要确认"
            )


def test_scope_and_status_never_leak_credential_values():
    """阈值可以给模型看，凭证的值一个都不能进返回。"""
    scope = tools.list_strategy_scope()
    status = config.ads_write_status()
    blob = str(scope) + str(status)
    # 就算 .env 真填了这些，值也不该出现在返回里
    for key in config._ADS_REQUIRED:
        value = os.environ.get(key, "").strip()
        if value:
            assert value not in blob, f"{key} 的值泄露进了工具返回"
    # 返回里只该有键名
    assert "GOOGLE_ADS_DEVELOPER_TOKEN" in str(status["missing_keys"]) or status[
        "credentials_configured"
    ]


if __name__ == "__main__":
    raise SystemExit(run(globals()))

