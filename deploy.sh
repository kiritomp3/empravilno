#!/bin/bash
# Production deployment script
# Usage: bash deploy.sh

set -e

echo "🚀 Starting production deployment..."
cd /app

echo "📥 Fetching latest changes from origin..."
git fetch origin

echo "🔄 Checking out add-miniapp-button branch..."
git checkout add-miniapp-button
git pull origin add-miniapp-button

echo "📊 Current changes:"
git log --oneline -3

echo "📦 Building Docker image..."
docker-compose build --no-cache

echo "🛑 Stopping current services..."
docker-compose down

echo "🚀 Starting services..."
docker-compose up -d

echo "⏳ Waiting for services to be ready..."
sleep 8

echo "🏥 Health checks:"
echo "  API: " && curl -s http://localhost:8000/healthz && echo ""
echo "  Read: " && curl -s http://localhost:8000/readyz && echo ""

echo "📋 Recent logs:"
docker-compose logs --tail=20

echo "✨ Deployment completed successfully!"
echo "🎉 Changes are now live on production!"
