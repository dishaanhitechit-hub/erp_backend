def res(msg="", data=None, code=200):
    return {
        "message": msg,
        "data": data if data is not None else []
    }, code