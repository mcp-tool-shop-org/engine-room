/* ============================================================================
 * engine-room — ui.js
 * Rendering + event wiring. render() is the single re-render entry point.
 * Interactions are realized via [data-act] delegation (see EVENT MAP in data.js).
 * ========================================================================== */

const $ = (s, r = document) => r.querySelector(s);
const esc = (s) => String(s).replace(/[&<>"]/g, c => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;' }[c]));
let booting = true;

/* ---------- badges ---------- */
function badge(cls, icon, label, tipTitle, tipMono) {
  const tip = tipTitle ? `<span class="tip"><span class="tip-k">${esc(tipTitle)}</span>${tipMono ? `<br><span class="mono">${esc(tipMono)}</span>` : ''}</span>` : '';
  return `<span class="badge ${cls}" tabindex="0" role="note" aria-label="${esc(label)}. ${esc(tipTitle || '')} ${esc(tipMono || '')}">${icon}<span>${esc(label)}</span>${tip}</span>`;
}
function trustBadges(r) {
  const t = r.trust; let h = '';
  h += t.verified
    ? badge('ok', ICON.check, 'verified', 'Claims grounded in a cited source', t.verifiedSource)
    : badge('gray', ICON.dash, 'unverified', 'No cited source backing the claims');
  h += t.resolvable === 'yes'
    ? badge('ok', ICON.check, 'resolvable', 'Pinned artifacts still install today')
    : t.resolvable === 'no'
      ? badge('bad', ICON.alert, "won't resolve", 'A pinned artifact no longer installs', t.failingPin)
      : badge('gray', ICON.dash, 'unchecked', 'Resolvability not yet probed');
  const cl = t.commercial === 'yes' ? 'ok' : t.commercial === 'conditional' ? 'warn' : 'bad';
  const lbl = t.commercial === 'yes' ? 'commercial' : t.commercial === 'conditional' ? 'conditional' : 'no commercial';
  h += badge(cl, ICON.scale, lbl, 'License', t.license);
  return h;
}

/* ---------- status pill ---------- */
function statusPill(inst) {
  if (!inst || inst.state === 'idle') return '';
  const busy = BUSY.has(inst.state);
  const label = inst.state.replace(/-/g, ' ');
  return `<span class="status-pill" data-s="${inst.state}" data-busy="${busy}"><span class="sdot"></span>${esc(label)}</span>`;
}

/* ---------- catalog ---------- */
function filtered() {
  const f = STATE.filters, q = f.q.trim().toLowerCase();
  return RECIPES.filter(r => {
    if (q && !(`${r.name} ${r.blurb} ${r.backend} ${r.kind}`.toLowerCase().includes(q))) return false;
    if (f.kind && r.kind !== f.kind) return false;
    if (f.verified && !r.trust.verified) return false;
    if (f.resolvable && r.trust.resolvable !== 'yes') return false;
    if (f.commercial && r.trust.commercial !== 'yes') return false;
    return true;
  });
}
function card(r) {
  const inst = STATE.instances[r.id];
  const running = inst && inst.state !== 'idle';
  const km = KIND_META[r.kind];
  const base = r.baselines[0];
  const baseTxt = r.kind === 'modifier'
    ? `Δ +${r.deltas[r.deltas.length - 1].pct}% @ ${r.deltas[r.deltas.length - 1].at}`
    : r.kind === 'router-fleet'
      ? `${r.upstreams.length} upstreams`
      : base ? `${base.value} <b>${base.unit}</b>` : '';
  return `<button class="card needs-exec-soft" role="option" aria-selected="${STATE.selectedId === r.id}" data-running="${!!running}" data-act="select" data-id="${r.id}">
    <div class="card-top">
      <span class="kind-tag" data-kind="${r.kind}">${km.label}</span>
      <span class="card-name">${esc(r.name)}</span>
      ${statusPill(inst)}
    </div>
    <div class="card-blurb">${esc(r.blurb)}</div>
    <div class="badges">${trustBadges(r)}</div>
    <div class="card-foot">
      <span class="lane">${r.backend || 'inherits target'}</span>
      <span class="baseline-mini">${baseTxt}</span>
    </div>
  </button>`;
}
function renderCatalog() {
  const wrap = $('#catalog');
  if (booting) {
    wrap.innerHTML = Array.from({ length: 4 }).map(() =>
      `<div class="card" aria-hidden="true"><div class="skeleton" style="height:14px;width:60%"></div><div class="skeleton" style="height:12px;width:90%"></div><div class="skeleton" style="height:22px;width:50%"></div></div>`).join('');
    return;
  }
  const list = filtered();
  if (!list.length) {
    wrap.innerHTML = `<div class="empty-state">${ICON.empty}<div style="font-weight:600;color:var(--ink-dim)">No recipes match</div><div class="tiny">Clear a filter to widen the catalog.</div></div>`;
    return;
  }
  wrap.innerHTML = list.map(card).join('');
}

/* ---------- gauges ---------- */
function sparkline(history, baselineV, breachLow) {
  if (!history.length) return '';
  const all = history.concat([baselineV]);
  const min = Math.min(...all) * 0.97, max = Math.max(...all) * 1.03, span = (max - min) || 1;
  const y = v => 44 - ((v - min) / span) * 40 + 2;
  const stepX = history.length > 1 ? 100 / (history.length - 1) : 0;
  const pts = history.map((v, i) => `${(i * stepX).toFixed(1)},${y(v).toFixed(1)}`);
  const last = history[history.length - 1];
  const breach = breachLow && last < baselineV;
  const area = `M0,46 L${pts.map(p => 'L' + p).join(' ').slice(1)} L100,46 Z`.replace('LL', 'L');
  return `<svg class="spark" viewBox="0 0 100 48" preserveAspectRatio="none" aria-hidden="true">
    <path class="fill" d="M0,46 ${pts.map(p => 'L' + p).join(' ')} L100,46 Z"/>
    <line class="base-line" x1="0" x2="100" y1="${y(baselineV).toFixed(1)}" y2="${y(baselineV).toFixed(1)}"/>
    <polyline class="trace ${breach ? 'breach' : ''}" points="${pts.join(' ')}"/>
  </svg>`;
}
function serverGauges(r, inst) {
  const t = inst.telemetry; if (!t) return '';
  const breachAxis = t.value < t.baseline.value;
  const vramPct = Math.min(100, (t.vram / t.vramCeiling) * 100);
  const vramBreach = t.vram > t.vramCeiling;
  const tickPct = 100; // ceiling tick at far right
  return `<div class="gauges">
    <div class="gauge ${breachAxis ? 'breach' : 'ok'}">
      <div class="gauge-h"><span class="gauge-k">${t.axis === 'tok_s' ? 'throughput' : t.axis}</span>
        <span class="tiny mono muted">baseline ≥ ${t.baseline.value} ${t.baseline.unit}</span></div>
      <div class="gauge-v mono">${t.value}<span class="unit">${t.baseline.unit}</span></div>
      ${sparkline(t.history, t.baseline.value, true)}
      <div class="gauge-sub"><span>${esc(t.baseline.model)}</span><span>${breachAxis ? 'BELOW baseline' : '+' + Math.round((t.value / t.baseline.value - 1) * 100) + '% vs bound'}</span></div>
    </div>
    <div class="gauge ${vramBreach ? 'breach' : 'ok'}">
      <div class="gauge-h"><span class="gauge-k">VRAM</span><span class="tiny mono muted">ceiling ${t.vramCeiling} GB</span></div>
      <div class="gauge-v mono">${t.vram.toFixed(1)}<span class="unit">/ ${t.vramCeiling} GB</span></div>
      <div class="meter" style="margin-top:14px"><div class="meter-fill ${vramBreach ? 'breach' : ''}" style="width:${vramPct}%"></div><div class="meter-tick" data-label="ceil" style="left:${tickPct}%"></div></div>
      <div class="gauge-sub"><span>temp ${Math.round(t.temp)}°C</span><span>${Math.round(t.power)} W</span></div>
    </div>
  </div>`;
}

/* ---------- steps ---------- */
function stepsList(inst) {
  if (!inst.steps.length) return '';
  return `<ul class="steps">${inst.steps.map(s => `<li class="step" data-st="${s.status}">
    <span class="step-ico">${s.status === 'ok' ? ICON.check : s.status === 'fail' ? ICON.x : ''}</span>
    <span class="step-body"><div class="step-label">${esc(s.label)}</div><div class="step-cmd mono">${esc(s.cmd)}</div></span>
  </li>`).join('')}</ul>`;
}

/* ---------- compensator ledger ---------- */
function ledgerRows(inst, teardown) {
  if (!inst.ledger.length) return `<div class="tiny muted">No destructive steps yet — nothing to undo.</div>`;
  const q = inst._teardownQueue;
  return `<div class="ledger">${inst.ledger.map((c, i) => {
    let running = '';
    if (teardown && q) {
      const idxInQ = q.findIndex(x => x.id === c.id);
      if (idxInQ < inst._teardownAt) running = 'done';
      else if (idxInQ === inst._teardownAt) running = 'active';
    }
    return `<div class="comp-row">
      <div class="comp-top"><span class="comp-label">${esc(c.label)}</span>${c.human_gated ? '<span class="comp-gate">human-gated</span>' : ''}
        ${running === 'active' ? '<span class="btn-spin spin" style="width:13px;height:13px;border-color:var(--cyan);border-right-color:transparent;margin-left:auto"></span>' : running === 'done' ? '<span style="margin-left:auto;color:var(--accent)">'+ICON.check.replace('24 24','24 24')+'</span>' : ''}</div>
      <div class="comp-cmd mono">$ ${esc(c.cmd)}</div>
      <div class="comp-post">post-state: <b>${esc(c.postState)}</b></div>
    </div>`;
  }).join('')}</div>`;
}

/* ---------- ANDON banner ---------- */
function andonBanner(r, inst) {
  if (!inst || !inst.andon) return '';
  const a = inst.andon;
  const canRollback = inst.ledger.length > 0;
  return `<div class="andon" role="alert" id="andon-focus" tabindex="-1">
    <div class="andon-top"><span class="andon-light"></span><span class="andon-title">${ICON.alert} Andon — line stopped</span></div>
    <div class="andon-contrast"><span class="exp">You expected ${esc(a.expected)} —</span> <span class="because">it halted because ${esc(a.because)}.</span>
      ${a.pin ? `<span class="pin mono">${esc(a.pin)}</span>` : ''}</div>
    <div class="andon-actions">
      <button class="btn btn-danger needs-exec" data-act="${a.recovery.event}" data-id="${r.id}">${esc(a.recovery.label)}</button>
      ${canRollback ? `<button class="btn btn-ghost needs-exec" data-act="rollback" data-id="${r.id}">Roll back ${inst.ledger.length} step${inst.ledger.length > 1 ? 's' : ''}</button>` : `<button class="btn btn-ghost" data-act="deselect">Dismiss</button>`}
    </div>
  </div>`;
}

/* ---------- config form ---------- */
function configForm(r) {
  const d = draftFor(r);
  return `<div class="form-grid">${r.params.map(p => {
    const locked = p.locked;
    const id = `f-${r.id}-${p.key}`;
    let control;
    if (p.options) {
      control = `<select id="${id}" data-act="param" data-id="${r.id}" data-key="${p.key}" ${locked ? 'disabled' : ''}>${p.options.map(o => `<option ${String(o) === String(d[p.key]) ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select>`;
    } else {
      control = `<input id="${id}" value="${esc(d[p.key])}" data-act="param" data-id="${r.id}" data-key="${p.key}" ${locked ? 'readonly' : ''} ${typeof p.value === 'number' ? 'inputmode="numeric"' : ''}>`;
    }
    return `<div class="field" data-locked="${locked}">
      <label for="${id}">${esc(p.label)} ${locked ? '<span class="lock has-tip" tabindex="0">locked'+(p.help?`<span class="tip"><span class="tip-k">default-tier</span><br>${esc(p.help)}</span>`:'')+'</span>' : ''}</label>
      ${control}
    </div>`;
  }).join('')}</div>`;
}

/* ---------- polymorphic "instrument" section per kind ---------- */
function instrument(r, inst) {
  if (!inst) return '';
  const measuring = ['measuring'].includes(inst.state);
  const terminal = ['ready', 'done', 'applied', 'stale'].includes(inst.state);

  if (r.kind === 'router-fleet' && inst.telemetry?.upstreams) {
    const ups = inst.telemetry.upstreams;
    return `<div class="section"><h3 class="section-h">Fleet — per-upstream health</h3>
      <div class="panel-box"><table class="fleet"><thead><tr><th>Upstream</th><th>Order</th><th>Required</th><th>Health</th></tr></thead>
      <tbody>${ups.map(u => `<tr><td>${esc(u.name)}</td><td class="order">${u.order}</td><td class="req">${u.required ? 'required' : 'optional'}</td>
        <td><span class="health-dot ${u.health}"></span><span class="mono tiny">${u.health === 'green' ? 'healthy' : u.health === 'amber' ? 'starting' : 'down'}</span></td></tr>`).join('')}</tbody></table>
      <div class="tiny muted mt12">Router stays <b>not-ready</b> until every required upstream is green. Teardown is refcounted — it stops the front only.</div></div></div>`;
  }
  if (r.kind === 'modifier' && inst.telemetry?.delta) {
    return `<div class="section"><h3 class="section-h">Measured delta vs unmodified ${esc(r.target)}</h3>
      <div class="delta-wrap">${inst.telemetry.delta.map(dd => `<div class="delta-card"><div class="delta-res">@ ${esc(dd.at)}</div><div class="delta-val">+${dd.pct}%</div><div class="delta-bar"><span style="width:${Math.min(100, dd.pct * 3)}%"></span></div></div>`).join('')}</div>
      <div class="tiny muted mt12">No port, no server, no self-baseline — a modifier is judged purely by its delta against the base.</div></div>`;
  }
  if (r.kind === 'batch-producer' && (terminal || inst.telemetry?.bpw)) {
    const t = inst.telemetry || {};
    const wall = Math.round((inst.steps.reduce((a, s) => a + (s.dur || 0), 0)) / 1000 * 9.4);
    const written = inst.state === 'done';
    return `<div class="section"><h3 class="section-h">Producer output</h3>
      <div class="gauges" style="margin-bottom:14px">
        <div class="gauge ok"><div class="gauge-h"><span class="gauge-k">bits / weight</span><span class="tiny mono muted">target ≤ ${t.bpwCeil || 4.6}</span></div><div class="gauge-v mono">${(t.bpw || r.baselines[0].value)}<span class="unit">bpw</span></div><div class="meter mt12"><div class="meter-fill" style="width:${((t.bpw||4.52)/(t.bpwCeil||4.6))*100}%"></div><div class="meter-tick" data-label="ceil" style="left:100%"></div></div></div>
        <div class="gauge"><div class="gauge-h"><span class="gauge-k">build wall-clock</span></div><div class="gauge-v mono">${wall}<span class="unit">s</span></div><div class="gauge-sub mt12"><span>golden: ${esc(r.golden.kind)}</span><span>${written ? 'PASS' : '—'}</span></div></div>
      </div>
      <div class="outfile ${written ? 'written' : ''}">${written ? ICON.check : ICON.dash}<span class="mono">${esc(r.outputPath)}</span>${written ? `<span class="hash mono">${esc(inst.fileHash || '')}</span>` : '<span class="hash">not written yet</span>'}</div>
    </div>`;
  }
  if (r.kind === 'launchable-server' && inst.telemetry && (measuring || inst.state === 'ready')) {
    return `<div class="section"><h3 class="section-h">Live telemetry — instrument readout</h3>${serverGauges(r, inst)}
      <div class="tiny muted mt12">Green = inside the bound, red = breached. Axis vs baseline and VRAM vs ceiling shown as colour <b>and</b> number.</div></div>`;
  }
  return '';
}

/* ---------- action row (polymorphic primary action) ---------- */
function actionRow(r, inst) {
  const km = KIND_META[r.kind];
  const st = inst ? inst.state : 'idle';
  const busy = BUSY.has(st);
  const offline = !STATE.online;
  const terminalGood = st === TERMINAL_GOOD[r.kind];

  if (offline) {
    return `<div class="action-row"><button class="btn" disabled>${esc(km.verb)}</button>
      <span class="action-hint">${ICON.plug} Read-only — connect an executor to run. You can still browse, configure, and inspect.</span></div>`;
  }
  if (terminalGood || st === 'stale') {
    const driftBtn = (r.kind === 'launchable-server' && st === 'ready') ? `<button class="btn btn-ghost needs-exec" data-act="drift" data-id="${r.id}" title="simulate a driver bump">Simulate drift</button>` : '';
    const staleBtn = st === 'stale' ? `<button class="btn btn-warn needs-exec" data-act="reProbe" data-id="${r.id}">Re-probe (cheap)</button>` : '';
    return `<div class="action-row">
      ${staleBtn}
      <button class="btn btn-danger needs-exec" data-act="teardown" data-id="${r.id}">${esc(km.running)}</button>
      ${driftBtn}
      <span class="action-hint">${esc(stateHint(r, inst))}</span>
    </div>`;
  }
  if (busy) {
    return `<div class="action-row"><button class="btn btn-primary" disabled><span class="spin"></span>${esc(cap(st.replace(/-/g,' ')))}…</button>
      <span class="action-hint" aria-live="polite">${esc(inst.phase)}</span></div>`;
  }
  // idle or preflight-passed
  const pfOk = inst && inst.preflightOk;
  const val = validateDraft(r);
  const canRun = pfOk && val.ok;
  return `<div class="action-row">
    <button class="btn ${pfOk ? 'btn-ghost' : 'btn-cyan'} needs-exec" data-act="preflight" data-id="${r.id}">${pfOk ? 'Re-preflight' : 'Preflight'}</button>
    <button class="btn btn-primary needs-exec" data-act="run" data-id="${r.id}" ${canRun ? '' : 'disabled'}>${esc(km.verb)}${r.kind === 'modifier' ? ' to ' + esc(draftFor(r).target) : r.port ? ' :' + draftFor(r).port : ''}</button>
    <span class="action-hint ${!val.ok ? 'err' : ''}">${!val.ok ? ICON.alert + ' ' + esc(val.why) : pfOk ? 'Preflight passed — clear to ' + km.verb.toLowerCase() + '.' : 'Run preflight to resolve the lock and probe artifacts before any long work.'}</span>
  </div>`;
}
function stateHint(r, inst) {
  if (inst.state === 'ready') return r.kind === 'router-fleet' ? 'Router up — all required upstreams healthy.' : 'Serving on :' + r.port + ' (pid ' + inst.pid + ') — baseline passed.';
  if (inst.state === 'done') return 'Artifact written + golden passed.';
  if (inst.state === 'applied') return 'Overlay applied to ' + r.target + ' — delta measured.';
  if (inst.state === 'stale') return inst.phase;
  return '';
}
const cap = s => s.charAt(0).toUpperCase() + s.slice(1);

/* ---------- detail pane ---------- */
function renderDetail(animate) {
  const col = $('#detail');
  const r = recipeById(STATE.selectedId);
  if (!r) {
    col.innerHTML = `<div class="detail-empty">${ICON.reactor}<div style="font-weight:600;font-size:15px;color:var(--ink-dim)">Select a recipe</div><div class="tiny mt8">Pick an engine recipe from the catalog to see what it is, what it will do, and how to stand it up on your rig.</div></div>`;
    return;
  }
  const inst = STATE.instances[r.id];
  const km = KIND_META[r.kind];
  const contradiction = r.trust.verified && r.trust.resolvable === 'no';
  const teardownActive = inst && (inst.state === 'tearing-down' || inst.state === 'rolling-back');

  col.innerHTML = `<div class="detail ${animate ? 'anim' : ''}">
    <div class="detail-scroll">
      <div class="dh-top">
        <div style="flex:1">
          <div class="row"><span class="kind-tag" data-kind="${r.kind}">${km.label}</span> ${statusPill(inst)}</div>
          <div class="dh-title mt8">${esc(r.name)}</div>
          <div class="dh-sub">${esc(r.blurb)}</div>
        </div>
      </div>
      <div class="dh-badges">${trustBadges(r)}</div>
      ${contradiction ? `<div class="lineage" style="background:var(--andon-dim);border-color:var(--andon);color:var(--ink)">${ICON.alert}<span>Verified <b>but won't resolve</b> — the claim is sound; the pinned artifact is gone. Re-resolve to use it.</span></div>` : ''}
      ${inst && inst.lineage ? `<div class="lineage">${ICON.check}<span>${esc(inst.lineage.from)}</span><span class="arrow">→</span><span>${esc(inst.lineage.to)}</span></div>` : ''}

      <div class="section"><h3 class="section-h">What this will do</h3>
        <ul class="willdo">${r.willDo.map((w, i) => `<li><span class="n">${i + 1}</span><span>${esc(w)}</span></li>`).join('')}</ul></div>

      <div class="section"><h3 class="section-h">Baseline &amp; compatibility</h3>
        <div class="panel-box">
          ${r.baselines.length ? `<dl class="kv">${r.baselines.map(b => `<dt>${esc(b.model)}</dt><dd>${b.value} ${b.unit} <span class="muted">· ${b.bound}-bound${b.note ? ' ' + esc(b.note) : ''}</span></dd>`).join('')}</dl>` : `<div class="tiny muted">${r.kind === 'modifier' ? 'No self-baseline — measured purely as a delta vs the target.' : 'Readiness is upstream health, not a sampled axis.'}</div>`}
          <dl class="kv mt12"><dt>compat band</dt><dd>driver ${esc(r.compat.driver)} · cuda ${esc(r.compat.cuda)} · ${esc(r.compat.sm)}</dd>
          <dt>golden gate</dt><dd>${esc(r.golden.kind)} — <span class="muted">${esc(r.golden.desc)}</span></dd>
          ${r.conflictsWhen ? `<dt>conflicts</dt><dd style="color:var(--warn)">${esc(r.conflictsWhen)}</dd>` : ''}
          ${r.defectFloor ? `<dt>defect floor</dt><dd style="color:var(--warn)">${esc(r.defectFloor.dep)} ≥ ${esc(r.defectFloor.min)}</dd>` : ''}</dl>
        </div></div>

      <div class="section"><h3 class="section-h">Configure</h3>${configForm(r)}</div>

      ${actionRow(r, inst)}

      ${inst && inst.steps.length ? `<div class="section"><h3 class="section-h">${cap((inst.phase && BUSY.has(inst.state)) ? inst.state.replace(/-/g,' ') : 'Progress')}</h3><div class="panel-box">${stepsList(inst)}</div></div>` : ''}

      ${andonBanner(r, inst)}

      ${instrument(r, inst)}

      <div class="section"><h3 class="section-h">${teardownActive ? cap(inst.state.replace(/-/g,' ')) + ' — newest first' : 'Compensators — named undo + honest post-state'}</h3>
        <div class="panel-box">${inst ? ledgerRows(inst, teardownActive) : `<div class="ledger">${r.compensators.map(c => `<div class="comp-row"><div class="comp-top"><span class="comp-label">${esc(c.label)}</span>${c.human_gated ? '<span class="comp-gate">human-gated</span>' : ''}</div><div class="comp-cmd mono">$ ${esc(c.cmd)}</div><div class="comp-post">post-state: <b>${esc(c.postState)}</b></div></div>`).join('')}</div>`}</div></div>

      <div class="section"><h3 class="section-h">Pinned artifacts</h3><div class="panel-box"><dl class="kv">${r.pins.map(p => `<dt>${esc(p.label)}</dt><dd>${esc(p.ref)} <span class="muted">${p.vendored ? '· vendored' : '· ⚠ not vendored'}</span></dd>`).join('')}</dl></div></div>
    </div>
  </div>`;
}

/* ---------- topbar / banner ---------- */
function renderChrome() {
  $('#app').dataset.online = STATE.online;
  document.documentElement.dataset.theme = STATE.theme;
  $('#theme-ico').innerHTML = STATE.theme === 'dark' ? ICON.sun : ICON.moon;
  const ex = $('#exec'); ex.dataset.online = STATE.online;
  ex.querySelector('.exec-label').textContent = STATE.online ? 'Executor connected' : 'Offline — read-only';
  $('#readonly-banner').hidden = STATE.online;
  // filter chip states
  document.querySelectorAll('[data-filter-kind]').forEach(c => c.setAttribute('aria-pressed', STATE.filters.kind === c.dataset.filterKind));
  ['verified','resolvable','commercial'].forEach(k => { const c = $(`[data-filter-flag="${k}"]`); if (c) c.setAttribute('aria-pressed', STATE.filters[k]); });
}

/* ---------- modal ---------- */
function renderModal() {
  const host = $('#modal-host');
  const m = STATE.modal;
  if (!m) { host.innerHTML = ''; return; }
  let inner = '';
  if (m.type === 'gate') {
    const c = m.comp;
    inner = `<div class="modal modal-gate" role="alertdialog" aria-labelledby="m-h" aria-describedby="m-d">
      <div class="modal-h" id="m-h"><span class="warn-ico">${ICON.alert}</span> Human gate required</div>
      <p id="m-d" class="muted mt8" style="font-size:13.5px">This step can’t be scoped to engine-room alone. Approve the blast radius before it runs.</p>
      <div class="blast"><span class="blast-k">Blast radius</span>${esc(c.blastRadius)}</div>
      <div class="comp-row"><div class="comp-top"><span class="comp-label">${esc(c.label)}</span><span class="comp-gate">human-gated</span></div><div class="comp-cmd mono">$ ${esc(c.cmd)}</div><div class="comp-post">undo post-state: <b>${esc(c.postState)}</b></div></div>
      <div class="modal-actions"><button class="btn btn-ghost" data-act="gate-cancel">Cancel</button><button class="btn btn-warn" data-act="gate-approve" autofocus>Approve — I own this</button></div>
    </div>`;
  } else if (m.type === 'stop') {
    const r = recipeById(m.recipeId); const inst = STATE.instances[m.recipeId];
    inner = `<div class="modal modal-danger" role="alertdialog" aria-labelledby="m-h" aria-describedby="m-d">
      <div class="modal-h" id="m-h"><span class="danger-ico">${ICON.alert}</span> Stop ${esc(r.name)}?</div>
      <p id="m-d" class="muted mt8" style="font-size:13.5px">Identity-verified so you don’t stop the wrong thing:</p>
      <div class="comp-row"><div class="comp-cmd mono">$ er stop --pid ${inst.pid} --port ${r.port}</div><div class="comp-post"><b>Stops engine-room’s server on :${r.port} (pid ${inst.pid})</b> — not any other ${esc(r.name.split(' ')[0])} you’re running.</div></div>
      <p class="tiny muted">Then compensators run newest-first: per-instance shim removed, PATH restored (your global PATH was never touched).</p>
      <div class="modal-actions"><button class="btn btn-ghost" data-act="stop-cancel">Keep running</button><button class="btn btn-danger" data-act="stop-confirm" autofocus>Stop &amp; tear down</button></div>
    </div>`;
  }
  host.innerHTML = `<div class="modal-scrim" data-act="scrim">${inner}</div>`;
  const f = host.querySelector('[autofocus]'); if (f) f.focus();
}

/* ---------- toasts ---------- */
let toastSeq = 0;
function toast(msg, kind) {
  const id = ++toastSeq;
  const host = $('#toasts');
  const el = document.createElement('div');
  el.className = 'toast' + (kind === 'warn' ? ' warn' : '');
  el.setAttribute('role', 'status');
  el.innerHTML = `<span class="tdot"></span><span>${esc(msg)}</span>`;
  host.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; el.style.transform = 'translateY(8px)'; setTimeout(() => el.remove(), 250); }, 3200);
}

/* ---------- master render ---------- */
function render() {
  renderChrome();
  renderCatalog();
  renderDetail(false);
  renderModal();
}

/* ============================================================================
 * EVENT WIRING
 * ========================================================================== */
function selectRecipe(id) {
  STATE.selectedId = id;
  $('#main').classList.add('detail-open');
  renderChrome(); renderCatalog(); renderDetail(true);
}

document.addEventListener('click', (e) => {
  const t = e.target.closest('[data-act]');
  if (!t) return;
  const act = t.dataset.act, id = t.dataset.id, r = id && recipeById(id);
  switch (act) {
    case 'select': selectRecipe(id); break;
    case 'deselect': { const inst = STATE.instances[STATE.selectedId]; if (inst) inst.andon = null; renderDetail(false); break; }
    case 'preflight': SIM.preflight(r); break;
    case 'run': SIM.run(r); break;
    case 'reResolve': SIM.reResolve(r); break;
    case 'fixFloor': SIM.fixFloor(r); break;
    case 'rollback': SIM.rollback(r); break;
    case 'teardown': SIM.beginTeardown(r); break;
    case 'drift': SIM.driftDetected(r); break;
    case 'reProbe': SIM.reProbe(r); break;
    case 'gate-approve': STATE.modal && STATE.modal.onApprove(); break;
    case 'gate-cancel': STATE.modal && STATE.modal.onCancel(); break;
    case 'stop-confirm': STATE.modal && STATE.modal.onConfirm(); break;
    case 'stop-cancel': STATE.modal = null; renderModal(); break;
    case 'scrim': if (e.target === t) { if (STATE.modal?.onCancel) STATE.modal.onCancel(); else { STATE.modal = null; renderModal(); } } break;
    case 'toggle-theme': STATE.theme = STATE.theme === 'dark' ? 'light' : 'dark'; localStorage.setItem('er-theme', STATE.theme); renderChrome(); break;
    case 'toggle-exec': STATE.online = !STATE.online; renderChrome(); renderDetail(false); break;
    case 'filter-kind': STATE.filters.kind = STATE.filters.kind === t.dataset.filterKind ? null : t.dataset.filterKind; renderChrome(); renderCatalog(); break;
    case 'filter-flag': STATE.filters[t.dataset.filterFlag] = !STATE.filters[t.dataset.filterFlag]; renderChrome(); renderCatalog(); break;
  }
});

// config inputs (changeParam)
document.addEventListener('input', (e) => {
  const t = e.target.closest('[data-act="param"]'); if (!t) return;
  const r = recipeById(t.dataset.id); const d = draftFor(r);
  d[t.dataset.key] = t.value;
  // re-validate + re-enable run without losing focus: just update the action row + hint
  const inst = STATE.instances[r.id];
  if (inst) inst.preflightOk = false;     // changing config invalidates preflight
  renderDetail(false);
});
document.addEventListener('input', (e) => {
  const s = e.target.closest('#search'); if (!s) return;
  STATE.filters.q = s.value; renderCatalog();
  // keep focus in the search box after re-render
  const ns = $('#search'); if (ns && ns !== s) { ns.focus(); ns.value = s.value; }
});

// keyboard: Esc closes modal; arrows move catalog selection
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && STATE.modal) { e.preventDefault(); if (STATE.modal.onCancel) STATE.modal.onCancel(); else { STATE.modal = null; renderModal(); } return; }
  if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && e.target.closest('#catalog')) {
    const list = filtered(); if (!list.length) return;
    e.preventDefault();
    let idx = list.findIndex(x => x.id === STATE.selectedId);
    idx = e.key === 'ArrowDown' ? Math.min(list.length - 1, idx + 1) : Math.max(0, idx - 1);
    selectRecipe(list[idx].id);
    requestAnimationFrame(() => $(`.card[data-id="${list[idx].id}"]`)?.focus());
  }
  // simple focus trap inside modal
  if (e.key === 'Tab' && STATE.modal) {
    const f = [...document.querySelectorAll('.modal button')]; if (!f.length) return;
    const first = f[0], last = f[f.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  }
});

/* ---------- boot ---------- */
function boot() {
  STATE.theme = localStorage.getItem('er-theme') || 'dark';
  renderChrome();
  renderCatalog();              // shows skeletons while booting
  renderDetail(false);
  // simulate catalog load
  setTimeout(() => { booting = false; renderCatalog(); }, 650);
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
else boot();
