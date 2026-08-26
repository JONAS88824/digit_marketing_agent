r"""投放策略与风控工具：strategy_agent 能调用的 9 个工具。

【这一层的分工原则】
和其它三个模块一致：工具负责**取数 + 算准**，模型负责**语义判断**。
本模块的特殊之处是多了一条：**工具还负责"拦"**。

拦的边界要说清楚——
能拦的是有唯一正确答案的事：数值越界、词表命中、正负向词矛盾、消耗速率超标。
拦不了的是语义：一句文案算不算夸大宣传、这个词和产品搭不搭、
落地页内容和广告说的是不是一回事。这些每个工具都会在返回值里点名交还给模型。

【写操作只有两个，而且都要确认】
submit_campaign_payload 和 pause_campaign。它们在 agent.py 里被
FunctionTool(require_confirmation=True) 包了一层，模型调用会被框架拦住等用户点确认。
本文件里的函数体不做确认判断——那是框架的活，写在这里反而会有两套逻辑。
"""

from __future__ import annotations

from datetime import date, timedelta

from google.adk.tools import ToolContext

from ... import config
from ...session_state import remember
from ..creative import metrics as creative_metrics
from ..keywords import data as keywords_data
from ..keywords import metrics as keyword_metrics
from ..performance import data as perf_data
from . import checks, data as strategy_data, payload, rules, schema

# 返回给模型的清单类结果上限。风控结论要能一眼读完，列一百条等于没列。
MAX_ISSUES_RETURNED = 40

# 监控窗口的最大天数。冷启动看的是头两天，翻到一个月就不叫冷启动了。
MAX_MONITOR_DAYS = 14


def list_strategy_scope() -> dict:
    """查询当前风控阀门数值、支持的出价策略、敏感词类目和写入模式。

    做任何审查或提交之前先调本工具，确认阀门是多少、现在是演练还是真落盘。
    **本工具只返回阈值和键名，不返回任何凭证的值。**

    注意：本工具不需要任何参数。
    """
    write_status = config.ads_write_status()
    return {
        "status": "success",
        "write_mode": write_status["effective_mode"],
        "write_mode_requested": write_status["requested_mode"],
        "can_really_write": write_status["ready_for_live"],
        "risk_limits": write_status["risk_limits"],
        "risk_limit_meaning": write_status["risk_limit_meaning"],
        "risk_limit_env_keys": write_status["risk_limit_env_keys"],
        "bidding_strategies": {
            name: {
                "label": spec["label"],
                "must_provide": list(spec["needs"]),
                "may_provide": list(spec["optional"]),
                "note": spec["note"],
            }
            for name, spec in rules.BIDDING_STRATEGIES.items()
        },
        "sensitive_word_categories": list(rules.SENSITIVE_CATEGORIES),
        "sensitive_word_count": len(rules.SENSITIVE_WORD_RULES),
        "campaigns_with_data": list(perf_data.CAMPAIGNS),
        "initial_campaign_status": payload.INITIAL_CAMPAIGN_STATUS,
        "approval_policy": (
            "本 agent 的写操作一律需要用户点确认才执行，**包括熔断触发的暂停**。"
            "不存在任何自动改动账号的路径。"
        ),
        "safety_note": write_status["safety_note"],
    }


def review_budget_and_bidding(
    campaign_name: str,
    daily_budget: float,
    bidding_strategy: str,
    target_cpa: float | None = None,
    target_roas: float | None = None,
    max_cpc: float | None = None,
    other_campaigns_daily_budget: float = 0.0,
    tool_context: ToolContext = None,
) -> dict:
    """校验预算与出价是否越界：日预算、账户合计预算、目标 CPA / ROAS、手动出价。

    这是提交前的第一道闸。返回里每一条都带 actual 和 limit，
    汇报时要把"超了多少"说清楚，不要只说"超了"。

    Args:
        campaign_name: 广告系列名，用于把结论记进会话。
        daily_budget: 单日预算，单位元。
        bidding_strategy: 出价策略。可选值先调 list_strategy_scope 确认。
        target_cpa: 目标每次转化费用（元），TARGET_CPA 策略必填。
        target_roas: 目标 ROAS，用倍数表示（2 即 200%），TARGET_ROAS 策略必填。
        max_cpc: 每次点击最高出价（元），MANUAL_CPC 策略必填。
        other_campaigns_daily_budget: 账户里其它广告系列的日预算合计，
            填了才能算出账户总预算有没有超。不知道就不填。
    """
    limits = config.risk_limits()
    try:
        budget = float(daily_budget)
    except (TypeError, ValueError):
        return {
            "status": "error",
            "error_message": f"daily_budget 必须是数字，收到 {daily_budget!r}。",
        }

    result = checks.review_guardrails(
        daily_budget=budget,
        bidding_strategy=(bidding_strategy or "").strip().upper(),
        limits=limits,
        target_cpa=target_cpa,
        target_roas=target_roas,
        max_cpc=max_cpc,
        other_campaigns_daily_budget=other_campaigns_daily_budget or 0.0,
    )

    remember(
        tool_context,
        current_campaign_draft_name=campaign_name,
        current_daily_budget=budget,
        last_guardrail_passed=result["passed"],
    )
    return {
        "status": "success" if result["passed"] else "blocked",
        "campaign_name": campaign_name,
        "passed": result["passed"],
        "blocking": result["blocking"][:MAX_ISSUES_RETURNED],
        "warnings": result["warnings"][:MAX_ISSUES_RETURNED],
        "all_checks": result["checks"],
        "limits_applied": result["limits_applied"],
        "next_step": (
            "预算与出价这一关过了，接着调 screen_policy_compliance 查文案和关键词。"
            if result["passed"]
            else "有拦截项。把每条的 actual 和 limit 原样告诉用户，"
            "让用户决定是改方案还是改 .env 里的阀门——**不要自己绕过校验**。"
        ),
    }


def screen_policy_compliance(
    headlines: list[str],
    descriptions: list[str],
    keywords: list[str] | None = None,
    negative_keywords: list[str] | None = None,
    tool_context: ToolContext = None,
) -> dict:
    """合规审查：敏感词、绝对化用语、侵权仿品词、文案字符与内容规则、关键词负向规则。

    这是提交前的第二道闸。**过了不等于一定能过审**——词表只能抓字面硬伤。
    返回里的 your_turn 列出了必须由你自己读一遍才能判断的三类问题。

    Args:
        headlines: 广告标题列表。
        descriptions: 广告描述列表。
        keywords: 投放关键词列表。不填则不查关键词。
        negative_keywords: 负向词列表。不填则不查。
    """
    if not headlines or not descriptions:
        return {
            "status": "error",
            "error_message": "标题和描述都不能为空，先让 creative_agent 出文案。",
        }

    keywords = keywords or []
    negative_keywords = negative_keywords or []

    # ---- 敏感词：扫全部部位，包括关键词（词本身违规同样会被拒审）----
    sensitive = checks.scan_sensitive_words(
        {
            "标题": headlines,
            "描述": descriptions,
            "关键词": keywords,
            "负向词": negative_keywords,
        }
    )

    # ---- 文案字符数与内容红线：直接复用 creative 那套，不重写一遍 ----
    copy_result = creative_metrics.validate_rsa(headlines, descriptions)

    # ---- 关键词命中负向规则库：复用 keywords 那套 ----
    keyword_rule_hits = []
    for keyword in keyword_metrics.dedupe(keywords):
        hits = keyword_metrics.match_negative_rules(
            keyword, keywords_data.NEGATIVE_KEYWORD_RULES
        )
        if hits:
            keyword_rule_hits.append(
                {
                    "keyword": keyword,
                    "matched_words": [h["word"] for h in hits],
                    "categories": sorted({h["category"] for h in hits}),
                    "reason": hits[0]["reason"],
                }
            )

    blocking_count = len(sensitive["blocking_hits"]) + (
        0 if copy_result["ready_to_submit"] else 1
    )
    passed = blocking_count == 0

    remember(tool_context, last_policy_passed=passed)
    return {
        "status": "success" if passed else "blocked",
        "passed": passed,
        "sensitive_words": {
            "blocking_hits": sensitive["blocking_hits"][:MAX_ISSUES_RETURNED],
            "warning_hits": sensitive["warning_hits"][:MAX_ISSUES_RETURNED],
            "categories_hit": sensitive["categories_hit"],
        },
        "ad_copy": {
            "ready_to_submit": copy_result["ready_to_submit"],
            "over_limit_texts": copy_result["over_limit_texts"][:MAX_ISSUES_RETURNED],
            "structure_issues": copy_result["structure_issues"],
            "warnings": copy_result["warnings"][:MAX_ISSUES_RETURNED],
        },
        "keyword_rule_hits": keyword_rule_hits[:MAX_ISSUES_RETURNED],
        "your_turn": (
            "以上都是字面层面能查的。**这三类词表查不到，必须你自己逐条读一遍判断**："
            "(1) 夸大宣传——把没有依据的效果说成事实；"
            "(2) 与落地页不符——文案承诺的内容页面上根本没有；"
            "(3) 语气过度承诺——没用违禁词但读起来像在保证结果。"
            "命中任何一条都要在汇报里点名，不要因为工具没报就说「合规没问题」。"
        ),
        "next_step": (
            "合规这一关过了，可以调 assemble_campaign_payload 构造提交结构。"
            if passed
            else "先按 blocking_hits 和 over_limit_texts 改，改完重新调本工具。"
        ),
    }


def _full_review(draft: schema.CampaignDraft, other_campaigns_daily_budget: float) -> dict:
    """把三道闸一次跑全：预算出价、合规词表、逻辑矛盾。

    assemble 和 submit 都要用它。提交时**重跑一遍**不是多余的：
    会话状态可能被上一轮改过、阀门可能刚被改小，
    真正落盘前必须以当下的规则再判一次。
    """
    limits = config.risk_limits()
    guardrails = checks.review_guardrails(
        daily_budget=draft.daily_budget,
        bidding_strategy=draft.bidding_strategy,
        limits=limits,
        target_cpa=draft.target_cpa,
        target_roas=draft.target_roas,
        max_cpc=draft.max_cpc,
        ad_group_max_cpcs=tuple(
            (g.name, g.max_cpc) for g in draft.ad_groups if g.max_cpc is not None
        ),
        other_campaigns_daily_budget=other_campaigns_daily_budget,
    )

    sections: dict[str, list[str]] = {"标题": [], "描述": [], "关键词": [], "负向词": []}
    copy_issues: list[dict] = []
    for group in draft.ad_groups:
        sections["标题"].extend(group.ad.headlines)
        sections["描述"].extend(group.ad.descriptions)
        sections["关键词"].extend(group.keywords)
        sections["负向词"].extend(group.negative_keywords)
        copy_result = creative_metrics.validate_rsa(
            list(group.ad.headlines), list(group.ad.descriptions)
        )
        if not copy_result["ready_to_submit"]:
            copy_issues.append(
                {
                    "ad_group": group.name,
                    "over_limit_texts": copy_result["over_limit_texts"],
                    "structure_issues": copy_result["structure_issues"],
                }
            )

    sensitive = checks.scan_sensitive_words(sections)
    logic = checks.check_logic(draft.ad_groups)

    blocking: list[str] = []
    blocking += [c["message"] for c in guardrails["blocking"]]
    blocking += [
        f"{h['section']}「{h['text']}」命中{h['category']}词「{h['word']}」：{h['reason']}"
        for h in sensitive["blocking_hits"]
    ]
    blocking += [i["detail"] for i in logic["blocking"]]
    blocking += [
        f"广告组「{item['ad_group']}」的文案没过字符或结构校验，先回 creative_agent 修"
        for item in copy_issues
    ]

    warnings: list[str] = []
    warnings += [c["message"] for c in guardrails["warnings"]]
    warnings += [
        f"{h['section']}「{h['text']}」命中{h['category']}词「{h['word']}」（需人工判断）：{h['reason']}"
        for h in sensitive["warning_hits"]
    ]
    warnings += [i["detail"] for i in logic["warnings"]]

    return {
        "passed": not blocking,
        "blocking": blocking[:MAX_ISSUES_RETURNED],
        "warnings": warnings[:MAX_ISSUES_RETURNED],
        "guardrails": guardrails,
        "sensitive_words": sensitive,
        "logic": logic,
        "copy_issues": copy_issues,
        "limits_applied": limits,
    }


def assemble_campaign_payload(
    campaign_name: str,
    daily_budget: float,
    bidding_strategy: str,
    ad_groups: list[dict],
    target_cpa: float | None = None,
    target_roas: float | None = None,
    max_cpc: float | None = None,
    other_campaigns_daily_budget: float = 0.0,
    tool_context: ToolContext = None,
) -> dict:
    """把方案构造成 Google Ads Mutate 操作结构，构造前先跑完全部风控校验。

    **只有全部校验通过才会返回 submission_token**，没有 token 就没法提交。
    这是刻意的：拿不到 token 说明方案还不能上，去改方案，不要绕。

    本工具**不会**改动账号，它只是把结构算出来给你和用户看。

    Args:
        campaign_name: 广告系列名。
        daily_budget: 单日预算（元）。
        bidding_strategy: 出价策略，先调 list_strategy_scope 确认可选值。
        ad_groups: 广告组列表，每个元素是一个对象，字段如下：
            name（广告组名，必填）、keywords（关键词列表，必填）、
            headlines（标题列表，必填）、descriptions（描述列表，必填）、
            final_url（落地页地址，必填）、negative_keywords（负向词列表，选填）、
            max_cpc（该组的点击出价，选填）、paths（展示路径，最多 2 段，选填）、
            image_urls（图片素材地址，选填，本版本只记录不提交）。
        target_cpa: 目标每次转化费用（元）。
        target_roas: 目标 ROAS（倍数）。
        max_cpc: 系列级点击出价上限（元）。
        other_campaigns_daily_budget: 账户里其它系列的日预算合计。
    """
    draft, shape_errors = schema.parse_campaign(
        campaign_name=campaign_name,
        daily_budget=daily_budget,
        bidding_strategy=bidding_strategy,
        ad_groups=ad_groups,
        target_cpa=target_cpa,
        target_roas=target_roas,
        max_cpc=max_cpc,
    )
    if draft is None:
        return {
            "status": "error",
            "error_message": "方案的结构不完整，还没到风控校验这一步。",
            "shape_errors": shape_errors[:MAX_ISSUES_RETURNED],
            "hint": (
                "这些是**填写问题**不是风控拦截：把缺的字段补齐再调一次。"
                "缺文案找 creative_agent，缺关键词分组找 keyword_agent。"
            ),
        }

    review = _full_review(draft, other_campaigns_daily_budget or 0.0)
    if not review["passed"]:
        remember(tool_context, pending_submission=None, last_review_passed=False)
        return {
            "status": "blocked",
            "passed": False,
            "campaign_name": draft.name,
            "blocking": review["blocking"],
            "warnings": review["warnings"],
            "submission_token": None,
            "next_step": (
                "有拦截项，**没有生成 submission_token，所以现在提交不了**。"
                "把每条原样告诉用户，说清是改方案还是改 .env 阀门，改完重新调本工具。"
            ),
        }

    ops = payload.build_operations(draft)
    token = payload.submission_token(ops)
    summary = payload.summarize(draft, ops)

    remember(
        tool_context,
        pending_submission={
            "token": token,
            "args": {
                "campaign_name": campaign_name,
                "daily_budget": daily_budget,
                "bidding_strategy": bidding_strategy,
                "ad_groups": ad_groups,
                "target_cpa": target_cpa,
                "target_roas": target_roas,
                "max_cpc": max_cpc,
                "other_campaigns_daily_budget": other_campaigns_daily_budget or 0.0,
            },
        },
        last_review_passed=True,
        current_campaign_draft_name=draft.name,
    )
    return {
        "status": "success",
        "passed": True,
        "submission_token": token,
        "payload_summary": summary,
        "warnings": review["warnings"],
        "write_mode": config.ads_write_status()["effective_mode"],
        "next_step": (
            "校验全过了。**先把要创建什么、花多少钱、以什么状态创建讲给用户听，"
            "问他要不要提交**；用户同意后再调 submit_campaign_payload，"
            "那一步框架还会再弹一次确认。"
        ),
    }


def submit_campaign_payload(
    submission_token: str, tool_context: ToolContext = None
) -> dict:
    """【需用户确认】把已通过校验的方案提交到 Google Ads 账户。

    调用前必须先调 assemble_campaign_payload 拿到 submission_token。
    本工具会**重新跑一遍全部校验并重算 token**：方案被改过、阀门被改小、
    或者 token 对不上，都会拒绝提交而不是勉强提交。

    幂等：同一个 token 提交两次，第二次不会重复创建，只返回上次回执。

    Args:
        submission_token: assemble_campaign_payload 返回的令牌，原样传回来。
    """
    state = tool_context.state if tool_context else {}
    pending = state.get("pending_submission")
    if not pending:
        return {
            "status": "error",
            "error_message": (
                "会话里没有待提交的方案。先调 assemble_campaign_payload 构造并通过校验。"
            ),
        }
    if not submission_token or submission_token != pending["token"]:
        return {
            "status": "error",
            "error_message": (
                f"令牌不匹配：待提交的是 {pending['token']}，你传的是 {submission_token!r}。"
                "不要自己编令牌，原样使用 assemble_campaign_payload 返回的那一个。"
            ),
        }

    args = pending["args"]
    draft, shape_errors = schema.parse_campaign(
        campaign_name=args["campaign_name"],
        daily_budget=args["daily_budget"],
        bidding_strategy=args["bidding_strategy"],
        ad_groups=args["ad_groups"],
        target_cpa=args["target_cpa"],
        target_roas=args["target_roas"],
        max_cpc=args["max_cpc"],
    )
    if draft is None:
        return {
            "status": "error",
            "error_message": "会话里存的方案已经不完整了，请重新构造。",
            "shape_errors": shape_errors[:MAX_ISSUES_RETURNED],
        }

    # 落盘前的最后一次复核。阀门可能在这期间被改小，必须以当下规则为准。
    review = _full_review(draft, args.get("other_campaigns_daily_budget") or 0.0)
    if not review["passed"]:
        return {
            "status": "blocked",
            "error_message": "重新校验没通过，已拒绝提交。",
            "blocking": review["blocking"],
            "hint": "阀门或方案在构造之后发生了变化。修好后重新调 assemble_campaign_payload。",
        }

    ops = payload.build_operations(draft)
    recomputed = payload.submission_token(ops)
    if recomputed != submission_token:
        return {
            "status": "error",
            "error_message": (
                f"方案内容和令牌对不上（重算得到 {recomputed}）。"
                "说明方案在构造之后被改过，请重新调 assemble_campaign_payload。"
            ),
        }

    try:
        receipt = strategy_data.submit_operations(draft, ops, submission_token)
    except strategy_data.AdsWriteNotReady as exc:
        return {
            "status": "error",
            "error_message": str(exc),
            "hint": (
                "你要求的是真落盘（ADS_WRITE_MODE=live），但条件不齐，所以**什么都没做**。"
                "不要退回演练模式假装提交成功，把待办如实告诉用户。"
            ),
        }

    remember(tool_context, last_submission=receipt)
    return {
        "status": "success",
        "receipt": receipt,
        "committed": receipt["committed"],
        "report_requirement": (
            "汇报时必须说清三件事：(1) 这次是演练还是真落盘（看 committed）；"
            f"(2) 广告系列以 {payload.INITIAL_CAMPAIGN_STATUS} 状态创建，不会自动开始花钱；"
            "(3) 接下来 48 小时要用 monitor_new_campaign 盯冷启动。"
            "**committed 是 false 时绝对不能说「已经建好了」。**"
        ),
    }


def monitor_new_campaign(
    campaign: str,
    daily_budget: float,
    days: int = 2,
    target_cpa: float | None = None,
    tool_context: ToolContext = None,
) -> dict:
    """新广告冷启动护航：查异常消耗速率、CTR 近零、CPC 飙升、零转化烧钱，判断是否该熔断。

    **本工具只读不写。** 即使熔断触发，也不会自动暂停任何东西——
    要暂停必须你先告诉用户、用户同意后再调 pause_campaign。

    Args:
        campaign: 广告系列名。可选值先调 list_strategy_scope 看 campaigns_with_data。
        daily_budget: 这个系列的日预算（元）。消耗速率以它为分母，填错会误判。
        days: 护航窗口天数，默认 2 天（约 48 小时），最多 14 天。
        target_cpa: 目标 CPA（元）。有它才能判「花了多少还零转化」，没有就退回按日预算判。
    """
    if campaign not in perf_data.CAMPAIGNS:
        return {
            "status": "error",
            "error_message": (
                f"没有名为 {campaign} 的广告系列。"
                f"可用：{'、'.join(perf_data.CAMPAIGNS)}。"
            ),
        }
    try:
        budget = float(daily_budget)
    except (TypeError, ValueError):
        return {
            "status": "error",
            "error_message": f"daily_budget 必须是数字，收到 {daily_budget!r}。",
        }
    if budget <= 0:
        return {"status": "error", "error_message": "daily_budget 必须大于 0。"}

    window = max(1, min(int(days or 1), MAX_MONITOR_DAYS))
    # 多取一段历史当基线，才能判断 CPC 是不是相对以前飙了
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=window + 7)
    try:
        rows = perf_data.fetch_ads_rows(start, end, campaign)
    except perf_data.DataSourceNotReady as exc:
        return {"status": "error", "error_message": str(exc)}

    result = checks.evaluate_cold_start(
        rows, daily_budget=budget, target_cpa=target_cpa, window_days=window
    )
    remember(
        tool_context,
        current_campaign=campaign,
        current_daily_budget=budget,
        last_monitor_severity=result.get("severity"),
    )
    return {
        "status": "success",
        "campaign": campaign,
        **result,
        "data_caveat": (
            f"当前投放数据来源是 "
            f"{'真实 Google Ads API' if config.is_live(config.SOURCE_ADS) else '内置演示数据'}。"
            "演示数据下的熔断结论只用来验证机制，不能当真实账户的判断。"
        ),
        "no_auto_action": (
            "本工具没有、也不会自动暂停任何广告系列。"
            "熔断触发时你要做的是：把触发的规则和数字讲给用户，问他要不要暂停。"
        ),
    }


def pause_campaign(
    campaign: str, reason: str, tool_context: ToolContext = None
) -> dict:
    """【需用户确认】暂停一个广告系列，用于熔断止损。

    调用前必须已经把熔断原因讲给用户、并且用户同意暂停。
    框架还会再拦一次等用户点确认——**不存在自动暂停的路径**。

    Args:
        campaign: 要暂停的广告系列名。
        reason: 为什么要暂停。请写具体触发了哪条规则、数字是多少，
            这句话会进回执，是事后复盘唯一的依据。
    """
    if not campaign or not campaign.strip():
        return {"status": "error", "error_message": "campaign 不能为空。"}
    if not reason or not reason.strip():
        return {
            "status": "error",
            "error_message": (
                "reason 不能为空。暂停广告是有代价的动作，"
                "必须留下「因为什么暂停」，否则事后没人说得清该不该恢复。"
            ),
        }

    try:
        result = strategy_data.pause_campaign(campaign.strip(), reason.strip())
    except strategy_data.AdsWriteNotReady as exc:
        return {
            "status": "error",
            "error_message": str(exc),
            "hint": "你要求真落盘但条件不齐，所以**什么都没做**，广告仍在投。如实告诉用户。",
        }

    remember(tool_context, last_pause_request={"campaign": campaign, "reason": reason})
    return {
        "status": "success",
        "result": result,
        "committed": result["committed"],
        "report_requirement": (
            "committed 为 false 时说明这只是演练，**广告还在正常投放**，"
            "必须明确告诉用户「还没真的暂停」以及需要做什么才能真的暂停。"
        ),
    }


def get_strategy_context(tool_context: ToolContext) -> dict:
    """查询会话里的上游方案与本轮风控状态，用来接省略句。

    用户说「提交吧」「那个方案怎么样」「暂停它」时，先调本工具找回对象，
    不要反问用户重新说一遍。

    返回里的 upstream 是另外三个专员留下的成果（关键词方案、已校验的文案），
    可以直接拿来填 assemble_campaign_payload。

    注意：本工具不需要任何参数。
    """
    state = tool_context.state if tool_context else {}
    plan = state.get("keyword_plan")
    pending = state.get("pending_submission")
    return {
        "status": "success",
        "upstream": {
            "current_product": state.get("current_product"),
            "keyword_plan_clusters": list(plan["clusters"]) if plan else None,
            "keyword_plan_negative_count": len(plan["negative_keywords"]) if plan else None,
            "keyword_plan": plan,
            "validated_headlines": state.get("current_headlines"),
            "validated_descriptions": state.get("current_descriptions"),
        },
        "strategy_state": {
            "current_campaign_draft_name": state.get("current_campaign_draft_name"),
            "current_daily_budget": state.get("current_daily_budget"),
            "last_guardrail_passed": state.get("last_guardrail_passed"),
            "last_policy_passed": state.get("last_policy_passed"),
            "last_review_passed": state.get("last_review_passed"),
            "has_pending_submission": pending is not None,
            "pending_token": pending["token"] if pending else None,
            "last_submission": state.get("last_submission"),
            "last_monitor_severity": state.get("last_monitor_severity"),
            "last_risk_decision": state.get("last_risk_decision"),
        },
        "hint": (
            "validated_headlines / validated_descriptions 为空说明文案还没过 creative_agent "
            "的字符校验，不要拿没校验过的文案去提交。"
            "keyword_plan 为空说明还没有关键词方案，先让 keyword_agent 出。"
        ),
    }


def record_risk_decision(
    decision: str, rationale: str, tool_context: ToolContext = None
) -> dict:
    """记录这次风控结论：放行、拦下、还是带条件放行，以及理由。

    有拦截项却决定继续，或者工具说通过但你自己判断有问题，都要用本工具记一笔。
    这是事后复盘唯一的线索——尤其是那些工具查不出、靠你判断的问题。

    Args:
        decision: approved（放行）/ blocked（拦下）/ approved_with_conditions（带条件放行）。
        rationale: 为什么这么判。工具没查到但你判断有问题的地方，写在这里。
    """
    allowed = ("approved", "blocked", "approved_with_conditions")
    normalized = (decision or "").strip().lower()
    if normalized not in allowed:
        return {
            "status": "error",
            "error_message": f"decision 只能是：{'、'.join(allowed)}。",
        }
    if not rationale or not rationale.strip():
        return {
            "status": "error",
            "error_message": "rationale 不能为空——没有理由的结论事后没法复盘。",
        }

    record = {"decision": normalized, "rationale": rationale.strip()}
    remember(tool_context, last_risk_decision=record)
    return {
        "status": "success",
        "recorded": record,
        "note": "已记入会话。汇报时把这条结论和理由一起讲给用户。",
    }
