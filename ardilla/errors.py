
class BaseDBException(Exception):
    pass


class ModelIntegrityError(BaseDBException):
    pass

class MissingEngine(BaseDBException):
    pass
