#!/bin/bash
# SMS sender helper — watches the queue file and sends via iMessage.
# Run this in a terminal that has Automation permission for Messages.app.
# Usage: ./scripts/sms_sender.sh

QUEUE="/Users/claude/projects/crypto-trader/data/sms_queue.txt"
PHONE="+19197498832"

echo "SMS sender watching $QUEUE (Ctrl+C to stop)"

while true; do
    if [ -f "$QUEUE" ] && [ -s "$QUEUE" ]; then
        while IFS= read -r line; do
            if [ -n "$line" ]; then
                echo "[$(date '+%H:%M:%S')] Sending: ${line:0:80}..."
                /usr/bin/osascript -e "
                    tell application \"Messages\"
                        set targetService to 1st account whose service type = iMessage
                        set targetBuddy to participant \"$PHONE\" of targetService
                        send \"$line\" to targetBuddy
                    end tell
                " 2>/dev/null
                if [ $? -eq 0 ]; then
                    echo "  -> Sent OK"
                else
                    echo "  -> FAILED"
                fi
            fi
        done < "$QUEUE"
        > "$QUEUE"  # clear the queue
    fi
    sleep 5
done
