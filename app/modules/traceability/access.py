# app/modules/traceability/access.py
"""
Who may see which document in the Traceability Workbench.

* super_admin / admin (global roles that own the Master module): every project.
* everyone else: only projects they are assigned to, and within a project
  only the document types whose page they hold VIEW / EDIT / APPROVER on —
  the same permission keys the frontend sidebar and pages use.

Documents the user may not see are still returned as anonymous
"restricted" nodes so the flow structure stays truthful, but without any
number, party, quantity or amount.
"""

from sqlalchemy import text
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models.user import User
from app.models.project import Project

GLOBAL_ROLES = ("super_admin", "admin")


class TraceAccess:

    def __init__(self, user_id):
        self.user_id = user_id
        user = User.query.options(joinedload(User.global_role)).get(user_id)
        self.role = user.global_role.name if user and user.global_role else None
        self.is_global = self.role in GLOBAL_ROLES
        self._perm_cache = {}
        self._projects = None

    # ── projects ──────────────────────────────────────────────────
    def projects(self):
        """[{id, code, name}] the user can trace in."""
        if self._projects is None:
            q = Project.query.order_by(Project.project_code)
            if not self.is_global:
                ids = [r[0] for r in db.session.execute(
                    text("SELECT DISTINCT project_id FROM project_user_roles WHERE user_id = :u"),
                    {"u": self.user_id},
                ).fetchall()]
                q = q.filter(Project.id.in_(ids or [-1]))
            self._projects = [
                {"id": p.id, "code": p.project_code, "name": p.project_name} for p in q.all()
            ]
        return self._projects

    def project_codes(self):
        return [p["code"] for p in self.projects()]

    def _perms(self, project_code):
        if project_code not in self._perm_cache:
            proj = next((p for p in self.projects() if p["code"] == project_code), None)
            if not proj:
                self._perm_cache[project_code] = None
            else:
                from app.modules.setting.permission_service import get_user_permissions
                self._perm_cache[project_code] = get_user_permissions(proj["id"], self.user_id) or {}
        return self._perm_cache[project_code]

    # ── documents ─────────────────────────────────────────────────
    def can_view(self, page_codes, project_codes):
        """page_codes: any of these pages grants access; project_codes: any of these projects."""
        project_codes = [c for c in project_codes if c]
        if self.is_global:
            return True
        for pc in project_codes:
            perms = self._perms(pc)
            if not perms:
                continue
            for page in page_codes:
                if any(perms.get(f"{page}.{a}") for a in ("VIEW", "EDIT", "APPROVER")):
                    return True
        return False

    def projects_for_pages(self, page_codes):
        """Project codes where the user may see documents guarded by page_codes."""
        if self.is_global:
            return None  # no restriction
        return [c for c in self.project_codes() if self.can_view(page_codes, [c])]
