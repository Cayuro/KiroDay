"""Pytest configuration and shared Hypothesis profile for the POS backend.

Registers a ``pos`` Hypothesis profile with ``max_examples>=100`` (as required
by the design's property-based testing strategy) and activates it for the whole
test session.
"""

from __future__ import annotations

from hypothesis import HealthCheck, settings

# Property-based tests must run at least 100 iterations each (design.md).
settings.register_profile(
    "pos",
    max_examples=100,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
settings.load_profile("pos")
