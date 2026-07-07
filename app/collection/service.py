import base64
import json
import re
import secrets
import shutil
import urllib.request
from datetime import datetime
from pathlib import Path

from app.core.constants import *
from app.core.storage import append_event, ensure_dirs, now_iso, write_json
from app.resume.parser import candidate_id_from_file, fallback_resume_text, extract_resume_text, parse_resume
from app.config.service import load_app_config
from app.data.service import current_resume_files, load_candidates, save_candidates

PLATFORM_SOURCES = {
    "boss": "BOSS直聘",
    "liepin": "猎聘",
    "zhilian": "智联招聘",
    "51job": "前程无忧",
    "local": "本地上传",
}


def default_collection_sources():
    return [
        {"id": "boss", "name": "BOSS直聘", "enabled": True, "api_url": "", "method": "POST", "api_key": "", "headers": "", "request_body": "{}"},
        {"id": "liepin", "name": "猎聘", "enabled": True, "api_url": "", "method": "POST", "api_key": "", "headers": "", "request_body": "{}"},
        {"id": "zhilian", "name": "智联招聘", "enabled": True, "api_url": "", "method": "POST", "api_key": "", "headers": "", "request_body": "{}"},
        {"id": "51job", "name": "前程无忧", "enabled": True, "api_url": "", "method": "POST", "api_key": "", "headers": "", "request_body": "{}"},
        {"id": "local", "name": "本地上传", "enabled": True, "api_url": "", "method": "POST", "api_key": "", "headers": "", "request_body": "{}"},
    ]


def normalize_collection_sources(sources=None):
    defaults = {item["id"]: item for item in default_collection_sources()}
    if not isinstance(sources, list) or not sources:
        sources = default_collection_sources()
    merged = []
    seen = set()
    for item in sources:
        sid = str(item.get("id") or secrets.token_hex(4)).strip()
        base = defaults.get(sid, {})
        merged.append({
            **base,
            **item,
            "id": sid,
            "name": item.get("name") or base.get("name") or sid,
            "enabled": bool(item.get("enabled", True)),
            "method": (item.get("method") or "POST").upper(),
            "headers": item.get("headers") or "",
            "request_body": item.get("request_body") or "{}",
        })
        seen.add(sid)
    for sid, item in defaults.items():
        if sid not in seen:
            merged.append(item)
    return merged


def normalize_user_collection_sources(user):
    return normalize_collection_sources(user.get("collection_sources"))


def ensure_collection_sources(config):
    existing = config.get("collection_sources")
    if not isinstance(existing, list) or not existing:
        config["collection_sources"] = default_collection_sources()
        write_json(APP_CONFIG_FILE, config)
        return
    config["collection_sources"] = normalize_collection_sources(existing)


def public_collection_source(item):
    safe = {k: v for k, v in item.items() if k != "api_key"}
    safe["has_api_key"] = bool(item.get("api_key"))
    return safe


def collection_source_map(user=None):
    if user:
        return {item.get("id"): item for item in normalize_user_collection_sources(user)}
    config = load_app_config()
    ensure_collection_sources(config)
    return {item.get("id"): item for item in config.get("collection_sources", [])}


def platform_key(source, user=None):
    raw = (source or "local").strip().lower()
    configured = collection_source_map(user)
    if raw in configured:
        return raw
    if "boss" in raw or "boss直聘" in raw:
        return "boss"
    if "liepin" in raw or "猎聘" in raw:
        return "liepin"
    if "zhilian" in raw or "智联" in raw:
        return "zhilian"
    if "51job" in raw or "前程" in raw:
        return "51job"
    return "local"


def source_from_resume_path(path, user=None):
    text = str(path).lower()
    configured = collection_source_map(user)
    labels = {key: value.get("name", key) for key, value in configured.items()}
    labels.update(PLATFORM_SOURCES)
    for key, label in labels.items():
        if key in text:
            return label
    return "本地简历"


def safe_upload_name(name):
    name = Path(name or "resume.txt").name
    stem = re.sub(r"[^\w\u4e00-\u9fa5·.-]+", "_", Path(name).stem).strip("._") or "resume"
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_RESUME_SUFFIXES:
        suffix = ".txt"
    return stem[:80] + suffix


def save_collected_resumes(payload, actor=None, user=None):
    ensure_dirs()
    key = platform_key(payload.get("source"), user)
    configured = collection_source_map(user)
    source = configured.get(key, {}).get("name") or PLATFORM_SOURCES.get(key, "本地上传")
    target_dir = RESUME_DIRS[0] / key
    target_dir.mkdir(parents=True, exist_ok=True)
    saved = []
    skipped = []
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    for i, item in enumerate(payload.get("files") or []):
        name = safe_upload_name(item.get("name") or f"resume-{i + 1}.txt")
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED_RESUME_SUFFIXES:
            skipped.append({"name": name, "reason": "unsupported_type"})
            continue
        raw = item.get("content") or ""
        if "," in raw and raw.split(",", 1)[0].startswith("data:"):
            raw = raw.split(",", 1)[1]
        try:
            data = base64.b64decode(raw)
        except Exception as exc:
            skipped.append({"name": name, "reason": str(exc)})
            continue
        path = target_dir / f"{stamp}_{i + 1}_{name}"
        path.write_bytes(data)
        saved.append(str(path.relative_to(ROOT)))
    for i, item in enumerate(payload.get("texts") or []):
        text = (item.get("text") or "").strip()
        if not text:
            continue
        name = safe_upload_name(item.get("name") or f"{source}-候选人-{i + 1}.txt")
        path = target_dir / f"{stamp}_text_{i + 1}_{Path(name).stem}.txt"
        header = f"来源：{source}\n采集人：{actor or ''}\n采集时间：{now_iso()}\n\n"
        path.write_text(header + text, encoding="utf-8")
        saved.append(str(path.relative_to(ROOT)))
    result = scan_resumes(actor=actor, remove_missing=False, user=user)
    append_event("resume_collected", None, {"source": source, "saved": saved, "skipped": skipped}, actor=actor)
    return {"ok": True, "source": source, "saved": saved, "saved_count": len(saved), "skipped": skipped, "scan": result}


def collect_resumes_from_api(source_id, actor=None, user=None):
    sources = normalize_user_collection_sources(user or {})
    source = next((s for s in sources if s.get("id") == source_id), None)
    if not source:
        return {"ok": False, "error": "collection source not found"}
    if not source.get("enabled"):
        return {"ok": False, "error": "collection source disabled"}
    if not source.get("api_url"):
        return {"ok": False, "error": "api_url_empty", "message": "该来源还没有配置 API，可先使用本地文件或粘贴文本导入。"}
    headers = {"Content-Type": "application/json"}
    if source.get("api_key"):
        headers["Authorization"] = f"Bearer {source.get('api_key')}"
    try:
        custom_headers = json.loads(source.get("headers") or "{}")
        if isinstance(custom_headers, dict):
            headers.update({str(k): str(v) for k, v in custom_headers.items()})
    except Exception:
        pass
    try:
        request_body = json.loads(source.get("request_body") or "{}")
    except Exception:
        request_body = {}
    request_body.setdefault("source", source.get("id"))
    request_body.setdefault("requested_by", actor or "")
    data = json.dumps(request_body, ensure_ascii=False).encode("utf-8")
    method = (source.get("method") or "POST").upper()
    req = urllib.request.Request(source.get("api_url"), data=data if method != "GET" else None, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "source": source.get("name"), "error": str(exc)}
    payload = {"source": source.get("id"), "files": result.get("files") or [], "texts": result.get("texts") or []}
    for i, candidate in enumerate(result.get("candidates") or []):
        if isinstance(candidate, dict):
            text = candidate.get("resume_text") or candidate.get("text") or json.dumps(candidate, ensure_ascii=False, indent=2)
            name = candidate.get("name") or f"{source.get('name')}-候选人-{i + 1}"
            payload["texts"].append({"name": name + ".txt", "text": text})
    if not payload["files"] and not payload["texts"]:
        return {"ok": True, "source": source.get("name"), "saved_count": 0, "message": "API 已返回，但未识别到 files/texts/candidates 字段。", "raw": result}
    collected = save_collected_resumes(payload, actor=actor, user=user)
    collected["api_source"] = source.get("name")
    return collected


def scan_resumes(actor=None, remove_missing=False, user=None):
    ensure_dirs()
    candidates = load_candidates()
    by_id = {c["id"]: c for c in candidates}
    scanned = 0
    failed = []
    seen_ids = set()
    for path in current_resume_files():
            scanned += 1
            cid = candidate_id_from_file(path)
            seen_ids.add(cid)
            text, err = extract_resume_text(path)
            if not text:
                failed.append({"file": str(path), "error": err, "imported_from_filename": True})
                text = fallback_resume_text(path, err)
            parsed = parse_resume(path, text)
            parsed["source"] = source_from_resume_path(path, user)
            if err:
                parsed["parse_status"] = "filename_only"
                parsed["parse_error"] = err
                parsed["notes"] = (parsed.get("notes") or "") + "简历原文解析失败，已先按文件名导入，待安装 PDF/DOCX 解析依赖后重新解析。"
            if cid in by_id:
                existing = by_id[cid]
                if err and existing.get("parse_status") == "parsed" and not (existing.get("resume_text", "").startswith("姓名：") and "仅从文件名导入" in existing.get("resume_text", "")):
                    existing["parse_error"] = err
                    existing["updated_at"] = now_iso()
                    continue
                preserved = {
                    "stage": existing.get("stage"),
                    "notes": existing.get("notes"),
                    "group_interview": existing.get("group_interview"),
                    "assignment": existing.get("assignment"),
                    "hr_interview": existing.get("hr_interview"),
                    "final_result": existing.get("final_result"),
                    "match": existing.get("match"),
                    "created_at": existing.get("created_at"),
                }
                existing.update(parsed)
                for key, value in preserved.items():
                    if value not in [None, "", {}, []]:
                        existing[key] = value
                if err and existing.get("resume_text", "").startswith("姓名："):
                    existing["parse_status"] = "filename_only"
                    existing["parse_error"] = err
                existing["updated_at"] = now_iso()
            else:
                candidates.append(parsed)
                by_id[cid] = parsed
                append_event("candidate_created", cid, {"file": parsed["resume_file"]}, actor=actor)
    removed = []
    if remove_missing:
        kept = []
        for c in candidates:
            cid = c.get("id")
            if c.get("source") == "本地简历" and c.get("resume_file") and cid not in seen_ids:
                removed.append({"id": cid, "name": c.get("name", ""), "resume_file": c.get("resume_file", "")})
            else:
                kept.append(c)
        candidates = kept
    save_candidates(candidates)
    return {"scanned": scanned, "total": len(candidates), "failed": failed, "removed": removed, "removed_count": len(removed)}

