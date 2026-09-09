FROM python:3.12-slim@sha256:a39549e211a16149edf74e5fdc9ef03a6767e46cd987c5048b6659b6c9904c94

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system triage && adduser --system --ingroup triage triage
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

USER triage
EXPOSE 8080
CMD ["uvicorn", "agentictriage.api:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]
