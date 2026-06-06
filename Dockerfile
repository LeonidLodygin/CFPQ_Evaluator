FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY . /opt/cfpq-evaluator
RUN python -m pip install --no-cache-dir /opt/cfpq-evaluator

WORKDIR /workspace
ENTRYPOINT ["cfpq-eval"]
