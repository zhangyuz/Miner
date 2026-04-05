ARG BASE_IMAGE=miner-base:latest
FROM ${BASE_IMAGE}

USER miner

COPY --chown=miner:miner release/ /miner_release/
COPY --chown=miner:miner docker_entry.sh /miner_release/
RUN chmod a+x /miner_release/*.sh

# nautilus_trader provides pre-built manylinux wheels for linux/amd64 + Python 3.12
# on PyPI, so Rust is NOT needed here (saves ~618 MB).
# If the install fails, add a multi-stage Rust builder — see IMPLEMENTATION_PLAN.md.
RUN uv pip install /miner_release/MinerTrader && \
    rm -rfv /miner_release/MinerTrader && \
    rm -rfv $HOME/.cache/uv $HOME/.cache/pip

ENTRYPOINT /miner_release/docker_entry.sh
