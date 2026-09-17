#!/bin/bash
set -e

# gunicorn stays on loopback only -- Apache is the sole thing listening on
# 80 (matching how ec-site is actually reached), and its own access_log
# picks up every request the way a production front end normally would.
gunicorn --workers 2 --threads 4 --bind 127.0.0.1:8000 app:app &

exec apache2ctl -D FOREGROUND
