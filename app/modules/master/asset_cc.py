"""Which CC codes count as Fixed Asset CC codes.

A CC code is a Fixed Asset CC code when its main group, or the sub group it
sits in (any level, or any parent of that sub group), is named "Fixed Asset"
or "Fixed Assets" (case and surrounding spaces ignored).

Asset CC codes used to be matched only on a main group named exactly
"Fixed Asset", which found nothing once asset CCs were filed under a
"Fixed Asset" sub group of a Balance Sheet group.
"""
from sqlalchemy import false, or_

from app.extensions import db
from app.models.category_group import GroupMaster, SubGroupMaster
from app.models.cc_code import CCCode

FIXED_ASSET_NAMES = ("fixed asset", "fixed assets")


def _name_matches(column):
    return db.func.lower(db.func.trim(column)).in_(FIXED_ASSET_NAMES)


def fixed_asset_cc_condition():
    """SQL condition on CCCode that is true for Fixed Asset CC codes."""
    group_ids = [g.id for g in GroupMaster.query.filter(_name_matches(GroupMaster.group_name)).all()]

    # matching sub groups plus every sub group below them
    sub_ids = {s.id for s in SubGroupMaster.query.filter(_name_matches(SubGroupMaster.sub_group_name)).all()}
    frontier = set(sub_ids)
    while frontier:
        children = {s.id for s in SubGroupMaster.query.filter(SubGroupMaster.parent_id.in_(frontier)).all()}
        frontier = children - sub_ids
        sub_ids |= frontier

    parts = []
    if group_ids:
        parts.append(CCCode.group_id.in_(group_ids))
    if sub_ids:
        parts.append(CCCode.sub_group_id.in_(sub_ids))
    return or_(*parts) if parts else false()
