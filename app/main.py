import copy
import logging
from pathlib import Path
from typing import Annotated

from fastapi import Body, FastAPI, Form, HTTPException, Query, Request
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

STATUS_ORDER = ["open", "in_progress", "resolved", "closed"]

app = FastAPI(title="TriageBot")
ASSIGNEES_ERROR = "Responsables no válidos: máximo 5, de 1 a 50 caracteres cada uno."
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

    return db.create_ticket(
        payload.title, payload.description, classification, payload.assignees
    )


@app.post("/tickets", status_code=201, response_model=Ticket)
def create_ticket(payload: TicketCreate) -> dict:
    """Crea un ticket, lo clasifica y lo guarda. Si la IA falla, usa el fallback."""
    return _classify_and_save(payload)


@app.get("/tickets", response_model=list[Ticket])
def list_tickets(
    category: Category | None = None,
    priority: Priority | None = None,
    status: Status | None = None,
    assignee: Annotated[str | None, Query(min_length=1)] = None,
    overdue: bool | None = None,
) -> list[dict]:
    """Lista tickets filtrando por categoría, prioridad, estado, responsable y vencidos (AND)."""
    return db.list_tickets(
        category=category, priority=priority, status=status, assignee=assignee, overdue=overdue
    )


@app.patch("/tickets/{ticket_id}", response_model=Ticket)
def update_ticket(ticket_id: int, payload: Annotated[dict, Body()]) -> dict:
    """Actualiza status, priority y/o assignees. El 404 se comprueba antes que el 422."""
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


def _clean_filters(
    category: str, priority: str, status: str, assignee: str = "", overdue: str = ""
) -> dict[str, str | bool | None]:
    """Convierte los filtros del formulario ('' = Todas) y descarta valores fuera del enum."""
    allowed = {
        "category": (category, ALLOWED_CATEGORIES),
        "priority": (priority, ALLOWED_PRIORITIES),
        "status": (status, ALLOWED_STATUSES),
    }
    filters = {
        name: (value if value in valid else None) for name, (value, valid) in allowed.items()
    }
    filters["assignee"] = assignee.strip() or None
    filters["overdue"] = True if overdue == "1" else None  # «Solo vencidos»
    return filters


def _parse_assignees(text: str) -> list[str]:
    """'Ana, Luis,, ' -> ['Ana', 'Luis']. La validación (máx. 5, 1-50) la hace el modelo."""
    return [name.strip() for name in text.split(",") if name.strip()]


def _render_table(
    request: Request,
    filters: dict[str, str | bool | None],
    error: str | None = None,
) -> HTMLResponse:
    """Fragmento HTML de la tabla; los errores se muestran dentro del fragmento."""
    return templates.TemplateResponse(
        request,
        "_tickets_table.html",
        {"tickets": db.list_tickets(**filters), "error": error, "statuses": STATUS_ORDER},
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
            "statuses": STATUS_ORDER,
        },
    )


@app.get("/ui/tickets", response_class=HTMLResponse)
def ui_list_tickets(
    request: Request,
    category: str = "",
    priority: str = "",
    status: str = "",
    assignee: str = "",
    overdue: str = "",
) -> HTMLResponse:
    """Tabla filtrada para HTMX."""
    return _render_table(request, _clean_filters(category, priority, status, assignee, overdue))


@app.post("/ui/tickets", response_class=HTMLResponse)
def ui_create_ticket(
    request: Request,
    title: Annotated[str, Form()] = "",
    description: Annotated[str, Form()] = "",
    assignees: Annotated[str, Form()] = "",
    category: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "",
    assignee: Annotated[str, Form()] = "",
    overdue: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Crea un ticket desde el formulario y devuelve la tabla (con el mensaje si hay error)."""
    filters = _clean_filters(category, priority, status, assignee, overdue)
    try:
        payload = TicketCreate(
            title=title, description=description, assignees=_parse_assignees(assignees)
        )
    except ValidationError as exc:
        if any("assignees" in error["loc"] for error in exc.errors()):
            error = ASSIGNEES_ERROR
        else:
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
    new_assignees: Annotated[str | None, Form()] = None,
    category: Annotated[str, Form()] = "",
    priority: Annotated[str, Form()] = "",
    status: Annotated[str, Form()] = "",
    assignee: Annotated[str, Form()] = "",
    overdue: Annotated[str, Form()] = "",
) -> HTMLResponse:
    """Actualiza estado, prioridad y/o responsables desde la fila de la tabla."""
    filters = _clean_filters(category, priority, status, assignee, overdue)
    changes: dict = {"status": new_status or None, "priority": new_priority or None}
    changes = {k: v for k, v in changes.items() if v}
    if new_assignees is not None:  # campo enviado (aunque vacío = quitar a todos)
        changes["assignees"] = _parse_assignees(new_assignees)
    try:
        update = TicketUpdate.model_validate(changes)
    except ValidationError as exc:
        if any("assignees" in error["loc"] for error in exc.errors()):
            return _render_table(request, filters, ASSIGNEES_ERROR)
        return _render_table(request, filters, "Valor no válido para estado o prioridad.")
    if db.update_ticket(ticket_id, update.model_dump(exclude_none=True)) is None:
        return _render_table(request, filters, f"El ticket {ticket_id} no existe.")
    return _render_table(request, filters)
