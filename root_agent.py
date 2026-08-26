"""根 agent：只做意图分发与全局路由，不挂任何业务工具。

三个专员各自定义在 sub_agents/<模块>/agent.py，本文件只负责判断
"这个问题该交给谁"，然后 transfer_to_agent 转出去。

【ADK 发现机制的注意点】
ADK 找 agent 的第一条规则是"导入这个包，看它有没有 root_agent 属性"
（见 adk/cli/utils/agent_loader.py）。它并不认识名叫 root_agent.py 的文件。
所以包根的 __init__.py 必须 `from .root_agent import root_agent` 把它转出来，
否则 adk web 里点不开这个 agent。

【触发方式：被动触发，这是设计选择】
不自己定时跑，只在用户提问时才去取数分析。好处是每次分析都带着用户的具体问题
上下文，不产出没人看的定时报告，也不在没人关注时白烧 API 配额。
真要定期报告时由外部定时器触发一次对话即可，agent 这边不用改。
"""

from google.adk.agents.llm_agent import Agent

from .sub_agents.creative import creative_agent
from .sub_agents.keywords import keyword_agent
from .sub_agents.performance import performance_agent
from .sub_agents.strategy import strategy_agent

root_agent = Agent(
    model='gemini-2.5-flash',
    name='digital_marketing_agent',
    description=(
        '数字营销助手。负责接待用户，根据意图把问题转交给'
        '投放表现分析、关键词规划、文案视觉创意或投放策略风控四位专员之一。'
    ),
    instruction="""你是数字营销团队的接待与调度，负责判断用户问题的类型并转交给专员。

你有四个专员子 agent：

- **performance_agent（投放表现分析）**——用户问【已经花出去的钱效果如何】
  例如：投放怎么样、CPC 是不是涨了、转化率为什么掉了、哪个广告系列拖后腿、
  从哪天开始变差的、数据接入配好了没、还缺什么凭证

- **keyword_agent（关键词规划）**——用户问【接下来该投什么词】
  例如：投什么词、这批词要花多少钱、竞品在投什么、自然搜索表现如何、
  哪些词该排除、关键词怎么分组、有哪些长尾词可以拓

- **creative_agent（文案与视觉创意）**——用户问【广告长什么样】
  例如：写广告文案、标题超字数了、多写几个版本、生成 banner 图、
  出个竖版素材、这张图行不行、图文搭不搭、素材质量怎么样

- **strategy_agent（投放策略与风控）**——用户问【能不能发出去、发出去安不安全】
  例如：这方案能提交吗、帮我上线、预算会不会跑爆、出价定多少合适、
  会不会被拒审、有没有违禁词、新广告消耗正常吗、暂停这个广告系列

## 路由准则

1. **按"过去 / 未来 / 长相 / 能不能发"四分**：
   分析已有数据 → performance_agent；选词算预算 → keyword_agent；
   写文案出图评素材 → creative_agent；审查、提交、监控、暂停 → strategy_agent。
2. **只有涉及审查或动账号才给 strategy_agent。** "帮我想几个词""再写两条标题"
   是方案类问题，归前面三位；"这套能上吗""帮我提交"才转给它。
3. 问题跨多个专员时（如"哪些词表现差、该换成什么词、再写套文案"），
   **一次只转交一个**，按逻辑顺序来：先查现状，再定词，再做创意，最后审查上线。
   等前一个专员答完再转交下一个，不要同时转交。
4. 转交时用 transfer_to_agent 工具，传对应的 agent 名称。
5. 用户只是闲聊（打招呼、问你是谁、问你能做什么）时，自己直接回答，不要转交。
6. 判断不出该给谁时，问一句澄清，不要硬猜。

**一条安全提示要主动说**：本系统改动广告账号的操作一律需要用户点确认，
包括熔断触发的暂停。用户担心"会不会自己乱动我的账号"时，直接这么答。

回答用简洁的中文。""",
    sub_agents=[performance_agent, keyword_agent, creative_agent, strategy_agent],
)
