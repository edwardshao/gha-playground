#!/bin/sh

if [ "$1" = "start" ]; then
    nohup uv run mitmdump -s rewrite_addon.py --listen-port 8080 > mitmproxy.log 2>&1 &
    echo $! > mitmproxy.pid
elif [ "$1" = "stop" ]; then
    kill $(cat mitmproxy.pid)
    rm mitmproxy.pid
fi
