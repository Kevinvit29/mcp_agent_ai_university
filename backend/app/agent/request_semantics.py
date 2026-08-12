from app.agent.natural_query import normalize_typos


SCHEMA_PHRASES = {
    "database schema",
    "database structure",
    "database map",
    "table schema",
    "table columns",
    "column names",
    "what tables",
    "list tables",
    "show tables",
    "what data can you access",
    "โครงสร้างฐานข้อมูล",
    "โครงสร้างตาราง",
    "ชื่อตาราง",
    "คอลัมน์",
    "ตารางอะไรบ้าง",
    "เข้าถึงข้อมูลอะไร",
}

TABLE_VIEW_PHRASES = {
    "as a table",
    "in a table",
    "table format",
    "make it a table",
    "put it in a table",
    "show it in table",
    "ทำเป็นตาราง",
    "แสดงเป็นตาราง",
    "ในรูปแบบตาราง",
    "ตารางรายชื่อ",
}

REPORT_WORDS = {
    "report",
    "pdf report",
    "download report",
    "export",
    "รายงาน",
    "ไฟล์รายงาน",
    "ดาวน์โหลดรายงาน",
}

REALTIME_PHRASES = {
    "right now",
    "currently doing",
    "doing now",
    "live location",
    "current location",
    "where are they now",
    "where is he now",
    "where is she now",
    "ตอนนี้กำลังทำอะไร",
    "ตอนนี้อยู่ที่ไหน",
    "ตำแหน่งปัจจุบัน",
}


def request_semantics(message: str) -> dict:
    text = normalize_typos(message or "").lower().strip()

    is_schema_request = (
        any(phrase in text for phrase in SCHEMA_PHRASES)
        or (("column" in text or "columns" in text) and "table" in text)
        or ("คอลัมน์" in text and "ตาราง" in text)
    )
    wants_table = (
        any(phrase in text for phrase in TABLE_VIEW_PHRASES)
        or ("table" in text and not is_schema_request)
        or ("ตาราง" in text and not is_schema_request)
    )
    wants_report = any(word in text for word in REPORT_WORDS)
    is_realtime_request = any(phrase in text for phrase in REALTIME_PHRASES)

    return {
        "is_schema_request": is_schema_request,
        "wants_table": wants_table,
        "wants_report": wants_report,
        "is_realtime_request": is_realtime_request,
    }
