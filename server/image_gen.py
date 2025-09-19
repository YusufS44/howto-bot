# server/image_gen.py
import os, base64, hashlib
from pathlib import Path
from typing import Dict, List

# ---------- Config ----------
IMAGE_PROVIDER = (os.getenv("IMAGE_PROVIDER") or "openai").strip().lower()  # "openai" or "stability"
IMAGE_STYLE = os.getenv("IMAGE_STYLE", "instructional diagram, flat UI, neutral background, clear labels, no clutter")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1024")  # OpenAI uses WxH
LOG_IMAGE_PROMPTS = (os.getenv("LOG_IMAGE_PROMPTS") or "").lower() in ("1", "true", "yes")

# Absolute output dir inside the container
BASE_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BASE_DIR / "static" / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------- Helpers ----------
def _slug(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]

def _prompt_from_step(title: str, action: str, style: str) -> str:
    title = (title or "").strip()
    action = (action or "").strip()
    core = title if title else action
    detail = f" Action: {action}" if (action and title) else ""
    return (
        f"{style}. Show: {core}.{detail} "
        "Perspective: simple, straight-on. Background: white/neutral. "
        "Purpose: job-aid step illustration for technicians. "
        "Use minimal, readable labels if helpful. Avoid decorative elements."
    )

# ---------- Providers ----------
def _generate_image_openai(prompt: str, size: str = "1024x1024") -> bytes:
    from openai import OpenAI
    if LOG_IMAGE_PROMPTS:
        print("[image_gen] openai ->", prompt[:180], "…")
    client = OpenAI()
    resp = client.images.generate(model="gpt-image-1", prompt=prompt, size=size)
    return base64.b64decode(resp.data[0].b64_json)

def _generate_image_stability(prompt: str, aspect_ratio: str = "1:1") -> bytes:
    import requests
    api_key = os.getenv("STABILITY_API_KEY")
    if not api_key:
        raise RuntimeError("Missing STABILITY_API_KEY")
    if LOG_IMAGE_PROMPTS:
        print("[image_gen] stability ->", prompt[:180], "…")
    url = "https://api.stability.ai/v2beta/stable-image/generate/core"
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "image/png"}
    files = {"none": ("", "")}  # multipart needs a files part
    data = {"prompt": prompt, "mode": "text-to-image", "output_format": "png", "aspect_ratio": aspect_ratio}
    r = requests.post(url, headers=headers, files=files, data=data, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"Stability API error: {r.status_code} {r.text[:300]}")
    return r.content

def _generate_image(prompt: str, size: str = "1024x1024") -> bytes:
    if IMAGE_PROVIDER == "stability":
        return _generate_image_stability(prompt, aspect_ratio="1:1")
    return _generate_image_openai(prompt, size=size)

# ---------- Public ----------
def attach_step_images(data: Dict) -> Dict:
    steps: List[Dict] = list(data.get("steps") or [])
    out_steps: List[Dict] = []

    for s in steps:
        title = (s.get("title") or "").strip()
        action = (s.get("action") or "").strip()
        if not title and not action:
            out_steps.append(s); continue

        key = _slug(title + "|" + action + "|" + IMAGE_STYLE + "|" + IMAGE_PROVIDER)
        fname = f"{key}.png"
        fpath = OUT_DIR / fname

        if not fpath.exists():
            prompt = _prompt_from_step(title, action, IMAGE_STYLE)
            try:
                img_bytes = _generate_image(prompt, size=IMAGE_SIZE)
                tmp = fpath.with_suffix(".png.tmp")
                with open(tmp, "wb") as f:
                    f.write(img_bytes)
                tmp.replace(fpath)
            except Exception as e:
                s["image_error"] = f"{type(e).__name__}: {e}"

        s["image_url"] = f"/static/images/{fname}"
        out_steps.append(s)

    data["steps"] = out_steps
    return data
