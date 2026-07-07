import sys
from pathlib import Path


def load_index_html(root: Path) -> str:
    candidates = [root / "app/frontend" / "index.html"]
    bundle_root = getattr(sys, "_MEIPASS", None)
    if bundle_root:
        candidates.append(Path(bundle_root) / "app/frontend" / "index.html")
    for index_path in candidates:
        if index_path.exists():
            return index_path.read_text(encoding="utf-8")
    return (
        '<!doctype html><meta charset="utf-8"><title>HR Copilot</title>'
        "<body><h1>前端页面文件缺失</h1>"
        "<p>请确认 app/frontend/index.html 存在。</p></body>"
    )
