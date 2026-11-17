"""A urlopen stand-in that records the request it was handed.

Both notification channels go through `webhook_delivery.post_json`, so one fake
covers them and neither test module has to reach for a real socket.
"""

import json


class FakeResponse:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


class RecordingWebhook:
    def __init__(self, status=200, error=None):
        self.status = status
        self.error = error
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return FakeResponse(self.status)

    def payload(self, index=0):
        return json.loads(self.requests[index].data.decode("utf-8"))
