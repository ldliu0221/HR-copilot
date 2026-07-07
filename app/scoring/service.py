import json
import re
import urllib.request

from app.config.service import load_app_config, active_model_config
from app.core.constants import DEFAULT_CANDIDATE_RESCORE_PROMPT
from app.llm.client import call_llm_json, get_llm_api_key, normalize_llm_endpoint
from app.core.storage import now_iso
from app.resume.parser import extract_keywords

def score_candidate(candidate, profile):
    text = (candidate.get("resume_text") or "") + "\n" + " ".join(candidate.get("skills") or [])
    lower = text.lower()
    max_score = 0
    score = 0
    matched = []
    missing = []
    for skill in profile.get("required_skills", []):
        name = skill.get("name", "")
        weight = float(skill.get("weight", 0) or 0)
        max_score += weight
        if name and name.lower() in lower:
            score += weight
            matched.append(name)
        else:
            missing.append(name)
    ability_hits = []
    for ability in profile.get("abilities", []):
        weight = float(ability.get("weight", 0) or 0)
        max_score += weight
        keywords = ability.get("keywords") or [ability.get("name", "")]
        hits = [k for k in keywords if k and k.lower() in lower]
        if hits:
            score += weight
            ability_hits.append(ability.get("name", ""))
    risk_hits = [k for k in profile.get("risk_keywords", []) if k and k.lower() in lower]
    normalized = round((score / max_score) * 100) if max_score else 0
    skill_total = sum(float(s.get("weight", 0) or 0) for s in profile.get("required_skills", []))
    skill_score = sum(float(s.get("weight", 0) or 0) for s in profile.get("required_skills", []) if s.get("name", "").lower() in lower)
    ability_total = sum(float(a.get("weight", 0) or 0) for a in profile.get("abilities", []))
    ability_score = 0
    for item in profile.get("abilities", []):
        keywords = item.get("keywords") or [item.get("name", "")]
        if any(k and k.lower() in lower for k in keywords):
            ability_score += float(item.get("weight", 0) or 0)
    risk_penalty = min(20, len(risk_hits) * 6)
    dimensions = [
        {"name": "技能匹配", "score": round(skill_score / skill_total * 100) if skill_total else 0, "evidence": matched[:6]},
        {"name": "能力信号", "score": round(ability_score / ability_total * 100) if ability_total else 0, "evidence": ability_hits[:6]},
        {"name": "风险控制", "score": max(0, 100 - risk_penalty), "evidence": risk_hits[:6]},
        {"name": "岗位相关", "score": min(100, normalized + (8 if matched and ability_hits else 0)), "evidence": [profile.get("name", "")]},
    ]
    questions = []
    if missing:
        questions.append("请候选人补充说明：" + "、".join(missing[:4]) + " 的实际项目经验。")
    questions.append("确认可实习周期、每周到岗天数、工作地点接受度和最快到岗时间。")
    if "LLM" in matched or "RAG" in matched:
        questions.append("追问最近一个 LLM/RAG 项目中的数据流、评测指标和上线问题。")
    return {
        "score": min(100, normalized),
        "profile_id": profile.get("id"),
        "profile_name": profile.get("name"),
        "matched_skills": matched,
        "missing_skills": missing,
        "abilities": ability_hits,
        "dimensions": dimensions,
        "risks": risk_hits or (["关键技能覆盖不足"] if normalized < profile.get("pass_score", 70) else []),
        "strengths": build_strengths(matched, ability_hits),
        "questions": questions,
        "suggestion": "建议推进群面" if normalized >= profile.get("pass_score", 70) else "建议补充追问后再决定",
        "scored_at": now_iso(),
        "method": "规则匹配，可在配置中接入大模型复评",
    }


def build_strengths(matched, abilities):
    items = []
    if matched:
        items.append("技能匹配：" + "、".join(matched[:6]))
    if abilities:
        items.append("能力信号：" + "、".join(abilities[:4]))
    if not items:
        items.append("简历中暂未识别到明显岗位匹配信号")
    return items


def try_llm_rescore(candidate, profile):
    config = load_app_config()
    if not config.get("llm_enabled"):
        return None
    model_cfg = active_model_config(config)
    api_key = get_llm_api_key(config, model_cfg)
    payload = {
        "model": model_cfg.get("model") or config.get("llm_model", "gpt-4o-mini"),
        "messages": [
            {"role": "system", "content": config.get("candidate_rescore_prompt") or DEFAULT_CANDIDATE_RESCORE_PROMPT},
            {"role": "user", "content": json.dumps({"job": profile, "resume": candidate.get("resume_text", "")[:8000]}, ensure_ascii=False)},
        ],
        "temperature": float(model_cfg.get("temperature", 0.2) or 0.2),
    }
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(normalize_llm_endpoint(model_cfg.get("base_url") or config.get("llm_base_url")), data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=int(model_cfg.get("timeout", 120) or 120)) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", content, re.S)
        return json.loads(match.group(0) if match else content)
    except Exception as exc:
        return {"error": str(exc)}


