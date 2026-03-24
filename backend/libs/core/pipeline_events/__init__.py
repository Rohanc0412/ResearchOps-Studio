"""
Pipeline event utilities for run event emission and node instrumentation.

Provides:
- emit_run_event: Emit SSE events to run_events table
- instrument_node: Decorator for automatic event emission
"""

from __future__ import annotations

from core.pipeline_events.events import (
    emit_run_event,
    instrument_node,
)

__all__ = [
    "emit_run_event",
    "instrument_node",
]
