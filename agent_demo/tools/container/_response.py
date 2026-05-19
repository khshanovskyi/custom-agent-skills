from typing import Optional

from pydantic import BaseModel, Field


class _FileReference(BaseModel):
    """A file result with its MIME type and base64-encoded content."""

    uri: str
    mime_type: str
    name: str
    size: int


class _ExecutionResult(BaseModel):
    """Standardized response structure for code execution."""

    success: bool
    output: list[str] = Field(default_factory=list)
    result: Optional[str] = Field(default=None)
    error: Optional[str] = Field(default=None)
    traceback: list[str] = Field(default_factory=list)
    files: list[_FileReference] = Field(default_factory=list)
