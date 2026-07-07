import os
import secrets

from app.core.constants import *
from app.core.storage import read_json, write_json

def default_job_profiles():
    return [
        {
            "id": "ai-intern",
            "name": "AI算法实习生",
            "description": "面向 AI/LLM/算法方向实习生，关注工程落地、模型调用、数据处理和学习能力。",
            "required_skills": [
                {"name": "Python", "weight": 18},
                {"name": "LLM", "weight": 12},
                {"name": "Prompt", "weight": 8},
                {"name": "RAG", "weight": 10},
                {"name": "FastAPI", "weight": 8},
                {"name": "Docker", "weight": 6},
                {"name": "Git", "weight": 5},
                {"name": "算法", "weight": 8},
            ],
            "abilities": [
                {"name": "项目交付经验", "keywords": ["交付", "上线", "联调", "部署"], "weight": 10},
                {"name": "数据与文档解析", "keywords": ["文档解析", "文本切分", "向量化", "数据"], "weight": 8},
                {"name": "沟通协作", "keywords": ["团队", "协助", "需求", "沟通"], "weight": 5},
            ],
            "risk_keywords": ["频繁跳槽", "无实习", "不接受实习", "无法到岗"],
            "pass_score": 70,
        }
    ]


def load_job_profiles():
    profiles = read_json(JOB_PROFILES_FILE, None)
    if not profiles:
        profiles = default_job_profiles()
        write_json(JOB_PROFILES_FILE, profiles)
    return profiles


def load_app_config():
    config = read_json(APP_CONFIG_FILE, None)
    if not config:
        config = {
            "llm_enabled": False,
            "llm_base_url": "https://api.openai.com/v1/chat/completions",
            "llm_model": "gpt-4o-mini",
            "llm_api_key": "",
            "llm_api_key_env": "OPENAI_API_KEY",
            "reminder_hours": 24,
            "manager_register_code": "MANAGER2026",
            "resume_parse_prompt": DEFAULT_RESUME_PARSE_PROMPT,
            "candidate_review_prompt": DEFAULT_CANDIDATE_REVIEW_PROMPT,
            "jd_generate_prompt": DEFAULT_JD_GENERATE_PROMPT,
            "next_action_prompt": DEFAULT_NEXT_ACTION_PROMPT,
            "group_score_prompt": DEFAULT_GROUP_SCORE_PROMPT,
            "interview_plan_prompt": DEFAULT_INTERVIEW_PLAN_PROMPT,
            "daily_report_prompt": DEFAULT_DAILY_REPORT_PROMPT,
            "training_exam_prompt": DEFAULT_TRAINING_EXAM_PROMPT,
            "exam_grading_prompt": DEFAULT_EXAM_GRADING_PROMPT,
            "candidate_rescore_prompt": DEFAULT_CANDIDATE_RESCORE_PROMPT,
            "ui_theme": "light",
            "ui_primary_color": "#126b61",
            "ui_font_size": 14,
            "ui_font_family": "Microsoft YaHei",
            "workflow_rules": AUTO_WORKFLOW_RULES,
            "mask_contact_for_hr": False,
            "data_retention_days": 365,
        }
        write_json(APP_CONFIG_FILE, config)
    changed = False
    defaults = {
        "llm_enabled": False,
        "llm_base_url": "https://api.openai.com/v1/chat/completions",
        "llm_model": "gpt-4o-mini",
        "llm_api_key": "",
        "llm_api_key_env": "OPENAI_API_KEY",
        "reminder_hours": 24,
        "manager_register_code": "MANAGER2026",
        "resume_parse_prompt": DEFAULT_RESUME_PARSE_PROMPT,
        "candidate_review_prompt": DEFAULT_CANDIDATE_REVIEW_PROMPT,
        "jd_generate_prompt": DEFAULT_JD_GENERATE_PROMPT,
        "next_action_prompt": DEFAULT_NEXT_ACTION_PROMPT,
        "group_score_prompt": DEFAULT_GROUP_SCORE_PROMPT,
        "interview_plan_prompt": DEFAULT_INTERVIEW_PLAN_PROMPT,
        "daily_report_prompt": DEFAULT_DAILY_REPORT_PROMPT,
        "training_exam_prompt": DEFAULT_TRAINING_EXAM_PROMPT,
        "exam_grading_prompt": DEFAULT_EXAM_GRADING_PROMPT,
        "candidate_rescore_prompt": DEFAULT_CANDIDATE_RESCORE_PROMPT,
        "ui_theme": "light",
        "ui_primary_color": "#126b61",
        "ui_font_size": 14,
        "ui_font_family": "Microsoft YaHei",
        "workflow_rules": AUTO_WORKFLOW_RULES,
        "mask_contact_for_hr": False,
        "data_retention_days": 365,
    }
    for key, value in defaults.items():
        if key not in config:
            config[key] = value
            changed = True
    if changed:
        write_json(APP_CONFIG_FILE, config)
    return config


def public_app_config():
    from app.collection.service import ensure_collection_sources, public_collection_source

    config = load_app_config()
    ensure_model_configs(config)
    ensure_collection_sources(config)
    safe = {k: v for k, v in config.items() if k != "llm_api_key"}
    safe["has_llm_api_key"] = bool(config.get("llm_api_key"))
    safe["model_configs"] = [public_model_config(m) for m in config.get("model_configs", [])]
    safe["collection_sources"] = [public_collection_source(s) for s in config.get("collection_sources", [])]
    return safe


def save_app_config_from_payload(payload):
    from app.collection.service import ensure_collection_sources

    config = load_app_config()
    ensure_model_configs(config)
    ensure_collection_sources(config)
    for key in ["llm_enabled", "llm_base_url", "llm_model", "llm_api_key_env", "manager_register_code", "resume_parse_prompt", "candidate_review_prompt", "jd_generate_prompt", "next_action_prompt", "group_score_prompt", "interview_plan_prompt", "daily_report_prompt", "training_exam_prompt", "exam_grading_prompt", "candidate_rescore_prompt", "ui_theme", "ui_primary_color", "ui_font_family"]:
        if key in payload:
            config[key] = payload[key]
    if "ui_font_size" in payload:
        try:
            config["ui_font_size"] = max(12, min(18, int(payload["ui_font_size"])))
        except Exception:
            config["ui_font_size"] = 14
    if "reminder_hours" in payload:
        try:
            config["reminder_hours"] = int(payload["reminder_hours"])
        except Exception:
            config["reminder_hours"] = 24
    if "data_retention_days" in payload:
        try:
            config["data_retention_days"] = max(30, int(payload["data_retention_days"]))
        except Exception:
            config["data_retention_days"] = 365
    if "mask_contact_for_hr" in payload:
        config["mask_contact_for_hr"] = bool(payload.get("mask_contact_for_hr"))
    if isinstance(payload.get("workflow_rules"), dict):
        config["workflow_rules"] = normalize_workflow_rules(payload.get("workflow_rules"))
    if payload.get("llm_api_key"):
        config["llm_api_key"] = payload["llm_api_key"]
    if payload.get("clear_llm_api_key"):
        config["llm_api_key"] = ""
    if isinstance(payload.get("model_configs"), list):
        models = []
        for item in payload["model_configs"]:
            model = {
                "id": item.get("id") or secrets.token_hex(6),
                "name": item.get("name") or item.get("model") or "未命名模型",
                "model": item.get("model") or "",
                "base_url": item.get("base_url") or "",
                "api_key": item.get("api_key") or "",
                "api_key_env": item.get("api_key_env") or "OPENAI_API_KEY",
                "temperature": float(item.get("temperature", 0.2) or 0.2),
                "timeout": int(item.get("timeout", 120) or 120),
                "thinking": item.get("thinking") or "OpenAI",
                "source": item.get("source") or "自定义",
                "status": item.get("status") or "未测试",
                "last_test": item.get("last_test", ""),
                "last_test_ok": item.get("last_test_ok", None),
                "last_test_message": item.get("last_test_message", ""),
                "available_models": item.get("available_models", []),
                "model_found": item.get("model_found", None),
                "models_error": item.get("models_error", ""),
            }
            old = find_model_config(config.get("model_configs", []), model["id"])
            if old and not model["api_key"]:
                model["api_key"] = old.get("api_key", "")
            models.append(model)
        config["model_configs"] = models
    if payload.get("active_model_id"):
        config["active_model_id"] = payload["active_model_id"]
    if isinstance(payload.get("collection_sources"), list):
        sources = []
        old_sources = {s.get("id"): s for s in config.get("collection_sources", [])}
        for item in payload["collection_sources"]:
            sid = str(item.get("id") or secrets.token_hex(4)).strip()
            source = {
                "id": sid,
                "name": item.get("name") or sid,
                "enabled": bool(item.get("enabled", True)),
                "api_url": item.get("api_url") or "",
                "method": (item.get("method") or "POST").upper(),
                "api_key": item.get("api_key") or "",
                "headers": item.get("headers") or "",
                "request_body": item.get("request_body") or "{}",
            }
            old = old_sources.get(sid)
            if old and not source["api_key"]:
                source["api_key"] = old.get("api_key", "")
            sources.append(source)
        config["collection_sources"] = sources
    sync_active_model_to_legacy(config)
    write_json(APP_CONFIG_FILE, config)
    return public_app_config()


def normalize_workflow_rules(rules=None):
    source = {**AUTO_WORKFLOW_RULES, **(rules or {})}
    normalized = {}
    for key, default in AUTO_WORKFLOW_RULES.items():
        try:
            normalized[key] = max(0, min(100, int(float(source.get(key, default)))))
        except Exception:
            normalized[key] = default
    return normalized


def load_workflow_rules():
    config = load_app_config()
    rules = normalize_workflow_rules(config.get("workflow_rules"))
    if rules != config.get("workflow_rules"):
        config["workflow_rules"] = rules
        write_json(APP_CONFIG_FILE, config)
    return rules


def default_model_config(config):
    return {
        "id": "default",
        "name": config.get("llm_model") or "默认模型",
        "model": config.get("llm_model", ""),
        "base_url": config.get("llm_base_url", ""),
        "api_key": config.get("llm_api_key", ""),
        "api_key_env": config.get("llm_api_key_env", "OPENAI_API_KEY"),
        "temperature": 0.2,
        "timeout": 120,
        "thinking": "OpenAI",
        "source": "环境配置",
        "status": "未测试",
        "last_test": "",
    }


def ensure_model_configs(config):
    if not config.get("model_configs"):
        config["model_configs"] = [default_model_config(config)]
        config["active_model_id"] = config["model_configs"][0]["id"]
        write_json(APP_CONFIG_FILE, config)
    if not config.get("active_model_id") and config.get("model_configs"):
        config["active_model_id"] = config["model_configs"][0]["id"]


def public_model_config(model):
    safe = {k: v for k, v in model.items() if k != "api_key"}
    safe["has_api_key"] = bool(model.get("api_key"))
    return safe


def find_model_config(models, model_id):
    return next((m for m in models if m.get("id") == model_id), None)


def active_model_config(config=None):
    config = config or load_app_config()
    ensure_model_configs(config)
    return find_model_config(config.get("model_configs", []), config.get("active_model_id")) or config["model_configs"][0]


def sync_active_model_to_legacy(config):
    model = active_model_config(config)
    config["llm_model"] = model.get("model", config.get("llm_model", ""))
    config["llm_base_url"] = model.get("base_url", config.get("llm_base_url", ""))
    config["llm_api_key_env"] = model.get("api_key_env", config.get("llm_api_key_env", "OPENAI_API_KEY"))
    config["llm_api_key"] = model.get("api_key", config.get("llm_api_key", ""))



