# engine-room

A **recipe-driven provisioner for local AI engines.** Browse a catalog of verified, measured
"engine recipes," pick one, and stand it up on your own GPU rig — **provision → launch →
measure** — on the fly, reproducibly, and validated against a real performance baseline.

## Why

Local AI engines are wildly heterogeneous to stand up — one is a from-source CUDA build, the
next is a container, the next a portable bundle, the next a quantizer that writes a file and
exits. Knowing *which* engine to use is one problem (a knowledge base solves it); actually
*standing it up correctly, reproducibly, and measuring that it works* is a different one.
engine-room is the second half.

## Architecture — two artifacts, one seam

engine-room is the **action** half of a deliberate split:

- **Knowledge** — the verified, sourced, abstract *recipe* (what to build, the pinned
  toolchain, the measured baseline targets, the declared rollback steps). It changes when an
  upstream engine changes. Lives in the knowledge base.
- **Action** — this repo: resolving a recipe against the live rig, materializing it,
  launching/measuring it, and rolling it back safely. It changes when the *rig* changes.

## Getting the recipe layer

engine-room is the **action** half; it does not ship the recipes. The **knowledge** half is a
separately-provided, verified artifact — the **tensor-engine-knowledge** recipe DB
(`engines.db`) — that you point `er` at. Cloning this repo alone gives you the executor, not the
catalog.

- **Detect your rig** with no recipe DB at all: `er rig` reads only the live hardware
  (`nvidia-smi` + env), so it works out of the box.
- **Point at the recipe DB** for everything else (`list` / `show` / `preflight` / `provision`)
  one of two ways:
  - set `ER_RECIPES_DB` to the DB path, or
  - pass `--db <path>` on any command.
- If neither is set, `er` looks for `../../readouts/tensor-engine-knowledge/engines.db` relative
  to the repo. When the DB is missing you get a clear error
  (`recipe DB not found: … — set $ER_RECIPES_DB or pass --db`), not a stack trace.

The recipe layer is the trusted knowledge input (see [Security / threat model](#security--threat-model)).
Obtain `engines.db` from the tensor-engine-knowledge distribution; engine-room reads it
**read-only** and never writes it.

A recipe is **polymorphic** — four kinds, each with a different shape:

| Kind | What it does | Measured by |
|------|--------------|-------------|
| `launchable-server` | starts a long-lived server on a port | throughput (tok/s, it/s) |
| `batch-producer` | runs, writes an artifact, exits | output quality + wall-clock |
| `modifier` | a drop-in overlay that speeds up another recipe | a measured delta |
| `router-fleet` | a front that routes to other recipes | per-upstream health |

## Reproducible + validated by design

- **Pinned + vendored** artifacts (a hash against a curated index isn't enough when the index
  drops the channel — the pin must be a content-addressed copy).
- **Measured baselines** are model-keyed and carry a compatibility band, so a routine driver
  bump doesn't invalidate them.
- **A correctness gate runs before any performance claim**, pluggable per output modality.
- **Every irreversible step has a named undo** with an honest post-rollback state; the
  machine-global ones require explicit human approval.

## Status

The executor is implemented. The `er` CLI reads the recipe layer and resolves a recipe
against the live rig (`rig` / `list` / `show` / `preflight`, all non-side-effecting), and the
provisioner runs the reconcile loop — **dry-run by default**, with a wired `--execute` path
that materializes the pinned artifacts, launches a local server, and measures it against the
recipe's baseline (`provision` / `teardown` / `status`). See [`executor/README.md`](executor/README.md).

Reproducibility is honestly partial today: pins are resolved against an index, and unpinned
artifacts are accepted — vendoring them into a content-addressed store so `reproducible` is
*earned* is **Goal 1**.

The operator UI ships as a self-contained prototype (mock data + timer-simulated side effects,
faithful to the real JSON/WS API):

- [`app/`](app/) — the Control Panel: browse recipes and run them, with live telemetry, ANDON
  halts, and rollback. Designed from
  [`design/ui-control-panel.claude-design-brief.md`](design/ui-control-panel.claude-design-brief.md)
  (the full event-handler map and usability requirements).

## Security / threat model

The **recipe layer** (`tensor-engine-knowledge/engines.db`) is the trusted knowledge input:
the verified, sourced recipes that say what to build and what targets to hit. engine-room
treats it as the source of truth.

`er provision --execute` is the only command that touches the rig. It is **gated behind an
explicit `--execute` and `--model`** — every other command, and `provision` without
`--execute`, is read-only / dry-run. When you do execute, it:

- **downloads** the recipe's pinned artifacts and **sha256-verifies** them *when the pin
  carries a sha* — unpinned / placeholder shas are currently accepted (the Goal-1 vendoring
  gap above; treat the recipe DB and its artifact URLs as trusted until that lands),
- **extracts** archives into a per-instance directory (never global PATH),
- **launches** a local server (`127.0.0.1`) and can **stop** it — teardown is identity-verified
  (it only kills a PID whose executable lives under our instance dir, so it never kills an
  unrelated process).

Every irreversible step is recorded on a ledger *before* it runs and has a named, newest-first
compensator. To report a vulnerability, see [`SECURITY.md`](SECURITY.md).

## Support

engine-room is **actively maintained**. Security fixes land on the **latest minor** (the 1.0.x
line); see [`SECURITY.md`](SECURITY.md) for supported versions and the private-advisory reporting
path. File bugs and feature requests as GitHub issues.

## License

MIT — see [LICENSE](LICENSE).
