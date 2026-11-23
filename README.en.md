# Engram

[中文](README.md) · Runnable sketch: [mock/engram_mock.py](mock/engram_mock.py)

A self-evolving agent memory with utility attribution and compiled write-back. Design only. The service is not written. Organizations, people, and tasks in the examples are fictional and do not refer to any internal system.

Run the sketch before reading the design. It prints one loop in eight steps: write, candidate not injected, personal scope isolation, authority override, holdout, credit assignment, compile gate, explain.

```bash
python mock/engram_mock.py
```

The last line is `ok`. Retrieval is token overlap, not vectors. `accept` is a human flip from candidate to active. Candidates are not injected, so that flip cannot be inferred from utility.

Mem0, Letta, and Graphiti decide what to store and how to retrieve it. ACE and AWM turn traces into reusable context or workflows. Engram does not redo either layer. It closes one loop around the four things below. The row-by-row comparison is in the next section.

1. **Utility attribution.** Each memory has a measured contribution, bucketed by `kind × stage`. The system knows which memory helped or hurt on which kind of task, and a holdout corrects single-item bias.
2. **Multi-source arbitration.** When a memory conflicts with an authority (repository, docs, issue tracker), a configured rank decides. The loser is closed with a time window. History is kept.
3. **Promotion and compile.** Experience is abstracted step by step, then compiled into a concrete artifact (prompt fragment, checklist, skill, routing rule). Signals after rollout still update the source memories. A worse artifact is rolled back.
4. **Built-in evaluation.** Holdouts, offline replay, and online metrics are part of the system, not a later analysis job.

## Non-goals

- Not a vector database, and not a general RAG stack.
- The memory layer does not own facts. Facts stay in the authority. Memory stores a pointer and a TTL cache.
- No multi-tenant billing, graph database, or message queue in v1.
- Personal memory is never promoted to the org automatically.

## Comparison

These are not the same kind of system. Mem0 and Graphiti are memory layers. Letta is an agent runtime with memory built in. ACE and AWM are methods that turn traces into a playbook or a workflow. Engram does not replace their retrieval and it is not a runtime. The piece it adds is: after a memory is used, score it; after it scores well, write it back into a concrete artifact; if that artifact gets worse, pull it back.

| | What it stores | Conflict | Utility | Write-back | Control |
|---|---|---|---|---|---|
| [Mem0](https://github.com/mem0ai/mem0) | Facts extracted from conversation, scoped to user, session, or agent. Earlier versions classify neighbors as ADD / UPDATE / DELETE / NOOP. The newer algorithm only appends, and keeps old and new facts with time | The extractor model decides to rewrite or ignore. There is no configured rank such as repository > docs > memory | None | None. Memories exist to be inserted into a later prompt | Has its own benchmark. A holdout is not attached to each recall |
| [Letta](https://github.com/letta-ai/letta) (was MemGPT) | Memory blocks the agent maintains: one resident block in context, plus searchable archival memory | The agent edits its own memory with tools | No statistic. The current model call decides | Edits its own block, not a skill or rule in a repository. No canary, no rollback | None |
| [Graphiti](https://github.com/getzep/graphiti) (Zep) | A temporal knowledge graph. Episodes become entities and edges. Valid time and ingestion time are separate. Contradicted edges are invalidated, not deleted | A newer fact in the graph supersedes an older one. Rank is not a configurable authority order | None | None | Retrieval benchmarks. No injection holdout |
| [ACE](https://arxiv.org/abs/2510.04618) | An append-only playbook. Generator, reflector, and curator add deltas instead of rewriting the whole context | Does not decide whether the repository, the docs, or the tracker wins | Yes. Bullets carry helpful / harmful counts. Not bucketed by task stage, and not sampled at recall | The playbook is the only artifact. No separate target, gate, or rollback | Task success of the playbook, not a per-recall holdout |
| [AWM](https://arxiv.org/abs/2409.07429) | Workflows induced from traces, offline or online, then shown to the agent on later tasks | None | None. One success is enough to induce a workflow | Workflow text is retrieved later. Later signals do not flow back, and a regression does not roll it back | The paper reports success on Mind2Web and WebArena. The method has no online control arm |

What Engram takes, and what it leaves alone:

- **Mem0.** The reconcile actions (add, merge, update, invalidate, ignore) are the ingest pipeline. Mem0 stores the extracted sentence as the fact. Engram's `fact_ref` stores a pointer and a TTL cache. The memory layer does not own the fact.
- **Letta.** The agent decides what to remember and what stays in context. That fits a runtime. It is a poor fit for memory shared across agents. Engram exposes five calls. Changes pass a scope check and a gate. The model on the current turn does not edit storage directly.
- **Graphiti.** Bitemporal fields and invalidation-without-delete are copied into the schema. Engram does not ship a graph database by default. Links live in a table. Recall is lexical, vector, entity, and trigger. When two sources disagree, Policy rank decides. A tie goes to a human. Later-write does not win by default.
- **ACE.** Utility is not a blank cell here. ACE counts helpful and harmful on playbook bullets, and a model does the reflection. Engram puts a Beta on each `kind × stage` bucket, samples it at recall instead of taking the mean, and shrinks per-unit credit toward the holdout gap. Write-back is not limited to one playbook. A prompt fragment, checklist, skill, or routing rule can be a target, and it has to pass shadow and canary before it is fully on.
- **AWM.** Inducing a reusable routine from many episodes is the consolidate step, episode → lesson → procedure. Engram continues past that. A procedure becomes a rule only after a helpful count, a posterior mean, and a harmful rate. Signals after the rule is live still score the source units. A regression demotes and rolls back.

Plain RAG is not in the table. It has no write decision, no validity window, and no record of whether an injection helped. Every row above already goes past RAG. The difference Engram is arguing for is the loop, not another vector store.

## Architecture

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

Five calls. Everything else is internal.

| Call | Role |
|---|---|
| `observe(trace)` | Record one run. Extract candidate memories asynchronously |
| `recall(context, budget)` | Return a memory pack and this call's `recall_id` |
| `feedback(recall_id, signal)` | Return an outcome. Starts credit assignment |
| `compile(target)` | Render a candidate artifact and send it through the gate |
| `explain(unit_id \| recall_id)` | Why it was stored, why it was injected, current utility |

## Objects

| Object | Meaning |
|---|---|
| Source | External authority. Rank, and when it is refreshed: on write, on read, or live only |
| Unit | One memory |
| Trace | One run: task, stage, which units were injected, outcome signals |
| Signal | Outcome: type, polarity, weight, source, time |
| Target | Where a compiled artifact lands. Each target implements render and gate |
| Policy | Retrieval, scoring, promotion, decay, arbitration. Versioned YAML |

Abstraction chain, concrete to abstract:

```
episode → lesson → procedure → rule
one run    lesson    reusable flow   rule compiled into a target
```

`preference` and `fact_ref` are outside the chain. A `fact_ref` is a pointer plus a cache. When the cache expires, the authority wins.

## Schema

```sql
create table unit (
  id            uuid primary key,
  version       int not null,
  kind          text not null,   -- preference | fact_ref | episode | lesson | procedure | rule
  scope         ltree not null,  -- org.project.user; recall inherits upward
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
  stage     text not null,
  injected  int not null default 0,
  used      int not null default 0,
  helpful   int not null default 0,
  harmful   int not null default 0,
  alpha     float not null,      -- Beta(alpha, beta), sampled at recall
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

A `candidate` is never injected. Invalidation sets `invalidated_at` and `status`. Rows are not deleted.

## API

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
  "recall_id": "9f3c",
  "arm": "treatment",
  "policy_rev": 17,
  "units": [
    {
      "id": "1b20",
      "kind": "lesson",
      "summary": "Make the invoice write idempotent on Idempotency-Key before retrying",
      "content": "…",
      "score": 0.81,
      "why": ["trigger:stage=review", "entity overlap", "utility sample 0.74"]
    }
  ]
}
```

`feedback` may arrive hours later. `recall_id` stays valid across sessions. Credit assignment decays by `occurred_at`.

```json
// POST /v1/feedback
{
  "recall_id": "9f3c",
  "type": "review_rejected",
  "polarity": -0.8,
  "weight": 1.0,
  "source": "code_review",
  "occurred_at": "2026-11-19T08:12:00Z"
}
```

`explain` returns three chains: where the unit came from, why this recall selected it, and the posterior plus sample size per stage.

## Pipelines

### 1. Ingest

`observe → extract → resolve → reconcile → arbitrate → candidate`

- **extract.** The model proposes units and labels `kind`, `triggers`, and `entities`. If nothing is worth keeping, store an empty trace. Do not invent a memory.
- **resolve.** Map entities onto existing canonical ids.
- **reconcile.** Compare with current units: `ADD | MERGE | UPDATE | INVALIDATE | NOOP`.
- **arbitrate.** On conflict with an authority, Policy rank wins. The lower rank is invalidated, not deleted. Equal rank opens a human review and changes nothing.
- New units are `candidate`. Moving to `active` requires the evidence floor in Policy.

### 2. Recall

`plan → retrieve → rerank → explore → pack → log`

Four retrievers, no full-context dump:

| Path | Match |
|---|---|
| lexical | full text of `summary` / `content` |
| vector | nearest `embedding` |
| entity | intersection of `triggers.entities` and the current entities |
| trigger | exact `stage` and `task_type` |

Rerank:

```
score = relevance ^ w_r
      * utility_sample ^ w_u
      * freshness ^ w_f
      * scope_proximity ^ w_s
```

`utility_sample` is one draw from `Beta(alpha, beta)`, not the mean. New and low-sample memories get tried. That draw is the online-learning step.

Packing assigns a token budget per kind, for example preference 10%, lesson 50%, procedure 40%. Unused budget falls through to the next-best unit of another kind.

Every recall writes `recall_id → unit_ids`, plus `arm` and `policy_rev`. Credit assignment cannot run without that row.

Arms:

- `treatment`: normal injection
- `holdout`: inject nothing
- `kind_ablation`: drop one kind

Cap the holdout rate, and shrink it once the metric is stable. See open questions.

### 3. Credit

On a signal:

1. **Was it used?** Compare the reply or the action to each injected unit, first by tokens and embedding, then by a model if still unsure. Unused units only increment `injected`.
2. **Polarity split.** Used units share the signal, weighted by how strongly they were cited, and update `alpha` or `beta` in the `kind × stage` bucket.
3. **Holdout correction.** Under the same `policy_rev`, the treatment-minus-holdout gap is the global effect. If the sum of per-unit credit drifts from that gap, shrink the per-unit updates toward it.

### 4. Consolidate

A daily job.

- Cluster near-duplicate lessons.
- Many similar episodes become one lesson. Many lessons become one procedure. The result is a new `candidate` with `derived_from` links. Raw units stay.
- Unused units lose weight. `harmful / injected` over the threshold becomes `deprecated`: stop injecting, keep the row.
- Re-check `fact_ref` and lessons against authorities. Mismatch invalidates the unit.

### 5. Compile

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

A target is a plugin with two methods:

```text
render(units) -> artifact
gate(artifact) -> {pass, fail, reason}
```

Artifacts move `shadow → canary → full`. A regression stops the rollout and rolls back. Signals after the rule is live still score the source units. The rule itself keeps a holdout. Otherwise there is no control once it is on for everyone.

### 6. Govern

- Recall inherits upward. A user scope can see its project and org. The reverse is forbidden.
- Personal memory does not move to the project scope unless a redaction step and an approval plugin both pass.
- `explain` must answer, without a log dive: origin, why injected, utility, and whether the sample is large enough.
- Audit, PII detection, and authz are plugins. A failed check leaves the unit as `candidate`.

## Policy

```yaml
version: 17
recall:
  weights: { relevance: 0.4, utility: 0.3, freshness: 0.2, scope: 0.1 }
  budget:  { preference: 0.1, lesson: 0.5, procedure: 0.4 }
  holdout_rate: 0.05
  holdout_max_rate: 0.1
  prior: { alpha: 1.0, beta: 1.0 }   # new units; inheriting the bucket prior is open
credit:
  half_life: 72h
  use_threshold: 0.55
  shrink_toward_ate: true
arbitrate:
  rank: [repository, docs, issue_tracker, memory]
  tie: human_review
decay:
  unused_after: 30d
  deprecate_harmful_rate: 0.3
```

Each policy change increments `version`. `recall_log.policy_rev` is the version that served the call. Replay uses that version.

## Plugins

| Plugin | Role |
|---|---|
| Connector | External source: GitHub, GitLab, Jira, Confluence, Notion, or read-only HTTP |
| Extractor | What to extract from a given trace shape |
| Retriever | One recall path |
| SignalMap | Domain event to signal. Review rejected `-0.8`, user upvote `+0.5` |
| Target | `render` + `gate`. Artifact may be a prompt fragment, checklist, skill, or routing rule |
| Store | Storage. Default is Postgres + pgvector |
| LLM | Extract, abstract, and break ties |

One database by default. Entity links live in `unit_link` and `triggers.entities`. Add a graph plugin only when that is not enough.

## Evaluation

Same tables as ingest and recall. No separate warehouse.

| Layer | Metric | Source |
|---|---|---|
| Coverage | share of scopes with memory, daily inserts, kind mix | `unit` |
| Injection precision | `used / injected` | `unit_utility` |
| Effect | treatment vs holdout on rework rate, turns, latency | `recall_log.arm` + `signal` |
| Harm | harmful rate, injections of invalidated units | utility + `invalidated_at` |
| Write-back | metric delta across shadow, canary, full | target versions |

Offline replay reads historical `recall_log`, rescores with another policy, and does not call authorities again. Item types follow LongMemEval: static state, dynamic state, workflow, pitfalls, and whether a precondition holds.

## Suggested layout

```
engram/
  proto/
  openapi/
  internal/
    ingest/
    recall/
    credit/
    consolidate/
    compile/
    govern/
  plugin/
  policy/
  migrate/
  cmd/engram/
  eval/
  mock/              # stdlib sketch, see mock/engram_mock.py
```

v1 is a library, HTTP, and one Postgres. gRPC, MCP, and compile gates wait until the five calls stop changing.

## Milestones

| Milestone | Done when |
|---|---|
| M0 | `observe` / `recall` / `feedback` work, and `recall_log` is explainable |
| M1 | reconcile, arbitration, bitemporal invalidation |
| M2 | Thompson sampling, holdout, online metrics |
| M3 | consolidate: dedupe, abstract, decay |
| M4 | one target (prompt fragment) goes shadow → canary → rollback |

## Open questions

- **Split.** Default is citation strength. A Shapley approximation is only worth it if the latency is acceptable.
- **Control for rules.** A fully rolled-out rule has no natural holdout. The holdout has to be compiled into the target, not only sampled at recall.
- **Cost of holdout.** Some requests get worse. Need a max rate, a minimum runtime, and a kill switch when the effect is negative.
- **Cold-start prior.** `Beta(1,1)`, or the posterior of the same `kind × stage` bucket. Inheriting makes a new memory look more certain than it is.
- **Late signals.** A review rejection can arrive hours later. Decay uses `half_life`. Whether a signal updates the bucket of the original day is undecided.

## Mock

`mock/engram_mock.py` is stdlib only. It does not call a model. It shows candidate vs active, upward scope, a Beta draw, holdout, credit assignment, and a compile gate.

```bash
python mock/engram_mock.py
```

## References

- [Mem0](https://github.com/mem0ai/mem0). Fact extraction and maintenance. Earlier: ADD / UPDATE / DELETE / NOOP. Newer: append-only, old and new facts kept with time
- [Letta](https://github.com/letta-ai/letta). Formerly MemGPT. The agent edits memory blocks and archival memory with tools
- [Graphiti](https://github.com/getzep/graphiti). Zep's temporal knowledge graph. Bitemporal edges, contradiction invalidates rather than deletes. [Paper](https://arxiv.org/abs/2501.13956)
- [ACE](https://arxiv.org/abs/2510.04618), Agentic Context Engineering. Incremental playbook updates, helpful / harmful counts on bullets
- [AWM](https://arxiv.org/abs/2409.07429), Agent Workflow Memory. Induce reusable workflows from traces
- LongMemEval
