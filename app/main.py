import copy
import logging
from typing import Annotated

from fastapi import Body, FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError

from app import classifier, db
from app.models import Category, Priority, Status, Ticket, TicketCreate, TicketUpdate

logger = logging.getLogger(__name__)

app = FastAPI(title="TriageBot")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/tickets", status_code=201, response_model=Ticket)
def create_ticket(payload: TicketCreate) -> dict:
    """Crea un ticket, lo clasifica y lo guarda. Si la IA falla, usa el fallback."""
    try:
        classification = classifier.classify_ticket(payload.title, payload.description)
    except Exception as exc:
        logger.warning("Clasificador fallido (%s); se aplica el fallback", type(exc).__name__)
        classification = copy.deepcopy(classifier.FALLBACK_CLASSIFICATION)

    return db.create_ticket(payload.title, payload.description, classification)


@app.get("/tickets", response_model=list[Ticket])
def list_tickets(
    category: Category | None = None,
    priority: Priority | None = None,
    status: Status | None = None,
) -> list[dict]:
    """Lista tickets filtrando por categoría, prioridad y estado (AND)."""
    return db.list_tickets(category=category, priority=priority, status=status)


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
def update_ticket(ticket_id: int, payload: Annotated[dict, Body()]) -> dict:
    """Actualiza status y/o priority. El 404 se comprueba antes que el 422."""
    if db.get_ticket(ticket_id) is None:
        raise HTTPException(status_code=404, detail="Ticket not found")
    try:
        changes = TicketUpdate.model_validate(payload)
    except ValidationError as exc:
        raise RequestValidationError(exc.errors(include_url=False, include_context=False)) from exc
    ticket = db.update_ticket(ticket_id, changes.model_dump(exclude_none=True))
    if ticket is None:  # borrado entre la comprobación y la actualización
        raise HTTPException(status_code=404, detail="Ticket not found")
    return ticket


# TODO: GET / (tablero HTML) — pendiente.
