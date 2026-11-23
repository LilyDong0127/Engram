# Engram

[English](README.en.md) · 可运行草图：[engram_mock.py](engram_mock.py)

带效用归因和编译反补的自进化 Agent 记忆系统。设计稿，服务还没写。文中的组织、人和任务都是虚构例子，不对应任何内部系统。

先跑草图，再往下看设计。草图把一次闭环按 8 步打印出来：写入、候选不注入、个人记忆隔离、权威源覆盖、对照组、归因、编译门禁、解释。

```bash
python mock/engram_mock.py
```

最后一行是 `ok`。检索是词面重叠，不是向量；`accept` 是人工把 candidate 放成 active，因为候选按设计不参与注入，这一步不能从效用里推出来。

现有方案里，Mem0、Letta、Graphiti 解决的是记住什么、怎么取出来；ACE 和 AWM 解决的是从轨迹里抽出可复用的东西。Engram 不重复这两层，它把下面四件事收成同一条闭环。思路和路线在后面两节，和现有方案的逐项对照在「和其他方案比」。

1. **效用归因**。每条记忆的贡献可量化，按 `kind × stage` 分桶。系统知道哪条记忆在哪类任务上帮过忙、坏过事，并用对照组校正单条归因的偏差。
2. **多源仲裁**。记忆和外部权威源（代码、文档、工单）冲突时，按配置的权威等级裁决。有时间窗，不删历史，可追溯。
3. **晋升和编译**。经验逐级升格，编译成流程里的具体产物（prompt 片段、checklist、skill、路由规则），并持续追踪编译后的效果。效果变差就降级、回滚。
4. **内置评估**。对照组、离线回放、在线指标是系统的一部分，不靠事后另做分析。

## 思路

问题不是 agent 记不住，而是记下来的东西不会改变它下一次怎么干活。

常见的做法断在三处：

1. 记了，但不知道这条有没有被用上，更不知道帮了还是害了。检索只能按相似度，旧的、错的和好的一起回来。
2. 记忆、仓库、文档、工单各说各的。没有权威等级，也没有时间窗。要么删掉就没审计，要么冲突一直留在上下文里。
3. 就算归纳出一条经验，它还是躺在记忆库里，下次仍要靠检索碰运气。它没有变成流程里的 prompt、checklist、skill 或路由规则。变成了之后，也没有人看它是不是真的更好，变差了不能撤。

所以自进化指的是这一整截，少一截就不成立：

```
一次执行留下 Trace
  → 抽出 Unit，先放在 candidate，不注入
  → 召回时写下 recall_id 和注入了谁
  → 结果变成 Signal，只分给真正用上的 Unit
  → 离线把 episode 收成 lesson，再收成 procedure
  → 过门禁，编译进 Target
  → Target 上线后的 Signal 仍流回源 Unit，变差就回滚
```

后面的设计都是从这截推出来的，不是功能清单：

- **记忆层不存事实。** 事实会过期，权威在仓库和文档。`fact_ref` 只留指针和带 TTL 的缓存。
- **新记忆默认不注入。** 没有证据就进上下文，是在用别人的任务做实验。
- **效用按 `kind × stage` 分桶。** 同一条经验在实现时有用，在评审时可能有害。
- **探索用抽样，不用均值。** 用均值的话，新记忆永远输给老记忆，学习会停。
- **必须留一批不注入的请求。** 否则分到每条记忆上的好坏会自己证明自己。
- **个人记忆不自动收到项目。** 晋升是治理动作，不是检索的副作用。
- **编译不是终点。** 规则生效后的 Signal 继续记回源 Unit。

## 路线

按闭环缺的那一截排，不按组件排。上一截还不能解释一次注入，下一截就不动工。

**R0，能复述一次注入。** 只有 `observe`、`recall`、`feedback`、`explain`。存储先用一张 Postgres。召回先用词面。做完的标志：任意一次召回都能回答注入了谁、回复有没有用上、信号改了哪几个数。`mock/engram_mock.py` 就是这一截的形状，后面几截在里面是假动作。先不做向量、仲裁、归纳、编译。

**R1，坏记忆会失效，而不被删掉。** 加上 reconcile、权威等级、双时态。做完的标志：和文档冲突时，等级低的那条还在，但不再被注入，`explain` 能说出是谁判的。

**R2，效用开始可信。** 加上 Thompson Sampling、holdout、在线指标。做完的标志：能拿出注入组和对照组的差，而不是只看单条 `helpful`。holdout 有上限，效果为负就停。

**R3，经验会升格，但还只是记忆。** 离线做去重、`episode → lesson → procedure`、衰减。新产物仍是 `candidate`，不改 prompt。做完的标志：多条相似经历变成一条 lesson，原材料还在，带来源链接。

**R4，第一次真正反补。** 只做一个 Target，prompt 片段。路径是 shadow、canary、full，能回滚。规则上线后的信号仍回到源 Unit。做完的标志：一条 procedure 变成规则；指标变差时规则撤下，源 Unit 的后验也掉下去。

R4 之前不接 MCP，不上图数据库，不把个人记忆升到项目。这些都不帮助证明闭环是通的。

| 阶段 | 补上的那一截 | 做完才算数 |
|---|---|---|
| R0 | 注入有记录 | 能解释一次 `recall_id` |
| R1 | 冲突有裁决 | 失效的 Unit 还在，但不再注入 |
| R2 | 效用有对照 | 能报注入组和对照组的差 |
| R3 | 经验会抽象 | 归纳结果仍是 candidate |
| R4 | 经验写回流程 | 一个 Target 能灰度，也能回滚 |

## 非目标

- 不替代向量数据库，也不做通用 RAG。
- 不拥有事实。代码、文档、工单里的事实留在权威源，记忆层只存引用和带 TTL 的缓存。
- 不在第一版做多租户计费、图数据库、消息队列。
- 不自动把个人记忆提升到组织范围。

## 和其他方案比

这几样不是同一层。Mem0 和 Graphiti 是记忆层，Letta 是自带记忆的 agent 运行时，ACE 和 AWM 是从轨迹里改上下文或归纳流程的方法。Engram 不替换它们的检索，也不做 agent 运行时。它要补的是：取回来之后能算账，算账之后能写回具体产物，写回之后还能撤。

| | 存什么 | 冲突 | 效用 | 写回 | 对照 |
|---|---|---|---|---|---|
| [Mem0](https://github.com/mem0ai/mem0) | 从对话抽出的事实，按用户、会话、agent 分开。早期对近邻做 ADD / UPDATE / DELETE / NOOP。新算法改为只追加，新旧事实靠时间并存 | 抽取时由模型决定改写或忽略。没有「仓库 > 文档 > 记忆」这种可配置的源等级 | 没有 | 没有。记下来是为了下次塞回 prompt | 有自己的基准，不是每次召回自带 holdout |
| [Letta](https://github.com/letta-ai/letta)（原 MemGPT） | agent 自己维护的 memory block：一块常驻上下文，加上可检索的 archival | agent 用工具自己改记忆 | 没有统计量。改不改由当次模型决定 | 改的是自己的 memory block，不是仓库里的 skill 或规则，也没有灰度回滚 | 没有 |
| [Graphiti](https://github.com/getzep/graphiti)（Zep） | 时间知识图谱。episode 抽出实体和边。现实时间与入库时间分开，矛盾的边标记失效，不删除 | 图里的事实互相失效。后写入的事实盖过旧事实，不是按外部源等级裁决 | 没有 | 没有 | 有检索基准，没有注入对照 |
| [ACE](https://arxiv.org/abs/2510.04618) | 一份只增不改写的 playbook。生成、反思、策展三步，避免整份重写把细节冲掉 | 不判断代码、文档、工单谁为准 | 有。条目带 helpful / harmful 计数。不按任务阶段分桶，召回时也不抽样 | 写回的就是这份 playbook。没有独立的 Target、门禁和回滚 | 用任务成功率看 playbook，不是召回级 holdout |
| [AWM](https://arxiv.org/abs/2409.07429) | 从轨迹里归纳可复用 workflow，离线或在线都可以，下次任务再提供给 agent | 没有 | 没有。一次成功就可以归纳 | workflow 文本供下次检索。生效后的信号不回流，变差也不回滚 | 论文在 Mind2Web、WebArena 上报告成功率。系统本身不带在线对照 |

逐个看，Engram 拿来用的和故意不做的：

- **Mem0** 的 reconcile（新增、合并、更新、失效、忽略）直接进了写入流水线。Mem0 把抽出的句子当成事实存下来。Engram 的 `fact_ref` 只存权威源的指针和带 TTL 的缓存，记忆层不拥有事实。
- **Letta** 让 agent 自己决定记什么、把什么留在上下文里。这适合做运行时，不适合做跨 agent 的共享记忆。Engram 对外只有五个调用，任何 agent 都能接，记忆的改动要过作用域和门禁，不靠当次模型随手改。
- **Graphiti** 的双时态和「失效不删除」被数据模型照搬。Engram 不默认带图数据库：实体关系先放关系表，检索先做关键词、向量、实体、trigger 四路。源和源冲突时按 Policy 里的权威等级裁决，等级相同就转人工，而不是谁后写入谁赢。
- **ACE** 已经在做效用，这点不能说成空白。它的计数挂在 playbook 条目上，反思由模型完成。Engram 把计数做成 `kind × stage` 上的 Beta 分布，召回时抽样而不是取均值，并用 holdout 把单条归因往整体效果上收缩。写回的目标也不限于一份 playbook，可以是 prompt 片段、checklist、skill 或路由规则，而且要过 shadow、canary 才能全量。
- **AWM** 的「多条经历归纳成可复用流程」对应巩固阶段的 episode → lesson → procedure。Engram 在这之后还有一截：procedure 要满足 helpful 次数、后验均值和 harmful 率，才编译成 rule；rule 上线后的信号继续记回源 Unit，变差就降级回滚。

普通 RAG 不在这张表里。它没有写入决策，没有时效，也没有「这次注入帮了还是害了」。上面任何一个都已经超过 RAG。Engram 和它们的差别是闭环，不是「又一个向量库」。

## 架构

```
Agent
  │  observe / recall / feedback / compile / explain
  ▼
API  (library · HTTP · gRPC · MCP)
  │
  ├─ Ingest        extract → resolve → reconcile → arbitrate
  ├─ Recall        retrieve → rerank → explore → pack → log
  ├─ Credit        used? → attribute signal → update Beta
  ├─ Consolidate   dedupe → abstract → decay → rescan   (cron)
  ├─ Compile       promote → render → gate → rollout
  └─ Govern        scope · provenance · audit · PII
  │
  ▼
Postgres + pgvector
```

对外只有五个动作，其余都在内部流水线。

| 动作 | 作用 |
|---|---|
| `observe(trace)` | 写入一次执行，异步抽取候选记忆 |
| `recall(context, budget)` | 返回记忆包，以及这次的 `recall_id` |
| `feedback(recall_id, signal)` | 回传结果信号，触发归因 |
| `compile(target)` | 产出候选反补产物，进入门禁 |
| `explain(unit_id \| recall_id)` | 解释来源、注入原因、当前效用 |

## 核心对象

| 对象 | 含义 |
|---|---|
| Source | 外部知识源。权威等级，以及更新方式：写入时刷新、调用时刷新、或只实时查 |
| Unit | 一条记忆 |
| Trace | 一次执行：任务、阶段、注入了哪些 Unit、结果信号 |
| Signal | 结果信号：类型、极性、权重、来源、发生时间 |
| Target | 反补落点。每个 Target 自己实现渲染和门禁 |
| Policy | 检索、打分、晋升、淘汰、仲裁。YAML 声明，版本化 |

记忆从具体升到抽象：

```
episode → lesson → procedure → rule
一次经历   抽象经验   可复用流程     编译进 Target 的规则
```

`preference` 和 `fact_ref` 不在这条链上。`fact_ref` 只保存权威源的指针和缓存，缓存过期后以源为准。

## 数据模型

```sql
create table unit (
  id            uuid primary key,
  version       int not null,
  kind          text not null,   -- preference | fact_ref | episode | lesson | procedure | rule
  scope         ltree not null,  -- org.project.user，检索时向上继承
  content       text not null,
  summary       text not null,
  triggers      jsonb not null,  -- {stages, task_types, entities}
  embedding     vector(1536),
  status        text not null,   -- candidate | active | promoted | deprecated | invalid
  valid_from    timestamptz,
  valid_to      timestamptz,
  recorded_at   timestamptz not null,
  invalidated_at timestamptz,
  created_at    timestamptz not null default now()
);

create table unit_utility (
  unit_id   uuid not null references unit(id),
  stage     text not null,       -- 分桶键的一半，另一半是 unit.kind
  injected  int not null default 0,
  used      int not null default 0,
  helpful   int not null default 0,
  harmful   int not null default 0,
  alpha     float not null,      -- Beta(alpha, beta)，探索时抽样
  beta      float not null,
  primary key (unit_id, stage)
);

create table provenance (
  unit_id      uuid not null references unit(id),
  source       text not null,
  ref          text not null,
  trace_id     uuid,
  extracted_at timestamptz not null
);

create table unit_link (
  src    uuid not null references unit(id),
  dst    uuid not null references unit(id),
  rel    text not null,          -- derived_from | supersedes | conflicts_with
  primary key (src, dst, rel)
);

create table recall_log (
  recall_id  uuid primary key,
  context    jsonb not null,
  unit_ids   uuid[] not null,
  arm        text not null,      -- treatment | holdout | kind_ablation
  policy_rev int not null,
  created_at timestamptz not null default now()
);

create table signal (
  id         uuid primary key,
  recall_id  uuid references recall_log(recall_id),
  type       text not null,
  polarity   float not null,     -- [-1, 1]
  weight     float not null,
  source     text not null,
  occurred_at timestamptz not null
);
```

`candidate` 不参与注入。失效只写 `invalidated_at` 和 `status`，不删除行。

## 接口

`recall` 的请求和响应：

```json
// POST /v1/recall
{
  "scope": "org/acme/project/billing/user/ada",
  "stage": "review",
  "task_type": "bugfix",
  "query": "retry duplicated an invoice write",
  "budget_tokens": 1200
}

// 200
{
  "recall_id": "9f3c…",
  "arm": "treatment",
  "policy_rev": 17,
  "units": [
    {
      "id": "1b20…",
      "kind": "lesson",
      "summary": "重试账单写入前先带上 Idempotency-Key",
      "content": "…",
      "score": 0.81,
      "why": [
        "trigger:stage=review",
        "entity overlap",
        "utility sample 0.74"
      ]
    }
  ]
}
```

`feedback` 可以晚到。`recall_id` 跨会话有效，信号带 `occurred_at`，归因时按时间衰减。

```json
// POST /v1/feedback
{
  "recall_id": "9f3c…",
  "type": "review_rejected",
  "polarity": -0.8,
  "weight": 1.0,
  "source": "code_review",
  "occurred_at": "2026-11-19T08:12:00Z"
}
```

`explain` 返回三条链：这条记忆从哪次 trace、哪个源来；这次召回为什么选中它（各分项）；它在各 `stage` 上的后验和样本量。

## 流水线

### 1. 写入

`observe → extract → resolve → reconcile → arbitrate → candidate`

- **extract**：模型从 trace 抽出候选，标 `kind`、`triggers`、`entities`。抽不出就记一条空 trace，不硬造记忆。
- **resolve**：把实体对齐到已有 canonical id，避免同一对象写出多条互不关联的记忆。
- **reconcile**：和已有 Unit 比，得出 `ADD | MERGE | UPDATE | INVALIDATE | NOOP`。
- **arbitrate**：和权威源冲突时按 Policy 的等级裁决。等级低的一方标记失效，不删除。等级相同，生成人工复核，两边都保持原状态。
- 写入结果一律是 `candidate`。晋升到 `active` 要过最小证据门槛，见 Policy。

### 2. 召回

`plan → retrieve → rerank → explore → pack → log`

四路召回并行，不做全量注入：

| 路 | 命中方式 |
|---|---|
| lexical | `summary` / `content` 全文 |
| vector | `embedding` 近邻 |
| entity | `triggers.entities` 与当前实体求交 |
| trigger | `stage`、`task_type` 精确匹配 |

重排：

```
score = relevance ^ w_r
      * utility_sample ^ w_u
      * freshness ^ w_f
      * scope_proximity ^ w_s
```

`utility_sample` 从 `Beta(alpha, beta)` 抽一次，不取均值。新记忆和样本少的记忆因此有机会被用到。这是在线学习发生的地方。

装箱按 kind 分预算，例如 preference 10%、lesson 50%、procedure 40%。某一类不够，余量按分数顺延给其他类，不留空。

每次召回写 `recall_log`：`recall_id → unit_ids`，并记下 `arm` 和 `policy_rev`。没有这条记录就不能归因。

对照由 Policy 决定，三种 arm：

- `treatment`：正常注入
- `holdout`：不注入
- `kind_ablation`：去掉某一类 kind

holdout 比例要设上限，并在指标稳定后自动缩小。见「待决问题」。

### 3. 归因

收到 Signal 后：

1. **是否被使用**。对每条注入的 Unit，先做词面和 embedding 比对；不确定再问模型。没用上的只加 `injected`。
2. **极性分摊**。用上的 Unit 分这条 Signal 的极性，更新对应桶的 `alpha` 或 `beta`。默认按引用强度分，不是均分。
3. **对照校正**。同一 `policy_rev` 下，treatment 与 holdout 的结果差记为全局增益。单条归因的总和若偏离这个差，按比例收缩，避免偏差累积。

### 4. 巩固

离线任务，建议按天跑。

- 聚类合并近似 lesson。
- 多条相似 episode 归纳成一条 lesson；多条 lesson 归纳成 procedure。归纳结果是新的 `candidate`，带来源链接 `derived_from`，不覆盖原材料。
- 长期未命中的降权。`harmful / injected` 超过阈值的改为 `deprecated`，停止注入，保留记录。
- 拿 `fact_ref` 和 lesson 重新对照权威源。不一致就标失效。

### 5. 编译

```yaml
promotion:
  candidate_to_active:
    min_injected: 3
    max_harmful_rate: 0.2
  lesson_to_procedure:
    min_helpful: 5
    min_posterior_mean: 0.7
    max_harmful_rate: 0.1
  procedure_to_rule:
    min_helpful: 10
    gate: [shadow_eval, human_approval]
```

Target 是插件，只实现两个方法：

```text
render(units) -> artifact
gate(artifact) -> {pass, fail, reason}
```

产物有版本：`shadow → canary → full`，任一阶段指标变差就停在当前阶段并回滚。规则生效后的 Signal 继续记到源 Unit 上。规则自己也留 holdout，否则上线后没有对照。

### 6. 治理

- 检索向上继承：`user` 能看到 `project` 和 `org`，反过来不行。
- 个人记忆默认不能升到 project。升级要脱敏，并过审批插件。
- `explain` 必须能在不看日志的情况下回答：从哪来、为什么注入、效用是多少、样本量够不够。
- 审计、PII 检测、权限都是插件。检测失败的 Unit 停在 `candidate`。

## Policy

```yaml
version: 17
recall:
  weights: { relevance: 0.4, utility: 0.3, freshness: 0.2, scope: 0.1 }
  budget:  { preference: 0.1, lesson: 0.5, procedure: 0.4 }
  holdout_rate: 0.05
  holdout_max_rate: 0.1
  prior: { alpha: 1.0, beta: 1.0 }   # 新 Unit。是否继承桶先验见待决问题
credit:
  half_life: 72h
  use_threshold: 0.55
  shrink_toward_ate: true           # 单条归因向对照差收缩
arbitrate:
  rank: [repository, docs, issue_tracker, memory]
  tie: human_review
decay:
  unused_after: 30d
  deprecate_harmful_rate: 0.3
```

Policy 每次变更 `version + 1`。`recall_log.policy_rev` 指向当时的版本，回放时按这个版本重算。

## 插件

| 插件 | 职责 |
|---|---|
| Connector | 接外部源：GitHub、GitLab、Jira、Confluence、Notion，或只读 HTTP |
| Extractor | 从一种 trace 里抽什么、不抽什么 |
| Retriever | 一路召回的实现 |
| SignalMap | 业务事件到 Signal，例如评审打回 `-0.8`、用户点赞 `+0.5` |
| Target | `render` + `gate`，产物可以是 prompt 片段、checklist、skill、路由规则 |
| Store | 存储。默认 Postgres + pgvector |
| LLM | 抽取、归纳、歧义判断 |

默认存储只有一个数据库。实体关系先放 `unit_link` 和 `triggers.entities`，不够用再加图数据库插件，不作为默认依赖。

## 评估

评估和写入、召回同一套表，不另建数仓。

| 层 | 指标 | 来源 |
|---|---|---|
| 覆盖 | 有记忆的 scope 占比、日新增、kind 分布 | `unit` |
| 注入准确率 | `used / injected` | `unit_utility` |
| 效果 | treatment 与 holdout 在返工率、轮数、耗时上的差 | `recall_log.arm` + `signal` |
| 副作用 | harmful 率、失效记忆被注入的次数 | utility + `invalidated_at` |
| 反补 | 产物在 shadow、canary、full 各阶段的指标差 | Target 版本 |

离线回放读历史 `recall_log`，换一份 Policy 重算排序和装箱，不重新调用外部源。题型分五类：静态状态、动态状态、流程、坑点、前提是否成立。分类参照 LongMemEval。

## 建议的仓库布局

```
engram/
  proto/            # gRPC
  openapi/          # HTTP
  internal/
    ingest/
    recall/
    credit/
    consolidate/
    compile/
    govern/
  plugin/           # Connector, Target, Store 的接口和默认实现
  policy/           # 默认 policy.yaml 和 schema
  migrate/          # SQL
  cmd/engram/       # 服务入口
  eval/             # 回放和对照报告
```

第一版只做 library + HTTP + 一张 Postgres，对应路线里的 R0 到 R1。gRPC、MCP、编译门禁放在 R4，避免接口还没稳定就做三套传输。

## 待决问题

- **分摊**。一条 Signal 对应多条被使用的 Unit 时，按引用强度分是默认，但是否要上 Shapley 近似，要看延迟能不能接受。
- **规则的对照**。rule 一旦全量就没有天然 holdout，必须在编译时把 holdout 写进 Target，而不是只在 recall 层抽样。
- **对照的代价**。holdout 会让一部分请求变差。需要规定最大比例、最短运行时间，以及效果为负时立即关掉的条件。
- **冷启动先验**。新 Unit 用 `Beta(1,1)`，还是继承同 `kind × stage` 桶的后验。继承会让新记忆看起来比实际更可信。
- **信号延迟**。评审打回可能在数小时后才到。衰减用 `half_life`，但跨天的 Signal 是否还应该更新当天的桶，需要定。

## 草图

`mock/engram_mock.py` 只用标准库，不调用模型。它演示 candidate 不注入、作用域向上继承、Beta 抽样、holdout、归因和编译门禁。

```bash
python mock/engram_mock.py
```

## 参考

- [Mem0](https://github.com/mem0ai/mem0)。抽取后的事实维护；早期是 ADD / UPDATE / DELETE / NOOP，新算法改为只追加并用时间并存新旧事实
- [Letta](https://github.com/letta-ai/letta)。原 MemGPT。agent 用工具维护 memory block 和 archival memory
- [Graphiti](https://github.com/getzep/graphiti)。Zep 的时间知识图谱，双时态，矛盾边失效不删除。[论文](https://arxiv.org/abs/2501.13956)
- [ACE](https://arxiv.org/abs/2510.04618)，Agentic Context Engineering。playbook 增量更新，条目带 helpful / harmful 计数
- [AWM](https://arxiv.org/abs/2409.07429)，Agent Workflow Memory。从轨迹归纳可复用 workflow
- LongMemEval
