#!/bin/bash
# Script de déploiement Railway sans GitHub
# Lance ce script depuis le Shell de Replit

echo "========================================="
echo "  VFS Italy Monitor — Deploy on Railway"
echo "========================================="
echo ""

# Check if railway CLI is installed
if ! command -v railway &> /dev/null; then
    echo "Installation de Railway CLI..."
    npm install -g @railway/cli
fi

echo "Connexion à Railway..."
echo "(Suis les instructions : ouvre le lien dans ton navigateur)"
railway login

echo ""
echo "Linking to your Railway project..."
railway link

echo ""
echo "Setting environment variables on Railway..."
railway variables set TELEGRAM_BOT_TOKEN="$TELEGRAM_BOT_TOKEN"
railway variables set VFS_EMAIL="$VFS_EMAIL"
railway variables set VFS_PASSWORD="$VFS_PASSWORD"
railway variables set CHECK_INTERVAL="120"
railway variables set DB_PATH="/app/data/vfs_bot.db"
railway variables set PYTHONUNBUFFERED="1"

echo ""
echo "Deploying to Railway..."
railway up --detach

echo ""
echo "✅ Deployment initiated!"
echo "Check your Railway dashboard for deployment status."
