# app/cloudinary_config.py

# import cloudinary
#
# cloudinary.config(
#     cloud_name="dn3cq0lbu",
#     api_key="811429497525459",
#     api_secret="IoFNga0m03AXpBxbCSclBgtjEP8",
#     secure=True
# )

import os
import cloudinary

cloudinary.config(
    cloud_name=os.getenv("dn3cq0lbu"),
    api_key=os.getenv("811429497525459"),
    api_secret=os.getenv("IoFNga0m03AXpBxbCSclBgtjEP8"),
    secure=True
)