# Contributing to engine-room

engine-room is the **action** half of a deliberate split: it resolves a verified recipe against
the live rig, materializes it, launches/measures it, and rolls it back. The recipes themselves
(the **knowledge** half) live in the separately-provided tensor-engine-knowledge DB and are out
of scope for this repo — see [`README.md`](README.md).

This guide covers the one extension point most contributions touch: **adding a provider** (a new
backend) or wiring up **a new recipe kind**.

## Ground rules

- **The core stays stdlib-only.** The executor core (`recipes.py`, `rig.py`, `resolve.py`,
  `providers.py`, `provision.py`, `cli.py`) imports only the Python standard library
  (`sqlite3`, `subprocess`, `urllib`, `hashlib`, `json`, …). A provider may shell out to tools
  that bring their own dependencies, but it does that **at materialize-time** as a subprocess —
  it never adds a Python import dependency to the core.
- **Dry-run is the default and must stay side-effect-free.** `er provision <slug>` (no
  `--execute`) prints the full plan — every side effect and its named compensator — and touches
  nothing. Only `--execute` (gated behind `--model`) acts on the rig.
- **Every irreversible step needs a named, honest compensator.** It is recorded on the ledger
  *before* it runs, and teardown is newest-first and identity-verified. Do not add a side effect
  without its undo.
- **Verify before you push:** `python -m unittest discover tests` (stdlib, no install). Keep the
  existing tests green.

## The provider contract (4 functions)

A *provider* is the one non-leaky seam over heterogeneous backends. The core carries **zero**
backend-specific code; it dispatches on `recipe.backend` to a `Provider` subclass. The contract
is four functions (see [`executor/providers.py`](executor/providers.py)):

| Function | Side effects? | Role |
|---|---|---|
| `match(recipe, rig) -> (bool, why)` | **none** (read-only) | can this backend run on this rig? Used by `preflight`. |
| `materialize(recipe, rig, instance)` | yes | download/vendor pins, extract into the per-instance dir (never global PATH). |
| `launch(recipe, rig, instance)` | yes | start the engine (e.g. a local `127.0.0.1` server). |
| `probe(recipe, rig, instance)` | reads a running endpoint | measure against the recipe's model-keyed baseline. |

`match()` is implemented for every backend in this first slice (it's the read-only rig-suitability
check `preflight` relies on). `materialize` / `launch` / `probe` are the **side-effecting** next
increment — they raise `NotImplementedError` until built per-backend with the
lock + ledger + compensators, rather than half-doing something irreversible.

The seven backends already registered (with `match()`):

`native-win-compile` · `wsl2-docker` · `portable-bundle` · `venv` · `onnx-compile` ·
`python-proxy` · `raw-cmd`

The live provisioning path (`provision.py`) is currently implemented for the
**`native-win-compile`** backend on the **`launchable-server`** kind (llama.cpp) — the
lowest-risk engine that exercises the whole contract. Other `backend` / `kind` combinations
return a clean `BLOCKED` in the plan rather than running.

## Add a new backend (provider)

1. **Subclass `Provider`** in [`executor/providers.py`](executor/providers.py). Set `backend`
   (the exact string that appears in the recipe DB's `backend_kind`) and a one-line `summary`.

   ```python
   class MyBackend(Provider):
       backend = "my-backend"
       summary = "what this lane is (the engines it covers)"

       def match(self, recipe, rig):
           # read-only: return (False, "why not") to fail preflight, else (True, "why")
           if rig.os_surface != "linux":
               return False, "needs Linux"
           return True, "ok"
   ```

2. **Register it** in the `REGISTRY` tuple at the bottom of the module — that's the whole
   registration step; `provider_for(recipe)` looks the backend up there:

   ```python
   REGISTRY = {p.backend: p() for p in (
       NativeWinCompile, Wsl2Docker, PortableBundle, Venv, OnnxCompile, PythonProxy, RawCmd,
       MyBackend,                # <- add here
   )}
   ```

   A recipe whose `backend` isn't in the registry falls back to `raw-cmd` (the opaque-launch
   escape hatch). A `modifier`-kind recipe resolves to `None` — it inherits its target recipe's
   backend at apply-time and has no provider of its own.

3. **Implement the side-effecting trio** (`materialize` / `launch` / `probe`) — but only behind
   the ledger + compensators discipline in [`executor/provision.py`](executor/provision.py).
   Until then they should keep raising `NotImplementedError`. Wire the live path the way
   `native-win-compile` is wired in `provision.py`: ledger row *before* any side effect, a
   per-instance dir (never global PATH), identity-verified teardown, and the measure gate.

## Add a new recipe kind

There are four kinds — `launchable-server`, `batch-producer`, `modifier`, `router-fleet`. Only
`launchable-server` has a live provision path today. To add a kind's live behavior:

- Extend the plan in `provision.py` so the kind no longer returns the
  `kind '<kind>' not in this slice` blocker, and emit the kind-appropriate steps + compensators.
- Pick the right measured axis (`tok_s`, `bits_per_weight`, `delta_pct`, `fleet_health`) and a
  correctness gate; honor the baseline's `bound` direction (`lower` = higher-is-better,
  `upper` = lower-is-better) in the verdict.
- Mirror the kind's UI shape in the data contract
  ([`design/data-contract.md`](design/data-contract.md)) so the Control Panel can render it.

## Where to look

| File | What it owns |
|---|---|
| [`executor/recipes.py`](executor/recipes.py) | the read-only DB seam (loads a recipe into dataclasses) |
| [`executor/rig.py`](executor/rig.py) | rig fingerprint + the semantic compat-band |
| [`executor/resolve.py`](executor/resolve.py) | preflight: constraint evaluator + resolvability floor + `instance_id` |
| [`executor/providers.py`](executor/providers.py) | the 4-function provider contract + the `REGISTRY` |
| [`executor/provision.py`](executor/provision.py) | the reconcile loop, ledger, and newest-first compensators |
| [`executor/cli.py`](executor/cli.py) | the `er` subcommands |
| [`design/data-contract.md`](design/data-contract.md) | the recipe + instance shapes + event map (UI source of truth) |

## Reporting security issues

Don't open a public issue for a vulnerability — see [`SECURITY.md`](SECURITY.md) for the private
disclosure route.
