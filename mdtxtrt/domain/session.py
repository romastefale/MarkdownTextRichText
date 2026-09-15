from __future__ import annotations


def normalize_session(value: dict | None) -> dict:
    source = dict(value or {})
    selection = source.get("selection") if isinstance(source.get("selection"), dict) else {}
    source["selection"] = {
        "node_id": selection.get("node_id"),
        "start": int(selection.get("start") or 0),
        "end": int(selection.get("end") or 0),
    }
    source["scroll_y"] = float(source.get("scroll_y") or 0)
    source["active_node_id"] = source.get("active_node_id")
    source["active_marks"] = list(source.get("active_marks") or [])
    return source
