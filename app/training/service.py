import hashlib
import re

from app.config.service import load_app_config
from app.core.constants import DEFAULT_EXAM_GRADING_PROMPT, DEFAULT_TRAINING_EXAM_PROMPT
from app.data.service import load_training_exams, load_training_results, save_training_exams, save_training_results
from app.llm.client import call_llm_json
from app.core.storage import append_event, now_iso

def default_training_exam(payload):
    title = payload.get("title") or "新员工业务能力测评"
    target = payload.get("target") or "候选人/新员工"
    topic = payload.get("topic") or "岗位基础能力、业务理解和综合素质"
    difficulty = payload.get("difficulty") or "中等"
    total_score = int(payload.get("total_score") or 100)
    pass_score = int(payload.get("pass_score") or 60)
    skills = [x.strip() for x in re.split(r"[,，、\n]+", payload.get("skills", "")) if x.strip()]
    if not skills:
        skills = ["岗位认知", "专业技能", "问题分析", "沟通协作"]
    questions = []
    qid = 1
    for skill in skills[:4]:
        questions.append({
            "id": f"Q{qid}",
            "type": "单选题",
            "score": 5,
            "stem": f"关于{skill}，以下哪一项最能体现岗位所需能力？",
            "options": ["能结合业务目标说明方法选择", "只关注工具名称", "完全依赖他人安排", "忽略结果验证"],
            "answer": "能结合业务目标说明方法选择",
            "analysis": f"该题考察{skill}是否能落到业务目标、执行方法和结果验证。",
        })
        qid += 1
    questions.extend([
        {
            "id": f"Q{qid}",
            "type": "简答题",
            "score": 20,
            "stem": f"请结合{topic}，说明你会如何拆解一个真实工作任务，并识别关键风险。",
            "answer": "参考要点：目标澄清、信息收集、方案拆解、风险识别、里程碑和复盘。",
            "analysis": "重点看结构化表达、业务理解和风险意识。",
        },
        {
            "id": f"Q{qid + 1}",
            "type": "案例题",
            "score": 30,
            "stem": f"假设你负责推进一个{target}相关项目，时间紧、信息不完整，你会如何安排优先级并与团队协作？",
            "answer": "参考要点：明确目标、确定最小可交付、同步干系人、记录假设、及时复盘。",
            "analysis": "重点看项目推进、沟通协作和压力场景下的判断。",
        },
    ])
    return {
        "id": hashlib.sha1((title + now_iso()).encode("utf-8")).hexdigest()[:12],
        "title": title,
        "target": target,
        "topic": topic,
        "difficulty": difficulty,
        "duration": int(payload.get("duration") or 60),
        "total_score": total_score,
        "pass_score": pass_score,
        "description": payload.get("description") or f"面向{target}的{topic}测评，用于培训后验收和岗位胜任力判断。",
        "sections": [
            {"name": "基础认知", "score": 20, "focus": "岗位知识、基本概念、工具理解"},
            {"name": "能力应用", "score": 30, "focus": "任务拆解、方法选择、结果验证"},
            {"name": "案例综合", "score": 50, "focus": "业务场景、协作推进、风险控制"},
        ],
        "questions": questions,
        "scoring_rules": [
            "选择题按标准答案计分。",
            "简答题重点看结构完整度、关键风险识别和表达清晰度。",
            "案例题重点看目标拆解、优先级判断、沟通协作和复盘意识。",
        ],
        "created_at": now_iso(),
        "method": "本地规则生成",
    }


def generate_training_exam(payload):
    config = load_app_config()
    prompt = config.get("training_exam_prompt") or DEFAULT_TRAINING_EXAM_PROMPT
    llm = call_llm_json(prompt, payload, temperature=0.25, timeout=35, cap_timeout=True)
    exam = llm if not llm.get("error") else default_training_exam(payload)
    exam.setdefault("id", hashlib.sha1(((exam.get("title") or payload.get("title") or "exam") + now_iso()).encode("utf-8")).hexdigest()[:12])
    exam.setdefault("created_at", now_iso())
    exam.setdefault("method", "LLM智能生成" if not llm.get("error") else "本地规则生成")
    exam.setdefault("title", payload.get("title") or "新员工业务能力测评")
    exam.setdefault("total_score", int(payload.get("total_score") or 100))
    exam.setdefault("pass_score", int(payload.get("pass_score") or 60))
    if llm.get("error"):
        exam["llm_error"] = llm.get("error")
    exams = load_training_exams()
    exams = [e for e in exams if e.get("id") != exam["id"]]
    exams.insert(0, exam)
    save_training_exams(exams)
    return exam


def upsert_training_result(payload, actor=""):
    results = load_training_results()
    rid = payload.get("id") or hashlib.sha1(((payload.get("exam_id") or "") + (payload.get("student_name") or "") + now_iso()).encode("utf-8")).hexdigest()[:12]
    score = float(payload.get("score") or 0)
    pass_score = float(payload.get("pass_score") or 60)
    result = {
        "id": rid,
        "exam_id": payload.get("exam_id", ""),
        "exam_title": payload.get("exam_title", ""),
        "student_name": payload.get("student_name", ""),
        "department": payload.get("department", ""),
        "score": score,
        "total_score": float(payload.get("total_score") or 100),
        "pass_score": pass_score,
        "status": payload.get("status") or ("通过" if score >= pass_score else "未通过"),
        "submitted_at": payload.get("submitted_at") or now_iso(),
        "answers": payload.get("answers", ""),
        "comment": payload.get("comment", ""),
        "updated_by": actor,
        "updated_at": now_iso(),
    }
    results = [r for r in results if r.get("id") != rid]
    results.insert(0, result)
    save_training_results(results)
    return result


def local_grade_exam(exam, answer_text):
    answer_text = answer_text or ""
    total = float(exam.get("total_score") or 100)
    score = 0
    details = []
    for q in exam.get("questions", []):
        q_score = float(q.get("score") or 0)
        answer = str(q.get("answer") or "")
        stem = str(q.get("stem") or "")
        keywords = [x for x in re.split(r"[\s,，、；;。.\n]+", answer) if len(x) >= 2][:8]
        hit = sum(1 for k in keywords if k and k in answer_text)
        ratio = min(1, hit / max(1, min(4, len(keywords)))) if keywords else (0.7 if stem[:8] in answer_text else 0.4)
        earned = round(q_score * ratio, 1)
        score += earned
        details.append({"id": q.get("id"), "type": q.get("type"), "score": earned, "max_score": q_score, "reason": "命中参考答案关键要点" if hit else "未明显命中参考答案，建议人工复核"})
    score = max(0, min(total, round(score, 1)))
    return {
        "method": "本地标准答案关键词评分",
        "score": score,
        "total_score": total,
        "pass_score": float(exam.get("pass_score") or 60),
        "status": "通过" if score >= float(exam.get("pass_score") or 60) else "未通过",
        "details": details,
        "comment": "本地评分用于快速初筛；复杂语义题建议 HR 结合答题原文复核。",
        "review_required": any(d["score"] < d["max_score"] * 0.6 for d in details),
    }


def grade_training_answers(payload, actor=""):
    exams = load_training_exams()
    exam = next((e for e in exams if e.get("id") == payload.get("exam_id")), None)
    if not exam:
        raise ValueError("exam not found")
    answer_text = payload.get("answers") or payload.get("comment") or ""
    config = load_app_config()
    llm = call_llm_json(
        config.get("exam_grading_prompt") or DEFAULT_EXAM_GRADING_PROMPT,
        {"exam": exam, "answer_text": answer_text[:12000]},
        temperature=0.1,
        timeout=35,
        cap_timeout=True,
    )
    graded = llm if not llm.get("error") else local_grade_exam(exam, answer_text)
    graded.setdefault("method", "LLM智能阅卷" if not llm.get("error") else "本地标准答案关键词评分")
    graded.setdefault("total_score", exam.get("total_score", 100))
    graded.setdefault("pass_score", exam.get("pass_score", 60))
    graded.setdefault("status", "通过" if float(graded.get("score", 0) or 0) >= float(exam.get("pass_score", 60) or 60) else "未通过")
    if llm.get("error"):
        graded["llm_error"] = llm.get("error")
    result_payload = {
        **payload,
        "exam_title": exam.get("title"),
        "score": graded.get("score", 0),
        "total_score": graded.get("total_score", exam.get("total_score", 100)),
        "pass_score": graded.get("pass_score", exam.get("pass_score", 60)),
        "status": graded.get("status"),
        "answers": answer_text,
        "comment": graded.get("comment") or payload.get("comment", ""),
    }
    result = upsert_training_result(result_payload, actor=actor)
    result["grading"] = graded
    results = load_training_results()
    for item in results:
        if item.get("id") == result.get("id"):
            item["grading"] = graded
            item["answers"] = answer_text
    save_training_results(results)
    return result


