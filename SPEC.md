# SPEC.md — Contrato funcional de TriageBot

> **Equipo A (Vibe):** usad este SPEC tal cual. No lo modifiquéis.
>
> **Equipo B (Spec-Driven):** este SPEC está incompleto a propósito. Vuestra tarea es completarlo
> antes de pedir código: casos límite, errores, funcionalidades de cada pantalla, tests propios y
> todo lo que traslade el cliente en `BRIEF.md`.

## 1. Objetivo

Construir una aplicación web interna para registrar, clasificar y consultar tickets de soporte.

## 2. Modelo de datos

### Ticket

Campos mínimos:

| Campo | Tipo | Reglas |
|---|---|---|
| `id` | int | Autogenerado |
| `title` | str | Obligatorio, 1–200 caracteres tras trim |
| `description` | str | Obligatorio, 1–5000 caracteres tras trim |
| `category` | str | `bug`, `feature_request`, `question`, `urgent` |
| `priority` | str | `P1`, `P2`, `P3` |
| `tags` | list[str] | Lista, puede estar vacía |
| `status` | str | `open`, `in_progress`, `resolved`, `closed` |
| `created_at` | datetime | UTC, generado en servidor |
| `updated_at` | datetime | UTC, actualizado en cambios relevantes |
| `status_changed_at` | datetime | UTC, «en este estado desde»: se fija al crear y cambia solo cuando cambia `status` |
| `due_at` | datetime | UTC, calculado (no se guarda): fin del día de `created_at` + plazo de la prioridad |
| `overdue` | bool | Calculado: `true` si el ticket está `open`/`in_progress` y ya pasó `due_at` |

Valores por defecto:

- `status`: `open`
- fallback de clasificación: `category="question"`, `priority="P3"`, `tags=[]`

Los valores de `category`, `priority` y `status` son vinculantes: exactamente esos, en minúsculas
(salvo `P1`–`P3`). Si el código devuelve `"URGENT"`, los tests fallan.

## 3. Arquitectura de módulos

Estructura recomendada:

```text
app/
  __init__.py
  main.py          # FastAPI app y endpoints HTTP
  models.py        # Modelos Pydantic (Ticket, TicketCreate, TicketUpdate)
  db.py            # Conexión y operaciones SQLite (sqlite3)
  classifier.py    # ÚNICO módulo que llama al LLM

templates/
  index.html
  _tickets_table.html

tests/
  test_acceptance.py
```

Regla importante:

> Todo lo que llame a una API de IA (OpenRouter u otra) vive solo en `app/classifier.py`.
> Si hay llamadas al SDK en `main.py`, algo se ha torcido. Y `classifier.py` no importa nada de FastAPI.

El stack cerrado no está aquí: está en `BRIEF.md`, sección «Restricciones técnicas».

## 4. API HTTP

| Endpoint | Devuelve | Errores |
|---|---|---|
| `GET /health` | `200 {"status": "ok"}` | — |
| `POST /tickets` | `201` con el ticket ya clasificado | `422` si título o descripción vacíos o demasiado largos |
| `GET /tickets` | `200` lista, filtrable por `category`, `priority` y `status` | — |
| `PATCH /tickets/{ticket_id}` | `200` ticket actualizado | `404` si no existe · `422` si el valor no está en el enum |
| `GET /` | `200` HTML con el tablero (ver §6) | — |

### `POST /tickets`

Crea un ticket y lo clasifica. La clasificación ocurre de forma síncrona durante la petición: la
respuesta ya trae `category`, `priority` y `tags`.

Request JSON:

```json
{
  "title": "La app no carga",
  "description": "Desde esta mañana aparece una pantalla en blanco al iniciar sesión"
}
```

Response `201`:

```json
{
  "id": 1,
  "title": "La app no carga",
  "description": "Desde esta mañana aparece una pantalla en blanco al iniciar sesión",
  "category": "bug",
  "priority": "P1",
  "tags": ["login", "blank-screen"],
  "status": "open",
  "created_at": "2026-06-29T09:30:00Z",
  "updated_at": "2026-06-29T09:30:00Z"
}
```

Errores:

- `422` si `title` está vacío (o solo espacios) o supera 200 caracteres.
- `422` si `description` está vacía (o solo espacios) o supera 5000 caracteres.

### `GET /tickets`

Lista tickets en JSON. Query params opcionales: `category`, `priority`, `status`.

```text
GET /tickets?category=bug&priority=P1&status=open
```

Devuelve `200` con una lista de tickets con la misma forma que la respuesta de `POST /tickets`.

### `PATCH /tickets/{ticket_id}`

Solo se pueden cambiar `status` y `priority`. El resto de campos son inmutables tras la creación.

```json
{
  "status": "in_progress",
  "priority": "P2"
}
```

- `status`: `open`, `in_progress`, `resolved`, `closed`
- `priority`: `P1`, `P2`, `P3`

Errores:

- `404` si no existe el ticket.
- `422` si el valor no pertenece al enum permitido.

`GET /` devuelve HTML; `GET /tickets` devuelve JSON. No los confundáis: los tests y el agente del
Día 3 usan el JSON.

## 5. Clasificador IA

Función esperada:

```python
def classify_ticket(title: str, description: str) -> dict:
    ...
```

Contrato de salida:

```python
{
    "category": "bug" | "feature_request" | "question" | "urgent",
    "priority": "P1" | "P2" | "P3",
    "tags": list[str],
}
```

Llamada al LLM: SDK de `openai` apuntando a OpenRouter (`base_url="https://openrouter.ai/api/v1"`),
modelo `openai/gpt-oss-120b`, API key desde la variable de entorno `OPENROUTER_API_KEY`.

Requisitos no negociables:

- **Valida la salida.** Si el LLM devuelve `"category": "URGENT"` (mayúsculas) o una categoría
  inventada, aplica el fallback. No propagues basura.
- **Como mucho un reintento** si la llamada falla. Si vuelve a fallar, fallback.
- **Nunca propaga excepciones del SDK.** Ante cualquier problema devuelve el fallback:

```python
{"category": "question", "priority": "P3", "tags": []}
```

El SPEC no fija el prompt: lo decidís vosotros. Sí es obligatorio que la salida cumpla el contrato.

## 6. Frontend mínimo

`GET /` devuelve una página HTML con:

1. Formulario para crear ticket.
2. Tablero de tickets.
3. Filtros por categoría, prioridad y estado.

Recomendación:

- Usar Jinja2 templates.
- Usar HTMX para refrescar la tabla sin recargar toda la página.
- No escribir HTML grande como string dentro de `main.py`.

## 7. Tests obligatorios

El archivo `tests/test_acceptance.py` contiene los 5 tests de aceptación. No se modifica.

Los tests comprueban:

1. Crear un ticket válido devuelve `201` y clasificación.
2. El ticket creado queda persistido y aparece en `GET /tickets`.
3. Input inválido devuelve `422`.
4. Si el clasificador falla, se aplica fallback y la app no cae.
5. Se puede actualizar estado/prioridad y filtrar tickets.

## 8. No negociable

- No commitear `.env`.
- No hardcodear API keys.
- No propagar excepciones del SDK de la IA al endpoint.
- No modificar los tests de aceptación para hacerlos pasar.
- No introducir React ni frontend complejo.

## 9. Decisiones de diseño del Equipo B

### 9.1 Modelo de datos

- **`title` y `description`:** se validan y se guardan **ya recortados** (trim). La longitud (1–200 y 1–5000) se mide después del trim. El contenido se guarda tal cual (emojis, saltos de línea y HTML incluidos) y se **escapa al renderizar** (autoescape de Jinja).
- **`tags`:**
  - Máximo **5** etiquetas, de 1 a 30 caracteres cada una.
  - En minúsculas, sin espacios laterales, formato `kebab-case`, sin duplicados y conservando el orden.
  - Si el LLM devuelve más de 5, se descartan las sobrantes. Las etiquetas vacías o que no sean texto se descartan.
- **Fechas:** ISO 8601 en UTC con sufijo `Z` y precisión de segundos (`2026-06-29T09:30:00Z`).
- **`updated_at`:** cambia solo cuando un `PATCH` modifica de verdad `status` o `priority`. Un `PATCH` que repite los valores actuales no lo toca.
- **SQLite:**
  - Tabla `tickets` con `id INTEGER PRIMARY KEY AUTOINCREMENT`.
  - `tags` se guarda como texto JSON.
  - Restricciones `CHECK` para `category`, `priority` y `status`.
  - `created_at` y `updated_at` se guardan como texto ISO 8601.
- **`DATABASE_URL`:** formato `sqlite:///ruta/al/fichero.db`. Valor por defecto: `sqlite:///./triagebot.db`. Se **lee en cada conexión**, no al importar el módulo, y la tabla se crea si no existe (`CREATE TABLE IF NOT EXISTS`).

### 9.2 API HTTP

**Formato de error.** Se usa el formato por defecto de FastAPI:

- `404` → `{"detail": "Ticket not found"}`
- `422` → `{"detail": [ ... ]}` (lista de errores de validación de Pydantic)

**`GET /tickets`**

- Orden: `created_at` descendente y, a igualdad, `id` descendente.
- Sin paginación en esta versión.
- Los filtros se combinan con **AND**.
- Un valor de filtro fuera del enum devuelve `422` (no una lista vacía).

**`GET /tickets/{ticket_id}`** (nuevo)

- `200` con el ticket.
- `404` si no existe.
- `422` si el id no es un entero.

**`PATCH /tickets/{ticket_id}`**

- Admite `status`, `priority` o ambos. **Debe venir al menos uno**: `{}` devuelve `422`.
- Cualquier otro campo (`title`, `category`, etc.) devuelve `422`, porque son inmutables.
- Se puede reabrir un ticket `resolved` o `closed` (→ `open`). Cualquier transición entre estados es válida.
- Orden de comprobación: `404` (el ticket no existe) antes que `422`.

**Endpoints HTML para HTMX** (separados de la API JSON bajo el prefijo `/ui`, para que los endpoints JSON sigan devolviendo siempre JSON):

| Endpoint | Devuelve |
|---|---|
| `GET /` | Página completa |
| `GET /ui/tickets` | Fragmento `_tickets_table.html`, acepta `category`, `priority` y `status` |
| `POST /ui/tickets` | Crea el ticket (formulario `application/x-www-form-urlencoded`) y devuelve el fragmento de la tabla |
| `POST /ui/tickets/{ticket_id}` | Actualiza `status` y/o `priority` desde la tabla y devuelve el fragmento de la tabla |

Los endpoints `/ui` responden siempre `200` con un fragmento HTML. Los errores de validación se muestran como mensaje dentro del fragmento.

**Requisitos de implementación** (por cómo están escritos los tests):

1. `main.py` llama a `classifier.classify_ticket(...)` **a través del módulo** (`from app import classifier`). Con `from app.classifier import classify_ticket` el parche de los tests no funcionaría.
2. `main.py` envuelve esa llamada en `try/except Exception` y aplica el fallback si lanza. No basta con que el clasificador lo haga por dentro.
3. `db.py` obtiene `DATABASE_URL` en cada conexión.

### 9.3 Clasificador IA

- **Salida del modelo:** se pide JSON estricto (`response_format={"type": "json_object"}`). Si la respuesta viene envuelta en un bloque de código (```` ``` ````), se retira la envoltura una vez antes de parsear.
- **Validación:**
  - `category` y `priority` deben coincidir **exactamente** con el enum, sin corregir mayúsculas. `"URGENT"` o una categoría inventada → fallback completo.
  - `tags` debe ser una lista; si no lo es → fallback completo. Los elementos se normalizan según §9.1.
- **Intentos:** como máximo 2 llamadas en total (1 inicial + 1 reintento), con timeout de 15 segundos cada una.
  - Se reintenta ante excepción del SDK, timeout o respuesta que no es JSON.
  - **No** se reintenta si el JSON es válido pero los valores no lo son: va directo al fallback.
- **Sin `OPENROUTER_API_KEY`:** se devuelve el fallback sin llamar a la red y se registra un aviso.
- **Fallback:** siempre una **copia nueva** de `{"category": "question", "priority": "P3", "tags": []}`, nunca el diccionario compartido.
- **Prompt:**
  - El contenido del ticket se envía delimitado y se indica al modelo que es **datos, no instrucciones**.
  - Criterios: `urgent` si bloquea la operación o hay una fecha límite con impacto; `bug` para fallos de lo existente; `feature_request` para algo nuevo; `question` para dudas de uso.
  - `P1`: impacto crítico inmediato. `P2`: importante pero no bloqueante. `P3`: bajo impacto.
  - Etiquetas en inglés, `kebab-case`, de 0 a 5.
- **Logging:** ante cualquier fallo se registra con `logging` el tipo de excepción y el motivo. No se registran la clave ni el contenido del ticket.
- **Aislamiento:** `classifier.py` no importa nada de FastAPI y es el único módulo que usa el SDK de `openai`.

### 9.4 Frontend

Idioma de la interfaz: **español**. Estilos con Tailwind CDN y HTMX por CDN con versión fijada.

**Pantalla única `GET /`**, con tres bloques:

1. **Formulario de creación**
   - Campo `title` (`maxlength=200`, obligatorio).
   - Campo `description` (`maxlength=5000`, obligatorio).
   - Botón «Crear ticket».
2. **Filtros:** tres selectores (categoría, prioridad, estado), cada uno con la opción «Todas». Al cambiar uno se refresca la tabla sin recargar la página.
3. **Tabla de tickets**
   - Columnas: ID, Título, Categoría, Prioridad, Estado, Etiquetas, Creado.
   - Prioridad y estado son selectores editables en la propia fila; al cambiarlos se guarda al instante.
   - Orden: el más reciente primero.


### 9.5 Cambio de Marta A: varios responsables por ticket

Marta pide que un ticket pueda tener **varios responsables** y poder **filtrar el tablero por responsable**.

**Modelo**

- Nuevo campo `assignees: list[str]` en el ticket. Por defecto `[]` (sin asignar).
- Los responsables son **nombres libres** (no hay login ni tabla de usuarios: está fuera de alcance del BRIEF).
- Cada nombre: se recorta (trim), de 1 a 50 caracteres. Un nombre vacío o de solo espacios → `422`.
- Sin duplicados: se comparan sin distinguir mayúsculas/minúsculas (`casefold`) y se conserva la primera aparición y el orden.
- Máximo **5** responsables por ticket (tras eliminar duplicados). Más de 5 → `422`.
- SQLite: columna `assignees TEXT NOT NULL DEFAULT '[]'` con JSON, igual que `tags`. Si la base de datos ya existía sin esa columna, se añade al abrir la conexión (`ALTER TABLE ... ADD COLUMN`), sin perder datos.

**API**

- `POST /tickets` acepta `assignees` **opcional**.
- `PATCH /tickets/{id}` acepta `assignees` además de `status` y `priority`. La lista enviada **reemplaza** a la actual; `[]` quita a todos. Debe venir al menos uno de los tres campos; `{}` sigue siendo `422`.
- `updated_at` cambia solo si la lista cambia de verdad (tras normalizar). Repetir la misma lista no lo toca. Cambiar solo las mayúsculas de un nombre (`Ana` → `ana`) cuenta como cambio, porque cambia el nombre que se muestra.
- `GET /tickets?assignee=<nombre>` devuelve los tickets en los que ese nombre figura entre los responsables. Coincidencia exacta, sin distinguir mayúsculas/minúsculas. Se combina con `AND` con el resto de filtros. `assignee` vacío → `422`. Un nombre que no existe devuelve `[]`.

**Interfaz** (se implementa cuando exista el tablero, §9.4)

- Nueva columna «Responsables» en la tabla.
- Nuevo filtro «Responsable» junto a los otros tres, con la opción «Todos».

### 9.5 Plazos (petición de Marta)

- **Fecha límite** (`due_at`): fin del día (UTC, `23:59:59Z`) de la fecha de creación más el plazo de la prioridad: `P1` el mismo día, `P2` el día siguiente, `P3` a los dos días.
- Se **calcula** al leer a partir de `created_at` y `priority`; no se guarda. Si cambia la prioridad, cambia la fecha límite.
- **Vencido** (`overdue`): el ticket está `open` o `in_progress` y la hora actual supera `due_at`. Un ticket `resolved` o `closed` nunca está vencido; si se reabre pasada su fecha, vuelve a estarlo.
- `GET /tickets?overdue=true` devuelve solo los vencidos y `overdue=false` solo los demás. Un valor que no sea booleano devuelve `422`. Se combina con el resto de filtros mediante **AND**.
- Tablero: columna «Vence» con la fecha, etiqueta «Vencido» y fila resaltada; filtro «Plazo» con la opción «Solo vencidos» (`/ui/tickets?overdue=1`).
- Limitación conocida: «hoy» se calcula en UTC, no en hora de Madrid.
