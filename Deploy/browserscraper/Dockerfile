ARG BASE_IMAGE=miner-base:latest
FROM ${BASE_IMAGE}

USER root

RUN wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg && \
    echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list

RUN apt-get update && \
    apt-get install -y --no-install-recommends google-chrome-stable \
    libx11-6 libx11-xcb1 libxcomposite1 libxcursor1 libxdamage1 libxext6 \
    libxfixes3 libxi6 libxrandr2 libxrender1 libxtst6 libglib2.0-0 libnss3 \
    libasound2 x11-apps xvfb xauth && \
    rm -rf /var/lib/apt/lists/* && apt-get clean

USER miner
COPY --chown=miner:miner release/ /miner_release/
COPY --chown=miner:miner docker_entry.sh /miner_release/
RUN chmod a+x /miner_release/*.sh

RUN uv pip install /miner_release/Detonator /miner_release/DataMiner /miner_release/BrowserScraper /miner_release/MinerWorkers && \
    rm -rfv /miner_release/Detonator /miner_release/DataMiner /miner_release/BrowserScraper /miner_release/MinerWorkers && \
    rm -rfv $HOME/.cache/uv $HOME/.cache/pip

ENTRYPOINT xvfb-run --auto-servernum --server-args="-screen 0 1920x1080x24" /miner_release/docker_entry.sh
