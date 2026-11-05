import copy
import logging
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, Form, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app import classifier, db
from app.models import (
    ALLOWED_CATEGORIES,
    ALLOWED_PRIORITIES,
    ALLOWED_STATUSES,
    Category,
    Priority,
    Status,
    Ticket,
    TicketCreate,
    TicketUpdate,
)

logger = logging.getLogger(__name__)

app = FastAPI(title="TriageBot")
templates = Jinja2Templates(directory=Path(__file__).resolve().parent.parent / "templates")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


def _classify_and_save(payload: TicketCreate) -> dict:
    """Clasifica (con fallback si la IA falla) y guarda el ticket."""
    try:
        classification = classifier.classify_ticket(payload.title, payload.description)
    except Exception as exc:
        logger.warning("Clasificador fallido (%s); se aplica el fallback", type(exc).__name__)
        classification = copy.deepcopy(classifier.FALLBACK_CLASSIFICATION)

    return db.create_ticket(payload.title, payload.description, classification)


@app.post("/tickets", status_code=201, response_model=Ticket)
def create_ticket(payload: TicketCreate) -> dict:
    """Crea un ticket, lo clasifica y lo guarda. Si la IA falla, usa el fallback."""
    return _classify_and_save(payload)


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


def _clean_filters(category: str, priority: str, status: str) -> dict[str, str | None]:
    """Convierte los filtros del formulario ('' = Todas) y descarta valores fuera del enum."""
    allowed = {
        "category": (category, ALLOWED_CATEGORIES),
        "priority": (priority, ALLOWED_PRIORITIES),
        "status": (status, ALLOWED_STATUSES),
    }
    return {name: (value if value in valid else None) for name, (value, valid) in allowed.items()}


def _render_table(
    request: Request,
    filters: dict[str, str | None],
    error: str | None = None,
) -> HTMLResponse:
    """Fragmento HTML de la tabla; los errores se muestran dentro del fragmento."""
    return templates.TemplateResponse(
        request,
        "_tickets_table.html",
        {"tickets": db.list_tickets(**filters), "error": error},
    )


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Página completa del tablero."""
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "tickets": db.list_tickets(),
            "error": None,
            "categories": sorted(ALLOWED_CATEGORIES),
            "priorities": sorted(ALLOWED_PRIORITIES),
            "statuses": ["open", "in_progress", "closed"],
        },
    )


@app.get("/ui/tickets", response_class=HTMLResponse)
def ui_list_tickets(
    request: Request, category: str = "", priority: str = "", status: str = ""
) -> HTMLResponse:
    """Tabla filtrada para HTMX."""
    return _render_table(request, _clean_filters(category, priority, status))


@app.post("/ui/tickets", response_class=HTMLResponse)
def ui_create_ticket(
    request: Request,
    title: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Crea un ticket desde el formulario y devuelve la tabla (con el mensaje si hay error)."""
    filters = _clean_filters(category, priority, status)
    try:
        payload = TicketCreate(title=title, description=description)
    except ValidationError:
        error = "El título (1-200) y la descripción (1-5000) son obligatorios."
        return _render_table(request, filters, error)
    _classify_and_save(payload)
    return _render_table(request, filters)


@app.post("/ui/tickets/{ticket_id}", response_class=HTMLResponse)
def ui_update_ticket(
    request: Request,
    ticket_id: int,
    new_status: Annotated[str, Form()] = "",
    new_priority: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Actualiza estado y/o prioridad desde la fila de la tabla."""
    filters = _clean_filters(category, priority, status)
    changes = {"status": new_status or None, "priority": new_priority or None}
    try:
        update = TicketUpdate.model_validate({k: v for k, v in changes.items() if v})
    except ValidationError:
        return _render_table(request, filters, "Valor no válido para estado o prioridad.")
    if db.update_ticket(ticket_id, update.model_dump(exclude_none=True)) is None:
        return _render_table(request, filters, f"El ticket {ticket_id} no existe.")
    return _render_table(request, filters)
