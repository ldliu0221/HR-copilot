import sys
from pathlib import Path

APP_NAME = "AI 招聘流程 Copilot"
ROOT = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
RESUME_DIRS = [DATA_DIR / "简历", DATA_DIR / "resumes"]
SUPPORTED_RESUME_SUFFIXES = [".pdf", ".docx", ".txt", ".md"]
STATUS_DIR = DATA_DIR / "status"
CONFIG_DIR = DATA_DIR / "config"
EXPORT_DIR = DATA_DIR / "exports"
LEGACY_STATUS_FILE = DATA_DIR / "legacy_status" / "状态.xlsx"

CANDIDATES_FILE = STATUS_DIR / "candidates.json"
EVENTS_FILE = STATUS_DIR / "events.jsonl"
STATUS_CSV_FILE = STATUS_DIR / "状态.csv"
JOB_PROFILES_FILE = CONFIG_DIR / "job_profiles.json"
APP_CONFIG_FILE = CONFIG_DIR / "app_config.json"
USERS_FILE = CONFIG_DIR / "users.json"
SESSIONS_FILE = CONFIG_DIR / "sessions.json"
TRAINING_EXAMS_FILE = STATUS_DIR / "training_exams.json"
TRAINING_RESULTS_FILE = STATUS_DIR / "training_results.json"

PIPELINE = ["待沟通", "已沟通", "待群面", "已群面", "待提交群面作业", "已提交群面", "待最终面", "已最终面", "淘汰", "通过"]
AUTO_WORKFLOW_RULES = {
    "resume_pass_score": 70,
    "resume_watch_score": 55,
    "group_pass_score": 70,
    "assignment_pass_score": 70,
    "hr_pass_score": 70,
}
WORKFLOW_RULE_LABELS = {
    "resume_pass_score": "简历推进群面线",
    "resume_watch_score": "简历待观察线",
    "group_pass_score": "群面推进作业线",
    "assignment_pass_score": "作业推进终面线",
    "hr_pass_score": "HR面通过线",
}
STAGE_ALIASES = {
    "待二筛": "待群面",
    "待约面": "待最终面",
    "已约面": "待最终面",
    "已面试": "已最终面",
    "待反馈": "已最终面",
    "已淘汰": "淘汰",
    "已录用": "通过",
}
DEFAULT_RESUME_PARSE_PROMPT = (
    "你是招聘简历分析智能体。请只基于简历原文和岗位标准进行分析，不要编造简历中没有的信息。"
    "输出 JSON，字段包括 analysis_summary、education_analysis、skill_analysis、project_analysis、"
    "experience_analysis、risk_points、follow_up_questions、conclusion、confidence。"
)
DEFAULT_CANDIDATE_REVIEW_PROMPT = (
    "你是招聘初筛评审智能体。请根据岗位标准和候选人简历，评估候选人与岗位的适配度。"
    "输出 JSON，字段包括 suitability_score、suitability_level、fit_summary、matched_evidence、"
    "gap_risks、questions、decision、next_stage、reason。suitability_score 为 0-100。"
)
DEFAULT_JD_GENERATE_PROMPT = (
    "你是资深招聘专家和JD撰写助手。请根据输入生成专业、清晰、可发布的岗位JD，并同步抽取可用于简历评分的岗位标准。"
    "如果输入包含 knowledge/行业知识库/RAG上下文，必须把其中的业务术语、真实项目、行业要求融入职位描述、职责、要求、加分项和面试关注点，避免模板化。"
    "生成内容必须覆盖职位名称、工作地点、部门、工作类型、薪资范围、职位描述、岗位职责、任职要求、公司介绍、福利待遇、工作亮点。"
    "输出 JSON，字段包括 title、city、department、work_type、salary、summary、responsibilities、requirements、company_intro、benefits、highlights、bonus_points、interview_focus、skills、abilities、risk_keywords、pass_score。"
)
DEFAULT_NEXT_ACTION_PROMPT = "你是招聘流程推进智能体。请基于候选人状态输出 action、reason、message、suggested_stage、priority。"
DEFAULT_GROUP_SCORE_PROMPT = "你是群面评分智能体。请输出 group_score、dimension_scores、evaluation、decision、reason、risks。"
DEFAULT_INTERVIEW_PLAN_PROMPT = (
    "你是资深技术面试官和招聘面试设计专家。请根据候选人简历、岗位标准和匹配评分，输出个性化面试方案 JSON。"
    "字段包括 interview_goal、candidate_summary、focus_areas、question_sections、project_deep_dive、risk_checks、scoring_rubric、schedule、decision_signals、interviewer_notes。"
    "question_sections 每项包含 title、purpose、questions。"
)
DEFAULT_DAILY_REPORT_PROMPT = "你是招聘日报智能体。请输出 summary、risks、priorities、actions、bottlenecks。"
DEFAULT_TRAINING_EXAM_PROMPT = (
    "你是企业HR培训考试设计专家。请根据培训对象、考试主题、难度、技能点和说明，输出 JSON。"
    "字段包括 title、target、topic、difficulty、duration、total_score、pass_score、description、sections、questions、scoring_rules。"
    "questions 每项包含 id、type、score、stem、options、answer、analysis。"
)
DEFAULT_EXAM_GRADING_PROMPT = (
    "你是企业培训考试阅卷专家。请根据试卷、标准答案和考生答案输出 JSON，字段包括 score、total_score、status、details、comment、review_required。"
    "details 每项包含 id、score、reason。复杂语义题如果不确定请标记 review_required=true。"
)
DEFAULT_CANDIDATE_RESCORE_PROMPT = "你是招聘初筛助手，请输出 JSON，字段包含 score, strengths, risks, questions, suggestion。"
