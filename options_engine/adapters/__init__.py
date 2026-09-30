"""Broker adapters for the options engine.

The generic execution interfaces live in :mod:`options_engine.execution`.
Broker-specific integrations live in this package.
"""

from options_engine.execution import DemoOnlyAdapter, ExecutionAdapter, PaperAdapter

__all__ = [
    "ExecutionAdapter",
    "PaperAdapter",
    "DemoOnlyAdapter",
]
