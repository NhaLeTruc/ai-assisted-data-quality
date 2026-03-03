#!/bin/bash
set -e

echo "==> Stopping all containers..."
docker compose down

echo "==> Clearing data directories..."
rm -rf ./data/chroma/* ./data/sqlite/*

echo "==> Starting services..."
docker compose up -d

echo "==> Waiting 30 seconds for services to become healthy..."
sleep 30

echo "==> Seeding demo data..."
docker compose exec app python scripts/seed_demo_data.py

echo "==> Reset complete."
