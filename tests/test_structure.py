r"""目录结构与入口的自检测试。

【为什么专门测结构】
这些是"重构时最容易静默弄坏"的地方——代码照样能 import，
但 adk web 里点不开 agent，或者图片被写进了错误的目录，
而普通功能测试完全发现不了。

运行方式：
    .venv\Scripts\python.exe -m digital_marketing_agent.tests.test_structure
"""

import pathlib

from .. import config
from ..sub_agents.creative import visual_tools
from .test_runner import run

# 包根目录：tests → digital_marketing_agent
PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_adk_can_discover_root_agent_through_the_package():
    """ADK 找 agent 的第一条规则是"包上有没有 root_agent 属性"。

    根 agent 放在 root_agent.py 而不是 agent.py，ADK 不认识这个文件名，
    全靠 __init__.py 把 root_agent 转出来。这条断言就是守住那一行转发。
    """
    import digital_marketing_agent

    assert hasattr(digital_marketing_agent, "root_agent"), (
        "包上没有 root_agent 属性，adk web 会找不到这个 agent。"
        "检查 __init__.py 是否有 from .root_agent import root_agent"
    )


def test_root_agent_only_routes_and_has_no_business_tools():
    """根 agent 只做分发，不该挂业务工具——挂了就说明职责又糊回去了。"""
    from ..root_agent import root_agent

    assert not root_agent.tools, f"根 agent 不该挂工具，现在挂了 {len(root_agent.tools)} 个"
    assert len(root_agent.sub_agents) == 3
    assert {a.name for a in root_agent.sub_agents} == {
        "performance_agent",
        "keyword_agent",
        "creative_agent",
    }


def test_each_sub_agent_module_exposes_its_agent():
    """每个模块的 __init__.py 都要把自己的 agent 转出来，根 agent 才导得到。"""
    from ..sub_agents.creative import creative_agent
    from ..sub_agents.keywords import keyword_agent
    from ..sub_agents.performance import performance_agent

    assert performance_agent.name == "performance_agent"
    assert keyword_agent.name == "keyword_agent"
    assert creative_agent.name == "creative_agent"


def test_each_agent_keeps_its_own_tool_count():
    """工具数量对得上，防止重构时把某个模块的工具漏掉。"""
    from ..sub_agents.creative import creative_agent
    from ..sub_agents.keywords import keyword_agent
    from ..sub_agents.performance import performance_agent

    assert len(performance_agent.tools) == 8
    assert len(keyword_agent.tools) == 9
    assert len(creative_agent.tools) == 7


def test_generated_images_go_to_package_root_not_into_sub_agents():
    """出图目录必须在包根，不能因为文件挪深了就写进 sub_agents/creative/ 里。"""
    assert visual_tools.OUTPUT_DIR == PACKAGE_ROOT / "generated", (
        f"出图目录跑偏了：{visual_tools.OUTPUT_DIR}"
    )
    assert "sub_agents" not in str(visual_tools.OUTPUT_DIR)


def test_env_file_is_read_from_package_root():
    """config 读的 .env 必须是包根那一份，不是某个子目录里的。"""
    assert config._ENV_FILE == PACKAGE_ROOT / ".env"
    assert config._ENV_FILE.exists(), "包根没有 .env，agent 跑不起来"


def test_expected_layout_exists():
    """目录结构本身就是约定，缺文件要立刻发现。"""
    expected = [
        "__init__.py",
        "config.py",
        "root_agent.py",
        "main.py",
        "sub_agents/__init__.py",
        "sub_agents/performance/agent.py",
        "sub_agents/performance/tools.py",
        "sub_agents/performance/metrics.py",
        "sub_agents/performance/data.py",
        "session_state.py",
        "sub_agents/keywords/agent.py",
        "sub_agents/keywords/tools.py",
        "sub_agents/keywords/metrics.py",
        "sub_agents/keywords/data.py",
        "sub_agents/keywords/schema.py",
        "sub_agents/keywords/mock.py",
        "sub_agents/creative/agent.py",
        "sub_agents/creative/tools.py",
        "sub_agents/creative/visual_tools.py",
        "sub_agents/creative/metrics.py",
        "sub_agents/creative/image_quality.py",
        "sub_agents/creative/data.py",
        "tests/test_metrics.py",
        "tests/test_keywords.py",
        "tests/test_creative.py",
        "tests/test_runner.py",
    ]
    missing = [rel for rel in expected if not (PACKAGE_ROOT / rel).is_file()]
    assert not missing, f"缺少这些文件：{missing}"


def test_mock_data_is_isolated_from_the_access_layer():
    """演示数据和取数入口要分得干净：真接上 API 后 mock.py 能整个删掉。

    判据：schema.py（形状契约）不许 import mock，
    否则删 mock.py 会把契约一起带走。
    """
    schema_src = (PACKAGE_ROOT / "sub_agents/keywords/schema.py").read_text(encoding="utf-8")
    assert "import mock" not in schema_src
    assert "from .mock" not in schema_src

    mock_src = (PACKAGE_ROOT / "sub_agents/keywords/mock.py").read_text(encoding="utf-8")
    # mock 只依赖形状，不该反过来依赖取数层
    assert "from .data" not in mock_src
    assert "import data" not in mock_src


def test_session_helper_is_shared_not_duplicated():
    """会话状态的写入只该有一份实现，三个模块都用它。"""
    for module in ("performance", "keywords", "creative"):
        src = (PACKAGE_ROOT / f"sub_agents/{module}/tools.py").read_text(encoding="utf-8")
        assert "def _remember(" not in src, f"{module} 又抄了一份 _remember"
        assert "session_state import remember" in src, f"{module} 没用共用的 remember"


def test_copy_and_visual_tools_stay_separated():
    """文案工具不该拖进图片依赖——这是拆开这两个文件的主要目的。"""
    copy_src = (PACKAGE_ROOT / "sub_agents/creative/tools.py").read_text(encoding="utf-8")
    assert "PIL" not in copy_src, "文案工具里不该出现 Pillow"
    assert "genai" not in copy_src, "文案工具里不该出现图像模型调用"

    visual_src = (PACKAGE_ROOT / "sub_agents/creative/visual_tools.py").read_text(encoding="utf-8")
    assert "PIL" in visual_src and "genai" in visual_src


def test_main_entry_parses_arguments_without_calling_the_model():
    """入口的参数解析要能单独验证，不用真发起对话。"""
    from .. import main

    assert main.APP_NAME == "digital_marketing_agent"
    # agents_dir 要指向包的上一级，adk web 才能发现同级的其它 agent
    assert main.AGENTS_DIR == PACKAGE_ROOT.parent

    # --help 会往 stdout 打一屏用法，测试里吞掉，别污染测试输出
    import contextlib
    import io

    parser_ok = True
    with contextlib.redirect_stdout(io.StringIO()):
        try:
            main.main(["--help"])
        except SystemExit as exc:
            parser_ok = exc.code == 0
    assert parser_ok, "--help 应该正常退出"


if __name__ == "__main__":
    raise SystemExit(run(globals()))
