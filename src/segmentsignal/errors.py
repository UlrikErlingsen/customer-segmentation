"""Domain errors with messages written for non-technical users."""


class DataProblem(ValueError):
    """A data or configuration problem that the user can correct."""


def friendly_message(exc: Exception) -> str:
    """Return a concise, actionable message without exposing internals."""
    if isinstance(exc, DataProblem):
        return str(exc)
    return (
        "The analysis could not finish. Check that the selected columns contain usable values, "
        "then try again. Technical details are available below."
    )

