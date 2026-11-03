# Sub Group master: a small tree under each Group.
#   Group -> Sub Group (level 0) -> Sub Group 1 (level 1) -> Sub Group 2 (level 2)
# Code: optional on input. Typed codes are saved in UPPERCASE; empty -> auto code.
# Codes are unique across all sub groups.
import re

from flask import g
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.response import res
from app.models.category_group import GroupMaster, SubGroupMaster, SUB_GROUP_MAX_LEVELS
from app.models.cc_code import CCCode

CODE_MAX_LEN = 50
CODE_PATTERN = re.compile(r"^[A-Z0-9_-]+$")
LEVEL_LABELS = ["Sub Group"] + [f"Sub Group {i}" for i in range(1, SUB_GROUP_MAX_LEVELS)]


# ---------------- helpers ----------------

def level_label(level):
    return LEVEL_LABELS[level] if 0 <= level < len(LEVEL_LABELS) else f"Level {level}"


def normalize_code(code):
    """Trim, spaces -> '_', UPPERCASE."""
    return re.sub(r"\s+", "_", (code or "").strip()).upper()


def validate_code_format(code):
    if not code:
        return "Code is empty"
    if len(code) > CODE_MAX_LEN:
        return f"Code must be at most {CODE_MAX_LEN} characters"
    if not CODE_PATTERN.match(code):
        return "Code can only have letters, numbers, '_' and '-'"
    return None


def code_exists(code, exclude_id=None):
    q = SubGroupMaster.query.filter(db.func.upper(SubGroupMaster.fixed_code) == code.upper())
    if exclude_id:
        q = q.filter(SubGroupMaster.id != int(exclude_id))
    return db.session.query(q.exists()).scalar()


def _base_code(name):
    """'Fixed Asset' -> 'FA', 'Project Overhead' -> 'PO', 'Machinery' -> 'MACH'."""
    words = re.findall(r"[A-Za-z0-9]+", name or "")
    if not words:
        return "SG"
    if len(words) == 1:
        return words[0][:4].upper()
    return "".join(w[0] for w in words[:4]).upper()


def generate_code(name, parent=None):
    """Standard auto code. Child codes start with the parent code: FA, FA_HM, FA_HM_EX.
    Adds 01, 02... if needed so it is never a duplicate."""
    base = _base_code(name)
    if parent is not None:
        base = f"{parent.fixed_code}_{base}"
    base = base[:CODE_MAX_LEN - 2]
    if not code_exists(base):
        return base
    for n in range(1, 1000):
        candidate = f"{base}{n:02d}"
        if not code_exists(candidate):
            return candidate
    raise ValueError("Could not generate a unique code")


def _subtree_height(node):
    """1 for a node without children."""
    return 1 + max((_subtree_height(c) for c in node.children), default=0)


def _is_descendant(node, possible_child_id):
    return any(c.id == possible_child_id or _is_descendant(c, possible_child_id) for c in node.children)


def _set_levels(node, level):
    node.level = level
    for c in node.children:
        _set_levels(c, level + 1)


def _subtree_ids(node):
    ids = [node.id]
    for c in node.children:
        ids += _subtree_ids(c)
    return ids


def _name_taken(group_id, parent_id, name, exclude_id=None):
    q = SubGroupMaster.query.filter(
        SubGroupMaster.group_id == group_id,
        db.func.lower(SubGroupMaster.sub_group_name) == name.lower(),
    )
    q = q.filter(SubGroupMaster.parent_id.is_(None)) if parent_id is None else q.filter(SubGroupMaster.parent_id == parent_id)
    if exclude_id:
        q = q.filter(SubGroupMaster.id != exclude_id)
    return db.session.query(q.exists()).scalar()


def sub_group_path_for(node, prefix="cc"):
    """Generic sub-group path serializer. prefix e.g. 'cc', 'bs', 'pl'."""
    p = prefix
    if node is None:
        return {
            f"{p}SubGroupId": None, f"{p}SubGroupName": None, f"{p}SubGroupCode": None,
            f"{p}SubGroupPath": None, f"{p}SubGroupLevels": [],
        }
    path = node.path()
    return {
        f"{p}SubGroupId": node.id,
        f"{p}SubGroupName": node.sub_group_name,
        f"{p}SubGroupCode": node.fixed_code,
        f"{p}SubGroupPath": " > ".join(n.sub_group_name for n in path),
        f"{p}SubGroupLevels": [
            {"subGroupId": n.id, "subGroupName": n.sub_group_name, "level": n.level, "levelLabel": level_label(n.level)}
            for n in path
        ],
    }


def sub_group_path_fields(node):
    """Used by CC code responses (cc prefix)."""
    return sub_group_path_for(node, "cc")


def row(sub):
    path = sub.path()
    return {
        "subGroupId": sub.id,
        "subGroupCode": sub.fixed_code,
        "subGroupName": sub.sub_group_name,
        "groupId": sub.group_id,
        "groupName": sub.group.group_name if sub.group else None,
        "headUnder": sub.group.head_under if sub.group else None,
        "parentId": sub.parent_id,
        "parentName": sub.parent.sub_group_name if sub.parent else None,
        "level": sub.level,
        "levelLabel": level_label(sub.level),
        "path": " > ".join(n.sub_group_name for n in path),
        "pathIds": [n.id for n in path],
        "hasChildren": len(sub.children) > 0,
        "canHaveChildren": sub.level < SUB_GROUP_MAX_LEVELS - 1,
        "status": sub.status,
    }


def _resolve_code(raw_code, name, parent, exclude_id=None):
    """Return (code, error). Empty input -> auto code."""
    code = normalize_code(raw_code)
    if not code:
        return generate_code(name, parent), None
    err = validate_code_format(code)
    if err:
        return None, err
    if code_exists(code, exclude_id):
        return None, f"Code '{code}' already exists"
    return code, None


# ---------------- APIs ----------------

def check_sub_group_code(args):
    """Live check while typing: ?code=&excludeId="""
    code = normalize_code(args.get("code"))
    if not code:
        return res("Empty code: will be auto generated", [{"code": "", "valid": True, "exists": False}], 200)
    err = validate_code_format(code)
    if err:
        return res(err, [{"code": code, "valid": False, "exists": False}], 200)
    exists = code_exists(code, args.get("excludeId"))
    return res(
        "Code already exists" if exists else "Code is available",
        [{"code": code, "valid": True, "exists": exists}],
        200,
    )


def suggest_sub_group_code(args):
    """Preview of the auto code: ?name=&parentId="""
    name = (args.get("name") or "").strip()
    if not name:
        return res("name is required", [], 400)
    parent = SubGroupMaster.query.get(args.get("parentId")) if args.get("parentId") else None
    return res("Suggested code", [{"code": generate_code(name, parent)}], 200)


def create_sub_group(data):
    name = (data.get("subGroupName") or "").strip()
    if not name:
        return res("subGroupName is required", [], 400)

    parent = None
    if data.get("parentId"):
        parent = SubGroupMaster.query.get(data.get("parentId"))
        if not parent:
            return res("Parent Sub Group not found", [], 400)
        if parent.level + 1 >= SUB_GROUP_MAX_LEVELS:
            return res(f"Maximum {SUB_GROUP_MAX_LEVELS} sub group levels allowed", [], 400)
        if data.get("groupId") and int(data.get("groupId")) != parent.group_id:
            return res("Parent Sub Group belongs to another Group", [], 400)
        group_id = parent.group_id
    else:
        group_id = data.get("groupId")
        if not group_id or not GroupMaster.query.get(group_id):
            return res("Valid groupId is required", [], 400)

    if _name_taken(group_id, parent.id if parent else None, name):
        return res("Sub Group with this name already exists here", [], 400)

    created_by = g.current_user.get("id") if hasattr(g, "current_user") else None
    typed = bool(normalize_code(data.get("subGroupCode")))

    # retry only for auto codes (two users saving at the same moment)
    for _ in range(3):
        code, err = _resolve_code(data.get("subGroupCode"), name, parent)
        if err:
            return res(err, [], 400)
        sub = SubGroupMaster(
            fixed_code=code,
            sub_group_name=name,
            group_id=group_id,
            parent_id=parent.id if parent else None,
            level=parent.level + 1 if parent else 0,
            created_by=created_by,
        )
        try:
            db.session.add(sub)
            db.session.commit()
            return res("Sub Group created successfully", [row(sub)], 201)
        except IntegrityError:
            db.session.rollback()
            if typed:
                return res("Code or name already exists", [], 400)
        except Exception:
            db.session.rollback()
            return res("Failed to create sub group", [], 500)
    return res("Could not save, please try again", [], 409)


def update_sub_group(subGroupId, data):
    sub = SubGroupMaster.query.get(subGroupId)
    if not sub:
        return res("Sub Group not found", [], 404)

    name = (data.get("subGroupName") or sub.sub_group_name).strip()

    # parent (key present -> may be cleared with null)
    new_parent_id = data.get("parentId") if "parentId" in data else sub.parent_id
    new_parent_id = int(new_parent_id) if new_parent_id else None
    new_parent = None
    if new_parent_id:
        if new_parent_id == sub.id or _is_descendant(sub, new_parent_id):
            return res("A Sub Group cannot be placed under itself", [], 400)
        new_parent = SubGroupMaster.query.get(new_parent_id)
        if not new_parent:
            return res("Parent Sub Group not found", [], 400)
    new_level = new_parent.level + 1 if new_parent else 0
    if new_level + _subtree_height(sub) > SUB_GROUP_MAX_LEVELS:
        return res(f"Maximum {SUB_GROUP_MAX_LEVELS} sub group levels allowed", [], 400)

    new_group_id = new_parent.group_id if new_parent else int(data.get("groupId") or sub.group_id)
    if new_parent and data.get("groupId") and int(data.get("groupId")) != new_parent.group_id:
        return res("Parent Sub Group belongs to another Group", [], 400)
    if not GroupMaster.query.get(new_group_id):
        return res("Valid groupId is required", [], 400)
    if new_group_id != sub.group_id:
        if sub.children:
            return res("Cannot change Group: this Sub Group has child sub groups", [], 400)
        if CCCode.query.filter(CCCode.sub_group_id.in_(_subtree_ids(sub))).first():
            return res("Cannot change Group: CC codes use this Sub Group", [], 400)

    if _name_taken(new_group_id, new_parent_id, name, exclude_id=sub.id):
        return res("Sub Group with this name already exists here", [], 400)

    # code: empty/missing keeps current code
    if normalize_code(data.get("subGroupCode")):
        code, err = _resolve_code(data.get("subGroupCode"), name, new_parent, exclude_id=sub.id)
        if err:
            return res(err, [], 400)
        sub.fixed_code = code

    sub.sub_group_name = name
    sub.group_id = new_group_id
    sub.parent_id = new_parent_id
    _set_levels(sub, new_level)
    if data.get("status"):
        sub.status = data.get("status")
    try:
        db.session.commit()
        return res("Sub Group updated successfully", [row(sub)], 200)
    except IntegrityError:
        db.session.rollback()
        return res("Code or name already exists", [], 400)
    except Exception:
        db.session.rollback()
        return res("Failed to update sub group", [], 500)


def get_all_sub_groups(args):
    """?groupId=&parentId=(id | root)&level=&status="""
    q = SubGroupMaster.query
    if args.get("groupId"):
        q = q.filter(SubGroupMaster.group_id == args.get("groupId"))
    parent_id = args.get("parentId")
    if parent_id in ("root", "0"):
        q = q.filter(SubGroupMaster.parent_id.is_(None))
    elif parent_id:
        q = q.filter(SubGroupMaster.parent_id == parent_id)
    if args.get("level") not in (None, ""):
        q = q.filter(SubGroupMaster.level == int(args.get("level")))
    if args.get("status"):
        q = q.filter(SubGroupMaster.status == args.get("status"))

    rows = [row(s) for s in q.all()]
    # tree order: group, then path
    rows.sort(key=lambda r: ((r["groupName"] or "").lower(), r["path"].lower()))
    return res("Sub Group list fetched successfully", rows, 200)


def get_sub_group_by_id(subGroupId):
    sub = SubGroupMaster.query.get(subGroupId)
    if not sub:
        return res("Sub Group not found", [], 404)
    return res("Sub Group fetched successfully", [row(sub)], 200)


def delete_sub_group(subGroupId):
    sub = SubGroupMaster.query.get(subGroupId)
    if not sub:
        return res("Sub Group not found", [], 404)
    if sub.children:
        return res("Delete its child sub groups first", [], 400)
    if CCCode.query.filter_by(sub_group_id=sub.id).first():
        return res("Sub Group is used by CC codes and cannot be deleted", [], 400)
    db.session.delete(sub)
    db.session.commit()
    return res("Sub Group deleted successfully", [], 200)
