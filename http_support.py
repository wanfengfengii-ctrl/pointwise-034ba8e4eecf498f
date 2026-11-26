import json


MAX_ID = (1 << 63) - 1
MAX_BODY = 16 * 1024 * 1024


class Problem(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def require_id(value, name):
    if type(value) is not int or not 1 <= value <= MAX_ID:
        raise Problem(400, f'{name} must be a positive ID')
    return value


def path_id(value):
    if value.isascii() and value.isdecimal() and len(value) <= 19:
        identifier = int(value)
        if 1 <= identifier <= MAX_ID:
            return identifier
    raise Problem(404, 'resource not found')


def _invalid_constant(value):
    raise ValueError(f'{value} is not JSON')


def read_object(handler):
    try:
        length = int(handler.headers.get('Content-Length', '0'))
    except ValueError as error:
        raise Problem(400, 'invalid body length') from error
    if length < 0 or length > MAX_BODY:
        raise Problem(400, 'invalid body length')
    if length == 0:
        return {}
    try:
        data = json.loads(handler.rfile.read(length), parse_constant=_invalid_constant)
    except (ValueError, RecursionError) as error:
        raise Problem(400, 'invalid JSON body') from error
    if not isinstance(data, dict):
        raise Problem(400, 'JSON body must be an object')
    return data
