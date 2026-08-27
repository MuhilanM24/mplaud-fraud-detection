FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend
COPY frontend ./frontend
COPY VALIDATION_REPORT.md* ./

# Optional: pre-bake the sentence-transformers model for the stronger NLP
# backend. Build with `docker build --build-arg BAKE_SBERT=1` when network
# access is available; otherwise the app uses the labelled offline fallback.
ARG BAKE_SBERT=0
RUN if [ "$BAKE_SBERT" = "1" ]; then \
        cd /app/backend && MPLAUD_NLP_BACKEND=sbert python -c "\
from app.duplicates import NLPBackend; NLPBackend('sbert')" || true; \
    fi

ENV MPLAUD_DATA_DIR=/app/data
RUN mkdir -p /app/data && \
    cd /app/backend && python -c "from app.data_generator import generate; generate()"

EXPOSE 8000
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
