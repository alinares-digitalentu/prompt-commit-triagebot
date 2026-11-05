# TODO: define aquí los modelos de dominio / schemas Pydantic.

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ALLOWED_CATEGORIES = {"bug", "feature_request", "question", "urgent"}
ALLOWED_PRIORITIES = {"P1", "P2", "P3"}
ALLOWED_STATUSES = {"open", "in_progress", "closed"}

Category = Literal["bug", "feature_request", "question", "urgent"]
Priority = Literal["P1", "P2", "P3"]
Status = Literal["open", "in_progress", "closed"]


class TicketCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=5000)


class TicketUpdate(BaseModel):
    """PATCH: solo status y/o priority; cualquier otro campo es inmutable (422)."""

    model_config = ConfigDict(extra="forbid")

    status: Status | None = None
    priority: Priority | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> "TicketUpdate":
        if self.status is None and self.priority is None:
            raise ValueError("Debe indicarse al menos 'status' o 'priority'")
        return self


class Ticket(BaseModel):
    id: int
    title: str
    description: str
    category: Category
    priority: Priority
    tags: list[str]
    status: Status
    created_at: str
    updated_at: str
