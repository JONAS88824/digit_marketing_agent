"""关键词规划工具：keyword_agent 能调用的 7 个工具。

【这一层的分工原则】
工具负责**取数 + 算准**，模型负责**语义判断**。
所以你会看到 analyze_keyword_structure 只给出"词根分组、重复项、跨来源重叠、
命中的负向规则"这些确定性结果，然后明确把"该怎么聚类、哪些长尾值得拓展"
留给模型——因为那没有唯一正确答案，Python 硬算只会算出一个假精确。
"""

from __future__ import annotations

from google.adk.tools import ToolContext

from . import keywords, keywords_data

# 单次返回给模型的关键词上限。太多会挤爆上下文，也没人读得完。
MAX_KEYWORDS_RETURNED = 60

# 可选的用户意图，与 keywords_data 的修饰词分组一致
INTENTS = (
    "transactional",
    "commercial",
    "informational",
    "navigational",
    "negative_signal",
)

_INTENT_MEANING = {
    "transactional": "交易意图：想买了，最值钱",
    "commercial": "商业调研：在比较选择，还没决定",
    "informational": "信息意图：只想了解，转化很低",
    "navigational": "导航意图：找特定品牌或官网",
    "negative_signal": "疑似无效流量：可能该加进负向词",
}


def _idea_to_dict(idea: keywords_data.KeywordIdea, with_trend: bool = False) -> dict:
    """把关键词对象转成模型友好的 dict。趋势序列很占篇幅，默认不带。"""
    row = {
        "keyword": idea.text,
        "intent": idea.intent,
        "core": idea.core,
        "avg_monthly_searches": idea.avg_monthly_searches,
        "competition": idea.competition,
        "competition_index": idea.competition_index,
        "avg_cpc": idea.avg_cpc,
        "top_of_page_bid_range": [idea.low_top_of_page_bid, idea.high_top_of_page_bid],
    }
    if with_trend:
        row["trend"] = keywords.summarize_trend(idea.monthly_volumes)
    return row


def _remember(tool_context: ToolContext | None, **kwargs) -> None:
    if not tool_context:
        return
    for key, value in kwargs.items():
        if value is not None:
            tool_context.state[key] = value


def list_keyword_scope() -> dict:
    """查询可以规划哪些行业、哪些产品词，以及有哪些竞品和意图分类。

    开始关键词规划前先调用本工具，确认行业名和产品词的准确写法，不要凭猜测填。

    注意：本工具不需要任何参数。
    """
    return {
        "status": "success",
        "industries": {
            industry: list(cores)
            for industry, cores in keywords_data.INDUSTRY_CORES.items()
        },
        "competitors": list(keywords_data.COMPETITORS),
        "intents": _INTENT_MEANING,
        "negative_rule_words": [r["word"] for r in keywords_data.NEGATIVE_KEYWORD_RULES],
        "note": (
            "intent 是本项目按修饰词规则标注的近似值，不是 Google 提供的官方字段。"
            "遇到标注明显不合理的词，以你自己的语义判断为准。"
        ),
    }


def plan_keywords(
    industry: str | None = None,
    product: str | None = None,
    intent: str | None = None,
    min_monthly_searches: int = 0,
    tool_context: ToolContext = None,
) -> dict:
    """按行业或产品规划关键词，返回搜索量、CPC、竞争度和首页出价区间。

    这是关键词规划的第一步：先把候选词捞出来，再谈聚类和取舍。

    Args:
        industry: 行业名，如 '运动户外'。不确定写法就先调 list_keyword_scope。
        product: 产品词，如 '跑鞋'。填了就只看含这个词的关键词。
        intent: 只看某种用户意图，可选 transactional / commercial /
            informational / navigational / negative_signal。不填则全都看。
        min_monthly_searches: 过滤掉月搜索量低于这个数的词，默认不过滤。
    """
    if intent and intent not in INTENTS:
        return {
            "status": "error",
            "error_message": f"不支持的意图 {intent}。可选：{'、'.join(INTENTS)}。",
        }
    if industry and industry not in keywords_data.INDUSTRY_CORES:
        return {
            "status": "error",
            "error_message": (
                f"没有名为 {industry} 的行业。"
                f"可用行业：{'、'.join(keywords_data.INDUSTRY_CORES)}。"
            ),
        }

    try:
        ideas = keywords_data.fetch_keyword_ideas(
            industry=industry, product=product, intents=(intent,) if intent else None
        )
    except keywords_data.KeywordSourceNotReady as exc:
        return {"status": "error", "error_message": str(exc)}

    ideas = [i for i in ideas if i.avg_monthly_searches >= min_monthly_searches]
    if not ideas:
        return {
            "status": "error",
            "error_message": (
                "没有符合条件的关键词。试试放宽 min_monthly_searches，"
                "或换个行业/产品词。"
            ),
        }

    ideas.sort(key=lambda i: -i.avg_monthly_searches)
    truncated = len(ideas) > MAX_KEYWORDS_RETURNED
    shown = ideas[:MAX_KEYWORDS_RETURNED]

    _remember(
        tool_context,
        current_industry=industry,
        current_product=product,
        current_keywords=[i.text for i in shown],
    )
    return {
        "status": "success",
        "source": "keyword_planner",
        "industry": industry or "全部行业",
        "product": product or "全部产品",
        "total_matched": len(ideas),
        "returned": len(shown),
        "truncated": truncated,
        "keywords": [_idea_to_dict(i) for i in shown],
        "hint": (
            "avg_cpc 单位是元；competition 为 HIGH 说明抢的人多、出价会被推高。"
            "接下来可以调 analyze_keyword_structure 拿到分组原料，再由你做语义聚类。"
        )
        + ("（结果已截断，只返回搜索量最高的部分）" if truncated else ""),
    }


def forecast_keywords(
    keywords_list: list[str],
    share_of_voice: float = 0.3,
    tool_context: ToolContext = None,
) -> dict:
    """预测一批关键词的搜索量趋势与投放成本：预计点击数、月花费、平均 CPC。

    同时给出每个词的搜索量趋势（在涨还是在跌、旺季是哪个月），
    用来判断这批词值不值得现在投、什么时候加预算。

    Args:
        keywords_list: 要预测的关键词列表。
        share_of_voice: 预期曝光占有率，0~1。默认 0.3 表示只吃到三成搜索量。
            预算充足想全量覆盖才填 1.0，否则会高估点击数。
    """
    cleaned = keywords.dedupe(keywords_list)
    if not cleaned:
        return {"status": "error", "error_message": "关键词列表是空的。"}

    try:
        universe = keywords_data.fetch_keyword_ideas()
    except keywords_data.KeywordSourceNotReady as exc:
        return {"status": "error", "error_message": str(exc)}

    by_text = {keywords.normalize(i.text): i for i in universe}
    matched = [by_text[k] for k in (keywords.normalize(c) for c in cleaned) if k in by_text]
    unknown = [c for c in cleaned if keywords.normalize(c) not in by_text]

    if not matched:
        return {
            "status": "error",
            "error_message": (
                "这些词都不在关键词库里，查不到搜索量和 CPC，无法预测："
                f"{'、'.join(unknown[:10])}。"
            ),
        }

    estimate = keywords.estimate_cost(matched, share_of_voice=share_of_voice)
    _remember(tool_context, current_keywords=[i.text for i in matched])
    return {
        "status": "success",
        "source": "keyword_planner",
        "cost_forecast": estimate,
        "per_keyword_trend": [
            {
                "keyword": i.text,
                "avg_monthly_searches": i.avg_monthly_searches,
                "avg_cpc": i.avg_cpc,
                **keywords.summarize_trend(i.monthly_volumes),
            }
            for i in matched[:MAX_KEYWORDS_RETURNED]
        ],
        "unknown_keywords": unknown,
        "hint": (
            "花费是**预估**，依赖假设点击率，必须向用户说明这不是承诺值。"
            "direction=rising 的词值得提前布局，falling 的词要谨慎加预算；"
            "seasonality_ratio 越大说明越吃季节性，要按旺季排预算节奏。"
        ),
    }


def get_competitor_keywords(
    competitor: str | None = None,
    my_keywords: list[str] | None = None,
    tool_context: ToolContext = None,
) -> dict:
    """查竞品在投的关键词，并可与我方词表对比，找出机会缺口。

    Args:
        competitor: 竞品名。不填则看全部竞品。不确定写法先调 list_keyword_scope。
        my_keywords: 我方当前在投的词。填了才会算出"只有竞品在投"的缺口词。
    """
    if competitor and competitor not in keywords_data.COMPETITORS:
        return {
            "status": "error",
            "error_message": (
                f"没有名为 {competitor} 的竞品。"
                f"可选：{'、'.join(keywords_data.COMPETITORS)}。"
            ),
        }

    try:
        rows = keywords_data.fetch_competitor_keywords(competitor)
    except keywords_data.KeywordSourceNotReady as exc:
        return {"status": "error", "error_message": str(exc)}

    if not rows:
        return {"status": "error", "error_message": "没有查到竞品投放数据。"}

    # 曝光占有率高的词才是竞品真正重仓的，优先看这些
    ranked = sorted(rows, key=lambda r: -r.visibility_pct)[:MAX_KEYWORDS_RETURNED]
    result = {
        "status": "success",
        "source": "competitor_intel",
        "competitor": competitor or "全部竞品",
        "total_keywords": len(rows),
        "top_keywords": [
            {
                "keyword": r.text,
                "competitor": r.competitor,
                "estimated_position": r.estimated_position,
                "visibility_pct": r.visibility_pct,
                "estimated_cpc": r.estimated_cpc,
            }
            for r in ranked
        ],
        "data_caveat": (
            "第三方情报是**估算值**，不是竞品账户的真实数据。"
            "位置和 CPC 都有误差，只能判断方向（它在抢哪类词），不能当精确数字引用。"
        ),
    }

    if my_keywords:
        comparison = keywords.compare_sets(my_keywords, [r.text for r in rows])
        result["gap_analysis"] = {
            "both_bidding": comparison["overlap"][:MAX_KEYWORDS_RETURNED],
            "only_i_bid": comparison["only_mine"][:MAX_KEYWORDS_RETURNED],
            "only_competitor_bids": comparison["only_theirs"][:MAX_KEYWORDS_RETURNED],
            "my_coverage_pct": comparison["overlap_pct"],
        }
        result["hint"] = (
            "only_competitor_bids 是机会缺口，但**不要无脑全抄**——"
            "竞品的产品线和利润结构可能和我们不同。要结合意图和转化数据判断。"
        )

    _remember(tool_context, current_competitor=competitor)
    return result


def get_seo_queries(
    min_impressions: int = 100, tool_context: ToolContext = None
) -> dict:
    """查 Search Console 里的自然搜索词：点击、曝光、点击率、平均排名。

    自然搜索词的价值在于它是"用户真实说的话"，而且免费。
    典型用法：自然排名已经很好的词可以少投付费；曝光高但排名差的词考虑用付费补位。

    Args:
        min_impressions: 过滤掉曝光低于这个数的词，默认 100。
    """
    try:
        rows = keywords_data.fetch_seo_queries(limit=500)
    except keywords_data.KeywordSourceNotReady as exc:
        return {"status": "error", "error_message": str(exc)}

    filtered = [r for r in rows if r.impressions >= min_impressions]
    if not filtered:
        return {
            "status": "error",
            "error_message": f"没有曝光 ≥ {min_impressions} 的自然搜索词，试试调低这个门槛。",
        }

    shown = filtered[:MAX_KEYWORDS_RETURNED]
    _remember(tool_context, current_seo_queries=[r.query for r in shown])
    return {
        "status": "success",
        "source": "search_console",
        "total_matched": len(filtered),
        "queries": [
            {
                "query": r.query,
                "clicks": r.clicks,
                "impressions": r.impressions,
                "ctr_pct": r.ctr_pct,
                "position": r.position,
            }
            for r in shown
        ],
        "data_caveat": (
            "Search Console 会把搜索量过少的词**匿名化隐去**以保护隐私，"
            "所以这里所有词的点击加起来一定小于站点总点击，缺的部分翻页也拿不回来。"
            "另外数据有 2~3 天延迟，最近几天可能还会变。"
        ),
        "hint": (
            "position 是平均排名，数字越小越好。"
            "排名 1~3 且点击多的词，付费投放可能是重复花钱；"
            "曝光高但排名 >10 的词，是付费补位的好机会。"
        ),
    }


def get_converting_search_terms(
    min_conversions: int = 1, tool_context: ToolContext = None
) -> dict:
    """查 GA4 里实际带来转化的搜索词，做转化归因。

    这是四个数据源里唯一的**事实**——其他三个都是"预估"和"机会"。
    所以关键词规划应该以它为锚：真实转化过的词优先保、优先加价，
    而不是只看搜索量大就去抢。

    Args:
        min_conversions: 只看转化数不低于这个值的词，默认 1（即至少转化过一次）。
    """
    try:
        rows = keywords_data.fetch_converting_terms(limit=500)
    except keywords_data.KeywordSourceNotReady as exc:
        return {"status": "error", "error_message": str(exc)}

    filtered = [r for r in rows if r.conversions >= min_conversions]
    if not filtered:
        return {
            "status": "error",
            "error_message": f"没有转化数 ≥ {min_conversions} 的搜索词。",
        }

    shown = filtered[:MAX_KEYWORDS_RETURNED]
    total_conversions = sum(r.conversions for r in filtered)
    total_revenue = round(sum(r.revenue for r in filtered), 2)

    _remember(tool_context, current_converting_terms=[r.term for r in shown])
    return {
        "status": "success",
        "source": "ga4",
        "total_matched": len(filtered),
        "total_conversions": total_conversions,
        "total_revenue": total_revenue,
        "terms": [
            {
                "term": r.term,
                "sessions": r.sessions,
                "conversions": r.conversions,
                "revenue": r.revenue,
                # 转化率在这里算，不让模型口算
                "cvr_pct": round(r.conversions / r.sessions * 100, 2) if r.sessions else None,
                "revenue_per_session": round(r.revenue / r.sessions, 2) if r.sessions else None,
            }
            for r in shown
        ],
        "data_caveat": (
            "GA4 对用户数过少的行会做**阈值过滤**整行隐去；"
            "关键词是高基数维度，长尾词会被并进 (other) 行。"
            "所以这里看到的是转化的主力部分，不是全貌。"
        ),
        "hint": (
            "cvr_pct 高但 sessions 少的词，是值得加预算放量的；"
            "sessions 多但 cvr_pct 极低的词，要考虑降价或加负向词。"
        ),
    }


def analyze_keyword_structure(
    keywords_list: list[str], tool_context: ToolContext = None
) -> dict:
    """给一批关键词做**确定性**的结构分析：词根分组、重复项、命中的负向规则、跨来源覆盖。

    **本工具不做语义聚类。** 它只提供原料：
    - 词根分组只能看出"字面上带同一个产品词"
    - 负向规则只能命中明确的坏词（免费、二手、招聘…）

    拿到这些原料后，**由你来做语义判断**：
    1. 词根聚类：把同一种用户需求的词归到一组（字面不同也可能同义）
    2. 长尾拓展：基于高转化的词，推演还没被覆盖到的长尾说法
    3. 负向词筛选：判断规则没抓到但语义上不该投的词
       （比如"跑鞋怎么保养"是老客户问题，不是新客购买意图）

    Args:
        keywords_list: 要分析的关键词列表。
    """
    cleaned = keywords.dedupe(keywords_list)
    if not cleaned:
        return {"status": "error", "error_message": "关键词列表是空的。"}

    duplicates = len(keywords_list) - len(cleaned)
    cores = list(keywords_data.CORE_TO_INDUSTRY)

    try:
        universe = keywords_data.fetch_keyword_ideas()
    except keywords_data.KeywordSourceNotReady as exc:
        return {"status": "error", "error_message": str(exc)}
    by_text = {keywords.normalize(i.text): i for i in universe}

    # 按词根分组（确定性部分）
    grouped: dict[str, list[str]] = {}
    unknown_root: list[str] = []
    for keyword in cleaned:
        root = keywords.find_root(keyword, cores)
        if root is None:
            unknown_root.append(keyword)
        else:
            grouped.setdefault(root, []).append(keyword)

    # 命中负向规则的词（确定性部分）
    negative_hits = []
    for keyword in cleaned:
        hits = keywords.match_negative_rules(keyword, keywords_data.NEGATIVE_KEYWORD_RULES)
        if hits:
            negative_hits.append(
                {
                    "keyword": keyword,
                    "matched_words": [h["word"] for h in hits],
                    "categories": sorted({h["category"] for h in hits}),
                    "reason": hits[0]["reason"],
                }
            )

    # 每个词在其他数据源里有没有出现（确定性部分）
    seo_set = {keywords.normalize(r.query) for r in keywords_data.fetch_seo_queries(limit=500)}
    converting_set = {
        keywords.normalize(r.term) for r in keywords_data.fetch_converting_terms(limit=500)
    }
    coverage = [
        {
            "keyword": keyword,
            "intent_label": by_text[key].intent if key in by_text else None,
            "avg_monthly_searches": by_text[key].avg_monthly_searches if key in by_text else None,
            "has_organic_presence": key in seo_set,
            "has_converted_before": key in converting_set,
        }
        for keyword in cleaned
        for key in (keywords.normalize(keyword),)
    ]

    _remember(tool_context, current_keywords=cleaned)
    return {
        "status": "success",
        "input_count": len(keywords_list),
        "unique_count": len(cleaned),
        "duplicates_removed": duplicates,
        "root_groups": grouped,
        "keywords_without_known_root": unknown_root,
        "negative_rule_hits": negative_hits,
        "cross_source_coverage": coverage[:MAX_KEYWORDS_RETURNED],
        "your_turn": (
            "以上都是字面层面的确定性结果。现在需要你做语义判断："
            "(1) 把同一种用户需求的词聚成组，字面不同也要能认出来；"
            "(2) 以 has_converted_before=true 的词为基础拓展长尾说法；"
            "(3) 找出规则没抓到但语义上不该投的词，说明理由。"
            "结论请调 record_keyword_plan 存下来。"
        ),
    }


def record_keyword_plan(
    clusters: dict[str, list[str]],
    negative_keywords: list[str],
    rationale: str,
    tool_context: ToolContext = None,
) -> dict:
    """把你做出的关键词方案存进会话，供后续追问和成本预测使用。

    调用前请先用 analyze_keyword_structure 拿到原料，别凭空生成词。
    本工具会做确定性校验：统计每组词数、检查跨组重复、
    检查负向词是否和投放词自相矛盾。

    Args:
        clusters: 语义聚类结果。键是你给这组起的名字（如 '购买意图-跑鞋'），
            值是这组包含的关键词列表。
        negative_keywords: 你判断应该排除的负向词。
        rationale: 这个方案的理由：为什么这么分组、为什么排除这些词。
    """
    if not clusters:
        return {"status": "error", "error_message": "clusters 是空的，至少要有一个分组。"}
    if not rationale.strip():
        return {
            "status": "error",
            "error_message": "rationale 不能为空——方案必须说清理由，否则没法评估。",
        }

    # 校验一：跨组重复（同一个词被塞进两个组，说明聚类没想清楚）
    seen: dict[str, str] = {}
    cross_group_duplicates = []
    for name, members in clusters.items():
        for keyword in members:
            key = keywords.normalize(keyword)
            if key in seen and seen[key] != name:
                cross_group_duplicates.append(
                    {"keyword": keyword, "groups": [seen[key], name]}
                )
            seen[key] = name

    # 校验二：自相矛盾（既列为投放词又列为负向词）
    negative_set = {keywords.normalize(k) for k in negative_keywords}
    contradictions = sorted(
        {k for k in seen if k in negative_set}
    )

    warnings = []
    if cross_group_duplicates:
        warnings.append(f"有 {len(cross_group_duplicates)} 个词被分进了多个组。")
    if contradictions:
        warnings.append(
            f"有 {len(contradictions)} 个词既在投放列表又在负向列表里，自相矛盾。"
        )

    plan = {
        "clusters": {name: keywords.dedupe(members) for name, members in clusters.items()},
        "negative_keywords": keywords.dedupe(negative_keywords),
        "rationale": rationale,
    }
    _remember(tool_context, keyword_plan=plan)

    return {
        "status": "warning" if warnings else "success",
        "cluster_count": len(plan["clusters"]),
        "cluster_sizes": {name: len(members) for name, members in plan["clusters"].items()},
        "total_keywords": len(seen),
        "negative_count": len(plan["negative_keywords"]),
        "cross_group_duplicates": cross_group_duplicates,
        "contradictions": contradictions,
        "warnings": warnings,
        "next_step": (
            "方案已存入会话。可以调 forecast_keywords 预测这批词的花费，"
            "或用 get_converting_search_terms 验证方案是否覆盖了真实转化词。"
        )
        if not warnings
        else "请先修正上面的问题，再重新调用本工具。",
    }


def get_keyword_context(tool_context: ToolContext) -> dict:
    """查询当前会话正在规划的对象：行业、产品、词表、竞品、已存的方案。

    用户用省略说法时（如"那再加上竞品的词"、"这批词要花多少钱"），
    调用本工具找回上一轮的分析对象，不要反问用户。

    注意：本工具不需要任何参数。
    """
    state = tool_context.state if tool_context else {}
    plan = state.get("keyword_plan")
    return {
        "status": "success",
        "current_industry": state.get("current_industry"),
        "current_product": state.get("current_product"),
        "current_competitor": state.get("current_competitor"),
        "current_keywords": state.get("current_keywords"),
        "current_converting_terms": state.get("current_converting_terms"),
        "has_saved_plan": plan is not None,
        "saved_plan_summary": (
            {
                "cluster_count": len(plan["clusters"]),
                "cluster_names": list(plan["clusters"]),
                "negative_count": len(plan["negative_keywords"]),
            }
            if plan
            else None
        ),
        "hint": "如果用户指的是刚才聊过的对象，沿用这里的值继续，不要重新问一遍。",
    }
