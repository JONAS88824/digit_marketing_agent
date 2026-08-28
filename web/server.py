"""FastAPI Web 服务：把 ADK Runner 包成 SSE 接口，给 Next.js 前端用。

运行方式（在 adk-workspace 根目录）：
    .venv\\Scripts\\python.exe -m digital_marketing_agent.web.server
    # 或
    .venv\\Scripts\\python.exe -m uvicorn digital_marketing_agent.web.server:app --port 8001

【设计要点】
1. 进程内直接跑 Runner（复用 main.py 的模式），不经过 adk web 的通用服务。
2. 人工确认的接线（已对照 ADK 2.6.2 源码核实）：
   - 模型想调写工具时，框架不执行，而是发出一个名叫 adk_request_confirmation
     的函数调用事件（functions.py 的 generate_request_confirmation_event）。
   - 用户的确认/取消，要以 function_response 的形式作为一条 user 消息喂回
     runner（request_confirmation.py 的 _RequestConfirmationLlmRequestProcessor
     读的就是"最后一条 user 事件里的 adk_request_confirmation 响应"）。
   - 所以 /api/chat/confirm 不是简单打个标，而是把确认结果作为 new_message
     再跑一轮 run_async，流程会自动续上并产出后续事件（同一套 SSE 流）。
3. 凭证安全底线延续 config.py：所有接口只报键名和状态，永不返回值。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from google.adk.artifacts import InMemoryArtifactService
from google.adk.flows.llm_flows.functions import REQUEST_CONFIRMATION_FUNCTION_CALL_NAME
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .. import config
from ..root_agent import root_agent

APP_NAME = "digital_marketing_agent"
DEFAULT_USER_ID = "web-user"

# 前端开发服务器。生产部署同源后这个 CORS 可以收紧或去掉。
FRONTEND_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

app = FastAPI(title="投放作战室 API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 自定义入口没人替我们加载 .env（ADK CLI 才会做），必须自己来，
# 否则第一次调模型直接报 "No API key was provided"（main.py 踩过的同一个坑）。
config.load()

_session_service = InMemorySessionService()
_artifact_service = InMemoryArtifactService()
_runner = Runner(
    app_name=APP_NAME,
    agent=root_agent,
    session_service=_session_service,
    artifact_service=_artifact_service,
)


# ============================ 会话 ============================

class CreateSessionRequest(BaseModel):
    """空请求体：新建会话不需要参数。"""


@app.post("/api/sessions")
async def create_session(_req: CreateSessionRequest | None = None) -> dict[str, str]:
    session = await _session_service.create_session(
        app_name=APP_NAME, user_id=DEFAULT_USER_ID
    )
    return {"session_id": session.id}


@app.get("/api/sessions")
async def list_sessions() -> dict[str, Any]:
    response = await _session_service.list_sessions(
        app_name=APP_NAME, user_id=DEFAULT_USER_ID
    )
    # InMemorySessionService 返回 ListSessionsResponse，会话列表在 .sessions 里
    found = getattr(response, "sessions", response)
    items = [
        {"session_id": s.id, "updated_at": getattr(s, "last_update_timestamp", None)}
        for s in found
    ]
    # 新的排前面
    items.sort(key=lambda x: x["updated_at"] or 0, reverse=True)
    return {"sessions": items}


@app.get("/api/sessions/{session_id}/events")
async def session_events(session_id: str) -> dict[str, Any]:
    """重放一个会话的历史事件（翻译成与 /api/chat 同格式）。

    前端切换会话时用它恢复对话流；agent 端不需要任何改动，
    因为事件本来就存在 Session 里，这里只是再翻译一遍。
    """
    session = await _session_service.get_session(
        app_name=APP_NAME, user_id=DEFAULT_USER_ID, session_id=session_id
    )
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")
    events = []
    for event in session.events:
        events.extend(_translate_event(event, session_id))
    return {"session_id": session_id, "events": events}


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    await _session_service.delete_session(
        app_name=APP_NAME, user_id=DEFAULT_USER_ID, session_id=session_id
    )
    return {"ok": True}


# ============================ 配置体检与配置中心 ============================

@app.get("/api/config/status")
async def config_status() -> dict[str, Any]:
    """三盏状态灯 + 各数据源体检。全部来自 config.py，天然不含凭证值。"""
    report = config.describe()
    image = config.image_generation_status()
    ads_write = config.ads_write_status()
    return {
        "data_source_mode": report["requested_mode"],
        "image": {
            "effective_mode": image["effective_mode"],
            "api_key_configured": image["api_key_configured"],
            "max_images_per_call": image["max_images_per_call"],
        },
        "ads_write": {
            "effective_mode": ads_write["effective_mode"],
            "credentials_configured": ads_write["credentials_configured"],
            "write_implemented": ads_write["write_implemented"],
        },
        "sources": report["sources"],
        "note": report["note"],
    }


# 各 .env 键的填写提示。新增数据源时在 config.py 加凭证要求、这里加提示即可。
_ENV_KEY_NOTES: dict[str, str] = {
    "GOOGLE_ADS_DEVELOPER_TOKEN": "需 Google 审核，通过后才能调 API",
    "CUSTOMER_ID": "10 位纯数字，不带横线",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "选填，仅 MCC 经理账号需要",
    "GA4_PROPERTY_ID": "纯数字",
    "GA4_CREDENTIALS_JSON_PATH": "服务账号密钥文件路径",
    "SEARCH_CONSOLE_SITE_URL": "须与后台属性完全一致（含结尾斜杠）",
    "COMPETITOR_INTEL_BASE_URL": "厂商中立，换厂商只改这里",
    "IMAGE_GENERATION_MODE": "mock = 占位图零成本；live = 按张计费",
}

# 凭证键：值是敏感的，保存后只显示"已配置"，永不回显
_SECRET_KEYS = {
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "COMPETITOR_INTEL_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
}

# 数据源展示名（键来自 config.ALL_SOURCES）
_SOURCE_DISPLAY_NAMES = {
    "google_ads": "Google Ads",
    "ga4": "GA4（站内数据 + 转化词）",
    "keyword_planner": "Keyword Planner（共用 Ads 凭证）",
    "search_console": "Search Console（SEO 词库）",
    "competitor_intel": "第三方竞品情报",
}


def _build_config_schema() -> dict[str, Any]:
    """生成配置中心的清单。键名来自 config.py 的凭证要求，界面只负责渲染。"""
    groups: list[dict[str, Any]] = []

    # 第一组：模型与引擎。provider 切换需要 LiteLLM（未装），
    # 先如实标注；Gemini 内换模型可以真实生效（保存时直接改 agent 属性）。
    groups.append({
        "name": "模型与引擎（Provider / Model）",
        "fields": [
            {
                "key": "MODEL_PROVIDER", "type": "select", "value": "google",
                "note": "换引擎后模型列表与 API key 字段会随之刷新",
                "options": [
                    {"value": "google", "label": "Google Gemini（当前）"},
                    {"value": "anthropic", "label": "Anthropic Claude（需 LiteLLM，未安装）"},
                    {"value": "openai", "label": "OpenAI（需 LiteLLM，未安装）"},
                ],
            },
            {
                "key": "MODEL", "type": "select", "value": str(root_agent.model),
                "note": "五个 agent 共用同一模型；创意/风控各自的温度分层不受影响",
                "options": [
                    {"value": "gemini-2.5-flash", "label": "gemini-2.5-flash（速度与质量平衡）"},
                    {"value": "gemini-2.5-pro", "label": "gemini-2.5-pro（更强，更贵）"},
                    {"value": "gemini-2.5-flash-lite", "label": "gemini-2.5-flash-lite（更快更省）"},
                ],
            },
            {"key": "GOOGLE_API_KEY", "type": "password", "secret": True},
        ],
    })

    # 数据源组：键名直接来自 config._REQUIRED_BY_SOURCE，两边不会漂移
    for source in config.ALL_SOURCES:
        required = list(getattr(config, "_REQUIRED_BY_SOURCE", {}).get(source, ()))
        fields = []
        for key in required:
            fields.append({
                "key": key,
                "type": "password" if key in _SECRET_KEYS else "text",
                "note": _ENV_KEY_NOTES.get(key, ""),
                "secret": key in _SECRET_KEYS,
            })
        # Ads 的选填键
        if source in ("google_ads", "keyword_planner"):
            for key in getattr(config, "_ADS_OPTIONAL", ()):
                fields.append({
                    "key": key,
                    "type": "text",
                    "note": _ENV_KEY_NOTES.get(key, ""),
                    "optional": True,
                })
        groups.append({"name": _SOURCE_DISPLAY_NAMES.get(source, source), "fields": fields})

    # 图像生成组
    groups.append({
        "name": "图像生成",
        "fields": [
            {"key": "GOOGLE_API_KEY", "type": "password", "secret": True},
            {
                "key": "IMAGE_GENERATION_MODE", "type": "select", "value": config.image_generation_mode(),
                "note": _ENV_KEY_NOTES["IMAGE_GENERATION_MODE"],
                "options": [
                    {"value": "mock", "label": "mock（占位图，零成本）"},
                    {"value": "live", "label": "live（按张计费，需已开通付费）"},
                ],
            },
        ],
    })

    # 已配置标记：值不回显，只打一个"已配置"徽章
    import os

    for group in groups:
        for field in group["fields"]:
            field["configured"] = bool((os.environ.get(field["key"]) or "").strip())
        # 数据源组带上 source 标识，前端的"测连通"按钮才知道打哪个接口
        for source, display in _SOURCE_DISPLAY_NAMES.items():
            if group["name"] == display:
                group["source"] = source
    return {
        "groups": groups,
        # 换引擎时前端联动刷新模型列表用
        "provider_models": {
            "google": ["gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"],
            "anthropic": ["claude-sonnet-5", "claude-haiku-4-5", "claude-opus-5"],
            "openai": ["gpt-5.2", "gpt-5.2-mini"],
        },
        "provider_keys": {
            "google": "GOOGLE_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
        },
    }


@app.get("/api/config/schema")
async def config_schema() -> dict[str, Any]:
    return _build_config_schema()


class SaveConfigRequest(BaseModel):
    values: dict[str, str]


def _apply_model_to_agents(model: str) -> None:
    """把模型切到 root + 四个专员身上。

    agent.model 是运行时每次构造 LLM 请求都会读的属性，直接改属性即可，
    不需要动 agent 代码——这也是不改 root_agent.py 就能换模型的原因。
    """
    root_agent.model = model
    for sub in root_agent.sub_agents:
        sub.model = model


@app.post("/api/config/save")
async def save_config(req: SaveConfigRequest) -> dict[str, Any]:
    """保存配置：写 .env + 更新进程环境变量，即时生效。

    白名单校验：只接受 schema 里出现过的键，防止把任意环境变量写进 .env。
    """
    import os

    schema = _build_config_schema()
    allowed = {f["key"] for g in schema["groups"] for f in g["fields"]}
    allowed |= {"DATA_SOURCE_MODE", "ADS_WRITE_MODE"}
    rejected = [k for k in req.values if k not in allowed]
    if rejected:
        raise HTTPException(
            status_code=400, detail=f"不在配置清单里的键：{rejected}"
        )

    # 空值跳过（前端不填 = 不改这一项）
    applied = {k: v for k, v in req.values.items() if v.strip()}
    if not applied:
        return {"ok": True, "applied": [], "message": "没有要保存的值"}

    # 1. 写 .env：逐行找已存在的键则替换，找不到则追加；其余行原样保留
    env_path = config._ENV_FILE
    lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    written = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in applied:
                new_lines.append(f"{key}={applied[key]}")
                written.add(key)
                continue
        new_lines.append(line)
    for key, value in applied.items():
        if key not in written:
            new_lines.append(f"{key}={value}")
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    # 2. 更新进程环境变量：config 每次读取都查 os.environ，这里改了就即时生效
    for key, value in applied.items():
        os.environ[key] = value
    config.load()

    # 3. 换模型：直接改 agent 属性，立即生效。
    #    只有 Gemini 系的模型名才真正应用——Claude/OpenAI 需要 LiteLLM 网关，
    #    直接把名字挂到 agent 上会在调 Gemini API 时报错，所以只存为预留配置。
    note = "已写入 .env 并生效"
    if "MODEL" in applied:
        gemini_models = {"gemini-2.5-flash", "gemini-2.5-pro", "gemini-2.5-flash-lite"}
        if applied["MODEL"] in gemini_models:
            _apply_model_to_agents(applied["MODEL"])
            note += "；模型已即时应用到当前进程"
        else:
            note += "；该模型属于非 Gemini 引擎，已存为预留配置（切换引擎需先装 LiteLLM）"

    return {"ok": True, "applied": list(applied.keys()), "message": note}


@app.post("/api/config/test/{source}")
async def test_connectivity(source: str) -> dict[str, Any]:
    """连通性检测：目前如实返回就绪度拆解（凭证/库/取数逻辑），不发真实请求。

    五个数据源的真实取数逻辑都还没实现（FETCH_IMPLEMENTED 全是 False），
    现在就发真实 API 请求只会得到误导性的"失败"。等某个 _fetch_*_live
    实现后，在这里补一次轻量真实调用即可。
    """
    if source not in config.ALL_SOURCES:
        raise HTTPException(status_code=404, detail=f"未知数据源：{source}")
    status = config.source_status(source)
    package = config.missing_package(source)
    implemented = config.FETCH_IMPLEMENTED[source]
    ready = status.configured and package is None and implemented
    if ready:
        result, detail = "ok", "凭证齐备、依赖已装、取数逻辑已实现，可切 live。"
    elif status.missing_keys:
        result, detail = "fail", f"缺 {len(status.missing_keys)} 项凭证：{'、'.join(status.missing_keys)}"
    elif package:
        result, detail = "fail", f"缺依赖库：pip install {package}"
    else:
        result, detail = "pending", "凭证齐备，但真实取数逻辑还没实现（见 PROJECT_STATUS 的未完成清单）。"
    return {"source": source, "result": result, "detail": detail}


# ============================ 对话（SSE） ============================

class Attachment(BaseModel):
    """上传的文件。图片走多模态 inline_data，文本文件拼进消息文本。"""

    filename: str
    mime_type: str
    data: str  # base64


class ChatRequest(BaseModel):
    session_id: str = ""
    message: str
    attachments: list[Attachment] = []


class ConfirmRequest(BaseModel):
    session_id: str
    function_call_id: str  # adk_request_confirmation 那个函数调用的 id
    confirmed: bool


def _translate_event(event: Any, session_id: str) -> list[dict[str, Any]]:
    """把一个 ADK Event 翻译成若干条前端友好的 JSON 事件。

    事件类型：
    - text            模型说的一段话（author 标明哪位专员在说）
    - tool_call       模型发起工具调用
    - tool_result     工具执行完的返回值（前端按工具名渲染成卡片）
    - confirmation_request  框架拦截了写操作，等用户确认
    - transfer        对话被转交给某位专员
    - artifact        有新产物（如生成的图片）
    """
    out: list[dict[str, Any]] = []
    if not event.author or event.author == "user":
        return out  # 用户自己的回声不发给前端

    for fc in event.get_function_calls() or []:
        if fc.name == REQUEST_CONFIRMATION_FUNCTION_CALL_NAME:
            # 确认请求：args 里带着原始工具调用的名字和参数
            args = fc.args or {}
            original = args.get("originalFunctionCall") or {}
            hint = (args.get("toolConfirmation") or {}).get("hint", "")
            out.append({
                "type": "confirmation_request",
                "id": fc.id,
                "tool_name": original.get("name"),
                "args": original.get("args") or {},
                "hint": hint,
                "author": event.author,
            })
        else:
            out.append({
                "type": "tool_call",
                "id": fc.id,
                "name": fc.name,
                "args": fc.args or {},
                "author": event.author,
            })

    for fr in event.get_function_responses() or []:
        out.append({
            "type": "tool_result",
            "id": fr.id,
            "name": fr.name,
            "result": fr.response,
            "author": event.author,
        })

    actions = getattr(event, "actions", None)
    if actions is not None:
        if getattr(actions, "transfer_to_agent", None):
            out.append({
                "type": "transfer",
                "to": actions.transfer_to_agent,
                "from": event.author,
            })
        if getattr(actions, "artifact_delta", None):
            out.append({
                "type": "artifact",
                "filenames": list(actions.artifact_delta.keys()),
                "session_id": session_id,
            })

    if event.content and event.content.parts:
        for part in event.content.parts:
            if getattr(part, "text", None) and not getattr(part, "thought", False):
                out.append({"type": "text", "text": part.text, "author": event.author})

    return out


async def _stream_run(new_message: types.Content, session_id: str) -> Any:
    """跑一轮 Runner，把事件翻译成 SSE 行。对话和确认共用这一段。"""
    async def generator():
        try:
            async for event in _runner.run_async(
                user_id=DEFAULT_USER_ID,
                session_id=session_id,
                new_message=new_message,
            ):
                for payload in _translate_event(event, session_id):
                    yield f"data: {json.dumps(payload, ensure_ascii=False, default=str)}\n\n"
            yield f'data: {json.dumps({"type": "done"})}\n\n'
        except Exception as exc:  # noqa: BLE001 - SSE 里报错要送到前端而不是断流
            yield (
                "data: "
                + json.dumps(
                    {"type": "error", "message": f"{type(exc).__name__}: {exc}"},
                    ensure_ascii=False,
                )
                + "\n\n"
            )
    return StreamingResponse(generator(), media_type="text/event-stream")


@app.post("/api/chat")
async def chat(req: ChatRequest) -> Any:
    session_id = req.session_id
    if not session_id:
        session = await _session_service.create_session(
            app_name=APP_NAME, user_id=DEFAULT_USER_ID
        )
        session_id = session.id
    else:
        session = await _session_service.get_session(
            app_name=APP_NAME, user_id=DEFAULT_USER_ID, session_id=session_id
        )
        if not session:
            raise HTTPException(status_code=404, detail=f"会话不存在：{session_id}")

    parts = [types.Part.from_text(text=req.message)]
    for att in req.attachments:
        import base64
        import binascii

        if len(att.data) > 4 * 1024 * 1024:  # 4MB 上限，防超大文件撑爆上下文
            raise HTTPException(status_code=400, detail=f"附件过大：{att.filename}")
        try:
            raw = base64.b64decode(att.data)
        except (binascii.Error, ValueError) as exc:
            raise HTTPException(status_code=400, detail=f"附件编码错误：{att.filename}") from exc
        if att.mime_type.startswith("image/"):
            # 图片走 Gemini 原生多模态，模型能直接看（素材诊断的入口）
            parts.append(
                types.Part.from_bytes(data=raw, mime_type=att.mime_type)
            )
        else:
            # 文本类文件（词表/文案稿等）直接拼进消息，模型能读到内容
            text = raw.decode("utf-8", errors="replace")
            if len(text) > 100_000:
                text = text[:100_000] + "\n…（内容过长，已截断）"
            parts[0] = types.Part.from_text(
                text=req.message + f"\n\n【附件 {att.filename}】\n{text}"
            )

    message = types.Content(role="user", parts=parts)
    response = await _stream_run(message, session_id)
    # 把 session_id 放在响应头里，前端首次自动建会话时能拿到
    response.headers["X-Session-Id"] = session_id
    return response


@app.post("/api/chat/confirm")
async def chat_confirm(req: ConfirmRequest) -> Any:
    """用户在确认卡上点了确认/取消。

    机制（对照 request_confirmation.py 核实）：确认结果要作为一条
    user 消息喂回去，内容是针对 adk_request_confirmation 的 function_response。
    处理器在下一轮 run_async 的 LLM 请求构造阶段读到它，重新执行被拦的
    工具（确认时）或告诉模型用户拒绝了（取消时），然后流程继续。
    """
    session = await _session_service.get_session(
        app_name=APP_NAME, user_id=DEFAULT_USER_ID, session_id=req.session_id
    )
    if not session:
        raise HTTPException(status_code=404, detail=f"会话不存在：{req.session_id}")

    # from_function_response() 不收 id 参数（这版 google.genai 的签名只有
    # name/response），所以先构造 Part 再把 id 补到 function_response 上
    confirmation_part = types.Part.from_function_response(
        name=REQUEST_CONFIRMATION_FUNCTION_CALL_NAME,
        response={"confirmed": req.confirmed},
    )
    confirmation_part.function_response.id = req.function_call_id
    confirmation = types.Content(role="user", parts=[confirmation_part])
    return await _stream_run(confirmation, req.session_id)


# ============================ 产物（生成的图片） ============================

@app.get("/api/generated/{filename}")
async def get_generated_image(filename: str) -> Response:
    """取 render_visual_assets 生成到 generated/ 目录的图片。

    出图工具把文件写进包根的 generated/（结构测试守着这条约定），
    这里把它们暴露给前端。路径做了约束：只允许取该目录下的文件。
    """
    from ..sub_agents.creative import visual_tools

    directory = visual_tools.OUTPUT_DIR.resolve()
    path = (directory / filename).resolve()
    if path.parent != directory:
        raise HTTPException(status_code=400, detail="非法路径")
    if not path.is_file():
        raise HTTPException(status_code=404, detail=f"文件不存在：{filename}")
    mime = "image/png" if path.suffix.lower() == ".png" else "application/octet-stream"
    return Response(content=path.read_bytes(), media_type=mime)


@app.get("/api/artifacts/{session_id}/{filename}")
async def get_artifact(session_id: str, filename: str) -> Response:
    part = await _artifact_service.load_artifact(
        app_name=APP_NAME,
        user_id=DEFAULT_USER_ID,
        session_id=session_id,
        filename=filename,
    )
    if part is None or not part.inline_data:
        raise HTTPException(status_code=404, detail=f"产物不存在：{filename}")
    return Response(
        content=part.inline_data.data,
        media_type=part.inline_data.mime_type or "image/png",
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8001)
