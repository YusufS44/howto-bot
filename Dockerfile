FROM python:3.11-slim
WORKDIR /app
RUN python -m pip install --upgrade pip setuptools wheel
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=8080 PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
CMD ["sh","-c","python -m uvicorn server.app:app --host 0.0.0.0 --port ${PORT} --log-level debug"]
