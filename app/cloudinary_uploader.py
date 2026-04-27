import cloudinary.uploader


def upload_file_to_cloudinary(file, mainFolder, subFolder, fileName):
    """
    Generic upload function

    Example:
    upload_file_to_cloudinary(
        file=panFile,
        mainFolder="ledger",
        subFolder="L000001",
        fileName="pan"
    )
    """

    if not file:
        return None

    try:
        filename = file.filename.lower()


        # Detect raw files like PDF / DOC


        raw_extensions = [
            "pdf",
            "doc",
            "docx",
            "xls",
            "xlsx",
            "csv",
            "txt",
            "zip"
        ]

        extension = filename.split(".")[-1]

        if extension in raw_extensions:
            resourceType = "raw"
        else:
            resourceType = "image"


        # Upload to Cloudinary


        upload_result = cloudinary.uploader.upload(
            file,
            folder=f"{mainFolder}/{subFolder}",
            public_id=fileName,
            resource_type=resourceType,
            overwrite=True
        )

        return upload_result.get("secure_url")

    except Exception as e:
        print("Cloudinary Upload Error:", str(e))
        return None