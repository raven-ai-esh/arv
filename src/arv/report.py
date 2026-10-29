"""Bind an unreviewed proposal and optional typed citation dossier to one verdict."""
from .store import digest
import json


def reviewed_report_hash(proposal, citation_roles=None):
    model = {k: v for k, v in proposal.items() if k != "candidate_id"}
    return digest(model if citation_roles is None else {"proposal": model, "citation_roles": citation_roles})


def primary_source_match(fragment, source):
    """Return exact extraction type; never accept paraphrases or changed JSON values."""
    if fragment in source:
        return "literal_passage"
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON keys")
            result[key] = value
        return result
    def parse(value):
        return json.loads(value, object_pairs_hook=unique_object)
    try:
        original = parse(source)
    except (ValueError, TypeError):
        return ""
    def values(value):
        yield value
        if isinstance(value, dict):
            for child in value.values():
                yield from values(child)
        elif isinstance(value, list):
            for child in value:
                yield from values(child)
    candidates = list(values(original))
    if any(fragment in value for value in candidates if isinstance(value, str)):
        return "literal_field_text"
    extraction = "exact_json_field_projection"
    try:
        projection = parse(fragment)
    except (ValueError, TypeError):
        # A quoted sequence of original JSON object members is also an exact
        # field extraction. Adding braces adds no field or factual value.
        if not fragment.lstrip().startswith('"'):
            return ""
        try:
            projection = parse("{" + fragment + "}")
            extraction = "exact_json_member_projection"
        except (ValueError, TypeError):
            # Some source extracts quote one complete JSON member per line,
            # without inter-member commas. Parse each singleton strictly.
            projection = {}
            try:
                for line in fragment.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    field = parse("{" + line.removesuffix(",") + "}")
                    if len(field) != 1 or set(field) & set(projection):
                        return ""
                    projection.update(field)
                extraction = "exact_json_field_lines"
            except (ValueError, TypeError):
                return ""
    if not isinstance(projection, dict) or not projection:
        return ""
    def subset(part, whole):
        if type(part) is not type(whole):
            return False
        if isinstance(part, dict):
            return bool(part) and all(k in whole and subset(v, whole[k]) for k, v in part.items())
        if isinstance(part, list):
            return len(part) == len(whole) and all(subset(a, b) for a, b in zip(part, whole))
        return part == whole
    return extraction if any(subset(projection, value) for value in candidates if isinstance(value, dict)) else ""
