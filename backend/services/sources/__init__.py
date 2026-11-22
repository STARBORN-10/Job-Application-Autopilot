"""
Job source plugins. See base.py for the interface, registry.py for the list of sources and the
per-source settings, and runner.py for how a run executes them.

Kept free of imports on purpose: jsearch_service imports services.sources.common, so importing
the registry here would create an import cycle.
"""
