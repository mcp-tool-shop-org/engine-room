---
title: engine-room Handbook
description: Recipe-driven provisioner for local AI engines — the action half over a verified recipe layer. Provision, launch, and measure an engine on your own GPU rig, dry-run first.
sidebar:
  order: 0
---

**engine-room** is a recipe-driven provisioner for local AI engines. You browse a catalog of
verified, measured *engine recipes*, pick one, and stand it up on your own GPU rig —
**provision → launch → measure** — on the fly and validated against a real performance baseline.

The CLI is `er` (or `python -m executor.cli`). The core is **stdlib-only Python** (`sqlite3` +
`subprocess`), targets **Python 3.10+**, and has **zero third-party dependencies**. It is a public,
MIT-licensed repo — installed with `pip install -e .`, not from PyPI.

## The knowledge / action split

Local AI engines are wildly heterogeneous to stand up: one is a from-source CUDA build, the next
is a container, the next a portable bundle, the next a quantizer that writes a file and exits.
Knowing *which* engine to use is one problem (a knowledge base solves it); actually
*standing it up correctly, reproducibly, and measuring that it works* is a different one.

engine-room is built around that seam — two artifacts, one boundary:

- **Knowledge** — the verified, sourced, abstract *recipe*: what to build, the pinned toolchain,
  the measured baseline targets, the declared rollback steps. It changes when an upstream engine
  changes. It lives in the separately-provided **tensor-engine-knowledge** recipe DB
  (`engines.db`).
- **Action** — *this tool*: resolving a recipe against the live rig, materializing it,
  launching/measuring it, and rolling it back safely. It changes when *your rig* changes.

engine-room is the **action** half. It does not ship the recipes — you point `er` at the recipe DB
(see [Getting Started](/handbook/getting-started/)). The recipe layer is **trusted input**;
engine-room reads it **read-only** and never writes it.

## The four recipe kinds

A recipe is *polymorphic* — four kinds, each with a different shape and a different way of being
measured:

| Kind | What it does | Measured by |
|------|--------------|-------------|
| `launchable-server` | starts a long-lived server on a port | throughput (tok/s, it/s) |
| `batch-producer` | runs, writes an artifact, exits | output quality + wall-clock |
| `modifier` | a drop-in overlay that speeds up another recipe | a measured delta |
| `router-fleet` | a front that routes to other recipes | per-upstream health |

Today the live provisioning path is implemented for one combination —
`launchable-server` on the `native-win-compile` backend (llama.cpp), the lowest-risk engine that
exercises the whole contract. The other kinds and backends are read-only / planned (see
[Architecture](/handbook/architecture/)).

## Safety posture

engine-room is designed to be safe to run *before* it is safe to trust:

- **Dry-run by default.** `er provision <slug>` prints the full plan — every side effect and its
  named compensator — and touches nothing. `--execute` is **the only flag that touches the rig**,
  and it additionally requires `--model`.
- **ANDON halts.** Any step that can't be ruled out safe halts the pipeline loudly rather than
  guessing. A preflight halt blocks provision; a failed measure gate halts and rolls back.
- **Honest compensators.** Every irreversible step is recorded on a persisted ledger *before* it
  runs and has a named, newest-first undo with an honest post-rollback state. Teardown is
  identity-verified — it only stops a server whose executable lives under our instance directory,
  so it never kills an unrelated process.
- **Honest reproducibility.** Pins are resolved against an index; unpinned artifacts are still
  accepted today. Preflight says `reproducible: no (vendor pins — Goal 1)` rather than overclaiming.
  Content-addressed vendoring is **Goal 1**.

## Where to go next

- **[Getting Started](/handbook/getting-started/)** — install, point at the recipe DB, run your
  first commands.
- **[Usage](/handbook/usage/)** — the dry-run-first workflow: preflight → dry-run plan → execute →
  teardown.
- **[Command Reference](/handbook/reference/)** — every command, flag, and exit code.
- **[Architecture](/handbook/architecture/)** — how the executor is built, module by module.
- **[Security](/handbook/security/)** — the trust boundary and how to report a vulnerability.
