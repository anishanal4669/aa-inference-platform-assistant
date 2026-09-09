FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY app ./app

EXPOSE 8080
# One worker keeps the in-process limiter and ledger coherent. Scale out only
# after moving both to Redis/Postgres.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
