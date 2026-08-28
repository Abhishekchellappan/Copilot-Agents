# Jira Data Center MCP Server (Kubernetes Deployment)

This directory contains the complete code and Kubernetes manifest for running a centralized **Jira Data Center MCP Server** for GitHub Copilot in VS Code.

---

## 🛠️ Build & Deployment Instructions

### Step 1: Build Docker Image on Local Laptop
Run the following commands on your laptop (or CI pipeline):

```bash
cd jira-mcp-server

# Build Docker image
docker build -t your-registry/jira-mcp-server:1.0 .

# Push to your company's Docker/Container Registry
docker push your-registry/jira-mcp-server:1.0
```

---

### Step 2: Deploy to Kubernetes Cluster

1. Edit `jira-mcp-k8s.yaml` and update line 18 with your container image registry tag:
   ```yaml
   image: your-registry/jira-mcp-server:1.0
   ```
2. Apply the manifest to your Kubernetes cluster:
   ```bash
   kubectl apply -f jira-mcp-k8s.yaml
   ```
3. Verify the pod and service are running on NodePort `30005`:
   ```bash
   kubectl get pods -l app=jira-mcp
   kubectl get svc jira-mcp-service
   ```

---

### Step 3: Developer VS Code Configuration

Every team member can now connect their VS Code / GitHub Copilot to your Kubernetes MCP server:

1. In VS Code, press `Ctrl + Shift + P` -> Select **`Preferences: Open Remote Settings (JSON)`** (or `.vscode/mcp.json` in project root).
2. Add the following JSON snippet:

```json
{
  "mcpServers": {
    "jira-data-center": {
      "url": "http://10.221.31.25:30005/sse",
      "headers": {
        "X-Jira-PAT": "<YOUR_PERSONAL_ACCESS_TOKEN_HERE>"
      }
    }
  }
}
```

Replace `<YOUR_PERSONAL_ACCESS_TOKEN_HERE>` with your personal Jira Data Center PAT (generated from `http://jira.lge.com` -> Profile -> Personal Access Tokens).

---

### 🧪 Test with GitHub Copilot Chat

Open Copilot Chat in VS Code and try these prompts:

- **Fetch Issue**: `"Copilot, fetch details for Jira issue PROJ-101"`
- **Search Issues**: `"Search Jira for all open tasks in project PROJ"`
- **Create Issue**: `"Create a Jira task in project PROJ with summary 'Add unit test for authentication'"`
- **Add Comment**: `"Add a comment to Jira ticket PROJ-101 saying 'Working on the fix now'"`
