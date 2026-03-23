#!/bin/sh

if [ "$1" = "start" ]; then
    MAX_WAIT_SECONDS=15
    nohup uv run mitmdump -s rewrite_addon.py --listen-port 8080 > mitmproxy.log 2>&1 &
    echo $! > mitmproxy.pid
    # wait for ~/.mitmproxy/mitmproxy-ca-cert.pem to be ready
    i=0
    while [ "$i" -lt "$MAX_WAIT_SECONDS" ]; do
        i=$((i + 1))
        if [ -f ~/.mitmproxy/mitmproxy-ca-cert.pem ]; then
            break
        fi
        sleep 1
    done
    if [ "$i" -eq "$MAX_WAIT_SECONDS" ]; then
        echo "~/.mitmproxy/mitmproxy-ca-cert.pem is not ready after $MAX_WAIT_SECONDS seconds"
        exit 1
    else
        echo "~/.mitmproxy/mitmproxy-ca-cert.pem is ready"
    fi

    # wait for mitmproxy to be ready
    i=0
    while [ "$i" -lt "$MAX_WAIT_SECONDS" ]; do
        i=$((i + 1))
        if curl -s http://localhost:8080/ > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    if [ "$i" -eq "$MAX_WAIT_SECONDS" ]; then
        echo "mitmproxy is not ready after $MAX_WAIT_SECONDS seconds"
        exit 1
    else
        echo "mitmproxy is ready"
    fi
elif [ "$1" = "stop" ]; then
    kill $(cat mitmproxy.pid)
    rm mitmproxy.pid
fi
