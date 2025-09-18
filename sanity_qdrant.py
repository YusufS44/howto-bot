# sanity_qdrant.py
from server.qdrant_client import client, COLLECTION
from qdrant_client.http.models import ScrollRequest

print("Collection:", COLLECTION)

try:
    # Grab a few records to prove data exists
    recs, _ = client.scroll(collection_name=COLLECTION, limit=5)
    print("Sample records returned:", len(recs))
except Exception as e:
    print("Scroll error:", e)

# Count chunks from the specific PDF
target = "Success Case Study Planning Guide"
count = 0
try:
    # Scroll through up to 5000 points in batches of 1000
    next_page = None
    while True:
        recs, next_page = client.scroll(
            collection_name=COLLECTION,
            limit=1000,
            offset=next_page
        )
        for r in recs:
            src = (r.payload or {}).get("source", "")
            if target in src:
                count += 1
        if not next_page:
            break
    print(f"Chunks from '{target}':", count)
except Exception as e:
    print("Count error:", e)
