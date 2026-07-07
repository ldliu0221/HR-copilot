import base64
import csv
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import sys
import traceback
import urllib.request
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app.frontend.loader import load_index_html


from app.core.constants import *
from app.core.storage import *
from app.resume.parser import *
from app.auth.service import *
from app.config.service import *
from app.data.service import *
from app.workflow.service import *
from app.collection.service import *
from app.llm.client import *
from app.jd.service import *
from app.scoring.service import *
from app.training.service import *
from app.agent.service import *



































class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if sys.stderr:
            sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def current_user(self):
        cookie = self.headers.get("Cookie", "")
        token = ""
        for part in cookie.split(";"):
            if part.strip().startswith("hr_session="):
                token = part.strip().split("=", 1)[1]
        return get_user_by_session(token)

    def require_user(self):
        user = self.current_user()
        if not user:
            self.send_json({"error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
            return None
        return user

    def require_manager(self):
        user = self.require_user()
        if not user:
            return None
        if user.get("role") != "manager":
            self.send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
            return None
        return user

    def send_json(self, payload, status=HTTPStatus.OK):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", "0") or 0)
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                body = load_index_html(ROOT).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif parsed.path == "/api/me":
                user = self.current_user()
                self.send_json({"user": public_user(user) if user else None})
            elif parsed.path == "/api/admin/overview":
                if not self.require_manager():
                    return
                self.send_json(manager_overview())
            elif parsed.path == "/api/app-config":
                if not self.require_manager():
                    return
                self.send_json(public_app_config())
            elif parsed.path == "/api/collection-sources":
                user = self.require_user()
                if not user:
                    return
                self.send_json([public_collection_source(s) for s in normalize_user_collection_sources(user) if s.get("enabled", True)])
            elif parsed.path == "/api/training":
                user = self.require_user()
                if not user:
                    return
                self.send_json({"exams": load_training_exams(), "results": load_training_results(), "summary": training_summary()})
            elif parsed.path == "/api/candidates":
                user = self.require_user()
                if not user:
                    return
                self.send_json(candidates_for_user(load_candidates(), user))
            elif parsed.path == "/api/summary":
                if not self.require_user():
                    return
                self.send_json(build_summary(load_candidates()))
            elif parsed.path == "/api/daily-report":
                if not self.require_user():
                    return
                candidates = load_candidates()
                self.send_json(RecruitingAgent().daily_report(candidates))
            elif parsed.path == "/api/job-profiles":
                if not self.require_user():
                    return
                self.send_json(load_job_profiles())
            elif re.match(r"^/api/candidates/[^/]+/templates$", parsed.path):
                if not self.require_user():
                    return
                cid = parsed.path.split("/")[3]
                candidate = find_candidate(load_candidates(), cid)
                if not candidate:
                    self.send_json({"error": "candidate not found"}, HTTPStatus.NOT_FOUND)
                    return
                self.send_json(build_templates(candidate))
            elif re.match(r"^/api/candidates/[^/]+/next-action$", parsed.path):
                if not self.require_user():
                    return
                cid = parsed.path.split("/")[3]
                candidate = find_candidate(load_candidates(), cid)
                if not candidate:
                    self.send_json({"error": "candidate not found"}, HTTPStatus.NOT_FOUND)
                    return
                self.send_json(RecruitingAgent().recommend_next_action(candidate))
            elif parsed.path == "/api/export/candidates.csv":
                if not self.require_user():
                    return
                candidates = load_candidates()
                export_candidates_csv(candidates)
                path = EXPORT_DIR / "candidates.csv"
                body = path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=candidates.csv")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc), "trace": traceback.format_exc()}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        try:
            parsed = urlparse(self.path)
            body = self.read_body()
            if parsed.path == "/api/register":
                try:
                    user = create_user(
                        body.get("username", ""),
                        body.get("password", ""),
                        body.get("role", "hr"),
                        body.get("display_name", ""),
                        body.get("manager_code", ""),
                    )
                    self.send_json({"user": user})
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return
            if parsed.path == "/api/login":
                user = verify_user(body.get("username", ""), body.get("password", ""))
                if not user:
                    self.send_json({"error": "用户名或密码错误"}, HTTPStatus.UNAUTHORIZED)
                    return
                token = create_session(user)
                payload = json.dumps({"user": public_user(user)}, ensure_ascii=False).encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", f"hr_session={token}; Path=/; HttpOnly; SameSite=Lax")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
            if parsed.path == "/api/logout":
                cookie = self.headers.get("Cookie", "")
                token = ""
                for part in cookie.split(";"):
                    if part.strip().startswith("hr_session="):
                        token = part.strip().split("=", 1)[1]
                clear_session(token)
                payload = b'{"ok":true}'
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Set-Cookie", "hr_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return

            user = self.require_user()
            if not user:
                return
            actor = user.get("username")

            if parsed.path == "/api/account":
                try:
                    updated = update_user_account(user.get("id"), body)
                    self.send_json({"user": updated})
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
                return

            if parsed.path == "/api/workflow-rerun":
                if user.get("role") != "manager":
                    self.send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                    return
                candidates = load_candidates()
                changed = 0
                rules = load_workflow_rules()
                for c in candidates:
                    if apply_workflow_automation(c, "rules_rerun", rules):
                        changed += 1
                    c["updated_at"] = now_iso()
                save_candidates(candidates)
                append_event("workflow_rules_rerun", None, {"count": len(candidates), "changed": changed, "rules": rules}, actor=actor)
                self.send_json({"ok": True, "count": len(candidates), "changed": changed})
                return

            if parsed.path == "/api/scan":
                result = scan_resumes(actor=actor, remove_missing=body.get("remove_missing", True))
                append_event("scan_resumes", None, result, actor=actor)
                self.send_json(result)
            elif parsed.path == "/api/resume-collect":
                result = save_collected_resumes(body, actor=actor, user=user)
                self.send_json(result)
            elif parsed.path == "/api/resume-api-collect":
                result = collect_resumes_from_api(body.get("source"), actor=actor, user=user)
                status = HTTPStatus.OK if result.get("ok", True) else HTTPStatus.BAD_REQUEST
                self.send_json(result, status)
            elif parsed.path == "/api/jd-generate":
                result = generate_job_description(body)
                append_event("jd_generated", None, {"title": result.get("title"), "method": result.get("method")}, actor=actor)
                self.send_json(result)
            elif parsed.path == "/api/training/exams/generate":
                result = generate_training_exam(body)
                append_event("training_exam_generated", None, {"title": result.get("title"), "method": result.get("method")}, actor=actor)
                self.send_json(result)
            elif parsed.path == "/api/training/results":
                result = upsert_training_result(body, actor=actor)
                append_event("training_result_saved", None, {"exam": result.get("exam_title"), "student": result.get("student_name"), "score": result.get("score")}, actor=actor)
                self.send_json(result)
            elif parsed.path == "/api/training/results/grade":
                try:
                    result = grade_training_answers(body, actor=actor)
                    append_event("training_result_graded", None, {"exam": result.get("exam_title"), "student": result.get("student_name"), "score": result.get("score")}, actor=actor)
                    self.send_json(result)
                except ValueError as exc:
                    self.send_json({"error": str(exc)}, HTTPStatus.NOT_FOUND)
            elif parsed.path == "/api/score-all":
                profile = pick_profile(body.get("profile_id"))
                candidates = load_candidates()
                for c in candidates:
                    c["match"] = score_candidate(c, profile)
                    c["updated_at"] = now_iso()
                save_candidates(candidates)
                append_event("score_all", None, {"profile": profile.get("name")}, actor=actor)
                self.send_json({"ok": True, "count": len(candidates)})
            elif re.match(r"^/api/candidates/[^/]+/score$", parsed.path):
                cid = parsed.path.split("/")[3]
                profile = pick_profile(body.get("profile_id"))
                candidates = load_candidates()
                c = find_candidate(candidates, cid)
                if not c:
                    self.send_json({"error": "candidate not found"}, HTTPStatus.NOT_FOUND)
                    return
                result = score_candidate(c, profile)
                llm = try_llm_rescore(c, profile)
                if llm and not llm.get("error"):
                    result["llm_review"] = llm
                    result["method"] = "规则匹配 + 大模型复评"
                elif llm and llm.get("error"):
                    result["llm_error"] = llm["error"]
                c["match"] = result
                if body.get("auto_workflow", True):
                    apply_workflow_automation(c, "resume_score")
                c["updated_at"] = now_iso()
                save_candidates(candidates)
                append_event("candidate_scored", cid, {"profile": profile.get("name"), "score": result.get("score")}, actor=actor)
                self.send_json(c)
            elif re.match(r"^/api/candidates/[^/]+/agent-review$", parsed.path):
                cid = parsed.path.split("/")[3]
                candidates = load_candidates()
                c = find_candidate(candidates, cid)
                if not c:
                    self.send_json({"error": "candidate not found"}, HTTPStatus.NOT_FOUND)
                    return
                review = RecruitingAgent().review_candidate(c, body.get("profile_id"))
                c["agent_review"] = review
                c["match"] = {
                    **c.get("match", {}),
                    "score": review.get("score", c.get("match", {}).get("score", 0)),
                    "strengths": review.get("strengths", c.get("match", {}).get("strengths", [])),
                    "risks": review.get("risks", c.get("match", {}).get("risks", [])),
                    "questions": review.get("questions", c.get("match", {}).get("questions", [])),
                    "suggestion": review.get("decision", c.get("match", {}).get("suggestion", "")),
                    "method": review.get("method", "Agent评审"),
                    "scored_at": now_iso(),
                }
                if body.get("auto_workflow", True):
                    apply_workflow_automation(c, "agent_review")
                c["updated_at"] = now_iso()
                save_candidates(candidates)
                append_event("agent_review", cid, {"decision": review.get("decision"), "score": review.get("score")}, actor=actor)
                self.send_json(c)
            elif re.match(r"^/api/candidates/[^/]+/analyze-resume$", parsed.path):
                cid = parsed.path.split("/")[3]
                candidates = load_candidates()
                c = find_candidate(candidates, cid)
                if not c:
                    self.send_json({"error": "candidate not found"}, HTTPStatus.NOT_FOUND)
                    return
                parsed_resume = RecruitingAgent().analyze_resume(c, body.get("profile_id"))
                c["ai_parse"] = parsed_resume
                if parsed_resume.get("target_position"):
                    c["position"] = parsed_resume.get("target_position") or c.get("position")
                if parsed_resume.get("skills"):
                    c["skills"] = parsed_resume.get("skills")
                c["updated_at"] = now_iso()
                save_candidates(candidates)
                append_event("resume_analyzed", cid, {"method": parsed_resume.get("method")}, actor=actor)
                self.send_json(c)
            elif re.match(r"^/api/candidates/[^/]+/group-score$", parsed.path):
                cid = parsed.path.split("/")[3]
                candidates = load_candidates()
                c = find_candidate(candidates, cid)
                if not c:
                    self.send_json({"error": "candidate not found"}, HTTPStatus.NOT_FOUND)
                    return
                result = RecruitingAgent().score_group_interview(c, body.get("text", ""))
                c["group_ai_review"] = result
                c["group_interview"] = {
                    **c.get("group_interview", {}),
                    "status": "已评分",
                    "score": result.get("group_score", ""),
                }
                if body.get("auto_workflow", True):
                    apply_workflow_automation(c, "group_score")
                c["updated_at"] = now_iso()
                save_candidates(candidates)
                append_event("group_scored", cid, {"score": result.get("group_score"), "decision": result.get("decision")}, actor=actor)
                self.send_json(c)
            elif re.match(r"^/api/candidates/[^/]+/interview-plan$", parsed.path):
                cid = parsed.path.split("/")[3]
                candidates = load_candidates()
                c = find_candidate(candidates, cid)
                if not c:
                    self.send_json({"error": "candidate not found"}, HTTPStatus.NOT_FOUND)
                    return
                result = RecruitingAgent().interview_plan(c, body.get("profile_id"))
                c["interview_plan"] = result
                c["updated_at"] = now_iso()
                save_candidates(candidates)
                append_event("interview_plan_generated", cid, {"method": result.get("method")}, actor=actor)
                self.send_json(c)
            elif re.match(r"^/api/candidates/[^/]+/apply-next-action$", parsed.path):
                cid = parsed.path.split("/")[3]
                candidates = load_candidates()
                c = find_candidate(candidates, cid)
                if not c:
                    self.send_json({"error": "candidate not found"}, HTTPStatus.NOT_FOUND)
                    return
                recommendation = RecruitingAgent().recommend_next_action(c)
                if recommendation.get("suggested_stage"):
                    c["stage"] = normalize_stage(recommendation.get("suggested_stage"))
                c["workflow"] = {
                    **c.get("workflow", {}),
                    "auto_enabled": True,
                    "last_trigger": "apply_next_action",
                    "last_reason": recommendation.get("reason") or recommendation.get("action") or "应用下一步推荐",
                    "next_action": workflow_next_action(c.get("stage")),
                    "updated_at": now_iso(),
                }
                c["updated_at"] = now_iso()
                save_candidates(candidates)
                append_event("workflow_next_action_applied", cid, {"stage": c.get("stage"), "recommendation": recommendation}, actor=actor)
                self.send_json(c)
            elif re.match(r"^/api/candidates/[^/]+$", parsed.path):
                cid = parsed.path.split("/")[3]
                candidates = load_candidates()
                c = find_candidate(candidates, cid)
                if not c:
                    self.send_json({"error": "candidate not found"}, HTTPStatus.NOT_FOUND)
                    return
                for key in [
                    "stage", "notes", "final_result", "expected_salary", "arrival_time",
                    "job_intention", "location_preference", "salary_expectation",
                    "availability", "stability_risk", "owner", "talent_pool", "talent_tags",
                    "next_follow_time", "follow_up_priority",
                ]:
                    if key in body:
                        c[key] = body[key]
                if isinstance(body.get("communication_logs"), list):
                    c["communication_logs"] = body["communication_logs"]
                if isinstance(body.get("interviewer_reviews"), list):
                    c["interviewer_reviews"] = body["interviewer_reviews"]
                for key in ["group_interview", "assignment", "hr_interview"]:
                    if key in body and isinstance(body[key], dict):
                        c[key] = body[key]
                if body.get("auto_workflow"):
                    apply_workflow_automation(c, "manual_save")
                c["updated_at"] = now_iso()
                save_candidates(candidates)
                append_event("candidate_updated", cid, body, actor=actor)
                self.send_json(c)
            elif parsed.path == "/api/job-profiles":
                profiles = load_job_profiles()
                profile = body
                if not profile.get("id"):
                    profile["id"] = hashlib.sha1((profile.get("name", "") + now_iso()).encode("utf-8")).hexdigest()[:10]
                profiles = [p for p in profiles if p.get("id") != profile["id"]]
                profiles.append(profile)
                write_json(JOB_PROFILES_FILE, profiles)
                append_event("job_profile_saved", None, {"profile": profile.get("name")}, actor=actor)
                self.send_json(profile)
            elif parsed.path == "/api/app-config":
                if user.get("role") != "manager":
                    self.send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                    return
                config = save_app_config_from_payload(body)
                append_event("app_config_saved", None, {"llm_enabled": config.get("llm_enabled"), "llm_model": config.get("llm_model")}, actor=actor)
                self.send_json(config)
            elif parsed.path == "/api/model-test":
                if user.get("role") != "manager":
                    self.send_json({"error": "forbidden"}, HTTPStatus.FORBIDDEN)
                    return
                config = load_app_config()
                ensure_model_configs(config)
                model = find_model_config(config.get("model_configs", []), body.get("id"))
                if not model:
                    self.send_json({"error": "model not found"}, HTTPStatus.NOT_FOUND)
                    return
                result = test_model_config(model)
                model["status"] = result.get("status", "失败")
                model["last_test"] = result.get("time", now_iso())
                model["last_test_ok"] = result.get("ok", False)
                model["last_test_message"] = result.get("message", "")
                model["available_models"] = result.get("available_models", [])
                model["model_found"] = result.get("model_found", False)
                model["models_error"] = result.get("models_error", "")
                write_json(APP_CONFIG_FILE, config)
                append_event("model_tested", None, {"model": model.get("name"), "status": model.get("status")}, actor=actor)
                self.send_json(result)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self.send_json({"error": str(exc), "trace": traceback.format_exc()}, HTTPStatus.INTERNAL_SERVER_ERROR)


def find_candidate(candidates, cid):
    return next((c for c in candidates if c.get("id") == cid), None)


def pick_profile(profile_id=None):
    profiles = load_job_profiles()
    if profile_id:
        for profile in profiles:
            if profile.get("id") == profile_id:
                return profile
    return profiles[0]


def bootstrap():
    ensure_dirs()
    load_job_profiles()
    load_app_config()
    if not CANDIDATES_FILE.exists():
        scan_resumes()
    else:
        load_candidates()


def main():
    bootstrap()
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "11011"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"{APP_NAME} 已启动: http://{host}:{port}")
    print(f"数据目录: {DATA_DIR}")
    print("按 Ctrl+C 停止服务")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
