# server/app.py
import os, asyncio
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Use Proactor loop on Windows so Playwright's subprocess works
if os.name == "nt":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    except Exception as e:
        print("[eventloop] Could not set Proactor policy:", e)

# Load env
load_dotenv()

# --- FastAPI app ---
app = FastAPI()

# --- CORS (open for local dev; tighten later) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Absolute paths anchored at project root ---
BASE_DIR = Path(__file__).resolve().parents[1]
STATIC_DIR = BASE_DIR / "static"
IMAGES_DIR = STATIC_DIR / "images"
TEMPLATE_DIR = BASE_DIR / "templates"

IMAGES_DIR.mkdir(parents=True, exist_ok=True)

# --- Static & templates ---
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

# --- Routes (include exactly once) ---
from .routes import router as server_router
app.include_router(server_router)

# --- Add this section for Cloud Run compatibility ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))  # Default to 8080 if PORT not set
    uvicorn.run(app, host="0.0.0.0", port=port)  # Must bind to 0.0.0.0