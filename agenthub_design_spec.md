# AgentHub MVP 完备设计与开发 Handoff

**文档状态：** 已定稿，可直接进入开发  
**版本：** v1.0  
**日期：** 2026-07-10  
**目标读者：** Coding Agent、后端工程师、Agent Runtime 工程师、前端工程师  
**权威性：** 本文档是 AgentHub MVP 的单一事实源。除非实现中发现与 Hermes 当前源码存在不可兼容的硬阻塞，否则不要重新讨论已经确认的产品与架构决策。

> Handoff 目标：Coding Agent 在没有本次对话上下文的情况下，仅凭本文档即可理解 AgentHub 为什么存在、要做什么、不做什么、如何与 Hermes 集成，以及第一版应该按什么顺序落地。

---

# 1. 执行摘要

AgentHub 是一个以 **Goal/Task 为核心**、以 **Agent 为可选择执行资源**、以 **动态 Harness 为执行程序** 的异构 Agent 控制面。

MVP 的核心链路是：

```text
用户通过 Web、API、Telegram、微信、Slack 等入口提出目标
        |
        v
固定的 Hermes Hub Agent 理解目标并判断 Direct / Harness 模式
        |
        v
Hub Agent 生成 Progressive Logical Harness
        |
        v
AgentHub Runtime 校验并编译为 Physical Harness
        |
        v
复用 Hermes Kanban 作为持久 Task Kernel
        |
        +--> Hermes Profile Worker
        +--> Claude Agent Worker
        +--> Codex Agent Worker
        |
        v
Runtime Gate + 独立语义 Review
        |
        v
输出候选 Commit / Patch / Artifact，默认由用户确认合并
```

AgentHub 不是一个 Persona 商店，也不是 Hermes 的另一套 Team 实现。它的价值在于：

1. 把 Hermes、Claude、Codex 等异构 Runtime 放进同一 Goal、Task、Artifact 与审计体系；
2. 根据当前 Goal 动态生成一次性的执行 Harness，而不是预先写死所有工作流；
3. 由 Runtime 保证状态、权限、预算、并发、恢复和验收等系统不变量；
4. 由 Agent 负责目标已知但路径未知的探索、规划、修正与临时代码生成；
5. 通过上下文隔离、Artifact/Handoff、失败预算和 Token 计量控制 Harness 的经济性。

MVP 只做单机、多进程、软件开发场景，第一条完整闭环是：

> 从自然语言需求或 GitHub Issue 出发，动态组织 Worker，在独立 Worktree 中完成修改，经过确定性检查与独立 Review，最终生成候选 Commit，等待用户确认合并。

---

# 2. Coding Agent 开工指令

实现者应遵循以下顺序：

1. 先阅读本文档的第 3、4、5、8、9、15、18 章；
2. 检出并阅读 Hermes 当前实现，优先关注：
   - `hermes_cli/kanban_db.py`
   - `hermes_cli/kanban.py`
   - `gateway/kanban_watchers.py`
   - `website/docs/user-guide/features/kanban-worker-lanes.md`
   - `gateway/platforms/api_server.py`
   - `website/docs/developer-guide/gateway-internals.md`
3. 不要直接修改 Hermes Kanban 数据库表；通过 Hermes 的 Python API、CLI 或公开接口操作；
4. 不要一开始实现分布式、Marketplace、自演进、复杂 Capability Graph；
5. 先用 FakeWorker 完成端到端闭环，再接 Hermes Profile，再接 Claude/Codex；
6. 每个阶段必须有自动化测试和可运行 Demo；
7. 对 Hermes 源码的真实接口名，以当前检出的版本为准；本文中的接口名若是 AgentHub 自定义接口，则按本文实现。

第一优先级不是 UI 漂亮，也不是 Agent 数量，而是以下闭环真实可恢复、可审计：

```text
Goal -> Harness Version -> Kanban Task -> Worker Run
     -> Artifact -> Gate -> Review -> Candidate Commit
```

---

# 3. 已确认的关键决策

以下决策已经完成讨论，MVP 不再重新选择。

## 3.1 产品与对象模型

1. AgentHub 采用 **Goal-centric** 内核；Agent 是一等资源，不是最终入口。
2. 产品表面可以展示 Agent，但用户默认只需要描述目标，不需要先手工组队。
3. 一等执行对象是 Goal/Task；一等资源对象是 Agent；一等交付对象是 Artifact。
4. 第一版聚焦软件开发任务，底层协议保持通用。

## 3.2 Runtime 与 Agent 边界

1. **Policy by Agent, Mechanism by Runtime.**
2. **Proposal by Agent, Commit by Runtime.**
3. 必须始终正确、可重放、可审计、跨运行一致的事情由 Runtime 实现。
4. 无法经济地提前枚举、需要语义理解和反馈修正的事情由 Agent 决定。
5. Agent 不能直接修改系统事实状态，只能提交结构化 Proposal。

## 3.3 Dynamic Harness

1. AgentHub 不只生成静态 Task DAG，而是生成动态、版本化、可恢复的 Harness Program。
2. Harness 采用 **Typed Harness IR**，不直接执行任意 JavaScript/Python 控制流。
3. 控制流由 IR 描述；临时确定性计算可以在受限 Sandbox 中执行。
4. Harness 使用 Progressive 模式：先生成有界骨架，再根据 Observation 提交 Patch。
5. Agent 生成 Logical Harness；Runtime 编译 Physical Harness。
6. Runtime 只能做语义保持的优化，不得改变 Goal、验收标准和独立性要求。

## 3.4 Hermes 复用

1. MVP 直接复用 Hermes Kanban 作为 Task Kernel，不自研调度器。
2. Hermes Profile、Memory、Session Search、Kanban、Workspace、Dispatcher、Retry、审计能力优先复用。
3. AgentHub 不建设新的 Agent Memory Engine。
4. Hub Agent 固定由 Hermes Profile 担任。
5. Claude、Codex 与其他 Hermes Profile 作为 Worker。

## 3.5 Team 与 Worker

1. Worker 可以在自己的 Runtime 内部调用 subagent。
2. 内部 subagent 默认不是 AgentHub 顶层 Team 成员，也不直接拥有全局 Task。
3. Worker 如需扩张顶层 Team，只能提交 `spawn_task_proposal`。
4. 只有 AgentHub Runtime 可以创建顶层 Task、绑定新 Agent、追加预算和修改 Harness Version。
5. 一个 AgentHub Task 在任一时刻只有一个 accountable owner。

## 3.6 Agent Pool 与 Persona

1. Hermes、Claude、Codex 应作为同等的 Worker Runtime 公民。
2. 一等公民指对 AgentHub 暴露统一外部契约，不要求内部实现相同。
3. 默认创建 Ephemeral Role Overlay，不为每个任务创建永久 Hermes Profile。
4. Durable Agent 是稳定能力载体；Persona 是行为风格；Role 是本次任务责任。
5. MVP 不自动把临时 Role 晋升为永久 Agent。

## 3.7 Registry 与评估

1. Registry 核心是 Capability Contract，而不是 Persona 文案。
2. MVP 只记录能力、约束、可用性和简单历史统计。
3. Capability Evidence 第一阶段只影响路由，不自动修改 Skill、Prompt、Memory 或模型。
4. 不实现复杂 Capability Graph 和在线强化学习。

## 3.8 Workspace 与代码交付

1. Goal 可以共享项目背景，但并行写任务不得共享可变工作目录。
2. 写任务使用独立 Git Worktree 与独立分支。
3. 默认输出候选 Commit/Patch，不直接合并用户分支。
4. 自动合并只允许在用户明确授权的低风险场景开启。

## 3.9 部署、入口与 UI

1. MVP 单机多进程，不做 Kubernetes、Ray 或跨节点调度。
2. Hermes Gateway 继续负责 Telegram、微信、Slack 等多 Channel。
3. Hermes API Server 负责 AgentHub Web 调用 Hub Agent 的对话与 Run 能力。
4. AgentHub 另有一个轻量 Backend/BFF，负责 Goal、Harness、Task、Artifact、Approval 与 UI API。
5. Hermes Session 是对话线程；AgentHub Goal 是可跨 Session、跨 Channel 的持久工作对象。
6. UI 是一个 Hub Agent 对话框加 Goal-centric 看板，不是多个 Agent 的群聊窗口。

---

# 4. 理论与工程原则

## 4.1 Agentic Software：决策逻辑从设计时迁移到运行时

传统软件将人类决策预先编码为 if-else、状态机和算法。Agentic Software 的差异不是不用代码，而是：

- 目标到来后，LLM 在运行时生成决策路径；
- Agent 可以临时生成脚本、查询、测试和转换程序；
- 这些代码是当前任务的工具，可用完即弃；
- Agent 本身的推理循环成为主要决策载体。

AgentHub 不能因此把所有机制交给 LLM。生产级形态必须是：

```text
稳定 Runtime 内核 + 动态 Agent 策略 + 临时执行代码
```

Runtime 固化不变量；Agent 动态决定下一步尝试；临时代码在 Sandbox 中执行。

## 4.2 Claude Code Dynamic Workflow：运行时生成 Harness

Dynamic Workflow 的关键思想不是“更多 subagent”，而是：

- Claude 针对当前任务生成一段编排程序；
- 编排程序持有循环、分支、并行和中间结果；
- Runtime 在后台执行；
- 主会话不再逐轮保存所有中间结果；
- 成功的脚本可以查看、修改、重跑和沉淀。

AgentHub 吸收该思想，但不直接照搬任意 JavaScript：

```text
Claude Dynamic Workflow: JavaScript + Claude subagents
AgentHub: Typed Harness IR + 异构 Agent Runtime + Durable State
```

DAG 只是 Harness 的一种结构。Harness 还必须表达有界循环、Review、等待事件、动态 Patch 与停止条件。

## 4.3 The Harness Effect：Harness 决定 Token 经济性

Harness 不只是胶水。它决定：

- 每次 Run 注入多少上下文；
- Prompt Cache 是否稳定；
- 是否重复购买历史上下文；
- 等待外部事件时是否空耗 Token；
- 失败是否被无限放大；
- 何时委派、压缩、重试和停止。

MVP 应落实的最小机制：

1. Worker 只获得局部 TaskEnvelope，不获得完整 Harness；
2. 大结果通过 Artifact Reference 传递，而不是直接复制进上下文；
3. Handoff 有大小上限和结构化字段；
4. Agent 不轮询等待，Runtime 持久等待与唤醒；
5. 每个 Goal、Task、Attempt 有 Token、成本、耗时和失败统计；
6. Retry 只处理技术性瞬时失败；策略失败交给 Agent Re-plan；
7. Harness 和工具 Schema 在单次 Run 内尽量保持稳定，保护 Prompt Cache。

## 4.4 核心不变量

以下规则应通过代码和数据库约束实现，而不是仅写在 Prompt 中：

1. Task 状态由 Runtime 提交；
2. 每个运行中的 Task 只有一个有效 Claim/Run；
3. 已被新 Run 取代的旧 Worker 不能提交完成；
4. Worker 不能提升自己的权限或预算；
5. 所有循环有上限；
6. 所有并行有上限；
7. 所有写操作位于授权 Workspace；
8. 独立 Reviewer 不能与被审查执行者是同一 Run；
9. 未通过 Mandatory Gate 的 Goal 不能标记为 Completed；
10. 所有状态变更必须生成 Event；
11. 所有 Artifact 必须可追溯到 Goal、Task、Run 和生成者；
12. Harness Patch 不得改写历史事件和已完成 Artifact。

---

# 5. MVP 范围与非目标

## 5.1 MVP 必须完成

1. 固定 Hermes Hub Agent；
2. Web/API 与至少一个 Hermes Gateway Channel 可发起 Goal；
3. Hub Agent 可判断 Direct / Harness；
4. 生成、校验、版本化 Progressive Harness；
5. 物化为 Hermes Kanban Task；
6. 支持 Hermes Profile Worker；
7. 支持 Claude Agent Worker；
8. 支持 Codex Agent Worker；
9. 支持独立 Worktree；
10. 支持 Runtime Gate：测试、Lint、类型检查等；
11. 支持独立语义 Reviewer；
12. 支持 Artifact、Handoff、Event、Usage；
13. 支持暂停、取消、审批、用户补充输入；
14. 支持进程重启后的状态恢复；
15. 最终生成候选 Commit/Patch 和验证报告。

## 5.2 明确不做

1. 不做分布式调度和远程 Worker；
2. 不做 Kubernetes/Ray；
3. 不做 Agent Marketplace；
4. 不做复杂多租户计费；
5. 不做通用研究/投资/内容生成产品化；
6. 不做大规模 Swarm；
7. 不做自动 Agent 自演进；
8. 不做自动修改 Skill、Memory、Prompt；
9. 不做复杂 Capability Graph；
10. 不做跨仓库事务；
11. 不做自动生产部署；
12. 不默认自动合并；
13. 不把所有 Hermes 内部 subagent 映射为顶层 Team；
14. 不重写 Hermes Memory；
15. 不 fork Hermes 核心代码，除非发现无替代方案的阻塞。

---

# 6. 目标用户与首条闭环

## 6.1 目标用户

MVP 面向单个开发者或小型工程团队，用户本机已经安装：

- Hermes Agent；
- 至少一个可用模型 Provider；
- Git；
- 可选的 Claude Agent SDK/CLI；
- 可选的 Codex CLI/App Server。

## 6.2 典型输入

```text
修复这个仓库中登录接口的并发刷新问题。
要求：不能改变公开 API；补充回归测试；最后只给我候选 Commit，不要自动合并。
```

## 6.3 期望执行

```text
1. Hub Agent 识别为 Harness 模式
2. 明确 Goal Contract 和验收条件
3. 生成初始 Harness
4. Hermes Worker 扫描代码与定位影响面
5. Codex 或 Claude 在独立 Worktree 实现
6. Runtime 执行测试、Lint、类型检查
7. 另一个 Agent 独立 Review
8. 如不通过，Harness Patch 增加修复轮次
9. 重新检查
10. 生成候选 Commit 与完整报告
11. 用户批准后才合并
```

## 6.4 最终交付

- 候选 Commit SHA；
- Branch/Worktree 信息；
- 修改文件列表；
- 测试与 Gate 结果；
- Reviewer 结论；
- 未解决风险；
- Token、成本与耗时；
- 用户批准合并的操作入口。

---

# 7. 系统总体架构

```text
                         External Channels
       Telegram / Weixin / Slack / Discord / Web / API
                              |
             +----------------+----------------+
             |                                 |
             v                                 v
      Hermes Gateway                    AgentHub Web
             |                                 |
             |                         AgentHub Backend/BFF
             |                                 |
             +-------------+-------------------+
                           |
                           v
               Hermes agenthub-hub Profile
               Goal clarification + planning
                           |
                 local MCP / native tools
                           |
                           v
+------------------------------------------------------------------+
|                     AgentHub Control Plane                        |
|                                                                  |
| Goal Service       Harness Service       Registry / Resolver      |
| Context Projector  Artifact Service      Approval / Usage         |
| External Lane Supervisor           Workspace Manager              |
+-----------------------------+------------------------------------+
                              |
                              v
                    Hermes Kanban Task Kernel
                  Task / DAG / Claim / Event / Retry
                              |
          +-------------------+-------------------+
          |                   |                   |
          v                   v                   v
 Hermes Profile Lane    Claude Agent Lane     Codex Agent Lane
          |                   |                   |
          +-------------------+-------------------+
                              |
                     Worktree / Scratch
                              |
                  Artifact / Handoff / Commit
```

## 7.1 进程形态

MVP 推荐以下本机进程：

```text
1. Hermes Gateway
2. Hermes API Server（作为 Gateway Adapter）
3. AgentHub Backend / Harness Controller
4. AgentHub External Lane Supervisor
5. AgentHub Web Dev/Prod Server
6. 按需拉起的 Hermes / Claude / Codex Worker Process
```

Backend 与 External Lane Supervisor 第一版可以在同一 Python 进程内以不同 asyncio Task 运行，但代码必须是独立模块，便于以后拆分。

## 7.2 数据存储

使用两类 SQLite：

```text
Hermes Kanban DB
- 任务生命周期
- Task DAG
- Claim / Run / Event
- Worker 日志与工作区信息

AgentHub DB
- Goal
- Harness Version / Run
- Kanban Task 映射
- Agent Registry / Binding
- Artifact / Handoff
- Approval / Usage
- Channel / Session 关联
```

不要把 AgentHub 专属字段强塞进 Hermes 表。通过映射表和 Kanban Comment/Metadata 关联。

---

# 8. Runtime 与 Agent 的职责边界

## 8.1 Runtime 必须负责

| 能力 | Runtime 责任 |
|---|---|
| 状态 | Goal、Harness、Task、Run、Approval 的唯一事实源 |
| 生命周期 | Claim、Heartbeat、Timeout、Cancel、Retry、Recovery |
| 权限 | Workspace、Secret、网络、读写、模型和工具权限 |
| 预算 | Token、成本、时间、并发、Agent 数、Patch 次数 |
| 事务 | 幂等、原子提交、版本检查、旧 Run 防写 |
| Artifact | 持久化、哈希、血缘、访问控制、TTL |
| Gate | 测试、Lint、类型检查、Schema、安全扫描 |
| 调度 | Worker 拉起、回收、崩溃检测、事件唤醒 |
| 审计 | Event、日志、Usage、Harness Diff |
| Context | 按权限投影 TaskEnvelope，限制大小 |
| 编译优化 | 并发、Checkpoint、Artifact Offload、技术性 Retry |

## 8.2 Agent 应负责

| 能力 | Agent 责任 |
|---|---|
| Goal 理解 | 澄清用户真实目标和验收条件 |
| 规划 | 生成初始 Logical Harness |
| 探索 | 在路径未知时选择下一步行动 |
| 拆解 | 提议 Task、Role Demand 和依赖 |
| 语义选择 | 在合格 Agent 候选中判断谁更适合 |
| Re-plan | 根据 Observation 提交 Harness Patch |
| 临时代码 | 生成一次性脚本、查询、测试和转换程序 |
| 语义验证 | 判断论证、架构和实现是否真正满足目标 |
| 升级请求 | 请求更多 Context、权限、预算、角色或人工输入 |

## 8.3 Proposal-Validate-Commit

所有高影响动作都应采用统一协议：

```text
Agent 生成 Typed Proposal
        |
        v
Runtime Schema Validation
        |
        v
State / Permission / Budget / Policy Validation
        |
        v
Atomic Commit + Event
        |
        v
Side Effect Execution
        |
        v
Observation 返回 Agent
```

MVP Proposal 类型：

- `CreateGoalProposal`
- `CreateHarnessProposal`
- `PatchHarnessProposal`
- `SpawnTaskProposal`
- `BindAgentProposal`
- `RequestContextProposal`
- `RequestCapabilityProposal`
- `PublishArtifactProposal`
- `CompleteTaskProposal`
- `RequestMergeProposal`
- `CancelGoalProposal`

---

# 9. 核心领域模型

## 9.1 Goal

Goal 是用户真正想完成的持久对象，跨 Session、跨 Channel 存在。

```yaml
Goal:
  id: goal_01J...
  title: Fix concurrent token refresh
  objective: 修复登录刷新并发问题
  status: draft|planned|running|waiting|review|completed|failed|canceled
  owner_user_id: local-user
  project_root: /path/to/repo
  default_branch: main
  delivery_policy: candidate_commit
  created_at: ...
  updated_at: ...
```

Goal 状态机：

```text
draft -> planned -> running -> review -> completed
                   |    |         |
                   |    +-> waiting
                   +------> failed
任意非终态 ----------------> canceled
```

只有 Completion Controller 可以提交 `completed`。

## 9.2 GoalContract

```yaml
GoalContract:
  objective: string
  acceptance_criteria:
    - string
  constraints:
    - string
  prohibited_actions:
    - string
  required_evidence:
    - string
  required_independence:
    - verifier_must_not_equal_executor
  delivery:
    mode: candidate_commit
    auto_merge: false
```

GoalContract 生成后可以版本化补充，但用户明确约束不能被 Runtime 自动放宽。

## 9.3 HarnessVersion

```yaml
HarnessVersion:
  id: hv_...
  goal_id: goal_...
  version: 1
  parent_version_id: null
  status: proposed|validated|active|superseded|rejected
  logical_ir: {...}
  semantic_hash: sha256
  patch_reason: initial_plan
  generated_by: hermes://agenthub-hub
  created_at: ...
```

每次 Patch 创建新版本，不原地改写旧版本。

## 9.4 HarnessRun

```yaml
HarnessRun:
  id: hr_...
  goal_id: goal_...
  harness_version_id: hv_...
  status: pending|running|waiting|completed|failed|canceled
  current_phase: implement
  started_at: ...
  ended_at: null
  checkpoint: {...}
```

## 9.5 AgentDefinition

```yaml
AgentDefinition:
  id: hermes://implementer
  runtime: hermes|claude|codex
  display_name: Hermes Implementer
  enabled: true
  capabilities:
    - code-analysis
    - code-implementation
  constraints:
    repository_write: true
    max_parallel_runs: 2
  config_ref: agents.yaml#hermes-implementer
  stats:
    completed_runs: 12
    verifier_pass_rate: 0.83
    recent_failure_count: 2
```

## 9.6 AgentBinding

记录某个 Harness Step 最终绑定到哪个 Agent。

```yaml
AgentBinding:
  id: bind_...
  goal_id: goal_...
  step_id: implement
  task_id: task_...
  agent_id: codex://default
  role_overlay:
    role: implementation-owner
    mission: 实现最小安全修复并补充测试
  bound_at: ...
```

## 9.7 TaskMapping

```yaml
TaskMapping:
  goal_id: goal_...
  harness_version_id: hv_...
  step_id: implement
  kanban_board: agenthub-project
  kanban_task_id: task-abc
  expected_run_id: 42
```

## 9.8 Artifact

```yaml
Artifact:
  id: art_...
  goal_id: goal_...
  task_id: task_...
  run_id: run_...
  kind: report|patch|commit|test-log|review|handoff|code
  uri: file:///.../.agenthub/artifacts/...
  sha256: ...
  media_type: text/markdown
  size_bytes: 1234
  created_by_agent: codex://default
  created_at: ...
```

## 9.9 Handoff

```yaml
Handoff:
  id: handoff_...
  from_task_id: task-a
  to_task_id: task-b
  summary: 受限长度的关键结论
  decisions:
    - ...
  claims:
    - ...
  artifact_refs:
    - art_...
  open_questions:
    - ...
  confidence: 0.8
```

## 9.10 Approval

```yaml
Approval:
  id: approval_...
  goal_id: goal_...
  type: capability|budget|merge|harness_launch|human_input
  status: pending|approved|rejected|expired
  request_payload: {...}
  decision_payload: {...}
  created_at: ...
  resolved_at: ...
```

## 9.11 UsageRecord

```yaml
UsageRecord:
  goal_id: goal_...
  task_id: task_...
  run_id: run_...
  agent_id: codex://default
  model: ...
  input_tokens: 0
  cached_input_tokens: 0
  output_tokens: 0
  reasoning_tokens: 0
  cost_usd: 0.0
  wall_time_ms: 0
  outcome: completed|failed|canceled
  failure_type: null
```

---

# 10. Harness IR v1

## 10.1 目标

Harness IR 必须：

- 足够表达软件开发 MVP；
- 可被 LLM 稳定生成；
- 可做静态校验；
- 可估算预算上限；
- 可恢复；
- 不允许任意控制面代码执行。

## 10.2 支持的节点

MVP 只支持以下节点，避免一开始设计完整 DSL：

1. `agent_call`
2. `parallel`
3. `runtime_gate`
4. `review`
5. `loop`
6. `wait_approval`
7. `finalize`

暂不支持通用 `while`、任意表达式、递归函数和动态代码加载。

## 10.3 顶层 Schema

```yaml
api_version: agenthub.io/harness/v1
kind: ProgressiveHarness
metadata:
  name: fix-concurrent-refresh
  goal_id: goal_...

bounds:
  max_parallelism: 3
  max_agent_runs: 8
  max_patch_versions: 5
  max_loop_iterations: 2
  max_wall_time_seconds: 7200
  max_cost_usd: 20

mandatory_gates:
  - tests
  - independent_review

steps:
  - id: inspect
    kind: agent_call
    task: 分析问题、影响面和现有测试
    selector:
      capabilities: [code-analysis]
    workspace:
      mode: read_only
    outputs: [analysis_report]

  - id: implement
    kind: agent_call
    depends_on: [inspect]
    task: 实现修复并补充回归测试
    selector:
      capabilities: [code-implementation]
    role_overlay:
      role: implementation-owner
    workspace:
      mode: write_candidate
    outputs: [candidate_commit, implementation_report]

  - id: checks
    kind: runtime_gate
    depends_on: [implement]
    checks:
      - command: pytest -q
      - command: ruff check .

  - id: review
    kind: review
    depends_on: [checks]
    selector:
      capabilities: [code-review]
      exclude_agents_from: [implement]
    inputs: [candidate_commit, checks]
    outputs: [review_report]

  - id: repair
    kind: loop
    depends_on: [review]
    max_iterations: 2
    continue_when: review_requires_changes
    body:
      agent_call:
        task: 根据 Review 修复问题
        selector:
          prefer_binding_from: implement
      runtime_gate:
        checks: inherit_from:checks
      review:
        inherit_from: review

  - id: finalize
    kind: finalize
    depends_on: [repair]
    delivery: candidate_commit
```

## 10.4 Harness 编译

编译流程：

```text
Logical IR
  -> JSON Schema Validation
  -> Semantic Contract Preservation Check
  -> Bounds / Permission / Independence Check
  -> Agent Candidate Resolution
  -> Workspace Planning
  -> Kanban Task Materialization
  -> Physical Plan + Compilation Record
```

## 10.5 允许的 Physical Optimization

Runtime 可以：

- 降低并发；
- 插入 Checkpoint；
- 将大输出转为 Artifact Reference；
- 将轮询改为事件等待；
- 在能力等价时选择更经济的 Agent；
- 添加瞬时故障 Retry；
- 复用已完成且输入哈希相同的结果；
- 为 Worker 生成局部 TaskEnvelope。

Runtime 不可以：

- 删除 Mandatory Gate；
- 放宽 Acceptance Criteria；
- 把独立 Review 改为自检；
- 改变用户指定的 Agent；
- 偷偷减少证据要求；
- 扩大权限；
- 修改 Goal 语义。

## 10.6 Harness Patch

任何 Agent 都可以提交 Patch Proposal，但只有 Controller 可以提交新版本。

```yaml
PatchHarnessProposal:
  goal_id: goal_...
  base_version: 2
  reason: 当前实现未覆盖进程级并发场景
  operations:
    - op: add_step
      after: inspect
      step:
        id: reproduce
        kind: agent_call
        task: 创建可重复的并发测试
```

Patch 校验失败时返回具体原因，不修改当前 Version。

---

# 11. Hub Agent 设计

## 11.1 固定 Profile

MVP 创建一个持久 Hermes Profile：

```text
profile: agenthub-hub
职责: 用户对话、Goal 澄清、Direct/Harness 判断、Logical Harness 生成、进度解释
```

Hub Profile 拥有：

- Hermes 原生 Memory；
- 用户偏好与 Session Search；
- AgentHub Orchestrator Skill；
- AgentHub Control MCP 工具；
- 只读项目探索工具；
- 不直接拥有全局状态数据库写权限。

## 11.2 Direct / Harness 路由

Hub 输出结构化决策：

```yaml
execution_decision:
  mode: direct|harness
  reasons:
    - multi_file_change
    - independent_review_required
```

Direct 适用：

- 简单解释；
- 小型只读分析；
- 不需要等待；
- 不需要多个 Worker；
- 不需要持久 Artifact；
- 失败影响低。

Harness 强制适用：

- 代码写入；
- 跨多个文件；
- 需要测试或 Review；
- 长任务；
- 需要等待外部事件；
- 需要多个 Agent；
- 需要独立 Worktree；
- 需要用户审批。

Runtime 可通过硬规则拒绝不合规的 Direct 请求。

## 11.3 Hub Agent 工具

建议以本地 MCP Server 暴露；也可实现为 Hermes Native Plugin，但外部契约必须保持一致。

```text
agenthub_create_goal
agenthub_submit_harness
agenthub_patch_harness
agenthub_get_goal
agenthub_list_goals
agenthub_request_context
agenthub_approve
agenthub_cancel_goal
agenthub_request_merge
```

`agenthub_create_goal` 输入：

```yaml
objective:
acceptance_criteria: []
constraints: []
project_root:
delivery_mode: candidate_commit
origin_session:
origin_channel:
```

`agenthub_submit_harness` 输入必须是 Harness IR v1，Runtime 不接受自然语言 Harness。

## 11.4 Hub Agent 不负责

- 直接更新 Task 状态；
- 直接写 AgentHub DB；
- 直接 Claim Kanban Task；
- 修改 Worker Run 结果；
- 绕过 Approval；
- 无限制拉起 Agent；
- 默认执行复杂实现任务。

---

# 12. Channel、API Server 与 Goal

## 12.1 三个不同层级

```text
Channel: 用户从哪里进来
Session: 当前对话线程
Goal: 系统持续完成的工作对象
```

一个 Goal 可以绑定多个 Session；一个 Session 可以创建多个 Goal。

## 12.2 Hermes Gateway

Telegram、Discord、Slack、飞书、钉钉、企业微信、个人微信等继续使用 Hermes Gateway。所有入口路由到 `agenthub-hub` Profile。

Gateway 只负责：

- 平台消息适配；
- 授权；
- Session 路由；
- 中断/审批指令；
- 回复与结果投递。

Gateway 不理解 Harness 内部状态。

## 12.3 Hermes API Server

AgentHub Web 的聊天请求通过 Hermes API Server 访问 Hub Agent。推荐使用：

- 持久 Session API；
- `/v1/runs` 异步 Run；
- SSE Run Events；
- Approval/Stop；
- Health Check。

AgentHub Backend 不重新实现 Hermes Agent Loop。

## 12.4 AgentHub Backend/BFF

Backend 统一向前端暴露：

```text
POST   /api/chat
GET    /api/goals
POST   /api/goals
GET    /api/goals/{goal_id}
GET    /api/goals/{goal_id}/events
POST   /api/goals/{goal_id}/cancel
POST   /api/goals/{goal_id}/approvals/{approval_id}
POST   /api/goals/{goal_id}/merge
GET    /api/agents
GET    /api/artifacts/{artifact_id}
```

`/api/chat` 代理 Hermes API Server，但在响应元数据中附带新创建或关联的 `goal_id`。

## 12.5 Session-Goal 关联

```yaml
GoalSessionLink:
  goal_id: goal_...
  hermes_profile: agenthub-hub
  session_key: agent:main:telegram:private:123
  channel: telegram
  external_user_id: 123
  relation: origin|attached|delivery
```

MVP 单用户环境可以暂不做复杂身份合并，但数据模型保留关联。

---

# 13. Hermes Kanban 集成

## 13.1 原则

Hermes Kanban 是 MVP 的 canonical Task Lifecycle 与审计事实源。

复用：

- Board；
- Task 与依赖；
- ready/running/blocked/done 等状态；
- Claim、Run、Heartbeat；
- Crash、Timeout、Retry、Circuit Breaker；
- Workspace；
- Comment、Event、日志；
- Gateway 内嵌 Dispatcher。

## 13.2 Board 策略

推荐每个项目/仓库一个 Board：

```text
board slug: agenthub-<repo-name>-<short-hash>
```

不要每个 Goal 创建一个 Board。Goal 通过 Task Metadata 和 AgentHub 映射表区分。

## 13.3 Task Materialization

每个可执行 Harness Step 映射为 Kanban Task。

Task Body 应包含一个稳定、可机读的 Header：

```yaml
agenthub:
  goal_id: goal_...
  harness_version: 2
  step_id: implement
  task_contract_version: 1
```

Task 正文随后包含人类可读 Objective、Acceptance Criteria、Inputs 和 Output Contract。

## 13.4 Assignee 命名

```text
Hermes Profile: implementer
Claude Lane:   claude:default
Codex Lane:    codex:default
```

Hermes 原生 Dispatcher 处理 Profile Assignee。AgentHub External Lane Supervisor 处理 `claude:` 与 `codex:` 前缀。

## 13.5 不修改 Hermes Dispatcher 的第一版方案

Hermes 对无法解析的非 Profile Assignee 会留在 ready 并记录 non-spawnable。AgentHub External Lane Supervisor 独立扫描自己负责的 Assignee，使用 Hermes Kanban 的公开 Claim/Run API 原子 Claim，随后拉起外部 Worker。

这样：

- 不需要 fork Hermes；
- 不与 Hermes Profile Lane 冲突；
- External Lane 可以独立升级；
- 未来可以迁移到 Hermes 正式 Plugin `spawn_fn` 机制。

实现时必须检查当前 Hermes 源码，复用其 `claim_task`、heartbeat、complete/block 或等价 API；禁止直接拼 SQL 更新状态。

## 13.6 状态映射

| Harness Step | Kanban |
|---|---|
| pending | todo |
| runnable | ready |
| executing | running |
| waiting dependency | todo + parent links |
| waiting input/capability | blocked |
| waiting review | blocked，reason 前缀 `review-required:` |
| succeeded | done |
| canceled | archived 或 AgentHub 终态映射 |
| failed | exhausted/gave_up 后映射为 Harness failed |

## 13.7 Reconciliation

Harness Controller 周期性执行无 Token 的数据库 Reconcile：

1. 读取 active Harness Run；
2. 查询映射的 Kanban Task；
3. 处理新 Event；
4. 更新 StepExecution；
5. 激活后继 Step；
6. 触发 Gate、Review 或 Patch 请求；
7. 写入 AgentHub Event。

轮询数据库是 Runtime 行为，不会消耗模型 Token。后续可改为 Hook/Event Push。

---

# 14. Worker Runtime Contract

## 14.1 统一接口

所有 Lane 实现同一 Python Protocol：

```python
class WorkerAdapter(Protocol):
    async def describe(self) -> AgentRuntimeDescriptor: ...
    async def start(self, request: WorkerStartRequest) -> WorkerHandle: ...
    async def stream_events(self, handle: WorkerHandle) -> AsyncIterator[WorkerEvent]: ...
    async def send_input(self, handle: WorkerHandle, payload: dict) -> None: ...
    async def cancel(self, handle: WorkerHandle) -> None: ...
    async def collect_result(self, handle: WorkerHandle) -> WorkerResult: ...
```

## 14.2 统一事件

```text
accepted
started
progress
tool_started
tool_completed
artifact_created
input_required
approval_required
heartbeat
completed
failed
canceled
```

Adapter 可以无法提供所有细粒度事件，但必须提供 `started`、`heartbeat/progress`、`completed/failed/canceled`。

## 14.3 WorkerStartRequest

```yaml
WorkerStartRequest:
  goal_id:
  task_id:
  kanban_task_id:
  expected_run_id:
  agent_binding:
  task_envelope:
  workspace_path:
  timeout_seconds:
  environment:
  artifact_output_dir:
```

## 14.4 WorkerResult

```yaml
WorkerResult:
  status: completed|blocked|failed|canceled
  summary:
  artifacts: []
  changed_files: []
  commit_sha: null
  tests_run: []
  usage: {}
  session_ref: null
  failure:
    type: null
    message: null
```

## 14.5 生命周期终止

External Lane Supervisor 负责将 WorkerResult 转换为 Kanban 生命周期调用：

- completed -> `kanban_complete` 等价 API；
- blocked -> `kanban_block`；
- failed -> 让 Run 进入失败/重试路径；
- canceled -> 终止进程并提交取消事件。

外部 Agent 本身不直接写 Kanban DB。

---

# 15. 三类 Worker Lane

## 15.1 Hermes Profile Lane

直接复用 Hermes Dispatcher：

```text
assignee = Hermes profile name
workspace = Kanban pinned workspace
spawn = hermes -p <profile> chat -q <prompt>
termination = kanban_complete / kanban_block
```

创建最少两个 Durable Profile：

```text
agenthub-hub       - 用户入口与规划
hermes-reviewer    - 独立架构/代码 Review
```

可选创建：

```text
hermes-researcher
hermes-implementer
```

不要为每个 Role 创建 Profile。Role Overlay 注入当前 Task Prompt。

## 15.2 Claude Agent Lane

优先使用 Claude Agent SDK，而不是抓取终端文本。

职责：

- 在指定 Worktree 中运行；
- 使用 TaskEnvelope；
- 使用 Runtime 提供的工具与权限配置；
- 将 SDK Stream 转换为 WorkerEvent；
- 记录 Session ID 以支持恢复；
- 最终由 Supervisor 提交 Kanban 状态。

第一版配置：

```yaml
id: claude://default
runtime: claude
capabilities: [code-analysis, code-implementation, code-review]
max_parallel_runs: 1
```

如果 SDK 接入被环境阻塞，可增加 CLI fallback，但必须隐藏在同一 Adapter 后面。

## 15.3 Codex Agent Lane

优先使用 Codex App Server 或稳定的 SDK 接口，实现：

- Thread/Session；
- 流式事件；
- Approval；
- Cancel；
- Sandbox/Workspace；
- 结果与 Usage 采集。

`openai/codex-plugin-cc` 的价值在于证明了 Codex 可以作为完整 Runtime 被委派、后台运行、查询状态、取消和恢复，而不是一次普通模型调用。AgentHub 不采用 Claude 主、Codex 从的固定结构，而是由统一 Task Kernel 调度。

第一版配置：

```yaml
id: codex://default
runtime: codex
capabilities: [code-implementation, code-review, debugging]
max_parallel_runs: 1
```

## 15.4 内部 Subagent 边界

Claude/Codex/Hermes Worker 可自行使用内部 subagent，但：

- AgentHub 只记录顶层 Worker Run；
- 内部 subagent 成本尽可能聚合到顶层 Usage；
- 内部 subagent 无权修改全局 Harness；
- 如需长期跨 Agent 协作，Worker 提交 `SpawnTaskProposal`。

---

# 16. Agent Registry 与 Resolver

## 16.1 存储形态

MVP 使用：

```text
config/agents.yaml       静态能力与 Runtime 配置
agenthub.db              动态统计与当前可用性
```

## 16.2 agents.yaml 示例

```yaml
agents:
  - id: hermes://reviewer
    runtime: hermes
    profile: hermes-reviewer
    enabled: true
    capabilities: [code-review, architecture-review]
    constraints:
      repository_write: false
      max_parallel_runs: 2

  - id: claude://default
    runtime: claude
    enabled: true
    capabilities: [code-analysis, code-implementation, code-review]
    constraints:
      repository_write: true
      max_parallel_runs: 1

  - id: codex://default
    runtime: codex
    enabled: true
    capabilities: [code-implementation, debugging, code-review]
    constraints:
      repository_write: true
      max_parallel_runs: 1
```

## 16.3 路由流程

保持简单：

```text
1. Runtime 硬过滤
   - enabled
   - capabilities
   - 权限
   - workspace
   - 容量
   - 用户指定约束

2. 简单评分
   - capability 完整匹配
   - 用户/项目偏好
   - recent verifier pass rate
   - 当前可用性
   - 预计成本

3. 选择最高分
   - 如 Harness 明确指定 Agent，则只验证是否合法
   - 独立 Reviewer 必须排除 Executor
```

MVP 不需要单独常驻 Resolver Agent。Hub Agent 可以在生成 Harness 时指定偏好；Runtime 完成资格过滤和最终 Binding。

## 16.4 简单统计

任务完成后记录：

- completed_runs；
- verifier_pass_rate；
- average_cost；
- average_latency；
- recent_failure_count；
- last_used_at。

统计只影响路由，不自动改 Agent。

---

# 17. Persona、Role Overlay 与 Memory

## 17.1 三层概念

```text
Capability: Agent 稳定能做什么
Persona:    本次采用什么行为风格
Role:       当前 Team 中负责什么
```

## 17.2 Role Overlay

```yaml
role_overlay:
  role: security-skeptic
  mission: 从越权、泄漏和回滚风险审查实现
  instructions:
    - 主动寻找反例
    - 不替实现者重写主要代码
  permissions:
    repository: read_only
  output_contract: SecurityReviewV1
```

Role Overlay 只在当前 Run 生效，不创建长期 Profile。

## 17.3 Memory

直接复用 Hermes：

- Hermes Profile `MEMORY.md`；
- `USER.md`；
- Session Search；
- 可选外部 Memory Provider。

AgentHub 不建设 Memory Engine。

MVP 规则：

1. Hermes Profile 使用自己的原生 Memory；
2. Claude/Codex 只获得任务级 Context，不写长期 AgentHub Memory；
3. Goal 状态属于 Runtime，不属于 Memory；
4. 大结果属于 Artifact；
5. Team 临时事实属于 Handoff/Comment；
6. 未来如需要跨 Runtime 长期记忆，再增加 Memory Adapter，不在 MVP 实现。

---

# 18. Context Projector、TaskEnvelope 与 Handoff

## 18.1 Worker 不看完整 Harness

Worker 默认只看到：

- 当前 Task；
- Goal 的必要摘要；
- 直接依赖 Handoff；
- 授权 Artifact；
- 当前权限和预算；
- 输出契约；
- 允许的升级 Proposal。

这样控制 Token、减少锚定、保护 Prompt Cache 和最小权限。

## 18.2 TaskEnvelope

```yaml
TaskEnvelope:
  identity:
    goal_id:
    task_id:
    run_id:
    role:

  objective:
    statement:

  goal_context:
    summary:
    relevance:

  acceptance_criteria: []

  inputs:
    handoffs: []
    artifacts: []

  constraints:
    permissions:
      repository: read_only|write_candidate
      network: deny|allow|allowlist
    token_budget:
    deadline:
    prohibited_actions: []

  output_contract:
    kind:
    schema:
    artifact_dir:

  escalation:
    allowed_proposals:
      - request_context
      - request_capability
      - spawn_task
      - report_blocker
```

## 18.3 Context 请求

Worker 需要额外信息时：

```yaml
RequestContextProposal:
  requested_refs: [artifact://security-model]
  reason: 需要验证跨租户边界
```

Runtime 决定：

- 是否有权限；
- 返回全文、摘要还是拒绝；
- 是否破坏 Reviewer 独立性；
- 是否超出 Context Budget。

## 18.4 Handoff Contract

Handoff 默认上限建议 8 KB：

```yaml
summary:
decisions: []
claims: []
artifact_refs: []
evidence_refs: []
open_questions: []
confidence:
```

完整探索放 Artifact，Handoff 只负责下游可执行的精简信息。

## 18.5 Prompt Cache 纪律

每个 Worker Run 将 Prompt 分为：

```text
Stable Prefix
- 固定 Runtime Contract
- 固定 Role/Tool Schema
- 固定安全规则

Volatile Tail
- 当前 TaskEnvelope
- 最新 Observation
- 当前剩余预算
```

不要每次全局 Harness Patch 都重写所有 Worker 的 Stable Prefix。

---

# 19. Workspace 与 Git 策略

## 19.1 目录结构

```text
<repo>/.agenthub/
  worktrees/
    <goal_id>/
      <task_id>/
  artifacts/
    <goal_id>/
      <task_id>/
  logs/
    <goal_id>/
  state/
```

实际 Worktree 可由 Hermes Kanban Workspace Root 管理；AgentHub 只记录路径与映射。

## 19.2 Workspace Mode

```text
read_only
- 分析任务
- 尽量使用项目目录只读视图

write_candidate
- 独立 Worktree
- 独立分支
- Worker 可修改并 Commit

auto_merge
- MVP 默认关闭
- 用户显式授权后才能启用
```

## 19.3 分支命名

```text
agenthub/<goal-short-id>/<task-short-id>
```

## 19.4 Candidate Commit

实现 Worker 完成时必须提供：

- commit SHA；
- branch name；
- changed files；
- tests run；
- implementation summary；
- known risks。

Runtime Gate 与 Review 通过后，Goal 进入 `review`，等待 merge approval。

## 19.5 合并

默认流程：

```text
用户点击 Approve Merge
  -> Runtime 确认 Goal/Commit/Gate 版本未变化
  -> 检查目标分支 HEAD
  -> 执行 fast-forward / merge / cherry-pick 策略
  -> 记录 Merge Event
  -> 清理 Worktree（可延迟）
```

如果目标分支已变化，拒绝自动合并并创建 Rebase/Conflict Task。

---

# 20. Verification 与 Completion Controller

## 20.1 两类验证

### Runtime Gate

确定性检查：

- 测试；
- Lint；
- 类型检查；
- Build；
- Schema；
- 禁止文件；
- Artifact 完整性；
- Commit 是否存在；
- 工作区是否干净。

### Semantic Reviewer Agent

开放式检查：

- 实现是否满足 Goal；
- 是否遗漏边界条件；
- 是否有隐藏风险；
- 测试是否覆盖关键失败路径；
- 是否改变公开 API；
- 结论是否有证据。

## 20.2 独立性

Reviewer 的 Agent ID 或 Run ID 不得与 Executor 相同。MVP 至少检查：

```text
review_binding.agent_id != implementation_binding.agent_id
```

如果只配置一个 Agent，可使用不同 Runtime/Profile；否则 Goal 需要人工 Review，不能伪装为独立 Agent Review。

## 20.3 Review 结果

```yaml
ReviewResult:
  decision: pass|changes_required|blocked
  findings:
    - severity: critical|major|minor
      summary:
      evidence:
  confidence:
```

## 20.4 Completion Policy

```yaml
completion_policy:
  required:
    - all_mandatory_steps_succeeded
    - runtime_gates_passed
    - semantic_review_passed
    - candidate_commit_exists
  optional:
    - merge_approved
```

`candidate_commit` 交付模式下，Goal 可以在“候选产物已完成”时标记 completed，但 Merge 是独立用户动作。UI 应清楚区分“Goal completed”和“Commit merged”。

---

# 21. Failure、Retry、Waiting 与恢复

## 21.1 失败类型

```text
TRANSIENT_RATE_LIMIT
PROVIDER_UNAVAILABLE
NETWORK_ERROR
STALL
TIMEOUT
MALFORMED_RESPONSE
TOOL_VALIDATION_ERROR
PERMISSION_DENIED
CONTEXT_OVERFLOW
SEMANTIC_DEAD_END
TEST_FAILURE
REVIEW_REJECTED
PERMANENT_FAILURE
CANCELED
```

## 21.2 Retry 与 Re-plan

Runtime Retry：

- Rate Limit；
- 短暂网络故障；
- Provider 暂时不可用；
- 进程异常退出且仍在 Attempt Budget 内。

Agent Re-plan：

- 测试持续失败；
- 原方案无效；
- 工具不适用；
- 证据不足；
- Reviewer 要求改变实现。

不要把语义失败做成无限技术 Retry。

## 21.3 Failure Budget

```yaml
failure_budget:
  max_attempts_per_task: 3
  max_failed_tokens: 100000
  max_harness_patches: 5
  max_review_repair_rounds: 2
```

## 21.4 Waiting

Waiting 是持久状态，不是 Agent 循环：

- 等用户 Approval；
- 等外部 Worker；
- 等 CI；
- 等依赖 Task；
- 等 Capability。

Controller 保存 Continuation，事件到达后恢复。Agent 不得每隔几秒询问“完成了吗”。

## 21.5 恢复

Backend 重启后：

1. 加载 active HarnessRun；
2. 与 Kanban 当前 Task/Run 对账；
3. 检测已结束但未处理的 Event；
4. 重新建立 External Worker 监控；
5. 对无法恢复的本地进程交给 Kanban Crash/Retry；
6. 从 Checkpoint 继续，不重新购买所有历史上下文。

所有 Controller 操作使用幂等键：

```text
<goal_id>:<harness_version>:<step_id>:<attempt>
```

---

# 22. Artifact、日志与审计

## 22.1 Artifact Store

MVP 使用本地文件系统，AgentHub DB 保存元数据。

```text
.agenthub/artifacts/<goal_id>/<task_id>/<artifact_id>
```

必须写 SHA256 和大小。禁止只把重要结果留在 Worker stdout。

## 22.2 Kanban Comment

需要给后续 Worker 或人类 Reviewer 看的结构化摘要，也写入 Kanban Comment，包含：

- Artifact refs；
- changed files；
- tests；
- decisions；
- review-required 信息。

## 22.3 AgentHub Event

事件示例：

```text
goal.created
harness.proposed
harness.validated
harness.activated
step.materialized
agent.bound
worker.started
artifact.published
gate.completed
review.completed
approval.requested
harness.patched
goal.completed
merge.completed
```

事件必须包含 `goal_id`、时间、actor、payload 和 correlation ID。

## 22.4 日志

- Worker stdout/stderr 复用 Hermes Kanban Logs 或 Adapter Log；
- Backend 使用结构化 JSON Log；
- 不在日志中写 Secret；
- UI 默认只展示摘要，可下载完整日志。

---

# 23. Usage 与 Harness 经济性

## 23.1 必须记录

- Input Tokens；
- Cached Input Tokens；
- Output Tokens；
- Reasoning Tokens（Provider 可用时）；
- 成本；
- Wall Time；
- Attempt；
- Failure Tokens；
- Agent/Model/Runtime；
- Harness Version。

## 23.2 核心指标

```text
Goal Completion Rate
Tokens per Completed Goal
Cost per Completed Goal
Quality / Dollar
Cache Hit Ratio
Failure Spend Ratio
Review Rework Rate
Median Wall Time
Waiting Tokens（目标为 0）
```

MVP UI 只展示：总 Token、成本、耗时、Attempt、当前预算百分比。更复杂报表以后再做。

## 23.3 成本保护

- Harness 执行前估算上限；
- 超出用户配置阈值时请求 Approval；
- 接近上限时禁止自动扩张 Team；
- Budget 不足不能偷偷降低验收标准；
- 可提交 Budget Increase Proposal。

---

# 24. Backend API 详细建议

## 24.1 创建 Goal

```http
POST /api/goals
```

```json
{
  "objective": "Fix concurrent token refresh",
  "project_root": "/repo",
  "acceptance_criteria": ["tests pass"],
  "delivery_mode": "candidate_commit",
  "origin": {
    "channel": "web",
    "session_key": "..."
  }
}
```

响应：

```json
{
  "goal_id": "goal_...",
  "status": "draft"
}
```

## 24.2 提交 Harness

```http
POST /api/goals/{goal_id}/harness
```

输入 Logical IR。响应包含：

- version；
- validation results；
- cost estimate；
- required approvals；
- compiled summary。

## 24.3 Goal Detail

```http
GET /api/goals/{goal_id}
```

应返回：

- Goal Contract；
- 当前 Harness Version；
- Step/Task 状态；
- Agent Binding；
- Artifacts；
- Approvals；
- Usage Summary；
- Candidate Commit。

## 24.4 SSE Events

```http
GET /api/goals/{goal_id}/events
Accept: text/event-stream
```

支持 `Last-Event-ID`，断线后续传。

## 24.5 Approval

```http
POST /api/goals/{goal_id}/approvals/{approval_id}
```

```json
{
  "decision": "approve",
  "comment": "Proceed"
}
```

## 24.6 Merge

```http
POST /api/goals/{goal_id}/merge
```

必须再次校验 Commit、Gate、Review 与目标分支 HEAD。

---

# 25. 前端 MVP

## 25.1 页面

1. Chat + Goal 列表；
2. Goal Detail；
3. Approval Drawer；
4. Artifact/Commit Detail；
5. Agent Registry 只读页。

## 25.2 Goal Detail 布局

```text
+----------------------------------------------------+
| Goal 标题 | 状态 | Harness v3 | 成本/预算 | Cancel |
+----------------------------------------------------+
| Chat / Hub Agent                                   |
+----------------------------+-----------------------+
| Task Board                 | Detail                |
| Todo                       | 当前 Task             |
| Running                    | Agent / Workspace     |
| Review                     | Events / Logs         |
| Done                       | Artifact / Diff       |
+----------------------------+-----------------------+
| Candidate Commit / Tests / Reviewer / Merge        |
+----------------------------------------------------+
```

## 25.3 用户操作

允许：

- 创建 Goal；
- 补充约束；
- 请求 Re-plan；
- Pause/Cancel；
- Approval；
- 查看 Harness Diff；
- 查看 Artifact；
- 批准 Merge。

不允许直接：

- 把 Task 改成 done；
- 改写历史 Event；
- 绕过 Gate；
- 直接编辑正在运行的 Physical Harness；
- 伪造 Worker Result。

用户自然语言修改目标时，由 Hub Agent 生成 Patch Proposal。

---

# 26. 推荐技术栈与仓库结构

## 26.1 技术栈

Backend：

- Python 3.12；
- FastAPI；
- Pydantic v2；
- SQLAlchemy 2 + Alembic；
- SQLite WAL；
- httpx；
- anyio/asyncio；
- 本地 MCP Server SDK；
- pytest。

Frontend：

- React；
- TypeScript；
- Vite；
- TanStack Query；
- 简单 CSS/UI Kit，不做重型设计系统。

## 26.2 仓库结构

```text
agenthub/
  pyproject.toml
  README.md
  .env.example

  config/
    agents.yaml
    agenthub.yaml

  schemas/
    harness-v1.schema.json
    task-envelope-v1.schema.json
    handoff-v1.schema.json

  profiles/
    agenthub-hub/
      SOUL.md
      AGENTS.md
      skills/
        agenthub-orchestrator/
          SKILL.md
    hermes-reviewer/
      SOUL.md
      AGENTS.md

  src/agenthub/
    main.py
    settings.py

    api/
      app.py
      chat.py
      goals.py
      approvals.py
      artifacts.py
      agents.py
      events.py

    db/
      base.py
      models.py
      repositories.py
      migrations/

    domain/
      goal.py
      harness.py
      agent.py
      artifact.py
      approval.py
      events.py
      usage.py

    harness/
      schema.py
      validator.py
      compiler.py
      controller.py
      patcher.py
      reconciler.py
      completion.py

    hermes/
      api_client.py
      kanban_adapter.py
      gateway_delivery.py
      session_linker.py

    registry/
      loader.py
      resolver.py
      stats.py

    workers/
      base.py
      supervisor.py
      hermes_lane.py
      claude_adapter.py
      codex_adapter.py
      fake_adapter.py

    context/
      projector.py
      task_envelope.py
      handoff.py

    workspace/
      manager.py
      git.py

    artifacts/
      store.py
      hashing.py

    gates/
      runner.py
      commands.py
      result.py

    mcp/
      server.py
      tools.py

    observability/
      logging.py
      usage.py

  web/
    package.json
    src/
      api/
      pages/
      components/
      hooks/

  tests/
    unit/
    integration/
    e2e/
    fixtures/
```

## 26.3 配置

```yaml
agenthub:
  host: 127.0.0.1
  port: 8787
  data_dir: ~/.agenthub
  database_url: sqlite:///~/.agenthub/agenthub.db

hermes:
  home: ~/.hermes
  hub_profile: agenthub-hub
  api_base_url: http://127.0.0.1:8642
  kanban_board_prefix: agenthub

execution:
  max_parallelism: 3
  reconcile_interval_seconds: 2
  default_task_timeout_seconds: 1800
  candidate_only: true

workers:
  claude:
    enabled: true
  codex:
    enabled: true
```

---

# 27. 数据库表建议

使用 AgentHub 自有 SQLite，不修改 Hermes Schema。

```text
goals
- id PK
- title
- objective
- status
- project_root
- default_branch
- delivery_mode
- contract_json
- created_at
- updated_at

harness_versions
- id PK
- goal_id FK
- version UNIQUE(goal_id, version)
- parent_version_id
- status
- logical_ir_json
- semantic_hash
- patch_reason
- generated_by
- created_at

harness_runs
- id PK
- goal_id FK
- harness_version_id FK
- status
- current_phase
- checkpoint_json
- started_at
- ended_at

step_executions
- id PK
- harness_run_id FK
- step_id
- status
- attempt
- kanban_task_id
- agent_binding_id
- started_at
- ended_at
- result_json
- UNIQUE(harness_run_id, step_id, attempt)

agent_definitions
- id PK
- runtime
- display_name
- enabled
- capabilities_json
- constraints_json
- config_json

agent_stats
- agent_id PK/FK
- completed_runs
- verifier_pass_count
- verifier_total_count
- average_cost
- average_latency_ms
- recent_failure_count
- last_used_at

agent_bindings
- id PK
- goal_id
- harness_version_id
- step_id
- agent_id
- role_overlay_json
- created_at

artifacts
- id PK
- goal_id
- task_id
- run_id
- kind
- uri
- sha256
- media_type
- size_bytes
- metadata_json
- created_at

handoffs
- id PK
- goal_id
- from_task_id
- to_task_id
- payload_json
- created_at

approvals
- id PK
- goal_id
- type
- status
- request_json
- decision_json
- created_at
- resolved_at

events
- id INTEGER PK AUTOINCREMENT
- goal_id
- type
- actor
- payload_json
- correlation_id
- created_at

usage_records
- id PK
- goal_id
- task_id
- run_id
- agent_id
- model
- usage_json
- cost_usd
- wall_time_ms
- outcome
- failure_type
- created_at

goal_session_links
- id PK
- goal_id
- hermes_profile
- session_key
- channel
- external_user_id
- relation
- created_at
```

所有 JSON 字段进入 Pydantic Model 校验后再写库。

---

# 28. 核心执行序列

## 28.1 创建并执行 Goal

```text
User -> Hub Agent: 需求
Hub Agent -> AgentHub MCP: create_goal
AgentHub -> DB: Goal(draft)
Hub Agent -> AgentHub MCP: submit_harness(Logical IR)
AgentHub -> Validator: validate
AgentHub -> Compiler: compile
AgentHub -> DB: HarnessVersion(active), HarnessRun(running)
AgentHub -> Hermes Kanban: create/link tasks
Hermes/External Supervisor -> Worker: start(TaskEnvelope)
Worker -> Artifact Store: publish
Worker/Supervisor -> Kanban: complete/block
Controller -> Gate Runner: execute checks
Controller -> Reviewer Task: create
Reviewer -> Review Artifact
Completion Controller -> Goal: completed/review
UI/Channel -> User: candidate commit ready
```

## 28.2 Review 不通过

```text
Reviewer: changes_required
  -> Controller 创建 Observation
  -> Hub/Planner 提交 Harness Patch 或使用预定义 repair loop
  -> 新 HarnessVersion
  -> 新 Repair Task
  -> Gate
  -> Independent Review
  -> 达到上限仍失败 -> Goal failed / human input
```

## 28.3 Worker 请求新角色

```text
Worker -> SpawnTaskProposal
Runtime -> 检查预算/权限/Team 上限
Runtime -> Registry 解析候选
Runtime -> 创建新 HarnessVersion 或子 Task
Runtime -> 绑定 Agent
```

Worker 不能直接拉起顶层 Agent。

## 28.4 用户修改优先级

```text
User -> Hub: 先不要改 UI，只修后端
Hub -> PatchHarnessProposal
Runtime -> 校验未执行 Step
Runtime -> Harness v3 -> v4
已运行历史保持不变
```

---

# 29. 安全与权限

## 29.1 默认安全姿态

- 所有服务默认绑定 `127.0.0.1`；
- 非本机暴露必须开启认证；
- Secret 通过环境变量或 Runtime Secret Store 注入；
- AgentHub DB 不存明文 API Key；
- 默认 `write_candidate`，不自动合并；
- 高风险命令沿用各 Runtime Approval/Sandbox；
- Artifact 访问必须验证 Goal/用户关联。

## 29.2 Prompt 不是安全边界

以下必须由 Runtime 执行：

- 目录限制；
- Worktree；
- 命令 Allow/Deny；
- 网络策略；
- Secret Scope；
- Token/时间/进程限制；
- 合并权限。

如果某个 Runtime 无法提供强 Sandbox，UI 和日志必须明确标记为 best-effort，不虚假宣称强隔离。

## 29.3 Harness 安全

- IR 使用 JSON Schema；
- 禁止任意 import 和直接 Shell；
- `sandbox_compute` 第一版可不实现；
- Loop、Agent 数、并发、成本全部有界；
- Harness 运行前展示摘要和成本；
- 高成本/高权限请求生成 Approval。

---

# 30. 测试策略

## 30.1 Unit Tests

- Goal 状态机；
- Harness Schema；
- Semantic Contract 保持；
- Patch Version；
- Bounds；
- Agent Resolver；
- TaskEnvelope 投影；
- Artifact Hash；
- Usage 聚合；
- Completion Policy。

## 30.2 Integration Tests

使用临时 Hermes Kanban DB 和临时 Git Repo：

1. 创建 Goal；
2. 编译 Harness；
3. 物化 Task；
4. FakeWorker Claim/Complete；
5. 后继 Task 激活；
6. Gate 运行；
7. Reviewer 完成；
8. 候选 Commit 生成；
9. Backend 重启后恢复。

## 30.3 Adapter Contract Tests

对 Hermes、Claude、Codex Adapter 使用相同测试套件：

- start；
- progress；
- cancel；
- timeout；
- result；
- artifact；
- usage；
- blocked/input required。

Live Provider Test 默认跳过，通过环境变量开启。

## 30.4 E2E Demo

创建一个小型示例仓库，内含一个确定 Bug：

- 用户提交修复；
- Fake/真实 Worker 修改；
- 测试从失败变成功；
- Reviewer 通过；
- 输出候选 Commit；
- 用户点击 Merge。

## 30.5 Resilience Tests

- Controller 在 Worker running 时被 kill；
- Controller 重启并恢复；
- External Worker 崩溃；
- 旧 Run 尝试完成被拒绝；
- 重复 Event 不产生重复 Task；
- Approval 重复提交幂等；
- 目标分支变化导致 Merge 拒绝。

---

# 31. 开发里程碑

## Milestone 0：仓库与可运行骨架

交付：

- Python/Frontend 项目；
- 配置；
- SQLite/Alembic；
- Health API；
- CI；
- Hermes 版本检测。

验收：`agenthub serve` 可启动，能检查 Hermes API/Gateway/Kanban 状态。

## Milestone 1：Goal + Harness 核心

交付：

- Goal Model/State；
- Harness IR v1 Schema；
- Validator；
- Version/Patch；
- Event Store；
- REST API。

验收：可以创建 Goal、提交 Harness、查看编译结果，不运行 Worker。

## Milestone 2：Hermes Kanban Vertical Slice

交付：

- Kanban Adapter；
- Board/Task Mapping；
- Reconciler；
- FakeWorker；
- Artifact Store；
- Runtime Gate。

验收：FakeWorker 可以将 Harness 跑完，Backend 重启后恢复。

## Milestone 3：Hermes Hub + Hermes Worker

交付：

- `agenthub-hub` Profile；
- Orchestrator Skill；
- MCP Server；
- Hermes Profile Lane；
- TaskEnvelope；
- Reviewer Profile。

验收：从 Hub 对话创建 Goal，Hermes Worker 完成候选修改和 Review。

## Milestone 4：Claude 与 Codex Lane

交付：

- External Lane Supervisor；
- Claude Adapter；
- Codex Adapter；
- Event/Cancel/Usage；
- Registry/Resolver。

验收：同一 Harness 可以在配置中切换 Hermes、Claude、Codex，且 Task Kernel 不变化。

## Milestone 5：Worktree、Commit 与 Merge Approval

交付：

- Workspace Manager；
- Candidate Commit；
- Gate Commands；
- Merge Approval；
- 冲突保护。

验收：完整 Issue-to-Candidate-Commit 闭环。

## Milestone 6：Web、Channel 与可观测性

交付：

- Chat/Goal UI；
- SSE；
- Kanban View；
- Artifact/Usage；
- Gateway Channel Goal Link；
- 结果通知。

验收：Web 和至少一个 Gateway Channel 可创建/查看同一 Goal。

## Milestone 7：Hardening

交付：

- Failure Budget；
- Crash/Resume；
- Security Review；
- Full E2E；
- 文档与安装脚本。

---

# 32. MVP 最终验收标准

必须全部满足：

1. 用户可从 Web 或 Hermes Channel 提交代码任务；
2. 固定 Hermes Hub Agent 创建 GoalContract；
3. Hub Agent 生成合法 Progressive Harness；
4. Runtime 拒绝无界 Loop、越权和缺少 Mandatory Gate 的 Harness；
5. Harness Step 成功映射到 Hermes Kanban；
6. 至少 Hermes Lane 正常工作；
7. Claude 与 Codex Lane 均通过 Contract Test，至少一个可完成真实任务；
8. 写任务在独立 Worktree；
9. Worker 只能提交候选 Commit；
10. Runtime Gate 能运行测试并记录结果；
11. Reviewer 与 Executor 独立；
12. Review 不通过可触发有界 Repair；
13. Backend 重启后可以恢复；
14. 用户可暂停、取消、审批；
15. UI 可查看 Goal、Harness、Task、Agent、Artifact、Usage；
16. 默认不自动合并；
17. 用户批准后可安全合并或明确报告冲突；
18. 所有关键状态变化有 Event；
19. 所有产物可追溯；
20. AgentHub 没有实现第二套 Hermes Memory 或第二套 Task Scheduler。

---

# 33. 常见错误与禁止实现

Coding Agent 不得采用以下捷径：

1. 用 Prompt 告诉 Worker “请不要越权”，但不做 Runtime 权限控制；
2. 让 Agent 直接更新数据库 status；
3. 把整个 Harness 和所有 Agent Transcript 塞给每个 Worker；
4. 把代码、日志和报告写进 Hermes MEMORY.md；
5. 每个临时 Role 创建永久 Hermes Profile；
6. 用 Agent 名称字符串代替 Capability Contract；
7. 把 Claude/Codex 包成 Hermes 内部一次 Tool Call，却对外宣称一等 Worker；
8. 让 External Worker 直接拼 SQL 修改 Kanban；
9. 把失败测试无限 Retry，而不 Re-plan；
10. 让 Agent 轮询等待后台任务；
11. 让同一个 Agent 实现并独立 Review；
12. 任务完成后自动合并到用户分支；
13. 一开始引入 K8s、消息队列、向量库和复杂分布式锁；
14. 先做 Agent Marketplace，再做 Goal 闭环；
15. 为了省成本偷偷减少用户验收标准。

---

# 34. 未来演进方向（不属于 MVP）

1. Remote Worker Lane；
2. 多机器 Artifact Store；
3. 多租户与组织权限；
4. A2A Agent Card 与外部 Agent Registry；
5. Harness Template 晋升与回归评测；
6. Ephemeral Role 自动晋升 Proposal；
7. Memory Adapter 与跨 Runtime 长期学习；
8. Agent Capability Graph；
9. Harness A/B 和自动优化；
10. 分布式 Task Kernel；
11. 通用研究、投资分析和内容生产场景；
12. Marketplace 与计费。

演进原则：只有当 MVP 执行数据证明某个需求真实存在时才增加，不提前搭建“未来可能需要”的平台层。

---

# 35. 决策理由速查

| 决策 | 理由 |
|---|---|
| Goal-centric | 用户要的是结果，Agent 是供应资源；任务数据才形成壁垒 |
| Hermes Hub 固定 | 减少控制面变量，复用 Memory、Gateway、Kanban |
| Dynamic Harness | 路径在运行时生成，支持循环、并行、验证和修正 |
| Typed IR | 可校验、可恢复、可限权，避免任意控制面代码 |
| Hermes Kanban | 已有持久状态、Claim、Retry、Workspace 和审计 |
| 外部 Lane Sidecar | 不 fork Hermes，也能让 Claude/Codex 成为顶层 Worker |
| Worktree | 并行写入隔离、回滚和审计 |
| Candidate Commit | 降低自动修改用户分支的风险 |
| Artifact/Handoff | Context Firewall，控制 Token 和信息污染 |
| 不新建 Memory | Hermes 已有成熟 Memory，Goal 状态不应混进 Memory |
| 单机 MVP | 先验证价值，不先造分布式基础设施 |
| 软件开发首场景 | 有测试、Commit、Diff 等可确定验证信号 |

---

# 36. 参考实现与资料

实现前应再次核对最新版本，本文基于 2026-07-10 前后的公开实现与以下核心资料：

## Hermes Agent

- Repository: `https://github.com/NousResearch/hermes-agent`
- Kanban overview: `website/docs/user-guide/features/kanban.md`
- Worker lanes: `website/docs/user-guide/features/kanban-worker-lanes.md`
- Kanban CLI/DB: `hermes_cli/kanban.py`, `hermes_cli/kanban_db.py`
- Kanban swarm: `hermes_cli/kanban_swarm.py`
- Kanban decompose: `hermes_cli/kanban_decompose.py`
- Profiles: `website/docs/user-guide/profiles.md`
- Memory: `website/docs/user-guide/features/memory.md`
- Memory providers: `website/docs/user-guide/features/memory-providers.md`
- Gateway internals: `website/docs/developer-guide/gateway-internals.md`
- API Server: `gateway/platforms/api_server.py`

建议第一版 pin Hermes commit/release，并在 CI 中检测兼容性；不要依赖未固定版本的内部字段。

## Claude Code

- Dynamic Workflows: `https://code.claude.com/docs/en/workflows`
- Agent Teams: `https://code.claude.com/docs/en/agent-teams`
- Agent SDK: `https://code.claude.com/docs/en/agent-sdk/typescript`

## Codex

- Official Claude Code plugin: `https://github.com/openai/codex-plugin-cc`
- 优先参考 Codex App Server / SDK 的当前官方文档与事件协议。

## Papers

- *Agentic Software: How AI Agents Are Restructuring the Software Paradigm*, arXiv:2606.05608
- *The Harness Effect: How Orchestration Design Sets the Token Economics of Enterprise Agentic AI*, arXiv:2607.06906

---

# 37. 最终架构定义

> AgentHub 是一个面向异构 Agent 的 JIT Harness Runtime。用户只描述 Goal；Hermes Hub Agent 在运行时生成有界、可修补的 Logical Harness；AgentHub Runtime 将其编译为可恢复的 Physical Harness，并复用 Hermes Kanban 管理任务生命周期，动态调度 Hermes、Claude、Codex Worker。Agent 负责未知路径的探索，Runtime 负责状态、权限、预算、隔离、恢复与验收。协作通过 Artifact 与 Handoff 完成，长期 Agent Memory 复用 Hermes，代码交付默认为经过验证的候选 Commit。

本文档到此结束。Coding Agent 应从 Milestone 0 开始实施，不再继续 Grill 产品方向。
