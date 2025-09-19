# server/routes.py
from pathlib import Path
from io import BytesIO
import re

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates

from .rag import maybe_attach_images, generate_json

router = APIRouter()

BASE_DIR = Path(__file__).resolve().parents[1]
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

def _build_data(payload: dict | None):
    if payload and isinstance(payload, dict) and payload.get("steps"):
        return payload
    q = (payload or {}).get("question")
    src = (payload or {}).get("source")
    return generate_json(q or "placeholder", source_contains=src)

@router.get("/health")
def health():
    return {"ok": True}

@router.post("/howto/json")
def howto_json(payload: dict | None = None):
    data = _build_data(payload)
    data = maybe_attach_images(data)
    return JSONResponse(data)

@router.post("/howto/html")
def howto_html(request: Request, payload: dict | None = None):
    data = _build_data(payload)
    data = maybe_attach_images(data)
    return templates.TemplateResponse("guide.html", {"request": request, **data})

@router.post("/html-to-pdf")
async def html_to_pdf_stub(payload: dict):
    return JSONResponse({"error": "PDF temporarily disabled for deploy sanity check"}, status_code=503)