# Control Panel

The operator UI for engine-room: browse the recipe catalog, inspect trust + baselines, and
run a recipe (launch / produce / apply / bring-up) with live telemetry, ANDON halts, and safe
rollback. Pure front-end — **open it in a browser, no server needed.**

## Run

- **Source (dev):** open [`index.html`](index.html) directly — it loads `data.js`, `engine.js`,
  `ui.js`, `styles.css` as siblings. Works from `file://`.
- **Standalone (share/preview):** [`dist/control-panel.html`](dist/control-panel.html) — a
  single self-contained, offline file (everything inlined).

## Source layout

| File | Role |
|------|------|
| `index.html` | entry markup (accessible chrome: rig strip, filters, catalog, detail) |
| `data.js` | **the data contract + event map** (header comment) and the **only** place mock fixtures live |
| `engine.js` | the instance state machine + the timer simulation (every fake side effect tagged `// SIDE EFFECT:`) |
| `ui.js` | rendering — catalog cards, the polymorphic detail pane, modals, toasts |
| `styles.css` | navy-ink + deep-blue instrument-panel theme; status colors (green go / amber gate / red halt); light theme |
| `logo.png` | brand asset |

The standalone in `dist/control-panel.html` is **built from these sources** — edit the source
files, then `node build.mjs` (zero-dep: inlines the CSS + JS into one offline file). Don't
hand-edit the compiled file. Refresh the [state gallery](screenshots/) with
`node screenshots/capture.mjs` (drives the page over CDP with the system Chrome — no install).

## Wiring to the real executor (handoff)

The prototype is faithful to the real engine-room API so the swap is mechanical:

1. Replace the `RECIPES` array in `data.js` with a `GET` of the recipe catalog (the typed
   recipe layer served from the tensor-engine knowledge base).
2. Replace the `SIM.*` timer simulation in `engine.js` (every point tagged `// SIDE EFFECT:`)
   with a WebSocket stream of the events documented in `data.js`'s header (`preflight`,
   `materializeProgress`, `humanGateRequired`, `baselineSample`, `andonHalt`, …).

The recipe + instance shapes and the full event map are documented at the top of `data.js`.

Scope is the panel only — auth, real executor wiring, and multi-rig are out of scope here
(noted in [`../design/ui-control-panel.claude-design-brief.md`](../design/ui-control-panel.claude-design-brief.md)).
