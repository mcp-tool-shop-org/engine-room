# executor — the engine-room action side

Reads the verified recipe layer (from `tensor-engine-knowledge/engines.db`), resolves a recipe
against the live rig, and provisions / launches / measures it. Stdlib-only core; providers
bring their own deps at materialize-time.

## Getting the recipe layer

This repo is the **action** half. The recipes are the **knowledge** half — a
separately-provided, verified artifact, the **tensor-engine-knowledge** recipe DB
(`engines.db`). engine-room reads it **read-only** and never writes it.

- `er rig` needs **no** recipe DB — it reads only the live hardware, so it works immediately
  after cloning.
- Everything else (`list` / `show` / `preflight` / `provision`) needs the DB. Point at it with
  `$env:ER_RECIPES_DB` **or** `--db <path>`. With neither set, `er` falls back to
  `../../readouts/tensor-engine-knowledge/engines.db` (relative to the repo).
- DB missing → a clear error (`recipe DB not found: … — set $ER_RECIPES_DB or pass --db`), never
  a stack trace.

## Run (no install)

```powershell
$env:ER_RECIPES_DB = "E:\AI\readouts\tensor-engine-knowledge\engines.db"   # or pass --db
python -m executor.cli rig                  # detected rig fingerprint + compat-band
python -m executor.cli list                 # executable recipes (kind / backend / verified)
python -m executor.cli show <slug>          # one recipe: baselines, constraints, artifacts, compensators, cross-KB techniques
python -m executor.cli preflight <slug>     # resolve + capability + resolvability + instance_id (NO side effects)
python -m executor.cli provision <slug>     # DRY-RUN plan: every step + its compensator (NO side effects)
python -m executor.cli provision <slug> --execute --model <gguf>   # live: materialize -> launch -> measure
python -m executor.cli status               # the ledger: provisioned instances + state + measured tok/s
python -m executor.cli teardown <instance>  # roll back an instance (compensators, newest-first, identity-verified)
```
Or `pip install -e .` then use `er <cmd>`.

## What's built

| Module | Role |
|---|---|
| `recipes.py` | read-only seam: load a recipe + baselines/constraints/artifacts/compensators/cross-KB techniques |
| `rig.py` | detect the rig fingerprint (nvidia-smi + env); split into a semantic **compat-band** vs the exact build |
| `resolve.py` | fail-fast **preflight**: capability/constraint checks + the **resolvability floor** + `instance_id` (hashes the compat-band, not the literal driver) |
| `providers.py` | the 4-function provider contract over 7 backends; `match()` (read-only) implemented, side-effecting fns guarded per-backend |
| `provision.py` | the reconcile loop — **dry-run by default** (the full plan + every compensator), wired live `--execute`; the ledger + newest-first identity-verified compensators + the tok/s measure gate (see below) |
| `cli.py` | `er` — rig / list / show / preflight (read-only) · provision / teardown / status (side-effecting, gated) |

The provisioner is implemented for the first backend — **native-win-compile** on the
`launchable-server` (llama.cpp) recipe (the rig's everyday driver, hands-on proven), because
it exercises the whole contract on the lowest-risk engine. It already does:

- **`provision`** — materialize → launch → measure as a reconcile loop. Dry-run prints every
  side effect and its compensator; `--execute --model <gguf>` runs it for real (`--from <dir>`
  reuses an engine already on the rig, skipping the download).
- **The ledger + compensators** — a persisted "what I provisioned," written *before* any side
  effect, with newest-first, identity-verified undo (per-instance dirs + a `run.cmd` shim,
  never global PATH; teardown only stops a server whose exe lives under our instance dir).
- **The measure gate** — a 256-token probe against the recipe's model-keyed baseline
  (bound-direction aware: lower-bound for `tok/s`, upper-bound for `s/img`) + the VRAM ceiling;
  off the wrong side of the baseline or over the ceiling → ANDON halt + rollback.

## Verify it works

The core is stdlib-only, so there's nothing to install — run the test suite straight from a
clone:

```powershell
python -m unittest discover tests        # from the repo root; no pip, no recipe DB needed
```

A green run proves the three load-bearing seams without touching your rig:

- **the read/resolve seam** — a recipe loads from the DB into the dataclasses and resolves
  against a faked rig (capability + resolvability floor + a stable `instance_id`).
- **the constraint evaluator** — the `gpu_arch` / `cuda_toolkit` / `conflicts_when` /
  `defect_floor` checks produce the right `pass` / `halt` / `warn` / `deferred` verdicts, and an
  *unknown* constraint expression degrades honestly to a `note` (legibly distinct from a
  deliberate `deferred`) instead of crashing or silently passing.
- **the provision honesty guarantees** — dry-run is side-effect-free; the ledger is written
  *before* any side effect; teardown is identity-verified and newest-first; the measure gate
  uses real token counts and an honest VRAM verdict; a corrupt ledger refuses to clobber
  rollback handles.

The tests fake the rig and the recipe DB (no GPU, no network, no `--execute`), so a green run is
fully reproducible on any machine.

## What's next

- **The lock + vendoring** (Goal 1): content-address the pins into a local store and reject
  placeholder shas, so `reproducible` is *earned*, not `index`-only. (Today an unpinned/`<sha256>`
  artifact is accepted — the honest gap.)
- **The remaining backends/kinds**: the other 6 providers and the `batch-producer` /
  `modifier` / `router-fleet` kinds (`wsl --update`-class steps stay human-gated).
- **The JSON/WS surface** the Control Panel (`../app/`) consumes — the recipe + instance shapes
  and the event map are the durable contract in
  [`../design/data-contract.md`](../design/data-contract.md) (the source of truth the prototype's
  `app/data.js` comment drifts from).

## Adding a provider or recipe

The provider seam and registration steps live in [`../CONTRIBUTING.md`](../CONTRIBUTING.md) —
the 4-function contract (`match` / `materialize` / `launch` / `probe`) and how to register a new
backend or recipe kind.
