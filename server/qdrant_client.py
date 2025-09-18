# server/qdrant_client.py
import os
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams

COLLECTION = os.getenv("COLLECTION_NAME", "docs")

# Use embedded Qdrant; data stored locally under ./qdrant_data
client = QdrantClient(path="qdrant_data")

def ensure_collection(vector_size: int):
    """
    Idempotently ensure the collection exists with the given vector size.
    """
    try:
        client.get_collection(COLLECTION)
        return
    except Exception:
        pass

    client.recreate_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
    )
