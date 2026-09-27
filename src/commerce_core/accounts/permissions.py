"""The named permissions every privileged action checks (A6a).

Core defines them; a deployment may regroup them, never rename them.
``manage_settings`` belongs to no default group and is granted explicitly.
"""

from commerce_core.platform.errors.exceptions import PermissionDenied

APP_LABEL = "accounts"

COLLECT_CASH = "collect_cash"
REQUEST_REFUND = "request_refund"
APPROVE_REFUND = "approve_refund"
APPROVE_CANCELLATION = "approve_cancellation"
ADJUST_STOCK = "adjust_stock"
RESOLVE_REVIEW = "resolve_review"
MANAGE_RETURNS = "manage_returns"
CHANGE_ADDRESS = "change_address"
CREATE_SHIPMENT = "create_shipment"
RECORD_DELIVERY = "record_delivery"
RECORD_RECEIPT = "record_receipt"
VIEW_PAYMENT_EVENTS = "view_payment_events"
MANAGE_SETTINGS = "manage_settings"

PERMISSIONS: dict[str, str] = {
    COLLECT_CASH: "Collect COD cash and record offline refund payouts",
    REQUEST_REFUND: "Request a refund of a staff-chosen amount",
    APPROVE_REFUND: "Approve a refund (second approval)",
    APPROVE_CANCELLATION: "Approve a cancellation",
    ADJUST_STOCK: "Adjust stock",
    RESOLVE_REVIEW: "Resolve a payment review case",
    MANAGE_RETURNS: "Manage returns",
    CHANGE_ADDRESS: "Change a shipping address",
    CREATE_SHIPMENT: "Create a shipment",
    RECORD_DELIVERY: "Record a courier outcome",
    RECORD_RECEIPT: "Record goods received back",
    VIEW_PAYMENT_EVENTS: "View raw payment events",
    MANAGE_SETTINGS: "Change runtime settings",
}

# Handoff section 3, User: the three default groups (A6a).
DEFAULT_GROUPS: dict[str, tuple[str, ...]] = {
    "support": (
        APPROVE_CANCELLATION,
        CHANGE_ADDRESS,
        MANAGE_RETURNS,
        COLLECT_CASH,
        RECORD_DELIVERY,
    ),
    "warehouse": (
        ADJUST_STOCK,
        MANAGE_RETURNS,
        CREATE_SHIPMENT,
        RECORD_DELIVERY,
        RECORD_RECEIPT,
    ),
    "finance": (
        REQUEST_REFUND,
        APPROVE_REFUND,
        APPROVE_CANCELLATION,
        COLLECT_CASH,
        RESOLVE_REVIEW,
        VIEW_PAYMENT_EVENTS,
    ),
}


def full_name(codename: str) -> str:
    return f"{APP_LABEL}.{codename}"


def require(user, codename: str) -> None:
    """Raise ``permission_denied`` unless ``user`` holds the named permission."""
    if codename not in PERMISSIONS:
        raise KeyError(f"{codename} is not a core permission")
    if not (user and user.is_active and user.has_perm(full_name(codename))):
        raise PermissionDenied()
