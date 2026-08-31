"""Safe HTTP errors; never reflect client fields or provider responses."""

from rest_framework.exceptions import APIException


class RequirementAnalysisAPIError(APIException):
    def __init__(self, code, message, *, status_code):
        self.status_code = status_code
        super().__init__({"code": code, "message": message})


HTTP_ERRORS = {
    400: ("invalid_request", "The requirement analysis request is invalid."),
    401: ("not_authenticated", "Authentication credentials are required or invalid."),
    403: ("permission_denied", "You do not have permission to perform this action."),
    404: ("not_found", "The requested resource was not found."),
    405: ("method_not_allowed", "This method is not allowed."),
    415: ("unsupported_media_type", "The request media type is not supported."),
}
