import json
from datetime import datetime

from app.core.constants import *

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def ensure_dirs():
    for path in [DATA_DIR, STATUS_DIR, CONFIG_DIR, EXPORT_DIR, *RESUME_DIRS]:
        path.mkdir(parents=True, exist_ok=True)


def read_json(path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def append_event(event_type, candidate_id=None, detail=None, actor=None):
    EVENTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    event = {
        "time": now_iso(),
        "type": event_type,
        "candidate_id": candidate_id,
        "actor": actor or "",
        "detail": detail or {},
    }
    with EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def read_events():
    if not EVENTS_FILE.exists():
        return []
    events = []
    with EVENTS_FILE.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except Exception:
                pass
    return events


def is_today(iso_text):
    try:
        return datetime.fromisoformat(iso_text).astimezone().date() == datetime.now().astimezone().date()
    except Exception:
        return False

