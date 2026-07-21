"""
Robust JSON extraction from LLM responses.

Same battle-tested approach used in the AI Receptionist Platform project:
strips markdown code-fence wrapping, tolerates unescaped control characters
inside string values (a common LLM quirk), and — if the model writes prose
followed by a repeated JSON block — finds every balanced {...} span and
uses the last valid one, rather than naively grabbing from the first '{'
to the last '}' (which can jumble prose and JSON together).
"""

import json


def _find_json_objects(text: str) -> list[dict]:
    results = []
    i, n = 0, len(text)
    while i < n:
        if text[i] == "{":
            depth = 0
            in_string = False
            escape = False
            j = i
            while j < n:
                ch = text[j]
                if in_string:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                else:
                    if ch == '"':
                        in_string = True
                    elif ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = text[i : j + 1]
                            try:
                                results.append(json.loads(candidate, strict=False))
                            except json.JSONDecodeError:
                                pass
                            break
                j += 1
            i = j + 1
        else:
            i += 1
    return results


def extract_json(raw_text: str) -> dict:
    text = raw_text.strip()

    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        text = text.removeprefix("json").strip()

    try:
        return json.loads(text, strict=False)
    except json.JSONDecodeError:
        objects = _find_json_objects(text)
        if objects:
            return objects[-1]
        raise
