r"""启动入口：命令行对话 / 一次性提问 / 起 Web 服务。

用法
----
    # 交互式命令行对话（默认）
    .venv\Scripts\python.exe -m digital_marketing_agent.main

    # 一次性提问，问完就退出（适合挂到定时任务里跑日报）
    .venv\Scripts\python.exe -m digital_marketing_agent.main --ask "最近一周投放怎么样"

    # 起 Web 服务（其实就是替你调 adk web，省得记参数）
    .venv\Scripts\python.exe -m digital_marketing_agent.main --web

【为什么需要这个文件】
adk web 已经够用，但它只有网页一种入口。有两件事它做不了：
1. 把 agent 挂到定时任务或脚本里，拿一次性答案（--ask）
2. 在没有浏览器的环境里用（服务器、SSH）

【会话与 artifact 服务】
两个都用内存实现：进程退出后会话和图片就没了。
学习阶段够用；将来要持久化，把 InMemory* 换成数据库/云存储版本即可，
agent 本身不用改。
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

from google.adk.artifacts import InMemoryArtifactService
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from . import config
from .root_agent import root_agent

APP_NAME = "digital_marketing_agent"
DEFAULT_USER_ID = "local-user"

# agent 包所在目录的上一级，也就是 adk web 要的 agents_dir
AGENTS_DIR = Path(__file__).resolve().parents[1]


def _build_runner() -> Runner:
    """装好一个可以跑对话的 Runner。

    artifact_service 必须给——creative_agent 要把生成的图片存成 artifact
    再让模型读回来看，没有这个服务那条链路会失败。
    """
    return Runner(
        app_name=APP_NAME,
        agent=root_agent,
        session_service=InMemorySessionService(),
        artifact_service=InMemoryArtifactService(),
    )


def _as_message(text: str) -> types.Content:
    return types.Content(role="user", parts=[types.Part.from_text(text=text)])


async def _run_once(runner: Runner, session_id: str, text: str) -> str:
    """发一句话，把模型最终的回答拼出来返回。

    中间事件（工具调用、转交子 agent）不打印全文，只提示一行，
    否则屏幕会被 JSON 淹没。
    """
    chunks: list[str] = []
    async for event in runner.run_async(
        user_id=DEFAULT_USER_ID,
        session_id=session_id,
        new_message=_as_message(text),
    ):
        content = getattr(event, "content", None)
        if not content or not content.parts:
            continue
        for part in content.parts:
            if getattr(part, "function_call", None):
                print(f"  · 调用工具 {part.function_call.name}", flush=True)
            elif getattr(part, "text", None) and getattr(event, "author", "") != "user":
                chunks.append(part.text)
    return "".join(chunks).strip()


def _print_startup_banner() -> None:
    """启动时把"当前是真数据还是演示数据、出图会不会花钱"讲清楚。

    这一步不是装饰。用户最容易踩的坑是拿演示数据当真实投放数据看，
    或者不知道出图要花钱就一顿猛调。
    """
    image = config.image_generation_status()
    print("=" * 62)
    print("数字营销 agent")
    print(f"  数据源模式：{config.data_source_mode()}（mock = 内置演示数据，不是真实投放数据）")
    print(f"  图像生成  ：{image['effective_mode']}（mock = 本地占位图，零成本）")
    if image["effective_mode"] == config.MODE_LIVE:
        print(f"  ⚠ 出图会按张计费，模型 {image['model']}，单次上限 {image['max_images_per_call']} 张")
    print("  三个专员：投放表现分析 / 关键词规划 / 文案与视觉创意")
    print("  输入问题开始；输入 exit 或 quit 退出。")
    print("=" * 62)


async def _chat_loop() -> int:
    """交互式命令行对话。整个会话共用一个 session，所以能接住省略句。"""
    runner = _build_runner()
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id=DEFAULT_USER_ID
    )
    _print_startup_banner()

    while True:
        try:
            text = input("\n你 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return 0
        if not text:
            continue
        if text.lower() in {"exit", "quit", "q"}:
            print("已退出。")
            return 0

        try:
            answer = await _run_once(runner, session.id, text)
        except Exception as exc:  # noqa: BLE001 - 交互模式下不该因一次报错就退出
            print(f"\n出错了：{type(exc).__name__}: {exc}")
            continue
        print(f"\nagent > {answer or '(没有返回文本)'}")


async def _ask_once(question: str) -> int:
    """一次性提问，打印答案后退出。适合挂到定时任务里。"""
    runner = _build_runner()
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id=DEFAULT_USER_ID
    )
    answer = await _run_once(runner, session.id, question)
    print(answer or "(没有返回文本)")
    return 0 if answer else 1


def _serve_web(port: int) -> int:
    """起 Web 服务。本质就是替你调 adk web，省得记 agents_dir 参数。"""
    command = [sys.executable, "-m", "google.adk.cli", "web", str(AGENTS_DIR), "--port", str(port)]
    print(f"启动 Web 服务：{' '.join(command)}")
    print(f"浏览器打开 http://127.0.0.1:{port} ，在左上角下拉里选 {APP_NAME}")
    return subprocess.call(command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="digital_marketing_agent",
        description="数字营销 agent 的启动入口：命令行对话 / 一次性提问 / Web 服务。",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--ask", metavar="问题", help="一次性提问，打印答案后退出")
    group.add_argument("--web", action="store_true", help="起 Web 服务（等价于 adk web）")
    parser.add_argument("--port", type=int, default=8000, help="Web 服务端口，默认 8000")
    args = parser.parse_args(argv)

    # 必须自己加载 .env。
    # adk web / adk run 会替你做这件事（ADK CLI 里的 load_dotenv_for_agent），
    # 但自定义入口没人替你做——不加载就没有 GOOGLE_API_KEY，
    # 第一次调模型会直接报 "No API key was provided"。
    config.load()

    if args.web:
        return _serve_web(args.port)
    if args.ask:
        return asyncio.run(_ask_once(args.ask))
    return asyncio.run(_chat_loop())


if __name__ == "__main__":
    raise SystemExit(main())
