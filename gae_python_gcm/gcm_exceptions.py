class GCMException(Exception):
    def __repr__(self):
        return self.message

class MissingRegistrationException(GCMException):
    message = "Raised when GCM message sent without device token. This should not happen!"

class MessageTooBigException(GCMException):
    message = "GCM message too big (max 4096 bytes)."

class InvalidTtlException(GCMException):
    message = "GCM Time to Live field must be an integer representing a duration in seconds between 0 and 2,419,200 (4 weeks)."

class InternalServerErrorException(GCMException):
    pass

class BadRequestException(GCMException):
    def __init__(self, json_str):
        self.message = "Invalid GCM JSON message: {0}".format(json_str)