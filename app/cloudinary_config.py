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
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)