"""Pydantic request/response models for the sccsos API."""
from __future__ import annotations

from typing import Optional

try:
    from pydantic import BaseModel
except ImportError:
    raise ImportError(
        "sccsos[api] extras are required for the FastAPI server. "
        "Install with: pip install sccsos[api]"
    )


class RegisterAgentRequest(BaseModel):
    name: str
    version: str = "1.0"
    description: str = ""
    toolsets: list[str] = []
    tags: list[str] = []
    tenant_id: str = "default"


class AskRequest(BaseModel):
    prompt: str
    timeout: int = 300


class RunWorkflowRequest(BaseModel):
    file: str
    input: Optional[dict] = None


class ValidateWorkflowRequest(BaseModel):
    file: str


class ErrorResponse(BaseModel):
    error: str
