"""Optional host adapter helper; never registered as a model-facing MCP tool."""
import os

from .store import Store
from .stopping import Protocol


def delivery(source_uri, origin_id, scope, content, case_keys, status="ok"):
    """Call BEFORE returning source content/snippets, using canonical host case IDs.

    With no ARV_RESEARCH this adapter is outside a managed protocol run. Once bound,
    incomplete host configuration fails closed. All source-access paths in the run
    must use this hook. Metadata with revealing snippets is also a delivery.
    """
    rid = os.environ.get("ARV_RESEARCH")
    if not rid:
        return None
    path, actor = os.environ.get("ARV_DB"), os.environ.get("ARV_ACTOR")
    if not path or not actor:
        raise RuntimeError("Instrumented source needs ARV_DB, ARV_RESEARCH and ARV_ACTOR")
    return Protocol(Store(path)).deliver(rid, actor, source_uri, origin_id, scope, content, case_keys, status)


def aliases(case_keys):
    """Host-only source-proven aliases; freshness rechecks old receipts against them."""
    rid = os.environ.get("ARV_RESEARCH")
    if not rid:
        return None
    path, actor = os.environ.get("ARV_DB"), os.environ.get("ARV_ACTOR")
    if not path or not actor:
        raise RuntimeError("Instrumented source needs ARV_DB, ARV_RESEARCH and ARV_ACTOR")
    return Protocol(Store(path), actor=actor).alias(rid, case_keys)
