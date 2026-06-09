import type { SiteConfig } from '@mcptoolshop/site-theme';

export const config: SiteConfig = {
  title: 'engine-room',
  description:
    'Recipe-driven provisioner for local AI engines — the executor over the tensor-engine recipe layer',
  logoBadge: 'ER',
  brandName: 'engine-room',
  repoUrl: 'https://github.com/mcp-tool-shop-org/engine-room',
  footerText:
    'MIT Licensed — built by <a href="https://mcp-tool-shop.github.io/" style="color:var(--color-muted);text-decoration:underline">MCP Tool Shop</a>',

  hero: {
    badge: 'Open source · stdlib-only',
    headline: 'Browse verified engine recipes,',
    headlineAccent: 'stand one up on your own GPU.',
    description:
      'engine-room is the <strong>action</strong> half over a verified recipe layer: pick a recipe, then provision, launch, measure, and roll back — all on your own rig. Resolve against the live hardware, materialize the pinned artifacts, gate on a real performance baseline, and undo every irreversible step newest-first.',
    primaryCta: { href: '#usage', label: 'Get started' },
    secondaryCta: { href: 'handbook/', label: 'Read the Handbook' },
    previews: [
      { label: 'Detect the rig (no DB needed)', code: 'er rig' },
      { label: 'Browse the catalog', code: 'er list' },
      { label: 'Resolve — no side effects', code: 'er preflight <slug>' },
      { label: 'Plan it (dry-run by default)', code: 'er provision <slug>' },
    ],
  },

  sections: [
    {
      kind: 'features',
      id: 'features',
      title: 'Knowledge and action, split clean',
      subtitle:
        'A verified recipe says what to build; engine-room stands it up correctly on your rig and proves it works.',
      features: [
        {
          title: 'Polymorphic recipes',
          desc: 'Four kinds, each measured on its own terms: launchable-server (tok/s, it/s), batch-producer (output + wall-clock), modifier (a measured delta), router-fleet (per-upstream health).',
        },
        {
          title: 'Verified + resolvable',
          desc: 'The recipe layer (tensor-engine-knowledge/engines.db) is the trusted, sourced input — read-only, never written. preflight resolves it against the live rig with a capability + resolvability check before anything runs.',
        },
        {
          title: 'Reproducible + validated by design',
          desc: 'Model-keyed baselines with a compatibility band, a correctness gate before any performance claim. Reproducibility is honestly partial today — content-addressed vendor pins are Goal 1, not an overclaim.',
        },
        {
          title: 'Stdlib-only + named compensators',
          desc: 'Zero third-party deps in the core (sqlite3 + subprocess). Every irreversible step is recorded on a ledger before it runs and has a named, newest-first, identity-verified undo.',
        },
      ],
    },
    {
      kind: 'code-cards',
      id: 'usage',
      title: 'Usage',
      subtitle:
        'Python >=3.10, stdlib-only core. Clone gives you the executor; point er at a separately-provided recipe DB for the catalog.',
      cards: [
        {
          title: 'Install (editable) — gives the er command',
          code: 'pip install -e .\n# or run without installing:\n# python -m executor.cli rig',
        },
        {
          title: 'Point at the recipe layer',
          code: '# tensor-engine-knowledge/engines.db is a separate artifact\nexport ER_RECIPES_DB=/path/to/engines.db\n# or pass --db <path> on any command',
        },
        {
          title: 'Browse + resolve (read-only)',
          code: 'er rig                 # detected rig fingerprint (no DB needed)\ner list                # list recipes (--all for everything)\ner show <slug>         # one recipe: baselines, artifacts, compensators\ner preflight <slug>    # resolve + capability check, no side effects',
        },
        {
          title: 'Provision — dry-run by default',
          code: 'er provision <slug>                         # full plan + every compensator (no side effects)\ner provision <slug> --execute --model <gguf>  # live: materialize -> launch -> measure\ner status                                   # the ledger: provisioned instances\ner teardown <instance>                      # roll back, compensators newest-first',
        },
      ],
    },
  ],
};
