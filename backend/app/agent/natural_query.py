import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

TYPO_REPLACEMENTS = {
    # question words / casual
    "wht": "what",
    "wat": "what",
    "whats": "what is",
    "whts": "what is",
    "pls": "please",
    "plz": "please",
    "u": "you",
    "ur": "your",

    # student data typos
    "gade": "grade",
    "grde": "grade",
    "gard": "grade",
    "graed": "grade",
    "grad": "grade",
    "garade": "grade",
    "scroe": "score",
    "socre": "score",
    "subjet": "subject",
    "subjct": "subject",
    "subjec": "subject",
    "studen": "student",
    "studnet": "student",
    "porfile": "profile",
    "profle": "profile",
    "prfile": "profile",
    "infomation": "information",
    "infromation": "information",
    "bisness": "business",
    "buisness": "business",
    "bussiness": "business",
    "busines": "business",
    "bisnes": "business",

    # document / report typos
    "re prot": "report",
    "re port": "report",
    "repo rt": "report",
    "repot": "report",
    "reprot": "report",
    "rport": "report",
    "writting": "writing",
    "writng": "writing",
    "wrting": "writing",
    "pdf beside": "uploaded pdfs",
    "pdf besides": "uploaded pdfs",

    # Common Thai typing/spelling slips used in chat and file questions.
    "เกรดด": "เกรด",
    "เกรต": "เกรด",
    "เกรดเฉลีย": "เกรดเฉลี่ย",
    "คะเเนน": "คะแนน",
    "คะแนนน": "คะแนน",
    "วิช่า": "วิชา",
    "เอกสารร": "เอกสาร",
    "ฟายล์": "ไฟล์",
    "เอ๊กเซล": "เอ็กเซล",
    "เอ็กเซลล์": "เอ็กเซล",
    "อธิบายย": "อธิบาย",
    "สรุบบ": "สรุป",
    "รายงาย": "รายงาน",
    "นักศีกษา": "นักศึกษา",
    "หล้กสูตร": "หลักสูตร",
    "ละเมิ้ด": "ละเมิด",
}

GRADE_WORDS = {
    "grade", "grades", "score", "scores", "gpa", "mark", "marks", "result", "results",
    "subject", "subjects", "course", "courses", "class", "classes",
    "เกรด", "คะแนน", "วิชา", "เกรดเฉลี่ย",
}
PROFILE_WORDS = {
    "profile", "information", "info", "record", "detail", "details", "data", "email", "status", "program", "major", "id",
    "ข้อมูล", "โปรไฟล์", "ข้อมูลส่วนตัว", "รายละเอียด", "สถานะ", "อีเมล", "หลักสูตร",
}
SELF_WORDS = {"my", "me", "mine", "own", "i", "ฉัน", "ผม", "เรา", "ของฉัน", "ของผม", "ตัวเอง"}
DOCUMENT_WORDS = {
    "pdf", "document", "file", "excel", "xlsx", "xls", "csv", "spreadsheet", "sheet", "dataset", "upload", "uploaded", "stored", "table", "rows", "columns", "summary", "summarize", "explain", "report",
    "writing", "lesson", "material", "assignment", "homework", "notes", "worksheet", "policy", "announcement",
    "เอกสาร", "ไฟล์", "อัปโหลด", "ตาราง", "ชีต", "เอ็กเซล", "สรุป", "รายงาน", "เขียน", "บทเรียน",
}


def normalize_typos(text: str) -> str:
    value = (text or "").lower()
    value = value.replace("_", " ").replace("-", " ")
    # Replace phrase typos first.
    for wrong, right in sorted(TYPO_REPLACEMENTS.items(), key=lambda x: len(x[0]), reverse=True):
        value = re.sub(rf"(?<![a-z0-9]){re.escape(wrong)}(?![a-z0-9])", right, value)
    value = re.sub(r"\s+", " ", value).strip()
    return value


def tokens(text: str) -> List[str]:
    return re.findall(r"[a-z0-9\u0E00-\u0E7F]+", normalize_typos(text))


def fuzzy_has_word(text: str, word_set: set[str], threshold: float = 0.78) -> bool:
    ts = tokens(text)
    for token in ts:
        if token in word_set:
            return True
        if len(token) >= 4:
            for word in word_set:
                if re.match(r"^[a-z0-9]{4,}$", word) and SequenceMatcher(None, token, word).ratio() >= threshold:
                    return True
    return False


def has_any(text: str, word_set: set[str]) -> bool:
    nt = normalize_typos(text)
    token_set = set(tokens(nt))
    for word in word_set:
        w = normalize_typos(word)
        if not w:
            continue
        # Multi-word phrases are allowed as contained phrases.
        if " " in w:
            if w in nt:
                return True
            continue
        # Thai words do not use spaces reliably, so substring match is okay for Thai only.
        if re.search(r"[\u0E00-\u0E7F]", w):
            if w in nt:
                return True
            continue
        # English words must match tokens. This prevents false positives like
        # "file" inside "profile", which previously routed profile questions to PDFs.
        if w in token_set:
            return True
    return fuzzy_has_word(nt, word_set)


def is_greeting(text: str) -> bool:
    nt = normalize_typos(text).strip(" .!?\t\n")
    return nt in {"hi", "hello", "hey", "yo", "good morning", "good afternoon", "good evening", "สวัสดี", "หวัดดี"}


def looks_like_self_data_request(text: str) -> bool:
    nt = normalize_typos(text)
    # Student often says "my grade" with typo. This must always be student data, not PDF.
    if any(w in nt for w in SELF_WORDS) and (has_any(nt, GRADE_WORDS) or has_any(nt, PROFILE_WORDS)):
        return True
    # Short direct messages after logging in can omit "my" but still refer to logged-in student.
    short = len(nt.split()) <= 5
    if short and (has_any(nt, {"gpa", "grade", "grades", "score", "scores"}) or "เกรด" in nt):
        return True
    return False


def looks_like_profile_request(text: str) -> bool:
    nt = normalize_typos(text)
    return any(w in nt for w in SELF_WORDS) and has_any(nt, PROFILE_WORDS)


def looks_like_document_request(text: str, history: str = "") -> bool:
    nt = normalize_typos(text)
    combined = normalize_typos((history or "") + "\n" + nt)
    if has_any(nt, DOCUMENT_WORDS):
        return True
    # Follow-up after a document context.
    if len(nt.split()) <= 5 and has_any(combined, DOCUMENT_WORDS):
        return nt in {"really", "then", "again", "more", "detail", "details", "explain", "this", "that", "it", "why"} or any(
            w in nt for w in ["beside", "besides", "available", "upload", "uploads", "subject"]
        )
    return False


def document_list_request(text: str) -> bool:
    nt = normalize_typos(text)
    list_words = {
        "list", "name", "names", "already", "available", "beside", "besides", "upload", "uploads", "uploaded", "stored",
        "all pdf", "all excel", "all files", "subject upload", "subject uploads", "what pdf", "which pdf", "what excel", "which excel", "documents yet", "pdfs yet", "excel yet",
        "รายชื่อ", "ชื่อไฟล์", "มีอะไร", "ไฟล์อะไร", "เอกสารอะไร",
    }
    return any(w in nt for w in list_words)


def friendly_clean_query(text: str) -> str:
    return normalize_typos(text) or (text or "")


def recent_topic(history: Optional[List[Dict[str, Any]]]) -> str:
    if not history:
        return ""
    joined = "\n".join(str(item.get("content", "")) for item in history[-8:])
    if has_any(joined, DOCUMENT_WORDS):
        return "documents"
    if has_any(joined, GRADE_WORDS):
        return "student_data"
    if has_any(joined, PROFILE_WORDS):
        return "student_data"
    return ""
