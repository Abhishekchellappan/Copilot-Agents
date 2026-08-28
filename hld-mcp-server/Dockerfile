FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install lightweight CPU-only PyTorch first (reduces image from 4.2GB to ~450MB)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

# Copy and install remaining python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Verify FastMCP import works (fail fast during build)
RUN python -c "from mcp.server.fastmcp import FastMCP; print('FastMCP import OK')"

# Copy application code
COPY config.py .
COPY rag_engine.py .
COPY collab_sync.py .
COPY hld_server.py .
COPY templates/ ./templates/

# Create persistent vector store directory
RUN mkdir -p /app/vector_store

# Expose SSE port
EXPOSE 8000

CMD ["python", "hld_server.py"]
