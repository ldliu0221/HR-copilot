import re

from app.config.service import load_app_config, load_job_profiles
from app.core.constants import (
    DEFAULT_CANDIDATE_REVIEW_PROMPT,
    DEFAULT_DAILY_REPORT_PROMPT,
    DEFAULT_GROUP_SCORE_PROMPT,
    DEFAULT_INTERVIEW_PLAN_PROMPT,
    DEFAULT_NEXT_ACTION_PROMPT,
    DEFAULT_RESUME_PARSE_PROMPT,
)
from app.data.service import normalize_stage
from app.llm.client import call_llm_json
from app.scoring.service import score_candidate
from app.workflow.service import build_summary, build_templates

class RecruitingAgent:
    def __init__(self, profiles=None):
        self.profiles = profiles or load_job_profiles()

    def profile_for(self, candidate, profile_id=None):
        if profile_id:
            for profile in self.profiles:
                if profile.get("id") == profile_id:
                    return profile
        position = candidate.get("position", "")
        for profile in self.profiles:
            if profile.get("name") and profile.get("name") in position:
                return profile
        return self.profiles[0]

    def analyze_resume(self, candidate, profile_id=None):
        profile = self.profile_for(candidate, profile_id)
        config = load_app_config()
        llm = call_llm_json(
            config.get("resume_parse_prompt") or DEFAULT_RESUME_PARSE_PROMPT,
            {"job_profile": profile, "resume_text": candidate.get("resume_text", "")[:9000]},
        )
        if not llm.get("error"):
            llm["method"] = "LLM结构化解析"
            return llm
        text = candidate.get("resume_text", "")
        return {
            "method": "本地规则解析兜底",
            "analysis_summary": build_resume_summary(candidate),
            "education_analysis": f"学历信息：{candidate.get('education', '无')}",
            "skill_analysis": "技能信号：" + ("、".join((candidate.get("skills") or [])[:10]) or "无"),
            "project_analysis": "；".join(extract_section_lines(text, ["项目经历", "项目经验", "个人项目"], 4)) or "无",
            "experience_analysis": "；".join(extract_section_lines(text, ["实习经历", "工作经历"], 4)) or "无",
            "risk_points": candidate.get("match", {}).get("risks", []),
            "follow_up_questions": candidate.get("match", {}).get("questions", []),
            "conclusion": "基于本地规则生成分析；启用并连通大模型后可获得更完整的语义分析。",
            "confidence": "中",
            "llm_error": llm.get("error"),
        }

    def review_candidate(self, candidate, profile_id=None):
        profile = self.profile_for(candidate, profile_id)
        rule_score = score_candidate(candidate, profile)
        config = load_app_config()
        llm = call_llm_json(
            config.get("candidate_review_prompt") or DEFAULT_CANDIDATE_REVIEW_PROMPT,
            {"job_profile": profile, "rule_score": rule_score, "candidate": compact_candidate(candidate)},
        )
        if not llm.get("error"):
            if "score" not in llm and "suitability_score" in llm:
                llm["score"] = llm.get("suitability_score")
            llm.setdefault("score", rule_score.get("score", 0))
            llm.setdefault("suitability_score", llm.get("score", rule_score.get("score", 0)))
            llm.setdefault("suitability_level", suitability_level(llm.get("suitability_score", 0)))
            llm.setdefault("strengths", rule_score.get("strengths", []))
            llm.setdefault("risks", rule_score.get("risks", []))
            llm.setdefault("questions", rule_score.get("questions", []))
            llm.setdefault("decision", "建议推进群面" if float(llm.get("score", 0)) >= profile.get("pass_score", 70) else "建议补充追问")
            llm["method"] = "LLM评审"
            return llm
        return {
            "method": "本地规则评审兜底",
            "score": rule_score.get("score", 0),
            "suitability_score": rule_score.get("score", 0),
            "suitability_level": suitability_level(rule_score.get("score", 0)),
            "fit_summary": f"与岗位「{profile.get('name', '无')}」的适配度为 {rule_score.get('score', 0)} 分。",
            "matched_evidence": rule_score.get("strengths", []),
            "gap_risks": rule_score.get("risks", []),
            "decision": rule_score.get("suggestion"),
            "strengths": rule_score.get("strengths", []),
            "risks": rule_score.get("risks", []),
            "questions": rule_score.get("questions", []),
            "next_stage": "待群面" if rule_score.get("score", 0) >= profile.get("pass_score", 70) else "待沟通",
            "reason": "基于技能权重、能力关键词和风险关键词生成。",
            "llm_error": llm.get("error"),
        }

    def recommend_next_action(self, candidate):
        config = load_app_config()
        stage = normalize_stage(candidate.get("stage"))
        table = {
            "待沟通": ("发送首次沟通话术", "确认实习周期、到岗时间、地点接受度和岗位意向。", "已沟通"),
            "已沟通": ("判断是否推进群面", "查看匹配分和追问结果，满足通过线则推进群面。", "待群面"),
            "待群面": ("发送群面通知", "同步群面时间、形式、注意事项，并记录候选人确认状态。", "已群面"),
            "已群面": ("录入群面评价", "补充群面表现、维度分和是否进入作业环节。", "待提交群面作业"),
            "待提交群面作业": ("催交群面作业", "发送作业提交提醒，并记录截止时间。", "已提交群面"),
            "已提交群面": ("评审作业并约最终面", "结合简历、群面和作业表现决定是否进入最终面。", "待最终面"),
            "待最终面": ("发送最终面邀约", "协调候选人与面试官时间，并发送最终面提醒。", "已最终面"),
            "已最终面": ("输出录用建议", "汇总所有环节证据，建议通过、淘汰或补充追问。", "通过"),
            "淘汰": ("归档候选人", "记录淘汰原因，沉淀到岗位复盘中。", "淘汰"),
            "通过": ("进入入职跟进", "确认 Offer、入职时间和材料清单。", "通过"),
        }
        action, reason, suggested_stage = table.get(stage, table["待沟通"])
        llm = call_llm_json(
            config.get("next_action_prompt") or DEFAULT_NEXT_ACTION_PROMPT,
            {"candidate": compact_candidate(candidate), "current_stage": stage, "default_action": action},
        )
        if not llm.get("error"):
            llm.setdefault("suggested_stage", suggested_stage)
            llm["method"] = "LLM下一步推荐"
            return llm
        return {
            "method": "本地流程规则兜底",
            "action": action,
            "reason": reason,
            "message": build_templates(candidate).get("群面确认", next(iter(build_templates(candidate).values()))),
            "suggested_stage": suggested_stage,
            "priority": "高" if stage.startswith("待") else "中",
            "llm_error": llm.get("error"),
        }

    def score_group_interview(self, candidate, text):
        config = load_app_config()
        llm = call_llm_json(
            config.get("group_score_prompt") or DEFAULT_GROUP_SCORE_PROMPT,
            {"candidate": compact_candidate(candidate), "group_record_or_homework": text[:6000]},
        )
        if not llm.get("error"):
            llm["method"] = "LLM群面评分"
            return llm
        score = local_group_score(text)
        return {
            "method": "本地关键词评分兜底",
            "group_score": score,
            "dimension_scores": {
                "表达能力": min(20, 12 + text.count("沟通") + text.count("表达")),
                "逻辑能力": min(20, 12 + text.count("逻辑") + text.count("分析")),
                "专业理解": min(20, 12 + text.count("项目") + text.count("技术")),
                "协作意识": min(20, 12 + text.count("团队") + text.count("协作")),
                "岗位匹配度": min(20, 12 + text.count("AI") + text.count("Python")),
            },
            "evaluation": "根据输入记录识别到候选人具备一定表达、项目和岗位相关信号。",
            "decision": "建议进入最终面" if score >= 70 else "建议暂缓推进",
            "reason": "未启用大模型，使用关键词和维度规则生成兜底评分。",
            "risks": [] if score >= 70 else ["群面证据不足或岗位信号偏弱"],
        }

    def interview_plan(self, candidate, profile_id=None):
        profile = self.profile_for(candidate, profile_id)
        rule_score = candidate.get("match") or score_candidate(candidate, profile)
        config = load_app_config()
        llm = call_llm_json(
            config.get("interview_plan_prompt") or DEFAULT_INTERVIEW_PLAN_PROMPT,
            {"job_profile": profile, "rule_score": rule_score, "candidate": compact_candidate(candidate)},
            temperature=0.25,
            timeout=35,
            cap_timeout=True,
        )
        if not llm.get("error"):
            llm["method"] = "LLM智能面试方案"
            return llm
        return local_interview_plan(candidate, profile, rule_score, llm.get("error"))

    def daily_report(self, candidates):
        summary = build_summary(candidates)
        config = load_app_config()
        llm = call_llm_json(
            config.get("daily_report_prompt") or DEFAULT_DAILY_REPORT_PROMPT,
            {"summary": summary, "candidates": [compact_candidate(c) for c in candidates[:40]]},
        )
        if not llm.get("error"):
            llm["method"] = "LLM招聘日报"
            return llm
        pending = [c for c in candidates if normalize_stage(c.get("stage")).startswith("待")]
        return {
            "method": "本地日报兜底",
            "summary": f"当前共有 {len(candidates)} 位候选人，推进中 {summary.get('active', 0)} 位，平均匹配分 {summary.get('avg_score', 0)}。",
            "risks": ["待处理候选人较多，建议优先处理超时阶段。"] if pending else [],
            "priorities": [f"{c.get('name')}：{normalize_stage(c.get('stage'))}" for c in pending[:5]],
            "actions": ["优先跟进待沟通/待群面候选人", "对已提交群面作业候选人尽快安排最终面", "复盘淘汰原因和岗位标准"],
            "bottlenecks": [k for k, v in summary.get("stages", {}).items() if v > 0 and k.startswith("待")],
        }


def extract_section_lines(text, titles, limit=6):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    found = []
    capture = False
    for line in lines:
        if any(title in line for title in titles):
            capture = True
            continue
        if capture and re.search(r"教育背景|专业技能|个人荣誉|项目经历|实习经历|工作经历", line) and not any(t in line for t in titles):
            break
        if capture:
            found.append(line[:120])
        if len(found) >= limit:
            break
    return found


def build_resume_summary(candidate):
    skills = "、".join((candidate.get("skills") or [])[:8])
    return f"{candidate.get('name', '候选人')}投递{candidate.get('position', '无')}，学历信号：{candidate.get('education', '无')}，技能信号：{skills or '无'}。"


def local_interview_plan(candidate, profile, rule_score, llm_error=""):
    skills = candidate.get("skills") or rule_score.get("matched_skills") or []
    missing = rule_score.get("missing_skills") or []
    risks = rule_score.get("risks") or []
    questions = rule_score.get("questions") or []
    project_lines = extract_section_lines(candidate.get("resume_text") or "", ["项目经历", "项目经验", "个人项目"], 5)
    exp_lines = extract_section_lines(candidate.get("resume_text") or "", ["实习经历", "工作经历"], 4)
    focus = ["简历真实性与项目贡献边界", "岗位核心技能匹配度", "问题拆解、沟通表达和复盘能力"]
    if missing:
        focus.append("补齐缺口：" + "、".join(missing[:4]))
    if risks:
        focus.append("风险验证：" + "、".join(risks[:3]))
    return {
        "method": "本地规则面试方案兜底",
        "llm_error": llm_error,
        "interview_goal": f"验证候选人对{profile.get('name', candidate.get('position', '目标岗位'))}的真实匹配度，确认项目深度、技能掌握和推进风险。",
        "candidate_summary": build_resume_summary(candidate),
        "focus_areas": focus,
        "question_sections": [
            {"title": "一、开场与动机确认（5分钟）", "purpose": "确认岗位意愿、到岗安排和候选人表达状态。", "questions": ["请用 2 分钟介绍自己，并说明为什么关注这个岗位。", "你对这个岗位的核心工作内容如何理解？", "最快到岗时间、可实习/工作周期、工作地点接受度分别是什么？"]},
            {"title": "二、技术/能力基础验证（15分钟）", "purpose": "围绕简历技能和岗位标准验证基础能力。", "questions": [f"请说明你最熟悉的技能：{('、'.join(skills[:5]) or '简历中的核心技能')}，分别用在什么场景？", "遇到一个陌生业务需求时，你通常如何拆解、排期和交付？", *questions[:3]]},
            {"title": "三、项目深挖（20分钟）", "purpose": "确认项目真实性、个人贡献、复杂问题和结果产出。", "questions": ["请选择一个最能代表你能力的项目，说明背景、目标、你的职责和最终结果。", "项目中最难的问题是什么？你尝试过哪些方案，为什么最终选择当前方案？", "如果让你重新做一次，你会如何优化架构、流程或协作方式？", *project_lines[:3]]},
            {"title": "四、风险与稳定性确认（10分钟）", "purpose": "验证简历薄弱项、沟通风险和入职确定性。", "questions": ["简历里哪些内容你认为面试官最应该继续追问？", "如果入职后发现工作节奏/技术栈和预期不同，你会怎么处理？", "请补充说明：" + ("、".join(missing[:4]) if missing else "简历中未展开但与岗位相关的能力证明。")]},
        ],
        "project_deep_dive": project_lines or exp_lines or ["简历未识别到清晰项目段落，建议要求候选人现场讲述最近一次完整交付经历。"],
        "risk_checks": risks or ["简历信息完整度、项目贡献真实性、到岗稳定性"],
        "scoring_rubric": [
            {"dimension": "岗位技能匹配", "weight": 30, "pass_signal": "能解释关键技能的业务场景和实现细节"},
            {"dimension": "项目深度与真实性", "weight": 30, "pass_signal": "能讲清个人贡献、关键问题和结果指标"},
            {"dimension": "问题拆解与学习能力", "weight": 20, "pass_signal": "面对追问能结构化分析并给出取舍"},
            {"dimension": "沟通协作与稳定性", "weight": 20, "pass_signal": "表达清晰，动机稳定，到岗条件明确"},
        ],
        "schedule": [{"part": "开场与岗位动机", "minutes": 5}, {"part": "基础技能验证", "minutes": 15}, {"part": "项目深挖", "minutes": 20}, {"part": "风险确认与候选人提问", "minutes": 10}],
        "decision_signals": {"strong_hire": "项目讲述扎实，关键技能可落地，风险项解释充分。", "hold": "基础能力可接受，但项目贡献或稳定性需要二次确认。", "reject": "关键经历无法自洽，岗位核心技能明显缺口，或到岗条件不匹配。"},
        "interviewer_notes": "面试官记录时建议标注：证据、追问、风险、是否推进、下一步动作。",
    }


def compact_candidate(candidate):
    return {
        "id": candidate.get("id"),
        "name": candidate.get("name"),
        "position": candidate.get("position"),
        "stage": normalize_stage(candidate.get("stage")),
        "education": candidate.get("education"),
        "skills": candidate.get("skills", []),
        "match": candidate.get("match", {}),
        "group_interview": candidate.get("group_interview", {}),
        "assignment": candidate.get("assignment", {}),
        "hr_interview": candidate.get("hr_interview", {}),
        "notes": candidate.get("notes", ""),
        "resume_text": (candidate.get("resume_text") or "")[:5000],
    }


def local_group_score(text):
    base = 55
    for keyword in ["逻辑", "表达", "协作", "项目", "技术", "AI", "Python", "主动", "负责", "分析"]:
        if keyword.lower() in text.lower():
            base += 4
    return max(0, min(100, base))


def suitability_level(score):
    try:
        score = float(score)
    except Exception:
        score = 0
    if score >= 85:
        return "高度适配"
    if score >= 70:
        return "较适配"
    if score >= 55:
        return "一般适配"
    return "低适配"
