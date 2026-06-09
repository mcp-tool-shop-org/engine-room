---
title: Security
description: The engine-room trust boundary — the recipe DB is trusted input, --execute is the only rig-touching command — the honest Goal-1 pinning gap, no secrets or telemetry, and how to report a vulnerability.
sidebar:
  order: 5
---

engine-room is an **executor over a verified recipe layer**. Its security model follows from one
boundary: what it *trusts* (the recipes) versus what it *acts on* (your rig). This page distills
[`SECURITY.md`](https://github.com/mcp-tool-shop-org/engine-room/blob/main/SECURITY.md).

## Supported versions

Security fixes land on the **latest minor** — currently the **1.0.x** line. Older minors are not
back-patched. Pre-1.0 is unsupported.

| Version | Supported |
|---------|-----------|
| 1.0.x | yes |
| < 1.0 | no |

## The trust boundary

Two things sit on either side of engine-room's trust boundary:

- **The recipe layer (`tensor-engine-knowledge/engines.db`) is the trusted input.** It is the
  verified, sourced knowledge — what to build, the pinned toolchain, the measured baseline targets,
  the declared rollback steps. engine-room treats it as the source of truth and **does not
  re-validate the recipes themselves**. It reads the DB read-only and never writes it. **A recipe DB
  you do not trust is a recipe DB you should not point `er` at.**
- **The live rig is what `er provision --execute` acts on.** This is the **only** command that
  produces irreversible side effects.

Everything else — `rig`, `list`, `show`, `preflight`, and `provision` *without* `--execute` (the
default) — is read-only or dry-run. The dry-run prints the full plan: every side effect and its
named compensator, before anything runs.

## What `er provision --execute` does

`--execute` is gated behind an explicit flag **and** `--model`. When you run it, it:

1. **Downloads** the recipe's pinned artifacts and **sha256-verifies** them *when the pin carries a
   sha*. The verify is a **full** hash comparison (a prefix compare would let a forged near-collision
   pass), and the download is atomic — it fetches to a `.part` file, verifies, and only then
   promotes it to the cache, so a truncated or forged body never becomes a silent cache hit.
2. **Extracts** archives into a **per-instance directory** under `ER_HOME` (`~/.engine-room` by
   default) — **never** onto the global PATH.
3. **Launches** a local server bound to **`127.0.0.1`** and **measures** it (a `tok/s` probe against
   the recipe's model-keyed baseline + a VRAM ceiling). Below baseline or over ceiling → halt + roll
   back.
4. **Can stop** that server (`er teardown <instance>`). Teardown is **identity-verified**: it only
   kills a PID that is alive *and* whose executable lives under our instance dir, so it will never
   kill an unrelated process or a recycled PID.

Every irreversible step is recorded on a ledger **before** it runs and has a named, newest-first
compensator — so a crashed run still has a rollback handle.

## The honest Goal-1 gap

engine-room states its own limitation plainly rather than overclaiming:

> An **unpinned artifact**, or a placeholder `<sha256>`, is currently **accepted** without a content
> check.

Until content-addressed vendoring lands (**Goal 1**), treat the recipe DB and the artifact URLs it
points at as **trusted inputs**. This is the same reason preflight reports
`reproducible: no (vendor pins — Goal 1)` — the executor is honest about not being content-
reproducible yet. Note the one thing it does *not* do: an **imprecise pin** (e.g. a releases *page*
rather than a concrete asset) is **rejected with an ANDON halt**, not guessed at.

## No secrets, no telemetry

The core is **stdlib-only** (`sqlite3` + `subprocess`). It collects **no telemetry** and stores
**no credentials**. The only network access is the artifact downloads described above. There is
nothing to phone home and no token to leak.

## Reporting a vulnerability

Private vulnerability reporting is **enabled** on this repo, so the preferred route is GitHub's
private advisories form — a confidential channel between you and the maintainers, with no public
trace:

- **Report:** <https://github.com/mcp-tool-shop-org/engine-room/security/advisories/new>
  (or, on the repo, the **Security → Report a vulnerability** button)

If you can't reach that form, open a regular issue that describes the **impact without a working
exploit**, and it will be moved to a private advisory:

- <https://github.com/mcp-tool-shop-org/engine-room/issues>

Reports are acknowledged promptly, and reporters who wish to be named are credited.
