"""Page-serving routes for Jinja2 templates (HTMX + Alpine.js views)."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["pages"])

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATE_DIR))


@router.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main dashboard page."""
    return templates.TemplateResponse("dashboard.html", {"request": request})


@router.get("/study-plan", response_class=HTMLResponse)
async def study_plan(request: Request) -> HTMLResponse:
    """Render the study plan page for today."""
    return templates.TemplateResponse("study_plan.html", {"request": request})


@router.get("/assessments/manage", response_class=HTMLResponse)
async def assessments_manage(request: Request) -> HTMLResponse:
    """Render the assessment management page."""
    return templates.TemplateResponse("assessments.html", {"request": request})


@router.get("/resources/manage", response_class=HTMLResponse)
async def resources_manage(request: Request) -> HTMLResponse:
    """Render the resource management page."""
    return templates.TemplateResponse("resources.html", {"request": request})


@router.get("/practice", response_class=HTMLResponse)
async def practice_session(request: Request) -> HTMLResponse:
    """Render the practice session page."""
    return templates.TemplateResponse("practice_session.html", {"request": request})


@router.get("/mastery", response_class=HTMLResponse)
async def mastery_dashboard(request: Request) -> HTMLResponse:
    """Render the mastery dashboard page."""
    return templates.TemplateResponse("mastery_dashboard.html", {"request": request})


@router.get("/class/{course_id}", response_class=HTMLResponse)
async def class_detail(request: Request, course_id: int) -> HTMLResponse:
    """Render the class detail page for a specific course."""
    return templates.TemplateResponse(
        "class_detail.html", {"request": request, "course_id": course_id}
    )
