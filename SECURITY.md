# Security Policy

## Trust boundary

engine-room is an **executor** over a verified recipe layer. Two things sit on either side of
its trust boundary:

- **The recipe layer (`tensor-engine-knowledge/engines.db`) is the trusted input.** It is the
  verified, sourced knowledge — what to build, the pinned toolchain, the measured baseline
  targets, the declared rollback steps. engine-room treats it as the source of truth and does
  not re-validate the recipes themselves. A recipe DB you do not trust is a recipe DB you
  should not point `er` at.
- **The live rig is what `er provision --execute` acts on.** This is the only command that
  produces irreversible side effects.

Everything else — `rig`, `list`, `show`, `preflight`, and `provision` *without* `--execute`
(the default) — is read-only or dry-run. The dry-run prints the full plan: every side effect
and its named compensator, before anything runs.

## What `er provision --execute` does

It is gated behind an explicit `--execute` **and** `--model`. When you run it, it:

1. **Downloads** the recipe's pinned artifacts and **sha256-verifies** them *when the pin
   carries a sha*.
   - **Known gap (Goal 1):** an unpinned artifact or a placeholder `<sha256>` is currently
     **accepted** without a content check. Until vendoring lands, treat the recipe DB and the
     artifact URLs it points at as trusted inputs. Imprecise pins (e.g. a releases *page*
     rather than a concrete asset) are rejected with an ANDON halt rather than guessed at.
2. **Extracts** archives into a **per-instance directory** under `ER_HOME`
   (`~/.engine-room` by default) — never onto the global PATH.
3. **Launches** a local server bound to `127.0.0.1` and **measures** it (a `tok/s` probe
   against the recipe's model-keyed baseline + a VRAM ceiling). Below baseline → halt + roll back.
4. **Can stop** that server (`er teardown <instance>`). Teardown is **identity-verified**: it
   only kills a PID that is alive *and* whose executable lives under our instance dir, so it
   will never kill an unrelated process or a recycled PID.

Every irreversible step is recorded on a ledger **before** it runs and has a named,
newest-first compensator, so a crashed run still has a rollback handle.

## No secrets, no telemetry

The core is stdlib-only (`sqlite3` + `subprocess`). It collects no telemetry and stores no
credentials. The only network access is the artifact downloads described above.

## Reporting a vulnerability

Please report security issues privately via **GitHub Security Advisories**:

- https://github.com/mcp-tool-shop-org/engine-room/security/advisories/new

If advisories are unavailable to you, open a regular issue that describes the impact without a
working exploit and we will move it to a private advisory:

- https://github.com/mcp-tool-shop-org/engine-room/issues

We aim to acknowledge reports promptly and will credit reporters who wish to be named.
