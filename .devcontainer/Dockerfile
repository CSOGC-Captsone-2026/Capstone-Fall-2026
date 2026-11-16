FROM ubuntu:24.04

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git gdb curl ca-certificates \
    python3 python3-pip python3-venv python3-dev \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Virtualenv owned by the built-in non-root "ubuntu" user (UID 1000)
RUN python3 -m venv /opt/venv && chown -R ubuntu:ubuntu /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

USER ubuntu
WORKDIR /workspace

# Dependencies are baked into the image; rebuilding picks up requirements.txt changes
COPY --chown=ubuntu:ubuntu requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt