# Control Panel — state gallery

Real UI, not mockups — every PNG is the live prototype (`../dist/control-panel.html`) driven
through one of its states and screenshotted. **Regenerate with `node capture.mjs`** (zero-dep:
drives the page over CDP with the system Chrome, no install). Rebuild the standalone first with
`node ../build.mjs` if you've edited a source file.

| State | What it shows |
|-------|---------------|
| [Catalog (dark)](01-catalog-dark.png) | The home: rig strip, search + kind/trust filters, the recipes with kind + trust badges. |
| [Catalog (light)](02-catalog-light.png) | The light-theme toggle — a real conversion (AA-contrast tokens), not a tint. |
| [Offline / read-only](03-offline-readonly.png) | No executor connected → the panel degrades to a recipe **browser**: a read-only banner, everything visible, running disabled. |
| [launchable-server](04-detail-server.png) | llama.cpp + llama-swap: model-keyed baselines, "what this will do", a port, Preflight/Launch, the compensator ledger + vendored pins. |
| [Server running](05-server-running.png) | Materialize → measure with a determinate step bar; the live tok/s + VRAM-vs-ceiling instruments. |
| [batch-producer](06-detail-producer.png) | GGUF quantize: no port, axis is bits/weight, a `file-hash + perplexity` golden, and an output artifact path. Terminates after writing the file. |
| [modifier](07-detail-modifier.png) | SageAttention: no port, no self-baseline — an "Apply to [target]" overlay measured as a **delta**, with a hard-crash conflict guard and an "Unpatch" compensator. |
| [router-fleet](08-detail-router.png) | LiteLLM proxy: fronts other recipes, per-upstream health, a refcounted-stop compensator. |
| [ANDON halt](09-andon-halt.png) | The cu128 recipe surfaces the **verified-but-won't-resolve** contradiction (its pinned wheel is gone) with a contrastive cause and a one-click **Re-resolve**. |
| [Empty filter](10-empty-search.png) | A filter that matches nothing → a distinct "no recipes match" state with **Clear all filters** (vs. an empty catalog or a failed fetch, which get their own states). |
