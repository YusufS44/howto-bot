import re

def split_paragraphs(text, max_chars=1200, overlap=150):
    parts, current = [], ""
    for para in re.split(r"\n\s*\n", text):
        if len(current) + len(para) + 1 <= max_chars:
            current = (current + "\n" + para).strip()
        else:
            if current: parts.append(current)
            tail = current[-overlap:] if current else ""
            current = (tail + "\n" + para).strip()
    if current: parts.append(current)
    return [p.strip() for p in parts if p.strip()]
