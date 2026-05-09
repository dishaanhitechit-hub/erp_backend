import random
from faker import Faker

from app import create_app
from app.extensions import db

from app.models.user import User
from app.models.role import Role
from app.models.project import Project
from app.models.team import ProjectTeam
from app.models.project_role import ProjectUserRole
from app.models.designation import Designation
from app.models.og_team import Team

app = create_app()
fake = Faker()


# def seed_data():
#     with app.app_context():
#         print("🔄 Seeding started...")
#
#         # =================================================
#         # ROLES (super_admin must exist)
#         # =================================================
#
#         role_names = ["super_admin", "admin", "user"]
#         roles = {}
#
#         for role_name in role_names:
#             existing = Role.query.filter_by(name=role_name).first()
#
#             if existing:
#                 roles[role_name] = existing
#             else:
#                 new_role = Role(name=role_name)
#                 db.session.add(new_role)
#                 db.session.flush()
#                 roles[role_name] = new_role
#
#         db.session.commit()
#
#         # =================================================
#         # SUPER ADMIN (must exist)
#         # =================================================
#
#         super_admin = User.query.filter_by(
#             email="superadmin@test.com"
#         ).first()
#
#         if not super_admin:
#             super_admin = User(
#                 username="Super Admin",
#                 email="superadmin@test.com",
#                 mobile="9999999999",
#                 wp_mobile="9999999999",
#                 emp_code="EMP0001",
#                 global_role=roles["super_admin"]
#             )
#
#             super_admin.set_password("123456")
#
#             db.session.add(super_admin)
#             db.session.commit()
#
#             print("✅ Super Admin created")
#         else:
#             print("✅ Super Admin already exists")
#
#         users = [super_admin]
#
#         # # =================================================
#         # # RANDOM USERS
#         # # =================================================
#         #
#         # for i in range(19):
#         #     user = User(
#         #         username=fake.name(),
#         #         email=f"user{i}@test.com",
#         #         mobile=f"98{random.randint(10000000, 99999999)}",
#         #         wp_mobile=f"98{random.randint(10000000, 99999999)}",
#         #         emp_code=f"EMP{1002 + i}",
#         #         global_role=random.choice(
#         #             [roles["admin"], roles["user"]]
#         #         )
#         #     )
#         #
#         #     user.set_password("123456")
#         #
#         #     db.session.add(user)
#         #     users.append(user)
#         #
#         # db.session.commit()
#         #
#         # # =================================================
#         # # DESIGNATIONS
#         # # =================================================
#         #
#         # designation_names = [
#         #     "Manager",
#         #     "Engineer",
#         #     "Supervisor",
#         #     "QA",
#         #     "Store",
#         #     "HR",
#         #     "Finance",
#         #     "Admin"
#         # ]
#         #
#         # designations = []
#         #
#         # for name in designation_names:
#         #     existing = Designation.query.filter_by(name=name).first()
#         #
#         #     if existing:
#         #         designations.append(existing)
#         #     else:
#         #         d = Designation(name=name)
#         #         db.session.add(d)
#         #         db.session.flush()
#         #         designations.append(d)
#         #
#         # db.session.commit()
#         #
#         # # =================================================
#         # # MASTER TEAM TABLE (teams)
#         # # HO / SITE
#         # # =================================================
#         #
#         # master_team_names = ["HO", "SITE"]
#         # master_teams = []
#         #
#         # for t_name in master_team_names:
#         #     existing = Team.query.filter_by(
#         #         team_type=t_name
#         #     ).first()
#         #
#         #     if existing:
#         #         master_teams.append(existing)
#         #     else:
#         #         t = Team(team_type=t_name)
#         #         db.session.add(t)
#         #         db.session.flush()
#         #         master_teams.append(t)
#         #
#         # db.session.commit()
#         #
#         # # =================================================
#         # # PROJECTS
#         # # =================================================
#         #
#         # projects = []
#         #
#         # for i in range(5):
#         #     project = Project(
#         #         project_code=f"P{100+i}",
#         #         project_name=fake.company(),
#         #         client_name=fake.company(),
#         #         status=random.choice(
#         #             ["ongoing", "completed", "hold"]
#         #         )
#         #     )
#         #
#         #     db.session.add(project)
#         #     projects.append(project)
#         #
#         # db.session.commit()
#         #
#         # # =================================================
#         # # PROJECT TEAMS
#         # # One designation + one team + one project
#         # # =================================================
#         #
#         # project_teams = []
#         #
#         # for project in projects:
#         #     for team in master_teams:
#         #         for designation in designations:
#         #
#         #             existing = ProjectTeam.query.filter_by(
#         #                 project_id=project.id,
#         #                 designation_id=designation.id,
#         #                 team_id=team.id
#         #             ).first()
#         #
#         #             if existing:
#         #                 project_teams.append(existing)
#         #                 continue
#         #
#         #             pt = ProjectTeam(
#         #                 project_id=project.id,
#         #                 designation_id=designation.id,
#         #                 team_id=team.id,
#         #                 user_id=random.choice(users).id
#         #                 if random.random() > 0.5
#         #                 else None
#         #             )
#         #
#         #             db.session.add(pt)
#         #             db.session.flush()
#         #             project_teams.append(pt)
#         #
#         # db.session.commit()
#         #
#         # # =================================================
#         # # PROJECT USER ROLES
#         # # =================================================
#         #
#         # for pt in project_teams:
#         #     existing = ProjectUserRole.query.filter_by(
#         #         user_id=pt.user_id,
#         #         project_id=pt.project_id,
#         #         designation_id=pt.designation_id,
#         #         team_id=pt.team_id  # FIXED
#         #     ).first()
#         #
#         #     if existing:
#         #         continue
#         #
#         #     pur = ProjectUserRole(
#         #         user_id=pt.user_id,
#         #         project_id=pt.project_id,
#         #         designation_id=pt.designation_id,
#         #         team_id=pt.team_id  # FIXED
#         #     )
#         #
#         #     db.session.add(pur)
#         #
#         # db.session.commit()
#         #
#         #
#         #
#         #
#         # print("✅ Seeding completed successfully!")

from app.extensions import db
from app.models.category_group import *


def seed_category_master():

    categories = [

        # =====================================
        # ITEM CATEGORY
        # =====================================

        {
            "fixed_code": "MAT_001",
            "category_name": "Material"
        },
        {
            "fixed_code": "SER_001",
            "category_name": "Service"
        },
        {
            "fixed_code": "EXP_001",
            "category_name": "Expenses"
        },
        {
            "fixed_code": "COM_001",
            "category_name": "Composite"
        },

        # =====================================
        # CC CATEGORY
        # =====================================

        {
            "fixed_code": "TDS_001",
            "category_name": "TDS"
        },
        {
            "fixed_code": "GST_001",
            "category_name": "GST"
        },
        {
            "fixed_code": "REV_001",
            "category_name": "Revenue"
        },

        # =====================================
        # LEDGER CATEGORY
        # =====================================

        {
            "fixed_code": "VEN_001",
            "category_name": "Vendor"
        },
        {
            "fixed_code": "VEN_002",
            "category_name": "Non Vendor"
        },

        # =====================================
        # UNIT CATEGORY
        # =====================================

        {
            "fixed_code": "UNIT_001",
            "category_name": "Length"
        },
        {
            "fixed_code": "UNIT_002",
            "category_name": "Area"
        },
        {
            "fixed_code": "UNIT_003",
            "category_name": "Volume"
        },
        {
            "fixed_code": "UNIT_004",
            "category_name": "Time"
        },
        {
            "fixed_code": "UNIT_005",
            "category_name": "Weight"
        },
        {
            "fixed_code": "UNIT_006",
            "category_name": "Count"
        }
    ]

    for item in categories:

        exists = CategoryMaster.query.filter_by(
            fixed_code=item["fixed_code"]
        ).first()

        if not exists:

            category = CategoryMaster(
                fixed_code=item["fixed_code"],
                category_name=item["category_name"]
            )

            db.session.add(category)

    db.session.commit()

    print("Category Master seeded successfully")



if __name__ == "__main__":
    # seed_data()
    app = create_app()

    with app.app_context():
        seed_category_master()