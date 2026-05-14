# def update_roles_by_project_code(projectCode, data):
#
#     project = Project.query.filter_by(
#         project_code=projectCode
#     ).first()
#
#     if not project:
#         return res(
#             "Project not found",
#             [],
#             404
#         )
#
#     role_user_map = data.get(
#         "roleUserMap",
#         []
#     )
#
#     if not role_user_map:
#         return res(
#             "roleUserMap is required",
#             [],
#             400
#         )
#
#     for item in role_user_map:
#
#         designation_id = item.get(
#             "designationId"
#         )
#
#         team_id = item.get(
#             "teamId"
#         )
#
#         user_id = item.get(
#             "userId"
#         )
#
#         permissions = item.get(
#             "permissions",
#             {}
#         )
#
#         # ==================================================
#         # CREATE / UPDATE PROJECT USER ROLE
#         # ==================================================
#
#         role = ProjectUserRole.query.filter_by(
#             project_id=project.id,
#             designation_id=designation_id,
#             team_id=team_id
#         ).first()
#
#         if role:
#
#             role.user_id = user_id
#
#         else:
#
#             role = ProjectUserRole(
#                 project_id=project.id,
#                 designation_id=designation_id,
#                 team_id=team_id,
#                 user_id=user_id
#             )
#
#             db.session.add(role)
#
#             db.session.flush()
#
#         # ==================================================
#         # UPDATE PROJECT TEAM
#         # ==================================================
#
#         pt = ProjectTeam.query.filter_by(
#             project_id=project.id,
#             designation_id=designation_id,
#             team_id=team_id
#         ).first()
#
#         if pt:
#             pt.user_id = user_id
#
#         # ==================================================
#         # REMOVE OLD DESIGNATION PERMISSIONS
#         # ==================================================
#
#         ProjectDesignationPermission.query.filter_by(
#             project_id=project.id,
#             designation_id=designation_id
#         ).delete()
#
#         # ==================================================
#         # ADD NEW DESIGNATION PERMISSIONS
#         # ==================================================
#
#         for permission_key, allowed in permissions.items():
#
#             try:
#
#                 page_code, action_name = (
#                     permission_key.split(".")
#                 )
#
#             except ValueError:
#                 continue
#
#             page = FeaturePage.query.filter_by(
#                 page_code=page_code
#             ).first()
#
#             if not page:
#                 continue
#
#             action = PermissionAction.query.filter_by(
#                 action_name=action_name
#             ).first()
#
#             if not action:
#                 continue
#
#             permission = (
#                 ProjectDesignationPermission(
#                     project_id=project.id,
#                     designation_id=designation_id,
#                     page_id=page.id,
#                     action_id=action.id,
#                     allowed=allowed
#                 )
#             )
#
#             db.session.add(permission)
#
#     db.session.commit()
#
#     data = [
#         {
#             "projectId": project.id
#         }
#     ]
#
#     return res(
#         "Roles and permissions updated successfully",
#         data,
#         200
#     )
#
#
#
#
# def update_roles_by_project_code(projectCode, data):
#     project = Project.query.filter_by(project_code=projectCode).first()
#
#     if not project:
#         return res("Project not found", [], 404)
#
#     role_user_map = data.get("roleUserMap", [])
#
#     if not role_user_map:
#         return res("roleUserMap is required", [], 400)
#
#     for item in role_user_map:
#         designation_id = item.get("designationId")
#         team_id = item.get("teamId")
#         user_id = item.get("userId")
#
#         role = ProjectUserRole.query.filter_by(
#             project_id=project.id,
#             designation_id=designation_id,
#             team_id=team_id
#         ).first()
#
#         if not role:
#             continue
#
#         # update ProjectUserRole
#         role.user_id = user_id
#
#         # update ProjectTeam also
#         pt = ProjectTeam.query.filter_by(
#             project_id=project.id,
#             designation_id=designation_id,
#             team_id=team_id
#         ).first()
#
#         if pt:
#             pt.user_id = user_id
#
#     db.session.commit()
#     data=[
#         {
#             "projectId": project.id
#         }
#     ]
#     return res("Roles updated successfully", data, 200)