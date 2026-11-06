"""JARVIS plugins package: manifest-based plugin lifecycle (spec section 14).

Plugins are staged, statically analyzed, explicitly approved, and only then
installed and imported. Their tools run through the same permission and
audit system as built-ins.
"""

__all__ = ["plugin_manager"]
