from server.qdrant_client import client, COLLECTION

target = "Success Case Study Planning Guide"
count = 0

recs, nextp = client.scroll(collection_name=COLLECTION, limit=1000)
while recs:
    for r in recs:
        if target in (r.payload or {}).get("source", ""):
            count += 1
    if not nextp:
        break
    recs, nextp = client.scroll(collection_name=COLLECTION, limit=1000, offset=nextp)

print(f"Chunks from '{target}':", count)
