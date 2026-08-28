# 投放作战室 · Web UI

digital_marketing_agent 的专属 Web 界面：**对话式营销控制台**。
设计稿见 `../../../web_ui_design/mockup.html`（adk-workspace 根目录）。

## 结构

```
web/
├── server.py       # FastAPI 后端：把 ADK Runner 包成 SSE 接口
└── frontend/       # Next.js + Tailwind 前端
```

后端**进程内直接跑 Runner**（复用 main.py 的模式），不经 `adk web`。
前端按后端 SSE 事件渲染：工具返回值 → 结构化卡片（KPI 行/趋势图/词表/
文案校验/图片廊/审查清单/人工确认卡）。

## 怎么跑

两个终端，都在 `adk-workspace` 根目录下：

```bash
# 终端 1：后端（端口 8001）
.venv\Scripts\python.exe -m digital_marketing_agent.web.server

# 终端 2：前端（端口 3000，首次要先 npm install）
cd digital_marketing_agent\web\frontend
npm install
npm run dev
```

浏览器打开 <http://localhost:3000>。

## 后端接口一览

| 接口 | 功能 |
|---|---|
| `POST /api/chat` | 发消息，SSE 流返回（text/tool_call/tool_result/transfer/confirmation_request/error/done） |
| `POST /api/chat/confirm` | 确认卡的按钮回传。确认结果以 function_response 形式作为 user 消息喂回 runner，被拦的写操作重新执行（机制见 server.py 头注释） |
| `GET/POST/DELETE /api/sessions` | 会话管理（内存） |
| `GET /api/sessions/{id}/events` | 重放会话历史（切会话恢复对话流） |
| `GET /api/config/status` | 三盏状态灯 + 数据源体检 |
| `GET /api/config/schema` | 配置中心清单（从 config.py 生成，前端数据驱动渲染） |
| `POST /api/config/save` | 写 .env + 热更新进程环境变量；Gemini 系模型即时换 |
| `POST /api/config/test/{source}` | 连通性检测（如实返回就绪度，不发真实请求） |
| `GET /api/generated/{filename}` | 取 render_visual_assets 出的图 |
| `GET /api/artifacts/{session}/{filename}` | 取素材诊断存的 artifact 图 |

## 安全边界（与 agent 的安全设计一一对应）

- 写操作只有一条路：确认卡点确认 → `/api/chat/confirm` → ADK 的
  `require_confirmation` 机制放行。没有绕过确认的接口。
- 凭证只写不读：配置中心所有接口永不返回凭证值，已配置项只显示徽章。
- 三盏状态灯（数据源/出图/写入）实时反映 `.env` 的三重安全阀。
- 附件上传：图片走 Gemini 多模态，文本文件拼进消息；单文件 4MB 上限。

## 已知限制

- 会话和图片在内存里，重启后端即清空（学习阶段够用；要持久化换
  DatabaseSessionService，agent 不用改）。
- 图像生成里的 provider 切换（Claude/OpenAI）需要 LiteLLM，未安装——
  配置中心如实标注了，选了也只是存为预留配置。
- 除本 README 外的说明见根目录 PROJECT_STATUS.md。
