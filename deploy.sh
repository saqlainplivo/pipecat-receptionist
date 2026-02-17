#!/bin/bash
#
# Project 3: Deploy to Railway
#
# Step-by-step deployment helper.
# Run from the Day6 directory.

set -e

echo "=========================================="
echo "  Railway Deployment Helper"
echo "=========================================="

# Step 1: Initialize Railway project
echo ""
echo "Step 1: Initialize Railway project"
echo "----------------------------------"
echo "  railway init"
echo "  railway link"
echo ""
read -p "Press Enter once you've initialized and linked the project..."

# Step 2: Set environment variables
echo ""
echo "Step 2: Set environment variables"
echo "----------------------------------"
echo "Run these commands (replace with your actual keys):"
echo ""
echo '  railway variables set OPENAI_API_KEY="sk-..."'
echo '  railway variables set DEEPGRAM_API_KEY="..."'
echo '  railway variables set ELEVENLABS_API_KEY="..."'
echo '  railway variables set PLIVO_AUTH_ID="..."'
echo '  railway variables set PLIVO_AUTH_TOKEN="..."'
echo '  railway variables set POSTGRES_URL="postgres://..."'
echo ""
read -p "Press Enter once you've set all environment variables..."

# Step 3: Deploy
echo ""
echo "Step 3: Deploy to Railway"
echo "----------------------------------"
echo "Running: railway up"
echo ""
railway up

# Step 4: Get public domain
echo ""
echo "Step 4: Get your public URL"
echo "----------------------------------"
echo "Running: railway domain"
echo ""
railway domain

echo ""
echo "=========================================="
echo "  Deployment Complete!"
echo "=========================================="
echo ""
echo "Next steps:"
echo "  1. Copy your Railway URL (e.g., https://your-app.up.railway.app)"
echo "  2. Test health: curl https://your-app.up.railway.app/health"
echo "  3. Check logs: railway logs"
echo "  4. Update Plivo: python update_plivo.py https://your-app.up.railway.app"
