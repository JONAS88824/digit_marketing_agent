"""数字营销 agent。

ADK 发现 agent 的第一条规则是「导入这个包，看它有没有 root_agent 属性」
（见 adk/cli/utils/agent_loader.py 的 _load_from_module_or_package）。
本项目把根 agent 放在 root_agent.py 而不是 agent.py，所以必须在这里转出来，
否则 adk web 找不到它。
"""

from .root_agent import root_agent

__all__ = ["root_agent"]
