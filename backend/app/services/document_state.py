ALLOWED_TRANSITIONS = {
    "uploaded": ["processing"],
    "processing": ["processed", "failed"],
    "processed": [],
    "failed": [],
}


def can_transition(current_status: str, new_status: str) -> bool:
    return new_status in ALLOWED_TRANSITIONS.get(current_status, [])
