#!/bin/bash
set -e

echo "Starting darts180 Studio..."

# Start Python image server in background
echo "Starting Python image server on port 5001..."
cd /app
python image_server.py &
PYTHON_PID=$!

# Wait for Python server to be ready
echo "Waiting for Python server..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:5001/health > /dev/null 2>&1; then
        echo "Python server is ready."
        break
    fi
    if [ $i -eq 30 ]; then
        echo "ERROR: Python server failed to start within 30 seconds."
        exit 1
    fi
    sleep 1
done

# Start Node.js Express server (foreground)
echo "Starting Express server on port ${PORT:-3000}..."
exec node /app/dist/index.cjs
