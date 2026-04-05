#!/bin/sh

# set -x
# Exit immediately if a command exits with a non-zero status.
set -e

MY_PWD=$PWD
MY_DIR=$(realpath $(dirname $0))

RELEASE_DIR=$MY_DIR/miner/release
BROWSERSCRAPER_RELEASE_DIR=$MY_DIR/browserscraper/release
MAINTAINER_RELEASE_DIR=$MY_DIR/maintainer/release
TRADER_RELEASE_DIR=$MY_DIR/trader/release
STKGURU_RELEASE_DIR=$MY_DIR/stkguru/release

function cleanup() {
    # This function is called on exit to clean up temporary files.
    echo "Cleaning up temporary release directories..."
    rm -rf "$RELEASE_DIR"
    rm -rf "$BROWSERSCRAPER_RELEASE_DIR"
    rm -rf "$MAINTAINER_RELEASE_DIR"
    rm -rf "$TRADER_RELEASE_DIR"
    rm -rf "$STKGURU_RELEASE_DIR"
    cd "$MY_PWD"
}

function exit_callback() {
    local exit_status=$?
    cleanup # Always run cleanup
    if [ $exit_status -eq 0 ]; then
        echo "✅ Deployment script finished successfully."
    else
        echo "❌ Deployment script failed with exit code: $exit_status."
    fi
    set +x
    set +e
    exit $exit_status
}

# Trap the EXIT signal to run the exit_callback function when the script finishes.
trap exit_callback EXIT

echo "Let's go ..."

usage() {
    echo "you must have the environment variables set to deploy"
    exit 1
}

# Check if MINER_ENV is set and points to a valid file
if [ ! -z "$MINER_ENV" ] && [ -f "$MINER_ENV" ]; then
    echo "🔍 Sourcing environment file: $MINER_ENV"
    # Source the MINER_ENV file
    echo "📁 Sourcing environment file: $MINER_ENV"
    set -o allexport
    source "$MINER_ENV"
    set +o allexport
fi

echo "Github Token: $GITHUB_TOKEN"
echo "Runtime Env: $RUNTIME_ENV"
echo "Git user name: $GIT_USER_NAME"
echo "Git user email: $GIT_USER_EMAIL"
echo "Mail sender: $MAIL_SENDER"
echo "Mail sender pwd: $MAIL_SENDER_PWD"
echo "Mail receivers: $MAIL_RECEIVERS"
echo "Miner root: $MINER_ROOT"
echo "Gemini API key: ${GEMINI_API_KEY:+SET}"
echo ""
# Validate required environment variables
echo "🔍 Validating required environment variables..."
REQUIRED_VARS=(
    "GITHUB_TOKEN"
    "RUNTIME_ENV"
    "MINER_ROOT"
    "MAIL_SENDER"
    "MAIL_SENDER_PWD"
    "MAIL_RECEIVERS"
    "GIT_USER_NAME"
    "GIT_USER_EMAIL"
)

MISSING_VARS=()
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var}" ]; then
        MISSING_VARS+=("$var")
    fi
done


if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    echo "❌ Error: Missing required environment variables:"
    for var in "${MISSING_VARS[@]}"; do
        echo "   - $var"
    done
    echo ""
    echo "Please ensure all required variables are set in your MINER_ENV file: $MINER_ENV"
    exit 1
fi

echo "✅ All required environment variables are set"

cd $MY_DIR

mkdir -p $MINER_ROOT/mongogo

mkdir -p "$MY_DIR/base/bin/"

rm -rf $RELEASE_DIR
mkdir -p $RELEASE_DIR

rm -rf $BROWSERSCRAPER_RELEASE_DIR
mkdir -p $BROWSERSCRAPER_RELEASE_DIR

rm -rf $MAINTAINER_RELEASE_DIR
mkdir -p $MAINTAINER_RELEASE_DIR

rm -rf $TRADER_RELEASE_DIR
mkdir -p $TRADER_RELEASE_DIR

rm -rf $STKGURU_RELEASE_DIR
mkdir -p $STKGURU_RELEASE_DIR

cp -a $MY_DIR/../Detonator $RELEASE_DIR/
cp -a $MY_DIR/../DataMiner $RELEASE_DIR/
cp -a $MY_DIR/../MarketBreadth $RELEASE_DIR/
cp -a $MY_DIR/../MinerWorkers $RELEASE_DIR/
cp -a $MY_DIR/../MinerService $RELEASE_DIR/
cp -a $MY_DIR/../BrowserScraper $RELEASE_DIR/
cp -a $MY_DIR/../MinerService/run_service_as_prod_uds.sh $RELEASE_DIR/
cp -a $MY_DIR/miner/run_socks5_proxy.sh $RELEASE_DIR/
cp -a $MY_DIR/miner/docker_entry.sh $RELEASE_DIR/

cp -a $MY_DIR/../Detonator $BROWSERSCRAPER_RELEASE_DIR/
cp -a $MY_DIR/../DataMiner $BROWSERSCRAPER_RELEASE_DIR/
cp -a $MY_DIR/../MinerWorkers $BROWSERSCRAPER_RELEASE_DIR/
cp -a $MY_DIR/../BrowserScraper $BROWSERSCRAPER_RELEASE_DIR/
cp -a $MY_DIR/browserscraper/docker_entry.sh $BROWSERSCRAPER_RELEASE_DIR/

cp -a $MY_DIR/../Detonator $MAINTAINER_RELEASE_DIR/
cp -a $MY_DIR/../MarketBreadth $MAINTAINER_RELEASE_DIR/
cp -a $MY_DIR/../DataMiner $MAINTAINER_RELEASE_DIR/
cp -a $MY_DIR/../MinerWorkers $MAINTAINER_RELEASE_DIR/
cp -a $MY_DIR/../Maintainer $MAINTAINER_RELEASE_DIR/
cp -a $MY_DIR/maintainer/docker_entry.sh $MAINTAINER_RELEASE_DIR/

cp -a $MY_DIR/../MinerTrader $TRADER_RELEASE_DIR/
cp -a $MY_DIR/trader/docker_entry.sh $TRADER_RELEASE_DIR/

cp -a $MY_DIR/../StkGuru $STKGURU_RELEASE_DIR/
rm -rf $STKGURU_RELEASE_DIR/StkGuru/public/api
rm -rf $STKGURU_RELEASE_DIR/StkGuru/node_modules
rm -rf $STKGURU_RELEASE_DIR/StkGuru/dist

# Set base image folder
BASE_DIR=$MY_DIR/base
BASE_DOCKERFILE=$BASE_DIR/Dockerfile.base
BASE_IMAGE_TAG=miner-base:latest
BASE_HASH_FILE=$BASE_DIR/.docker_base_hash

if [ -f "$BASE_DOCKERFILE" ]; then
    BASE_HASH=$(sha256sum "$BASE_DOCKERFILE" 2>/dev/null | awk '{print $1}')
    PREV_HASH=""
    if [ -f "$BASE_HASH_FILE" ]; then
        PREV_HASH=$(cat "$BASE_HASH_FILE")
    fi
    IMAGE_EXISTS=$(docker images -q $BASE_IMAGE_TAG)
    if [ -z "$IMAGE_EXISTS" ] || [ "$BASE_HASH" != "$PREV_HASH" ]; then
        echo "Building $BASE_IMAGE_TAG from $BASE_DOCKERFILE ..."
        docker build -f "$BASE_DOCKERFILE" -t $BASE_IMAGE_TAG "$BASE_DIR"
        echo "$BASE_HASH" > "$BASE_HASH_FILE"
    else
        echo "$BASE_IMAGE_TAG is up to date, skipping rebuild."
    fi
    # Create a dummy container to protect the base image from prune
    docker stop keep-miner-base || true
    docker rm keep-miner-base || true
    docker run -d --name keep-miner-base $BASE_IMAGE_TAG bash -c 'sleep infinity' || true
else
    echo "Dockerfile.base not found, skipping build."
    exit 1
fi

COMPOSE_BAKE=true docker compose --project-name miner up --build -d

#set +x
# The 'set +e' and final cleanup call are no longer needed as the EXIT trap handles the script's conclusion.
