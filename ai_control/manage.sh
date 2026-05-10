#!/bin/bash
# Manage the headless client on AWS
# Usage: ./manage.sh start|stop|status|restart

set -e
SSH="ssh -i ~/claw-build-host-contabo-key -o StrictHostKeyChecking=no root@claw-build-host-contabo"
REMOTE_DIR="rustdesk-ai-remote"
BINARY="./target/release/headless-client"
LOG="/tmp/hd_ai.log"
SCREEN_NAME="headless"

case "${1:-}" in
  start)
    echo "🚀 Starting headless client..."
    $SSH bash -l -c "cd $REMOTE_DIR && screen -dmS $SCREEN_NAME $BINARY \
      --id 206909769 --password new_password \
      --server aws.logany.info:21116 \
      --key ZN2KCx+WreaaWUaFYsvig+Kt1udVQoIgmbhru6QXRKc= \
      --ws-port 8080"
    sleep 5
    $SSH "screen -ls | grep $SCREEN_NAME && echo '✅ Running' || echo '❌ Failed'"
    ;;
  stop)
    echo "🛑 Stopping headless client..."
    $SSH "pkill -9 headless 2>/dev/null; screen -S $SCREEN_NAME -X quit 2>/dev/null; echo '✅ Stopped'"
    ;;
  restart)
    $0 stop
    sleep 2
    $0 start
    ;;
  status)
    echo "📊 Status:"
    $SSH "pgrep -la headless || echo 'Not running'"
    ;;
  log)
    $SSH "strings $LOG | tail -30"
    ;;
  screenshot)
    echo "📸 Fetching screenshot..."
    scp -i ~/claw-build-host-contabo-key -o StrictHostKeyChecking=no \
      root@claw-build-host-contabo:/tmp/headless_screenshot.png \
      /tmp/ai_remote/latest.png
    echo "Saved to /tmp/ai_remote/latest.png"
    ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|log|screenshot}"
    exit 1
    ;;
esac
