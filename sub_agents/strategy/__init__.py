"""投放策略与风控专员：方案落盘前的守门员，账号写操作的唯一出口。

模块内分五层：
- agent.py    人格、审查流程、两个写工具的确认包装
- tools.py    模型能调的 9 个工具
- checks.py   纯检查逻辑（预算/出价阀门、合规扫描、逻辑矛盾、冷启动异常）
- payload.py  Google Ads Mutate 操作的构造与依赖排序
- data.py     写入接缝（mock / live 分流）
- rules.py    规则库常量
- schema.py   契约 dataclass
"""

from .agent import strategy_agent

__all__ = ["strategy_agent"]
