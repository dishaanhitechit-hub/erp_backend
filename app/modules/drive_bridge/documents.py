"""ERP documents for Edox Drive: which uploaded files a person may see, laid out
as they are on disk, under their projects.

    <project code>/<module folder>/<record folder>/<file>     e.g. PC0001/grn/GRN-0012/invoice.pdf
    _company/<module folder>/…                                  vendors, labour, plant & machinery, company

Access follows the ERP: a project appears if the person has a role in it (super
admins see all), and a file appears only if one of the records that uses it is
in a module the person has VIEW, EDIT or APPROVER permission on in that project.
Nothing here changes how the ERP stores or uploads files.
"""

import json
import os
import re
from urllib.parse import unquote

from sqlalchemy import or_, select, text

from app.extensions import db
from app.modules.drive_bridge.registry import COMPANY, FOLDER_LABELS, SOURCES

ACTIONS = ("VIEW", "EDIT", "APPROVER")


class Denied(Exception):
    pass


def _media():
    base_url = (os.getenv("MEDIA_BASE_URL") or "").split("://", 1)[-1].rstrip("/")
    base_path = os.getenv("MEDIA_BASE_PATH") or ""
    return base_url, base_path


def _strings(value):
    """Every string in a column value (JSON lists and objects are walked)."""
    if value is None:
        return []
    if not isinstance(value, str):
        value = json.dumps(value)
    try:
        data = json.loads(value)
    except ValueError:
        return [value]
    out, stack = [], [data]
    while stack:
        item = stack.pop()
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            stack.extend(item.values())
    return out


def media_paths(value, base_url):
    """Paths under the upload folder for every file URL in one column value."""
    if not base_url:
        return set()
    pattern = re.compile(r"(?:https?://)?" + re.escape(base_url) + r"/([^\s\"'<>,;)\]}]+)")
    found = set()
    for s in _strings(value):
        s = s.strip()
        bare = re.sub(r"^https?://", "", s)
        rels = [bare[len(base_url) + 1:]] if bare.startswith(base_url + "/") and "\n" not in s else pattern.findall(s)
        for rel in rels:
            rel = unquote(rel).replace("\\/", "/").split("?")[0].strip("/")
            if rel and ".." not in rel.split("/"):
                found.add(rel)
    return found


class Scope:
    """What one ERP user may see. Cached for one request."""

    def __init__(self, user_id):
        self.user_id = int(user_id)
        row = db.session.execute(text(
            "SELECT r.name FROM users u LEFT JOIN roles r ON r.id = u.global_role_id WHERE u.id = :uid"),
            {"uid": self.user_id}).fetchone()
        if row is None:
            raise Denied("Unknown ERP user.")
        self.super_admin = row[0] == "super_admin"
        if self.super_admin:
            rows = db.session.execute(text("SELECT id, project_code, project_name FROM projects "
                                           "WHERE project_code IS NOT NULL ORDER BY project_code"))
        else:
            rows = db.session.execute(text(
                "SELECT DISTINCT p.id, p.project_code, p.project_name FROM project_user_roles pur "
                "JOIN projects p ON p.id = pur.project_id WHERE pur.user_id = :uid ORDER BY p.project_code"),
                {"uid": self.user_id})
        self.projects = {code: (pid, name) for pid, code, name in rows}
        self._perms = {}

    def keys(self, project_code):
        """Permission keys the person has in a project (super admins: everything)."""
        if project_code not in self._perms:
            from app.modules.setting.permission_service import get_user_permissions
            pid = self.projects[project_code][0]
            perms = get_user_permissions(pid, self.user_id) or {}
            self._perms[project_code] = {k.rsplit(".", 1)[0] for k, v in perms.items()
                                         if v is True and k.rsplit(".", 1)[-1] in ACTIONS}
        return self._perms[project_code]

    def allows(self, source, project_code=None):
        if self.super_admin:
            return True
        if project_code is not None:
            return bool(set(source.keys) & self.keys(project_code))
        # company-wide: the permission in any of the person's projects
        return any(set(source.keys) & self.keys(code) for code in self.projects)

    def has_company(self):
        return any(self.allows(s) for s in SOURCES if not s.project_columns)

    def files(self, scope):
        """{relative path on disk} the person may see in a project (or _company)."""
        if scope == COMPANY:
            sources = [s for s in SOURCES if not s.project_columns and self.allows(s)]
        elif scope in self.projects:
            sources = [s for s in SOURCES if s.project_columns and self.allows(s, scope)]
        else:
            raise Denied("You don't have access to this project.")
        base_url, _ = _media()
        found = set()
        for s in sources:
            table = db.metadata.tables.get(s.table)
            if table is None:
                continue
            cols = [table.c[c] for c in s.file_columns if c in table.c]
            if not cols:
                continue
            stmt = select(*cols).where(or_(*[c.is_not(None) for c in cols]))
            if scope != COMPANY:
                pcols = [table.c[p] for p in s.project_columns if p in table.c]
                if not pcols:
                    continue
                stmt = stmt.where(or_(*[p == scope for p in pcols]))
            for row in db.session.execute(stmt):
                for value in row:
                    found |= media_paths(value, base_url)
        return found


def _label(scope, scope_obj):
    if scope == COMPANY:
        return "Company-wide"
    name = scope_obj.projects.get(scope, (None, None))[1]
    return f"{scope} – {name}" if name else scope


def _stat(rel):
    _, base_path = _media()
    try:
        st = os.stat(os.path.join(base_path, rel))
        return st.st_size, int(st.st_mtime)
    except OSError:
        return None, None


def tree(user_id, path):
    s = Scope(user_id)
    parts = [p for p in (path or "").split("/") if p]
    if not parts:
        folders = [{"name": code, "label": _label(code, s), "path": code} for code in s.projects]
        if s.has_company():
            folders.append({"name": COMPANY, "label": "Company-wide", "path": COMPANY})
        return {"path": [], "folders": folders, "files": []}

    scope, inner = parts[0], parts[1:]
    rels = s.files(scope)
    prefix = "/".join(inner)
    folders, files = {}, []
    for rel in rels:
        if prefix:
            if not rel.startswith(prefix + "/"):
                continue
            rest = rel[len(prefix) + 1:]
        else:
            rest = rel
        if "/" in rest:
            top = rest.split("/", 1)[0]
            folders.setdefault(top, 0)
            folders[top] += 1
        else:
            size, mtime = _stat(rel)
            files.append({"name": rest, "path": f"{scope}/{rel}", "size": size, "modified": mtime,
                          "missing": size is None})
    if prefix and not folders and not files:
        raise Denied("Folder not found or not allowed.")

    crumbs = [{"name": _label(scope, s), "path": scope}]
    for i, seg in enumerate(inner):
        crumbs.append({"name": FOLDER_LABELS.get(seg, seg) if i == 0 else seg,
                       "path": "/".join([scope] + inner[:i + 1])})
    out_folders = [{"name": f, "label": FOLDER_LABELS.get(f, f) if not inner else f,
                    "path": "/".join([scope] + inner + [f]), "count": n}
                   for f, n in sorted(folders.items(), key=lambda x: x[0].lower())]
    return {"path": crumbs, "folders": out_folders,
            "files": sorted(files, key=lambda f: f["name"].lower())}


def check(user_id, path):
    """The file on disk for a path the person may see, or Denied."""
    parts = [p for p in (path or "").split("/") if p]
    if len(parts) < 2:
        raise Denied("Not a file.")
    scope, rel = parts[0], "/".join(parts[1:])
    if rel not in Scope(user_id).files(scope):
        raise Denied("You don't have access to this file in the ERP.")
    return {"rel": rel, "name": parts[-1]}
