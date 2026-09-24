from typing import Literal

InviteStatus = Literal["sent", "opened", "started", "completed", "expired", "declined"]

_ALLOWED: dict[InviteStatus | None, frozenset[InviteStatus]] = {
    None: frozenset({"sent", "expired"}),
    "sent": frozenset({"opened", "started", "declined", "expired"}),
    "opened": frozenset({"started", "declined", "expired"}),
    "started": frozenset({"completed", "declined", "expired"}),
    "completed": frozenset(),
    "expired": frozenset(),
    "declined": frozenset(),
}


def transition(current: InviteStatus | None, target: InviteStatus) -> InviteStatus:
    if target not in _ALLOWED[current]:
        raise ValueError(f"cannot transition invite from {current} to {target}")
    return target
