/* ============================================================================
 * engine-room — engine.js
 * App state, the lifecycle state machine, timer-driven simulation, telemetry.
 * Every timer that stands in for a real side effect is tagged `SIDE EFFECT:`.
 * Replace SIM.* with a WebSocket event stream (see EVENT MAP in data.js).
 * ========================================================================== */

const STATE = {
  theme: 'dark',
  online: true,                 // executor connected? false => read-only browser
  selectedId: null,
  filters: { q: '', kind: null, verified: false, resolvable: false, commercial: false },
  instances: {},                // recipeId -> instance (see INSTANCE shape in data.js)
  modal: null,                  // { type, ... }
  draft: {},                    // recipeId -> { paramKey: value }
};

/* ---- icons (inline, no external assets) ---- */
const ICON = {
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>',
  x:     '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z"/></svg>',
  dash:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M5 12h14"/></svg>',
  scale: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18M7 8 3 14h8L7 8ZM17 8l-4 6h8l-4-6ZM4 21h16"/></svg>',
  search:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>',
  sun:   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5 19 19M19 5l-1.5 1.5M6.5 17.5 5 19"/></svg>',
  moon:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>',
  plug:  '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 22v-5M9 7V2M15 7V2M7 7h10v3a5 5 0 0 1-10 0V7Z"/></svg>',
  reactor:'<svg viewBox="0 0 32 32" fill="none"><circle cx="16" cy="16" r="13" stroke="currentColor" stroke-width="1.6" opacity=".4"/><circle cx="16" cy="16" r="4" fill="currentColor"/><path d="M16 4v6M16 22v6M4 16h6M22 16h6" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/><path d="M7 7l4.2 4.2M20.8 20.8 25 25M25 7l-4.2 4.2M11.2 20.8 7 25" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" opacity=".6"/></svg>',
  empty: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="4" width="18" height="14" rx="2"/><path d="M3 9h18M8 14h2"/></svg>',
};

const uid = () => '0x' + Math.floor(Math.random() * 0xffff).toString(16).toUpperCase().padStart(3, '0');
const recipeById = (id) => RECIPES.find(r => r.id === id);

/* draft config accessor (initialized lazily from recipe params) */
function draftFor(recipe) {
  if (!STATE.draft[recipe.id]) {
    const d = {};
    recipe.params.forEach(p => { d[p.key] = p.value; });
    STATE.draft[recipe.id] = d;
  }
  return STATE.draft[recipe.id];
}

/* ---- instance lifecycle helpers ---- */
function ensureInstance(recipe) {
  if (!STATE.instances[recipe.id]) {
    STATE.instances[recipe.id] = {
      recipeId: recipe.id, state: 'idle', phase: '', steps: [],
      telemetry: null, ledger: [], andon: null, lineage: null,
      pid: null, wallClock: 0, preflightOk: false, _timers: [],
    };
  }
  return STATE.instances[recipe.id];
}
function clearTimers(inst) { (inst._timers || []).forEach(clearTimeout); (inst._intervals || []).forEach(clearInterval); inst._timers = []; inst._intervals = []; }
function setTimer(inst, fn, ms) { const t = setTimeout(fn, ms); inst._timers.push(t); return t; }

/* states that mean "busy / mid-flight" (used for spinner + non-blocking display) */
const BUSY = new Set(['resolving','materializing','activating','producing','applying','bringing-up','measuring','tearing-down','rolling-back']);
const TERMINAL_GOOD = { 'launchable-server':'ready', 'batch-producer':'done', 'modifier':'applied', 'router-fleet':'ready' };

/* Fallback meta for a recipe_kind the panel has no handler for (a 5th kind the
 * knowledge base grows that this build predates). Every consumer reads
 * KIND_META through kindMeta() so an unknown kind renders a legible
 * "unsupported kind" pane instead of crashing on `km.label` / `km.verb`. */
const UNKNOWN_KIND_META = { label: 'unsupported', verb: 'Run', running: 'Stop', glyph: 'unknown', axisLabel: '—', unsupported: true };
function kindMeta(recipe) {
  const k = recipe && recipe.kind;
  return (k && KIND_META[k]) || UNKNOWN_KIND_META;
}
function isSupportedKind(recipe) { return !!(recipe && KIND_META[recipe.kind]); }

/* ============================================================================
 * PLANS — per recipe action, the ordered steps the simulation walks.
 * Each step: { label, cmd, dur, phase?, gate?, comp?, upstream?, progress? }
 *   gate    -> compensator id whose blastRadius gates this step (human gate)
 *   comp    -> compensator id pushed to the ledger when the step completes
 *   upstream-> index of recipe.upstreams to flip healthy (router-fleet)
 *   progress-> show a determinate progress bar for this step (producer)
 * ========================================================================== */
function preflightPlan(recipe) {
  const steps = [
    { label: 'Resolving recipe lock', cmd: 'er resolve --lock ' + recipe.id, dur: 650 },
    { label: 'Checking capability band', cmd: `er check --driver "${recipe.compat.driver}" --cuda ${recipe.compat.cuda}`, dur: 700 },
  ];
  if (recipe.defectFloor) {
    steps.push({ label: `Checking defect floor (${recipe.defectFloor.dep} ≥ ${recipe.defectFloor.min})`,
      cmd: `er check --floor ${recipe.defectFloor.dep}>=${recipe.defectFloor.min}`, dur: 700, check: 'defectFloor' });
  }
  steps.push({ label: 'Probing artifact resolvability', cmd: 'er resolve --probe-pins', dur: 850, check: 'resolvable' });
  return steps;
}

function runPlan(recipe) {
  switch (recipe.kind) {
    case 'launchable-server':
      if (recipe.id === 'vllm-wsl') return {
        phase: 'materializing', verbPhase: 'activating',
        steps: [
          { label: 'Ensuring WSL2 distro + Docker engine', cmd: 'wsl --update', dur: 1300, gate: 'wslupdate', comp: 'wslupdate' },
          { label: 'Pulling pinned vLLM image', cmd: 'docker pull vllm/vllm-openai@sha256:9f3c…awq', dur: 1500, comp: 'container' },
          { label: 'Starting vLLM server on :8000', cmd: 'docker run --gpus all -p 8000 …', dur: 1100, phase: 'activating' },
        ],
      };
      return {
        phase: 'materializing', verbPhase: 'activating',
        steps: [
          { label: 'Unpacking vendored release asset', cmd: 'unzip llama-b4123-win-cuda12.8.zip', dur: 1100 },
          { label: 'Installing per-instance PATH shim', cmd: 'er shim add ' + recipe.id, dur: 700, comp: 'shim' },
          { label: `Starting server on :${recipe.port}`, cmd: `llama-server --port ${recipe.port} --model …`, dur: 1000, phase: 'activating', comp: 'stop' },
        ],
      };
    case 'batch-producer': return {
      phase: 'materializing', verbPhase: 'producing',
      steps: [
        { label: 'Building importance matrix', cmd: 'imatrix --calib wikitext-2 --chunks 512', dur: 1400, comp: 'venv' },
        { label: 'Quantizing to ' + draftFor(recipe).quant, cmd: `llama-quantize --imatrix … ${draftFor(recipe).quant}`, dur: 1900, phase: 'producing', comp: 'artifact', progress: true },
        { label: 'Writing GGUF artifact', cmd: 'write ' + recipe.outputPath, dur: 800 },
      ],
    };
    case 'modifier': return {
      phase: 'materializing', verbPhase: 'applying',
      steps: [
        { label: 'Inheriting target environment', cmd: 'er modifier env --from ' + recipe.target, dur: 900 },
        { label: 'Patching SageAttention kernels', cmd: 'pip install sageattention-2.2.0-cp311-win.whl', dur: 1300, phase: 'applying', comp: 'unpatch' },
      ],
    };
    case 'router-fleet': return {
      phase: 'materializing', verbPhase: 'bringing-up',
      steps: [
        { label: `Starting proxy on :${recipe.port}`, cmd: `litellm --config route.yaml --port ${recipe.port}`, dur: 1000, phase: 'bringing-up', comp: 'proxy' },
        { label: 'Awaiting upstream: ' + recipe.upstreams[0].name + ' (order 1)', cmd: 'wait http://:8080/health', dur: 1500, upstream: 0 },
        { label: 'Awaiting upstream: ' + recipe.upstreams[1].name + ' (order 2)', cmd: 'wait http://:8000/health', dur: 1600, upstream: 1 },
      ],
    };
    // A recipe_kind this build has no plan for: return null so SIM.run halts
    // legibly instead of dereferencing `plan.phase` on undefined.
    default: return null;
  }
}

/* ============================================================================
 * SIM — the timer-driven simulation. Public methods map 1:1 to EVENT MAP events.
 * ========================================================================== */
const SIM = {
  preflight(recipe) {
    const inst = ensureInstance(recipe);
    if (BUSY.has(inst.state)) return;
    clearTimers(inst);
    inst.andon = null; inst.preflightOk = false; inst.lineage = inst.lineage || null;
    inst.state = 'resolving'; inst.phase = 'preflight';
    inst.steps = preflightPlan(recipe).map(s => ({ ...s, status: 'pending' }));
    render();
    // SIDE EFFECT: real preflight resolves the lockfile, probes capability vs the rig,
    // and HEAD-requests every pinned artifact. Here it's a timed walk over the plan.
    this._walk(recipe, inst, inst.steps, 0, () => {
      inst.preflightOk = true; inst.state = 'preflight';
      inst.phase = 'preflight passed — ready to ' + kindMeta(recipe).verb.toLowerCase();
      render();
    });
  },

  // primary action: launch | produce | apply | bringUp — all share the walker
  run(recipe) {
    const inst = ensureInstance(recipe);
    if (!inst.preflightOk || BUSY.has(inst.state)) return;
    clearTimers(inst);
    const plan = runPlan(recipe);
    // Unknown recipe_kind: no plan to walk. Don't crash — surface it.
    if (!plan) {
      inst.state = 'idle'; inst.phase = '';
      toast('Unsupported recipe kind "' + (recipe.kind || '?') + '" — this build has no plan for it.', 'warn');
      render();
      return;
    }
    inst.state = plan.phase; inst.andon = null;
    inst.steps = plan.steps.map(s => ({ ...s, status: 'pending' }));
    if (recipe.kind === 'router-fleet') {
      inst.telemetry = { upstreams: recipe.upstreams.map(u => ({ ...u, health: 'gray' })) };
    }
    render();
    this._walk(recipe, inst, inst.steps, 0, () => this._enterMeasure(recipe, inst));
  },

  // walk an array of steps with timers, honoring gates / checks / compensators
  _walk(recipe, inst, steps, i, done) {
    if (i >= steps.length) { done(); return; }
    const step = steps[i];

    // human gate: pause and require explicit approval naming the blast radius
    if (step.gate && !step._approved) {
      step.status = 'pending';
      const comp = recipe.compensators.find(c => c.id === step.gate);
      STATE.modal = { type: 'gate', recipeId: recipe.id, comp, onApprove: () => {
        step._approved = true; STATE.modal = null;
        toast('Approved by you — ' + comp.label.toLowerCase(), 'warn');
        this._walk(recipe, inst, steps, i, done);          // resume same step
      }, onCancel: () => {
        STATE.modal = null; inst.state = 'preflight';
        inst.phase = 'gate declined — back to preflight'; toast('Gate declined — no machine-global change made');
        render();
      }};
      render();
      return;
    }

    step.status = 'active';
    if (step.phase) inst.state = step.phase;
    inst.phase = step.label;
    render();

    // SIDE EFFECT (materializeProgress): a determinate step (e.g. quantize) streams
    // a 0..1 progress fraction. Here a timer simulates that stream so a long op reads
    // as alive-and-advancing; the real WS replaces this with progress events.
    if (step.progress) {
      step._progress = step._progress || 0;
      const tick = 200, ramp = Math.max(tick, step.dur);
      inst._intervals = inst._intervals || [];
      const pv = setInterval(() => {
        if (step.status !== 'active') { clearInterval(pv); return; }
        // approach but never reach 1 until the step actually completes
        step._progress = Math.min(0.96, step._progress + tick / ramp);
        render();
      }, tick);
      inst._intervals.push(pv);
      step._progressIv = pv;
    }

    // SIDE EFFECT: each step below is a real shell/recipe_step in the executor.
    setTimer(inst, () => {
      // resolvability ANDON (the unresolvable cu128 recipe)
      if (step.check === 'resolvable' && recipe.trust.resolvable === 'no' && !inst.lineage) {
        step.status = 'fail';
        return this.andonHalt(recipe, inst, {
          expected: 'it to install the pinned artifacts and continue',
          because: 'a pinned artifact no longer resolves',
          pin: recipe.trust.failingPin,
          recovery: { label: 'Re-resolve', event: 'reResolve' },
        });
      }
      // defect-floor ANDON (e.g. vLLM WDDM hang below wsl2 2.7.0) — generic over
      // whatever dep the recipe names, not hardcoded to WSL.
      if (step.check === 'defectFloor') {
        const floor = recipe.defectFloor;
        const { cur } = defectFloorField(recipe);
        if (cur != null && cmpVer(cur, floor.min) < 0) {
          step.status = 'fail';
          return this.andonHalt(recipe, inst, {
            expected: `it to launch on ${floor.dep} ${cur}`,
            because: floor.why,
            pin: `${floor.dep} ${cur}  <  required ${floor.min}`,
            recovery: { label: `Set ${floor.dep} ≥ ${floor.min} & retry`, event: 'fixFloor' },
          });
        }
      }
      step.status = 'ok';
      if (step._progressIv) { clearInterval(step._progressIv); inst._intervals = (inst._intervals || []).filter(x => x !== step._progressIv); step._progressIv = null; step._progress = 1; }
      if (step.comp) {
        const comp = recipe.compensators.find(c => c.id === step.comp);
        if (comp && !inst.ledger.some(l => l.id === comp.id)) inst.ledger.push({ ...comp, doneAt: Date.now() });
      }
      if (step.upstream != null && inst.telemetry?.upstreams) {
        inst.telemetry.upstreams[step.upstream].health = 'green';
      }
      render();
      this._walk(recipe, inst, steps, i + 1, done);
    }, step.dur);
  },

  _enterMeasure(recipe, inst) {
    inst.state = 'measuring'; inst.phase = 'measuring against baseline';
    if (recipe.kind === 'router-fleet') {
      // router readiness is upstream health, not a sampled axis
      inst.phase = 'all required upstreams healthy';
      setTimer(inst, () => { inst.state = 'ready'; inst.phase = 'router up — upstreams healthy'; toast('Router ready — all upstreams green'); render(); }, 700);
      render(); return;
    }
    if (recipe.kind === 'modifier') {
      inst.telemetry = { delta: recipe.deltas, measuredAt: draftFor(recipe).res };
      render();
      // SIDE EFFECT: A/B probe vs the unmodified target at the chosen resolution.
      setTimer(inst, () => this.goldenResult(recipe, inst, true), 1700);
      return;
    }
    if (recipe.kind === 'batch-producer') {
      inst.telemetry = { bpw: recipe.baselines[0]?.value ?? null, bpwCeil: 4.6, wall: inst.wallClock };
      inst.phase = 'golden gate: file-hash + perplexity';
      render();
      setTimer(inst, () => this.goldenResult(recipe, inst, true), 1300);
      return;
    }
    // launchable-server: live telemetry samples
    const baseline = activeBaseline(recipe);
    inst.telemetry = { axis: recipe.axis, baseline, value: baseline.value, history: [],
      vram: 0, vramCeiling: RIG.vramCeiling, temp: 48, power: 120, samples: 0 };
    render();
    // SIDE EFFECT: repeating baselineSample over the WS while state===measuring,
    // then a goldenResult terminates the probe.
    inst._intervals = inst._intervals || [];
    const targetVram = recipe.id === 'vllm-wsl' ? 28.4 : 21.8;
    const iv = setInterval(() => {
      const t = inst.telemetry; if (!t) return;
      t.samples++;
      const jitter = (Math.sin(t.samples / 2) * 0.04 + (Math.random() - 0.5) * 0.05);
      t.value = Math.round(baseline.value * (1.06 + jitter));
      t.history.push(t.value); if (t.history.length > 32) t.history.shift();
      t.vram = Math.min(targetVram, t.vram + targetVram / 6 + Math.random() * 0.3);
      t.temp = Math.min(recipe.id === 'vllm-wsl' ? 71 : 64, t.temp + 3 + Math.random() * 2);
      t.power = Math.min(recipe.id === 'vllm-wsl' ? 410 : 352, t.power + 40 + Math.random() * 10);
      render();
    }, 600);
    inst._intervals.push(iv);
    setTimer(inst, () => { clearInterval(iv); inst._intervals = inst._intervals.filter(x => x !== iv); this.goldenResult(recipe, inst, true); }, 4600);
  },

  goldenResult(recipe, inst, pass) {
    if (!pass) {
      return this.andonHalt(recipe, inst, {
        expected: 'the golden gate to pass',
        because: 'output fell outside the golden tolerance — no performance claim is made',
        pin: recipe.golden.desc, recovery: { label: 'Re-resolve', event: 'reResolve' },
      });
    }
    inst.state = TERMINAL_GOOD[recipe.kind];
    inst.pid = inst.pid || uid();
    if (recipe.kind === 'batch-producer') { inst.phase = 'artifact written + golden passed'; inst.fileHash = 'sha256:' + Math.random().toString(16).slice(2, 14); toast('Done — ' + recipe.outputPath.split('/').pop() + ' written'); }
    else if (recipe.kind === 'modifier') { inst.phase = 'overlay applied + delta measured'; toast('Applied — delta measured vs ' + recipe.target); }
    else { inst.phase = 'serving + baseline passed'; toast(recipe.name + ' is ready on :' + recipe.port); }
    render();
  },

  andonHalt(recipe, inst, andon) {
    clearTimers(inst);
    inst.state = 'halted'; inst.phase = 'HALTED'; inst.andon = andon;
    render();
    // a halt is never silent: focus the banner for screen-reader + keyboard users
    requestAnimationFrame(() => document.getElementById('andon-focus')?.focus());
  },

  // recovery: re-resolve a 404'd / stale pin -> new instance lineage -> re-run
  reResolve(recipe) {
    const inst = ensureInstance(recipe);
    inst.lineage = recipe.trust.resolveFix
      ? { from: recipe.trust.resolveFix.from, to: recipe.trust.resolveFix.to }
      : { from: 'stale lock', to: 're-resolved lock' };
    inst.andon = null; inst.preflightOk = false;
    toast('Re-resolving on a fresh channel…');
    // SIDE EFFECT: mint a NEW instance pinned to the working channel, then re-probe.
    this.preflight(recipe);
  },

  fixFloor(recipe) {
    const floor = recipe.defectFloor;
    if (!floor) { this.preflight(recipe); return; }
    let { key } = defectFloorField(recipe);
    // If no field drives the floor, write to the dep key so the retry clears it.
    if (!key) key = floor.dep;
    const target = defectFloorTargetVersion(recipe, key);
    draftFor(recipe)[key] = target;
    toast(`${floor.dep} set to ${target} — retrying preflight`, 'warn');
    this.preflight(recipe);
  },

  // ready->stale drift (cheap re-probe, not a full re-measure)
  driftDetected(recipe) {
    const inst = STATE.instances[recipe.id];
    if (!inst || inst.state !== 'ready') return;
    inst.state = 'stale';
    inst.phase = 'driver bumped 581 → 610.47 — outside compat band';
    inst.lineage = { from: 'R581 baseline', to: 'R610.47 (re-probe)' };
    render();
  },
  reProbe(recipe) {
    const inst = STATE.instances[recipe.id];
    if (!inst) return;
    inst.state = 'measuring'; inst.phase = 're-probing (cheap, 256-tok)';
    render();
    setTimer(inst, () => { inst.state = 'ready'; inst.phase = 'within 5% — baseline still valid'; inst.lineage = null; toast('Re-probe OK — perf within 5%'); render(); }, 1600);
  },

  // executor connection dropped: in-flight work can no longer be observed. Stop
  // every busy instance's timers (gauges must NOT keep streaming under a
  // read-only label) and move it to a 'disconnected' limbo with an honest notice.
  goOffline() {
    let stopped = 0;
    for (const inst of Object.values(STATE.instances)) {
      if (BUSY.has(inst.state)) {
        clearTimers(inst);
        inst._wasBusy = inst.state;          // remember what was running, for reconnect
        inst.state = 'disconnected';
        inst.phase = 'executor disconnected mid-flight — last reading frozen; outcome unknown';
        inst.preflightOk = false;
        stopped++;
      }
    }
    if (stopped) toast(`Executor disconnected — ${stopped} in-flight run${stopped > 1 ? 's' : ''} frozen (no gauges stream offline).`, 'warn');
  },
  // executor reconnected: a frozen instance can't silently resume — it must be
  // re-driven from a clean state. Reset disconnected instances to idle so the
  // user re-preflights (the executor may have changed underneath us).
  goOnline() {
    for (const inst of Object.values(STATE.instances)) {
      if (inst.state === 'disconnected') {
        clearTimers(inst);
        inst.state = 'idle'; inst.phase = ''; inst.telemetry = null; inst.steps = [];
        inst.preflightOk = false; inst._wasBusy = null;
      }
    }
  },

  // stop / teardown: run compensators newest-first
  beginTeardown(recipe) {
    const inst = STATE.instances[recipe.id];
    if (!inst) return;
    // identity-verified confirm for a server stop (names what's being stopped)
    if (recipe.kind === 'launchable-server' && inst.state === 'ready') {
      STATE.modal = { type: 'stop', recipeId: recipe.id, onConfirm: () => { STATE.modal = null; this._teardown(recipe, inst); } };
      render(); return;
    }
    this._teardown(recipe, inst);
  },
  _teardown(recipe, inst) {
    clearTimers(inst);
    inst.state = 'tearing-down'; inst.phase = 'running compensators (newest-first)';
    const order = [...inst.ledger].reverse();      // newest-first
    inst._teardownQueue = order; render();
    const step = (k) => {
      if (k >= order.length) {
        inst.ledger = []; inst.telemetry = null; inst.steps = []; inst.state = 'idle';
        inst.phase = ''; inst.preflightOk = false; inst.pid = null; inst.andon = null; inst.lineage = null;
        toast('Torn down — rig is clean'); render(); return;
      }
      inst._teardownAt = k; render();
      setTimer(inst, () => step(k + 1), 800);
    };
    setTimer(inst, () => step(0), 500);
  },

  // rollback from a halt: replay the ledger (same machinery, different banner)
  rollback(recipe) {
    const inst = STATE.instances[recipe.id];
    if (!inst || !inst.ledger.length) return;
    inst.state = 'rolling-back'; inst.phase = 'replaying compensators from the ledger'; inst.andon = null;
    const order = [...inst.ledger].reverse();
    inst._teardownQueue = order; render();
    const step = (k) => {
      if (k >= order.length) {
        inst.ledger = []; inst.telemetry = null; inst.steps = []; inst.state = 'idle';
        inst.phase = ''; inst.preflightOk = false; toast('Rolled back — ledger replayed clean'); render(); return;
      }
      inst._teardownAt = k; render();
      setTimer(inst, () => step(k + 1), 800);
    };
    setTimer(inst, () => step(0), 400);
  },
};

/* ---- small utils ---- */
function activeBaseline(recipe) {
  const d = draftFor(recipe);
  const list = recipe.baselines || [];
  // empty baselines is contract-valid (modifier/router) — fall back to a neutral
  // readout instead of crashing the live-telemetry gauges on `baseline.value`.
  // null-safe: a baseline may be model-INDEPENDENT (model===null/undefined) — the
  // data contract + the Python _select_baseline both permit NULL-model baselines,
  // so guard both sides of startsWith instead of throwing on b.model.
  return list.find(b => (b.model || '').startsWith(d.model || '')) || list[0]
    || { model: '—', value: 0, unit: recipe.axis === 'tok_s' ? 'tok/s' : '', bound: 'lower' };
}
function cmpVer(a, b) {
  const pa = String(a).split('.').map(Number), pb = String(b).split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] || 0, y = pb[i] || 0; if (x !== y) return x < y ? -1 : 1;
  } return 0;
}

/* Generic resolver for the draft field a defect floor governs. The floor's
 * `dep` (e.g. "wsl2") may not equal the form's param key (e.g. "wsl"), so we
 * match by key, then by an open-tier param whose options/value are version
 * strings. Returns { key, cur } with key=null when no field drives the floor.
 * Used by BOTH the preflight check and fixFloor, so the recovery is templated
 * from defectFloor — never hardcoded to "wsl". */
function defectFloorField(recipe) {
  const floor = recipe.defectFloor;
  if (!floor) return { key: null, cur: undefined };
  const d = draftFor(recipe);
  const isVer = v => /^\d+(\.\d+)+$/.test(String(v ?? ''));
  // 1. exact draft key
  if (d[floor.dep] != null) return { key: floor.dep, cur: d[floor.dep] };
  // 2. a param whose key is a prefix/suffix of dep (wsl2 <-> wsl), versioned
  const params = recipe.params || [];
  const dep = String(floor.dep).toLowerCase();
  const related = params.find(p => {
    const k = String(p.key).toLowerCase();
    return (dep.startsWith(k) || k.startsWith(dep)) && (isVer(d[p.key]) || (p.options || []).some(isVer));
  });
  if (related) return { key: related.key, cur: d[related.key] };
  // 3. any open-tier versioned param (last resort)
  const verParam = params.find(p => !p.locked && (isVer(d[p.key]) || (p.options || []).some(isVer)));
  if (verParam) return { key: verParam.key, cur: d[verParam.key] };
  return { key: null, cur: undefined };
}
/* Smallest offered version that clears the floor (so fixFloor sets a real,
 * selectable value), else floor.min bumped to satisfy cmpVer. */
function defectFloorTargetVersion(recipe, key) {
  const floor = recipe.defectFloor;
  const param = (recipe.params || []).find(p => p.key === key);
  const opts = (param && param.options || []).filter(o => /^\d+(\.\d+)+$/.test(String(o)));
  const clearing = opts.filter(o => cmpVer(o, floor.min) >= 0).sort(cmpVer);
  if (clearing.length) return clearing[0];
  // no offered option clears it — synthesize min's next patch (2.7.0 -> 2.7.1)
  const parts = String(floor.min).split('.').map(Number);
  parts[parts.length - 1] = (parts[parts.length - 1] || 0) + 1;
  return parts.join('.');
}

/* constraint validation for the config form (changeParam guard)
 * Guards key off the ACTUAL field keys the form emits (model/port/ctx/flash/
 * conc/wsl/src/quant/calib/target/res) and live recipe/rig data — never a
 * phantom key the form never produces (that would fail-open). */
function validateDraft(recipe) {
  const d = draftFor(recipe);
  // hard constraint: a recipe pinned to a 12.x / cu12x toolchain conflicts with a
  // cuda-13 rig. Derive the cuda version from real data — the recipe's pinned
  // compat band vs the live RIG cuda — not a non-existent form field.
  const rigCuda = String(RIG.cuda || '');
  const pinnedCuda = String(recipe.compat && recipe.compat.cuda || '');
  if (/^13\./.test(rigCuda) && /(?:^|\D)12\.|cu12/i.test(pinnedCuda))
    return { ok: false, why: `CUDA ${rigCuda} (rig) conflicts with this recipe's pinned ${pinnedCuda} toolchain.` };
  // modifier conflict: conflictsWhen names the target's BACKEND that hard-crashes
  // the overlay (e.g. "target backend == fp16_cuda ..."). d.target is the 'Apply
  // to' field — a TARGET RECIPE ID, not a backend token — so comparing d.target to
  // the backend token can never match (dead guard). Resolve d.target to its recipe
  // and compare ITS backend field against the conflict token, so the guard fires
  // when the applied-to recipe's backend is the conflicting one.
  if (recipe.kind === 'modifier' && recipe.conflictsWhen) {
    const m = recipe.conflictsWhen.match(/==\s*([a-z0-9_]+)/i);
    const conflictTarget = m && m[1];
    const targetBackend = recipeById(d.target) && recipeById(d.target).backend;
    if (conflictTarget && targetBackend === conflictTarget)
      return { ok: false, why: `Conflicts: ${d.target}'s ${conflictTarget} backend hard-crashes with this overlay.` };
  }
  return { ok: true };
}
