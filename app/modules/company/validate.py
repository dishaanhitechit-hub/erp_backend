import re

def validate_company_data(data):
    errors = {}

    #  Email validation
    email = data.get("email")
    if email:
        if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
            errors["email"] = "Invalid email format"

    #  State should not be integer
    state = data.get("state")
    if state and state.isdigit():
        errors["state"] = "State must be a valid name, not number"

    #  Contact number (10 digits)
    contact = data.get("contactNumber")
    if contact:
        if not re.match(r"^\d{10}$", contact):
            errors["contactNumber"] = "Contact number must be 10 digits"

    #  PAN format (basic)
    pan = data.get("pan")
    if pan:
        if not re.match(r"[A-Z]{5}[0-9]{4}[A-Z]{1}", pan):
            errors["pan"] = "Invalid PAN format"

    #  GST format (basic)
    gstn = data.get("gstn")
    if gstn:
        if len(gstn) != 15:
            errors["gstn"] = "GSTN must be 15 characters"

    return errors