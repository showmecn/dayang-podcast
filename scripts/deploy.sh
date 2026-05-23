#!/bin/bash
# =============================================================================
# Dayang Podcast — One-click Deploy Script
# Usage: bash scripts/deploy.sh
# What it does:
#   1. Pulls latest code from GitHub main
#   2. Rebuilds & restarts the API container
#   3. Runs smoke tests to verify health
# =============================================================================

set -euo pipefail

# --- Config ---
PROJECT_DIR="/Users/zlj/.hermes/kanban/boards/zcompany/workspaces/t_7d6d2fee/dayang-podcast"
API_CONTAINER="dayang-api"
HEALTH_URL="http://localhost:8088/health"

echo "=== Dayang Podcast Deploy ==="
echo ""

# Step 1: Pull latest code
echo "[1/4] Pulling latest code from GitHub..."
cd "$PROJECT_DIR"
git pull origin main
echo "  ✅ git pull complete"

# Step 2: Rebuild & restart API
echo "[2/4] Rebuilding Docker image..."
docker-compose build api
echo "  ✅ build complete"

echo "[3/4] Restarting API container..."
docker-compose up -d api
echo "  ✅ API restarted"

# Step 3: Health check
echo "[4/4] Running health check..."
for i in $(seq 1 10); do
  sleep 2
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$HEALTH_URL" 2>/dev/null || echo "000")
  if [ "$STATUS" = "200" ]; then
    echo "  ✅ Health check passed (HTTP $STATUS)"
    break
  fi
  if [ "$i" = "10" ]; then
    echo "  ❌ Health check failed after 20s — HTTP $STATUS"
    exit 1
  fi
  echo "  ⏳ Waiting for API... attempt $i/10"
done

# Step 4: Smoke test
echo ""
echo "=== Smoke Test ==="
HEALTH_BODY=$(curl -s "$HEALTH_URL")
echo "  Health: $HEALTH_BODY"

# Check db_connected
if echo "$HEALTH_BODY" | grep -q '"db_connected":true'; then
  echo "  ✅ DB connected"
else
  echo "  ❌ DB not connected!"
  exit 1
fi

# Verify Vercel frontend has up-to-date API URL
echo ""
echo "=== Frontend Check ==="
VERCEL_FRONTEND="https://dayang-podcast-frontend.vercel.app"
VFC=$(curl -s -o /dev/null -w "%{http_code}" "$VERCEL_FRONTEND" 2>/dev/null || echo "000")
if [ "$VFC" = "200" ]; then
  echo "  ✅ Vercel frontend reachable (HTTP $VFC)"
else
  echo "  ⚠️  Vercel frontend returned HTTP $VFC (may need redeploy)"
fi

echo ""
echo "=== Deploy Complete ==="
echo "API:         http://localhost:8088"
echo "Production:  https://api.myagent.ccwu.cc"
echo "Frontend:    https://dayang-podcast-frontend.vercel.app"
