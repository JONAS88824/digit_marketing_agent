"""会话状态的共用小工具。

原来三个模块各写了一份一模一样的 `_remember`，改一处就得改三处。
提到包级共用，顺便把"为什么要有这个函数"讲清楚。

【会话状态是干什么的】
ADK 的 `tool_context.state` 是一张跨轮次的便利贴：这一轮写进去的值，
下一轮还能读到。有了它，用户说"那上周呢"、"这批词要花多少钱"这类省略句
才能接上——否则每轮都得让用户重复一遍在聊什么。
"""

from __future__ import annotations

from google.adk.tools import ToolContext


def remember(tool_context: ToolContext | None, **values) -> None:
    """把这一轮的分析对象记进会话状态。

    两条刻意的行为：
    1. `tool_context` 为空时直接返回——单元测试和脚本里没有会话，
       不该因此让工具报错。
    2. 值为 None 的键跳过不写——None 表示"这次没涉及这个对象"，
       不能用它覆盖掉上一轮记住的有效值。
    """
    if not tool_context:
        return
    for key, value in values.items():
        if value is not None:
            tool_context.state[key] = value
