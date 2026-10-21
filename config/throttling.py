"""Per-action scoped throttling for endpoints that spend real provider quota."""

from rest_framework.throttling import ScopedRateThrottle


class ScopedActionThrottleMixin:
    """Keep the global throttles and add a scoped rate only for spend actions.

    A viewset-wide ``throttle_scope`` would also meter cheap reads, so the scope
    is selected per action. Each action name maps to one configured scope.
    """

    scoped_throttle_actions: dict[str, str] = {}

    def get_throttles(self):
        throttles = list(super().get_throttles())
        scope = self.scoped_throttle_actions.get(getattr(self, "action", None))
        if scope is not None:
            # ScopedRateThrottle reads this attribute in allow_request().
            self.throttle_scope = scope
            throttles.append(ScopedRateThrottle())
        return throttles
