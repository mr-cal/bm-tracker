"""Achievements: a data-driven registry, the facts it reads, and the engine.

Adding achievement #301 is a diff in `achievements.toml`. The package exists so
that never requires understanding the engine.
"""

from bm_tracker.achievements.registry import Achievement, Registry, RegistryError, load

__all__ = ["Achievement", "Registry", "RegistryError", "load"]
