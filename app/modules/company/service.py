import os
import uuid
from flask import current_app
from app.models.companies import Company
from app.extensions import db
from app.response import res

UPLOAD_FOLDER = "uploads/company"

def create_company(request):
    data = request.form
    files = request.files

    company = Company(
        company_name=data.get("companyName"),
        registered_address=data.get("registeredAddress"),
        corporate_address=data.get("corporateAddress"),
        pan=data.get("pan"),
        gstn=data.get("gstn"),
        gstn_type=data.get("gstnType"),
        state=data.get("state"),
        state_code=data.get("stateCode"),
        contact_person=data.get("contactPerson"),
        contact_number=data.get("contactNumber"),
        whatsapp_number=data.get("whatsappNumber"),
        email=data.get("email")
    )

    # ensure folder exists
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    #  PAN file
    pan_file = files.get("panFile")
    if pan_file:
        ext = pan_file.filename.split('.')[-1]
        filename = f"pan_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        pan_file.save(filepath)
        company.pan_file = filename

    #  GST file
    gstn_file = files.get("gstnFile")
    if gstn_file:
        ext = gstn_file.filename.split('.')[-1]
        filename = f"gst_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        gstn_file.save(filepath)
        company.gstn_file = filename

    db.session.add(company)
    db.session.commit()

    base_url = request.host_url

    data = {
        "id": company.id,
        "companyName": company.company_name,
        "panUrl": f"{base_url}compny/uploads/company/{company.pan_file}" if company.pan_file else None,
        "gstnUrl": f"{base_url}compny/uploads/company/{company.gstn_file}" if company.gstn_file else None
    }

    return res("Company created successfully", data)



def get_company_by_id(company_id, request):
    base_url = request.host_url
    if not company_id:
        companies = Company.query.all()

        data = [
            {
                "id": c.id,
                "companyName": c.company_name,
                "registeredAddress": c.registered_address,
                "corporateAddress": c.corporate_address,
                "pan": c.pan,
                "gstn": c.gstn,
                "gstnType": c.gstn_type,
                "state": c.state,
                "stateCode": c.state_code,
                "contactPerson": c.contact_person,
                "contactNumber": c.contact_number,
                "whatsappNumber": c.whatsapp_number,
                "email": c.email,
                "panUrl": f"{base_url}compny/uploads/company/{c.pan_file}" if c.pan_file else None,
                "gstnUrl": f"{base_url}compny/uploads/company/{c.gstn_file}" if c.gstn_file else None
            }
            for c in companies
        ]
    return res("All companies fetched", data, 200)

    company = Company.query.get(company_id)

    if not company:
        return res("Company not found", [], 200)

    data = [{
        "id": company.id,
        "companyName": company.company_name,
        "registeredAddress": company.registered_address,
        "corporateAddress": company.corporate_address,
        "pan": company.pan,
        "gstn": company.gstn,
        "gstnType": company.gstn_type,
        "state": company.state,
        "stateCode": company.state_code,
        "contactPerson": company.contact_person,
        "contactNumber": company.contact_number,
        "whatsappNumber": company.whatsapp_number,
        "email": company.email,

        #  file URLs
        "panUrl": f"{base_url}compny/uploads/company/{company.pan_file}" if company.pan_file else None,
        "gstnUrl": f"{base_url}compny/uploads/company/{company.gstn_file}" if company.gstn_file else None
    }]

    return res("Company details fetched successfully", data)

def update_company(company_id, request):
    company = Company.query.get(company_id)

    if not company:
        return res("Company not found", [], 200)

    data = request.form
    files = request.files

    # Update fields
    company.company_name = data.get("companyName", company.company_name)
    company.registered_address = data.get("registeredAddress", company.registered_address)
    company.corporate_address = data.get("corporateAddress", company.corporate_address)
    company.pan = data.get("pan", company.pan)
    company.gstn = data.get("gstn", company.gstn)
    company.gstn_type = data.get("gstnType", company.gstn_type)
    company.state = data.get("state", company.state)
    company.state_code = data.get("stateCode", company.state_code)
    company.contact_person = data.get("contactPerson", company.contact_person)
    company.contact_number = data.get("contactNumber", company.contact_number)
    company.whatsapp_number = data.get("whatsappNumber", company.whatsapp_number)
    company.email = data.get("email", company.email)

    # ensure folder exists
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    #  PAN FILE UPDATE
    pan_file = files.get("panFile")
    if pan_file:
        # delete old file
        if company.pan_file:
            old_path = os.path.join(UPLOAD_FOLDER, company.pan_file)
            if os.path.exists(old_path):
                os.remove(old_path)

        ext = pan_file.filename.split('.')[-1]
        filename = f"pan_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        pan_file.save(filepath)
        company.pan_file = filename

    # GST FILE UPDATE
    gstn_file = files.get("gstnFile")
    if gstn_file:
        # delete old file
        if company.gstn_file:
            old_path = os.path.join(UPLOAD_FOLDER, company.gstn_file)
            if os.path.exists(old_path):
                os.remove(old_path)

        ext = gstn_file.filename.split('.')[-1]
        filename = f"gst_{uuid.uuid4()}.{ext}"
        filepath = os.path.join(UPLOAD_FOLDER, filename)

        gstn_file.save(filepath)
        company.gstn_file = filename

    db.session.commit()

    base_url = request.host_url

    data = [{
        "id": company.id,
        "companyName": company.company_name,
        "panUrl": f"{base_url}compny/uploads/company/{company.pan_file}" if company.pan_file else None,
        "gstnUrl": f"{base_url}compny/uploads/company/{company.gstn_file}" if company.gstn_file else None
    }]

    return res("Company updated successfully", data)