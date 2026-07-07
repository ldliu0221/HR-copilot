import re

from app.core.constants import DEFAULT_JD_GENERATE_PROMPT
from app.config.service import load_app_config
from app.llm.client import call_llm_json

def normalize_list(value):
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if value:
        return [x.strip() for x in re.split(r"[；;\n]+", str(value)) if x.strip()]
    return []


def jd_profile_from_result(result):
    skills = normalize_list(result.get("skills") or result.get("skill_tags"))
    abilities = normalize_list(result.get("abilities") or result.get("competencies"))
    if not skills:
        skills = ["沟通协作", "学习能力", "执行力"]
    if not abilities:
        abilities = ["业务理解", "项目推进", "跨部门协作"]
    skill_weight = max(5, round(70 / max(1, len(skills))))
    ability_weight = max(5, round(30 / max(1, len(abilities))))
    return {
        "name": result.get("title", "新岗位"),
        "description": result.get("summary", ""),
        "pass_score": int(result.get("pass_score", 70) or 70),
        "required_skills": [{"name": s, "weight": skill_weight} for s in skills[:10]],
        "abilities": [{"name": a, "keywords": [a], "weight": ability_weight} for a in abilities[:8]],
        "risk_keywords": normalize_list(result.get("risk_keywords"))[:10],
    }


def jd_text_from_result(result):
    sections = [
        ("岗位职责", normalize_list(result.get("responsibilities"))),
        ("任职要求", normalize_list(result.get("requirements"))),
        ("公司介绍", normalize_list(result.get("company_intro") or result.get("company"))),
        ("福利待遇", normalize_list(result.get("benefits"))),
        ("工作亮点", normalize_list(result.get("highlights") or result.get("work_highlights"))),
        ("加分项", normalize_list(result.get("bonus_points"))),
        ("面试关注点", normalize_list(result.get("interview_focus"))),
    ]
    lines = [
        f"职位名称：{result.get('title', '新岗位')}",
        f"工作地点：{result.get('city', '不限')}",
        f"部门：{result.get('department', '待定')}",
        f"工作类型：{result.get('work_type', '全职')}",
        f"薪资范围：{result.get('salary', '面议')}",
        "",
        "职位描述：",
        result.get("summary", "").strip(),
    ]
    for title, items in sections:
        if items:
            lines.extend(["", title + "：", *[f"{i + 1}. {item}" for i, item in enumerate(items)]])
    return "\n".join([line for line in lines if line is not None]).strip()


def local_generate_jd(payload):
    title = (payload.get("title") or "新岗位").strip()
    city = (payload.get("city") or "不限").strip()
    department = (payload.get("department") or "待定").strip()
    salary = (payload.get("salary") or "面议").strip()
    education = payload.get("education") or "本科"
    work_type = payload.get("work_type") or "全职"
    experience = (payload.get("experience") or "具备相关岗位经验").strip()
    headcount = payload.get("headcount") or 1
    skills = normalize_list(payload.get("skills")) or ["沟通协作", "学习能力", "执行力"]
    highlights = normalize_list(payload.get("highlights"))
    company = payload.get("company") or "我们是一家重视长期发展与人才培养的公司，持续为员工提供清晰的成长路径和开放协作的工作环境。"
    knowledge = (payload.get("knowledge") or "").strip()
    background = payload.get("background") or f"围绕{title}相关业务场景，完成需求分析、方案设计、开发交付与持续优化。"
    if knowledge:
        background = f"{background} 参考行业知识与业务上下文：{knowledge[:500]}"
    result = {
        "method": "本地JD模板兜底" + (" + 知识库上下文" if knowledge else ""),
        "title": title,
        "city": city,
        "department": department,
        "salary": salary,
        "work_type": work_type,
        "summary": f"我们正在寻找一位经验丰富的{title}加入{department}，负责{background}。候选人需要具备扎实的编程基础和项目经验，能够独立完成开发任务并与团队高效协作。",
        "responsibilities": [
            f"参与{title}产品或系统的设计、开发和优化，确保高性能、可扩展性和稳定性。",
            "使用" + "、".join(skills[:5]) + "等技术栈进行功能开发、接口联调和问题排查。",
            "参与需求分析、技术方案设计及代码评审，推动项目高质量交付。",
            "解决开发过程中的技术难题，优化系统架构，提升开发效率。",
            "与产品、测试等团队紧密合作，确保项目按时高质量完成。",
        ],
        "requirements": [
            f"{education}及以上学历，计算机或相关专业优先。",
            experience,
            "掌握" + "、".join(skills[:6]) + "等相关技能。",
            "具备清晰表达、问题分析和跨团队协作能力。",
        ],
        "company_intro": [company],
        "benefits": ["五险一金", "带薪年假", "弹性工作", "技术培训"] if not highlights else highlights,
        "highlights": highlights or ["核心项目实践机会", "完善的技术成长路径", "开放协作的团队氛围"],
        "bonus_points": ["有复杂系统开发、性能优化或团队协作项目经验优先。"] + (["能结合行业知识库中的业务术语、项目场景和目标用户做方案设计。"] if knowledge else []),
        "interview_focus": ["岗位动机", "项目经历真实性", "问题拆解能力", "稳定性与到岗时间"] + (["是否理解行业知识库/RAG上下文中的真实业务场景"] if knowledge else []),
        "skills": skills,
        "abilities": ["项目推进", "沟通协作", "问题分析", "结果复盘"],
        "risk_keywords": ["频繁跳槽", "到岗时间不确定", "项目描述不清晰"],
        "pass_score": 70,
    }
    result["jd_text"] = jd_text_from_result(result)
    result["profile"] = jd_profile_from_result(result)
    return result


def generate_job_description(payload):
    config = load_app_config()
    llm = call_llm_json(
        config.get("jd_generate_prompt") or DEFAULT_JD_GENERATE_PROMPT,
        payload,
        temperature=0.35,
        timeout=35,
        cap_timeout=True,
    )
    if llm.get("error"):
        return local_generate_jd(payload)
    llm["method"] = "LLM JD生成"
    llm.setdefault("title", payload.get("title") or "新岗位")
    llm.setdefault("summary", "")
    llm["jd_text"] = llm.get("jd_text") or jd_text_from_result(llm)
    llm["profile"] = jd_profile_from_result(llm)
    return llm


