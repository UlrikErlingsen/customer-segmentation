"""Domain errors with messages written for non-technical users."""


class DataProblem(ValueError):
    """A data or configuration problem that the user can correct."""


def out_of_memory_message(subject: str = "this analysis") -> str:
    return (
        f"There is not enough memory for {subject} on this computer. Close other programs, keep only the columns "
        "you need, or use a computer with more memory. Segment Signal itself sets no size limit."
    )


def friendly_message(exc: Exception) -> str:
    """Return a concise, actionable message without exposing internals."""
    if isinstance(exc, DataProblem):
        return str(exc)
    if isinstance(exc, MemoryError):
        return out_of_memory_message()
    return (
        "The analysis could not finish. Check that the selected columns contain usable values, "
        "then try again. Technical details are available below."
    )

