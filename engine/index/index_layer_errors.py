"""Exception types for the M3 index layer.

Purpose: one shared error vocabulary so callers (Ask-Omni service, server
handlers, tests) can distinguish "a heavy dependency is missing" from "the
index operation itself failed" without string-matching messages.
Pipeline position: imported by every ``engine.index`` module; raised at the
embedder/vec-store/watcher boundaries and inside the indexer.

Security invariant: missing optional dependencies FAIL CLOSED with a clear,
actionable message — the index layer never silently degrades into returning
wrong or partial answers while pretending the dense/vector path ran.
"""


class IndexLayerError(Exception):
    """An index-layer operation failed (indexing, retrieval, or lookup)."""


class IndexDependencyMissingError(IndexLayerError):
    """A lazily-imported heavy dependency is unavailable.

    Raised instead of ``ImportError`` so the caller gets an actionable
    message naming the package and where it is tracked
    (docs/progress/pending-deps.txt). Fail closed: the operation that
    needed the dependency does not proceed.
    """
