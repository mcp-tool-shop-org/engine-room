"""Shared, stdlib-only test fixtures for the engine-room executor test suite.

No third-party deps (the core is stdlib-only; tests stay stdlib-only too — `unittest`).
Two helpers the per-domain test modules build on:

  build_min_db(path) -> path
      Writes a minimal recipe DB (the 7 tables recipes.py reads) with a known, small
      row set covering the audit's fix cases:
        'llama-main'  launchable-server / native-win-compile / tok_s, verified+executable.
                      TWO tok_s LOWER baselines (Qwen3-4B=286.0, Qwen3-30B-A3B=334.0) — exercises
                      model-keyed baseline selection. One release-asset artifact, one auto compensator.
        'cuda13-trap' launchable-server / native-win-compile / tok_s. conflicts_when 'cuda_toolkit>=13.0'.
        'img-upper'   batch-producer / venv / s_per_img. ONE UPPER baseline (sdxl=5.0 s/img) — exercises
                      bound-direction handling in the measure gate.
        'arch-floor'  launchable-server / native-win-compile / tok_s. capability 'gpu_arch>=sm_130'.
        'wsl-floor'   launchable-server / wsl2-docker / tok_s. defect_floor 'wsl2>=2.7.0' (halt/warn/pass triad).
        'toolkit-12-8' launchable-server / native-win-compile / tok_s. capability 'cuda_toolkit==12.8' (warn/halt).
        'indep-base'  batch-producer / venv / bits_per_weight. ONE model-INDEPENDENT (NULL-model) baseline.
        'unmapped-expr' launchable-server / native-win-compile. requires_when 'torch_cuda==cu130' (no evaluator handler).

  fake_rig(**overrides) -> rig.Rig
      A Blackwell-default Rig you can override per-field, so resolve()/provider tests don't
      shell out to nvidia-smi.
"""
from __future__ import annotations
import os
import sqlite3
import sys

# make `executor` importable no matter where unittest is invoked from
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from executor import rig as _rig  # noqa: E402

_SHA64 = "a" * 64  # a full-length placeholder sha256 (distinct from the DB's NULL/'<sha256>' pins)

_DDL = """
CREATE TABLE categories (id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
                         description TEXT, sort INTEGER DEFAULT 0);
CREATE TABLE recipes (
  id INTEGER PRIMARY KEY, slug TEXT UNIQUE NOT NULL, name TEXT NOT NULL, engine_slug TEXT,
  category_id INTEGER REFERENCES categories(id), recipe_kind TEXT NOT NULL, backend_kind TEXT,
  measured_axis TEXT, toolchain_ref TEXT, summary TEXT, body TEXT,
  verified INTEGER DEFAULT 0, verify_note TEXT, resolvable_ok INTEGER, resolvable_checked TEXT,
  wave_id INTEGER, created_date TEXT, executable INTEGER DEFAULT 1);
CREATE TABLE recipe_baselines (
  id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL, model_name TEXT, model_quant TEXT, model_sha TEXT,
  context_len INTEGER, axis TEXT NOT NULL, bound_dir TEXT, value REAL, unit TEXT, vram_peak_gb REAL,
  temp_peak_c REAL, power_peak_w REAL, samples INTEGER, threshold_model TEXT, compat_band TEXT,
  measured_date TEXT, measured_note TEXT, verified INTEGER DEFAULT 0);
CREATE TABLE recipe_constraints (
  id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL, ctype TEXT NOT NULL, expr TEXT NOT NULL, reason TEXT);
CREATE TABLE recipe_artifacts (
  id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL, kind TEXT, ref TEXT NOT NULL, sha256 TEXT,
  store_expect TEXT, abi_tuple TEXT, resolvable_ok INTEGER, checked_date TEXT, note TEXT);
CREATE TABLE recipe_compensators (
  id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL, step TEXT NOT NULL, undo_cmd TEXT, post_state TEXT,
  owner TEXT, compensatable TEXT NOT NULL, note TEXT);
CREATE TABLE recipe_techniques (
  id INTEGER PRIMARY KEY, recipe_id INTEGER NOT NULL, kb TEXT NOT NULL DEFAULT 'training-knowledge',
  technique_slug TEXT NOT NULL, technique_name TEXT, technique_cat TEXT, note TEXT);
"""


def build_min_db(path: str) -> str:
    """Create a minimal recipe DB at `path`. Overwrites if present. Returns `path`."""
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    cur = con.cursor()
    cur.executescript(_DDL)
    cur.execute("INSERT INTO categories(id,slug,name) VALUES (1,'llm-inference','LLM inference')")
    cur.execute("INSERT INTO categories(id,slug,name) VALUES (2,'diffusion','Diffusion')")

    # 1) llama-main — two model-keyed lower baselines, an artifact, a compensator
    cur.execute("""INSERT INTO recipes(id,slug,name,engine_slug,category_id,recipe_kind,backend_kind,
                   measured_axis,summary,body,verified,executable)
                   VALUES (1,'llama-main','llama.cpp main','llama.cpp',1,'launchable-server',
                   'native-win-compile','tok_s','llama.cpp native serve','',1,1)""")
    cur.executemany("""INSERT INTO recipe_baselines(recipe_id,model_name,axis,bound_dir,value,unit,compat_band)
                       VALUES (?,?,?,?,?,?,?)""", [
        (1, 'Qwen3-4B',       'tok_s', 'lower', 286.0, 'tok/s', 'driver>=R570; cuda 12.8; sm_120'),
        (1, 'Qwen3-30B-A3B',  'tok_s', 'lower', 334.0, 'tok/s', 'driver>=R570; cuda 12.8; sm_120'),
    ])
    cur.execute("""INSERT INTO recipe_artifacts(recipe_id,kind,ref,sha256,store_expect,resolvable_ok)
                   VALUES (1,'release-asset','https://example.invalid/llama-b1234-cuda.zip',?,'index',1)""",
                (_SHA64,))
    cur.execute("""INSERT INTO recipe_compensators(recipe_id,step,undo_cmd,post_state,owner,compensatable)
                   VALUES (1,'launch','stop server (identity-verified)','our server stopped; others untouched',
                   'executor-module','auto')""")

    # 2) cuda13-trap — the conflicts_when constraint H1 must HALT on a CUDA-13 rig
    cur.execute("""INSERT INTO recipes(id,slug,name,category_id,recipe_kind,backend_kind,measured_axis,
                   summary,body,verified,executable)
                   VALUES (2,'cuda13-trap','avoid the 13.x MMQ trap',1,'launchable-server',
                   'native-win-compile','tok_s','pin 12.8',' ',1,1)""")
    cur.execute("""INSERT INTO recipe_constraints(recipe_id,ctype,expr,reason)
                   VALUES (2,'conflicts_when','cuda_toolkit>=13.0','13.x MMQ regression on Blackwell')""")

    # 3) img-upper — an UPPER-bound baseline (lower is better) for the measure-gate direction test
    cur.execute("""INSERT INTO recipes(id,slug,name,category_id,recipe_kind,backend_kind,measured_axis,
                   summary,body,verified,executable)
                   VALUES (3,'img-upper','sdxl image producer',2,'batch-producer','venv','s_per_img',
                   'produce an image',' ',1,1)""")
    cur.execute("""INSERT INTO recipe_baselines(recipe_id,model_name,axis,bound_dir,value,unit)
                   VALUES (3,'sdxl','s_per_img','upper',5.0,'s/img')""")

    # 4) arch-floor — a gpu_arch capability with a HIGHER floor than the rig (M3 operator test)
    cur.execute("""INSERT INTO recipes(id,slug,name,category_id,recipe_kind,backend_kind,measured_axis,
                   summary,body,verified,executable)
                   VALUES (4,'arch-floor','needs newer silicon',1,'launchable-server','native-win-compile',
                   'tok_s','future arch',' ',1,1)""")
    cur.execute("""INSERT INTO recipe_constraints(recipe_id,ctype,expr,reason)
                   VALUES (4,'capability','gpu_arch>=sm_130','needs Blackwell-next')""")

    # 5) wsl-floor — a defect_floor 'wsl2>=2.7.0' for the constraint-evaluation triad (halt/warn/pass)
    cur.execute("""INSERT INTO recipes(id,slug,name,category_id,recipe_kind,backend_kind,measured_axis,
                   summary,body,verified,executable)
                   VALUES (5,'wsl-floor','vLLM under WSL2',1,'launchable-server','wsl2-docker','tok_s',
                   'linux-first serve',' ',1,1)""")
    cur.execute("""INSERT INTO recipe_constraints(recipe_id,ctype,expr,reason)
                   VALUES (5,'defect_floor','wsl2>=2.7.0','WDDM graph-capture hang below 2.7')""")

    # 6) toolkit-12-8 — a positive 'cuda_toolkit==12.8' requirement (warn-when-unknown / halt-when-wrong)
    cur.execute("""INSERT INTO recipes(id,slug,name,category_id,recipe_kind,backend_kind,measured_axis,
                   summary,body,verified,executable)
                   VALUES (6,'toolkit-12-8','pin cuda 12.8',1,'launchable-server','native-win-compile','tok_s',
                   'pin 12.8',' ',1,1)""")
    cur.execute("""INSERT INTO recipe_constraints(recipe_id,ctype,expr,reason)
                   VALUES (6,'capability','cuda_toolkit==12.8','the 12.8 sweet spot')""")

    # 7) indep-base — a model-INDEPENDENT (NULL-model) baseline; applies to any running model
    cur.execute("""INSERT INTO recipes(id,slug,name,category_id,recipe_kind,backend_kind,measured_axis,
                   summary,body,verified,executable)
                   VALUES (7,'indep-base','model-independent quant',2,'batch-producer','venv','bits_per_weight',
                   'quantize',' ',1,1)""")
    cur.execute("""INSERT INTO recipe_baselines(recipe_id,model_name,axis,bound_dir,value,unit)
                   VALUES (7,NULL,'bits_per_weight','lower',4.5,'bpw')""")

    # 8) unmapped-expr — a constraint whose expr shape the evaluator has NO handler for (note vs deferred)
    cur.execute("""INSERT INTO recipes(id,slug,name,category_id,recipe_kind,backend_kind,measured_axis,
                   summary,body,verified,executable)
                   VALUES (8,'unmapped-expr','new KB constraint shape',1,'launchable-server','native-win-compile',
                   'tok_s','future expr',' ',1,1)""")
    cur.execute("""INSERT INTO recipe_constraints(recipe_id,ctype,expr,reason)
                   VALUES (8,'requires_when','torch_cuda==cu130','a KB expr shape with no evaluator handler')""")

    con.commit()
    con.close()
    return path


def fake_rig(**overrides) -> "_rig.Rig":
    """A Blackwell-default Rig. Override any field by kwarg, e.g. fake_rig(cuda_runtime=None)."""
    base = dict(
        gpu="NVIDIA GeForce RTX 5090",
        vram_gb=31.8,
        sm="sm_120",
        driver="610.47",
        cuda_runtime="13.3",   # the live driver CUDA runtime (UMD); H1's fix reads this
        cuda_toolkit=None,     # nvcc absent on the rig
        os_surface="windows",
        wsl2_version="2.7.3.0",
    )
    base.update(overrides)
    return _rig.Rig(**base)
