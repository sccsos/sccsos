"""Webhook management API routes."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from sccsos.security.rbac import require_permission

router = APIRouter(prefix="/api/v1/webhooks", tags=["webhooks"])


class WebhookEndpoint(BaseModel):
    url: str
    events: list[str] = ["*"]
    secret: str = ""
    enabled: bool = True


@router.get("")
async def list_webhooks(
    _: None = Depends(require_permission("webhooks:read")),
):
    """List all configured webhook endpoints."""
    from sccsos.core.config import get_config
    cfg = get_config()
    endpoints = getattr(cfg.webhooks, "endpoints", [])
    return {
        "enabled": cfg.webhooks.enabled,
        "endpoints": [
            {
                "url": ep.url,
                "events": list(ep.events) if ep.events else ["*"],
                "enabled": getattr(ep, "enabled", True),
            }
            for ep in endpoints
        ],
    }


@router.post("")
async def add_webhook(
    ep: WebhookEndpoint,
    _: None = Depends(require_permission("webhooks:write")),
):
    """Add a webhook endpoint."""
    from sccsos.core.config import get_config, reload_config, _config_path
    from pathlib import Path
    import yaml

    cfg_path = Path(_config_path) if _config_path else Path("sccsos.yaml")
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="sccsos.yaml not found")

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    wh = data.setdefault("webhooks", {})
    wh.setdefault("endpoints", [])

    # Check for duplicate URL
    for existing in wh["endpoints"]:
        if existing.get("url") == ep.url:
            raise HTTPException(status_code=400, detail=f"Webhook URL already exists: {ep.url}")

    wh["endpoints"].append({
        "url": ep.url,
        "events": ep.events,
        "secret": ep.secret,
        "enabled": ep.enabled,
    })

    cfg_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    reload_config()
    return {"status": "added", "url": ep.url}


@router.delete("")
async def remove_webhook(
    url: str,
    _: None = Depends(require_permission("webhooks:write")),
):
    """Remove a webhook endpoint by URL."""
    from sccsos.core.config import get_config, reload_config, _config_path
    from pathlib import Path
    import yaml

    cfg_path = Path(_config_path) if _config_path else Path("sccsos.yaml")
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="sccsos.yaml not found")

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    wh = data.get("webhooks", {})
    endpoints = wh.get("endpoints", [])

    before = len(endpoints)
    wh["endpoints"] = [ep for ep in endpoints if ep.get("url") != url]

    if len(wh["endpoints"]) == before:
        raise HTTPException(status_code=404, detail=f"Webhook not found: {url}")

    cfg_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    reload_config()
    return {"status": "removed", "url": url}


@router.post("/toggle")
async def toggle_webhooks(
    enabled: bool,
    _: None = Depends(require_permission("webhooks:write")),
):
    """Enable or disable webhooks globally."""
    from sccsos.core.config import get_config, reload_config, _config_path
    from pathlib import Path
    import yaml

    cfg_path = Path(_config_path) if _config_path else Path("sccsos.yaml")
    if not cfg_path.exists():
        raise HTTPException(status_code=404, detail="sccsos.yaml not found")

    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    wh = data.setdefault("webhooks", {})
    wh["enabled"] = enabled

    cfg_path.write_text(yaml.dump(data, default_flow_style=False, allow_unicode=True), encoding="utf-8")
    reload_config()
    return {"status": "updated", "enabled": enabled}
