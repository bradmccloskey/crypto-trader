#!/bin/bash
# SMS sender helper — watches the queue file and sends via iMessage (JXA).
# Uses the same JXA approach as the project orchestrator (proven working).
# Run this in a terminal that has Automation permission for Messages.app.
# Usage: ./scripts/sms_sender.sh

QUEUE="/Users/claude/projects/investment/crypto-trader/data/sms_queue.txt"
PHONE="+19197498832"
DIGITS="9197498832"

echo "[$(date '+%H:%M:%S')] SMS sender watching $QUEUE (Ctrl+C to stop)"

while true; do
    if [ -f "$QUEUE" ] && [ -s "$QUEUE" ]; then
        while IFS= read -r line; do
            if [ -n "$line" ]; then
                echo "[$(date '+%H:%M:%S')] Sending: ${line:0:80}..."

                # Write message to temp file (preserves special chars)
                TMPFILE="/tmp/crypto-sms-$(date +%s).txt"
                echo "$line" > "$TMPFILE"

                # Send via JXA (same approach as project orchestrator)
                /usr/bin/osascript -l JavaScript -e "
const m = Application('Messages');
const chat = m.chats().find(c => c.id().includes('${DIGITS}'));
if (!chat) throw new Error('No chat found');
const text = ObjC.unwrap(\$.NSString.stringWithContentsOfFileEncodingError('${TMPFILE}', \$.NSUTF8StringEncoding, null));
m.send(text, { to: chat });
" 2>/dev/null

                if [ $? -eq 0 ]; then
                    echo "  -> Sent OK"
                else
                    echo "  -> FAILED"
                fi
                rm -f "$TMPFILE"
            fi
        done < "$QUEUE"
        > "$QUEUE"  # clear the queue after processing
    fi
    sleep 5
done
