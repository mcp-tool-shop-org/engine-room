#!/usr/bin/env node
// Build the single-file standalone: dist/control-panel.html, inlined from the sources.
// Zero dependencies. Inlines styles.css into a <style> and data.js/engine.js/ui.js into
// <script> blocks (preserving load order), producing a self-contained, offline HTML with no
// runtime unpacker. Run after editing any app/ source:  node build.mjs
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const read = (f) => readFileSync(join(HERE, f), 'utf8');

// Inlined <script> content must not contain a literal </script> (or <!--) that would close the tag early.
const safeJs = (s) => s.replace(/<\/(script)/gi, '<\\/$1').replace(/<!--/g, '<\\!--');

let html = read('index.html');
const css = read('styles.css');

// 1) stylesheet link -> inline <style>
html = html.replace(/<link rel="stylesheet" href="styles\.css"\s*\/?>/,
  `<style>\n${css}\n</style>`);

// 2) drop the Claude-Design canvas thumbnail template (not needed in the standalone)
html = html.replace(/<template id="__bundler_thumbnail">[\s\S]*?<\/template>\s*/,'');

// 3) external scripts -> inline (preserve order: data -> engine -> ui)
for (const f of ['data.js', 'engine.js', 'ui.js']) {
  const tag = new RegExp(`<script src="${f.replace('.', '\\.')}"></script>`);
  if (!tag.test(html)) throw new Error(`source tag for ${f} not found in index.html`);
  html = html.replace(tag, `<script>\n${safeJs(read(f))}\n</script>`);
}

const out = join(HERE, 'dist', 'control-panel.html');
mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, html);
console.log(`built ${out}  (${(html.length / 1024).toFixed(1)} KB, fully inlined, offline)`);
