FROM node:20-slim

# Install Python 3 and pip
RUN apt-get update && \
    apt-get install -y python3 python3-pip python3-venv curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN python3 -m pip install --no-cache-dir --break-system-packages -r requirements.txt

# Copy Python server files
COPY image_server.py generate_image.py ./
COPY logo-light.jpg logo-dark.jpg ./

# Copy built Node.js app
COPY dist/ ./dist/

# Copy startup script
COPY start.sh .
RUN chmod +x start.sh

# Railway sets PORT env var automatically
ENV NODE_ENV=production
ENV PYTHON_IMAGE_SERVER=http://127.0.0.1:5001

EXPOSE 3000

CMD ["./start.sh"]
