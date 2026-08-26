r"""风控规则库：敏感词表与出价策略表。

【为什么规则表在这里、阈值数字在 config.py】
两者变的频率和变的人不一样。阈值（预算上限、出价上下限）是**每个账号不同**、
要让用户在 `.env` 里随时改的，所以归 config.py——全项目只有 config 读 `.env`。
规则表是**行业通用**的知识，改它等于改代码，所以写死在这里。

【这张敏感词表的定位：近似规则库，不是官方政策】
Google Ads 的审核政策没有公开的词表，任何词表都只是逼近。
它的作用是**在提交前拦掉一眼可见的硬伤**，省掉一次拒审往返，
不是"过了就一定能过审"。所以：
- 命中 error 的一定要改；
- 表里没有的不代表安全，"夸大宣传"这类要靠模型的语义判断补位（见 agent.py 指令）。

词表结构刻意与 keywords/data.py 的 NEGATIVE_KEYWORD_RULES 一致
（word / category / reason），这样两边能共用 metrics.match_negative_rules。
"""

from __future__ import annotations

# ===== 出价策略 =====
# needs：这个策略必须填哪个出价字段；optional：可以填但不强制。
# 分开列是因为校验要按策略选阀门——给 TARGET_CPA 的方案去查 max_cpc 是查错了对象。
BIDDING_STRATEGIES = {
    "MANUAL_CPC": {
        "label": "手动 CPC",
        "needs": ("max_cpc",),
        "optional": (),
        "note": "自己定每次点击最高出价，最可控，也最费人力。",
    },
    "TARGET_CPA": {
        "label": "目标每次转化费用",
        "needs": ("target_cpa",),
        "optional": (),
        "note": "系统按目标 CPA 自动出价。目标定太低会没量，定太高会超支。",
    },
    "TARGET_ROAS": {
        "label": "目标广告支出回报率",
        "needs": ("target_roas",),
        "optional": (),
        "note": "需要有转化价值回传，否则系统没有优化依据。ROAS 用倍数表示，2 即 200%。",
    },
    "MAXIMIZE_CONVERSIONS": {
        "label": "尽可能提高转化次数",
        "needs": (),
        "optional": ("target_cpa",),
        "note": "会把预算花完为止，所以**日预算就是唯一的刹车**，必须卡紧。",
    },
    "MAXIMIZE_CLICKS": {
        "label": "尽可能提高点击次数",
        "needs": (),
        "optional": ("max_cpc",),
        "note": "只买流量不看转化，冷启动试水可用，长期投放不建议。",
    },
}

# ===== 敏感词与合规规则 =====
# severity: error 会拦下提交；warning 只提示，由人决定。
SENSITIVE_WORD_RULES = (
    # --- 绝对化用语：《广告法》第九条明令禁止，国内投放命中即违法 ---
    {"word": "国家级", "category": "绝对化用语", "severity": "error",
     "reason": "《广告法》第九条禁止使用「国家级」等绝对化用语"},
    {"word": "最高级", "category": "绝对化用语", "severity": "error",
     "reason": "《广告法》第九条明令禁止的绝对化用语"},
    {"word": "最佳", "category": "绝对化用语", "severity": "error",
     "reason": "绝对化用语，无法证实且违反《广告法》"},
    {"word": "最好", "category": "绝对化用语", "severity": "error",
     "reason": "绝对化用语，无法证实且违反《广告法》"},
    {"word": "最便宜", "category": "绝对化用语", "severity": "error",
     "reason": "绝对化用语，且价格承诺无法长期成立"},
    {"word": "第一品牌", "category": "绝对化用语", "severity": "error",
     "reason": "排名类表述需要权威依据，否则构成虚假宣传"},
    {"word": "销量第一", "category": "绝对化用语", "severity": "error",
     "reason": "排名类表述需要权威依据，否则构成虚假宣传"},
    {"word": "全国第一", "category": "绝对化用语", "severity": "error",
     "reason": "排名类表述需要权威依据，否则构成虚假宣传"},
    {"word": "世界级", "category": "绝对化用语", "severity": "error",
     "reason": "绝对化用语，无法证实"},
    {"word": "唯一", "category": "绝对化用语", "severity": "warning",
     "reason": "多数语境下无法证实；确有独家资质可保留，但要能拿出证明"},
    {"word": "顶级", "category": "绝对化用语", "severity": "error",
     "reason": "绝对化用语，无法证实"},
    {"word": "no.1", "category": "绝对化用语", "severity": "error",
     "reason": "排名类表述，等同「第一」"},
    {"word": "#1", "category": "绝对化用语", "severity": "error",
     "reason": "排名类表述，等同「第一」"},

    # --- 虚假承诺：拒审高发区，也是投诉与退款纠纷的源头 ---
    {"word": "100%", "category": "虚假承诺", "severity": "error",
     "reason": "绝对比例承诺无法兑现，属虚假宣传"},
    {"word": "绝对", "category": "虚假承诺", "severity": "error",
     "reason": "绝对化承诺无法兑现"},
    {"word": "保证有效", "category": "虚假承诺", "severity": "error",
     "reason": "效果承诺无法兑现，Google Ads 与《广告法》双重禁止"},
    {"word": "永久", "category": "虚假承诺", "severity": "warning",
     "reason": "「永久」类承诺难以兑现，除非是明确的终身授权条款"},
    {"word": "稳赚不赔", "category": "虚假承诺", "severity": "error",
     "reason": "收益承诺属金融违规表述"},
    {"word": "一夜暴富", "category": "虚假承诺", "severity": "error",
     "reason": "诱导性收益承诺，属违规金融宣传"},
    {"word": "保本高收益", "category": "虚假承诺", "severity": "error",
     "reason": "「保本」+「高收益」是金融广告明令禁止的组合"},
    {"word": "guaranteed", "category": "虚假承诺", "severity": "warning",
     "reason": "英文效果承诺，需有明确条款支撑（如退款保障）才可用"},
    {"word": "risk-free", "category": "虚假承诺", "severity": "error",
     "reason": "「零风险」承诺无法兑现"},

    # --- 医疗与健康：Google Ads 单独成章的高压线 ---
    {"word": "治愈", "category": "医疗违规", "severity": "error",
     "reason": "非药品/医疗器械不得宣称治疗效果"},
    {"word": "根治", "category": "医疗违规", "severity": "error",
     "reason": "非药品/医疗器械不得宣称治疗效果"},
    {"word": "特效药", "category": "医疗违规", "severity": "error",
     "reason": "处方药与疗效宣称在多数地区禁止投放"},
    {"word": "抗癌", "category": "医疗违规", "severity": "error",
     "reason": "重大疾病疗效宣称，属严格禁止内容"},
    {"word": "无副作用", "category": "医疗违规", "severity": "error",
     "reason": "安全性绝对化宣称，医疗类禁止"},
    {"word": "减肥药", "category": "医疗违规", "severity": "error",
     "reason": "减重药品类目在多数地区需资质或直接禁投"},
    {"word": "壮阳", "category": "医疗违规", "severity": "error",
     "reason": "成人保健类违规内容"},
    {"word": "cure", "category": "医疗违规", "severity": "warning",
     "reason": "英文疗效词，非医疗资质账户慎用"},

    # --- 侵权与仿品：命中会封账号，比拒审严重得多 ---
    {"word": "高仿", "category": "侵权仿品", "severity": "error",
     "reason": "仿冒商品，Google Ads 禁止且可导致账号永久停用"},
    {"word": "a货", "category": "侵权仿品", "severity": "error",
     "reason": "仿冒商品的行业黑话，禁止投放"},
    {"word": "山寨", "category": "侵权仿品", "severity": "error",
     "reason": "仿冒商品，禁止投放"},
    {"word": "复刻版", "category": "侵权仿品", "severity": "error",
     "reason": "常用于规避仿品审核的说法，风险等同高仿"},
    {"word": "原单", "category": "侵权仿品", "severity": "error",
     "reason": "尾单/原单类表述指向未授权商品"},
    {"word": "同款", "category": "侵权仿品", "severity": "warning",
     "reason": "「某品牌同款」易构成商标搭便车，需确认未使用他人商标"},

    # --- 违禁品与灰产 ---
    {"word": "博彩", "category": "违禁行业", "severity": "error",
     "reason": "赌博类目需专门资质，多数地区禁投"},
    {"word": "代开发票", "category": "违禁行业", "severity": "error",
     "reason": "违法服务"},
    {"word": "高利贷", "category": "违禁行业", "severity": "error",
     "reason": "违规金融服务"},
    {"word": "信用卡套现", "category": "违禁行业", "severity": "error",
     "reason": "违法金融服务"},
    {"word": "内部消息", "category": "违禁行业", "severity": "error",
     "reason": "证券类违规诱导表述"},
)

SENSITIVE_CATEGORIES = tuple(sorted({rule["category"] for rule in SENSITIVE_WORD_RULES}))
