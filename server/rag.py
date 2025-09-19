# server/rag.py
import os
import re
import json
from typing import List, Dict, Any
from dotenv import load_dotenv

load_dotenv()

# -------------------------
# Embeddings (OpenAI, lightweight)
# -------------------------
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")

def _embed_single(text: str) -> list[float]:
    from openai import OpenAI
    client = OpenAI()
    resp = client.embeddings.create(model=OPENAI_EMBED_MODEL, input=[text])
    return resp.data[0].embedding


# -------------------------
# Retrieval from Qdrant (optional)
# -------------------------
def retrieve(question: str, k: int = 8, source_contains: str | None = None) -> List[Dict[str, str]]:
    """
    Try Qdrant (if available). If not installed/configured, return [] and we will
    fall back to question-only generation (handled later).
    """
    try:
        # Lazy imports so Cloud Run starts even if qdrant-client isn't installed
        from qdrant_client.models import Filter, FieldCondition, MatchText
        from .qdrant_client import client, COLLECTION

        qv = _embed_single(question)

        qfilter = None
        if source_contains:
            qfilter = Filter(must=[FieldCondition(key="source", match=MatchText(text=source_contains))])

        hits = client.search(
            collection_name=COLLECTION,
            query_vector=qv,
            limit=k,
            query_filter=qfilter
        )

        out: List[Dict[str, str]] = []
        for h in hits:
            payload = getattr(h, "payload", {}) or {}
            out.append({
                "text": payload.get("chunk", ""),
                "source": payload.get("source", "")
            })
        print(f"[rag] Retrieved {len(out)} chunks; sources -> {debug_sources(out)}")
        return out
    except Exception as e:
        print("[rag] retrieve disabled (no qdrant or not configured):", type(e).__name__, e)
        return []

def debug_sources(context: List[Dict[str, str]]) -> List[str]:
    return list({c.get("source", "") for c in context if c.get("source")})


# -------------------------
# Prompting + LLM (OpenAI)
# -------------------------
def _build_prompt(question: str, context: List[Dict[str, str]]) -> str:
    if not context:
        # Question-only mode (no RAG). Use general knowledge to write the guide.
        return f"""You are a careful technical writer. Write a step-action how-to guide as JSON with this schema:

{{
  "title": <string>,
  "description": <string>,
  "steps": [{{"number": <int>, "title": <string>, "action": <string>, "why": <string>, "check": <string>, "illustration_caption": <string>}}],
  "pro_tip": <string>,
  "troubleshooting": [{{"issue": <string>, "fix": <string>}}],
  "safety": [<string>]
}}

Rules:
- Use general knowledge and best practices to answer.
- Keep each step concise and atomic.
- Keep tone neutral and instructional.

Question: {question}

Respond with ONLY JSON (no commentary).
"""
    # Context-provided (RAG) prompt
    joined = "\n\n".join(f"[{i+1}] {c['text']}" for i, c in enumerate(context))
    return f"""You are a careful technical writer. Using ONLY the information below, write a step-action how-to guide as JSON with this schema:

{{
  "title": <string>,
  "description": <string>,
  "steps": [{{"number": <int>, "title": <string>, "action": <string>, "why": <string>, "check": <string>, "illustration_caption": <string>}}],
  "pro_tip": <string>,
  "troubleshooting": [{{"issue": <string>, "fix": <string>}}],
  "safety": [<string>]
}}

Rules:
- If the context does not contain enough information to answer, set "steps": [] and include only "abstain": true.
- Keep each step concise and atomic.
- Keep tone neutral and instructional.

Question: {question}

Context:
{joined}

Respond with ONLY JSON (no commentary).
"""

def _extract_json(text: str) -> Dict[str, Any]:
    if not text:
        raise ValueError("Empty LLM response")
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()
    brace = re.search(r"\{[\s\S]*\}", text)
    if brace:
        text = brace.group(0)
    return json.loads(text)

def _call_llm_for_json(question: str, context: List[Dict[str, str]]) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    prompt = _build_prompt(question, context)

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        resp = client.responses.create(
            model=model,
            input=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        return _extract_json(resp.output_text)
    except Exception:
        # Legacy fallback
        try:
            import openai
            openai.api_key = api_key
            chat = openai.ChatCompletion.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            return _extract_json(chat["choices"][0]["message"]["content"])
        except Exception as e2:
            raise RuntimeError(f"LLM call failed: {type(e2).__name__}: {e2}") from e2


# -------------------------
# Public: generate_json
# -------------------------
def generate_json(question: str, source_contains: str | None = None) -> Dict[str, Any]:
    """
    Returns a dict shaped for the Jinja template. Never raises.
    """
    # Step 1: try to retrieve context (optional)
    try:
        context = retrieve(question, k=8, source_contains=source_contains)
    except Exception as e:
        print("[rag] retrieve error:", type(e).__name__, e)
        context = []

    # Step 2: call LLM once (with context if present, else question-only)
    try:
        data = _call_llm_for_json(question, context if context else [])
    except Exception as e:
        print("[rag] LLM path failed:", type(e).__name__, e)
        # Minimal scaffold so page still renders
        pretty = question
        for p in ("How do I", "How to"):
            if pretty.startswith(p):
                pretty = pretty[len(p):].strip()
        title = f"How to {pretty.capitalize()}" if pretty else "How-To Guide"
        data = {
            "title": title,
            "description": "This guide was generated without full context (fallback mode).",
            "steps": [{
                "number": 1,
                "title": "Start with the basics",
                "action": "Break the task into small, verifiable steps.",
                "why": "Smaller steps reduce errors and make progress visible.",
                "check": "You can confirm each step independently.",
                "illustration_caption": "Show the first action on screen."
            }],
            "pro_tip": "Add more details as you iterate.",
            "troubleshooting": [],
            "safety": [],
            "abstain": False,
        }

    # Step 3: ensure required keys exist (defensive)
    data.setdefault("title", "")
    data.setdefault("description", "")
    data.setdefault("steps", [])
    data.setdefault("pro_tip", "")
    data.setdefault("troubleshooting", [])
    data.setdefault("safety", [])
    return data


# -------------------------
# Image helpers
# -------------------------
from .image_gen import attach_step_images

def maybe_attach_images(data: dict) -> dict:
    try:
        return attach_step_images(data)
    except Exception as e:
        print("[maybe_attach_images] ERROR:", type(e).__name__, e)
        return data
