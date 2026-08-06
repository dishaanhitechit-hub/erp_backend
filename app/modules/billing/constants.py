GRN_CATEGORIES = {"Purchases_Order", "Customer_Supply_Order", "Site_Transfer_Order"}
SRN_CATEGORIES = {"Hire_Order", "Job_Contract_Order", "Work_Order"}

GRN_MODULE = "billing_by_grn"
SRN_MODULE = "billing_by_srn"


def get_billing_type(category):
    if category in GRN_CATEGORIES:
        return "GRN"
    if category in SRN_CATEGORIES:
        return "SRN"
    return None


def get_module_code(billing_type):
    if billing_type == "GRN":
        return GRN_MODULE
    if billing_type == "SRN":
        return SRN_MODULE
    return None
