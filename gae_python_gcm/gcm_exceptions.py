class GCMException(Exception):
    def __repr__(self):
        return self.message

class MissingRegistrationException(GCMException):
    message = "Check that the request contains a registration ID (either in the registration_id parameter in a plain text message, "\
        "or in the registration_ids field in JSON). "

class InvalidRegistrationException(GCMException):
    message = "Check the formatting of the registration ID that you pass to the server. Make sure it matches the registration ID the "\
    "phone receives in the com.google.android.c2dm.intent.REGISTRATION intent and that you're not truncating it or adding additional "\
    "characters. "

class MessageTooBigException(GCMException):
    message = "The total size of the payload data that is included in a message can't exceed 4096 bytes. Note that this includes both "\
    "the size of the keys as well as the values."

class InvalidDataKeyException(GCMException):
    message = "The payload data contains a key (such as from or any value prefixed by google.) that is used internally by GCM in the "\
    "com.google.android.c2dm.intent.RECEIVE Intent and cannot be used. Note that some words (such as collapse_key) are also used by "\
    "GCM but are allowed in the payload, in which case the payload value will be overridden by the GCM value. "

class InvalidTtlException(GCMException):
    message = "The value for the Time to Live field must be an integer representing a duration in seconds between 0 and 2,419,200 (4 weeks)."

class InternalServerErrorException(GCMException):
    pass

class BadRequestException(GCMException):
    def __init__(self, json_str):
        self.message = "Invalid GCM JSON message: {0}".format(json_str)