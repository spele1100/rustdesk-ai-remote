#!/bin/bash
cd /root/.openclaw/workspace/projects/rustdesk-ai-remote/headless-client
export RUSTDESK_SERVER="aws.logany.info"
export RUSTDESK_TARGET_ID="283 760 096"
export RUSTDESK_PASSWORD="d88ax6"
python3 client.py --server "$RUSTDESK_SERVER" --target "$RUSTDESK_TARGET_ID" --password "$RUSTDESK_PASSWORD" 2>&1
