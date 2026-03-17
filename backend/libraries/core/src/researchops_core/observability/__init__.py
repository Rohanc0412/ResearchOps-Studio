"""
Observability utilities for event emission and instrumentation.

Provides:
- emit_run_event: Emit SSE events to run_events table
- instrument_node: Decorator for automatic event emission
"""

from __future__ import annotations

from researchops_core.observability.events import (
    emit_run_event,
    instrument_node,
)

__all__ = [
    "emit_run_event",
    "instrument_node",
]
