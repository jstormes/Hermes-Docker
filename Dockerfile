FROM nousresearch/hermes-agent:latest

# System packages (apt)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Terminal multiplexer (needed for spawning agent sessions via tmux)
    tmux \
    # Media processing (video analysis, manim-video skill, songsee)
    ffmpeg \
    # TTS: espeak-ng is required by the NeuTTS backend
    espeak-ng \
    # Archive tools
    unzip zip p7zip-full \
    # JSON parsing utility
    jq \
    # Node.js for npx calls (Playwright browser install, etc.)
    nodejs npm \
    # Browser tool: Chromium binary + required system libraries
    chromium \
    libx11-xcb1 libxrandr2 libxcomposite1 libxcursor1 libxdamage1 \
    libxfixes3 libxi6 libxtst6 libxkbcommon0 libatk1.0-0 \
    libatk-bridge2.0-0 libcups2 libdbus-1-3 libdrm2 libgbm1 \
    libasound2 libpango-1.0-0 libcairo2 libatspi2.0-0 \
    libwayland-client0 libxshmfence1 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Python packages (uv) — optional toolsets detected at import time
RUN uv pip install --python /opt/hermes/.venv/bin/python3 --no-cache \
    ddgs                        \
    # faster-whisper              \
    # neutts                      \
    scipy

# Patch the dashboard's loopback-only WS client gate so the embedded chat
# (--tui) works behind Docker Desktop's bridge NAT. See patch-ws-loopback.py
# for the full rationale. Runs at build time; fails loudly if the upstream
# anchor changes so a base-image bump can't silently break the fix.
#
# SECURITY: this drops the loopback-peer requirement on the chat WebSockets in
# --insecure mode, so anyone who can reach the dashboard port gets a full agent
# session (shell + file access to the mounted repo). It is only safe because
# the port is published to host loopback (127.0.0.1) in the compose file. Do
# NOT expose the port to the LAN (0.0.0.0/9119:9119) with this patch + --insecure;
# use gated OAuth mode instead. See docker-compose.windows.yml.
COPY patch-ws-loopback.py /tmp/patch-ws-loopback.py
RUN /opt/hermes/.venv/bin/python3 /tmp/patch-ws-loopback.py \
    && rm -f /tmp/patch-ws-loopback.py
