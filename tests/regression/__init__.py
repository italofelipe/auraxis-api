"""Regression suite for already-fixed bugs.

Each module here locks in the fix for a specific production bug so it cannot be
silently reintroduced. Tests are named after the bug they guard and reference the
originating fix (commit or issue) in their docstring.
"""
