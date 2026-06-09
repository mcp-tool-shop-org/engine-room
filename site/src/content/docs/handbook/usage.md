---
title: Usage — the dry-run-first workflow
description: Take a recipe from preflight to a running, measured engine — read preflight statuses, read the dry-run plan and compensators, execute with the measure gate, then teardown.
sidebar:
  order: 2
---

engine-room is built to be run in a fixed order, each step safer than the next: **inspect →
preflight → dry-run plan → execute → teardown**. Nothing touches your rig until you pass
`--execute`. This page walks the full loop with real invocations and output.

Throughout, replace the example slug with one from `er list`. The examples below use a real
`launchable-server` recipe on the `native-win-compile` backend — the one combination with a live
provision path today.

## 1. Inspect a recipe — `er show`

Before resolving anything against your rig, read what a recipe *is*:

```
$ er show diffusion-engines-sdcpp-flux2-dev-q8-ram-offload-32gb
diffusion-engines-sdcpp-flux2-dev-q8-ram-offload-32gb
  <one-line summary>
  kind=launchable-server  backend=native-win-compile  axis=tok_s  verified=Y  executable=Y
  baselines:
    <model>: <value> <unit> (lower) [<compat-band>]
  constraints:
    [capability] gpu_arch>=sm_120
  artifacts: 1 (1 index-only)
  compensators:
    <step> -> <undo cmd> [<compensatable>]
  cross-KB techniques (training-knowledge):
    [<category>] <name>
```

This is the immutable knowledge artifact — baselines (the targets to hit), constraints (what the
rig must satisfy), artifacts (the pins), compensators (the declared undos), and cross-KB
techniques. The UI never mutates it; neither does `er`.

## 2. Preflight — `er preflight`

Preflight resolves the recipe against your live rig with **no side effects**. It runs the
capability/constraint checks, the resolvability floor, and computes the `instance_id` (the join key
to the measured baseline).

```
$ er preflight diffusion-engines-sdcpp-flux2-dev-q8-ram-offload-32gb
recipe   diffusion-engines-sdcpp-flux2-dev-q8-ram-offload-32gb  (launchable-server)
provider native-win-compile  match=YES — native-Windows Blackwell
instance bfd41f71595c84d8
checks:
  [warn] reproducibility  — 1/1 pins are index-only — not reproducible until vendored (Goal 1)

reproducible: no (vendor pins — Goal 1)
PREFLIGHT OK — no halts. (provision is the next executor increment)
```

### Reading the check statuses

Each check renders with a status glyph. The full vocabulary:

| Glyph | Status | Meaning |
|-------|--------|---------|
| `ok ` | `pass` | the constraint is satisfied against the live rig — an affirmative verdict. |
| `HALT` | `halt` | **ANDON**: the constraint is violated, or cannot be ruled out. Blocks provision. |
| `warn` | `warn` | soft signal — can't confirm but non-blocking (e.g. unknown toolkit, absent WSL). |
| `....` | `deferred` | a **deliberate punt** — a handler exists, but the real check happens at materialize (e.g. cross-artifact ABI, verified once pins are vendored). |
| `note` | `note` | the evaluator has **no rule** for this constraint expression — a newer KB constraint than this executor knows. Non-blocking; the signal is "a human / newer build should look." |

The distinction between **`note`** and **`deferred`** is deliberate and load-bearing: `deferred` is a
*planned* re-check; `note` means *this executor has no handler at all*. Neither blocks, but they mean
different things. A footer counts them so you can see at a glance what preflight could **not** decide.

### The resolvability floor

Below the constraint checks, preflight runs the **resolvability floor** — are the pinned artifacts
reproducible *and* still installable?

- An artifact recorded as un-resolvable (`resolvable_ok=0`) is a **`halt`** — the pin is known dead.
- An **index-only** pin produces a `warn` and sets `reproducible: no` — it's honest
  "not-yet-reproducible" (Goal 1). The recipe still runs; it's just not content-reproducible yet.
- All pins vendored/mirrored → `reproducibility pass` and `reproducible: yes`.

### Exit behavior

`er preflight` exits **0** when there are no halts (`PREFLIGHT OK`) and exits **2** on a blocking
halt (`PREFLIGHT HALT — N blocking: …`). That `2` is the same ANDON exit the live provision path
uses — it's the machine-readable signal that the pipeline stopped on a defect, not an ordinary error.

## 3. Dry-run plan — `er provision <slug>`

With preflight clean, see exactly what executing *would* do. **Without `--execute`, provision prints
the plan and touches nothing.** Every side-effecting step is flagged `!` and shows its
**compensator** (the named undo) and the honest post-rollback state:

```
$ er provision <slug>
recipe   <slug>  (launchable-server / native-win-compile)
instance bfd41f71595c84d8   dir C:\Users\you\.engine-room\instances\<slug>-bfd41f71595c84d8

PLAN (DRY-RUN):
   1.! [prepare   ] create per-instance dir
        $ mkdir …\instances\<slug>-bfd41f71595c84d8
        undo: rmtree …\instances\<slug>-bfd41f71595c84d8  =>  instance tree removed; nothing else touched
   2.! [materialize] vendor pin -> content-addressed cache
        $ download <pin-url> -> …\artifact-cache\<key> (+sha256 compute)
   3.! [materialize] extract into instance dir
        $ unzip …\artifact-cache\<key> -> …\instances\<slug>-…/
        undo: rmtree …\instances\<slug>-…  =>  instance tree removed
   4.! [activate  ] write per-instance launch shim (no global PATH)
        $ write …\instances\<slug>-…/run.cmd
        undo: del …/run.cmd  =>  shim removed; global PATH never touched
   5.! [activate  ] launch llama-server :8080 (+identity cookie)
        $ llama-server.exe -m <model> -ngl 99 -fa --host 127.0.0.1 --port 8080
        undo: stop iff pid alive AND exe under instance dir (identity-verified)  =>  our :8080 server stopped; other llama.cpp untouched
   6.  [measure   ] tok_s probe vs baseline + VRAM ceiling
        $ 256-tok probe; >= <value> <unit> on <model>; peak VRAM <= 31.8 GB

DRY-RUN — nothing executed. Re-run with --execute (+ --model <gguf>, optional --from <dir>).
```

Read this plan before every real run. Note the discipline baked into it:

- The **per-instance directory** lives under `ER_HOME` (`~/.engine-room` by default) — **never the
  global PATH**.
- A pin that is **not a direct file** (e.g. a releases *page* rather than a concrete asset) is
  flagged `[NOT a direct file -> will ANDON]` and will halt on execute rather than guess.
- The launched server binds **`127.0.0.1`** only, and its stop compensator is **identity-verified**.
- The **measure** step is read-only (no `!`).

If the recipe's backend or kind isn't implemented for live execute yet, the plan prints a clean
`BLOCKED: …` line instead of steps — it never half-does something irreversible.

## 4. Execute — `er provision <slug> --execute --model <gguf>`

`--execute` is **the only flag that touches the rig**, and it requires `--model <gguf>`. The
reconcile loop runs **materialize → launch → measure**, writing a ledger row *before* each side
effect:

```bash
er provision <slug> --execute --model C:\models\your-model.gguf
# optional:
#   --from <dir>   reuse an engine already on the rig (skip the download/vendor step)
#   --port <n>     127.0.0.1 port for the launched server (default 8080)
```

### The measure gate

This is the **external-verifier gate**. After launch, a **256-token probe** measures the running
server and judges it two ways:

- **Against the recipe's model-keyed baseline.** The verdict honors the baseline's `bound`
  direction: a `lower` bound (e.g. `tok/s`, higher-is-better) passes on `measured >= value`; an
  `upper` bound (e.g. `s/img`, lower-is-better) passes on `measured <= value`. The baseline is
  selected by *both axis and model* — comparing tok/s against some other model's number is noise,
  so if there's no model-keyed baseline the gate is **record-only** (it never halts).
- **Against the VRAM ceiling.** Peak VRAM is sampled via `nvidia-smi`. Over the ceiling → halt. If
  VRAM can't be sampled, the gate **warns** rather than silently green-lighting — absence of
  evidence is not a pass.

Off the wrong side of the baseline or over the ceiling → **ANDON halt**: the run stops, compensators
fire newest-first, the instance is **never marked ready**, and `er` exits **2**. On success:

```
READY — <slug> on :8080 (instance bfd41f71595c84d8). `er teardown bfd41f71595c84d8` to roll back.
```

## 5. Check state — `er status`

`er status` reads the persisted ledger and shows what you've provisioned:

```
$ er status
  bfd41f71595c84d8  ready        <slug>  pid=12345 :8080  42.7 tok/s
```

Each row shows the instance id, state, recipe, and — for a running server — its pid, port, and
measured throughput. With nothing provisioned: `no provisioned instances`.

## 6. Teardown — `er teardown <instance>`

Roll back a provisioned instance. Compensators run **newest-first** and each stop is
**identity-verified**:

```bash
er teardown bfd41f71595c84d8
```

Teardown only kills a PID that is **alive** *and* whose executable lives **under our instance
directory**, so it will never kill an unrelated `llama.cpp` or a recycled PID. The ledger state it
records is **honest**: it becomes `rolled-back` only when the server is verifiably stopped or
already gone. If liveness or identity is *inconclusive*, it records `stop-failed`, leaves the
instance directory in place (so it doesn't destroy a possibly-live orphan's dir), and tells you a
manual check is needed.

## The loop, end to end

```bash
er rig                                          # 0. confirm the rig
er list                                         # 1. find a slug
er show <slug>                                  # 2. read the recipe
er preflight <slug>                             # 3. resolve, no side effects
er provision <slug>                             # 4. dry-run plan + compensators
er provision <slug> --execute --model <gguf>    # 5. live: materialize → launch → measure
er status                                       # 6. confirm it's ready
er teardown <instance>                          # 7. roll back (newest-first, identity-verified)
```

For the exact flag and exit-code contract, see the [Command Reference](/handbook/reference/).
