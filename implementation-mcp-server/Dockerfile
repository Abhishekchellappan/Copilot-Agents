FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl build-essential && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -c "from mcp.server.fastmcp import FastMCP; print('FastMCP import OK')"
COPY config.py .
COPY rag_engine.py .
COPY ast_parser.py .
COPY bitbake_parser.py .
COPY server.py .
COPY templates/ ./templates/
RUN mkdir -p /app/vector_store /app/workspace
EXPOSE 8000
CMD ["python", "server.py"]
