"""创意素材库：卖点原料、品牌风格预设、广告尺寸规范。

【为什么卖点要放在数据文件里，而不是让模型现编】
让模型凭空编卖点，它会编出"品质卓越""匠心工艺"这种放到任何产品上都成立的废话。
真正能打的卖点来自产品事实——包不包邮、有没有认证、退货几天、比同类便宜多少。
所以这里存的是**事实原料**，模型的活是把事实写成有吸引力的短句，不是发明事实。

真实项目里，这些原料应该来自商品数据库或运营填的卖点表，
本文件的结构就是那张表的形状。
"""

from __future__ import annotations

from dataclasses import dataclass

# ===== 卖点维度 =====
# RSA 的核心玩法是"多角度覆盖"：Google 会自动组合不同标题去试探哪个组合转化好。
# 如果 15 个标题全是优惠角度，系统就没得试探了。所以卖点必须分维度铺开。
USP_ANGLES = {
    "pain_point": "痛点型：先说用户的烦恼，再说我们怎么解决",
    "offer": "优惠型：价格、折扣、赠品、限时",
    "trust": "信任型：认证、销量、评价、品牌背书",
    "service": "服务型：包邮、退换、保修、送装",
    "feature": "功能型：具体的产品参数与技术点",
    "scenario": "场景型：什么人在什么场合用",
}


@dataclass(frozen=True)
class ProductUsp:
    """一条卖点事实。angle 决定它适合写成哪种切入点的文案。"""

    product: str
    angle: str
    fact: str  # 客观事实，不带形容词
    proof: str | None = None  # 支撑证据，没有就是 None


# 演示用的卖点库。真实项目里换成从商品库读取。
PRODUCT_USPS = (
    # ---- 跑鞋 ----
    ProductUsp("跑鞋", "pain_point", "跑长距离时前掌容易发麻", "中底加厚 4mm 缓震层"),
    ProductUsp("跑鞋", "pain_point", "旧鞋跑 300 公里就塌陷", "实验室测试 800 公里回弹保持 90%"),
    ProductUsp("跑鞋", "offer", "新客首单立减 80 元", "限新用户，每人一次"),
    ProductUsp("跑鞋", "offer", "买一双第二双半价", None),
    ProductUsp("跑鞋", "trust", "累计售出 12 万双", "平台销量数据"),
    ProductUsp("跑鞋", "trust", "马拉松爱好者评分 4.8 分", "站内 3200 条评价"),
    ProductUsp("跑鞋", "service", "全国包邮，30 天无理由退换", None),
    ProductUsp("跑鞋", "service", "尺码不合免费换一次", None),
    ProductUsp("跑鞋", "feature", "单只重量 218 克", "43 码实测"),
    ProductUsp("跑鞋", "feature", "鞋面透气孔密度提升 35%", None),
    ProductUsp("跑鞋", "scenario", "适合每周跑 3 次以上的跑者", None),
    ProductUsp("跑鞋", "scenario", "通勤走路也能穿一整天", None),
    # ---- 扫地机器人 ----
    ProductUsp("扫地机器人", "pain_point", "扫完还要手动倒尘盒", "自动集尘，60 天不用管"),
    ProductUsp("扫地机器人", "pain_point", "总卡在桌椅腿之间", "激光雷达 + 视觉双避障"),
    ProductUsp("扫地机器人", "offer", "直降 600 元", "限时 7 天"),
    ProductUsp("扫地机器人", "trust", "京东同类销量前三", "平台榜单"),
    ProductUsp("扫地机器人", "service", "两年整机保修，上门服务", None),
    ProductUsp("扫地机器人", "feature", "吸力 8000Pa", None),
    ProductUsp("扫地机器人", "feature", "拖布自动热水洗并烘干", None),
    ProductUsp("扫地机器人", "scenario", "养宠家庭掉毛季专用", None),
    # ---- 精华液 ----
    ProductUsp("精华液", "pain_point", "换季泛红刺痛", "无酒精无香精配方"),
    ProductUsp("精华液", "offer", "买正装送 30ml 中样", None),
    ProductUsp("精华液", "trust", "皮肤科医生联合测试", "第三方机构报告"),
    ProductUsp("精华液", "trust", "回购率 42%", "站内数据"),
    ProductUsp("精华液", "service", "开封后 15 天可退", None),
    ProductUsp("精华液", "feature", "烟酰胺浓度 5%", "第三方检测报告"),
    ProductUsp("精华液", "scenario", "早晚护肤第三步使用", None),
)

PRODUCTS_WITH_USP = tuple(sorted({usp.product for usp in PRODUCT_USPS}))


# ===== 品牌视觉风格预设 =====
# 这些参数会被拼进图片生成的 prompt，保证一批素材看起来是一家的。
# 真实项目里应该来自品牌 VI 手册。


@dataclass(frozen=True)
class BrandStyle:
    """一套品牌视觉风格。字段会被拼成 prompt 的风格描述部分。"""

    name: str
    palette: tuple[str, ...]  # 主色，用英文写，图像模型对英文色彩词更敏感
    mood: str  # 整体氛围
    lighting: str  # 光线
    composition: str  # 构图习惯
    avoid: tuple[str, ...]  # negative prompt 用：这套风格绝对不要的东西


BRAND_STYLES = {
    "科技感": BrandStyle(
        name="科技感",
        palette=("deep navy #0B1F3A", "electric cyan #00D4FF", "cool grey #E8EDF2"),
        mood="clean, precise, futuristic, high-end product photography",
        lighting="soft studio rim lighting with subtle cyan accent glow",
        composition="centered product, generous negative space on the right for text overlay",
        avoid=("clutter", "warm yellow tones", "hand-drawn style", "vintage texture"),
    ),
    "简约风": BrandStyle(
        name="简约风",
        palette=("off-white #F7F5F2", "warm sand #D8CFC4", "charcoal #2E2E2E"),
        mood="calm, minimal, editorial, breathable",
        lighting="soft diffused daylight, gentle shadows",
        composition="off-center product, large clean area for headline",
        avoid=("busy background", "neon colors", "heavy shadows", "text in image"),
    ),
    "极简商业": BrandStyle(
        name="极简商业",
        palette=("pure white #FFFFFF", "brand red #E23A2E", "graphite #3A3A3A"),
        mood="confident, commercial, poster-like, high contrast",
        lighting="hard directional light, crisp edges",
        composition="bold single subject, strong geometric layout, clear text zone",
        avoid=("gradient mush", "pastel palette", "cluttered props"),
    ),
    "生活场景": BrandStyle(
        name="生活场景",
        palette=("warm beige #EFE3D3", "sage green #8FA98A", "terracotta #C2725A"),
        mood="warm, lived-in, natural, relatable everyday moment",
        lighting="golden hour window light",
        composition="product in use within a real room, person optional and partially framed",
        avoid=("studio backdrop", "cold blue tones", "obvious stock-photo posing"),
    ),
}


# ===== 广告尺寸规范 =====
# 用户要的三个比例。width/height 是投放常用的实际像素，
# imagen_ratio 是图像模型支持的最接近比例——不一定等于目标比例，
# 差异要靠生成后裁剪补上，这一点在工具里会明确告知。


@dataclass(frozen=True)
class AdSizeSpec:
    """一个广告位的尺寸要求。"""

    key: str
    label: str
    ratio_label: str
    width: int
    height: int
    usage: str
    imagen_ratio: str  # 交给图像模型的比例参数
    needs_crop: bool  # 生成比例与目标比例不一致，需要裁剪


AD_SIZE_SPECS = {
    "square": AdSizeSpec(
        key="square",
        label="正方形",
        ratio_label="1:1",
        width=1200,
        height=1200,
        usage="GDN 响应式展示广告主图；社交媒体信息流",
        imagen_ratio="1:1",
        needs_crop=False,
    ),
    "landscape": AdSizeSpec(
        key="landscape",
        label="横版",
        ratio_label="1.91:1",
        width=1200,
        height=628,
        usage="GDN 横版横幅；社交媒体链接卡片",
        # 图像模型没有 1.91:1，用最接近的 16:9(≈1.78:1) 生成后裁掉上下
        imagen_ratio="16:9",
        needs_crop=True,
    ),
    "vertical": AdSizeSpec(
        key="vertical",
        label="竖版",
        ratio_label="9:16",
        width=1080,
        height=1920,
        usage="短视频信息流；Story / Reels 竖屏广告",
        imagen_ratio="9:16",
        needs_crop=False,
    ),
}
