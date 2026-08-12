import re


def has_thai(text: str) -> bool:
    return bool(re.search(r"[\u0E00-\u0E7F]", text or ""))


def enrich_message_for_planning(message: str) -> str:
    """
    Keep original user message, but add English routing hints for the planner.
    This is NOT for final answer. It is only for routing/query planning.
    """
    raw = message or ""
    low = raw.lower()
    hints = []

    if not has_thai(raw):
        return raw

    # Student profile / information
    if re.search(r"\bS\d{3,6}\b", raw, flags=re.I):
        if any(w in raw for w in ["โปรไฟล์", "ข้อมูล", "ประวัติ", "รายละเอียด"]):
            hints.append("student profile information")
        else:
            hints.append("student data")

    # Advisor profile / information
    if re.search(r"\bA\d{3,6}\b", raw, flags=re.I):
        if any(w in raw for w in ["โปรไฟล์", "ข้อมูล", "ประวัติ", "รายละเอียด"]):
            hints.append("advisor profile information")
        else:
            hints.append("advisor data")

    # GPA lower than
    m = re.search(r"(?:gpa|เกรด|จีพีเอ).*?(?:ต่ำกว่า|น้อยกว่า|ไม่ถึง|under|below|less than)\s*(\d+(?:\.\d+)?)", low)
    if m:
        hints.append(f"students with GPA lower than {m.group(1)}")

    # GPA higher than
    m = re.search(r"(?:gpa|เกรด|จีพีเอ).*?(?:สูงกว่า|มากกว่า|above|higher than|more than)\s*(\d+(?:\.\d+)?)", low)
    if m:
        hints.append(f"students with GPA higher than {m.group(1)}")

    # Lowest / highest / ranking
    if any(w in raw for w in ["ต่ำที่สุด", "น้อยที่สุด", "แย่ที่สุด", "อ่อนที่สุด"]):
        hints.append("rank students by lowest GPA")

    if any(w in raw for w in ["สูงที่สุด", "ดีที่สุด", "ท็อป", "top"]):
        hints.append("rank students by highest GPA")

    # Need improvement
    if any(w in raw for w in ["ต้องปรับปรุง", "ควรปรับปรุง", "ต้องพัฒนา", "อ่อน", "เสี่ยง", "ต้องช่วย"]):
        hints.append("students who need academic improvement or support")

    # Limit
    m = re.search(r"(?:ขอ|แสดง|ลิสต์|list|show)?\s*(\d{1,3})\s*(?:คน|รายการ|students|student)?", raw)
    if m:
        hints.append(f"limit {m.group(1)}")

    # Documents
    if any(w in raw for w in ["เอกสาร", "ไฟล์", "pdf", "อัปโหลด", "อัพโหลด", "บทเรียน", "ชีท"]):
        hints.append("uploaded documents, PDF files, or Excel files")

    # Campus/location
    if any(w in raw for w in ["โรงอาหาร", "ห้องสมุด", "อาคาร", "ห้อง", "สำนักงาน", "อยู่ไหน", "ที่ไหน", "แผนที่"]):
        hints.append("campus location or facility information")

    # Database overview
    if any(w in raw for w in ["ฐานข้อมูล", "ตาราง", "โครงสร้าง", "ข้อมูลทั้งหมด", "ระบบมีข้อมูลอะไร"]):
        hints.append("database overview or schema")

    if not hints:
        return raw

    return (
        f"{raw}\n\n"
        f"[English planning hints only, do not answer this part directly: "
        f"{'; '.join(hints)}]"
    )