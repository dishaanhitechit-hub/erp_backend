import random
from app import create_app
from app.extensions import db
import random
import uuid
from faker import Faker

from app import create_app
from app.extensions import db
from app.models.user import User
from app.models.role import Role
from app.models.project import Project
from app.models.team import ProjectTeam
from app.models.project_role import ProjectUserRole
from app.models.designation import Designation

app = create_app()
fake = Faker()


def seed_data():
    with app.app_context():

        print("🔄 Seeding started...")

        # ---------- ROLES ----------
        roles = {
            "super_admin": Role(name="super_admin"),
            "admin": Role(name="admin"),
            "user": Role(name="user"),
        }

        db.session.add_all(roles.values())
        db.session.commit()

        # ---------- USERS ----------
        users = []

        # ---------- MUST SUPER ADMIN ----------
        super_admin_role = roles["super_admin"]

        super_admin = User(
            username="superadmin",
            email="superadmin@test.com",
            mobile="9999999999",
            wp_mobile="9999999999",
            emp_code="EMP0001",
            global_role=super_admin_role
        )
        super_admin.set_password("123456")

        db.session.add(super_admin)
        db.session.commit()

        users.append(super_admin)

        # ---------- RANDOM USERS ----------
        for i in range(19):  # total 20 users (1 already created)
            role_choice = random.choice(list(roles.values()))

            user = User(
                username=fake.user_name() + str(i),
                email=fake.email(),
                mobile=fake.phone_number()[:15],
                wp_mobile=fake.phone_number()[:15],
                emp_code=f"EMP{1001 + i}",
                global_role=role_choice
            )
            user.set_password("123456")

            users.append(user)

        db.session.add_all(users[1:])  # skip already added superadmin
        db.session.commit()

        # ---------- DESIGNATIONS ----------
        designation_names = [
            "Manager", "Engineer", "Supervisor",
            "QA", "Store", "HR", "Finance", "Admin"
        ]

        designations = []
        for name in designation_names:
            d = Designation(name=name)
            designations.append(d)

        db.session.add_all(designations)
        db.session.commit()

        # ---------- PROJECTS ----------
        projects = []
        for i in range(5):
            p = Project(
                project_code=f"P{100+i}",
                project_name=fake.company(),
                client_name=fake.company(),
                status=random.choice(["ongoing", "completed", "hold"])
            )
            projects.append(p)

        db.session.add_all(projects)
        db.session.commit()

        # ---------- TEAMS ----------
        teams = []
        for project in projects:
            site = ProjectTeam(project_id=project.id, name="SITE")
            ho = ProjectTeam(project_id=project.id, name="HO")
            teams.extend([site, ho])

        db.session.add_all(teams)
        db.session.commit()

        # ---------- PROJECT ROLES ----------
        for team in teams:
            for d in designations:

                # Ensure only ONE designation per team/project
                existing = ProjectUserRole.query.filter_by(
                    project_id=team.project_id,
                    team_id=team.id,
                    designation_id=d.id
                ).first()

                if existing:
                    continue

                role = ProjectUserRole(
                    project_id=team.project_id,
                    team_id=team.id,
                    designation_id=d.id,
                    user_id=random.choice(users).id if random.random() > 0.5 else None
                )

                db.session.add(role)

        db.session.commit()

        print("✅ Seeding completed successfully!")



if __name__ == "__main__":
        seed_data()