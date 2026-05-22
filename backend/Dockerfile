FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD python -c "from app.seed import seed_database; seed_database()" && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8007}
