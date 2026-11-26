"""
MIS Boards — Kanban (backlog-level board, Azure Boards style).

  * One board per project (NULL = company) and backlog level: PBI (PBIs + Bugs), Feature, Epic.
  * Columns map to states; several columns may share a state (e.g. "Design" and "Build" are both
    Committed). A column may be split into Doing / Done halves and may have a WIP limit
    (soft — the move is allowed, the answer carries a warning, like Azure).
  * Swimlanes are free names; "" is the default lane.
  * The card's position lives on the item (board_column / board_column_done / board_lane);
    a missing or stale column falls back to the first column mapped to the item's state.
Editing the settings: sprint managers (task_tracker.EDIT or sprint_admin.EDIT) of that project.
"""
from datetime import datetime, timedelta

from app.extensions import db
from app.response import res
from app.models.misTask import MisTask, MisBoardConfig, WI_STATES
from app.modules.mis.common import (
    MisError, api, uid, choice, project_by_code, is_all, is_member, is_super, can_manage_sprints, log_activity,
)
from app.modules.mis.workitem import service as wi

LEVELS = {"PBI": ("PBI", "Bug"), "Feature": ("Feature",), "Epic": ("Epic",)}
LEVEL_OF = {"PBI": "PBI", "Bug": "PBI", "Feature": "Feature", "Epic": "Epic"}
MAX_COLUMNS, MAX_LANES, DONE_DAYS = 12, 10, 30


def default_columns(level):
    if level == "PBI":
        return [{"name": "New", "state": "New", "wip": 0, "split": False},
                {"name": "Approved", "state": "Approved", "wip": 0, "split": False},
                {"name": "Committed", "state": "Committed", "wip": 5, "split": True},
                {"name": "Done", "state": "Done", "wip": 0, "split": False}]
    return [{"name": "New", "state": "New", "wip": 0, "split": False},
            {"name": "In Progress", "state": "In Progress", "wip": 0, "split": True},
            {"name": "Done", "state": "Done", "wip": 0, "split": False}]


def _project(code):
    """'all' (central view) uses the company board settings, like 'company'."""
    if is_all(code):
        return None, None
    p = project_by_code(code)
    return p, (p.id if p else None)


def _config_row(project_id, level):
    q = MisBoardConfig.query.filter(MisBoardConfig.level == level)
    q = q.filter(MisBoardConfig.project_id.is_(None) if project_id is None else MisBoardConfig.project_id == project_id)
    return q.first()


def get_config(project_id, level):
    """Project settings → else the company (central) settings → else the defaults."""
    row = _config_row(project_id, level) or (_config_row(None, level) if project_id is not None else None)
    return {"columns": row.columns if row else default_columns(level),
            "swimlanes": (row.swimlanes or []) if row else [], "isDefault": row is None}


def resolve_column(item, columns):
    """(column dict, done flag) for a card, or (None, False) when no column shows its state."""
    if item.board_column:
        for c in columns:
            if c["name"] == item.board_column and c["state"] == item.status:
                return c, bool(item.board_column_done and c.get("split"))
    for c in columns:
        if c["state"] == item.status:
            return c, False
    return None, False


def _check_access(user_id, project_id):
    if project_id is not None and not is_super(user_id) and not is_member(user_id, project_id):
        raise MisError("You are not a member of this project", 403)


def _validate(level, columns, swimlanes):
    states = [s for s in WI_STATES[LEVELS[level][0]] if s != "Removed"]
    if not isinstance(columns, list) or not 2 <= len(columns) <= MAX_COLUMNS:
        raise MisError(f"A board needs 2 to {MAX_COLUMNS} columns")
    out, names = [], set()
    for i, c in enumerate(columns):
        if not isinstance(c, dict):
            raise MisError("Each column must be an object")
        name = str(c.get("name") or "").strip()
        if not name or len(name) > 40:
            raise MisError("Column names must be 1–40 characters")
        if name.lower() in names:
            raise MisError(f"Column '{name}' appears twice")
        names.add(name.lower())
        state = choice(c.get("state"), states, f"State of column '{name}'")
        try:
            wip = int(c.get("wip") or 0)
        except (TypeError, ValueError):
            raise MisError(f"WIP limit of '{name}' must be a whole number")
        if not 0 <= wip <= 999:
            raise MisError(f"WIP limit of '{name}' must be 0–999 (0 = no limit)")
        split = bool(c.get("split")) and 0 < i < len(columns) - 1
        out.append({"name": name, "state": state, "wip": wip, "split": split})
    if out[0]["state"] != "New":
        raise MisError("The first column must be mapped to New")
    if out[-1]["state"] != "Done" or any(c["state"] == "Done" for c in out[:-1]):
        raise MisError("Only the last column can be mapped to Done")
    missing = [s for s in states if s not in {c["state"] for c in out}]
    if missing:
        raise MisError(f"Every state needs a column — missing: {', '.join(missing)}")

    lanes, seen = [], set()
    for l in swimlanes or []:
        n = str(l or "").strip()
        if not n or len(n) > 40:
            raise MisError("Swimlane names must be 1–40 characters")
        if n.lower() in seen:
            raise MisError(f"Swimlane '{n}' appears twice")
        seen.add(n.lower())
        lanes.append(n)
    if len(lanes) > MAX_LANES:
        raise MisError(f"At most {MAX_LANES} extra swimlanes")
    return out, lanes


# ─────────────────────────────── endpoints ─────────────────────────────

@api
def board_config(args, user_id):
    """GET ?projectCode= &level=PBI|Feature|Epic"""
    user_id = uid(user_id)
    level = choice(args.get("level") or "PBI", tuple(LEVELS), "level")
    _, pid = _project(args.get("projectCode"))
    _check_access(user_id, pid)
    return res("ok", {**get_config(pid, level), "level": level, "canEdit": can_manage_sprints(user_id, pid)})


@api
def save_board_config(data, user_id):
    """PUT { projectCode, level, columns: [{name, state, wip, split}], swimlanes: [name] }"""
    user_id = uid(user_id)
    level = choice(data.get("level") or "PBI", tuple(LEVELS), "level")
    _, pid = _project(data.get("projectCode"))
    if not can_manage_sprints(user_id, pid):
        raise MisError("Only a sprint manager can change the board settings", 403)
    columns, lanes = _validate(level, data.get("columns"), data.get("swimlanes"))
    row = _config_row(pid, level)
    if not row:
        row = MisBoardConfig(project_id=pid, level=level)
        db.session.add(row)
    row.columns, row.swimlanes, row.updated_by = columns, lanes, user_id
    db.session.commit()
    return res("Board settings saved", {**get_config(pid, level), "level": level, "canEdit": True})


@api
def kanban(args, user_id):
    """GET ?projectCode= &level= → config + cards (column / half / lane resolved) + child progress."""
    user_id = uid(user_id)
    level = choice(args.get("level") or "PBI", tuple(LEVELS), "level")
    _, pid = _project(args.get("projectCode"))
    _check_access(user_id, pid)
    cfg = get_config(pid, level)
    q = wi._visible_filter(MisTask.query.filter(MisTask.is_deleted.is_(False)), user_id)
    if not is_all(args.get("projectCode")):
        q = q.filter(MisTask.project_id.is_(None) if pid is None else MisTask.project_id == pid)
    q = q.filter(MisTask.work_item_type.in_(LEVELS[level]), MisTask.status != "Removed")
    cutoff = datetime.utcnow() - timedelta(days=DONE_DAYS)
    q = q.filter(db.or_(MisTask.status != "Done", MisTask.completed_at.is_(None), MisTask.completed_at >= cutoff))
    rows = q.order_by(MisTask.backlog_rank.asc().nullslast(), MisTask.id.asc()).all()

    # child progress (done / total) in one query
    prog = {}
    if rows:
        for pid_, st in (db.session.query(MisTask.parent_id, MisTask.status)
                         .filter(MisTask.parent_id.in_([r.id for r in rows]), MisTask.is_deleted.is_(False)).all()):
            p = prog.setdefault(pid_, {"done": 0, "total": 0})
            if st in ("Removed", "Cancelled"):
                continue
            p["total"] += 1
            p["done"] += st == "Done"

    lanes = set(cfg["swimlanes"])
    cards = []
    for t in rows:
        col, done = resolve_column(t, cfg["columns"])
        if not col:
            continue
        d = wi._out(t, user_id)
        d.update({"column": col["name"], "columnDone": done,
                  "lane": t.board_lane if t.board_lane in lanes else "",
                  "childProgress": prog.get(t.id, {"done": 0, "total": 0})})
        cards.append(d)
    return res("ok", {**cfg, "level": level, "canEdit": can_manage_sprints(user_id, pid), "cards": cards,
                      "doneDays": DONE_DAYS})


@api
def board_move(item_id, data, user_id):
    """POST { column, done?, lane? } — move a card; the state follows the column's state."""
    user_id = uid(user_id)
    t = wi._get(item_id, user_id, edit=True)
    level = LEVEL_OF.get(t.work_item_type)
    if not level:
        raise MisError("Tasks move on the sprint taskboard, not on the Kanban board")
    # the board the user is looking at decides the columns (central view → company settings)
    cfg = get_config(_project(data["projectCode"])[1] if "projectCode" in data else t.project_id, level)
    col = next((c for c in cfg["columns"] if c["name"] == data.get("column")), None)
    if not col:
        raise MisError("Unknown column")
    lane = data.get("lane", t.board_lane) or ""
    if lane and lane not in cfg["swimlanes"]:
        raise MisError("Unknown swimlane")

    before = resolve_column(t, cfg["columns"])
    old_state = wi._set_state(t, col["state"])
    if old_state:
        log_activity(wi.ENTITY, t.id, user_id, "STATUS", old=old_state, new=t.status)
    t.board_column = col["name"]
    t.board_column_done = bool(data.get("done")) and col["split"]
    t.board_lane = lane or None
    if before[0] is None or before[0]["name"] != col["name"]:
        log_activity(wi.ENTITY, t.id, user_id, "BOARD", old=before[0]["name"] if before[0] else None, new=col["name"])
    db.session.commit()

    warning = None
    if col["wip"]:
        same_state = MisTask.query.filter(
            MisTask.is_deleted.is_(False), MisTask.work_item_type.in_(LEVELS[level]), MisTask.status == col["state"],
            MisTask.project_id.is_(None) if t.project_id is None else MisTask.project_id == t.project_id).all()
        n = sum(1 for x in same_state if (resolve_column(x, cfg["columns"])[0] or {}).get("name") == col["name"])
        if n > col["wip"]:
            warning = f"{col['name']} is over its WIP limit ({n} / {col['wip']})"
    out = wi._out(t, user_id)
    out.update({"column": col["name"], "columnDone": t.board_column_done, "lane": t.board_lane or ""})
    return res(warning or "Moved", {"item": out, "warning": warning})
