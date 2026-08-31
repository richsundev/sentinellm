"""ID generation helpers."""

from __future__ import annotations

import uuid


def new_uuid() -> str:
    return str(uuid.uuid4())


def new_trace_id() -> str:
    return f"trc_{uuid.uuid4().hex}"


def new_request_id() -> str:
    return f"req_{uuid.uuid4().hex}"
