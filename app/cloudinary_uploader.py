import os

def upload_file_to_bunny(file, mainFolder, subFolder, fileName):
    if not file:
        return None
    try:
        extension = file.filename.split(".")[-1].lower()
        final_name = f"{fileName}.{extension}"

        media_base_path = os.getenv("MEDIA_BASE_PATH")
        media_base_url  = os.getenv("MEDIA_BASE_URL")
        print("MEDIA_BASE_PATH =", media_base_path)
        if not media_base_path or not media_base_url:
            raise ValueError("MEDIA_BASE_PATH or MEDIA_BASE_URL not set in environment")

        folder_path = os.path.join(media_base_path, mainFolder, subFolder)
        os.makedirs(folder_path, exist_ok=True)

        file_path = os.path.join(folder_path, final_name)
        file.save(file_path)

        return f"{media_base_url}/{mainFolder}/{subFolder}/{final_name}"

    except Exception as e:
        print("Upload Error:", str(e))
        return None