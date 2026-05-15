# from app import create_app
# from app.extensions import db
#
# app = create_app()
#
# with app.app_context():
#     db.drop_all()
#     db.create_all()


from app import create_app
from app.models.feature_page import FeaturePage

app = create_app()

with app.app_context():

    pages = FeaturePage.query.all()

    for p in pages:
        print(p.page_code)