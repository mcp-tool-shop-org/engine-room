"""Read the verified recipe layer from the tensor-engine-knowledge DB.

engine-room is the ACTION side; the recipe (knowledge) lives in the readouts KB. This module is
the read-only seam: it loads a recipe + its baselines / constraints / artifacts / compensators /
cross-KB techniques into plain dataclasses the executor acts on. It NEVER writes the KB.
"""
from __future__ import annotations
import os, sqlite3
from dataclasses import dataclass, field

# default DB location; override with --db or $ER_RECIPES_DB
_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB = os.environ.get(
    "ER_RECIPES_DB",
    os.path.normpath(os.path.join(_HERE, "..", "..", "readouts", "tensor-engine-knowledge", "engines.db")),
)


@dataclass
class Baseline:
    model: str | None; axis: str; bound: str | None; value: float | None; unit: str | None; compat_band: str | None

@dataclass
class Constraint:
    ctype: str; expr: str; reason: str | None

@dataclass
class Artifact:
    kind: str | None; ref: str; sha256: str | None; store_expect: str | None; resolvable_ok: int | None

@dataclass
class Compensator:
    step: str; undo_cmd: str | None; post_state: str | None; owner: str | None; compensatable: str

@dataclass
class Technique:
    kb: str; slug: str; name: str | None; category: str | None   # cross-KB link (training-knowledge)

@dataclass
class Recipe:
    slug: str; name: str; kind: str; backend: str | None; axis: str | None
    engine_slug: str | None; lane: str | None; summary: str | None; body: str | None
    verified: int; executable: int
    baselines: list[Baseline] = field(default_factory=list)
    constraints: list[Constraint] = field(default_factory=list)
    artifacts: list[Artifact] = field(default_factory=list)
    compensators: list[Compensator] = field(default_factory=list)
    techniques: list[Technique] = field(default_factory=list)


def _conn(db: str):
    if not os.path.exists(db):
        raise SystemExit(f"recipe DB not found: {db}\n  set $ER_RECIPES_DB or pass --db")
    return sqlite3.connect(f"file:{db}?mode=ro", uri=True)


def list_recipes(db: str = DEFAULT_DB, executable_only: bool = True) -> list[Recipe]:
    con = _conn(db); cur = con.cursor()
    where = "where r.executable=1" if executable_only else ""
    rows = cur.execute(f"""select r.slug from recipes r {where} order by r.recipe_kind, r.slug""").fetchall()
    con.close()
    return [load_recipe(s, db) for (s,) in rows]


def load_recipe(slug: str, db: str = DEFAULT_DB) -> Recipe | None:
    con = _conn(db); cur = con.cursor()
    row = cur.execute("""select r.id, r.slug, r.name, r.recipe_kind, r.backend_kind, r.measured_axis,
                                r.engine_slug, c.slug, r.summary, r.body, r.verified, r.executable
                         from recipes r left join categories c on c.id=r.category_id
                         where r.slug=?""", (slug,)).fetchone()
    if not row:
        con.close(); return None
    rid = row[0]
    rec = Recipe(slug=row[1], name=row[2], kind=row[3], backend=row[4], axis=row[5],
                 engine_slug=row[6], lane=row[7], summary=row[8], body=row[9],
                 verified=row[10], executable=row[11])
    rec.baselines = [Baseline(*r) for r in cur.execute(
        "select model_name,axis,bound_dir,value,unit,compat_band from recipe_baselines where recipe_id=?", (rid,))]
    rec.constraints = [Constraint(*r) for r in cur.execute(
        "select ctype,expr,reason from recipe_constraints where recipe_id=?", (rid,))]
    rec.artifacts = [Artifact(*r) for r in cur.execute(
        "select kind,ref,sha256,store_expect,resolvable_ok from recipe_artifacts where recipe_id=?", (rid,))]
    rec.compensators = [Compensator(*r) for r in cur.execute(
        "select step,undo_cmd,post_state,owner,compensatable from recipe_compensators where recipe_id=?", (rid,))]
    rec.techniques = [Technique(*r) for r in cur.execute(
        "select kb,technique_slug,technique_name,technique_cat from recipe_techniques where recipe_id=?", (rid,))]
    con.close()
    return rec
