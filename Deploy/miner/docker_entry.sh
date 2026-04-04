#!/bin/bash -l
set -x
set -e

MY_DIR=$(realpath $(dirname $0))

# $MY_DIR/run_socks5_proxy.sh &

echo 12qw | sudo -S nginx -g "daemon on; master_process off;"
# mongod --fork --syslog --bind_ip_all
# start flower for celery monitoring, you can view it from http://host/flower
celery --app=minerservice flower --port=6666 --auto_refresh=True --url_prefix=flower --broker_api=http://guest:guest@rabbitmq:15672/api &

touch ~/.miner-beat.log
celery --app=minerservice beat --loglevel INFO --detach --logfile ~/.miner-beat.log

touch ~/.miner-worker.log
# Wait for RabbitMQ to be ready before starting worker
echo "Waiting for RabbitMQ to be ready..."
until nc -z rabbitmq 5672; do
    echo "RabbitMQ not ready, waiting 5 seconds..."
    sleep 5
done
echo "RabbitMQ is ready, starting worker..."
celery --app=minerservice worker --loglevel INFO --detach --logfile ~/.miner-worker.log -Q minerservice --hostname=celery@miner-service --concurrency=2

$MY_DIR/run_service_as_prod_uds.sh &

sleep 5

catch_kill() {
  echo "Caught SIGKILL signal!"
  kill -KILL "$pid" 2>/dev/null
}

catch_term() {
  echo "Caught SIGTERM signal!"
  kill -TERM "$pid" 2>/dev/null
}

catch_quit() {
  echo "Caught SIGTERM signal!"
  kill -QUIT "$pid" 2>/dev/null
}

catch_ctrlc() {
  echo "Caught ctrl+c!"
  kill -KILL "$pid" 2>/dev/null
}

trap catch_term SIGTERM
trap catch_kill SIGKILL
trap catch_quit SIGQUIT
trap catch_ctrlc INT

echo "Script is running! waiting for signals."

pid=$$

sleep infinity
