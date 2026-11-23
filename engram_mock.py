
#!/usr/bin/env python3
"""In-memory sketch of the Engram loop. Standard library only.

Retrieval is token overlap, not embeddings. Arbitration is a rank table.
Nothing here is a service. Run: python mock/engram_mock.py
"""

from __future__ import annotations

import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


AUTHORITY_RANK = {"repository": 0, "docs": 1, "issue_tracker": 2, "memory": 3}


def _parts(scope: str) -> list[str]:
    return [p for p in scope.split("/") if p]


@dataclass
class Unit:
    id: str
    kind: str
    scope: str
    content: str
    summary: str
    stages: list[str]
    task_types: list[str]
    entities: list[str]
    status: str = "candidate"
    alpha: float = 1.0
    beta: float = 1.0
    injected: int = 0
    used: int = 0
    helpful: int = 0
    harmful: int = 0
    source: str = "session"
    ref: str = ""
    authority: str = "memory"
    claim: str = ""
    stance: str = ""
    recorded_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    invalidated_at: datetime | None = None

    @property
    def posterior_mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)


class Engram:
    """Five calls: observe, recall, feedback, compile, explain."""

    def __init__(self, seed: int = 7) -> None:
        self.rng = random.Random(seed)
        self.units: dict[str, Unit] = {}
        self.recalls: dict[str, dict] = {}
        self.policy_rev = 1
        self.weights = {"relevance": 0.4, "utility": 0.3, "freshness": 0.2, "scope": 0.1}
        self.events: list[str] = []

    def observe(self, trace: dict) -> dict:
        text = trace["text"].strip()
        summary = text.split(".")[0][:140]
        for old in self.units.values():
            if old.summary == summary and old.status != "invalid":
                self.events.append(f"reconcile NOOP {old.id}")
                return {"action": "NOOP", "unit_id": old.id}

        unit = Unit(
            id=uuid.uuid4().hex[:8],
            kind=trace.get("kind", "lesson"),
            scope=trace["scope"],
            content=text,
            summary=summary,
            stages=list(trace.get("stages", ["review"])),
            task_types=list(trace.get("task_types", ["bugfix"])),
            entities=list(trace.get("entities", [])),
            source=trace.get("source", "session"),
            ref=trace.get("trace_id", ""),
            authority=trace.get("authority", "memory"),
            claim=trace.get("claim", ""),
            stance=trace.get("stance", ""),
        )
        conflict = self._arbitrate(unit)
        if conflict is not None:
            return conflict
        self.units[unit.id] = unit
        self.events.append(f"ADD {unit.id} status={unit.status} scope={unit.scope}")
        return {"action": "ADD", "unit_id": unit.id, "status": unit.status}

    def accept(self, unit_id: str) -> str:
        """Human gate. Candidates are not injected, so this cannot be inferred from utility."""
        unit = self.units[unit_id]
        if unit.status == "candidate":
            unit.status = "active"
            self.events.append(f"accept {unit.id} -> active")
        return unit.status

    def recall(self, ctx: dict, budget_tokens: int = 800, arm: str = "treatment") -> dict:
        recall_id = uuid.uuid4().hex[:8]
        packed: list[dict] = []
        why: dict[str, dict] = {}
        if arm != "holdout":
            packed, why = self._pack(ctx, budget_tokens)
            for item in packed:
                self.units[item["id"]].injected += 1
        self.recalls[recall_id] = {
            "arm": arm,
            "units": [item["id"] for item in packed],
            "why": why,
            "ctx": ctx,
        }
        return {"recall_id": recall_id, "arm": arm, "policy_rev": self.policy_rev, "units": packed}

    def feedback(self, recall_id: str, signal: dict) -> dict:
        rec = self.recalls[recall_id]
        if rec["arm"] == "holdout":
            self.events.append(f"feedback {recall_id} holdout ignored")
            return {"updated": [], "skipped": "holdout"}
        reply = signal.get("reply", "")
        updated = []
        for unit_id in rec["units"]:
            unit = self.units[unit_id]
            if not _cited(unit, reply):
                self.events.append(f"credit {unit.id} injected only")
                continue
            unit.used += 1
            polarity = float(signal["polarity"])
            weight = float(signal.get("weight", 1.0))
            if polarity >= 0:
                unit.helpful += 1
                unit.alpha += weight * polarity
            else:
                unit.harmful += 1
                unit.beta += weight * abs(polarity)
            updated.append(unit.id)
            self.events.append(
                f"credit {unit.id} polarity={polarity:+.1f} mean={unit.posterior_mean:.2f} helpful={unit.helpful}"
            )
        return {"updated": updated}

    def compile_checklist(self) -> dict:
        ready = []
        for unit in self.units.values():
            if unit.kind != "lesson" or unit.status not in ("active", "promoted"):
                continue
            harmful_rate = unit.harmful / unit.used if unit.used else 0.0
            if unit.helpful >= 5 and unit.posterior_mean >= 0.7 and harmful_rate <= 0.1:
                ready.append(unit)
        if not ready:
            return {"pass": False, "reason": "no lesson passed helpful>=5, mean>=0.7, harmful_rate<=0.1"}
        for unit in ready:
            unit.status = "promoted"
        lines = "\n".join(f"- {unit.summary}" for unit in ready)
        return {
            "pass": True,
            "stage": "shadow",
            "unit_ids": [unit.id for unit in ready],
            "artifact": "# checklist\n" + lines,
        }

    def explain(self, unit_id: str, recall_id: str | None = None) -> dict:
        unit = self.units[unit_id]
        out = {
            "id": unit.id,
            "status": unit.status,
            "scope": unit.scope,
            "from": f"{unit.source}:{unit.ref}" if unit.ref else unit.source,
            "injected": unit.injected,
            "used": unit.used,
            "helpful": unit.helpful,
            "harmful": unit.harmful,
            "posterior_mean": round(unit.posterior_mean, 3),
        }
        if recall_id and unit_id in self.recalls.get(recall_id, {}).get("why", {}):
            out["why"] = self.recalls[recall_id]["why"][unit_id]
        return out

    def _arbitrate(self, incoming: Unit) -> dict | None:
        for old in list(self.units.values()):
            if old.status == "invalid" or old.invalidated_at:
                continue
            if not (set(old.entities) & set(incoming.entities)):
                continue
            if not _contradicts(old, incoming):
                continue
            old_rank = AUTHORITY_RANK[old.authority]
            new_rank = AUTHORITY_RANK[incoming.authority]
            if new_rank < old_rank:
                self._invalidate(old, incoming.authority)
                continue
            if old_rank < new_rank:
                self.events.append(f"arbitrate drop {incoming.summary[:48]} lost to {old.authority}")
                return {"action": "INVALIDATE_INCOMING", "kept": old.id, "authority": old.authority}
            self.events.append("arbitrate tie -> human review, write nothing")
            return {"action": "HUMAN_REVIEW", "kept": old.id}
        return None

    def _invalidate(self, unit: Unit, by: str) -> None:
        unit.status = "invalid"
        unit.invalidated_at = datetime.now(timezone.utc)
        self.events.append(f"invalidate {unit.id} by {by}")

    def _pack(self, ctx: dict, budget_tokens: int) -> tuple[list[dict], dict[str, dict]]:
        now = datetime.now(timezone.utc)
        ranked = []
        for unit in self.units.values():
            if unit.status not in ("active", "promoted") or unit.invalidated_at:
                continue
            if ctx["stage"] not in unit.stages:
                continue
            proximity = _scope_proximity(unit.scope, ctx["scope"])
            if proximity is None:
                continue
            relevance = _relevance(unit, ctx["query"], ctx.get("entities", []))
            if relevance <= 0:
                continue
            sample = self.rng.betavariate(max(unit.alpha, 1e-3), max(unit.beta, 1e-3))
            age_h = max((now - unit.recorded_at).total_seconds() / 3600, 0.0)
            freshness = math.exp(-age_h / (24 * 14))
            w = self.weights
            score = (
                max(relevance, 0.05) ** w["relevance"]
                * max(sample, 0.05) ** w["utility"]
                * max(freshness, 0.05) ** w["freshness"]
                * max(proximity, 0.05) ** w["scope"]
            )
            why = {
                "relevance": round(relevance, 3),
                "utility_sample": round(sample, 3),
                "freshness": round(freshness, 3),
                "scope": round(proximity, 3),
                "score": round(score, 3),
            }
            ranked.append((score, unit, why))
        ranked.sort(key=lambda row: row[0], reverse=True)

        packed: list[dict] = []
        why_map: dict[str, dict] = {}
        spent = 0
        for score, unit, why in ranked:
            cost = max(len(unit.content) // 4, 1)
            if spent + cost > budget_tokens:
                continue
            spent += cost
            packed.append({"id": unit.id, "kind": unit.kind, "summary": unit.summary, "score": round(score, 3)})
            why_map[unit.id] = why
        return packed, why_map


def _scope_proximity(unit_scope: str, query_scope: str) -> float | None:
    unit_parts = _parts(unit_scope)
    query_parts = _parts(query_scope)
    if unit_parts != query_parts[: len(unit_parts)]:
        return None
    return len(unit_parts) / len(query_parts)


def _relevance(unit: Unit, query: str, entities: list[str]) -> float:
    tokens = set(query.lower().split())
    text = set((unit.summary + " " + unit.content).lower().split())
    overlap = len(tokens & text) / max(len(tokens), 1)
    entity_hit = 1.0 if set(entities) & set(unit.entities) else 0.0
    return min(1.0, 0.7 * overlap + 0.3 * entity_hit)


def _cited(unit: Unit, reply: str) -> bool:
    blob = reply.lower()
    if unit.summary[:40].lower() in blob:
        return True
    return any(entity.lower() in blob for entity in unit.entities)


def _contradicts(left: Unit, right: Unit) -> bool:
    return bool(left.claim) and left.claim == right.claim and left.stance != right.stance


def _section(title: str) -> None:
    print(f"\n## {title}")


def _demo() -> None:
    mem = Engram(seed=7)
    ada = {
        "scope": "org/acme/project/billing/user/ada",
        "stage": "review",
        "task_type": "bugfix",
        "query": "invoice retry idempotency-key",
        "entities": ["invoice", "idempotency-key"],
    }
    lesson = (
        "Retrying an invoice write duplicates the row unless the request sends an Idempotency-Key."
    )

    _section("1. observe writes a candidate, and a repeat is a NOOP")
    first = mem.observe(
        {
            "trace_id": "t-1",
            "scope": "org/acme/project/billing",
            "entities": ["invoice", "idempotency-key"],
            "claim": "retry-key",
            "stance": "require",
            "text": lesson,
        }
    )
    again = mem.observe(
        {
            "trace_id": "t-1b",
            "scope": "org/acme/project/billing",
            "entities": ["invoice", "idempotency-key"],
            "claim": "retry-key",
            "stance": "require",
            "text": lesson,
        }
    )
    print(first)
    print(again)
    assert again["action"] == "NOOP"

    _section("2. a candidate is not injected")
    blocked = mem.recall(ada)
    print(blocked)
    assert blocked["units"] == []

    _section("3. a personal memory stays on its user")
    private = mem.observe(
        {
            "trace_id": "t-2",
            "scope": "org/acme/project/billing/user/bao",
            "kind": "preference",
            "entities": ["invoice"],
            "text": "Bao prefers short review comments on invoice changes.",
        }
    )
    mem.accept(private["unit_id"])
    mem.accept(first["unit_id"])
    hit = mem.recall(ada)
    print("ada sees", [item["id"] for item in hit["units"]])
    assert [item["id"] for item in hit["units"]] == [first["unit_id"]]

    _section("4. same rank goes to a human; docs outrank memory and the row stays, marked invalid")
    conflict = mem.observe(
        {
            "trace_id": "t-3",
            "scope": "org/acme/project/billing",
            "entities": ["invoice", "idempotency-key"],
            "claim": "retry-key",
            "stance": "skip",
            "text": "Always retry an invoice write. Do not send an Idempotency-Key.",
        }
    )
    print("same-rank conflict", conflict)
    assert conflict["action"] == "HUMAN_REVIEW"
    stale = mem.observe(
        {
            "trace_id": "t-4",
            "scope": "org/acme/project/other",
            "entities": ["retry-budget"],
            "claim": "retry-window",
            "stance": "forever",
            "text": "Keep trying with no limit.",
        }
    )
    overruled = mem.observe(
        {
            "trace_id": "doc-9",
            "scope": "org/acme/project/billing",
            "source": "docs",
            "authority": "docs",
            "entities": ["retry-budget"],
            "claim": "retry-window",
            "stance": "bounded",
            "text": "Stop after three attempts.",
        }
    )
    print("stale", stale["unit_id"], "docs", overruled)
    assert mem.units[stale["unit_id"]].status == "invalid"
    assert mem.units[stale["unit_id"]].invalidated_at is not None
    assert mem.units[first["unit_id"]].status == "active"

    _section("5. holdout injects nothing and ignores feedback")
    held = mem.recall(ada, arm="holdout")
    ignored = mem.feedback(held["recall_id"], {"polarity": 1, "reply": "idempotency-key invoice"})
    print(held["arm"], ignored)
    assert ignored["skipped"] == "holdout"
    assert mem.units[first["unit_id"]].used == 0

    _section("6. five cited accepts move the Beta; an uncited reply does not")
    lesson_id = first["unit_id"]
    last_id = hit["recall_id"]
    mem.feedback(last_id, {"polarity": 0.8, "reply": "Applied the Idempotency-Key lesson to the invoice write."})
    for n in range(4):
        rec = mem.recall(ada)
        last_id = rec["recall_id"]
        mem.feedback(last_id, {"polarity": 0.8, "reply": f"Applied the Idempotency-Key lesson, round {n}."})
    missed = mem.recall(ada)
    mem.feedback(missed["recall_id"], {"polarity": 0.8, "reply": "Shipped something else."})
    print(mem.explain(lesson_id, last_id))
    assert mem.units[lesson_id].helpful == 5
    assert mem.units[lesson_id].injected == 6  # first hit + four recalls + one miss; holdout excluded
    assert mem.units[lesson_id].used == 5

    _section("7. compile emits a shadow checklist only after the gate passes")
    compiled = mem.compile_checklist()
    print(compiled["artifact"])
    assert compiled["pass"] is True
    assert compiled["stage"] == "shadow"

    _section("8. explain answers origin, status, and the last score breakdown")
    print(mem.explain(lesson_id, last_id))
    print("\n".join(mem.events))
    print("\nok")


if __name__ == "__main__":
    _demo()
