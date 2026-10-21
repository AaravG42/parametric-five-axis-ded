#!/bin/zsh
cd "$(dirname "$0")"
if /usr/bin/curl --silent --fail http://127.0.0.1:8000/api/fibr3d/preset >/dev/null; then
    open http://127.0.0.1:8000/
else
    python3 app.py 8000 &
    server_pid=$!
    for attempt in {1..30}; do
        if /usr/bin/curl --silent --fail http://127.0.0.1:8000/api/fibr3d/preset >/dev/null; then
            open http://127.0.0.1:8000/
            break
        fi
        sleep 1
    done
    echo 'Local generator running. Leave this window open while using the page.'
    wait "$server_pid"
fi
