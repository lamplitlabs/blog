from datetime import datetime, timezone


def log_line(event: str, **fields) -> str:
    """Format one structured log line: `<ts> <event> k=v k=v`."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    parts = [ts, event] + [f"{k}={v}" for k, v in sorted(fields.items())]
    return " ".join(parts)
