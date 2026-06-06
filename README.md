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

## Design

engine-room is in active design; the executor is not yet implemented. The first artifact is
the operator UI:

- [`design/ui-control-panel.claude-design-brief.md`](design/ui-control-panel.claude-design-brief.md)
  — the Control Panel: browse recipes and run them, with the full event-handler map and
  usability requirements.

## License

MIT — see [LICENSE](LICENSE).
