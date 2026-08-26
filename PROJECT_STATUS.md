# 项目状态与架构

数字营销 agent。基于 Google ADK 2.6.2，模型 `gemini-2.5-flash`。

> **本文件是本仓库的进度单一来源。** 每次 git 提交后都要更新它，
> 具体要求见文末[文档维护要求](#文档维护要求)。

**最近更新**：2026-08-26 ｜ **当前状态**：可运行（演示数据）｜ **测试**：105/105 通过

---

## 一句话说明

两件事：

1. **投放表现分析** —— 用户问「最近投放怎么样」，agent 拉 Google Ads 和 GA4 数据，
   算出 CTR、CPC、转化率的变化，找出哪个广告系列、从哪天开始变差。
2. **关键词规划** —— 用户问「接下来投什么词」，agent 按行业/产品选词，
   预测搜索量趋势与投放成本，对比竞品投放词与自然搜索词库，
   由大模型做意图聚类、长尾拓展、负向词筛选，最后用 GA4 真实转化词校验方案。
3. **文案与视觉创意** —— 用户问「广告长什么样」，agent 基于产品卖点写多版本
   RSA 标题与描述并做严格字符校验，把营销主题转成图像 prompt 批量出图
   （1:1 / 1.91:1 / 9:16），再对素材做质量诊断（主体突出度、对比度、
   视觉焦点、叠字可读性、图文匹配度）。

目前跑的是**内置演示数据**，五个真实 API 的凭证和取数逻辑还没接
（见[接入进度](#真实-api-接入进度)）；图像生成默认走本地占位图，
真出图要显式打开开关（**按张计费**）。

---

## 架构图

```mermaid
flowchart TB
    User(["用户提问"]) --> Root

    subgraph Root["🤖 root_agent · 接待与路由"]
        Route{"过去 / 未来 / 长相？"}
    end

    Route -->|"已花的钱效果如何"| Perf
    Route -->|"接下来投什么词"| Kw
    Route -->|"广告长什么样"| Cr

    subgraph Perf["📉 performance_agent · 8 工具"]
        P1["投放快照 / 环比 / 逐日趋势<br/>GA4 交叉验证 / 配置体检"]
    end

    subgraph Kw["🔑 keyword_agent · 9 工具"]
        K1["选词 / 成本预测 / 竞品词<br/>SEO 词库 / 真实转化词<br/>结构分析 / 方案存档"]
    end

    subgraph Cr["✍️ creative_agent · 7 工具"]
        C1["卖点原料 / RSA 文案校验<br/>视觉 prompt / 批量出图<br/>素材诊断 / 读图"]
    end

    Perf --> CalcA["🧮 metrics.py<br/>CTR · CPC · 转化率 · 环比"]
    Kw --> CalcB["🧮 keywords.py<br/>词根 · 趋势 · 成本 · 集合对比"]
    Cr --> CalcC["🧮 creative.py<br/>字符宽度 · RSA 合规"]
    Cr --> CalcD["🧮 image_quality.py<br/>对比度 · 主体 · 焦点 · 叠字区"]

    Kw -.->|"没有唯一答案的活"| Brain1["🧠 词根聚类 · 长尾拓展 · 负向词筛选"]
    Cr -.->|"没有唯一答案的活"| Brain2["🧠 文案创作 · 画面审美 · 图文匹配"]

    Perf --> SrcA
    Kw --> SrcB
    Cr --> SrcC

    subgraph SrcA["📊 data.py · 投放数据"]
        SwA{"mock / live"}
    end
    subgraph SrcB["📊 keywords_data.py · 关键词数据"]
        SwB{"mock / live"}
    end
    subgraph SrcC["🎨 creative_data.py + 图像模型"]
        SwC{"占位图 / 真出图<br/>真出图按张计费"}
    end

    Config["⚙️ config.py<br/>5 个数据源 + 图像开关<br/>只报键名，不外泄凭证值"] --> SwA
    Config --> SwB
    Config --> SwC
    Env[(".env")] --> Config

    SwA -.->|"待接入"| E1["Google Ads API"]
    SwA -.->|"待接入"| E2["GA4 Data API"]
    SwB -.->|"待接入"| E3["Keyword Planner"]
    SwB -.->|"待接入"| E4["Search Console"]
    SwB -.->|"待接入"| E5["第三方竞品情报"]
    SwC -->|"已可用"| E6["Gemini 原生图像模型<br/>Imagen 系列已下线"]
```

**贯穿全局的一条红线：数字由 Python 算，判断交给模型。**
CTR 算错一位就是错误的投放决策，所以计算全部收进 `metrics.py` 和 `keywords.py`——
它们不依赖 ADK、不碰网络，因此能单独跑测试验证对错。
模型只负责拿算好的数字去解读、聚类、取舍。

**为什么拆子 agent**：三块业务加起来 24 个工具。挂在一个 agent 上，
模型每次要在 24 个里挑，名字相近的（`get_ads_metrics` vs `plan_keywords`
vs `validate_ad_copy`）容易选错，instruction 也会因为要同时写三套流程而臃肿。
拆开后每个专员只面对自己的 7-9 个工具。

---

## 文件职责

| 文件 | 职责 | 改动时要注意 |
|---|---|---|
| `agent.py` | root_agent（路由）+ performance_agent + keyword_agent | ADK 只认 `root_agent` 这个变量名 |
| `tools.py` | 投放分析的 8 个工具 | 函数名+类型注解+docstring 就是模型的说明书 |
| `metrics.py` | 投放指标纯计算：聚合、派生、环比、好坏判定 | 不依赖 ADK，改动必须补测试 |
| `data.py` | 投放数据源：mock/live 分流 + Ads/GA4 接缝 | 真实取数只需填两个 `_fetch_*_live` |
| `keyword_tools.py` | 关键词规划的 9 个工具 | 只做确定性计算，语义判断要明确交回模型 |
| `keywords.py` | 关键词纯计算：归一化、词根、趋势、成本预估、集合对比 | 成本预估带假设值，返回里必须留警告 |
| `keywords_data.py` | 关键词数据源：演示词库 + 四个来源的接缝 | 已 560 行，再长就该拆成"数据"和"接缝"两个文件 |
| `creative_tools.py` | 文案与视觉的 7 个工具（含 ADK 内置 load_artifacts） | 出图工具会花钱，改动要保住成本护栏 |
| `creative.py` | 文案纯计算：字符宽度、RSA 合规、结构校验 | 字符宽度是全项目最不能错的一处 |
| `image_quality.py` | 图片纯计算：对比度、主体、视觉焦点、叠字区 | 只用 Pillow，不引 numpy |
| `creative_data.py` | 卖点原料库、品牌风格预设、广告尺寸规范 | 卖点必须是事实，不能是形容词 |
| `config.py` | 读 `.env`，回答「配了没有」，产出待办清单 | **绝不能返回凭证的值**，有测试守着 |
| `test_metrics.py` | 投放分析层 27 个测试 | 改了计算或配置逻辑就要跑 |
| `test_keywords.py` | 关键词层 42 个测试 | 同上 |
| `test_creative.py` | 文案与视觉层 36 个测试 | 同上 |
| `test_runner.py` | 共享的极简测试运行器 | 不依赖 pytest，同时兼容 pytest 收集 |
| `.env` | 真实凭证与数据源开关 | 已 gitignore，永不提交 |
| `.env.example` | 可提交的配置模板，值全部为空 | 有测试检查它不含真值 |

---

## 已完成

### 投放表现分析

- [x] 8 个工具：家底查询、配置体检、Ads 快照/环比、GA4 快照/环比、逐日趋势、会话上下文
- [x] **指标口径正确**：CTR/CPC/转化率先加总再相除（不是按日平均），0 除数返回 `None` 而不是 0
- [x] **涨跌方向感知**：CTR 涨是好事、CPC 涨是坏事、花费涨算中性（可能是主动加预算），变化 <15% 不报警
- [x] **异常定位链路**：环比找「变差了」→ 逐日趋势找「从哪天开始」→ GA4 交叉验证「广告端还是站内」

### 关键词规划

- [x] **9 个工具**：范围查询、选词、成本预测、竞品词、SEO 词库、真实转化词、结构分析、方案存档、会话上下文
- [x] **按行业/产品选词**：搜索量、CPC、竞争度、首页出价区间，字段对齐 Keyword Planner
- [x] **搜索量趋势**：12 个月序列压成「在涨/在跌/平稳 + 旺季是哪月 + 季节性倍数」，
      用最近 3 月均值 vs 前 3 月均值对比，避免把单月噪声当趋势
- [x] **成本预测**：预计点击、月花费、均价，**并强制带上假设值警告**（点击率是经验假设，不是承诺）
- [x] **竞品缺口分析**：传入我方词表才算缺口，输出「都在投/只有我投/只有它投」
- [x] **SEO 词库**：点击、曝光、点击率、平均排名，附带匿名化查询的完整性提醒
- [x] **GA4 转化归因**：真实转化过的搜索词 + 转化率 + 单次会话价值，作为规划的锚点
- [x] **语义活交给模型**：`analyze_keyword_structure` 只给确定性原料（词根分组、重复项、
      负向规则命中、跨来源覆盖），聚类/长尾/负向筛选明确交回模型判断
- [x] **方案存档带校验**：`record_keyword_plan` 会拦住跨组重复和「既投又排除」的自相矛盾

### 文案与视觉创意

- [x] **7 个工具**：范围查询、卖点原料、RSA 校验、视觉 prompt、批量出图、素材诊断、读图
- [x] **字符宽度按 Google 口径算**：全角字符每个算 2 个单位，
      所以纯中文标题实际 15 字、描述 45 字。中英混排逐字符累加，天然正确
- [x] **校验结果可直接行动**：告诉模型"超了几个单位、约需删几个汉字、还能再写几个字"，
      而不是只说"超限了"
- [x] **合规规则分级**：官方明令禁止的（连续标点、滥用大写、逐字母加点、写电话号码、
      素材重复）判 error 阻塞提交；本项目的保守偏好（少用感叹号）判 warning 不阻塞
- [x] **卖点分六维度铺开**：痛点/优惠/信任/服务/功能/场景，并报出哪些维度缺料
- [x] **视觉 prompt 带品牌一致性**：主色、氛围、光线、构图从品牌风格预设注入
- [x] **1.91:1 的裁剪方案**：图像模型不支持 1.91:1，按 16:9 生成后居中裁剪，
      并提醒 prompt 里让主体避开上下边缘
- [x] **出图成本护栏**：默认 mock 画本地占位图（零成本），live 需显式开启，
      单次出图有硬上限，占位图明确标注"不能投放"
- [x] **素材诊断分两层**：Pillow 算客观指标（对比度、主体突出度、九宫格视觉焦点、
      最适合叠字的区域、叠字对比度是否达 WCAG 4.5），
      再把图存成 artifact 让模型调 load_artifacts **亲眼看**，判断吸引力与图文匹配

### 架构与安全

- [x] **拆子 agent**：root 路由 + performance_agent + keyword_agent + creative_agent，各管自己的工具
- [x] **凭证与配置分离**：五个数据源的凭证全在 `.env`，代码只读键名
- [x] **配置体检不外泄凭证值**，只返回键名与是否已配置（有测试守着）
- [x] **双重安全阀**：模式=live **且**凭证齐备才走真实 API，否则退回演示数据
- [x] **该用真实数据却用不了时明确报错**，绝不拿演示数据顶替
- [x] **依赖库已装**：`google-ads 31.4.0`、`google-analytics-data 0.23.0`、`google-api-python-client`、`Pillow 12.3.0`

## 未完成

- [ ] **填 Google Ads 凭证**（5 项，developer token 需 Google 审核；Keyword Planner 共用这套）
- [ ] **填 GA4 配置**（2 项）
- [ ] **填 Search Console 配置**（2 项，注意服务账号可用性未经官方确认）
- [ ] **买第三方竞品情报**（2 项：端点 + 密钥）
- [ ] **实现 5 个真实取数函数**：`data.py` 两个、`keywords_data.py` 四个（GA4 那个两处共用）
- [ ] **真出图**：把 `.env` 的 `IMAGE_GENERATION_MODE` 改成 `live`（按张计费，需已开通付费）。
      代码路径已写好并对照本账号可用模型核对过，但**没有花钱实测过一次**
- [ ] 评估测试（agent 回答质量的自动打分）
- [ ] 部署

**明确不做**：定时任务。被动触发是设计选择——每次分析都带着用户的具体问题，
不产出没人看的定时报告，也不在没人关注时白烧 API 配额。
真需要定期报告时由外部定时器触发一次对话即可，agent 这边不用改。

---

## 真实 API 接入进度

就绪度拆成三项分开看，因为三件事的负责人不一样：装库是环境问题，
填凭证要去申请，写取数逻辑是写代码。糊成一个「没配好」就不知道该干哪件。

| 数据源 | 依赖库 | 凭证 | 取数逻辑 | 生效模式 |
|---|---|---|---|---|
| **Google Ads**（投放数据） | ✅ 已装 | ❌ 5 项待填 | ❌ 待实现 | 演示数据 |
| **GA4**（站内数据 + 转化词） | ✅ 已装 | ❌ 2 项待填 | ❌ 待实现 | 演示数据 |
| **Keyword Planner**（选词） | ✅ 已装 | ❌ 共用 Ads 凭证 | ❌ 待实现 | 演示数据 |
| **Search Console**（SEO 词库） | ✅ 已装 | ❌ 2 项待填 | ❌ 待实现 | 演示数据 |
| **第三方竞品情报** | ✅ 无需专用库 | ❌ 2 项待填 | ❌ 待实现 | 演示数据 |
| **图像生成**（出图） | ✅ 已装 Pillow | ✅ API key 已配 | ✅ 已写好 | **本地占位图**（开关未开） |

随时可以问 agent「我还缺什么凭证」，它会调 `check_data_source_config`
报出精确的缺失项和待办清单（只报键名，不报值）。

### 各家需要什么（已核对官方文档与已安装库的源码）

**Google Ads + Keyword Planner**（`.env` 5 项 + 1 项选填，两者共用）

`GOOGLE_ADS_DEVELOPER_TOKEN`（需 Google 审核）、`CLIENT_ID`、`CLIENT_SECRET`、
`REFRESH_TOKEN`、`CUSTOMER_ID`（10 位纯数字不带横线），MCC 经理账号再加 `LOGIN_CUSTOMER_ID`。

两个容易踩的点：`use_proto_plus=True` 是库的**硬性必填项**（写在代码里，不进 `.env`）；
`customer_id` 不是客户端配置，而是调用参数。

选词用 `KeywordPlanIdeaService.generate_keyword_ideas()`，返回的 `keyword_idea_metrics`
里带 `avg_monthly_searches`、`competition`、`average_cpc_micros` 和
`monthly_search_volumes`（12 个月趋势）。所有 micros 字段除以 1,000,000 才是元。
**用户意图 API 不提供**，得靠大模型判断。

**GA4**（`.env` 2 项）

`GA4_PROPERTY_ID`（纯数字，拼成 `properties/<数字>`）、`GA4_CREDENTIALS_JSON_PATH`。

刻意**不用** Google 标准的 `GOOGLE_APPLICATION_CREDENTIALS`：那是全局凭证变量，
进程里所有 Google 客户端都读它，将来 ADK 切到 Vertex 模式会互相干扰。

搜索词维度：`sessionGoogleAdsKeyword`（你出价的词）、`sessionGoogleAdsQuery`（用户真实搜的词）、
`searchTerm`（站内搜索框，仅事件级）。**GA4 没有任何自然搜索关键词维度**——
自然搜索的词只能从 Search Console 拿，这就是为什么要同时接这两个源。

指标要用新名字：**`conversions` 已废弃**，2024-05 起改名 `keyEvents`
（`sessionConversionRate` → `sessionKeyEventRate`）。且 `keyEvents` 是所有关键事件的合计，
要看单个转化得加 `eventName` 维度 + 过滤器。

**Search Console**（`.env` 2 项）

`SEARCH_CONSOLE_SITE_URL`、`SEARCH_CONSOLE_CREDENTIALS_JSON_PATH`。
scope 用 `https://www.googleapis.com/auth/webmasters.readonly`。

siteUrl 两种写法必须与后台完全一致：URL 前缀属性 `https://example.com/`（含结尾斜杠），
或域名属性 `sc-domain:example.com`（覆盖全部子域与协议，需 DNS 验证）。

客户端是 `build('searchconsole', 'v1', ...)`，调 `searchanalytics().query()`。
四个坑：**返回的 ctr 是 0~1 小数不是百分比**；`rowLimit` 默认 1000、上限 25000，
更多要用 `startRow` 翻页；数据有 2~3 天延迟；**搜索量过少的词会被匿名化隐去**，
所以所有 query 行的点击加起来永远小于站点总点击，翻页也补不回来。

⚠️ **服务账号能否用于 Search Console，官方文档并未说明。** 社区做法是把服务账号邮箱
加为站点用户，但未经官方确认。真接的时候要留验证时间，必要时改用普通 OAuth 用户授权。

**第三方竞品情报**（`.env` 2 项）

`COMPETITOR_INTEL_BASE_URL`、`COMPETITOR_INTEL_API_KEY`。

竞品投放词 Google 官方不提供（Ads API 只能看自己的账户），只能买第三方数据
（SEMrush / Ahrefs / SpyFu / DataForSEO 等）。这里刻意做成**厂商中立**：
只认端点和密钥，换厂商只改 `keywords_data.py` 里一个函数。

两个提醒：第三方数据是**估算**不是竞品真实数据，只能判断方向；
这类接口按调用次数计费，别在循环里逐词查。

---

### 图像生成：Imagen 已下线，改用 Gemini 原生图像模型

⚠️ **这一条推翻了常见做法，务必知道**：用本账号的 API key 调
`client.models.list()` 实测，**列表里没有任何 `imagen-*` 模型**。
Imagen 3 已在 Gemini API 下线，Imagen 4 也已到停用日期。
所以网上大量教程里的 `client.models.generate_images()`（Imagen 的 predict 接口）
在这里根本调不通。

实测该账号可用的图像模型（都只支持 `generateContent`，不支持 `generate_images`）：

| 模型 | 定位 |
|---|---|
| `gemini-3.1-flash-lite-image` | 最便宜，1K 分辨率 |
| `gemini-2.5-flash-image` | 上一代，官方建议迁走 |
| `gemini-3.1-flash-image` | **当前默认**，文字渲染好、支持参考图 |
| `gemini-3-pro-image` | 最贵，图文交错输出 |

正确的调用方式：

```python
client.models.generate_content(
    model="gemini-3.1-flash-image",
    contents=prompt,
    config=types.GenerateContentConfig(
        response_modalities=["IMAGE"],
        image_config=types.ImageConfig(aspect_ratio="16:9"),
    ),
)
# 图片在 response.candidates[0].content.parts[i].inline_data.data
```

三个连带影响：

1. **没有 1.91:1 这个比例**。支持的是 1:1 / 3:4 / 4:3 / 9:16 / 16:9 这类
   （Nano Banana 系列多几个，但依然没有 1.91:1）。
   所以横版 banner 只能按 16:9 生成再居中裁剪——prompt 里要让主体避开上下边缘。
2. **负向 prompt 已失效**。当前这代模型不再支持单独的 negative prompt，
   不要的元素必须写进正向 prompt 的 Avoid 从句。
3. **免费额度不覆盖图像生成**，需要账号已开通付费。所以默认 mock。

配置项在 `.env`：`IMAGE_GENERATION_MODE`（mock/live）、`IMAGE_MODEL`、
`IMAGE_MAX_PER_CALL`（单次出图上限，硬上限 6）。
刻意和 `DATA_SOURCE_MODE` 分成两个开关——取数是只读的，出图是**真花钱**。

---

## 怎么运行

```bash
# 启动 web 界面（在工作区根目录执行）
cd D:\Projects\adk-workspace
.venv\Scripts\activate
adk web
# 然后在左上角下拉里选 digital_marketing_agent

# 跑自检测试（不联网、不消耗 API 配额）
.venv\Scripts\python.exe -m digital_marketing_agent.test_metrics    # 27 个
.venv\Scripts\python.exe -m digital_marketing_agent.test_keywords   # 42 个
.venv\Scripts\python.exe -m digital_marketing_agent.test_creative   # 36 个
```

生成的图片落在 `generated/`（已 gitignore）。mock 模式下是**占位图，不能投放**。

可以试着问：

| 问什么 | 会转交给 |
|---|---|
| 最近一周投放怎么样 / CPC 是不是涨了 / 哪个广告系列拖后腿 | performance_agent |
| 从哪天开始变差的 / 我还缺什么凭证 | performance_agent |
| 运动户外这个行业该投什么词 / 这批词要花多少钱 | keyword_agent |
| 竞品在投什么 / 哪些词该加进负向词 / 关键词怎么分组 | keyword_agent |
| 给跑鞋写一套搜索广告文案 / 标题超字数了帮我压一下 | creative_agent |
| 生成三个尺寸的 banner / 这张素材行不行 / 图文搭不搭 | creative_agent |
| 哪些词表现差、该换成什么词、再写套文案 | 依次转交三个专员，一次一个 |

---

## 变更记录

新的记录加在最上面。

| 日期 | 类型 | 变更内容 |
|---|---|---|
| 2026-08-26 | feat | **营销文案与视觉创意**。新增 `creative_data.py` / `creative.py` / `image_quality.py` / `creative_tools.py`（7 个工具）：RSA 多版本文案 + 全角字符严格校验、卖点六维度覆盖、视觉 prompt 构筑、三尺寸批量出图（含 1.91:1 裁剪）、素材质量诊断（客观指标 + 交模型读图）；新增 36 个测试 |
| 2026-08-26 | refactor | 架构加入第三个专员 `creative_agent`，root 路由改为「过去/未来/长相」三分 |
| 2026-08-26 | fix | 实测本账号 `models.list()` 后确认 **Imagen 系列已在 Gemini API 全部下线**，改用 `gemini-3.1-flash-image` 走 `generate_content` + `image_config`；负向 prompt 已失效，排除项改写进正向 prompt |
| 2026-08-26 | fix | 核对官方政策后修正感叹号规则：「标题不用感叹号」是 AdWords 旧指南、现行政策查不到，降级为 warning 不再阻塞提交 |
| 2026-08-26 | chore | 安装 `Pillow 12.3.0`（图片指标计算与占位图）；`.env` 加入图像生成开关 |
| 2026-08-26 | feat | **关键词规划功能**。新增 `keywords_data.py` / `keywords.py` / `keyword_tools.py`（9 个工具），覆盖行业选词、搜索量趋势与成本预测、竞品词缺口、SEO 词库、GA4 转化归因、意图聚类原料与方案存档；新增 42 个测试 |
| 2026-08-26 | refactor | 架构拆成 root_agent 路由 + performance_agent + keyword_agent 两个专员；测试运行器提取为共享 `test_runner.py` |
| 2026-08-26 | feat | config 扩展到 5 个数据源（新增 Keyword Planner / Search Console / 第三方竞品情报），`.env` 与模板同步 |
| 2026-08-26 | fix | 核对官方 schema 后修正 GA4 指标名：`conversions` 已废弃，改用 `keyEvents` |
| 2026-08-26 | chore | 安装 `google-api-python-client`（Search Console 用） |
| 2026-08-26 | feat | 初始化独立仓库。数据分析 agent 骨架 + 8 个工具 + 分层架构 + 演示数据 + 27 个自检测试 |
| 2026-08-26 | feat | 凭证配置层：`.env` 加入 Ads/GA4 配置项与模式开关，`config.py` 只读键名不外泄值，`.env.example` 模板 |
| 2026-08-26 | fix | 核对官方文档后修正 GA4 配置：改用 `GA4_CREDENTIALS_JSON_PATH` 显式传参，替代全局的 `GOOGLE_APPLICATION_CREDENTIALS` |
| 2026-08-26 | chore | 安装 `google-ads 31.4.0`、`google-analytics-data 0.23.0`（纯新增依赖，未升降级既有包） |

---

## 文档维护要求

**每次 git 提交后，必须更新本文件。** 这不是可选项——本文件是本仓库进度的
单一来源，一旦过时，下次接手的人（包括几周后的你自己）就会被误导。

### 每次提交后要更新的三处

1. **顶部状态行**：`最近更新` 改成当天日期；测试数量有变就一起改
2. **变更记录**：在表格最上面加一行，写日期、类型、这次实际改了什么
3. **受影响的章节**：
   - 完成了某项 → 从「未完成」移到「已完成」，并勾上 `[x]`
   - 加了新文件 → 补进「文件职责」表
   - 改了架构或数据流 → 更新架构图
   - 接入状态有变（装了库 / 填了凭证 / 实现了取数）→ 更新接入进度表

### 三条约定

- **只有代码提交需要记录**，本文件自身的更新不必记进变更记录（否则会陷入
  「记录一条记录的记录」的无限循环）
- **写实际做了什么，不写打算做什么**。计划属于「未完成」清单，不属于变更记录
- **文档与代码不一致时，改文档**。代码是事实，文档是对事实的描述

### 提交信息格式

```
<类型>: <一句话说明>

<可选的正文：为什么这么改、踩了什么坑>
```

类型用 `feat`（新功能）、`fix`（修 bug）、`refactor`（重构）、`docs`（文档）、
`test`（测试）、`chore`（依赖/配置杂务）。
