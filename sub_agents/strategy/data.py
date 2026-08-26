r"""写入接缝：唯一一处真的会改动 Google Ads 账户的地方。

【为什么写操作要单独一个入口】
读数据错了只是看错一眼，写错了是线上账户真金白银的损失。
把所有写操作收在这一个文件里，就只有这里需要被反复审、被测试盯着，
其它层想绕过它做写操作是做不到的。

【mock 和 live 的分界，以及什么时候该报错】
- 用户没要求 live（默认）→ 返回**演练回执**，明确标注账号里什么都没变。
- 用户明确要求 live 但条件不齐（缺凭证/缺库/落盘逻辑没写）→ **抛异常**。
  绝不悄悄降级成演练：把演练回执当成"已经建好了"汇报，
  比直接报错危险得多。这条与 performance/data.py 的取数原则一致。

【幂等账本】
_LEDGER 按 submission_token 记住每次提交结果。同一个 token 再提交一次，
直接返回上次回执。它是进程内的，重启会清空——学习阶段够用，
真接上 API 后应该换成数据库或直接查账户里已存在的对象。
"""

from __future__ import annotations

from ... import config
from .schema import CampaignDraft, MutateOp, SubmissionReceipt

# 真实落盘逻辑的实现要点，写在一处，供报错信息和文档共用
_WRITE_IMPL_HINT = (
    "在 strategy/data.py 的 _submit_operations_live 里，用 GoogleAdsClient.load_from_dict() "
    "建客户端（键名同取数那边，含硬性必填的 use_proto_plus=True），"
    "然后用 client.get_service('GoogleAdsService').mutate() 一次性提交，"
    "把 payload.py 生成的操作按 order 转成对应的 XxxOperation，"
    "并把 resource_name 里的 {customer_id} 占位符替换成真实账号 ID。"
    "务必带上 partial_failure=False，让整批操作要么全成要么全不成——"
    "这正是用负数临时 ID 的意义，半成品比失败更难清理。"
)

_PAUSE_IMPL_HINT = (
    "在 strategy/data.py 的 _pause_campaign_live 里，先用 GAQL 按 campaign.name 查到"
    "真实 resource_name，再用 CampaignOperation 的 update 把 status 改成 PAUSED，"
    "update_mask 只写 status 这一个字段——多写一个字段就可能顺手覆盖掉别的设置。"
)


class AdsWriteNotReady(RuntimeError):
    """该真的写入账户却写不了时抛出（缺库、缺凭证、落盘逻辑未实现）。"""


_LEDGER: dict[str, dict] = {}


def reset_ledger() -> None:
    """清空幂等账本。测试之间要用它隔离，正常运行不该调。"""
    _LEDGER.clear()


def already_submitted(token: str) -> dict | None:
    """这个 token 之前提交过没有。提交过就返回上次的回执。"""
    return _LEDGER.get(token)


def _write_blocker() -> str:
    """写不了的原因 + 完整待办清单，一句话说清卡在哪。"""
    status = config.ads_write_status()
    steps: list[str] = []
    if status["missing_package"]:
        steps.append(f"安装依赖库：pip install {status['missing_package']}")
    if status["missing_keys"]:
        steps.append(".env 里填上这些配置项：" + "、".join(status["missing_keys"]))
    if not status["write_implemented"]:
        steps.append(f"实现真实落盘逻辑：{_WRITE_IMPL_HINT}")
    if status["requested_mode"] != config.MODE_LIVE:
        steps.append(f"把 .env 的 {config.ADS_WRITE_MODE_ENV} 改成 {config.MODE_LIVE}")
    return "现在不能真的写入 Google Ads 账户。待办：" + "；".join(
        f"({i}) {step}" for i, step in enumerate(steps, 1)
    )


def _receipt_to_dict(receipt: SubmissionReceipt) -> dict:
    return {
        "token": receipt.token,
        "mode": receipt.mode,
        "committed": receipt.committed,
        "campaign_name": receipt.campaign_name,
        "operation_count": receipt.operation_count,
        "created_resources": list(receipt.created_resources),
        "note": receipt.note,
    }


def _submit_operations_mock(
    draft: CampaignDraft, ops: list[MutateOp], token: str
) -> dict:
    """演练：把"会创建什么"如实列出来，但一个 API 请求都不发。"""
    created = tuple(
        f"{op.resource}#{op.temp_id}" for op in ops if op.temp_id is not None
    )
    return _receipt_to_dict(
        SubmissionReceipt(
            token=token,
            mode=config.MODE_MOCK,
            committed=False,
            campaign_name=draft.name,
            operation_count=len(ops),
            created_resources=created,
            note=(
                "**这是演练回执，Google Ads 账号里什么都没有变。** "
                "资源名里的负数是临时 ID，不是真实 ID。"
                f"要真的落盘，见待办：{_write_blocker()}"
            ),
        )
    )


def _submit_operations_live(
    draft: CampaignDraft, ops: list[MutateOp], token: str
) -> dict:
    """真的提交到 Google Ads。【待实现：只差这个函数体】

    实现要点见模块顶部的 _WRITE_IMPL_HINT。三个必须守住的点：
    1. 整批原子提交（partial_failure=False），不允许留半成品；
    2. 提交成功后把真实 resource_name 写进 _LEDGER，幂等才有意义；
    3. 实现完成后把 config.ADS_WRITE_IMPLEMENTED 改成 True。
    """
    raise AdsWriteNotReady(_write_blocker())


def submit_operations(draft: CampaignDraft, ops: list[MutateOp], token: str) -> dict:
    """提交一批操作。幂等：同一个 token 第二次调用直接返回上次回执。"""
    existing = already_submitted(token)
    if existing is not None:
        return {**existing, "idempotent_replay": True}

    status = config.ads_write_status()
    if status["effective_mode"] == config.MODE_LIVE:
        receipt = _submit_operations_live(draft, ops, token)
    elif status["requested_mode"] == config.MODE_LIVE:
        # 用户要的是真落盘，条件却不齐 —— 必须报错，不能拿演练冒充
        raise AdsWriteNotReady(_write_blocker())
    else:
        receipt = _submit_operations_mock(draft, ops, token)

    _LEDGER[token] = receipt
    return {**receipt, "idempotent_replay": False}


def _pause_campaign_live(campaign: str, reason: str) -> dict:
    """真的把广告系列改成 PAUSED。【待实现：只差这个函数体】

    实现要点见模块顶部的 _PAUSE_IMPL_HINT。
    """
    raise AdsWriteNotReady(_write_blocker())


def pause_campaign(campaign: str, reason: str) -> dict:
    """暂停一个广告系列。调用方必须已经拿到用户确认。"""
    status = config.ads_write_status()
    if status["effective_mode"] == config.MODE_LIVE:
        return _pause_campaign_live(campaign, reason)
    if status["requested_mode"] == config.MODE_LIVE:
        raise AdsWriteNotReady(_write_blocker())
    return {
        "mode": config.MODE_MOCK,
        "committed": False,
        "campaign": campaign,
        "requested_status": "PAUSED",
        "reason": reason,
        "note": (
            "**这是演练，广告系列并没有被真的暂停。** "
            f"要真的暂停，见待办：{_write_blocker()}"
        ),
    }
