"""Claude Haiku integration for AI-suggested exercise substitutions
(BACKLOG item 4, Session B). Server-side only — the API key never reaches the
browser. The 100/day guardrail (can_make_ai_call) and the per-exercise cache
live in db.py / the route layer; this module only builds the prompt, calls
Haiku, and validates the response against the real schema enums, failing closed
on anything malformed so a bad response is never shown or cached.
"""

import json

from anthropic import Anthropic

from .importer import EXERCISE_TYPES, MOVEMENT_PATTERNS, MUSCLE_GROUPS

MODEL = "claude-haiku-4-5-20251001"

# every field the swap sheet and library creation need (BACKLOG response contract)
SUGGESTION_FIELDS = (
    "name", "reason", "movement_pattern", "muscle_group",
    "equipment", "exercise_type", "cue", "youtube_query",
)

# structured-outputs schema: enums are enforced by the model, then re-validated
# server-side below (belt and suspenders — structured outputs can be refused).
_SUGGESTION_OBJECT = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "reason": {"type": "string"},
        "movement_pattern": {"type": "string", "enum": sorted(MOVEMENT_PATTERNS)},
        "muscle_group": {"type": "string", "enum": sorted(MUSCLE_GROUPS)},
        "equipment": {"type": "string"},
        "exercise_type": {"type": "string", "enum": sorted(EXERCISE_TYPES)},
        "cue": {"type": "string"},
        "youtube_query": {"type": "string"},
    },
    "required": list(SUGGESTION_FIELDS),
    "additionalProperties": False,
}
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"suggestions": {"type": "array", "items": _SUGGESTION_OBJECT}},
    "required": ["suggestions"],
    "additionalProperties": False,
}


class AICallError(Exception):
    """The Haiku call could not be completed (offline, API error)."""


class AIValidationError(Exception):
    """A response came back but was malformed or failed enum validation."""


def _build_prompt(planned, objective, program_routines, exclusions, count):
    """Assemble the Haiku prompt from primitives. `planned` is a dict with the
    exercise being replaced; `program_routines` is [{name, exercises:[names]}]."""
    lines = [
        f"A lifter needs {count} substitute exercise(s) for one movement in their "
        "workout. The equipment for the exercise below is unavailable right now, so "
        "each substitute MUST work a similar pattern WITHOUT requiring that same "
        "equipment.",
        "",
        "Exercise to replace:",
        f"  name: {planned['name']}",
        f"  cue: {planned.get('cue') or '(none)'}",
        f"  movement_pattern: {planned['movement_pattern']}",
        f"  muscle_group: {planned['muscle_group']}",
        f"  equipment (UNAVAILABLE — do not require this): {planned.get('equipment') or '(unspecified)'}",
        f"  exercise_type: {planned['exercise_type']}",
        "",
        f"Program objective: {objective or '(not specified)'}",
        "",
        "Full program for context:",
    ]
    for r in program_routines:
        exs = ", ".join(r["exercises"]) if r["exercises"] else "(none)"
        lines.append(f"  {r['name']}: {exs}")
    lines.append("")
    if exclusions:
        lines.append("Do NOT suggest any of these (already suggested for this slot):")
        lines.append("  " + ", ".join(sorted(exclusions)))
        lines.append("")
    lines.extend([
        f"Return exactly {count} suggestion(s). Each needs: name, reason (one short "
        "sentence), movement_pattern, muscle_group, equipment, exercise_type, cue, "
        "youtube_query. movement_pattern must be one of: "
        + ", ".join(sorted(MOVEMENT_PATTERNS)) + ". muscle_group must be one of: "
        + ", ".join(sorted(MUSCLE_GROUPS)) + ". exercise_type must be one of: "
        + ", ".join(sorted(EXERCISE_TYPES)) + ".",
    ])
    return "\n".join(lines)


def _validate(raw):
    """Return a clean suggestion dict or raise AIValidationError."""
    if not isinstance(raw, dict):
        raise AIValidationError("suggestion is not an object")
    out = {}
    for field in SUGGESTION_FIELDS:
        val = raw.get(field)
        if not isinstance(val, str) or not val.strip():
            raise AIValidationError(f"missing/blank field: {field}")
        out[field] = val.strip()
    if out["movement_pattern"] not in MOVEMENT_PATTERNS:
        raise AIValidationError(f"bad movement_pattern: {out['movement_pattern']}")
    if out["muscle_group"] not in MUSCLE_GROUPS:
        raise AIValidationError(f"bad muscle_group: {out['muscle_group']}")
    if out["exercise_type"] not in EXERCISE_TYPES:
        raise AIValidationError(f"bad exercise_type: {out['exercise_type']}")
    return out


def fetch_suggestions(planned, objective, program_routines, exclusions, count):
    """Call Haiku for `count` new suggestions. Returns a list of validated dicts.
    Raises AICallError if the call itself fails, AIValidationError if the response
    is malformed or fails enum validation (fail closed — caller shows a retry state
    and stores nothing)."""
    prompt = _build_prompt(planned, objective, program_routines, exclusions, count)
    try:
        resp = Anthropic().messages.create(
            model=MODEL,
            max_tokens=2048,
            output_config={"format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}},
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:  # network, auth, rate limit, refusal-as-error, etc.
        raise AICallError(str(e))
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        raise AIValidationError("empty response")
    try:
        data = json.loads(text)
        raw_list = data["suggestions"]
    except (ValueError, KeyError, TypeError):
        raise AIValidationError("response was not the expected JSON shape")
    if not isinstance(raw_list, list) or not raw_list:
        raise AIValidationError("no suggestions in response")
    return [_validate(s) for s in raw_list]
