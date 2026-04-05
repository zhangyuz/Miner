ARG BASE_IMAGE=miner-base:latest

# --- Stage 1: grab Node.js + Gemini CLI from official node image ---
FROM --platform=linux/amd64 node:22-bookworm-slim AS node-stage
RUN npm install -g @google/gemini-cli && npm cache clean --force

# --- Stage 2: build the miner service image ---
FROM ${BASE_IMAGE}

USER root
RUN apt-get update && apt-get install -y --no-install-recommends nginx && \
    rm -rf /var/lib/apt/lists/* && apt-get clean
COPY --chown=root:root nginx.conf /etc/nginx/nginx.conf

# Copy Node.js runtime + Gemini CLI (no full nvm — saves ~400 MB)
COPY --from=node-stage /usr/local/bin/node /usr/local/bin/node
COPY --from=node-stage /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf ../lib/node_modules/@google/gemini-cli/bundle/gemini.js /usr/local/bin/gemini

USER miner

COPY --chown=miner:miner release/ /miner_release/
COPY --chown=miner:miner docker_entry.sh /miner_release/
RUN chmod a+x /miner_release/*.sh && mkdir -p $HOME/.cache/py-yfinance

RUN uv pip install /miner_release/Detonator /miner_release/DataMiner /miner_release/MarketBreadth /miner_release/MinerWorkers /miner_release/BrowserScraper /miner_release/MinerService && \
    rm -rfv /miner_release/Detonator /miner_release/DataMiner /miner_release/MarketBreadth /miner_release/MinerWorkers /miner_release/BrowserScraper /miner_release/MinerService && \
    rm -rfv $HOME/.cache/uv $HOME/.cache/pip

COPY --chown=miner:miner miner.json $HOME/.miner/miner.json

ENTRYPOINT /miner_release/docker_entry.sh
