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
def html_to_pdf(payload: dict, request: Request):
    """Accepts {html:'…'} and returns a PDF of that EXACT HTML (no extra CSS)."""
    from fastapi import HTTPException
    from fastapi.responses import StreamingResponse
    from io import BytesIO
    import re

    html = (payload or {}).get("html") or ""
    if not isinstance(html, str) or not html.strip():
        raise HTTPException(status_code=400, detail="Field 'html' is required.")

    # Make relative URLs (e.g., /static/images/...) resolve to your API host
    base_url = str(request.base_url).rstrip("/")
    if "<base" not in html.lower():
        html = html.replace("<head>", f'<head><base href="{base_url}/">', 1)

    # Render to PDF with Playwright (sync API; route is sync, so no asyncio conflict)
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.emulate_media(media="screen")  # match on-screen look
            page.set_viewport_size({"width": 1100, "height": 1400})
            page.set_content(html, wait_until="networkidle")
            pdf_bytes = page.pdf(
                format="Letter",
                print_background=True,
                margin={"top":"0.5in","bottom":"0.5in","left":"0.5in","right":"0.5in"},
                scale=1.0,
            )
            browser.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF engine error: {type(e).__name__}: {e}")

    # Use the <title> for both download name and PDF metadata
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    title = (m.group(1).strip() if m else "Guide") or "Guide"
    safe  = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "guide"

    # (Optional but nice) Set PDF metadata Title via pypdf
    try:
        from pypdf import PdfReader, PdfWriter
        _in = BytesIO(pdf_bytes)
        reader = PdfReader(_in)
        writer = PdfWriter()
        for pg in reader.pages:
            writer.add_page(pg)
        meta = reader.metadata or {}
        meta["/Title"] = title
        writer.add_metadata(meta)
        _out = BytesIO()
        writer.write(_out)
        _out.seek(0)
        pdf_stream = _out
    except Exception:
        pdf_stream = BytesIO(pdf_bytes)  # falls back if pypdf not installed

    return StreamingResponse(
        pdf_stream,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe}.pdf"'}
    )

