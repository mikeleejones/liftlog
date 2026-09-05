"""Claude Haiku integration for the in-app program builder."""

import json

from anthropic import Anthropic

from . import ai, importer


_EXERCISE = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "movement_pattern": {"type": "string", "enum": sorted(importer.MOVEMENT_PATTERNS)},
        "muscle_group": {"type": "string", "enum": sorted(importer.MUSCLE_GROUPS)},
        "sets": {"type": "integer"},
        "rep_min": {"type": "integer"},
        "rep_max": {"type": "integer"},
        "rest_seconds": {"type": "integer"},
        "increment_kg": {"type": "number"},
        "exercise_type": {"type": "string", "enum": sorted(importer.EXERCISE_TYPES)},
        "display_unit": {"type": "string", "enum": sorted(importer.DISPLAY_UNITS)},
        "equipment": {"type": "string"},
        "is_primary": {"type": "boolean"},
        "cue": {"type": "string"},
        "youtube_query": {"type": "string"},
    },
    "required": ["name", "movement_pattern", "muscle_group", "sets", "rep_min", "rep_max"],
    "additionalProperties": False,
}
_ROUTINE = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "week": {"type": "integer"}, "exercises": {"type": "array", "items": _EXERCISE}},
    "required": ["name", "week", "exercises"],
    "additionalProperties": False,
}
_PROGRAM = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "weeks": {"type": "integer"}, "routines": {"type": "array", "items": _ROUTINE}},
    "required": ["name", "weeks", "routines"],
    "additionalProperties": False,
}
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {"message": {"type": "string"}, "ready": {"type": "boolean"}, "program": _PROGRAM},
    "required": ["message", "ready", "program"],
    "additionalProperties": False,
}


def _build_prompt(messages, exercise_names, active_program, objective):
    transcript = "\n".join(f"{item['role'].upper()}: {item['content']}" for item in messages)
    library = ", ".join(exercise_names) or "(empty)"
    current = ", ".join(active_program) or "(none)"
    return f"""You are LiftLog's program builder. Help a single lifter design a safe, practical training program through a concise conversation. Ask for missing essentials such as schedule, goal, experience, equipment, constraints, and injuries before proposing a program. Do not prescribe medical treatment.

When ready, return a complete program. It will replace a program with the same name, so describe that consequence in your message. Prefer names from the existing exercise library exactly where suitable; only create a new exercise when needed.

Existing exercise library: {library}
Current active program routines: {current}
Saved program objective: {objective or '(not set)'}

The program must use one or more named routines. Each exercise requires name, movement_pattern, muscle_group, sets, rep_min, and rep_max. Use the enum values enforced by the supplied response schema. Use realistic rest_seconds, increment_kg, equipment, cue, youtube_query, exercise_type, display_unit, and is_primary where relevant. When not ready, return ready=false and an empty routines list.

Conversation:
{transcript}"""


def generate_turn(messages, exercise_names, active_program, objective):
    try:
        response = Anthropic().messages.create(
            model=ai.MODEL,
            max_tokens=4096,
            output_config={"format": {"type": "json_schema", "schema": _RESPONSE_SCHEMA}},
            messages=[{"role": "user", "content": _build_prompt(messages, exercise_names, active_program, objective)}],
        )
    except Exception as error:
        raise ai.AICallError(str(error))
    text = next((block.text for block in response.content if block.type == "text"), None)
    if not text:
        raise ai.AIValidationError("empty response")
    try:
        result = json.loads(text)
        message = result["message"].strip()
        ready = result["ready"]
        program = result["program"]
    except (AttributeError, KeyError, TypeError, ValueError):
        raise ai.AIValidationError("response was not the expected JSON shape")
    if not message or not isinstance(ready, bool) or not isinstance(program, dict):
        raise ai.AIValidationError("response has invalid fields")
    if ready:
        errors = importer.validate({"version": 2, "program": program})
        if errors:
            raise ai.AIValidationError("program failed validation: " + "; ".join(errors))
    return {"message": message, "ready": ready, "program": program if ready else None}
