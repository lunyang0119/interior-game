"""Error type shared by all layers. Rendered as {"error": code} by main.py."""


class ApiError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def bad_request(code: str) -> ApiError:
    return ApiError(400, code)
