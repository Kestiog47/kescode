# KesCode

KesCode 是一个以工作区为边界的 Python 编码 Agent CLI。给定一段自然语言任务后，它会在指定工作区内规划任务、搜集资料、读写文件、执行命令，并借助模型和验证命令检查结果。运行过程以事件流形式实时展示规划、工具调用、验证和最终结论。

项目当前版本为 `0.1.0`，使用 LangGraph 编排多 Agent 流程，同时提供单次任务命令行和交互式 Textual TUI。

## 项目内容

KesCode 主要覆盖以下内容：

- 单次任务执行：`kescode "Write a hello.py file" --workspace ./work`
- 交互式多轮会话：`kescode` 或 `kescode tui`
- 意图路由：区分普通聊天和需要访问工作区的任务，不确定时默认进入工作流
- 多 Agent 协作：planner 拆解任务，可委托 searchAgent 检索资料、委托 codeAgent 实现代码
- 验证闭环：verifier 使用只读工具和验证命令检查结果，失败后由 planner 修订并重试
- 上下文管理：监控 token 用量，超限时压缩对话并写入持久摘要
- 可恢复运行：检查点保存状态、文件清单和 Git 快照，支持 `--resume`
- 可观测性：记录完整执行事件并生成 `timeline.md`
- 命令安全：Bash 工具按风险分类，支持人工审批、自动放行和拒绝策略

## 核心功能

### 单次任务与多轮会话

单次任务模式通过 `kescode` 命令运行，把任务交给 LangGraph 工作流处理。TUI 模式在后台线程中运行同一套事件流，并把用户输入保存为多轮会话，后续对话可以感知最近 turn、工作区文件清单和压缩后的历史摘要。

### 意图路由

入口图先由 `intent_router` 判断输入属于 `chat` 还是 `workflow`。普通寒暄、概念问答走轻量 `chat_responder`，不调用工具；涉及文件、命令、搜索或交付物时走完整工作流。LLM 返回的置信度低于阈值或解析失败时，默认进入 `workflow`。

### Planner 与专家 Agent

`planner` 是规划者兼监督者，通过工具调用发布计划，并可把工作分发给两个专家：

- `searchAgent`：只使用 `WebSearchTool`，基于 Tavily 检索事实，产出研究摘要和来源 URL
- `codeAgent`：使用文件读写编辑、grep、Bash、记事本和 Todo 工具，在限定工作区内完成实现

专家 Agent 都采用 ReAct 风格循环：模型调用工具，工具结果回填消息，直到模型给出最终回答或达到最大循环数。

### 验证与重试

`verifier` 只绑定只读工具，会结合模型判定和实际执行的验证命令给出结论。只有模型判定通过且所有验证命令成功，任务才算完成。失败时如果未超过 `max_attempts`，流程回到 planner 修订计划；超过后进入 final 节点。

### 上下文压缩

`context_monitor` 估算消息和分层记忆的 token 用量，超过默认 400000 token 时触发 `context_compressor`。压缩节点把长对话转为摘要，清理原始消息，并把摘要写入 `HISTORY_SUMMARY.md`，同时记录 `compression_events`。

### 分层记忆

每个节点都会组装三层记忆：

- 规则层：工作区边界、路径约定、文件命名约定
- 工作记忆：当前任务、计划、Todo、验收条件、研究笔记、来源、最近结果
- 历史摘要层：`HISTORY_SUMMARY.md`、`NOTEPAD.md`、压缩事件

### 检查点与追踪

- `CheckpointManager` 支持 `light`、`strict`、`off` 三种模式
- 每次运行会记录 checkpoint，若工作区是 Git 仓库则自动创建 Git 快照
- `strict` 模式额外保存完整 state 和事件流
- `TraceRecorder` 把节点访问、工具调用、审批、检查点和交接统计写入 `.kescode/traces/`

## 工作流

```text
用户输入
  -> intent_router
       chat      -> chat_responder
       workflow  -> planner

planner（发布计划、委托 searchAgent / codeAgent）
  -> context_monitor
       token 超限 -> context_compressor -> 按 context_next_node 继续
       -> verifier（模型判定 + 验证命令）
            passed                          -> final
            failed 且 attempts < max        -> planner 修订
            failed 且 attempts >= max       -> final
```

## 项目结构

```text
src/kescode/
├── __main__.py            # python -m kescode 入口
├── cli/
│   ├── app.py             # Typer 命令入口与 Rich 事件渲染
│   └── tui/               # Textual TUI、审批弹窗、Logo
├── core/
│   ├── agent.py           # 事件流、会话流、运行时装配
│   ├── approval.py        # 命令风险分类与审批策略
│   ├── checkpoint.py      # 检查点、Git 快照、恢复
│   ├── paths.py           # 工作区路径解析与越界保护
│   ├── session.py         # 多轮会话存储与摘要
│   ├── state.py           # RuntimeState
│   └── trace.py           # 执行追踪与 timeline
├── agents/
│   ├── code_agent.py      # codeAgent ReAct 循环
│   └── search_agent.py    # searchAgent ReAct 循环
├── graph/
│   ├── memory.py          # 分层记忆
│   ├── nodes.py           # 各节点实现
│   ├── state.py           # LangGraph TypedDict 状态
│   └── workflow.py        # 入口图、主工作流、复杂工作流
├── prompts/
│   ├── stage2.py          # 早期 planner/verifier 提示词
│   ├── stage3.py          # 当前 planner/verifier 提示词
│   └── stage4.py          # 上下文压缩提示词
├── providers/
│   └── openai_provider.py # ChatOpenAI 模型工厂
└── tools/
    ├── bash_tool.py       # Bash 执行与审批
    ├── file_tools.py      # 文件读写编辑
    ├── grep_tool.py       # 正则搜索
    ├── registry.py        # 工具注册
    ├── todo_tools.py      # Todo 工具
    └── web_search_tool.py # Tavily 搜索
```

## 技术栈

| 模块 | 技术 | 说明 |
| --- | --- | --- |
| CLI 入口与输出 | Typer、Rich | `kescode` 命令、面板化事件输出 |
| 交互界面 | Textual | 多轮会话、审批弹窗、事件日志 |
| Agent 编排 | LangGraph、LangChain Core | StateGraph、TypedDict 状态、消息合并 |
| 模型接入 | langchain-openai、python-dotenv | `ChatOpenAI` 工厂，兼容 OpenAI 协议，默认使用 DeepSeek 端点 |
| 工具定义 | Pydantic、LangChain StructuredTool | 参数校验、工具绑定与调用 |
| 命令执行 | subprocess | 工作区内的 Shell 命令与验证命令 |
| Web 搜索 | Tavily Python SDK | `WebSearchTool` |
| 持久化 | JSON、Markdown、Git | session、checkpoint、trace 与 Git 快照 |
| 构建打包 | uv、uv_build、uv.lock | Python 3.14+ 项目依赖与发布 |
| 测试 | pytest | dev 依赖已声明，当前仓库尚未包含 `tests/` |

## 快速开始

需要 Python 3.14+ 和 uv：

```bash
uv sync
uv run kescode --help
```

在项目目录或工作区的 `.env` 中配置：

```dotenv
API_KEY=your_api_key
BASE_URL=https://api.deepseek.com
MODEL=deepseek-v4-flash
TAVILY_API_KEY=your_tavily_key
```

`MODEL`、`BASE_URL`、`API_KEY` 用于模型接入，`TAVILY_API_KEY` 用于 Web 搜索。没有对应环境变量时，代码会使用内置默认值。

## 使用示例

```bash
# 单次任务
kescode "Write a hello.py file" --workspace ./work

# 指定模型与最大重试次数
kescode "Run the test suite and fix failures" --workspace ./app --model deepseek-v4-flash --max-attempts 5

# 从工作区检查点恢复
kescode --resume ./work

# 交互式多轮会话
kescode
kescode tui
```

主要参数：

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `--workspace` / `-w` | 当前目录 | 工作区目录，不存在时自动创建 |
| `--model` | `MODEL` 或 `deepseek-v4-flash` | 模型名称 |
| `--max-attempts` | `3` | planner/verifier 最大尝试次数 |
| `--approval-mode` | `inline` | `inline`、`auto`、`deny` |
| `--checkpoint-mode` | `light` | `light`、`strict`、`off` |
| `--trace-mode` | `on` | `on`、`off` |
| `--resume` | 无 | 从指定工作区检查点恢复 |

TUI 还支持 `--session-workspace`，用于把会话文件保存到与工作区不同的目录。

## 运行时数据

KesCode 会在工作区内生成以下数据：

```text
.kescode/session/session.json        # 多轮会话记录
.kescode/session/SESSION_SUMMARY.md  # 会话摘要
.kescode/checkpoints/                # 检查点、恢复说明、Git 快照信息
.kescode/traces/                     # trace.json、events.jsonl、timeline.md
NOTEPAD.md                           # 可持久化的任务笔记
HISTORY_SUMMARY.md                   # 压缩后的历史摘要
```

`.kescode` 相关运行时数据已加入 `.gitignore`。

## 安全设计

- 文件工具通过 `resolve_within_workspace` 解析路径，拒绝任何逃出工作区的路径
- Bash 工具固定以工作区为当前目录运行
- 安装依赖、网络下载、长驻服务等命令会触发风险分类
- 风险命令在 `inline` 模式下需要人工审批，在 `deny` 模式下直接拒绝
- verifier 只获得只读工具，不能直接修改文件
- 验证命令有默认 120 秒超时，并提供 Windows 平台兼容处理
