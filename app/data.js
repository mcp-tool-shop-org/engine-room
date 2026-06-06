/* =============================================================================
 * engine-room Control Panel — DATA CONTRACT & EVENT MAP  (Claude Code handoff)
 * =============================================================================
 *
 * This file is the ONLY place mock fixtures live. Everything below is a faithful
 * stand-in for the real engine-room JSON/WS API. Replace `RECIPES` with a GET of
 * the recipe catalog, and replace the timer-driven simulation in app.js
 * (`SIM.*`) with a WebSocket stream of the events documented at the bottom.
 *
 * -----------------------------------------------------------------------------
 * RECIPE  (immutable knowledge artifact — comes from the knowledge base)
 * -----------------------------------------------------------------------------
 *   id              string           stable slug
 *   name            string           display name
 *   kind            'launchable-server' | 'batch-producer' | 'modifier' | 'router-fleet'
 *   backend         string           lane: native-win-compile | wsl2-docker | venv | null | python-proxy
 *   axis            'tok_s' | 'bits_per_weight' | 'delta_pct' | 'fleet_health'
 *   blurb           string           one-line "what this is"
 *   willDo          string[]         plain-language "what this will do" (shown before run)
 *   trust: {
 *     verified      true | false                 claims grounded in a cited source
 *     verifiedSource string|null                 citation (shown in tooltip)
 *     resolvable    'yes' | 'no' | 'unchecked'   pinned artifacts still install today
 *     failingPin    string|null                  which pin 404'd (when resolvable==='no')
 *     resolveFix    {from,to}|null               lineage offered by re-resolve
 *     commercial    'yes' | 'conditional' | 'no' license posture
 *     license       string                       license name
 *   }
 *   compat          { driver, cuda, sm }         compatibility band (server/producer)
 *   baselines       [{ model, value, unit, bound:'lower'|'upper', note? }]  model-keyed targets
 *   golden          { kind:'numeric'|'perceptual'|'file-hash'|'WER', desc }  correctness gate
 *   params          [{ key, label, value, tier:'default'|'open', locked, options?, help? }]
 *   pins            [{ label, ref, vendored:bool }]   content-addressed artifacts
 *   compensators    [{ id, label, cmd, postState, human_gated:bool, blastRadius? }]
 *   // kind-specific:
 *   port            number|null      (launchable-server)
 *   outputPath      string           (batch-producer)
 *   target          string           (modifier)  recipe id it overlays
 *   deltas          [{ at, pct }]    (modifier)  measured deltas
 *   conflictsWhen   string|null      (modifier)  hard-crash guard
 *   upstreams       [{ id, name, required, order }]  (router-fleet)
 *   defectFloor     { dep, min, why }|null         hard floor that triggers ANDON
 *
 * -----------------------------------------------------------------------------
 * INSTANCE  (mutable runtime — created when you run a recipe; lives in app state)
 * -----------------------------------------------------------------------------
 *   recipeId        string
 *   state           'idle'|'resolving'|'preflight'|'materializing'|'activating'|
 *                   'producing'|'applying'|'bringing-up'|'measuring'|'ready'|
 *                   'done'|'applied'|'halted'|'tearing-down'|'rolling-back'|'stale'
 *   phase           string           current human-readable phase label
 *   steps           [{ label, cmd, status:'pending'|'active'|'ok'|'fail' }]
 *   telemetry       { axisValue, axisHistory[], vram, vramCeiling, temp, power,
 *                     upstreams?, delta? }
 *   ledger          [{...compensator, doneAt }]   compensators run (newest-first teardown)
 *   andon           { expected, because, recovery:{label,event} } | null
 *   lineage         { from, to } | null           after re-resolve / drift
 *
 * -----------------------------------------------------------------------------
 * EVENT MAP  (UI event  ->  guard  ->  transition + real side effect)
 * -----------------------------------------------------------------------------
 *   selectRecipe        -> open detail pane (no side effect)
 *   changeParam         -> guard: tier==='open' & satisfies constraints -> mutate draft
 *   preflight           -> idle->resolving->preflight  | resolve lock + cap + resolvability
 *   resolvabilityResult -> if fail: ->halted (ANDON: which pin 404'd, [Re-resolve])
 *   launch|produce|apply|bringUp -> guard: preflight ok -> materializing->...->measuring
 *   materializeProgress -> advance phase (stream)
 *   humanGateRequired   -> pause at gate -> modal names blast radius
 *   approveGate         -> resume (toast "approved by you")
 *   baselineSample      -> (repeating, state===measuring) update gauges
 *   goldenResult        -> pass: continue ; fail: ->halted
 *   andonHalt           -> *->halted (loud contrastive banner + recovery)
 *   stop                -> ready|measuring -> tearing-down -> idle (identity-verified)
 *   teardown            -> run compensators newest-first (each shows undo + post-state)
 *   rollback            -> halted->rolling-back->idle (replay ledger)
 *   reResolve           -> stale|404 -> new instance -> re-measure (shows lineage)
 *   upstreamHealthChanged -> router only -> recompute readiness
 *   driftDetected       -> ready->stale (cheap re-probe offer)
 *   filter|search       -> filter catalog (instant)
 *   toggleTheme         -> dark<->light (persists localStorage)
 *   toggleExecutor      -> online<->offline read-only (catalog still browsable)
 *
 *  REAL side effects are tagged `// SIDE EFFECT:` at each timer in app.js.
 * ============================================================================= */

const RIG = {
  gpu: 'NVIDIA RTX 5090',
  vramCeiling: 32,      // GB
  driver: 'R575 / 581.15',
  cuda: '12.8',
  sm: 'sm_120',
};

const RECIPES = [
  /* ---- 1. launchable-server : the happy-path hero ---- */
  {
    id: 'llamacpp-swap',
    name: 'llama.cpp + llama-swap',
    kind: 'launchable-server',
    backend: 'native-win-compile',
    axis: 'tok_s',
    blurb: 'Native Windows build, hot-swaps models behind one port.',
    willDo: [
      'Unpack a vendored release-asset zip (no compile on your box).',
      'Start a long-lived server on port 8080 with a llama-swap front.',
      'Probe throughput against the model-keyed baseline, then mark ready.',
    ],
    trust: {
      verified: true,
      verifiedSource: 'measured 2025-11 on RTX 5090, R575 — studio readouts log #R-0241',
      resolvable: 'yes', failingPin: null, resolveFix: null,
      commercial: 'yes', license: 'MIT',
    },
    compat: { driver: '≥ R570', cuda: '12.8', sm: 'sm_120' },
    baselines: [
      { model: 'Qwen3-30B-A3B', value: 334, unit: 'tok/s', bound: 'lower' },
      { model: 'Qwen3-4B',      value: 286, unit: 'tok/s', bound: 'lower' },
    ],
    golden: { kind: 'numeric', desc: 'throughput ≥ baseline lower-bound on a 256-tok probe' },
    params: [
      { key: 'model',  label: 'Model',        value: 'Qwen3-30B-A3B', tier: 'open', locked: false,
        options: ['Qwen3-30B-A3B', 'Qwen3-4B'], help: 'Switches the active baseline target.' },
      { key: 'port',   label: 'Port',          value: 8080, tier: 'open', locked: false },
      { key: 'ctx',    label: 'Context',       value: '32768', tier: 'open', locked: false,
        options: ['8192', '16384', '32768', '65536'] },
      { key: 'flash',  label: 'Flash-attn',    value: 'on', tier: 'default', locked: true,
        help: 'Pinned by the recipe — locked at default tier.' },
    ],
    pins: [
      { label: 'release asset', ref: 'llama-b4123-win-cuda12.8.zip', vendored: true },
      { label: 'llama-swap',    ref: 'llama-swap@v0.9.1',            vendored: true },
    ],
    compensators: [
      { id: 'shim', label: 'Remove per-instance PATH shim', cmd: 'rm .er/shims/llamacpp-8080',
        postState: 'PATH restored; your global PATH was never touched.', human_gated: false },
      { id: 'stop', label: 'Stop server (identity-verified)', cmd: 'er stop --pid 0x1F4 --port 8080',
        postState: 'Stops engine-room\u2019s server on :8080 — not any other llama.cpp you run.', human_gated: false },
    ],
    port: 8080,
  },

  /* ---- 2. launchable-server : human-gate + defect-floor ANDON ---- */
  {
    id: 'vllm-wsl',
    name: 'vLLM (WSL2 / Docker)',
    kind: 'launchable-server',
    backend: 'wsl2-docker',
    axis: 'tok_s',
    blurb: 'High-concurrency serving inside a WSL2 Docker lane.',
    willDo: [
      'Ensure a WSL2 distro + Docker engine (may require a machine-global update).',
      'Pull a pinned vLLM image and start it on port 8000.',
      'Probe throughput at concurrency-64 against the AWQ baseline.',
    ],
    trust: {
      verified: true,
      verifiedSource: 'measured 2025-10, concurrency-64 sweep — readouts log #R-0188',
      resolvable: 'yes', failingPin: null, resolveFix: null,
      commercial: 'yes', license: 'Apache-2.0',
    },
    compat: { driver: '≥ R570', cuda: '12.8', sm: 'sm_120' },
    baselines: [
      { model: 'Qwen2.5-7B-AWQ', value: 4138, unit: 'tok/s', bound: 'lower', note: '@ concurrency-64' },
    ],
    golden: { kind: 'numeric', desc: 'aggregate tok/s ≥ baseline at concurrency-64' },
    params: [
      { key: 'model', label: 'Model',       value: 'Qwen2.5-7B-AWQ', tier: 'open', locked: false,
        options: ['Qwen2.5-7B-AWQ'] },
      { key: 'port',  label: 'Port',        value: 8000, tier: 'open', locked: false },
      { key: 'conc',  label: 'Concurrency', value: '64', tier: 'open', locked: false,
        options: ['16', '32', '64', '128'] },
      { key: 'wsl',   label: 'WSL2 version', value: '2.7.1', tier: 'open', locked: false,
        options: ['2.5.9', '2.7.1'], help: 'Below 2.7.0 hits a WDDM graph-capture hang (defect floor).' },
    ],
    pins: [
      { label: 'image',  ref: 'vllm/vllm-openai@sha256:9f3c…awq', vendored: true },
      { label: 'distro', ref: 'er-vllm-ubuntu-22.04',             vendored: true },
    ],
    compensators: [
      { id: 'container', label: 'Remove vLLM container', cmd: 'docker rm -f er-vllm-8000',
        postState: 'Container gone; image stays in your Docker cache.', human_gated: false },
      { id: 'wslupdate', label: 'Roll back wsl --update', cmd: 'wsl --update --rollback',
        postState: 'Reverts the WSL kernel — MACHINE-WIDE. Other WSL distros are affected.',
        human_gated: true,
        blastRadius: 'Changes the WSL2 kernel for every distro on this machine and may force a reboot. This cannot be scoped to engine-room alone.' },
    ],
    port: 8000,
    defectFloor: { dep: 'wsl2', min: '2.7.0', why: 'WDDM graph-capture hang below 2.7.0 — hard halt, not a warning.' },
  },

  /* ---- 3. batch-producer : runs, writes a file, exits ---- */
  {
    id: 'gguf-imatrix',
    name: 'GGUF imatrix quantize',
    kind: 'batch-producer',
    backend: 'venv',
    axis: 'bits_per_weight',
    blurb: 'Quantizes a model to GGUF using an importance matrix, then exits.',
    willDo: [
      'Build an importance matrix from a calibration set.',
      'Quantize to the target bits/weight and write a .gguf artifact.',
      'Gate on file-hash + a perplexity tolerance before declaring done.',
    ],
    trust: {
      verified: true,
      verifiedSource: 'golden ppl tolerance fixed against fp16 reference — readouts log #R-0205',
      resolvable: 'yes', failingPin: null, resolveFix: null,
      commercial: 'yes', license: 'MIT',
    },
    compat: { driver: '≥ R570', cuda: '12.8', sm: 'sm_120' },
    baselines: [
      { model: 'Qwen3-14B → Q4_K_M', value: 4.52, unit: 'bits/wt', bound: 'upper', note: 'target ≤ 4.6' },
    ],
    golden: { kind: 'file-hash', desc: 'sha256 of .gguf matches + perplexity within +0.15 of fp16' },
    params: [
      { key: 'src',   label: 'Source model', value: 'Qwen3-14B-fp16', tier: 'open', locked: false },
      { key: 'quant', label: 'Quant',        value: 'Q4_K_M', tier: 'open', locked: false,
        options: ['Q4_K_M', 'Q5_K_M', 'Q6_K', 'Q8_0'] },
      { key: 'calib', label: 'Calibration',  value: 'wikitext-2 (512 chunks)', tier: 'default', locked: true,
        help: 'Pinned calibration set — locked so the golden ppl stays comparable.' },
    ],
    pins: [
      { label: 'quantize bin', ref: 'llama-quantize-b4123', vendored: true },
      { label: 'imatrix',      ref: 'imatrix-wikitext2.dat', vendored: true },
    ],
    compensators: [
      { id: 'artifact', label: 'Delete written .gguf', cmd: 'rm out/Qwen3-14B-Q4_K_M.gguf',
        postState: 'Removes the output file only; source fp16 weights untouched.', human_gated: false },
      { id: 'venv', label: 'Remove scratch venv', cmd: 'rm -rf .er/venv/gguf',
        postState: 'Scratch venv removed; your system Python is untouched.', human_gated: false },
    ],
    outputPath: 'out/Qwen3-14B-Q4_K_M.gguf',
  },

  /* ---- 4. modifier : drop-in overlay, no port, delta gauge ---- */
  {
    id: 'sageattention',
    name: 'SageAttention 2.2',
    kind: 'modifier',
    backend: null,
    axis: 'delta_pct',
    blurb: 'Drop-in attention overlay — speeds up a target recipe, no server of its own.',
    willDo: [
      'Inherit the target recipe\u2019s environment (no engine, no port).',
      'Patch in the SageAttention kernels.',
      'Measure the speed delta against the unmodified target at two resolutions.',
    ],
    trust: {
      verified: true,
      verifiedSource: 'A/B vs unmodified comfyui-zimage-turbo — readouts log #R-0231',
      resolvable: 'yes', failingPin: null, resolveFix: null,
      commercial: 'conditional', license: 'BSD-3 + model terms',
    },
    compat: { driver: '≥ R570', cuda: '12.8', sm: 'sm_120' },
    baselines: [],
    golden: { kind: 'perceptual', desc: 'output images within LPIPS tolerance of the unmodified target' },
    params: [
      { key: 'target', label: 'Apply to', value: 'comfyui-zimage-turbo', tier: 'open', locked: false,
        options: ['comfyui-zimage-turbo'], help: 'The base recipe this overlay mutates.' },
      { key: 'res',    label: 'Probe resolution', value: '2048²', tier: 'open', locked: false,
        options: ['1024²', '2048²'] },
    ],
    pins: [
      { label: 'community wheel', ref: 'sageattention-2.2.0-cp311-win.whl', vendored: true },
    ],
    compensators: [
      { id: 'unpatch', label: 'Unpatch overlay', cmd: 'er modifier remove sageattention --from comfyui-zimage-turbo',
        postState: 'Target recipe reverts to its baseline kernels; nothing else changes.', human_gated: false },
    ],
    target: 'comfyui-zimage-turbo',
    deltas: [
      { at: '1024²', pct: 8.3 },
      { at: '2048²', pct: 29.3 },
    ],
    conflictsWhen: 'target backend == fp16_cuda (hard-crashes — overlay is disabled there)',
  },

  /* ---- 5. router-fleet : fronts other recipes, per-upstream health ---- */
  {
    id: 'litellm',
    name: 'LiteLLM proxy',
    kind: 'router-fleet',
    backend: 'python-proxy',
    axis: 'fleet_health',
    blurb: 'One OpenAI-compatible front that routes to your other engines.',
    willDo: [
      'Start a proxy on port 4000 with a pinned routing table.',
      'Wait for required upstreams to report healthy (start-order respected).',
      'Stay not-ready until every required upstream is green; refcount on teardown.',
    ],
    trust: {
      verified: true,
      verifiedSource: 'route table validated against upstream /health — readouts log #R-0250',
      resolvable: 'yes', failingPin: null, resolveFix: null,
      commercial: 'yes', license: 'MIT',
    },
    compat: { driver: 'n/a (proxy)', cuda: 'n/a', sm: 'n/a' },
    baselines: [],
    golden: { kind: 'numeric', desc: 'all required upstreams return /health 200 within the start window' },
    params: [
      { key: 'port', label: 'Port', value: 4000, tier: 'open', locked: false },
    ],
    pins: [
      { label: 'proxy', ref: 'litellm@1.52.0', vendored: true },
    ],
    compensators: [
      { id: 'proxy', label: 'Stop proxy (refcounted)', cmd: 'er stop --port 4000',
        postState: 'Stops the front only. Upstreams keep running — they are owned by their own instances.', human_gated: false },
    ],
    upstreams: [
      { id: 'llamacpp-swap', name: 'llama.cpp + llama-swap', required: true,  order: 1 },
      { id: 'vllm-wsl',      name: 'vLLM (WSL2 / Docker)',    required: true,  order: 2 },
    ],
    port: 4000,
  },

  /* ---- 6. launchable-server : UNRESOLVABLE — red badge + re-resolve demo ---- */
  {
    id: 'exllama-cu128',
    name: 'ExLlamaV2 (cu128)',
    kind: 'launchable-server',
    backend: 'venv',
    axis: 'tok_s',
    blurb: 'Fast EXL2 serving — pinned to a cu128 wheel channel.',
    willDo: [
      'Install the pinned cu128 wheel into a scratch venv.',
      'Start an EXL2 server on port 8090.',
      'Probe throughput against the EXL2 baseline.',
    ],
    trust: {
      verified: true,
      verifiedSource: 'measured 2025-09 on cu128 — readouts log #R-0150',
      resolvable: 'no',
      failingPin: 'exllamav2-0.2.4+cu128-cp311.whl  →  404 (cu128 channel retired upstream)',
      resolveFix: { from: 'cu128 channel (retired)', to: 'cu130 channel' },
      commercial: 'yes', license: 'MIT',
    },
    compat: { driver: '≥ R570', cuda: '12.8 (pinned cu128)', sm: 'sm_120' },
    baselines: [
      { model: 'Qwen2.5-7B-EXL2-4.0bpw', value: 412, unit: 'tok/s', bound: 'lower' },
    ],
    golden: { kind: 'numeric', desc: 'throughput ≥ baseline lower-bound on a 256-tok probe' },
    params: [
      { key: 'model', label: 'Model', value: 'Qwen2.5-7B-EXL2-4.0bpw', tier: 'open', locked: false },
      { key: 'port',  label: 'Port',  value: 8090, tier: 'open', locked: false },
    ],
    pins: [
      { label: 'wheel (cu128)', ref: 'exllamav2-0.2.4+cu128-cp311.whl', vendored: false },
    ],
    compensators: [
      { id: 'venv', label: 'Remove scratch venv', cmd: 'rm -rf .er/venv/exllama',
        postState: 'Scratch venv removed; system Python untouched.', human_gated: false },
    ],
    port: 8090,
  },
];

const KIND_META = {
  'launchable-server': { label: 'launchable-server', verb: 'Launch', running: 'Stop', glyph: 'server', axisLabel: 'tok/s' },
  'batch-producer':    { label: 'batch-producer',    verb: 'Produce', running: 'Cancel', glyph: 'file', axisLabel: 'bits/wt' },
  'modifier':          { label: 'modifier',          verb: 'Apply',   running: 'Unpatch', glyph: 'overlay', axisLabel: 'Δ%' },
  'router-fleet':      { label: 'router-fleet',      verb: 'Bring up', running: 'Tear down', glyph: 'router', axisLabel: 'health' },
};
