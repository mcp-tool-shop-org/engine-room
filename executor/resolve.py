"""Resolve a recipe against the live rig — the fail-fast PREFLIGHT (non-side-effecting).

Three checks, in the design's spirit:
  1. capability / constraints — evaluate recipe_constraints against the rig BEFORE any long work
     (a HALT here is ANDON: stop before compiling/downloading).
  2. resolvability floor — are the pinned artifacts reproducible? `store_expect='index'` is honest
     "not-yet-reproducible" (Goal 1: vendoring earns reproducibility); a recorded resolvable_ok=0 HALTs.
  3. instance_id — hash of (slug + compat-band + backend): the join key to the measured baseline.
     Hashes the semantic compat-BAND, not the literal driver, so a routine driver bump doesn't churn it.
This module performs NO side effects.
"""
from __future__ import annotations
import hashlib, json, re
from dataclasses import dataclass, field
from .recipes import Recipe
from .rig import Rig


@dataclass
class Check:
    name: str; status: str; detail: str
    # status set (the full vocabulary the preflight emits):
    #   pass     — the constraint is satisfied against the live rig.
    #   halt     — ANDON: the constraint is violated (or cannot be ruled out); blocks provision.
    #   warn     — soft signal: can't confirm, but non-blocking (e.g. unknown toolkit, absent WSL).
    #   deferred — a DELIBERATE punt: a handler exists but the real check happens at materialize
    #              (abi_equal cross-artifact ABI is verified once the pins are vendored).
    #   note     — the evaluator has NO rule for this expr shape (a newer KB constraint than this
    #              executor knows). Legibly distinct from 'deferred' (which is a planned re-check)
    #              and from 'pass' (which is an affirmative verdict). Non-blocking; the signal is
    #              "this executor has no handler — a human/newer build should look."

@dataclass
class ResolveResult:
    recipe: str; backend: str | None; instance_id: str
    ok: bool
    checks: list[Check] = field(default_factory=list)
    reproducible: bool = False
    notes: list[str] = field(default_factory=list)

    @property
    def halts(self):
        return [c for c in self.checks if c.status == "halt"]


def _ver(s: str | None):
    if not s:
        return None
    m = re.findall(r"\d+", s)
    return tuple(int(x) for x in m) if m else None


def _sm_num(s: str | None) -> int | None:
    """Numeric part of an sm_NNN string (sm_120 -> 120). None if not an sm_ token."""
    if not s:
        return None
    m = re.search(r"sm_?(\d+)", s)
    return int(m.group(1)) if m else None


# --------------------------------------------------------------- constraint handlers
# Each handler takes (constraint, rig) and returns a Check. A small dispatch registry
# (_HANDLERS) maps a `matcher(constraint) -> bool` to its handler, so adding a new
# constraint shape is a ONE-LINE registration at the bottom of the table — not another
# branch grafted onto an if-ladder (BACKEND-B-002). The terminal fall-through is
# _no_handler() below: an abi_equal is a DELIBERATE punt ('deferred', re-checked at
# materialize); ANY other unmatched expr is a 'note' ('this executor has no rule for it').


def _h_gpu_arch(c, rig: Rig) -> Check:
    # honor the sm_NNN threshold + comparator in the expr — don't hardcode sm_120
    e = c.expr
    floor = _sm_num(e)
    have = _sm_num(rig.sm)
    if floor is None:
        return Check(e, "warn", f"unparseable gpu_arch expr; rig sm={rig.sm}")
    if have is None:
        # ANDON: unknown rig arch can't clear an arch floor (absence of evidence != safety)
        return Check(e, "warn", f"rig sm unknown — can't confirm gpu_arch{'>=' if '>=' in e else ''}sm_{floor}")
    if ">=" in e:
        ok = have >= floor
    elif ">" in e:
        ok = have > floor
    elif "==" in e:
        ok = have == floor
    else:
        ok = have == floor
    return Check(e, "pass" if ok else "warn", f"rig sm={rig.sm} vs floor sm_{floor}")


def _h_toolkit_12_8(c, rig: Rig) -> Check:
    e = c.expr
    if rig.cuda_toolkit is None:
        return Check(e, "warn", "no nvcc on PATH — can't confirm toolkit 12.8 (wheels may bundle it)")
    return Check(e, "pass" if rig.cuda_toolkit.startswith("12.8") else "halt", f"toolkit={rig.cuda_toolkit}")


def _h_cuda_conflict(c, rig: Rig) -> Check:
    # the live rig has no nvcc (toolkit None) but DOES run CUDA UMD 13.x — evaluate the
    # conflict against BOTH fields, taking whichever is present / the max.
    e = c.expr
    tk = _ver(rig.cuda_toolkit)
    rt = _ver(rig.cuda_runtime)
    present = [v for v in (tk, rt) if v is not None]
    if not present:
        # ANDON: neither field known — can't clear a conflict; absence of evidence != safety
        return Check(e, "halt", "no cuda_toolkit/cuda_runtime detected — can't rule out the 13.x conflict")
    worst = max(present)
    hit = worst >= (13, 0)
    return Check(e, "halt" if hit else "pass",
                 f"toolkit={rig.cuda_toolkit} runtime={rig.cuda_runtime}")


def _h_wsl2_floor(c, rig: Rig) -> Check:
    e = c.expr
    wv = _ver(rig.wsl2_version)
    if wv is None:
        # unknown wsl2 -> warn (not halt): an absent WSL pathway means the wsl2 defect can't
        # apply, whereas an unknown cuda runtime under conflicts_when -> halt because a live
        # runtime is definitely present and we cannot rule the conflict out.
        return Check(e, "warn", "WSL2 not detected")
    return Check(e, "pass" if wv >= (2, 7, 0) else "halt", f"wsl2={rig.wsl2_version}")


def _h_gradient_checkpointing(c, rig: Rig) -> Check:
    return Check(c.expr, "warn", "launch-flag requirement — pass --gradient_checkpointing (else 32 GB spill)")


def _no_handler(c, rig: Rig) -> Check:
    """Terminal fall-through: no registered handler matched this constraint.

    The split (BACKEND-B-001) — keep 'deferred' ONLY for a deliberate punt:
      * abi_equal is a real-but-later check (cross-artifact ABI verified once pins are vendored
        at materialize) -> 'deferred'.
      * EVERYTHING else with no handler is a KB expr shape this executor has no rule for ->
        'note' (legibly 'evaluator has no rule', NOT a planned re-check, NOT a pass). 'note' is
        non-blocking: conflicts_when fall-throughs are NOT escalated to warn/halt (would false-halt
        ~29 KB rows the evaluator simply doesn't model yet); the legible signal is 'note'.
    """
    if c.ctype == "abi_equal":
        return Check(c.expr, "deferred", "cross-artifact ABI — verified at materialize")
    return Check(c.expr, "note", c.reason or "no evaluator rule for this constraint expr")


# Dispatch registry: ordered (matcher, handler) pairs. First matcher to return True wins; if
# none match, _no_handler() runs. Registering a new constraint shape == appending one line here.
_HANDLERS: list[tuple] = [
    (lambda c: c.ctype == "capability" and "gpu_arch" in c.expr,        _h_gpu_arch),
    (lambda c: "cuda_toolkit==12.8" in c.expr,                          _h_toolkit_12_8),
    (lambda c: c.ctype == "conflicts_when" and "cuda_toolkit>=13" in c.expr, _h_cuda_conflict),
    (lambda c: c.ctype == "defect_floor" and "wsl2>=2.7" in c.expr,     _h_wsl2_floor),
    (lambda c: "gradient_checkpointing" in c.expr,                      _h_gradient_checkpointing),
]


def _eval_constraint(c, rig: Rig) -> Check:
    for matcher, handler in _HANDLERS:
        if matcher(c):
            return handler(c, rig)
    return _no_handler(c, rig)


def resolve(recipe: Recipe, rig: Rig) -> ResolveResult:
    band = rig.compat_band()
    raw = json.dumps({"slug": recipe.slug, "backend": recipe.backend, "band": band}, sort_keys=True)
    iid = hashlib.sha256(raw.encode()).hexdigest()[:16]
    res = ResolveResult(recipe=recipe.slug, backend=recipe.backend, instance_id=iid, ok=True)

    # 1. constraints
    for c in recipe.constraints:
        res.checks.append(_eval_constraint(c, rig))

    # 2. resolvability floor
    pins = recipe.artifacts
    if pins:
        index_only = [a for a in pins if a.store_expect == "index"]
        dead = [a for a in pins if a.resolvable_ok == 0]
        if dead:
            res.checks.append(Check("resolvability", "halt", f"{len(dead)} pinned artifact(s) recorded un-resolvable"))
        res.reproducible = len(index_only) == 0 and not dead
        if index_only:
            res.checks.append(Check("reproducibility", "warn",
                f"{len(index_only)}/{len(pins)} pins are index-only — not reproducible until vendored (Goal 1)"))
        else:
            res.checks.append(Check("reproducibility", "pass", "all pins vendored/mirrored"))
    else:
        res.notes.append("no pinned artifacts recorded")

    # 3. verdict
    res.ok = len(res.halts) == 0
    if recipe.kind == "modifier":
        res.notes.append("modifier — inherits its target recipe's backend at apply-time")
    return res
