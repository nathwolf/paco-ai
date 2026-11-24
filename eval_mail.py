"""Live semantic evaluation using synthetic conversations and the configured model."""
import json

import discovery
from mail_reasoning import infer

CASES = [
    ("Indirect dependency", ["The client can sign as soon as you send the revised budget."], "add"),
    ("Delegated elsewhere", ["Juan will send the revised budget. Copying you for visibility."], None),
    ("French request", ["Nathalia, tu pourrais valider le devis avant vendredi ?"], "add"),
    ("Spanish request", ["Nathalia, nos falta tu firma para poder presentar el proyecto."], "add"),
    ("Completed before import", ["Could you send the signed copy?", "Attached is the signed copy."], None),
    ("Quoted and cancelled", ["Please review the proposal tomorrow.",
                              "Please disregard my earlier request. The proposal was withdrawn."], None),
]


def main():
    settings = json.loads(discovery.CONFIG.read_text())["model"]
    failures = []
    for case, texts, expected in CASES:
        messages = [dict(id=str(i), sent=case.startswith("Completed") and i == 1,
                         text=text, to="Nathalia" if i == 0 else "team")
                    for i, text in enumerate(texts)]
        actions = infer(settings, dict(owner="Nathalia", messages=messages, existing=[]))["actions"]
        valid = ([a["kind"] for a in actions] == ([expected] if expected else []) and
                 all(any(m["id"] == a["message"] and a["quote"] and a["quote"] in m["text"]
                         for m in messages) for a in actions))
        print(case, "PASS" if valid else "FAIL")
        if not valid:
            failures.append(case)
    return bool(failures)


if __name__ == "__main__":
    raise SystemExit(main())
