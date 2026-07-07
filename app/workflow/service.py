from datetime import datetime, timedelta

from app.core.constants import *
from app.config.service import load_app_config, load_workflow_rules, normalize_workflow_rules
from app.data.service import normalize_stage
from app.core.storage import now_iso

def number_or_none(value):
    if value in [None, ""]:
        return None
    try:
        return float(value)
    except Exception:
        return None


def workflow_next_action(stage):
    stage = normalize_stage(stage)
    table = {
        "待沟通": ("完成首轮沟通", "确认实习周期、到岗时间和岗位意向", 1),
        "已沟通": ("安排群面", "发送群面时间并同步面试官", 2),
        "待群面": ("等待群面评价", "群面结束后上传评价或面试记录", 1),
        "已群面": ("判断是否进入作业", "录入群面分数并生成作业安排", 1),
        "待提交群面作业": ("催交群面作业", "发送作业要求和截止时间", 2),
        "已提交群面": ("评审作业并约终面", "录入作业评分，满足阈值后安排终面", 1),
        "待最终面": ("安排最终面", "协调候选人与面试官时间", 2),
        "已最终面": ("确认录用结论", "录入 HR 面评价并输出最终结果", 1),
        "淘汰": ("归档并记录原因", "沉淀淘汰原因用于岗位复盘", 0),
        "通过": ("进入入职跟进", "确认 Offer、入职时间和材料清单", 2),
    }
    action, reason, days = table.get(stage, table["待沟通"])
    due = (datetime.now().astimezone() + timedelta(days=days)).isoformat(timespec="seconds") if days else ""
    return {"action": action, "reason": reason, "due_at": due}


def apply_workflow_automation(candidate, trigger="manual", rules=None):
    rules = normalize_workflow_rules(rules or load_workflow_rules())
    previous = normalize_stage(candidate.get("stage"))
    stage = previous
    reason = ""
    final_result = candidate.get("final_result", "待定") or "待定"
    match_score = number_or_none(candidate.get("match", {}).get("score"))
    group = candidate.get("group_interview") or {}
    assignment = candidate.get("assignment") or {}
    hr = candidate.get("hr_interview") or {}
    group_score = number_or_none(group.get("score"))
    assignment_score = number_or_none(assignment.get("score"))
    hr_score = number_or_none(hr.get("score"))
    group_status = group.get("status", "")
    assignment_status = assignment.get("status", "")
    hr_status = hr.get("status", "")

    if final_result in ["通过", "淘汰"]:
        stage = final_result
        reason = f"最终结果为{final_result}，同步到流程终态"
    elif hr_score is not None or hr_status in ["已完成", "已评分", "通过", "淘汰"]:
        if hr_status == "淘汰" or (hr_score is not None and hr_score < rules["hr_pass_score"]):
            stage, final_result, reason = "淘汰", "淘汰", "HR面未通过，自动归档为淘汰"
        elif hr_status == "通过" or (hr_score is not None and hr_score >= rules["hr_pass_score"]):
            stage, final_result, reason = "通过", "通过", "HR面通过，自动进入通过流程"
        else:
            stage, reason = "已最终面", "HR面已完成，等待最终结论"
    elif assignment_score is not None or assignment_status in ["已提交", "已完成", "已评分", "通过", "淘汰"]:
        if assignment_status == "淘汰" or (assignment_score is not None and assignment_score < rules["assignment_pass_score"]):
            stage, final_result, reason = "淘汰", "淘汰", "群面作业未达标，自动归档为淘汰"
        elif assignment_status in ["通过", "已评分", "已完成", "已提交"] or (assignment_score is not None and assignment_score >= rules["assignment_pass_score"]):
            stage, reason = "待最终面", "作业已通过，自动推进到待最终面"
    elif group_score is not None or group_status in ["已完成", "已评分", "通过", "淘汰"]:
        if group_status == "淘汰" or (group_score is not None and group_score < rules["group_pass_score"]):
            stage, final_result, reason = "淘汰", "淘汰", "群面评价未达标，自动归档为淘汰"
        elif group_status in ["通过", "已评分", "已完成"] or (group_score is not None and group_score >= rules["group_pass_score"]):
            stage, reason = "待提交群面作业", "群面评价通过，自动推进到作业环节"
    elif match_score is not None and previous in ["待沟通", "已沟通"]:
        if match_score >= rules["resume_pass_score"]:
            stage, reason = "待群面", "简历匹配分达到通过线，自动推进到待群面"
        elif match_score < rules["resume_watch_score"]:
            stage, reason = "待沟通", "简历匹配分偏低，保留在待沟通待确认"

    candidate["stage"] = normalize_stage(stage)
    candidate["final_result"] = final_result
    next_action = workflow_next_action(candidate["stage"])
    candidate["workflow"] = {
        **candidate.get("workflow", {}),
        "auto_enabled": True,
        "rules": rules,
        "last_trigger": trigger,
        "last_stage_before": previous,
        "last_stage_after": candidate["stage"],
        "last_reason": reason or "未触发阶段变化，仅刷新下一步安排",
        "next_action": next_action,
        "updated_at": now_iso(),
    }
    return previous != candidate["stage"]


def build_summary(candidates):
    total = len(candidates)
    stages = {stage: 0 for stage in PIPELINE}
    for c in candidates:
        stage = normalize_stage(c.get("stage"))
        stages[stage] = stages.get(stage, 0) + 1
    active = [c for c in candidates if normalize_stage(c.get("stage")) not in ["淘汰", "通过"]]
    scored = [c for c in candidates if c.get("match", {}).get("score") not in [None, ""]]
    avg_score = round(sum(float(c.get("match", {}).get("score", 0)) for c in scored) / len(scored), 1) if scored else 0
    pass_count = len([c for c in scored if float(c.get("match", {}).get("score", 0)) >= 70])
    metrics = build_metrics(candidates, stages, scored, pass_count)
    duplicates = detect_duplicate_candidates(candidates)
    reminders = []
    for c in candidates:
        if normalize_stage(c.get("stage")) in ["待沟通", "待群面", "待提交群面作业", "待最终面"]:
            reminders.append({
                "id": c.get("id"),
                "name": c.get("name"),
                "stage": normalize_stage(c.get("stage")),
                "message": f"{c.get('name')} 当前处于「{normalize_stage(c.get('stage'))}」，建议今天完成跟进。",
            })
    return {
        "total": total,
        "active": len(active),
        "avg_score": avg_score,
        "pass_rate": round(pass_count / len(scored) * 100, 1) if scored else 0,
        "stages": stages,
        "metrics": metrics,
        "reminders": reminders[:12],
        "duplicates": duplicates[:20],
        "talent_pool_count": len([c for c in candidates if c.get("talent_pool")]),
        "exports": {
            "csv": str((EXPORT_DIR / "candidates.csv").relative_to(ROOT)),
            "status_csv": str(STATUS_CSV_FILE.relative_to(ROOT)),
        },
    }


def pct(num, den):
    return round(num / den * 100, 1) if den else 0


def build_metrics(candidates, stages, scored, pass_count):
    total = len(candidates)
    group_done = stages.get("已群面", 0) + stages.get("待提交群面作业", 0) + stages.get("已提交群面", 0) + stages.get("待最终面", 0) + stages.get("已最终面", 0) + stages.get("通过", 0)
    final_invited = stages.get("待最终面", 0) + stages.get("已最终面", 0) + stages.get("通过", 0)
    interviewed = stages.get("已最终面", 0) + stages.get("通过", 0)
    offered = stages.get("通过", 0)
    rejected = stages.get("淘汰", 0)
    by_position = {}
    for c in candidates:
        position = c.get("position") or "无"
        item = by_position.setdefault(position, {
            "position": position,
            "total": 0,
            "active": 0,
            "avg_score": 0,
            "scored": 0,
            "pass": 0,
            "offer": 0,
            "rejected": 0,
            "talent_pool": 0,
        })
        item["total"] += 1
        stage = normalize_stage(c.get("stage"))
        if stage not in ["淘汰", "通过"]:
            item["active"] += 1
        if stage == "通过":
            item["offer"] += 1
        if stage == "淘汰":
            item["rejected"] += 1
        if c.get("talent_pool"):
            item["talent_pool"] += 1
        score = c.get("match", {}).get("score")
        if score not in [None, ""]:
            item["avg_score"] += float(score)
            item["scored"] += 1
            if float(score) >= 70:
                item["pass"] += 1
    for item in by_position.values():
        item["avg_score"] = round(item["avg_score"] / item["scored"], 1) if item["scored"] else 0
        item["pass_rate"] = pct(item["pass"], item["scored"])
        item["offer_rate"] = pct(item["offer"], item["total"])
    return {
        "resume_pass_rate": pct(pass_count, len(scored)),
        "screen_pass_rate": pct(group_done, total),
        "interview_invite_rate": pct(final_invited, total),
        "interview_show_rate": pct(interviewed, final_invited),
        "offer_conversion_rate": pct(offered, total),
        "loss_rate": pct(rejected, total),
        "positions": sorted(by_position.values(), key=lambda x: (-x["total"], x["position"])),
    }


def duplicate_key(value):
    value = str(value or "").strip().lower()
    return value if value and value not in ["无", "none", "null"] else ""


def detect_duplicate_candidates(candidates):
    buckets = {}
    for c in candidates:
        keys = [
            ("phone", duplicate_key(c.get("phone"))),
            ("email", duplicate_key(c.get("email"))),
            ("name_position", duplicate_key(c.get("name")) + "|" + duplicate_key(c.get("position"))),
        ]
        for kind, key in keys:
            if not key or key == "|":
                continue
            buckets.setdefault((kind, key), []).append(c)
    duplicates = []
    seen = set()
    for (kind, key), items in buckets.items():
        if len(items) < 2:
            continue
        ids = tuple(sorted(i.get("id", "") for i in items))
        if ids in seen:
            continue
        seen.add(ids)
        duplicates.append({
            "kind": kind,
            "key": key,
            "count": len(items),
            "candidates": [{"id": i.get("id"), "name": i.get("name"), "position": i.get("position"), "source": i.get("source")} for i in items],
        })
    return duplicates


def mask_text(value, keep=3):
    value = str(value or "")
    if not value:
        return ""
    if "@" in value:
        name, domain = value.split("@", 1)
        return (name[:2] + "***@" + domain) if name else "***@" + domain
    if len(value) <= keep * 2:
        return value[:1] + "***"
    return value[:keep] + "****" + value[-keep:]


def candidates_for_user(candidates, user):
    config = load_app_config()
    if user.get("role") == "manager" or not config.get("mask_contact_for_hr"):
        return candidates
    safe = []
    for c in candidates:
        item = dict(c)
        item["phone"] = mask_text(item.get("phone"))
        item["email"] = mask_text(item.get("email"), keep=2)
        safe.append(item)
    return safe


def build_templates(candidate):
    name = candidate.get("name") or "同学"
    position = candidate.get("position") or "该岗位"
    questions = candidate.get("match", {}).get("questions") or ["确认可实习周期、工作地点接受度和最快到岗时间。"]
    score = candidate.get("match", {}).get("score", "未评分")
    return {
        "群面确认": f"{name}你好，我是招聘团队 HR。看到你投递/沟通的是{position}，简历匹配度为{score}分。想再和你确认一下实习周期、每周到岗天数、工作地点接受度和最快到岗时间，方便我们推进群面安排。",
        "追问问题": "\n".join([f"{i + 1}. {q}" for i, q in enumerate(questions[:4])]),
        "最终面邀约": f"{name}你好，你的{position}方向群面/作业已完成。想和你约一次最终面，请你回复 2-3 个方便的时间段，我们会尽快协调面试官。",
        "最终面提醒": f"{name}你好，提醒一下今天有{position}岗位最终面安排。请提前 5 分钟准备好简历、项目介绍和网络环境，如时间有变化请及时告诉我。",
        "反馈催办": f"面试官老师好，{name}的{position}最终面已完成，麻烦方便时同步一下评价、是否通过以及建议关注点，感谢。",
    }

