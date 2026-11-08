FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend

COPY backend/requirements.lock ./requirements.lock
RUN python -m pip install --no-cache-dir --requirement requirements.lock

RUN addgroup --system alfa-signal \
    && adduser --system --ingroup alfa-signal --home /home/alfa-signal alfa-signal \
    && mkdir -p /app/backend/var \
    && chown -R alfa-signal:alfa-signal /app/backend /home/alfa-signal

COPY --chown=alfa-signal:alfa-signal backend/ ./
COPY --chown=alfa-signal:alfa-signal data/synthetic/ /app/data/synthetic/

USER alfa-signal

EXPOSE 8000

ENTRYPOINT ["sh", "docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
