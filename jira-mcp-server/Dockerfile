FROM python:3.11-slim

WORKDIR /app

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

# Copy and install python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy server code
COPY jira_server.py .

# Expose SSE port
EXPOSE 8000

# Set environment variables
ENV JIRA_BASE_URL="http://jira.lge.com"

CMD ["python", "jira_server.py"]
