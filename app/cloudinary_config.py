# app/cloudinary_config.py

# import cloudinary
#
# cloudinary.config(
#     cloud_name="dn3cq0lbu",
#     api_key="811429497525459",
#     api_secret="IoFNga0m03AXpBxbCSclBgtjEP8",
#     secure=True
# )

# import os
# import cloudinary
#
# cloudinary.config(
#     cloud_name=os.getenv("dn3cq0lbu"),
#     api_key=os.getenv("811429497525459"),
#     api_secret=os.getenv("IoFNga0m03AXpBxbCSclBgtjEP8"),
#     secure=True
# )

# config/bunny_config.py

import os
from dotenv import load_dotenv

load_dotenv()

class BunnyConfig:

    STORAGE_ZONE = os.getenv(
        "BUNNY_STORAGE_ZONE"
    )

    ACCESS_KEY = os.getenv(
        "BUNNY_ACCESS_KEY"
    )

    REGION = os.getenv(
        "BUNNY_REGION",
        "sg"
    )

    BASE_URL = (
        f"https://"
        f"{REGION}.storage.bunnycdn.com/"
        f"{STORAGE_ZONE}"
    )

    CDN_URL = (
        f"https://"
        f"{STORAGE_ZONE}.b-cdn.net"
    )