# TODO: define aquí los modelos de dominio / schemas Pydantic.

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

ALLOWED_CATEGORIES = {"bug", "feature_request", "question", "urgent"}
ALLOWED_PRIORITIES = {"P1", "P2", "P3"}
ALLOWED_STATUSES = {"open", "in_progress", "resolved", "closed"}

Category = Literal["bug", "feature_request", "question", "urgent"]
Priority = Literal["P1", "P2", "P3"]
Status = Literal["open", "in_progress", "resolved", "closed"]

MAX_ASSIGNEES = 5
MAX_ASSIGNEE_LENGTH = 50


def normalize_assignees(names: list[str]) -> list[str]:
    """Recorta, valida (1-50), quita duplicados sin distinguir mayúsculas y limita a 5."""
    result: list[str] = []
    seen: set[str] = set()
    for name in names:
        clean = name.strip()
        if not 1 <= len(clean) <= MAX_ASSIGNEE_LENGTH:
            raise ValueError(
                f"Cada responsable debe tener entre 1 y {MAX_ASSIGNEE_LENGTH} caracteres"
            )
        if clean.casefold() not in seen:
            seen.add(clean.casefold())
            result.append(clean)
    if len(result) > MAX_ASSIGNEES:
        raise ValueError(f"Un ticket admite como máximo {MAX_ASSIGNEES} responsables")
    return result


Assignees = Annotated[list[str], AfterValidator(normalize_assignees)]


class TicketCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)
    assignees: Assignees = Field(default_factory=list)


class TicketUpdate(BaseModel):
    """PATCH: solo status, priority y/o assignees; cualquier otro campo es inmutable (422)."""

    model_config = ConfigDict(extra="forbid")

    status: Status | None = None
    priority: Priority | None = None
    assignees: Assignees | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "TicketUpdate":
        if self.status is None and self.priority is None and self.assignees is None:
            raise ValueError("Debe indicarse al menos 'status', 'priority' o 'assignees'")
        return self


class Ticket(BaseModel):
    id: int
    title: str
    description: str
    category: Category
    priority: Priority
    tags: list[str]
    assignees: list[str]
    status: Status
    created_at: str
    updated_at: str
    status_changed_at: str
    due_at: str
    overdue: bool
