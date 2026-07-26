FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    SIMULATION_MODE=true \
    ALLOW_PRODUCTION_WRITE=false

WORKDIR /app

RUN useradd --create-home --uid 10001 energymesh

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install .

RUN mkdir -p /app/var /app/runs && chown -R energymesh:energymesh /app
USER energymesh

EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"

CMD ["uvicorn", "energymesh.api:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]
