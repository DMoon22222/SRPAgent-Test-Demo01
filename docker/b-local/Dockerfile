FROM python:3.11-slim

# Build-time installation only; execution never installs dependencies or networks.
RUN python3 -m pip install --no-cache-dir pytest==8.3.5

WORKDIR /workspace
USER 65534:65534
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONNOUSERSITE=1
