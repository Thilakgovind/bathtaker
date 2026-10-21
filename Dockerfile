FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy repository files (includes pre-built frontend/dist)
COPY . .

ENV PORT=8000
EXPOSE 8000

# Start the simulator in the background and the laptop backend on $PORT
CMD ["sh", "-c", "python contract/board_sim.py & python -m backend --port socket://localhost:5555 --host 0.0.0.0 --http ${PORT:-8000}"]
