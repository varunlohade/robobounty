# The hosted backend: the site server and the board server behind Caddy. Pages live on Vercel. Simulation stays on the Mac.
# Deploy with deploy/railway.sh, which uploads a clean copy of committed files only. Never run `railway up` from the repo root.
FROM node:22-slim AS world
WORKDIR /w
RUN npm install --omit=dev --no-audit --no-fund @worldcoin/idkit-core@4.6.0

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libegl1 procps util-linux libstdc++6 && rm -rf /var/lib/apt/lists/*
# cast sends and reads Arc transactions. Node signs World ID requests.
RUN python -c "import urllib.request as u; u.urlretrieve('https://github.com/foundry-rs/foundry/releases/download/v1.9.0/foundry_v1.9.0_linux_amd64.tar.gz', '/tmp/f.tgz')" && tar -xzf /tmp/f.tgz -C /usr/local/bin cast && rm /tmp/f.tgz && cast --version
COPY --from=node:22-slim /usr/local/bin/node /usr/local/bin/node
WORKDIR /app
COPY deploy/requirements.txt deploy/requirements.txt
RUN python -m venv policy/.venv && policy/.venv/bin/pip install --no-cache-dir -r deploy/requirements.txt
COPY --from=caddy:2.10-alpine /usr/bin/caddy /usr/local/bin/caddy
COPY package.json deploy/Caddyfile deploy/start.sh deploy/arc.json ./deploy-files/
COPY --from=world /w/node_modules node_modules
COPY policy/ policy/
COPY docs/evidence/ docs/evidence/
COPY contracts/src/ contracts/src/
RUN cp deploy-files/package.json package.json && useradd -m -u 1000 app && chown -R app /app
ENV PYTHONDONTWRITEBYTECODE=1
CMD ["bash", "/app/deploy-files/start.sh"]
