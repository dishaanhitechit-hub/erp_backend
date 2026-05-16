# import cloudinary.uploader
#
#
# def upload_file_to_cloudinary(file, mainFolder, subFolder, fileName):
#     """
#     Generic upload function
#
#     Example:
#     upload_file_to_cloudinary(
#         file=panFile,
#         mainFolder="ledger",
#         subFolder="L000001",
#         fileName="pan"
#     )
#     """
#
#     if not file:
#         return None
#
#     try:
#         filename = file.filename.lower()
#
#
#         # Detect raw files like PDF / DOC
#
#
#         raw_extensions = [
#             "pdf",
#             "doc",
#             "docx",
#             "xls",
#             "xlsx",
#             "csv",
#             "txt",
#             "zip"
#         ]
#
#         extension = filename.split(".")[-1]
#
#         if extension in raw_extensions:
#             resourceType = "raw"
#         else:
#             resourceType = "image"
#
#
#         # Upload to Cloudinary
#
#
#         upload_result = cloudinary.uploader.upload(
#             file,
#             folder=f"{mainFolder}/{subFolder}",
#             public_id=fileName,
#             resource_type=resourceType,
#             overwrite=True
#         )
#
#         return upload_result.get("secure_url")
#
#     except Exception as e:
#         print("Cloudinary Upload Error:", str(e))
#         return None

import requests

from cloudinary_config import *


def upload_file_to_bunny(
        file,
        mainFolder,
        subFolder,
        fileName
):

    if not file:
        return None

    try:

        extension = (
            file.filename
            .split(".")[-1]
            .lower()
        )

        final_name = (
            f"{fileName}.{extension}"
        )

        bunny_path = (
            f"{mainFolder}/"
            f"{subFolder}/"
            f"{final_name}"
        )

        upload_url = (
            f"{BunnyConfig.BASE_URL}/"
            f"{bunny_path}"
        )

        headers = {
            "AccessKey":
                BunnyConfig.ACCESS_KEY,
            "Content-Type":
                "application/octet-stream"
        }

        response = requests.put(
            upload_url,
            headers=headers,
            data=file.read()
        )

        if response.status_code in [200, 201]:

            return (
                f"{BunnyConfig.CDN_URL}/"
                f"{bunny_path}"
            )

        print(response.text)

        return None

    except Exception as e:

        print(
            "Upload Error:",
            str(e)
        )

        return None