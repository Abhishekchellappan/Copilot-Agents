FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Verify FastMCP import works (fail fast during build, not at runtime)
RUN python -c "from mcp.server.fastmcp import FastMCP; print('FastMCP import OK')"

# Copy server code
COPY build_server.py .

# Expose SSE port
EXPOSE 8000

CMD ["python", "build_server.py"]
