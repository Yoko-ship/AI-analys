"""Publication receipts shared by collectors that push to the web application."""
from collection_ops.model import receipt, scrub

def publish(post, logger, path, url, body, secret):
    rows = body.get("rows") or []
    heartbeat = path == "/api/admin/facts" and rows and all(
        row.get("entity_id") == "_collector" for row in rows)
    stage = "heartbeat" if heartbeat else path
    if not secret:
        receipt(stage, ok=False, phase="publication", reason="ADMIN_API_SECRET is not configured.")
        logger.error("ADMIN_API_SECRET is not set — cannot push")
        return 2
    try:
        response = post(url, json=body, headers={"X-Admin-Secret": secret}, timeout=120)
    except Exception as exc:
        receipt(stage, ok=False, phase="publication", reason=f"{type(exc).__name__}: {scrub(str(exc))}")
        raise
    if response.status_code != 200:
        reason = f"HTTP {response.status_code}: {scrub(response.text)[:500]}"
        receipt(stage, ok=False, phase="publication", reason=reason)
        logger.error("push %s failed: %s", path, reason)
        return 1
    try:
        result = response.json()
        if not isinstance(result, dict):
            raise ValueError("Expected a publication receipt object.")
    except ValueError as exc:
        receipt(stage, ok=False, phase="publication", reason=f"Invalid publication response: {type(exc).__name__}")
        raise
    counts = {k: v for k, v in result.items() if isinstance(v, int) and not isinstance(v, bool)}
    accepted = result.get("ok") is not False
    receipt(stage, ok=accepted, counts=counts, phase="publication",
            reason="" if accepted else "The server declined the publication.")
    errors = result.get("errors") or []
    for error in errors:
        if isinstance(error, dict):
            receipt(error.get("stage") or stage, ok=False, phase="publication", reason=str(error.get("reason") or "Publication failed."))
        else:
            receipt(stage, ok=False, phase="publication", reason=str(error))
    logger.info("push %s: accepted=%s counts=%s errors=%d", path, accepted, counts, len(errors))
    return 0 if accepted and not errors else 1
