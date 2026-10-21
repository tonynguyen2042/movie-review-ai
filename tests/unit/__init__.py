"""Test package.

The package markers make the test modules importable under a dotted name, so
two test files with the same basename in different directories cannot
collide, and so mypy resolves them as `tests.<dir>.<module>` rather than as
bare top-level names.
"""
