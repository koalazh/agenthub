# AgentHub

**Python 3.13+** · **MIT License**

🌐 选择语言 / Select Language:
[简体中文](README.md) | [English](README.en.md)

---

类比 **GitHub 管理代码仓库**，AgentHub 管理 Agent 的配置与演进。

每个 Agent 是一份配置（`soul.md`、`identity.md`、`skills/`、`memory/`），随任务执行自动演进，Git 记录完整演进历史。

## 核心概念

### Agent 即配置

```
GitHub:        repo/ → git log → 代码演进历史
AgentHub:      {agent}/ → git log → 行为演进历史
```

Agent 目录结构：

> **路径说明**：项目源码中的内置技能模板位于 `builtin_skills/` 目录。Agent 初始化时，会复制到运行时的 `skills/builtin/` 目录。

```
{agent_id}/
├── .git/                        # Git 仓库，追踪演进
├── soul.md                       # 身份定义
├── identity.md                   # 角色定义
├── BOOTSTRAP.md                # Recall 指令
├── skills/                       # 技能定义（运行时）
│   ├── builtin/                # 内置技能 (从 builtin_skills/ 复制)
│   ├── universal/              # 通用技能 (evolution 生成)
│   │   └── {skill_name}/
│   │       └── SKILL.md
│   └── projects/               # 项目特定技能
│       └── {project}/
│           └── {skill_name}/
│               └── SKILL.md
├── memory/                       # 经验积累
│   └── projects/
│       ├── universal/
│       │   └── experience.md
│       └── {project}/
│           └── experience.md
└── archives/                    # 任务归档 (不提交 git)
    └── {archive_id}.json
```

### Evolution 即 Commit

```
Git commit:
文件变更 → git add → git commit -m "fix: 修复 bug"

Evolution commit:
任务完成 → 分析 transcript → 判断是否值得记录 →
  → skill: 创建或更新 skills/{name}.md
  → experience: 追加到 memory/projects/*/experience.md
  → git add + commit
```

`evolution()` — 分析单个任务，类似单次 commit
`self_evolution()` — 复盘过往 archives，查漏补缺，确保重要信息不被遗漏

### 演进控制

- **可回退** — 任意历史 commit 可手动回退
- **可追溯** — `git log` 就是 Agent 的成长时间线
- **Append-only** — Evolution 输出只增不减，无覆盖冲突
- **换骨之船** — Agent 不断演进，核心 identity 保持稳定

## 技术栈

AgentHub 基于以下核心技术构建：

- **[deepagents](https://github.com/deepagents/deepagents)** — Agent 基础设施
- **[LangGraph](https://langchain-ai.github.io/langgraph/)** — Agent 工作流编排
- **[LangChain](https://python.langchain.com/)** — LLM 集成和工具生态
- **FastAPI** — HTTP API 服务
- **GitPython** — Git 版本控制集成

## 安装

```bash
git clone https://github.com/your-org/agenthub.git
cd agenthub

uv pip install -e .  # 推荐
pip install .
```

## 快速开始

### 配置

```bash
cp .env.example .env
# 填入 API key
```

### 创建 Agent

```python
from agenthub import init_agent
from agenthub.core.types import InitAgentConfig

agent = await init_agent(InitAgentConfig(
    name="my-agent",
    identity="A helpful coding assistant",
    traits=["helpful", "python-expert"],
))

print(agent.path)  # Agent 目录，Git 已初始化
```

### 任务完成后分析

```python
from agenthub import evolution
from agenthub.core.types import RawTranscriptInput

result = await evolution(agent.id, RawTranscriptInput(
    id="session-001",
    content="用户让我解决 race condition...",
    project_id="project-1",
))

if result.should_record:
    # 已创建 skills/xxx/SKILL.md
    # 已 git commit
    print(f"已记录: {result.skill_name}")
```

### 查看演进历史

```bash
cd ~/.agenthub/{agent_id}
git log --oneline
```

## API 参考

### Python API

| 函数 | 描述 |
|------|------|
| `init_agent(config)` | 创建新 Agent（初始化 Git 仓库） |
| `get_agent(agent_id)` | 获取 Agent 信息 |
| `list_agents()` | 列出所有 Agents |
| `delete_agent(agent_id)` | 删除 Agent |
| `evolution(agent_id, transcript)` | 分析任务，生成 commit |
| `self_evolution(agent_id)` | 复盘 archives，查漏补缺，创建或更新 skills |
| `rollback_agent(request)` | 回滚 Agent 到指定 commit（HEAD~N 或 hash） |
| `get_evolution_history(agent_id, limit, offset)` | 获取 Agent 演进历史（分页） |
| `export_agent_config(agent_id, project_id)` | 导出 Claude Code CLI 配置 |

流式版本：`_stream` 后缀。

### HTTP API

提供 FastAPI HTTP 接口，供外部调用（如 agentcenter）：

```bash
uvicorn agenthub.api.routes:app --host 0.0.0.0 --port 8000
```

| 方法 | 路径 | 描述 |
|------|------|------|
| `POST` | `/agents` | 创建新 Agent |
| `GET` | `/agents` | 列出所有 Agents |
| `GET` | `/agents/{agent_id}` | 获取 Agent 详情 |
| `DELETE` | `/agents/{agent_id}` | 删除 Agent |
| `POST` | `/evolution/start` | 触发 Evolution 分析 |
| `POST` | `/self-evolution/start` | 触发 Self-Evolution |
| `GET` | `/export/claude-code` | 导出 Claude Code CLI 配置 |
| `POST` | `/evolution/rollback` | 回滚到指定版本 |
| `GET` | `/evolution/history` | 获取演进历史 |
| `GET` | `/health` | 健康检查 |

完整文档：`/docs`（Swagger UI）

## 配置

| 环境变量 | 默认值 |
|----------|--------|
| `AGENTHUB_DIR` | `~/.agenthub` |
| `MODEL_NAME` | `anthropic:claude-sonnet-4-6` |

## 开发

```bash
uv pip install -e ".[dev]"
uv run pytest tests/ -v
uv run mypy src/
uv run ruff check src/
uv build
```

## 变更记录

### v0.1.0 (2026-03-27)

- 首次发布
- Agent 生命周期管理
- Git 管理的演进系统
- Evolution 和 Self-Evolution
- 内置 Skills
- Rollback 历史回滚
- Evolution 历史查询
- Claude Code CLI 配置导出
- FastAPI HTTP API

## 许可证

MIT License - 参见 LICENSE 文件
