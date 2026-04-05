ARG BASE_IMAGE=miner-base:latest

# --- Stage 1: grab Node.js + Gemini CLI ---
FROM --platform=linux/amd64 node:22-bookworm-slim AS node-stage
RUN npm install -g @google/gemini-cli && npm cache clean --force

# --- Stage 2: build the maintainer image ---
FROM ${BASE_IMAGE} AS base

USER root

# Copy Node.js runtime + Gemini CLI
COPY --from=node-stage /usr/local/bin/node /usr/local/bin/node
COPY --from=node-stage /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf ../lib/node_modules/@google/gemini-cli/bundle/gemini.js /usr/local/bin/gemini

USER miner

COPY --chown=miner:miner release/ /miner_release/
COPY --chown=miner:miner docker_entry.sh /miner_release/
RUN chmod a+x /miner_release/*.sh

RUN uv pip install /miner_release/Detonator /miner_release/DataMiner /miner_release/MinerWorkers /miner_release/Maintainer /miner_release/MarketBreadth && \
    rm -rfv /miner_release/Detonator /miner_release/DataMiner /miner_release/MinerWorkers /miner_release/Maintainer /miner_release/MarketBreadth && \
    rm -rfv $HOME/.cache/uv $HOME/.cache/pip

ARG RUNTIME_ENV
ARG GIT_USER_NAME
ARG GIT_USER_EMAIL
ARG GITHUB_TOKEN

COPY --chown=miner:miner setup_ssh_keys.sh $HOME/bin/
RUN chmod +x $HOME/bin/setup_ssh_keys.sh && \
    git config --global user.name "$GIT_USER_NAME" \
    && git config --global user.email "$GIT_USER_EMAIL"

RUN GITHUB_TOKEN="$GITHUB_TOKEN" $HOME/bin/setup_ssh_keys.sh && \
    rm -rfv $HOME/bin/setup_ssh_keys.sh

ENTRYPOINT /miner_release/docker_entry.sh
