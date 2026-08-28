"""Quick diagnostic script"""
import os
import sys

print(f"Python: {sys.executable}")
print(f"Python Version: {sys.version}")
print(f"JIRA_PAT: {'SET' if os.environ.get('JIRA_PAT') else 'NOT SET'}")
print(f"JIRA_BASE_URL: {os.environ.get('JIRA_BASE_URL', 'NOT SET')}")

try:
    import requests
    print(f"Requests version: {requests.__version__}")
except ImportError as e:
    print(f"ERROR importing requests: {e}")

print("\nNow running actual test...")

# Set variables
os.environ['JIRA_PAT'] = 'MDk1MjQwMTEwOTY1OjR1ayNCFcFCKT0jA3owY9XCuapU'
os.environ['JIRA_BASE_URL'] = 'http://jira.lge.com/issue'

print(f"JIRA_PAT: {'SET' if os.environ.get('JIRA_PAT') else 'NOT SET'}")
print(f"JIRA_BASE_URL: {os.environ.get('JIRA_BASE_URL')}")

# Try a simple test
import requests
headers = {
    "Authorization": f"Bearer {os.environ['JIRA_PAT']}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

print("\nTesting API connection...")
try:
    response = requests.get(
        f"{os.environ['JIRA_BASE_URL']}/rest/api/2/search",
        headers=headers,
        timeout=15
    )
    print(f"Response Status: {response.status_code}")
    print(f"Response: {response.text[:200]}")
except Exception as e:
    print(f"ERROR: {e}")
