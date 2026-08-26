r"""把审查通过的方案构造成 Google Ads API 的 Mutate Operations。

【为什么单独一层，而不是在 tools.py 里现拼】
两个原因：
1. **依赖顺序错了会留垃圾数据。** 预算要先建、才有 campaign 可挂；
   ad_group 要先建、才有地方放关键词和广告。顺序是死规矩，适合用代码固定住，
   不该每次让模型现想。
2. **单位换算错一位就是十倍预算。** Google Ads 的金额字段全是 micros
   （百万分之一单位），300 元要写成 300000000。这种换算必须收在一个地方并被测试守住。

【幂等怎么做的】
build_operations 的输出只由方案内容决定（不含时间戳、不含随机数），
所以对同一套方案算出来的 submission_token 是稳定的。
data.py 用这个 token 当账本主键：同一个 token 提交两次，第二次直接返回上次回执，
不会重复创建。这是"避免半成品垃圾数据"的另一半。
"""

from __future__ import annotations

import hashlib
import json

from .schema import CampaignDraft, MutateOp

MICROS = 1_000_000

# 临时资源 ID 的分段。分段而不是简单递减，是为了看日志时一眼知道是哪类对象。
TEMP_BUDGET = -1
TEMP_CAMPAIGN = -2
TEMP_AD_GROUP_BASE = -1000
TEMP_KEYWORD_BASE = -2000
TEMP_NEGATIVE_BASE = -5000
TEMP_AD_BASE = -9000

# customer_id 在这里刻意留成占位符，由 data.py 在真正提交时才替换。
# 理由和 config.py 的底线一致：payload 会被返回给模型看，
# 账号 ID 属于账户信息，不该进模型上下文。
CUSTOMER_PLACEHOLDER = "customers/{customer_id}"

# 新建的广告系列一律先 PAUSED。这是本项目的安全默认值：
# 创建动作本身不该开始花钱，要不要开投是另一次人工决定。
INITIAL_CAMPAIGN_STATUS = "PAUSED"

# 正向关键词默认用词组匹配。广泛匹配拉来的无关流量最多，
# 冷启动阶段用它等于把预算交给运气。
DEFAULT_MATCH_TYPE = "PHRASE"


def to_micros(amount: float) -> int:
    """元 → micros。四舍五入到整数，API 不接受小数 micros。"""
    return int(round(amount * MICROS))


def _resource(kind: str, temp_id: int) -> str:
    """拼出临时资源名。Google Ads 允许用负数 ID 指代同批还没创建的对象。"""
    return f"{CUSTOMER_PLACEHOLDER}/{kind}/{temp_id}"


def _bidding_fields(draft: CampaignDraft) -> dict:
    """按出价策略只填该填的字段，不该填的一个都不放。

    多填的字段 API 会直接报错（同一个 campaign 上不允许两种出价策略共存），
    所以这里必须按策略分支，不能"有值就填"。
    """
    strategy = draft.bidding_strategy
    if strategy == "MANUAL_CPC":
        return {"manual_cpc": {"enhanced_cpc_enabled": False}}
    if strategy == "TARGET_CPA":
        return {"target_cpa": {"target_cpa_micros": to_micros(draft.target_cpa or 0)}}
    if strategy == "TARGET_ROAS":
        return {"target_roas": {"target_roas": draft.target_roas}}
    if strategy == "MAXIMIZE_CONVERSIONS":
        fields = {"maximize_conversions": {}}
        if draft.target_cpa:
            fields["maximize_conversions"] = {
                "target_cpa_micros": to_micros(draft.target_cpa)
            }
        return fields
    if strategy == "MAXIMIZE_CLICKS":
        fields = {"target_spend": {}}
        if draft.max_cpc:
            fields["target_spend"] = {"cpc_bid_ceiling_micros": to_micros(draft.max_cpc)}
        return fields
    # 走到这里说明策略名没过 checks，构造阶段不该再兜底猜一个
    raise ValueError(f"不支持的出价策略：{draft.bidding_strategy}")


def build_operations(draft: CampaignDraft) -> list[MutateOp]:
    """把一份方案展开成按依赖顺序排好的 Mutate 操作列表。

    顺序是硬约束：campaign_budget → campaign → ad_group →
    关键词/负向词 → 广告素材。每一步的 depends_on 写明它等谁。
    """
    ops: list[MutateOp] = []
    order = 0

    def add(resource: str, temp_id: int | None, depends_on: tuple[int, ...], payload: dict):
        nonlocal order
        ops.append(
            MutateOp(
                order=order,
                resource=resource,
                operation="create",
                temp_id=temp_id,
                depends_on=depends_on,
                payload=payload,
            )
        )
        order += 1

    budget_resource = _resource("campaignBudgets", TEMP_BUDGET)
    add(
        "campaign_budget",
        TEMP_BUDGET,
        (),
        {
            "resource_name": budget_resource,
            "name": f"{draft.name} - 预算",
            "amount_micros": to_micros(draft.daily_budget),
            "delivery_method": "STANDARD",
            # 不共享预算：共享预算会让这个系列的超支影响到别的系列
            "explicitly_shared": False,
        },
    )

    campaign_resource = _resource("campaigns", TEMP_CAMPAIGN)
    add(
        "campaign",
        TEMP_CAMPAIGN,
        (TEMP_BUDGET,),
        {
            "resource_name": campaign_resource,
            "name": draft.name,
            "status": INITIAL_CAMPAIGN_STATUS,
            "advertising_channel_type": "SEARCH",
            "campaign_budget": budget_resource,
            # 只投搜索网络：搜索合作网络和展示网络的流量质量差异很大，
            # 新系列先不开，免得把效果混在一起看不清。
            "network_settings": {
                "target_google_search": True,
                "target_search_network": False,
                "target_content_network": False,
            },
            **_bidding_fields(draft),
        },
    )

    for index, group in enumerate(draft.ad_groups):
        group_temp = TEMP_AD_GROUP_BASE - index
        group_resource = _resource("adGroups", group_temp)
        group_payload = {
            "resource_name": group_resource,
            "name": group.name,
            "campaign": campaign_resource,
            "status": "ENABLED",
            "type_": "SEARCH_STANDARD",
        }
        if group.max_cpc:
            group_payload["cpc_bid_micros"] = to_micros(group.max_cpc)
        add("ad_group", group_temp, (TEMP_CAMPAIGN,), group_payload)

        for position, keyword in enumerate(group.keywords):
            add(
                "ad_group_criterion",
                TEMP_KEYWORD_BASE - index * 200 - position,
                (group_temp,),
                {
                    "ad_group": group_resource,
                    "status": "ENABLED",
                    "keyword": {"text": keyword, "match_type": DEFAULT_MATCH_TYPE},
                },
            )

        for position, keyword in enumerate(group.negative_keywords):
            add(
                "ad_group_criterion",
                TEMP_NEGATIVE_BASE - index * 200 - position,
                (group_temp,),
                {
                    "ad_group": group_resource,
                    "negative": True,
                    "keyword": {"text": keyword, "match_type": DEFAULT_MATCH_TYPE},
                },
            )

        ad = group.ad
        responsive = {
            "headlines": [{"text": text} for text in ad.headlines],
            "descriptions": [{"text": text} for text in ad.descriptions],
        }
        if len(ad.paths) >= 1:
            responsive["path1"] = ad.paths[0]
        if len(ad.paths) >= 2:
            responsive["path2"] = ad.paths[1]
        add(
            "ad_group_ad",
            TEMP_AD_BASE - index,
            (group_temp,),
            {
                "ad_group": group_resource,
                "status": "ENABLED",
                "ad": {"final_urls": [ad.final_url], "responsive_search_ad": responsive},
            },
        )

    return ops


def submission_token(ops: list[MutateOp]) -> str:
    """给这批操作算一个内容指纹。内容一样 → token 一样，改一个字 → token 变。

    刻意不掺时间戳和随机数：token 必须能复现，
    否则同一套方案每次构造都得到新 token，幂等就形同虚设。
    """
    canonical = json.dumps(
        [
            {
                "order": op.order,
                "resource": op.resource,
                "operation": op.operation,
                "temp_id": op.temp_id,
                "depends_on": list(op.depends_on),
                "payload": op.payload,
            }
            for op in ops
        ],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def summarize(draft: CampaignDraft, ops: list[MutateOp]) -> dict:
    """给模型看的 payload 摘要：会创建什么、按什么顺序、有哪些没覆盖到。"""
    by_resource: dict[str, int] = {}
    for op in ops:
        by_resource[op.resource] = by_resource.get(op.resource, 0) + 1

    images = [url for group in draft.ad_groups for url in group.ad.image_urls]
    return {
        "campaign_name": draft.name,
        "operation_count": len(ops),
        "operations_by_resource": by_resource,
        "execution_order": [
            {
                "step": op.order + 1,
                "resource": op.resource,
                "temp_id": op.temp_id,
                "waits_for": list(op.depends_on),
            }
            for op in ops
        ],
        "initial_campaign_status": INITIAL_CAMPAIGN_STATUS,
        "daily_budget_micros": to_micros(draft.daily_budget),
        "keyword_match_type": DEFAULT_MATCH_TYPE,
        "not_covered": [
            "图片素材需要单独走 AssetService 上传后再挂到广告上，本版本不构造这部分操作。"
            f"收到的 {len(images)} 个图片 URL 只做记录。"
            if images
            else "本次方案没有图片素材。",
            f"广告系列会以 {INITIAL_CAMPAIGN_STATUS} 状态创建，"
            "不会自动开始投放；要开投是另一次人工决定。",
        ],
        "image_urls_recorded": images,
    }
