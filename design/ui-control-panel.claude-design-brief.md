# Claude Design brief — engine-room Control Panel

> Paste this into a new Claude Design project file. Target output: **ONE self-contained,
> offline HTML file** (embedded CSS + JS + mock data), navigable in the live canvas, with
> the lifecycle simulated on timers so every state is demoable WITHOUT a backend. It should
> be Claude-Code-handoff-ready (clean component structure + a documented data contract +
> the event map, so Claude Code can later wire it to the real executor).

---

## Build: the engine-room Control Panel

You are designing the product face of **engine-room** — a recipe-driven local-AI **engine provisioner**. A solo operator (a game-studio director, power-user but NOT a sysadmin) uses it to browse a catalog of verified "engine recipes," configure one, and **provision → launch → measure** it on their own single-GPU rig "on the fly," with live telemetry and safe rollback. **Usability is the #1 goal:** make a heterogeneous, side-effecting, partly-irreversible process feel safe, legible, and fast.

Deliver a **single self-contained HTML file** (no external resources; embedded JS/CSS/fonts-as-system-stack; mock data inline). The lifecycle must be simulated with `setTimeout` so a click-through demos materialize → measure → ready/halt without a server.

### Brand (match the studio's "readouts" line)
- Navy ink (`#0f1b2d`-ish) on a deep blue-gradient; **dark default + a light toggle**.
- A single logo/wordmark "engine-room" top-left; no breadcrumb/wordmark redundancy.
- Dense-but-calm. Monospace for tok/s, VRAM, ports, hashes. This is an instrument panel, not a marketing page.

---

## Domain you must model

engine-room executes **recipes**. A recipe is a verified spec for standing up ONE AI engine on this rig. Recipes are **polymorphic — four kinds, each a different UI shape:**

| `recipe_kind` | What it does | Primary action | Terminal "good" state | Telemetry axis |
|---|---|---|---|---|
| `launchable-server` | starts a long-lived server on a port (llama.cpp, vLLM) | **Launch** / Stop | `ready` (serving + baseline passed) | tok/s (live) |
| `batch-producer` | runs, **writes an artifact, exits** (GGUF quantize, LoRA train) | **Produce** | `done` (file written + golden passed) | bits/weight, build-wall-clock |
| `modifier` | a drop-in **overlay** that mutates another recipe (SageAttention) — no port, no server of its own | **Apply to <base>** | `applied` (delta measured) | delta-% vs the base |
| `router-fleet` | a front that **routes to other recipes** (LiteLLM, llama-swap) | **Bring up** | `ready` (router up + upstreams healthy) | per-child health |

**Two trust signals, shown as badges on every recipe** (orthogonal — show both):
- `verified` — the recipe's claims are grounded in a cited source (green check / gray "unverified").
- `resolvable` — its pinned artifacts still install today (green / **red "won't resolve"** with the failing pin / gray "unchecked"). A recipe can be verified-but-unresolvable; surface that contradiction loudly.
- Plus `commercial_use` (yes / conditional / no) — a license chip.

**Lifecycle state machine** (drives everything):
`idle → resolving → preflight → materializing → (activating | producing | applying | bringing-up) → measuring → ready | halted`, plus `tearing-down`, `rolling-back`, `stale`.

**ANDON (stop-the-line):** any step can **halt**. A halt is loud, names the cause **contrastively** ("you expected it to launch — it halted because the pinned wheel returns 404; re-resolve?"), and offers the **recovery action** inline. Never a silent failure, never a raw stack.

**Compensators (safe rollback):** every destructive step has a **named undo + an honest post-state**. Some are `human-gated` (e.g. a machine-global `wsl --update` that can't be scoped to one engine) — those require an explicit modal that names the **blast radius** before proceeding. Show the undo + post-state in any confirm dialog.

**Rig reality:** ONE GPU, finite VRAM (e.g. 32 GB). Telemetry must show **VRAM vs the ceiling** and **the live axis vs the baseline bound** (green inside, red breached).

---

## Mock data (embed this; make the prototype alive)

Five recipes spanning all four kinds — grounded in real measured numbers:

1. **`llama.cpp + llama-swap`** — `launchable-server`, backend `native-win-compile`, axis `tok_s`. verified ✓, resolvable ✓, commercial **yes**. Baselines (model-keyed!): Qwen3-30B-A3B → **334 tok/s** (lower-bound), Qwen3-4B → 286. compat-band `driver≥R570; cuda 12.8; sm_120`. Pins: a vendored release-asset zip. Compensators: per-instance shim (NOT global PATH), identity-verified stop.
2. **`vLLM (WSL2/Docker)`** — `launchable-server`, backend `wsl2-docker`, axis `tok_s`. verified ✓, resolvable ✓. Baseline: Qwen2.5-7B-AWQ → **4138 tok/s @ concurrency-64**. **Has a `human-gated` compensator** (provisioning the WSL2 distro / `wsl --update` is machine-global) — use this one to demo the human-gate modal. Also a `defect_floor` constraint: `wsl2 ≥ 2.7.0` (WDDM graph-capture hang) — demo an ANDON halt when violated.
3. **`GGUF imatrix quantize`** — `batch-producer`, backend `venv`, axis `bits_per_weight`. Produces a `.gguf`. Golden = `file-hash` + perplexity tolerance. No port. Use to show the producer shape (progress → file written, NOT a server).
4. **`SageAttention 2.2`** — `modifier`, **backend null** ("inherits target"), axis `delta_pct`. Modifies `comfyui-zimage-turbo`; delta **+8.3% @1024², +29.3% @2048²**. Constraint `conflicts_when backend==…fp16_cuda` (hard-crashes). resolvable ✓ (vendored community wheel). Use to show the modifier shape (Apply-to-base + a delta gauge, no port, no self-baseline).
5. **`LiteLLM proxy`** — `router-fleet`, backend `python-proxy`. `depends_on: [llama.cpp+llama-swap, vLLM]` with a start-order. Use to show the fleet shape (per-upstream health, "won't go ready until upstreams healthy," refcounted teardown).

Make one recipe (e.g. an extra cu128 one) **`resolvable: false`** to demo the red badge + the re-resolve recovery.

---

## Event-handler map  ← design to this explicitly

Realize these as actual interactions. (In the prototype, "side effect" is simulated with a timer + a fixture; document the *real* intended side effect in a comment so Claude Code can wire it.)

| Event | Source | Guard / precondition | Transition + side effect | UI feedback |
|---|---|---|---|---|
| `selectRecipe` | user (catalog click) | — | open detail pane | slide-in detail; badges, baseline, sources, "what this will do" |
| `changeVariant` / `changeParam` | user (form) | param is `default`-tier (locked = read-only); value satisfies `constraints` | update draft config | live-validate; **disable Launch + show why** if a constraint fails (e.g. cuda 13.x conflict) |
| `preflight` | user (Preflight btn) | recipe selected | `idle→resolving→preflight`; resolve lock + capability + **resolvability** check | progress chips ("resolving lock", "checking artifacts"); **fail fast** before any long work |
| `resolvabilityResult` | stream | — | if fail → `halted` | red ANDON: which pin 404'd + **[Re-resolve]** |
| `launch` / `produce` / `apply` / `bringUp` | user (primary action) | preflight passed | `preflight→materializing→…→measuring` | per-phase progress; the button morphs to the kind's verb; **the panel never blocks** (other recipes stay interactive) |
| `materializeProgress` | stream | — | advance phase | step list with check/spinner; show the active `recipe_step` cmd |
| `humanGateRequired` | stream | step is `human-gated` | pause at gate | **modal**: names the blast radius ("changes the WSL kernel machine-wide; may reboot") + **[Approve] / [Cancel]** |
| `approveGate` | user (modal) | gate shown | resume | toast "approved by you"; continue |
| `baselineSample` | stream (repeating) | state `measuring` | update telemetry | **live gauges**: axis vs baseline bound, VRAM vs ceiling, temp/power — green inside, **red breached** |
| `goldenResult` | stream | measure done | pass→continue; fail→`halted` | golden pass/fail (per-modality: numeric / perceptual / file-hash / WER) |
| `andonHalt` | stream | any defect | `*→halted` | **loud, contrastive** banner: "expected X; halted because Y" + the recovery action button |
| `stop` | user | state `ready`/`measuring` | `→tearing-down→idle` | confirm only if irreversible; identity-verified ("stopping engine-room's server, not your other one") |
| `teardown` | user | provisioned | run compensators **newest-first** | each compensator row shows undo + **honest post-state**; progress |
| `rollback` | user (after halt) | ledger non-empty | `halted→rolling-back→idle` | replays compensators from the ledger; non-compensatable steps shown as "named, owner: you" |
| `reResolve` | user (stale/404) | `stale` or resolvability-fail | re-resolve → **new instance** → re-measure | shows lineage "old → new (cu128 channel gone → cu130)" |
| `upstreamHealthChanged` | stream (router) | kind `router-fleet` | recompute readiness | per-child health dots; router not `ready` until all required upstreams green |
| `driftDetected` | stream | re-measure outside compat band | `ready→stale` | "driver bumped 581→610.47; perf within 5%? re-probe" (cheap re-probe, not full re-measure) |
| `filter` / `search` | user | — | filter catalog | by kind / lane / backend / verified / resolvable / commercial; instant |
| `toggleTheme` | user | — | dark↔light | persists |

---

## Usability requirements (non-negotiable)

- **Progressive disclosure:** catalog → recipe detail → configure → run. Don't dump all fields at once.
- **Trust first:** the `verified` + `resolvable` + license badges are visible in the catalog AND detail, with tooltips that cite the source / name the failing pin.
- **Polymorphic, not one-size:** the detail pane + primary action + telemetry **change shape per `recipe_kind`** (server has a port + Launch/Stop; producer has an output path + Produce; modifier has Apply-to-base + a delta gauge; router has a fleet table).
- **ANDON is loud + actionable:** contrastive cause + a one-click recovery; never a dead-end.
- **Destructive actions name their undo:** confirm dialogs show the compensator's command + honest post-state; human-gated ops name the blast radius.
- **Live telemetry as instruments:** axis-vs-baseline and VRAM-vs-ceiling as gauges, color + numeric (not color alone).
- **All states designed:** loading, empty (no recipes), error, and **offline/read-only** (no executor connected → the panel becomes a recipe *browser* — degrade gracefully; this doubles as the everyday "what can I run?" view).
- **Accessible:** full keyboard operation, focus management, ARIA roles, and signals that don't rely on color alone.
- **Non-blocking:** one recipe's long provision must not freeze the panel; show its progress in place while the rest stays live.

---

## Deliverable & acceptance

A single self-contained HTML file that:
- renders the 5 mock recipes, all four kinds visibly different;
- click-through demos a full **launch → materialize → measure → ready** on llama.cpp (timers);
- demos an **ANDON halt + recovery** (the unresolvable cu128 recipe, or the vLLM WDDM defect-floor);
- demos the **human-gate modal** on vLLM's WSL provisioning;
- demos **offline/read-only** mode (a toggle);
- is keyboard-operable and theme-toggles;
- carries a short comment block documenting the **data contract** (the recipe + instance shapes) and the **event map**, so a Claude Code handoff can wire it to the real `engine-room` JSON/WS API.

Keep scope to the panel itself. If you spot adjacent things worth building (auth, real API, multi-rig), note them but don't build them.
