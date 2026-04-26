FROM python:3.11-slim

# 1. Install System Dependencies
RUN apt-get update && apt-get install -y \
    wget \
    xvfb \
    libglib2.0-0 \
    libnss3 \
    libnspr4 \
    libatk1.0-0 \
    libatk-bridge2.0-0 \
    libcups2 \
    libdrm2 \
    libdbus-1-3 \
    libxkbcommon0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxrandr2 \
    libgbm1 \
    libasound2 \
    && rm -rf /var/lib/apt/lists/*

# 2. Setup App
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install firefox

COPY src/ ./src/

# 3. Environment Variables
ENV DISPLAY=:99
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
ENV PORT=8000

# 4. Run Xvfb + App
CMD ["sh", "-c", "Xvfb :99 -screen 0 1920x1080x24 & python -m src.main"]
