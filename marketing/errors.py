from admin_control.store import ControlError


class MarketingError(ControlError):
    """A safe, actionable domain error, serialized by the admin route handler."""


def require_owner(actor):
    if actor.get("role") != "administrator":
        raise MarketingError("OWNER_REQUIRED", "Only the owner can approve this decision.", 403)
