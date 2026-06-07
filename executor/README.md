# executor — the engine-room action side

Reads the verified recipe layer (from `tensor-engine-knowledge/engines.db`), resolves a recipe
against the live rig, and (next increment) provisions / launches / measures it. Stdlib-only core;
providers bring their own deps at materialize-time.

## Run (no install)

```powershell
$env:ER_RECIPES_DB = "E:\AI\readouts\tensor-engine-knowledge\engines.db"   # or pass --db
python -m executor.cli rig                  # detected rig fingerprint + compat-band
python -m executor.cli list                 # executable recipes (kind / backend / verified)
python -m executor.cli show <slug>          # one recipe: baselines, constraints, artifacts, compensators, cross-KB techniques
python -m executor.cli preflight <slug>     # resolve + capability + resolvability + instance_id (NO side effects)
```
Or `pip install -e .` then use `er <cmd>`.

## What's built (this slice — all non-side-effecting)

| Module | Role |
|---|---|
| `recipes.py` | read-only seam: load a recipe + baselines/constraints/artifacts/compensators/cross-KB techniques |
| `rig.py` | detect the rig fingerprint (nvidia-smi + env); split into a semantic **compat-band** vs the exact build |
| `resolve.py` | fail-fast **preflight**: capability/constraint checks + the **resolvability floor** + `instance_id` (hashes the compat-band, not the literal driver) |
| `providers.py` | the 4-function provider contract over 7 backends; `match()` (read-only) implemented, side-effecting fns guarded |
| `cli.py` | `er` — rig / list / show / preflight |

## What's next (side-effecting — built per-backend, with care)

- **`provision`**: materialize → launch/produce/apply → measure, as a reconcile loop over the recipe's phases.
- **The lock + vendoring** (Goal 1): content-address the pins into a local store so `reproducible` is *earned*, not `index`-only.
- **The ledger + compensators**: persisted "what I provisioned" + newest-first, identity-verified undo (per-instance shims, never global PATH; `wsl --update` is human-gated).
- **The measure gate**: the recipe's `measured_axis` vs its model-keyed baseline + the golden, by a separate harness (EXTERNAL_VERIFIER).
- **The JSON/WS surface** the Control Panel (`../app/`) consumes.

The order is the design's: ship the **native-win-compile** provider first on the llama.cpp recipe (the rig's everyday driver, hands-on proven), because it exercises the whole contract on the lowest-risk engine.
