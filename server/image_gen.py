# server/image_gen.py
import os, base64, hashlib
from pathlib import Path
from typing import Dict, List

IMAGE_PROVIDER = (os.getenv("IMAGE_PROVIDER") or "openai").strip().lower()
IMAGE_STYLE = os.getenv("IMAGE_STYLE", "instructional diagram, flat UI, neutral background, clear labels, no clutter")
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1024")
LOG_IMAGE_PROMPTS = (os.getenv("LOG_IMAGE_PROMPTS") or "").lower() in ("1","true","yes")

# ABSOLUTE path anchored at project root
BASE_DIR = Path(__file__).resolve().parents[1]
OUT_DIR = BASE_DIR / "static" / "images"
OUT_DIR.mkdir(parents=True, exist_ok=True)


# ----------------- Configuration -----------------

IMAGE_PROVIDER = (os.getenv("IMAGE_PROVIDER") or "openai").strip().lower()
IMAGE_STYLE = os.getenv(
    "IMAGE_STYLE",
    "instructional diagram, flat UI, neutral background, clear labels, no clutter",
)
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1024")  # for OpenAI
LOG_IMAGE_PROMPTS = (os.getenv("LOG_IMAGE_PROMPTS") or "").lower() in ("1", "true", "yes")

OUT_DIR = os.path.join("static", "images")
os.makedirs(OUT_DIR, exist_ok=True)

# ----------------- Helpers -----------------


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


# ----------------- Providers -----------------


def _generate_image_openai(prompt: str, size: str = "1024x1024") -> bytes:
    """
    Generate a PNG using OpenAI Images API (gpt-image-1).
    Requires: OPENAI_API_KEY in environment.
    pip install openai>=1.0
    """
    from openai import OpenAI  # lazy import so module loads even if package missing
    client = OpenAI()

    if LOG_IMAGE_PROMPTS:
        print("[image_gen] openai ->", prompt[:180], "…")

    resp = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size=size,
        # Transparent backgrounds are not universally supported; keep opaque for consistency.
    )
    b64 = resp.data[0].b64_json
    return base64.b64decode(b64)


def _generate_image_stability(prompt: str, aspect_ratio: str = "1:1") -> bytes:
    """
    Generate a PNG using Stability v2beta 'core' endpoint.
    Requires: STABILITY_API_KEY in environment.
    pip install requests
    """
    import requests

    api_key = os.getenv("STABILITY_API_KEY")
    if not api_key:
        raise RuntimeError("Missing STABILITY_API_KEY")

    if LOG_IMAGE_PROMPTS:
        print("[image_gen] stability ->", prompt[:180], "…")

    url = "https://api.stability.ai/v2beta/stable-image/generate/core"
    headers = {
        "Authorization": f"Bearer {api_key}",
        # Accept PNG bytes directly
        "Accept": "image/png",
    }
    # Stability expects multipart/form-data; simplest is to send an empty 'files' part
    files = {"none": ("", "")}
    data = {
        "prompt": prompt,
        "mode": "text-to-image",
        "output_format": "png",
        "aspect_ratio": aspect_ratio,
    }
    r = requests.post(url, headers=headers, files=files, data=data, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"Stability API error: {r.status_code} {r.text[:300]}")
    return r.content  # PNG bytes


def _generate_image(prompt: str, size: str = "1024x1024") -> bytes:
    if IMAGE_PROVIDER == "stability":
        # Stability uses aspect ratios instead of WxH strings
        ar = "1:1"
        return _generate_image_stability(prompt, aspect_ratio=ar)
    # Default: OpenAI
    return _generate_image_openai(prompt, size=size)


# ----------------- Public API -----------------


def attach_step_images(data: Dict) -> Dict:
    """
    Mutates and returns the input dict by attaching `image_url` (relative) to each step.

    Expected input shape (minimal):
      {
        "title": "...",
        "steps": [
          {"title": "Open Control Panel", "action": "Tap Settings gear on home screen"},
          ...
        ]
      }

    On success, each step gains:
      step["image_url"] = "/static/images/<hash>.png"

    On failure, step may include:
      step["image_error"] = "ErrorType: message"
    """
    steps: List[Dict] = list(data.get("steps") or [])
    out_steps: List[Dict] = []

    for s in steps:
        title = (s.get("title") or "").strip()
        action = (s.get("action") or "").strip()

        # Keep step as-is if it has no content
        if not title and not action:
            out_steps.append(s)
            continue

        # Content-hash for caching
        key = _slug(title + "|" + action + "|" + IMAGE_STYLE + "|" + IMAGE_PROVIDER)
        fname = f"{key}.png"
        fpath = os.path.join(OUT_DIR, fname)

        # Generate if missing
        if not os.path.exists(fpath):
            prompt = _prompt_from_step(title, action, IMAGE_STYLE)
            try:
                img_bytes = _generate_image(prompt, size=IMAGE_SIZE)
                # Write atomically to reduce race conditions
                tmp_path = fpath + ".tmp"
                with open(tmp_path, "wb") as f:
                    f.write(img_bytes)
                os.replace(tmp_path, fpath)
            except Exception as e:
                s["image_error"] = f"{type(e).__name__}: {e}"

        # Attach relative URL regardless (so frontend can show cached or placeholder)
        s["image_url"] = f"/static/images/{fname}"
        out_steps.append(s)

    data["steps"] = out_steps
    return data
