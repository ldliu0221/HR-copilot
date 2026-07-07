import hashlib
import re
from pathlib import Path

from app.core.constants import ROOT
from app.core.storage import now_iso

def candidate_id_from_file(path):
    raw = str(path.resolve()).encode("utf-8", "ignore")
    return hashlib.sha1(raw).hexdigest()[:12]


def clean_text(text):
    return re.sub(r"\n{3,}", "\n\n", text.replace("\x00", "")).strip()


def extract_pdf_text(path):
    errors = []
    try:
        import pdfplumber

        with pdfplumber.open(str(path)) as pdf:
            return clean_text("\n".join(page.extract_text() or "" for page in pdf.pages)), ""
    except Exception as exc:
        errors.append(f"pdfplumber: {exc}")
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        return clean_text("\n".join(page.extract_text() or "" for page in reader.pages)), ""
    except Exception as exc:
        errors.append(f"pypdf: {exc}")
    return "", "; ".join(errors)


def extract_docx_text(path):
    try:
        from docx import Document

        doc = Document(str(path))
        return clean_text("\n".join(p.text for p in doc.paragraphs if p.text.strip())), ""
    except Exception as exc:
        return "", str(exc)


def extract_resume_text(path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text, err = extract_pdf_text(path)
        return text, err
    if suffix == ".docx":
        return extract_docx_text(path)
    if suffix in [".txt", ".md"]:
        try:
            return clean_text(path.read_text(encoding="utf-8", errors="ignore")), ""
        except Exception as exc:
            return "", str(exc)
    return "", "暂不支持该文件类型"


GENERIC_NAME_WORDS = {
    "个人简历", "简历", "基本信息", "教育背景", "教育经历", "专业技能", "项目经历", "实习经历",
    "工作经历", "校园经历", "自我评价", "求职意向", "个人信息", "联系方式",
}


def guess_from_filename(path):
    stem = Path(path).stem.strip()
    clean = re.sub(r"\s+", " ", stem)
    name = ""
    position = ""
    if clean.lower().startswith("51job_"):
        parts = [p.strip() for p in clean.split("_") if p.strip()]
        if len(parts) >= 2:
            name = parts[1]
        if len(parts) >= 3:
            position = re.split(r"[（(]", parts[2])[0].strip()
    if not name:
        bracket = re.search(r"】\s*([\u4e00-\u9fa5·]{2,12})", clean)
        if bracket:
            name = bracket.group(1)
    if not name:
        match = re.search(r"([\u4e00-\u9fa5·]{2,12})(?:[-_ ]|$)", clean)
        if match:
            name = match.group(1)
    if not position:
        bracket_pos = re.search(r"【([^】_]+)", clean)
        if bracket_pos:
            position = bracket_pos.group(1).split()[0]
    name = re.sub(r"[^\u4e00-\u9fa5·]", "", name).strip()
    if name in GENERIC_NAME_WORDS:
        name = ""
    return {"name": name or clean[:20], "position": position or "无"}


def fallback_resume_text(path, error):
    guessed = guess_from_filename(path)
    return clean_text(
        "\n".join([
            f"姓名：{guessed['name']}",
            f"求职意向：{guessed['position']}",
            f"简历文件：{Path(path).name}",
            "解析状态：仅从文件名导入，原文待解析",
            f"解析失败原因：{error}",
        ])
    )


def pick_name(text, fallback):
    guessed = guess_from_filename(fallback)
    if guessed.get("name") and ("51job_" in Path(fallback).stem or Path(fallback).stem.startswith("【")):
        return guessed["name"]
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    label_match = re.search(r"姓\s*名\s*[:：]\s*([\u4e00-\u9fa5]{2,5})(?=\s|年|性|$)", text)
    if label_match:
        name = label_match.group(1)
        if name not in GENERIC_NAME_WORDS:
            return name
    for i, line in enumerate(lines[:12]):
        if line in ["个人简历", "简历", "Resume", "RESUME", "Personal resume"]:
            continue
        cleaned = re.sub(r"\s+", "", line)
        if cleaned in GENERIC_NAME_WORDS:
            continue
        if 2 <= len(cleaned) <= 5 and re.fullmatch(r"[\u4e00-\u9fa5]+", cleaned):
            return cleaned
        if line in ["个人简历", "简历"] and i + 1 < len(lines):
            next_line = re.sub(r"\s+", "", lines[i + 1])
            if 2 <= len(next_line) <= 5 and re.fullmatch(r"[\u4e00-\u9fa5]+", next_line):
                return next_line
    stem = Path(fallback).stem
    stem_name = re.split(r"[-_ （(]", stem)[0]
    if 2 <= len(stem_name) <= 5 and re.fullmatch(r"[\u4e00-\u9fa5]+", stem_name) and stem_name not in GENERIC_NAME_WORDS:
        return stem_name
    return guessed.get("name") or stem_name or stem


def find_first(pattern, text):
    match = re.search(pattern, text, re.I)
    return match.group(0) if match else ""


def find_phone(text):
    compact = re.sub(r"(?<=\d)[\s-]+(?=\d)", "", text)
    return find_first(r"(?<!\d)1[3-9]\d{9}(?!\d)", compact)


def find_email(text):
    match = re.search(r"([A-Za-z0-9._%+\-\s]{2,80}@[A-Za-z0-9.\-\s]{2,80}\.[A-Za-z]{2,})", text)
    if not match:
        return ""
    return re.sub(r"\s+", "", match.group(1))


def find_labeled_value(text, labels, max_len=30):
    label_pattern = "|".join(labels)
    match = re.search(rf"(?:{label_pattern})\s*[:：]\s*([^\n\r]{{1,{max_len}}})", text)
    if not match:
        return ""
    value = re.split(r"\s{2,}|电话|邮箱|政治面貌|语言能力|籍贯|年龄|性别", match.group(1).strip())[0].strip()
    return value[:max_len]


def find_gender(text):
    match = re.search(r"性\s*别\s*[:：]\s*([男女])", text)
    return match.group(1) if match else ""


def parse_resume(path, text):
    phone = find_phone(text)
    email = find_email(text)
    gender = find_gender(text)
    expected_salary = find_labeled_value(text, ["期望薪资", "薪资要求", "期望月薪"])
    arrival_time = find_labeled_value(text, ["到岗时间", "最快到岗", "可到岗时间", "实习周期"])
    intent_match = re.search(r"(?:求职意向|应聘岗位|目标岗位)[:：]?\s*([^\n]+)", text)
    guessed = guess_from_filename(path)
    position = intent_match.group(1).strip()[:40] if intent_match else guessed.get("position", "无")
    edu = []
    for keyword in ["博士", "硕士", "本科", "大专", "计算机", "人工智能", "软件工程"]:
        if keyword in text and keyword not in edu:
            edu.append(keyword)
    skill_hits = extract_keywords(text)
    return {
        "id": candidate_id_from_file(path),
        "name": pick_name(text, path.name),
        "gender": gender or "无",
        "phone": phone or "无",
        "wechat": phone or "无",
        "email": email or "无",
        "position": position,
        "education": " / ".join(edu[:5]) if edu else "无",
        "skills": skill_hits,
        "expected_salary": expected_salary or "无",
        "arrival_time": arrival_time or "无",
        "source": "本地简历",
        "resume_file": str(path.relative_to(ROOT)),
        "resume_text": text,
        "parse_status": "parsed",
        "parse_error": "",
        "stage": "待沟通",
        "group_interview": {"status": "待定", "score": ""},
        "assignment": {"status": "待定", "score": ""},
        "hr_interview": {"status": "待定", "score": ""},
        "final_result": "待定",
        "match": {},
        "notes": "",
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }


def extract_keywords(text):
    bank = [
        "Python", "Java", "C++", "JavaScript", "HTML", "CSS", "FastAPI", "Django", "Flask",
        "SpringBoot", "Spring AI", "MyBatis", "MySQL", "Redis", "RabbitMQ", "Prometheus", "Grafana",
        "ELK", "Maven", "WebSocket", "SSE", "SQL", "Linux", "Docker", "Git", "LLM", "Prompt",
        "RAG", "MCP", "LangChain", "Milvus", "向量化", "Rerank", "Agent", "机器学习", "深度学习",
        "NLP", "PyTorch", "数据结构", "算法", "接口", "部署",
    ]
    lower = text.lower()
    hits = []
    for word in bank:
        if word.lower() in lower and word not in hits:
            hits.append(word)
    return hits


