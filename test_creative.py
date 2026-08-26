r"""文案与视觉创意层的自检测试（不需要 pytest、不联网、不花钱）。

运行方式：
    .venv\Scripts\python.exe -m digital_marketing_agent.test_creative

重点测什么：**字符宽度算得准不准**。
这是整个创意功能里唯一"错了就直接被 Google 拒收"的地方——
中文全角算 2 个单位这件事只要错一位，提交上去就是白忙。
"""

import asyncio
import pathlib
import tempfile

from . import config, creative, creative_data, creative_tools, image_quality
from .test_runner import run


def test_cjk_characters_count_as_two_units():
    """中文全角字符每个算 2 个单位——这是最容易搞错、后果最直接的一条。"""
    assert creative.display_width("跑鞋") == 4
    assert creative.display_width("abcd") == 4
    # 全角标点也算 2
    assert creative.display_width("，") == 2
    assert creative.display_width(",") == 1


def test_mixed_text_width_is_summed_per_character():
    """中英数混排要逐字符累加，不能按整串长度估。"""
    # Nike(4) + 跑鞋(4) + 空格(1) + 30(2) + 天退换(6) = 17
    assert creative.display_width("Nike跑鞋 30天退换") == 17


def test_pure_chinese_headline_allows_15_characters():
    """标题额度 30 个单位 → 纯中文正好 15 个字，第 16 个字就超。"""
    fifteen = "一二三四五六七八九十一二三四五"
    assert len(fifteen) == 15
    assert creative.display_width(fifteen) == creative.HEADLINE_MAX_UNITS
    assert creative.validate_asset(fifteen, "headline")["within_limit"] is True

    sixteen = fifteen + "六"
    result = creative.validate_asset(sixteen, "headline")
    assert result["within_limit"] is False
    assert result["over_by_units"] == 2


def test_pure_chinese_description_allows_45_characters():
    """描述额度 90 个单位 → 纯中文 45 个字。"""
    text = "字" * 45
    assert creative.display_width(text) == creative.DESCRIPTION_MAX_UNITS
    assert creative.validate_asset(text, "description")["within_limit"] is True
    assert creative.validate_asset("字" * 46, "description")["within_limit"] is False


def test_remaining_cjk_chars_is_actionable():
    """要告诉模型"还能再写几个汉字"，而不是只说"还剩几个单位"。"""
    result = creative.validate_asset("跑鞋", "headline")  # 用掉 4，剩 26 单位
    assert result["remaining_cjk_chars"] == 13


def test_truncate_never_splits_a_character():
    """裁剪不能切出半个字符。"""
    assert creative.truncate_to_width("跑鞋价格", 5) == "跑鞋"  # 第三个字要 2 单位，放不下
    assert creative.truncate_to_width("abc", 2) == "ab"


def test_unknown_asset_kind_raises():
    try:
        creative.validate_asset("测试", "subtitle")
    except ValueError as exc:
        assert "未知素材类型" in str(exc)
    else:
        raise AssertionError("应该抛 ValueError")


def test_repeated_punctuation_is_an_error():
    """连续重复标点是官方明令禁止的，必须判为 error（阻塞提交）。"""
    issues = creative.check_content_rules("限时优惠！！", "headline")
    rules = {i["rule"]: i["severity"] for i in issues}
    assert rules.get("标点不可连续重复") == "error"


def test_abusive_uppercase_is_an_error():
    assert any(
        i["rule"] == "不滥用全大写"
        for i in creative.check_content_rules("HUGE SALE today", "headline")
    )
    # 白名单里的缩写不该被误判
    assert not any(
        i["rule"] == "不滥用全大写"
        for i in creative.check_content_rules("SPF50 防晒", "headline")
    )


def test_letter_spaced_word_is_an_error():
    assert any(
        i["rule"] == "不逐字母加标点"
        for i in creative.check_content_rules("F.L.O.W.E.R.S", "headline")
    )


def test_phone_number_in_copy_is_an_error():
    assert any(
        i["rule"] == "文案里不写电话号码"
        for i in creative.check_content_rules("咨询 400-123-4567", "description")
    )
    # 短数字（价格、天数）不能误判成电话
    assert not any(
        i["rule"] == "文案里不写电话号码"
        for i in creative.check_content_rules("直降 600 元，30 天退换", "description")
    )


def test_single_exclamation_warns_but_does_not_block():
    """单个感叹号在现行官方政策里并不违规，所以只警告、不阻塞提交。

    "标题不用感叹号"是 AdWords 时代的旧指南，现行政策查不到，
    本项目保留为保守偏好，但不能因此判素材不合格。
    """
    result = creative.validate_asset("限时直降六百元!", "headline")
    severities = {i["severity"] for i in result["content_issues"]}
    assert severities == {"warning"}
    assert result["is_valid"] is True


def test_rsa_structure_rules():
    """数量不够、超上限、重复，都要拦住。"""
    too_few = creative.validate_rsa(["标题一", "标题二"], ["描述一", "描述二"])
    assert any("至少需要 3 条" in x for x in too_few["structure_issues"])

    too_many_desc = creative.validate_rsa(
        ["一", "二", "三"], ["d1", "d2", "d3", "d4", "d5"]
    )
    assert any("超过上限" in x for x in too_many_desc["structure_issues"])

    duplicated = creative.validate_rsa(["同一句", "同一句", "不同"], ["d1", "d2"])
    assert any("标题有重复" in x for x in duplicated["structure_issues"])


def test_rsa_ready_to_submit_only_when_everything_passes():
    good = creative.validate_rsa(
        headlines=["跑鞋官方旗舰店", "全国包邮送到家", "三十天无理由退换", "累计售出十二万双"],
        descriptions=["全国包邮，三十天无理由退换，累计售出十二万双。", "单只重两百一十八克，长跑不压脚。"],
        paths=["跑鞋"],
    )
    assert good["ready_to_submit"] is True
    assert good["over_limit_count"] == 0


def test_rsa_warns_when_headlines_too_few_for_optimization():
    """数量合法但偏少时给建议，不阻塞——这是本项目的建议不是官方硬性要求。"""
    result = creative.validate_rsa(["一二三", "四五六", "七八九"], ["描述一", "描述二"])
    assert result["ready_to_submit"] is True
    assert any("组合优化" in w for w in result["warnings"])


def test_usp_tool_rejects_unknown_product_and_angle():
    bad_product = creative_tools.get_product_usps("不存在的产品")
    assert bad_product["status"] == "error"
    assert "可用产品" in bad_product["error_message"]

    bad_angle = creative_tools.get_product_usps("跑鞋", angle="瞎写的维度")
    assert bad_angle["status"] == "error"


def test_usp_tool_reports_missing_angles():
    """要告诉模型哪些卖点维度缺料，它才知道该找运营补什么。"""
    result = creative_tools.get_product_usps("跑鞋")
    assert result["status"] == "success"
    assert set(result["covered_angles"]) | set(result["missing_angles"]) == set(
        creative_data.USP_ANGLES
    )


def test_usp_library_covers_multiple_angles_per_product():
    """每个产品至少要覆盖 3 个卖点维度，否则 RSA 没法多角度铺开。"""
    for product in creative_data.PRODUCTS_WITH_USP:
        angles = {u.angle for u in creative_data.PRODUCT_USPS if u.product == product}
        assert len(angles) >= 3, f"{product} 只有 {len(angles)} 个维度"


def test_validate_ad_copy_gives_actionable_fix_instructions():
    """超限时要说清超几个单位、约需删几个汉字，模型才改得动。"""
    result = creative_tools.validate_ad_copy(
        headlines=["限时直降六百元包邮送好礼超值不要错过", "跑鞋旗舰店", "三十天退换"],
        descriptions=["描述一句话", "描述第二句话"],
    )
    assert result["status"] == "needs_fix"
    assert result["ready_to_submit"] is False
    assert any("约需删掉" in x for x in result["must_fix"])


def test_validate_ad_copy_rejects_empty_input():
    assert creative_tools.validate_ad_copy([], ["d1", "d2"])["status"] == "error"
    assert creative_tools.validate_ad_copy(["h1"], [])["status"] == "error"


def test_build_prompts_rejects_unknown_style_and_size():
    assert creative_tools.build_visual_prompts("theme", "不存在的风格")["status"] == "error"
    bad_size = creative_tools.build_visual_prompts("theme", "科技感", ["banner"])
    assert bad_size["status"] == "error"
    assert "可选" in bad_size["error_message"]


def test_build_prompts_embeds_brand_style_and_forbids_text():
    """prompt 必须带上品牌色与风格，并明确要求画面无文字。"""
    result = creative_tools.build_visual_prompts(
        "a pair of running shoes on a wet track", "科技感", ["landscape"]
    )
    assert result["status"] == "success"
    prompt = result["plans"][0]["prompt"]
    assert "electric cyan #00D4FF" in prompt
    assert "no text" in prompt
    # 负向 prompt 已失效，排除项必须落在正向 prompt 的 Avoid 从句里
    assert "Avoid:" in prompt


def test_landscape_needs_crop_because_no_191_ratio():
    """图像模型没有 1.91:1，横版必须走"16:9 生成 + 裁剪"这条路。"""
    spec = creative_data.AD_SIZE_SPECS["landscape"]
    assert spec.ratio_label == "1.91:1"
    assert spec.imagen_ratio == "16:9"
    assert spec.needs_crop is True
    # 正方形和竖版是原生支持的，不该标记裁剪
    assert creative_data.AD_SIZE_SPECS["square"].needs_crop is False
    assert creative_data.AD_SIZE_SPECS["vertical"].needs_crop is False


def test_image_generation_defaults_to_mock():
    """出图是花钱的操作，默认必须是 mock，不能悄悄扣费。"""
    status = config.image_generation_status()
    assert status["mode"] == "mock"
    assert status["effective_mode"] == "mock"
    assert "按张收费" in status["cost_warning"]


def test_image_model_is_one_that_actually_exists():
    """默认模型必须在实测可用列表里。

    Imagen 系列已在 Gemini API 下线（本账号 models.list() 里一个都没有），
    所以默认模型不能是 imagen-*。
    """
    status = config.image_generation_status()
    assert status["model_is_known_available"] is True
    assert not status["model"].startswith("imagen")
    assert all(not m.startswith("imagen") for m in status["available_models"])


def test_image_count_per_call_is_capped():
    """单次出图数量有硬上限，防止一句话烧掉一笔钱。"""
    assert config.image_max_per_call() <= config.IMAGE_HARD_CAP_PER_CALL


def test_render_in_mock_mode_produces_correctly_sized_files():
    """mock 出图要真的落盘，且尺寸严格等于目标广告位尺寸（含裁剪后的 1.91:1）。"""
    result = creative_tools.render_visual_assets(
        "a pair of running shoes on a wet rubber track", "科技感", ["square", "landscape"]
    )
    assert result["status"] == "success"
    assert result["mode"] == "mock"
    assert result["images_generated"] == 2

    from PIL import Image

    for asset in result["assets"]:
        assert asset["is_placeholder"] is True, "mock 模式必须标明是占位图"
        spec = creative_data.AD_SIZE_SPECS[asset["size_key"]]
        with Image.open(asset["file"]) as image:
            assert image.size == (spec.width, spec.height), asset


def test_mock_render_warns_it_is_not_usable():
    """占位图不能拿去投放，这句提醒必须在返回值里。"""
    result = creative_tools.render_visual_assets("a shoe", "简约风", ["square"])
    assert "不能拿去投放" in result["cost_note"]


def test_render_refuses_to_exceed_per_call_cap():
    """超过单次上限时要明确拒绝并说明怎么办，而不是偷偷少出几张。"""
    original = config._get

    def fake_get(key: str) -> str:
        return "1" if key == config.IMAGE_MAX_PER_CALL_ENV else original(key)

    config._get = fake_get
    try:
        result = creative_tools.render_visual_assets("a shoe", "科技感", None)
        assert result["status"] == "error"
        assert "超过单次上限" in result["error_message"]
    finally:
        config._get = original


def _make_test_image(path: pathlib.Path, size=(1200, 628)) -> None:
    """造一张左侧有高对比主体、右侧留白的测试图。"""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", size, "#F7F5F2")
    draw = ImageDraw.Draw(image)
    draw.ellipse([80, 100, 460, 500], fill="#0B1F3A")
    image.save(path)


def test_analyze_image_locates_subject_and_empty_area():
    """主体在左边，工具就该说主体在左、叠字放右——这是能客观验证的。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "t.png"
        _make_test_image(path)
        metrics = image_quality.analyze_image(path)

    assert metrics["width"] == 1200
    assert metrics["aspect_ratio"] == "1.91:1"
    assert "左" in metrics["subject"]["strongest_cell"], metrics["grid_energy"]
    assert "右" in metrics["text_overlay_suggestion"]["emptiest_cell"]
    # 断言实质而不是措辞：重心必须落在画面中线偏左。
    # 不断言 description 里有"偏左"——它有 0.42 的判定阈值，
    # 主体虽偏左但画面四边也有能量时会被判为"居中"，那是合理的保守判断。
    assert metrics["focal_point"]["x_ratio"] < 0.5, metrics["focal_point"]
    # 客观指标不能替模型下审美结论
    assert "不代表画面好看" in metrics["reminder"]


def test_analyze_image_rejects_missing_and_bad_files():
    try:
        image_quality.analyze_image("这个文件不存在.png")
    except FileNotFoundError as exc:
        assert "图片不存在" in str(exc)
    else:
        raise AssertionError("应该抛 FileNotFoundError")

    with tempfile.TemporaryDirectory() as tmp:
        fake = pathlib.Path(tmp) / "fake.png"
        fake.write_text("这不是图片", encoding="utf-8")
        try:
            image_quality.analyze_image(fake)
        except Exception as exc:
            assert isinstance(exc, (ValueError, OSError)), type(exc)
        else:
            raise AssertionError("坏文件应该报错")


def test_contrast_ratio_matches_wcag_extremes():
    """WCAG 对比度的两个端点是已知值，可以精确验证公式。"""
    assert image_quality.contrast_ratio((0, 0, 0), (255, 255, 255)) == 21.0
    assert image_quality.contrast_ratio((120, 120, 120), (120, 120, 120)) == 1.0


def test_size_compliance_tolerates_rounding_only():
    """1200x628 算 1.91:1 合规（取整误差），16:9 的图不该算合规。"""
    assert image_quality.check_size_compliance(1200, 628, "1.91")["compliant"] is True
    assert image_quality.check_size_compliance(1200, 675, "1.91")["compliant"] is False


def test_inspect_asset_returns_metrics_and_asks_model_to_look():
    """诊断工具必须把"算出来的"和"要你看的"分清楚。"""
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "t.png"
        _make_test_image(path)
        result = asyncio.run(
            creative_tools.inspect_visual_asset(
                str(path), ad_copy="限时直降六百元", target_size="landscape"
            )
        )

    assert result["status"] == "success"
    assert result["objective_metrics"]["aspect_ratio"] == "1.91:1"
    assert result["size_compliance"]["compliant"] is True
    assert result["text_legibility"]["recommended_text_color"] in ("白字", "黑字")
    # 没有 tool_context 时存不了 artifact，必须如实说明模型看不到图
    assert result["artifact_name"] is None
    assert "看不到画面" in result["your_turn"]


def test_inspect_asset_saves_artifact_when_context_available():
    """有会话上下文时要把图存成 artifact，并提示模型调 load_artifacts 亲眼看。"""

    class FakeContext:
        def __init__(self):
            self.state: dict = {}
            self.saved: dict = {}

        async def save_artifact(self, filename, artifact, custom_metadata=None):
            self.saved[filename] = artifact
            return 1

    ctx = FakeContext()
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "banner.png"
        _make_test_image(path)
        result = asyncio.run(
            creative_tools.inspect_visual_asset(str(path), tool_context=ctx)
        )

    assert result["artifact_name"] == "banner.png"
    assert "banner.png" in ctx.saved
    assert "load_artifacts" in result["your_turn"]
    assert "图文匹配度" in result["your_turn"]


def test_inspect_asset_rejects_unknown_target_size():
    with tempfile.TemporaryDirectory() as tmp:
        path = pathlib.Path(tmp) / "t.png"
        _make_test_image(path)
        result = asyncio.run(
            creative_tools.inspect_visual_asset(str(path), target_size="billboard")
        )
    assert result["status"] == "error"
    assert "可选" in result["error_message"]


if __name__ == "__main__":
    raise SystemExit(run(globals()))
