# Deploy from the service directory (builds locally, reads sibling .env):
docker compose up -d --build

# Verify health (no audible test):
curl -s http://localhost:8095/health
