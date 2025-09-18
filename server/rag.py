# server/rag.py
import os
import re
import json
import hashlib
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
# Retrieval from Qdrant
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

        # Use OpenAI embeddings instead of sentence_transformers
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

        out = []
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
    """Helper for logging which sources were used."""
    return list({c.get("source", "") for c in context if c.get("source")})


# -------------------------
# Prompting + LLM (OpenAI optional)
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
    # --- Original RAG prompt (context provided) ---
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
    """Tolerant JSON extraction: pulls first {...} block or ```json fenced code."""
    if not text:
        raise ValueError("Empty LLM response")

    # fenced code ```json ... ```
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    if fence:
        text = fence.group(1).strip()

    # first {...} block
    brace = re.search(r"\{[\s\S]*\}", text)
    if brace:
        text = brace.group(0)

    return json.loads(text)


def _call_llm_for_json(question: str, context: List[Dict[str, str]]) -> Dict[str, Any]:
    """
    Calls OpenAI (Responses API or Chat Completions) if OPENAI_API_KEY is present.
    Returns parsed dict. Raises on failure.
    """
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")

    # Prefer the newer responses API if available; fall back to chat/completions.
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    prompt = _build_prompt(question, context)

    try:
        # Try responses API (openai>=1.0)
        from openai import OpenAI  # type: ignore
        client = OpenAI(api_key=api_key)
        resp = client.responses.create(
            model=model,
            input=[{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        text = resp.output_text  # unified accessor
        return _extract_json(text)
    except Exception:
        # Fallback to legacy ChatCompletion interface
        try:
            import openai  # type: ignore
            openai.api_key = api_key
            chat = openai.ChatCompletion.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            text = chat["choices"][0]["message"]["content"]
            return _extract_json(text)
        except Exception as e2:
            raise RuntimeError(f"LLM call failed: {type(e2).__name__}: {e2}") from e2


# -------------------------
# Public: generate_json
# -------------------------
def generate_json(question: str, source_contains: str | None = None) -> Dict[str, Any]:
    """
    Main entry used by app.py. Returns a dict shaped for the Jinja template.
    Never raises on retrieval/LLM failure—returns an 'abstain' payload instead.
    """
    try:
        context = retrieve(question, k=8, source_contains=source_contains)
    except Exception as e:
        print("[rag] retrieve error:", type(e).__name__, e)
        context = []

   if not context:
    print("[rag] No context found; generating from question only.")
    try:
        data = _call_llm_for_json(question, [])
    except Exception as e:
        print("[rag] LLM (question-only) failed:", type(e).__name__, e)
        # Fallback scaffold so the page still renders
        data = {
            "title": f"How to {question.removeprefix('How do I').removeprefix('How to').strip().capitalize()}",
            "description": "This guide was generated without RAG (question-only).",
            "steps": [{
                "number": 1,
                "title": "Start with the basics",
                "action": "Break the task into small, verifiable steps.",
                "why": "Small steps reduce errors and make progress visible.",
                "check": "You can confirm each step independently.",
                "illustration_caption": "Show the first action on screen."
            }],
            "pro_tip": "Add more details as you iterate.",
            "troubleshooting": [],
            "safety": [],
            "abstain": False,
        }


    # Try LLM path
    try:
        data = _call_llm_for_json(question, context)
    except Exception as e:
        print("[rag] LLM path failed:", type(e).__name__, e)
        # Fallback: minimal single-step scaffold so the page still renders
        data = {
            "title": f"How to {question.removeprefix('How do I').removeprefix('How to').strip().capitalize()}",
            "description": "This guide was generated without LLM (fallback mode).",
            "steps": [
                {
                    "number": 1,
                    "title": "Review the provided document",
                    "action": "Open the relevant source document and locate the section that answers your question.",
                    "why": "To ensure instructions come only from your knowledge base.",
                    "check": "You can cite the section/heading from the document.",
                    "illustration_caption": "Open the document and highlight the relevant section."
                }
            ],
            "pro_tip": "Add more detailed documents to your library for richer steps.",
            "troubleshooting": [{"issue": "Empty or vague results", "fix": "Re-ingest with clearer .txt/.docx content."}],
            "safety": [],
            "abstain": False,
        }

    # Ensure required keys exist (defensive)
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

# server/rag.py
from .image_gen import attach_step_images

def maybe_attach_images(data: dict) -> dict:
    try:
        return attach_step_images(data)
    except Exception as e:
        print("[maybe_attach_images] ERROR:", type(e).__name__, e)
        return data
