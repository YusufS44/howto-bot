# server/ingest.py
import os, glob, uuid, math
from typing import List
from dotenv import load_dotenv

from qdrant_client.models import PointStruct
from sentence_transformers import SentenceTransformer

from .qdrant_client import client, ensure_collection, COLLECTION

load_dotenv()

EMBED_MODEL_NAME = os.getenv("EMBED_MODEL_NAME", "all-MiniLM-L6-v2")

# --------- util: load docs ----------
def read_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()

def read_docx(path: str) -> str:
    try:
        import docx  # python-docx
    except ImportError:
        raise RuntimeError("Install python-docx: pip install python-docx")
    doc = docx.Document(path)
    return "\n".join(p.text for p in doc.paragraphs)

def load_document(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".txt":
        return read_txt(path)
    if ext == ".docx":
        return read_docx(path)
    # You can add .pdf later; for now, skip with a clear message
    raise RuntimeError(f"Unsupported file type for now: {ext} ({path})")

# --------- util: simple chunker ----------
def chunk_text(text: str, max_chars: int = 1000) -> List[str]:
    # split on blank lines; then re-pack to ~1000 chars
    paras = [p.strip() for p in text.splitlines()]
    blocks, buf = [], []
    size = 0
    for line in paras:
        if not line:
            line = "\n"
        if size + len(line) + 1 > max_chars and buf:
            blocks.append(" ".join(buf).strip())
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        blocks.append(" ".join(buf).strip())
    # drop empties
    return [b for b in blocks if b and not b.isspace()]

def main():
    docs_dir = os.path.join(os.getcwd(), "docs")
    if not os.path.isdir(docs_dir):
        raise RuntimeError(f"Docs folder not found: {docs_dir}")

    files = glob.glob(os.path.join(docs_dir, "*.txt")) + glob.glob(os.path.join(docs_dir, "*.docx"))
    if not files:
        raise RuntimeError(f"No .txt or .docx files in {docs_dir}")

    print(f"Loading embed model: {EMBED_MODEL_NAME}")
    model = SentenceTransformer(EMBED_MODEL_NAME)
    dim = model.get_sentence_embedding_dimension()
    print(f"Embed dim: {dim}")

    # Ensure collection matches this dimension
    ensure_collection(vector_size=dim)

    total_points = 0
    for path in files:
        try:
            full = load_document(path)
        except Exception as e:
            print(f"SKIP {path}: {type(e).__name__}: {e}")
            continue

        chunks = chunk_text(full, max_chars=1000)
        if not chunks:
            print(f"SKIP (no text) {path}")
            continue

        vecs = model.encode(chunks, normalize_embeddings=True).tolist()
        points = []
        for chunk, vec in zip(chunks, vecs):
            points.append(
                PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vec,
                    payload={"source": os.path.basename(path), "chunk": chunk},
                )
            )

        client.upsert(collection_name=COLLECTION, points=points)
        total_points += len(points)
        print(f"{os.path.basename(path)} → {len(points)} chunks")

    print(f"Done. Upserted {total_points} vectors into collection '{COLLECTION}'.")

if __name__ == "__main__":
    main()
