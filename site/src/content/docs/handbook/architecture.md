---
title: Architecture
description: How the engine-room executor is built — the read-only recipe seam, the rig fingerprint and compat-band, fail-fast preflight, the 7-backend provider contract, and the reconcile loop with ledger, compensators, and measure gate.
sidebar:
  order: 4
---

engine-room is the **action** half of the knowledge / action split. The core is **stdlib-only**
(`sqlite3`, `subprocess`, `urllib`, `hashlib`, `json`) — a provider may shell out to tools that
bring their own dependencies, but it does so *at materialize-time* as a subprocess and never adds a
Python import to the core. The executor lives under `executor/`; here is how the modules fit
together.

| Module | Role |
|--------|------|
| `recipes.py` | the read-only DB seam — load a recipe into dataclasses |
| `rig.py` | detect the rig fingerprint; split into a semantic compat-band vs the exact build |
| `resolve.py` | fail-fast preflight — constraint dispatch + the resolvability floor + `instance_id` |
| `providers.py` | the 4-function provider contract over 7 backends |
| `provision.py` | the reconcile loop — dry-run plan, ledger, compensators, measure gate |
| `cli.py` | `er` — the subcommands, read-only and side-effecting |

## The read-only recipe seam — `recipes.py`

The recipe layer is **trusted input**, and engine-room treats it as **read-only**. `recipes.py` is
the one place that opens the `engines.db` SQLite DB. It loads a recipe and its
baselines / constraints / artifacts / compensators / cross-KB techniques into plain dataclasses, and
exposes `list_recipes()` and `load_recipe(slug)`. Nothing in the executor writes the DB. This is
the seam that the future JSON/WS API replaces with a `GET` of the catalog — the rest of the
executor depends only on the dataclasses, not on SQLite.

## The rig fingerprint + compat-band — `rig.py`

`rig.py` detects the live rig via `nvidia-smi` and the environment: GPU, VRAM, `sm`, driver, CUDA
runtime and toolkit, OS surface, WSL2 version. The key design move is the **compat-band**: it splits
the *exact* build (the literal driver string) from a coarser **semantic band** —
`gpu_arch` / `cuda_toolkit` / `os_surface` / `driver_floor`.

The compat-band, not the literal driver, is what recipes resolve against and what feeds the
`instance_id`. So a **routine driver bump doesn't churn your instance identity** or invalidate a
model-keyed baseline — the band is stable across builds that are semantically equivalent. This is
why measured baselines stay valid across minor driver updates.

## Fail-fast preflight — `resolve.py`

`resolve()` is the non-side-effecting preflight. It does three things:

1. **Constraint evaluation via a dispatch registry.** Rather than an if-ladder, constraints route
   through an ordered `(matcher, handler)` table — adding a new constraint shape is a **one-line
   registration**. Handlers exist for `gpu_arch` thresholds, `cuda_toolkit==12.8`, the
   `cuda_toolkit>=13` conflict, the `wsl2>=2.7` defect floor, and the gradient-checkpointing launch
   flag. Each returns a `Check` with one of: `pass`, `halt` (ANDON), `warn`, `deferred`, or `note`.
2. **The resolvability floor.** Are the pinned artifacts reproducible *and* still installable? A pin
   recorded un-resolvable is a `halt`; an index-only pin is a `warn` that sets `reproducible: no`
   (Goal 1); all-vendored is a `pass`.
3. **The `instance_id`.** A 16-hex hash of `(slug + compat-band + backend)` — the join key to the
   measured baseline, stable across cosmetic rig changes.

### The `note` status — graceful degradation

The terminal fall-through in the constraint dispatch is the load-bearing honesty move. When no
handler matches an expression:

- An `abi_equal` constraint becomes **`deferred`** — a *deliberate* punt: a real check exists, but
  it runs at materialize once the pins are vendored (cross-artifact ABI).
- **Anything else** becomes **`note`** — the evaluator has *no rule* for that expression shape (a
  newer KB constraint than this executor knows). `note` is **non-blocking** and legibly distinct
  from both `deferred` (a planned re-check) and `pass` (an affirmative verdict). This prevents a
  newer recipe DB from either false-halting on ~dozens of expressions the executor doesn't model, or
  silently passing them. The CLI renders unknown statuses via `.get(status, status)`, so a future
  status the backend adds never crashes the command.

## The provider contract — `providers.py`

A *provider* is the one non-leaky seam over heterogeneous backends. The core carries **zero**
backend-specific code; it dispatches on `recipe.backend` to a `Provider` subclass. The contract is
**four functions**:

| Function | Side effects? | Role |
|----------|---------------|------|
| `match(recipe, rig) -> (bool, why)` | none (read-only) | can this backend run on this rig? Used by `preflight`. |
| `materialize(recipe, rig, instance)` | yes | download/vendor pins, extract into the per-instance dir (never global PATH). |
| `launch(recipe, rig, instance)` | yes | start the engine (e.g. a local `127.0.0.1` server). |
| `probe(recipe, rig, instance)` | reads a running endpoint | measure against the model-keyed baseline. |

**Seven backends** are registered, each with a `match()`:

`native-win-compile` · `wsl2-docker` · `portable-bundle` · `venv` · `onnx-compile` ·
`python-proxy` · `raw-cmd`

`match()` is the read-only rig-suitability check `preflight` relies on, implemented for every
backend. The side-effecting trio (`materialize` / `launch` / `probe`) is **reconcile-implemented
only for `native-win-compile`** — the rest raise `NotImplementedError` rather than half-doing
something irreversible, and the live path guards on `provider.reconcile_implemented`. A recipe whose
backend isn't registered falls back to `raw-cmd` (the opaque-launch escape hatch); a `modifier`
recipe resolves to `None` and inherits its target's backend at apply-time.

## The reconcile loop — `provision.py`

`provision.py` is the heart of the action side: `resolve → lock(+vendor) → materialize → launch →
measure → ready | halted`, run on a persisted ledger with newest-first, identity-verified
compensators.

### Dry-run by default

`plan()` builds the full step list — every side effect and its compensator — without running
anything. `run()` prints it (the `PLAN (DRY-RUN)` you see without `--execute`). Only `--execute`
(gated on `--model`) calls the side-effecting provider bodies. `run()` owns the ledger / run.log /
compensator bookkeeping; the provider owns the backend-specific materialize/launch/probe — a clean
split (the orchestration is backend-agnostic).

### The ledger + compensators

The ledger (a JSON file under `ER_HOME`, `~/.engine-room` by default) is written **before** any side
effect — so a crashed run still has a rollback handle. Each irreversible step appends a named
compensator (`rmtree`, `stop`). Teardown replays them **newest-first**.

The corrupt-ledger guard is deliberate: a missing ledger is the empty ledger, but a *corrupt* one is
**not** silently treated as empty — that would let the next write clobber every prior instance's
rollback handle. On a decode error the file is backed up and a structured `RuntimeError` is raised
(surfaced as `er: error: …`, exit 1), refusing to overwrite durable rollback state.

### Identity-verified, tri-state teardown

The stop compensator never kills blindly. It checks two things, each **tri-state** (`True` /
`False` / `None`-inconclusive):

- **Liveness** (`_alive`) parses the PID *column* of `tasklist` CSV — not a substring of the row, so
  a stray number in a memory column can't read as a PID. Inconclusive (probe failed) is **not**
  treated as "gone."
- **Identity** (`_exe_under`) uses PowerShell `Get-CimInstance Win32_Process` to confirm the exe
  path lives under our instance dir. Inconclusive is **not** treated as safe-to-kill.

Only a PID that is verifiably alive *and* verifiably ours is killed. The ledger state stays
honest — `rolled-back` only on a clean stop; `stop-failed` (instance dir kept) otherwise.

### The measure gate

The external-verifier gate after launch: a **256-token probe** judged against the recipe's
**model-keyed baseline** (selected by axis *and* model — an arbitrary other model's number is noise,
not a verdict), honoring the `bound` direction (`lower` = higher-is-better, `>=`; `upper` =
lower-is-better, `<=`). With no model-keyed baseline the gate is **record-only** and never halts.
It also enforces the **VRAM ceiling** via an `nvidia-smi` sample: over the ceiling → halt; *can't*
sample → **warn** (absence of evidence is not a pass). Off-baseline or over-ceiling → ANDON halt,
compensators fire, instance never marked ready.

## The Control Panel + the data contract

`app/` is a self-contained operator-UI prototype — mock data plus timer-simulated side effects,
faithful to the real JSON/WS API. It browses recipes and runs them with live telemetry, ANDON
halts, and rollback.

The durable contract between the executor and any UI is **not** the prototype's inline comment — it
is [`design/data-contract.md`](https://github.com/mcp-tool-shop-org/engine-room/blob/main/design/data-contract.md),
the source of truth for the **RECIPE** (immutable knowledge) and **INSTANCE** (mutable runtime)
shapes and the **event map** (UI event → guard → transition + real side effect). The handoff is
mechanical: replace the mock `RECIPES` array with a `GET` of the catalog, and replace the timer
simulation with a WebSocket stream of the documented events. When the prototype's comment and the
contract disagree, the contract wins, and the executor's actual surface (`providers.py`,
`resolve.py`) is the ground truth behind it.

## Extending it

Adding a backend is subclassing `Provider`, setting `backend` + `summary`, implementing `match()`,
and registering it in the `REGISTRY` tuple — that's the whole registration step. The side-effecting
trio goes in behind the ledger + compensator discipline. Adding a recipe kind extends the plan in
`provision.py` and picks the right measured axis and correctness gate. Full steps are in
[`CONTRIBUTING.md`](https://github.com/mcp-tool-shop-org/engine-room/blob/main/CONTRIBUTING.md).
