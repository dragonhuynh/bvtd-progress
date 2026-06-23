"""CSV và versioning utilities — dùng bởi tất cả scripts khác."""
import base64
import csv
import io
import json
import re
import socket
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
TASKS_CSV = DATA / "tasks.csv"
TASKS_INDEX = DATA / "tasks_index.json"
VERSIONS_JSON = DATA / "report_versions.json"

FIELDNAMES = [
    "id", "ten_dau_viec", "nhom", "phong_chinh", "phong_phoi_hop",
    "bat_dau", "ket_thuc", "trang_thai", "so_lan_nhac",
    "ghi_chu", "nguon_van_ban", "dinh_ky",
    # Chỉ đạo PGĐ (TS.BS. Phạm Thanh Hải) — lưu cấu trúc để chức năng nhắc việc đọc
    "cd_noi_dung", "cd_phu_trach", "cd_deadline", "cd_ngay"
]

# Các cột chỉ đạo PGĐ — dùng chung cho load/save/apply
CD_FIELDS = ("cd_noi_dung", "cd_phu_trach", "cd_deadline", "cd_ngay")

# Từ khóa xác định task định kỳ (lặp lại thường xuyên, không bao giờ "xong")
_DINH_KY_PATTERNS = re.compile(
    r"hàng\s+(tuần|ngày|tháng|quý)"
    r"|mỗi\s+(tuần|ngày|tháng|quý)"
    r"|định\s*kỳ\s+(hàng|mỗi)"
    r"|\d+\s*lần\s*/\s*(ngày|tuần|tháng)",
    re.IGNORECASE
)

def detect_dinh_ky(ten: str) -> bool:
    return bool(_DINH_KY_PATTERNS.search(ten))

def save_directive_fields(task: dict, p: dict, today: str) -> None:
    """Ghi cấu trúc chỉ đạo PGĐ vào task: công việc / phụ trách / deadline / ngày.
    Dùng cho chức năng nhắc việc sau này (đọc cd_deadline + cd_phu_trach)."""
    pt = p.get("phu_trach") or []
    if isinstance(pt, list):
        pt = "|".join(str(x).strip() for x in pt if str(x).strip())
    if p.get("noi_dung"):
        task["cd_noi_dung"] = p["noi_dung"]
    if pt:
        task["cd_phu_trach"] = pt
    if p.get("deadline"):
        task["cd_deadline"] = p["deadline"]
    task["cd_ngay"] = p.get("at") or today

# ── Nhóm công tác ──────────────────────────────────────────────────────────────

NHOM_LABELS = {
    "hanh_chanh": "Công tác Hành chánh quản trị",
    "chuyen_mon": "Công tác Chuyên môn",
    "quan_ly_khac": "Công tác quản lý khác",
}

_NHOM_PHONG = {
    "hanh_chanh": {"HCQT", "VTTBYT"},
    "chuyen_mon": {"Điều dưỡng", "XN", "KSNK", "YHCT", "PHCT", "RHM", "Nội", "Ngoại", "Nhi", "Mắt", "TMH"},
    "quan_ly_khac": {"KHTH", "CNTT", "CSKH", "TCKT", "CTXH", "Dược"},
}

_NHOM_KEYWORDS = {
    "hanh_chanh": [
        "lắp đặt", "di chuyển", "sửa chữa", "tháo dỡ", "khảo sát", "đo lường",
        "bổ sung", "thay thế", "bố trí", "mặt bằng", "cơ sở vật chất", "máy lạnh",
        "ghế", "tủ", "giường", "bàn khám", "TV", "phòng máy", "hành lang", "cửa hông",
        "thông vách", "WC", "sảnh", "kho",
    ],
    "chuyen_mon": [
        "quy trình khám", "lấy máu", "kỹ thuật", "điều trị", "thủ thuật",
        "5S", "kiểm soát nhiễm khuẩn", "KSNK", "poster", "soi", "siêu âm",
        "xét nghiệm", "châm cứu", "massage", "CT", "X-quang", "ECG",
        "Nội", "Ngoại", "Nhi", "BHYT điều trị",
    ],
    "quan_ly_khac": [
        "báo cáo", "kế hoạch", "hợp đồng", "BHYT", "phần mềm", "hệ thống",
        "in toa", "bảng hướng dẫn", "luồng xe", "thiết kế bảng", "tờ trình",
        "họp thống nhất", "rà soát điều kiện", "CSKH",
    ],
}


def classify_nhom(ten_dau_viec: str, phong_chinh: str) -> str:
    """Phân loại task vào 1 trong 3 nhóm dựa trên phòng và từ khóa."""
    ten_lower = ten_dau_viec.lower()

    # Ưu tiên 1: từ khóa đặc trưng
    for nhom, keywords in _NHOM_KEYWORDS.items():
        if any(kw.lower() in ten_lower for kw in keywords):
            return nhom

    # Ưu tiên 2: phòng chính
    for nhom, phongs in _NHOM_PHONG.items():
        if phong_chinh in phongs:
            return nhom

    return "quan_ly_khac"

TRANG_THAI = {
    "da_hoan_thanh": "Đã hoàn thành",
    "dang_thuc_hien": "Đang thực hiện",
    "tre_deadline": "Trễ deadline",
}

# ── Update log ─────────────────────────────────────────────────────────────────

UPDATE_LOG = DATA / "update_log.csv"

LOG_HEADERS = [
    "ngay_cap_nhat", "task_id", "ten_dau_viec", "phong_chinh",
    "phong_bao_cao", "user", "trang_thai_cu", "trang_thai_moi",
    "ngay_hoan_thanh", "ghi_chu", "nguon", "may", "ip",
]


def _get_machine_info() -> tuple[str, str]:
    try:
        host = socket.gethostname()
        ip = socket.gethostbyname(host)
    except Exception:
        host, ip = "—", "—"
    return host, ip


def _migrate_log_if_needed() -> None:
    """Thêm cột may, ip vào update_log.csv cũ nếu chưa có."""
    if not UPDATE_LOG.exists():
        return
    content = UPDATE_LOG.read_text(encoding="utf-8")
    if not content.strip() or "may" in content.split("\n")[0]:
        return
    rows = list(csv.DictReader(io.StringIO(content)))
    with UPDATE_LOG.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_HEADERS, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(rows)


def append_update_log(rows: list[dict]) -> None:
    """Ghi rows vào update_log.csv (append, tự tạo header nếu chưa có)."""
    _migrate_log_if_needed()
    host, ip = _get_machine_info()
    for r in rows:
        r.setdefault("may", host)
        r.setdefault("ip", ip)
    write_header = not UPDATE_LOG.exists()
    with UPDATE_LOG.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_HEADERS, extrasaction="ignore", restval="")
        if write_header:
            w.writeheader()
        w.writerows(rows)


# ── Shared utilities ──────────────────────────────────────────────────────────

def normalize_source_name(name: str) -> str:
    """Normalize date in source names to dd/mm/yyyy (4-digit year)."""
    m = re.search(r'\b(\d{4})-(\d{2})-(\d{2})\b', name)
    if m:
        return name[:m.start()] + f"{m.group(3)}/{m.group(2)}/{m.group(1)}" + name[m.end():]
    m = re.search(r'\b(\d{2})/(\d{2})/(\d{2})\b', name)
    if m:
        return name[:m.start()] + f"{m.group(1)}/{m.group(2)}/20{m.group(3)}" + name[m.end():]
    return name


def _logo_data_uri() -> str:
    for name in ("logo-tudu-footer.png", "logo-tudu.png"):
        p = ROOT / name
        if p.exists():
            return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
    return ""


# ── JSON helpers ──────────────────────────────────────────────────────────────

def load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)

def save_json(path: Path, data: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ── CSV helpers ───────────────────────────────────────────────────────────────

def load_tasks() -> list[dict]:
    if not TASKS_CSV.exists():
        return []
    with open(TASKS_CSV, newline="", encoding="utf-8") as f:
        tasks = list(csv.DictReader(f))
    for t in tasks:
        t.setdefault("dinh_ky", "0")
        for c in CD_FIELDS:
            t.setdefault(c, "")
    return tasks

def save_tasks(tasks: list[dict]) -> None:
    with open(TASKS_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(tasks)
    _rebuild_index(tasks)


def _rebuild_index(tasks: list[dict]) -> dict:
    """Cập nhật tasks_index.json — file nhỏ để /scan đọc thay vì toàn bộ CSV."""
    nums = []
    for t in tasks:
        tid = t.get("id", "")
        raw = tid[1:] if tid.upper().startswith("T") else tid
        try:
            nums.append(int(raw))
        except ValueError:
            pass
    index = {
        "next_id_num": (max(nums) + 1) if nums else 1,
        "total": len(tasks),
        "titles": [t.get("ten_dau_viec", "") for t in tasks],
        "updated": date.today().isoformat(),
    }
    save_json(TASKS_INDEX, index)
    return index


def load_tasks_index() -> dict:
    """Đọc index nhỏ — dùng trong /scan thay vì load_tasks() toàn bộ."""
    if not TASKS_INDEX.exists():
        return _rebuild_index(load_tasks())
    return load_json(TASKS_INDEX)

def next_id(tasks: list[dict]) -> str:
    if not tasks:
        return "T001"
    nums = []
    for t in tasks:
        tid = t["id"]
        raw = tid[1:] if tid.upper().startswith("T") else tid
        try:
            nums.append(int(raw))
        except ValueError:
            pass
    return f"T{max(nums)+1:03d}" if nums else "T001"

def append_task(row: dict) -> str:
    tasks = load_tasks()
    row["id"] = next_id(tasks)
    row.setdefault("so_lan_nhac", "1")
    row.setdefault("ghi_chu", "")
    tasks.append(row)
    save_tasks(tasks)
    return row["id"]

def append_tasks_batch(rows: list[dict]) -> list[str]:
    """Thêm nhiều task 1 lần — tránh đọc/ghi CSV N lần trong vòng lặp."""
    if not rows:
        return []
    tasks = load_tasks()
    ids = []
    for row in rows:
        row["id"] = next_id(tasks)
        row.setdefault("so_lan_nhac", "1")
        row.setdefault("ghi_chu", "")
        tasks.append(row)
        ids.append(row["id"])
    save_tasks(tasks)
    return ids

def update_task(task_id: str, updates: dict) -> bool:
    tasks = load_tasks()
    for t in tasks:
        if t["id"] == task_id:
            t.update(updates)
            save_tasks(tasks)
            return True
    return False

def auto_mark_overdue(tasks: list[dict]) -> list[str]:
    """Đánh dấu trễ deadline tự động. Trả về list id đã thay đổi."""
    today = date.today().isoformat()
    changed = []
    for t in tasks:
        if (t["trang_thai"] == "dang_thuc_hien"
                and t.get("dinh_ky", "0") != "1"   # task định kỳ không bao giờ trễ
                and t["ket_thuc"]
                and t["ket_thuc"] < today):
            t["trang_thai"] = "tre_deadline"
            changed.append(t["id"])
    return changed


# ── Versioning ─────────────────────────────────────────────────────────────────

def bump_version(loai: str, thay_doi: list[str]) -> str:
    """
    loai: "parse" → tăng major; "check" → tăng minor.
    Trả về version string mới.
    """
    v = load_json(VERSIONS_JSON)
    cur = v.get("version", "0.0")
    major, minor = (int(x) for x in cur.split("."))
    new_ver = f"{major+1}.0" if loai == "parse" else f"{major}.{minor+1}"

    entry = {
        "version": new_ver,
        "ngay": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "loai": loai,
        "thay_doi": thay_doi,
    }
    v["history"].insert(0, entry)
    v["history"] = v["history"][:50]
    v["version"] = new_ver
    save_json(VERSIONS_JSON, v)
    return new_ver

def current_version() -> str:
    v = load_json(VERSIONS_JSON)
    return v.get("version", "0.0")

def recent_history(n: int = 10) -> list[dict]:
    v = load_json(VERSIONS_JSON)
    return v.get("history", [])[:n]


# ── Parsed files tracker ───────────────────────────────────────────────────────

PARSED_TXT = DATA / "parsed_files.txt"

def get_parsed_files() -> set[str]:
    if not PARSED_TXT.exists():
        return set()
    return set(PARSED_TXT.read_text(encoding="utf-8").splitlines())

def mark_parsed(filename: str) -> None:
    parsed = get_parsed_files()
    parsed.add(filename)
    PARSED_TXT.write_text("\n".join(sorted(parsed)), encoding="utf-8")
