"""投放方案的形状定义：模型给的草案 → 校验 → Mutate 操作 → 回执。

【为什么单独一个文件】
和 keywords/schema.py 同一个理由：这些 dataclass 是**契约**。
checks.py 拿它做校验、payload.py 拿它构造 API 操作、data.py 拿它落盘，
三层都 import 它，所以谁都不该独占它。

【为什么要有 parse_* 函数】
草案是大模型填的，不是程序生成的：字段可能缺、数字可能写成字符串 "300"、
列表可能是 None。所以入口必须挡一道，并且把两类问题分开——
"形状不对"是模型填错了要重填，"数值超标"是风控拦截，
两者给用户的话完全不同，混在一起会让人以为是自己预算填多了。
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 一个广告组里最多放多少个关键词。Google Ads 单账户有上限，
# 但这里卡得更紧：一组塞几百个词本身就是分组没想清楚。
MAX_KEYWORDS_PER_AD_GROUP = 100
MAX_AD_GROUPS_PER_CAMPAIGN = 20


@dataclass(frozen=True)
class AdDraft:
    """一个响应式搜索广告（RSA）的素材。字段名对齐 Google Ads 的 AdGroupAd。"""

    headlines: tuple[str, ...]
    descriptions: tuple[str, ...]
    final_url: str
    image_urls: tuple[str, ...] = ()
    paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class AdGroupDraft:
    """一个广告组：一批关键词 + 一组负向词 + 一个广告。"""

    name: str
    keywords: tuple[str, ...]
    negative_keywords: tuple[str, ...]
    ad: AdDraft
    max_cpc: float | None = None


@dataclass(frozen=True)
class CampaignDraft:
    """一个待创建的广告系列。金额单位都是元，转 micros 是 payload.py 的活。"""

    name: str
    daily_budget: float
    bidding_strategy: str
    ad_groups: tuple[AdGroupDraft, ...]
    target_cpa: float | None = None
    target_roas: float | None = None
    max_cpc: float | None = None


@dataclass(frozen=True)
class MutateOp:
    """一条 Mutate 操作。

    temp_id 是负数临时资源 ID——Google Ads 允许在同一批 mutate 里先用负数指代
    还没创建的对象，提交后由服务端替换成真实 ID。这是"原子化创建整棵树"的关键，
    没有它就得分多次请求，中间失败会留下半成品。
    """

    order: int
    resource: str
    operation: str
    temp_id: int | None
    depends_on: tuple[int, ...]
    payload: dict = field(default_factory=dict)


@dataclass(frozen=True)
class SubmissionReceipt:
    """提交回执。committed=False 表示这次是演练，账号里什么都没变。"""

    token: str
    mode: str
    committed: bool
    campaign_name: str
    operation_count: int
    created_resources: tuple[str, ...]
    note: str


def _as_float(value, label: str, errors: list[str]) -> float | None:
    """把模型给的值转成浮点数。转不了就记一条错误并返回 None。"""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        errors.append(f"{label} 必须是数字，收到的是 {value!r}。")
        return None


def _as_str_tuple(value, label: str, errors: list[str]) -> tuple[str, ...]:
    """把模型给的列表转成字符串元组，顺手去掉空串。"""
    if value is None:
        return ()
    if isinstance(value, str):  # 模型偶尔会把单个值直接给成字符串
        value = [value]
    if not isinstance(value, (list, tuple)):
        errors.append(f"{label} 必须是列表，收到的是 {type(value).__name__}。")
        return ()
    return tuple(str(item).strip() for item in value if str(item).strip())


def parse_ad_group(raw: dict, index: int, errors: list[str]) -> AdGroupDraft | None:
    """把模型给的一个广告组 dict 解析成 AdGroupDraft。形状不对就记错误返回 None。

    只看**自己**这一组有没有出错：errors 是所有组共用的一张单子，
    不记住起始位置的话，前一组的错误会把后面每一组都判成失败。
    """
    where = f"第 {index + 1} 个广告组"
    started_with = len(errors)
    if not isinstance(raw, dict):
        errors.append(f"{where} 不是对象，收到的是 {type(raw).__name__}。")
        return None

    name = str(raw.get("name") or "").strip()
    if not name:
        errors.append(f"{where} 缺少 name（广告组名）。")

    keywords = _as_str_tuple(raw.get("keywords"), f"{where} 的 keywords", errors)
    negatives = _as_str_tuple(
        raw.get("negative_keywords"), f"{where} 的 negative_keywords", errors
    )
    headlines = _as_str_tuple(raw.get("headlines"), f"{where} 的 headlines", errors)
    descriptions = _as_str_tuple(raw.get("descriptions"), f"{where} 的 descriptions", errors)
    final_url = str(raw.get("final_url") or "").strip()
    max_cpc = _as_float(raw.get("max_cpc"), f"{where} 的 max_cpc", errors)
    image_urls = _as_str_tuple(raw.get("image_urls"), f"{where} 的 image_urls", errors)
    paths = _as_str_tuple(raw.get("paths"), f"{where} 的 paths", errors)

    if not keywords:
        errors.append(f"{where} 一个关键词都没有，投不出去。")
    if len(keywords) > MAX_KEYWORDS_PER_AD_GROUP:
        errors.append(
            f"{where} 有 {len(keywords)} 个关键词，超过单组上限 "
            f"{MAX_KEYWORDS_PER_AD_GROUP}，说明该拆组了。"
        )
    if not headlines or not descriptions:
        errors.append(f"{where} 缺少标题或描述，先让 creative_agent 出文案。")
    if not final_url:
        errors.append(f"{where} 缺少 final_url（落地页地址）。")

    if len(errors) > started_with:
        return None
    return AdGroupDraft(
        name=name,
        keywords=keywords,
        negative_keywords=negatives,
        max_cpc=max_cpc,
        ad=AdDraft(
            headlines=headlines,
            descriptions=descriptions,
            final_url=final_url,
            image_urls=image_urls,
            paths=paths,
        ),
    )


def parse_campaign(
    campaign_name: str,
    daily_budget,
    bidding_strategy: str,
    ad_groups: list[dict] | None,
    target_cpa=None,
    target_roas=None,
    max_cpc=None,
) -> tuple[CampaignDraft | None, list[str]]:
    """把模型给的一整套参数解析成 CampaignDraft，同时返回形状错误清单。

    返回 (draft, errors)。errors 非空时 draft 一定是 None——
    形状都没对上就不该往下走风控校验，那只会报出一堆二次错误。
    """
    errors: list[str] = []
    name = (campaign_name or "").strip()
    if not name:
        errors.append("缺少 campaign_name（广告系列名）。")

    budget = _as_float(daily_budget, "daily_budget", errors)
    if budget is None and daily_budget in (None, ""):
        errors.append("缺少 daily_budget（单日预算，单位元）。")

    strategy = (bidding_strategy or "").strip().upper()
    if not strategy:
        errors.append("缺少 bidding_strategy（出价策略）。")

    if not ad_groups:
        errors.append("一个广告组都没有，先让 keyword_agent 出分组方案。")
    elif not isinstance(ad_groups, (list, tuple)):
        errors.append(f"ad_groups 必须是列表，收到的是 {type(ad_groups).__name__}。")
    elif len(ad_groups) > MAX_AD_GROUPS_PER_CAMPAIGN:
        errors.append(
            f"一次提交 {len(ad_groups)} 个广告组，超过上限 "
            f"{MAX_AD_GROUPS_PER_CAMPAIGN}，请分批提交。"
        )

    parsed_groups: list[AdGroupDraft] = []
    for index, raw in enumerate(ad_groups or ()):
        group = parse_ad_group(raw, index, errors)
        if group is not None:
            parsed_groups.append(group)

    seen_names = [g.name for g in parsed_groups]
    duplicated = sorted({n for n in seen_names if seen_names.count(n) > 1})
    if duplicated:
        errors.append(f"广告组名重复：{'、'.join(duplicated)}。同名组会互相覆盖。")

    tcpa = _as_float(target_cpa, "target_cpa", errors)
    troas = _as_float(target_roas, "target_roas", errors)
    cpc = _as_float(max_cpc, "max_cpc", errors)

    if errors:
        return None, errors
    return (
        CampaignDraft(
            name=name,
            daily_budget=budget,
            bidding_strategy=strategy,
            ad_groups=tuple(parsed_groups),
            target_cpa=tcpa,
            target_roas=troas,
            max_cpc=cpc,
        ),
        [],
    )
