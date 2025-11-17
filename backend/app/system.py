from __future__ import annotations

import os
import resource
from datetime import datetime, timezone

from .models import ResourceSample, ResourceStats


def read_resource_stats() -> ResourceStats:
    cpu_cores = os.cpu_count() or 1
    try:
        load_1m = os.getloadavg()[0]
    except (OSError, AttributeError):
        load_1m = 0.0

    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss_kb = usage.ru_maxrss
    process_rss_bytes = int(rss_kb * 1024)

    read_bytes = None
    write_bytes = None
    try:
        with open("/proc/self/io", "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("read_bytes:"):
                    read_bytes = int(line.split()[1])
                elif line.startswith("write_bytes:"):
                    write_bytes = int(line.split()[1])
    except OSError:
        read_bytes = None
        write_bytes = None

    return ResourceStats(
        cpu_cores=cpu_cores,
        load_1m=float(load_1m),
        process_rss_bytes=process_rss_bytes,
        process_read_bytes=read_bytes,
        process_write_bytes=write_bytes,
    )


def read_resource_sample() -> ResourceSample:
    stats = read_resource_stats()
    return ResourceSample(
        timestamp=datetime.now(timezone.utc),
        cpu_cores=stats.cpu_cores,
        load_1m=stats.load_1m,
        process_rss_bytes=stats.process_rss_bytes,
        process_read_bytes=stats.process_read_bytes,
        process_write_bytes=stats.process_write_bytes,
    )
