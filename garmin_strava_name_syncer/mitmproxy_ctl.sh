#!/bin/sh

if [ "$1" = "start" ]; then
    nohup uv run mitmdump -s rewrite_addon.py --listen-port 8080 > mitmproxy.log 2>&1 &
    echo $! > mitmproxy.pid
    # wait mitmproxy to be ready and maximum 5 seconds
    i=0
    while [ "$i" -lt 10 ]; do
        i=$((i + 1))
        if curl -s http://localhost:8080/ > /dev/null 2>&1; then
            break
        fi
        sleep 1
    done
    if [ "$i" -eq 5 ]; then
        echo "mitmproxy is not ready after 5 seconds"
        exit 1
    else
        echo "mitmproxy is ready"
        cp ~/.mitmproxy/mitmproxy-ca-cert.pem .
    fi
elif [ "$1" = "stop" ]; then
    kill $(cat mitmproxy.pid)
    rm mitmproxy.pid
fi
