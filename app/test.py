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
from app.models.approval_path import *
from app.models.user import User
import pandas as pd
from reportlab.platypus import SimpleDocTemplate, Preformatted
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Spacer, Paragraph
from reportlab.lib import colors
from reportlab.lib import styles
from reportlab.lib import units

app = create_app()

with app.app_context():

    pages = ModuleMaster.query.all()

    pdf = SimpleDocTemplate(
        "module_master_report.pdf"
    )

    elements = []

    style_sheet = styles.getSampleStyleSheet()

    title = Paragraph(
        "Module Master Report",
        style_sheet['Title']
    )

    elements.append(title)
    elements.append(Spacer(1, 0.3 * units.inch))

    # Header
    data = [["Page Name", "Page Code"]]

    # Rows
    for p in pages:
        data.append([
            str(p.module_name),
            str(p.module_code)
        ])

    table = Table(
        data,
        colWidths=[250, 200]
    )

    table.setStyle(
        TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.grey),
            ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),

            ('ALIGN',(0,0),(-1,-1),'CENTER'),

            ('FONTNAME', (0,0),(-1,0),'Helvetica-Bold'),
            ('FONTSIZE', (0,0),(-1,-1),10),

            ('BOTTOMPADDING',(0,0),(-1,0),12),

            ('GRID',(0,0),(-1,-1),1,colors.black),

            ('BACKGROUND',(0,1),(-1,-1),colors.beige)
        ])
    )

    elements.append(table)

    pdf.build(elements)

    print("PDF created successfully: module_master_report.pdf")



    # name = User.query.all()
    #
    # data = []
    #
    # for n in name:
    #     data.append({
    #         "Username": n.username,
    #         "Login Username": n.login_username
    #     })
    #
    # df = pd.DataFrame(data)
    #
    # df.to_excel("users.xlsx", index=False)
    #
    # print("Excel exported successfully")