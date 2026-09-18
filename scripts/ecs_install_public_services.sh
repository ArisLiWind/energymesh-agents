#!/usr/bin/env bash
set -euo pipefail

ROOT="${ENERGYMESH_ROOT:-/opt/energymesh-agents}"

cd "${ROOT}"
git fetch origin main
git checkout main
git reset --hard origin/main

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -U pip setuptools wheel
python -m pip install -e .
python -m pip install uvicorn fastapi pydantic starlette python-multipart scipy numpy

install -m 0644 deploy/systemd/energymesh-web.service /etc/systemd/system/energymesh-web.service
install -m 0644 deploy/systemd/energymesh-agentteams.service /etc/systemd/system/energymesh-agentteams.service
install -m 0644 deploy/nginx/energymesh-public.conf /etc/nginx/conf.d/energymesh-public.conf

if docker ps --format '{{.Names}}' | grep -q '^agentteams-controller$'; then
  docker exec agentteams-controller sh -lc '
    for path in /usr/share/nginx/html/config.json /app/config.json /var/www/html/config.json; do
      if [ -f "$path" ]; then
        cp "$path" "$path.bak.$(date +%s)"
        cat >"$path" <<'"'"'EOF'"'"'
{
  "default_server_config": {
    "m.homeserver": {
      "base_url": "https://matrix.gensphereai.xyz",
      "server_name": "gensphereai.xyz"
    }
  },
  "disable_custom_urls": false,
  "disable_guests": true,
  "brand": "AgentTeams Element"
}
EOF
      fi
    done
  ' || true
fi

systemctl daemon-reload
systemctl enable --now docker
systemctl enable --now energymesh-web.service
systemctl enable --now energymesh-agentteams.service
nginx -t
systemctl enable --now nginx
systemctl restart energymesh-web.service energymesh-agentteams.service nginx

echo "EnergyMesh public services installed."
systemctl is-active docker energymesh-web.service energymesh-agentteams.service nginx
