# The hosted backend: the site server and the board server behind Caddy. Pages live on Vercel. Simulation stays on the Mac.
# Deploy with deploy/railway.sh, which uploads a clean copy of committed files only. Never run `railway up` from the repo root.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libegl1 procps util-linux && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY deploy/requirements.txt deploy/requirements.txt
RUN python -m venv policy/.venv && policy/.venv/bin/pip install --no-cache-dir -r deploy/requirements.txt
COPY --from=caddy:2.10-alpine /usr/bin/caddy /usr/local/bin/caddy
COPY package.json deploy/Caddyfile deploy/start.sh ./deploy-files/
COPY policy/ policy/
COPY docs/evidence/ docs/evidence/
RUN cp deploy-files/package.json package.json && useradd -m -u 1000 app && chown -R app /app
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["bash", "/app/deploy-files/start.sh"]
