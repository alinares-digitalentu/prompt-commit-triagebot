import copy
import logging

from fastapi import FastAPI

from app import classifier, db
from app.models import Ticket, TicketCreate

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


# TODO: implementar durante el bootcamp.
# Endpoints esperados por los tests:
# - GET /tickets
# - PATCH /tickets/{ticket_id}
# - GET /
