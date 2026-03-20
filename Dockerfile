FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash openssh-client jq openssl git uuid-runtime \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1002 sigil && useradd -u 1002 -g 1002 -m sigil

WORKDIR /home/sigil/SigilGate/SigilGate_bot

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ ./bot/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER sigil
ENTRYPOINT ["/entrypoint.sh"]
