FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY requirements.txt ./
RUN uv pip install --system -r requirements.txt

COPY backend/ backend/
COPY alembic.ini .
COPY .env* ./

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
