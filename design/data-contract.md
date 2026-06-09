# Control Panel data contract & event map

This is the **durable source of truth** for the recipe + instance shapes and the event map that
the future engine-room **JSON/WS API** and the [Control Panel](../app/) agree on. It is promoted
here out of the header comment in [`../app/data.js`](../app/data.js) so the contract lives in one
place and doesn't drift with the prototype.

> **Why this file, not the prototype comment?** `app/data.js` is a *faithful mock* — its inline
> `RECIPES` fixtures stand in for a real `GET` of the catalog, and its timer simulation stands in
> for the WebSocket stream. The mock only exercises the backends/kinds it needs to demo, so its
> comment can lag the executor (e.g. it enumerates a subset of providers). When the two disagree,
> **this file wins**, and the executor's actual surface
> ([`../executor/providers.py`](../executor/providers.py),
> [`../executor/resolve.py`](../executor/resolve.py)) is the ground truth behind it.

The handoff is mechanical: replace the `RECIPES` array with a `GET` of the recipe catalog, and
replace the `SIM.*` timer simulation in `app/engine.js` with a WebSocket stream of the events
below.

---

## RECIPE — immutable knowledge artifact

A recipe comes from the verified knowledge base (tensor-engine-knowledge); the UI never mutates
it. Field shapes:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | stable slug |
| `name` | string | display name |
| `kind` | enum | `launchable-server` \| `batch-producer` \| `modifier` \| `router-fleet` |
| `backend` | string \| null | the provider lane (see **Backends** below); `null` for a `modifier` (it inherits its target's backend) |
| `axis` | enum | `tok_s` \| `bits_per_weight` \| `delta_pct` \| `fleet_health` |
| `blurb` | string | one-line "what this is" |
| `willDo` | string[] | plain-language "what this will do" (shown before a run) |
| `trust` | object | see **trust** below |
| `compat` | `{ driver, cuda, sm }` | compatibility band (server / producer) |
| `baselines` | `[{ model, value, unit, bound, note? }]` | model-keyed targets; `bound` is `lower` (higher-is-better) or `upper` (lower-is-better) |
| `golden` | `{ kind, desc }` | correctness gate; `kind` ∈ `numeric` \| `perceptual` \| `file-hash` \| `WER` |
| `params` | `[{ key, label, value, tier, locked, options?, help? }]` | `tier` ∈ `default` \| `open`; locked params are pinned by the recipe |
| `pins` | `[{ label, ref, vendored }]` | content-addressed artifacts (`vendored:false` = index-only, not yet reproducible — Goal 1) |
| `compensators` | `[{ id, label, cmd, postState, human_gated, blastRadius? }]` | named undos; `human_gated:true` ⇒ machine-global, needs explicit approval |

### `trust`

| Field | Type | Meaning |
|---|---|---|
| `verified` | bool | claims grounded in a cited source |
| `verifiedSource` | string \| null | citation (shown in tooltip) |
| `resolvable` | enum | `yes` \| `no` \| `unchecked` — do the pinned artifacts still install today |
| `failingPin` | string \| null | which pin 404'd (when `resolvable === 'no'`) |
| `resolveFix` | `{from,to}` \| null | lineage offered by re-resolve |
| `commercial` | enum | `yes` \| `conditional` \| `no` — license posture |
| `license` | string | license name |

### Kind-specific fields

| Field | Type | Applies to |
|---|---|---|
| `port` | number \| null | `launchable-server`, `router-fleet` |
| `outputPath` | string | `batch-producer` |
| `target` | string | `modifier` — the recipe id it overlays |
| `deltas` | `[{ at, pct }]` | `modifier` — measured deltas |
| `conflictsWhen` | string \| null | `modifier` — hard-crash guard |
| `upstreams` | `[{ id, name, required, order }]` | `router-fleet` |
| `defectFloor` | `{ dep, min, why }` \| null | hard floor that triggers ANDON |

### Backends (provider lanes)

The `backend` string names a provider. The executor registers **seven**
([`../executor/providers.py`](../executor/providers.py)):

`native-win-compile` · `wsl2-docker` · `portable-bundle` · `venv` · `onnx-compile` ·
`python-proxy` · `raw-cmd`

A `modifier` recipe carries `backend: null` and inherits its target recipe's backend at
apply-time. (The prototype's mock catalog only exercises a subset of these lanes; the seven above
are the full set the API can return.)

---

## INSTANCE — mutable runtime

Created when you run a recipe; it lives in app state (and, in the executor, on the persisted
ledger).

| Field | Type | Meaning |
|---|---|---|
| `recipeId` | string | the recipe this instance runs |
| `state` | enum | `idle` \| `resolving` \| `preflight` \| `materializing` \| `activating` \| `producing` \| `applying` \| `bringing-up` \| `measuring` \| `ready` \| `done` \| `applied` \| `halted` \| `tearing-down` \| `rolling-back` \| `stale` |
| `phase` | string | current human-readable phase label |
| `steps` | `[{ label, cmd, status }]` | `status` ∈ `pending` \| `active` \| `ok` \| `fail` |
| `telemetry` | object | `{ axis, value, history[], baseline:{model,value,unit,bound}, vram, vramCeiling, temp, power, samples, upstreams?, delta?, bpw?, bpwCeil? }` |
| `ledger` | `[{ ...compensator, doneAt }]` | compensators run (newest-first teardown) |
| `andon` | object \| null | `{ expected, because, pin?, recovery:{label,event} }` — the contrastive halt banner |
| `lineage` | `{ from, to }` \| null | after a re-resolve / drift |

---

## EVENT MAP — UI event → guard → transition + real side effect

| Event | Guard | Transition / effect |
|---|---|---|
| `selectRecipe` | — | open detail pane (no side effect) |
| `changeParam` | `tier==='open'` & satisfies constraints | mutate draft |
| `preflight` | — | `idle→resolving→preflight`; resolve lock + capability + resolvability |
| `resolvabilityResult` | fail | `→halted` (ANDON: which pin 404'd, **[Re-resolve]**) |
| `launch` / `produce` / `apply` / `bringUp` | preflight ok | `materializing→…→measuring` |
| `materializeProgress` | — | advance phase (stream) |
| `humanGateRequired` | — | pause at gate → modal names blast radius |
| `approveGate` | — | resume (toast "approved by you") |
| `baselineSample` | `state===measuring` | update gauges (repeating) |
| `goldenResult` | pass / fail | continue / `→halted` |
| `andonHalt` | — | `*→halted` (loud contrastive banner + recovery) |
| `stop` | `ready` \| `measuring` | `→tearing-down→idle` (identity-verified) |
| `teardown` | — | run compensators newest-first (each shows undo + post-state) |
| `rollback` | — | `halted→rolling-back→idle` (replay ledger) |
| `reResolve` | `stale` \| 404 | new instance → re-measure (shows lineage) |
| `upstreamHealthChanged` | router only | recompute readiness |
| `driftDetected` | — | `ready→stale` (cheap re-probe offer) |
| `filter` / `search` | — | filter catalog (instant) |
| `toggleTheme` | — | dark ↔ light (persists `localStorage`) |
| `toggleExecutor` | — | online ↔ offline read-only (catalog still browsable) |

In the prototype, every real side effect is tagged `// SIDE EFFECT:` at its timer in
`app/engine.js`. In the executor those side effects are the ledgered, compensator-backed steps in
[`../executor/provision.py`](../executor/provision.py).
