"""
generate_dashboard.py — Sinh dashboard.html theo phong cach project management hien dai
"""
import csv
import json
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict
import sys
sys.path.insert(0, str(Path(__file__).parent))
from tracker import load_tasks, auto_mark_overdue, normalize_source_name, _logo_data_uri

ROOT = Path(__file__).parent.parent

DEPT_NORMALIZE = {
    "Bs Hoàng":          "KHTH",
    "Bảo vệ":            "HCQT",
    "Đoàn Thanh niên":   "Đoàn Thanh Niên",
    "ĐTN":               "Đoàn Thanh Niên",
    "Điều dưỡng trưởng": "Điều dưỡng",
    "K.CC":              "K.Cấp cứu",
    "CC":                "K.Cấp cứu",
    "K.XN":              "XN",
    "Khoa Dược":         "Dược",
    "K.PHCN":            "K.PHCN",
}

def normalize_dept(d: str) -> str:
    return DEPT_NORMALIZE.get(d, d)


def extract_date_key(name: str) -> str | None:
    """Extract YYMMDD from a name containing dd/mm/yyyy or dd/mm/yy pattern."""
    m = re.search(r'\b(\d{2})/(\d{2})/(\d{4})\b', name)
    if m:
        return m.group(3)[2:] + m.group(2) + m.group(1)
    m = re.search(r'\b(\d{2})/(\d{2})/(\d{2})\b', name)
    if m:
        return m.group(3) + m.group(2) + m.group(1)
    return None


def load_json_file(p: Path) -> dict:
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def load_update_log() -> list[dict]:
    log_path = ROOT / "data" / "update_log.csv"
    if not log_path.exists():
        return []
    with log_path.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    rows.reverse()  # newest first
    return rows


def build_pdf_map() -> dict:
    """Scan bien-ban-da-ky/ and return {YYMMDD: filename} (first match wins)."""
    folder = ROOT / "bien-ban-da-ky"
    pdf_map = {}
    if not folder.exists():
        return pdf_map
    for f in sorted(folder.glob("*.pdf")):
        prefix = f.name[:6]
        if prefix.isdigit() and prefix not in pdf_map:
            pdf_map[prefix] = f.name
    return pdf_map


# ── Stats computation ──────────────────────────────────────────────────────────

def compute(tasks):
    auto_mark_overdue(tasks)

    total = len(tasks)
    done  = sum(1 for t in tasks if t["trang_thai"] == "da_hoan_thanh")
    active = sum(1 for t in tasks if t["trang_thai"] == "dang_thuc_hien")
    late  = sum(1 for t in tasks if t["trang_thai"] == "tre_deadline")

    # Monthly tasks added (last 8 months)
    monthly = defaultdict(int)
    for t in tasks:
        if t.get("bat_dau") and len(t["bat_dau"]) >= 7:
            monthly[t["bat_dau"][:7]] += 1
    month_keys = sorted(monthly.keys())[-8:]

    # Department breakdown — normalized
    dept = defaultdict(lambda: {"total": 0, "done": 0, "active": 0, "late": 0})
    for t in tasks:
        raw = (t.get("phong_chinh") or "Khác").strip()
        d = normalize_dept(raw)
        dept[d]["total"] += 1
        s = t["trang_thai"]
        if s == "da_hoan_thanh":    dept[d]["done"] += 1
        elif s == "dang_thuc_hien": dept[d]["active"] += 1
        else:                        dept[d]["late"] += 1

    dept_list = sorted(
        [{"name": k, **v} for k, v in dept.items()],
        key=lambda x: -x["total"]
    )

    # Nhom breakdown
    nhom = defaultdict(int)
    for t in tasks:
        nhom[t.get("nhom") or "quan_ly_khac"] += 1

    urgent = sorted(
        [t for t in tasks if t["trang_thai"] == "tre_deadline"],
        key=lambda t: t.get("ket_thuc") or "9999"
    )

    # Repeat tasks (so_lan_nhac >= 2)
    repeat_tasks = sorted(
        [t for t in tasks if int(t.get("so_lan_nhac") or "1") >= 2],
        key=lambda t: -int(t.get("so_lan_nhac") or "1")
    )

    # Source documents — normalize date format in names
    sources = {}
    for t in tasks:
        src_raw = (t.get("nguon_van_ban") or "").strip()
        src = normalize_source_name(src_raw) if src_raw else ""
        if src and src not in sources:
            sources[src] = {"date": t.get("bat_dau", ""), "count": 0}
        if src:
            sources[src]["count"] += 1
    src_list = sorted(sources.items(), key=lambda x: x[1]["date"])
    _pdf_map = build_pdf_map()

    # Build task_id → last_reminder_date / cac_bien_ban from repeat_alerts.json
    _repeat_data = load_json_file(ROOT / "data" / "repeat_alerts.json")
    _task_last_reminder: dict[str, str] = {}
    _task_bien_ban: dict[str, list] = {}
    for _dept_alerts in _repeat_data.get("alerts", {}).values():
        for _alert in _dept_alerts:
            _bbs = _alert.get("cac_bien_ban", [])
            _last_date = None
            for _bb in reversed(_bbs):
                _m = re.search(r'\b(\d{2})/(\d{2})/(\d{4})\b', _bb)
                if _m:
                    _last_date = f"{_m.group(3)}-{_m.group(2)}-{_m.group(1)}"
                    break
            for _tid in _alert.get("task_ids", []):
                _key = str(int(_tid))
                if _last_date and (_key not in _task_last_reminder or _last_date > _task_last_reminder[_key]):
                    _task_last_reminder[_key] = _last_date
                if _key not in _task_bien_ban:
                    _task_bien_ban[_key] = _bbs

    # Slim tasks for JS — normalized dept
    tasks_slim = [
        {
            "id":      t["id"],
            "ten":     t["ten_dau_viec"],
            "nhom":    t.get("nhom") or "quan_ly_khac",
            "phong":   normalize_dept((t.get("phong_chinh") or "").strip()),
            "phoi_hop": (t.get("phong_phoi_hop") or "").replace("|", ", "),
            "bat_dau": t.get("bat_dau") or "",
            "ket_thuc": t.get("ket_thuc") or "",
            "tt":      t["trang_thai"],
            "dk":      t.get("dinh_ky", "0"),
            "nhac":    t.get("so_lan_nhac") or "1",
            "ghi_chu": t.get("ghi_chu") or "",
            "nguon":   normalize_source_name((t.get("nguon_van_ban") or "").strip()),
            "last_reminder": _task_last_reminder.get(t["id"], ""),
            "cac_bien_ban":  _task_bien_ban.get(t["id"], []),
        }
        for t in tasks
    ]

    # Today label in Vietnamese
    today_obj = datetime.now()
    wd_vn = ["Thứ Hai","Thứ Ba","Thứ Tư","Thứ Năm","Thứ Sáu","Thứ Bảy","Chủ Nhật"]
    today_vn = f"{wd_vn[today_obj.weekday()]}, {today_obj.strftime('%d/%m/%Y')}"

    return {
        "total": total, "done": done, "active": active, "late": late,
        "rate": round(done / total * 100) if total else 0,
        "months": month_keys,
        "monthly_counts": [monthly[m] for m in month_keys],
        "dept": dept_list,
        "nhom": dict(nhom),
        "urgent": [
            {"id": t["id"], "ten": t["ten_dau_viec"],
             "phong": normalize_dept(t.get("phong_chinh", "")),
             "ket_thuc": t.get("ket_thuc", ""), "nhac": t.get("so_lan_nhac", "1")}
            for t in urgent
        ],
        "repeats": [
            {"id": t["id"], "ten": t["ten_dau_viec"],
             "phong": normalize_dept(t.get("phong_chinh", "")),
             "nhom": t.get("nhom") or "quan_ly_khac",
             "nhac": t.get("so_lan_nhac", "1"),
             "ket_thuc": t.get("ket_thuc", ""),
             "tt": t["trang_thai"],
             "nguon": normalize_source_name((t.get("nguon_van_ban") or "").strip()),
             "cac_bien_ban": _task_bien_ban.get(t["id"], []),
             "last_reminder": _task_last_reminder.get(t["id"], "")}
            for t in repeat_tasks
        ],
        "sources": [
            {"name": k, "count": v["count"], "date": v["date"],
             "pdf": _pdf_map.get(extract_date_key(k))}
            for k, v in src_list
        ],
        "tasks": tasks_slim,
        "generated": datetime.now().strftime("%d/%m/%Y %H:%M"),
        "today": today_obj.strftime("%d/%m/%Y"),
        "today_vn": today_vn,
        "version": load_json_file(ROOT / "data" / "report_versions.json").get("version", "—"),
    }


# ── HTML template ──────────────────────────────────────────────────────────────

def build_html(data: dict) -> str:
    data_json = json.dumps(data, ensure_ascii=False).replace('</script>', r'<\/script>')
    fb_cfg = load_json_file(ROOT / "data" / "firebase_config.json")
    fb_cfg_json = json.dumps(fb_cfg, ensure_ascii=False)
    logo_uri = _logo_data_uri()

    return """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BVTD CS2 — Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Be+Vietnam+Pro:wght@400;500;600;700;800&family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
<script defer src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script defer src="https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js"></script>
<script defer src="https://www.gstatic.com/firebasejs/10.12.0/firebase-database-compat.js"></script>
<style>
:root {
  --bg:      #EBF4FF;
  --sidebar: #0D3B7A;
  --accent:  #1A5CA8;
  --accent2: #134489;
  --pink:    #F06EA3;
  --pink2:   #D8578A;
  --white:   #ffffff;
  --text:    #1a202c;
  --muted:   #718096;
  --border:  #dce8f5;
  --green:   #48bb78;
  --blue:    #4299e1;
  --red:     #f56565;
  --orange:  #ed8936;
  --purple:  #9f7aea;
  --r: 14px;
  --sh: 0 2px 16px rgba(13,59,122,.10);
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  font-family: 'Be Vietnam Pro', 'Inter', 'Segoe UI', -apple-system, sans-serif;
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
  min-height: 100vh;
}

/* ── Login overlay — split layout ── */
#login-overlay {
  position: fixed; inset: 0; z-index: 9999;
  display: flex; overflow: hidden;
}
/* LEFT HERO PANEL */
.login-hero {
  flex: 0 0 52%; position: relative;
  background: linear-gradient(145deg, #061D4A 0%, #0E3F8A 50%, #14307A 100%);
  display: flex; flex-direction: column;
  align-items: center; justify-content: center;
  padding: 48px 56px; overflow: hidden;
}
.login-hero::before {
  content: ''; position: absolute;
  width: 520px; height: 520px; border-radius: 50%;
  background: radial-gradient(circle, rgba(233,30,140,.18) 0%, transparent 70%);
  top: -180px; right: -140px; pointer-events: none;
}
.login-hero::after {
  content: ''; position: absolute;
  width: 380px; height: 380px; border-radius: 50%;
  background: radial-gradient(circle, rgba(255,255,255,.06) 0%, transparent 70%);
  bottom: -120px; left: -100px; pointer-events: none;
}
.lh-wave {
  position: absolute; bottom: 0; left: 0; right: 0;
  height: 120px; pointer-events: none;
  background: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1440 120'%3E%3Cpath fill='rgba(255,255,255,0.04)' d='M0,64 C360,110 1080,20 1440,80 L1440,120 L0,120 Z'/%3E%3C/svg%3E") bottom/cover no-repeat;
}
.lh-logo-ring {
  width: 130px; height: 130px; border-radius: 50%;
  background: rgba(255,255,255,.12);
  border: 2px solid rgba(255,255,255,.25);
  display: flex; align-items: center; justify-content: center;
  margin-bottom: 28px; position: relative; z-index: 1;
  box-shadow: 0 0 0 16px rgba(255,255,255,.05), 0 20px 40px rgba(0,0,0,.35);
}
.lh-logo-ring img { width: 100px; height: 100px; object-fit: contain; border-radius: 50%; }
.lh-brand { text-align: center; position: relative; z-index: 1; }
.lh-brand .lh-main {
  font-size: 32px; font-weight: 900; color: #fff; letter-spacing: -.01em; line-height: 1.15;
}
.lh-brand .lh-main em { color: #F472B6; font-style: normal; }
.lh-brand .lh-cs2 {
  display: inline-block; margin-top: 6px;
  background: rgba(233,30,140,.25); border: 1px solid rgba(233,30,140,.4);
  color: #F9A8D4; font-size: 11px; font-weight: 700; letter-spacing: .1em;
  text-transform: uppercase; padding: 3px 12px; border-radius: 20px;
}
.lh-desc {
  margin-top: 20px; font-size: 14px; color: rgba(255,255,255,.55);
  line-height: 1.6; text-align: center; max-width: 300px;
  position: relative; z-index: 1;
}
.lh-stats {
  display: flex; gap: 32px; margin-top: 36px;
  position: relative; z-index: 1;
}
.lh-stat {
  text-align: center;
  background: rgba(255,255,255,.07);
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 12px; padding: 12px 18px;
  min-width: 80px;
}
.lh-stat .lh-sn { font-size: 22px; font-weight: 800; color: #fff; }
.lh-stat .lh-sl { font-size: 10px; color: rgba(255,255,255,.45); letter-spacing: .06em; text-transform: uppercase; margin-top: 2px; }

/* RIGHT FORM PANEL */
.login-panel {
  flex: 1; background: #F1F5F9;
  display: flex; align-items: center; justify-content: center;
  padding: 40px 32px; position: relative;
}
.login-panel::before {
  content: ''; position: absolute; inset: 0;
  background: url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%230E3F8A' fill-opacity='0.04'%3E%3Ccircle cx='30' cy='30' r='2'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E");
  pointer-events: none;
}
.login-card {
  background: #fff; border-radius: 20px;
  padding: 40px 36px 32px; width: 100%; max-width: 380px;
  box-shadow: 0 4px 6px rgba(0,0,0,.04), 0 20px 48px rgba(14,63,138,.1);
  position: relative; z-index: 1;
}
.login-card-header { margin-bottom: 28px; }
.login-card-header .lc-title {
  font-size: 22px; font-weight: 800; color: #0D3B7A; letter-spacing: -.01em;
}
.login-card-header .lc-title span { color: #E91E8C; }
.login-card-header .lc-sub { font-size: 13px; color: #94A3B8; margin-top: 5px; }
.login-sep {
  height: 2px; border-radius: 2px; margin-bottom: 24px;
  background: linear-gradient(90deg, #0D3B7A, #E91E8C, transparent);
}
.login-field { margin-bottom: 16px; }
.login-field label {
  display: block; font-size: 11px; font-weight: 700; color: #64748B;
  margin-bottom: 6px; text-transform: uppercase; letter-spacing: .06em;
}
.login-field .lf-wrap { position: relative; }
.login-field .fi {
  position: absolute; top: 50%; left: 14px;
  transform: translateY(-50%); font-size: 15px; pointer-events: none; line-height: 1;
}
.login-field input {
  width: 100%; padding: 12px 14px 12px 40px;
  border: 1.5px solid #E2E8F0; border-radius: 10px;
  font-size: 14px; outline: none;
  transition: border .18s, box-shadow .18s, background .18s;
  font-family: inherit; background: #F8FAFC; box-sizing: border-box; color: #1E293B;
}
.login-field input:focus {
  border-color: #1A5CA8;
  box-shadow: 0 0 0 3px rgba(26,92,168,.1);
  background: #fff;
}
.login-remember { display: flex; align-items: center; gap: 8px; margin-bottom: 18px; }
.login-remember input[type=checkbox] { width: auto; accent-color: #1A5CA8; cursor: pointer; }
.login-remember label { font-size: 13px; color: #64748B; cursor: pointer; margin-bottom: 0; }
#login-err {
  color: #C53030; font-size: 12px; margin-bottom: 14px; display: none;
  padding: 9px 12px; background: #FFF5F5; border-radius: 8px;
  border-left: 3px solid #FC8181; font-weight: 500;
}
.login-btn {
  width: 100%; padding: 14px;
  background: linear-gradient(90deg, #0D3B7A, #1A5CA8 40%, #C2185B);
  background-size: 200% 100%; background-position: right center;
  color: #fff; border: none; border-radius: 10px;
  font-size: 15px; font-weight: 700; letter-spacing: .03em;
  cursor: pointer; font-family: inherit;
  transition: background-position .4s ease, transform .15s, box-shadow .15s;
  box-shadow: 0 4px 14px rgba(13,59,122,.35);
}
.login-btn:hover {
  background-position: left center;
  transform: translateY(-1px);
  box-shadow: 0 8px 24px rgba(26,92,168,.45);
}
.login-btn:active { transform: translateY(0); box-shadow: 0 2px 8px rgba(13,59,122,.3); }
.login-hint { font-size: 11px; color: #94A3B8; text-align: center; margin-top: 14px; }

/* RESPONSIVE — collapse hero on small screens */
@media (max-width: 768px) {
  #login-overlay { flex-direction: column; }
  .login-hero {
    flex: 0 0 auto; padding: 32px 24px;
    flex-direction: row; gap: 16px; justify-content: flex-start;
  }
  .lh-logo-ring { width: 64px; height: 64px; margin-bottom: 0; flex-shrink: 0; box-shadow: none; }
  .lh-logo-ring img { width: 50px; height: 50px; }
  .lh-brand .lh-main { font-size: 20px; }
  .lh-cs2 { display: none !important; }
  .lh-desc, .lh-stats { display: none; }
  .login-hero::before, .login-hero::after, .lh-wave { display: none; }
  .login-panel { flex: 1; padding: 24px 16px; align-items: flex-start; padding-top: 24px; }
  .login-card { padding: 28px 20px 24px; }
}

/* ── App body ── */
#app-body { display: none; min-height: 100vh; }

/* Sidebar */
.sidebar {
  width: 220px; min-height: 100vh;
  background: var(--sidebar);
  display: flex; flex-direction: column;
  position: sticky; top: 0; height: 100vh;
  overflow-y: auto; flex-shrink: 0; z-index: 100;
}
.sidebar-logo { padding: 20px 16px 18px; border-bottom: 1px solid rgba(255,255,255,.10); }
.logo-icon { display: none; }
.sidebar-brand { display: flex; flex-direction: column; gap: 3px; }
.sidebar-brand .sb-main { font-size: 14px; font-weight: 800; color: #fff; letter-spacing: .01em; line-height: 1.2; }
.sidebar-brand .sb-pink { color: #E91E8C; font-weight: 700; font-size: 11px; letter-spacing: .06em; text-transform: uppercase; margin-top: 1px; }
.logo-name { display: none; }
.logo-sub  { font-size: 10px; color: rgba(255,255,255,.4); margin-top: 4px; letter-spacing: .02em; }
.nav-section { padding: 14px 0 8px; flex: 1; }
.nav-group-label {
  font-size: 10px; font-weight: 600; color: rgba(255,255,255,.3);
  text-transform: uppercase; letter-spacing: .08em;
  padding: 0 20px 6px; margin-top: 8px;
}
.nav-item {
  display: flex; align-items: center; gap: 12px;
  padding: 11px 20px; cursor: pointer;
  border-left: 3px solid transparent;
  transition: background-color .15s, color .15s, border-left-color .15s;
  color: rgba(255,255,255,.58); font-size: 13.5px; font-weight: 500;
  text-decoration: none; user-select: none;
}
.nav-item:hover { background: rgba(255,255,255,.05); color: rgba(255,255,255,.9); }
.nav-item.active { background: rgba(26,92,168,.18); border-left-color: var(--pink); color: #fff; }
.nav-item .ni { font-size: 16px; width: 20px; text-align: center; flex-shrink: 0; }
.sidebar-footer { padding: 12px 0 20px; border-top: 1px solid rgba(255,255,255,.07); }
.sidebar-gen { font-size: 10px; color: rgba(255,255,255,.55); padding: 6px 20px; text-align: center; }
.user-info {
  display: flex; align-items: center; justify-content: space-between;
  padding: 10px 16px; margin: 0 8px 4px;
  background: rgba(255,255,255,.07); border-radius: 8px;
}
.user-badge {
  font-size: 12px; font-weight: 700; color: #fff;
  background: var(--accent); padding: 3px 10px; border-radius: 5px;
}
.logout-btn {
  font-size: 11px; color: rgba(255,255,255,.4);
  background: none; border: none; cursor: pointer;
  padding: 10px 12px; min-height: 44px; min-width: 44px;
  font-family: inherit; transition: color .15s;
}
.logout-btn:hover { color: rgba(255,255,255,.9); }

/* Main */
.main { flex: 1; overflow-y: auto; min-width: 0; }
.view { display: none; padding: 28px 32px 40px; }
.view.active { display: block; }

/* Page header */
.page-header {
  display: flex; align-items: flex-start;
  justify-content: space-between; margin-bottom: 24px;
  flex-wrap: wrap; gap: 12px;
}
.page-header h1 { font-size: 22px; font-weight: 700; }
.page-header .subtitle { color: var(--muted); margin-top: 3px; font-size: 13px; }
.search-box input {
  background: var(--white); border: 1px solid var(--border);
  border-radius: 8px; padding: 9px 16px; font-size: 13px;
  width: 240px; outline: none; transition: border .15s;
}
.search-box input:focus { border-color: var(--accent); }

/* Stats grid */
.stats-grid {
  display: grid; grid-template-columns: repeat(5, 1fr);
  gap: 16px; margin-bottom: 20px;
}
.stat-card {
  background: var(--white); border-radius: var(--r);
  padding: 20px 22px; box-shadow: var(--sh);
  display: flex; align-items: center; gap: 16px;
}
.stat-icon { font-size: 28px; }
.stat-num  { font-size: 28px; font-weight: 800; line-height: 1; }
.stat-label { font-size: 12px; color: var(--muted); margin-top: 4px; font-weight: 500; }
.stat-total .stat-num  { color: #4299e1; }
.stat-done  .stat-num  { color: #48bb78; }
.stat-active .stat-num { color: #ed8936; }
.stat-late  .stat-num  { color: #f56565; }
.stat-rate  .stat-num  { color: var(--pink); }

/* Btn */
.btn-primary {
  background: var(--accent); color: #fff; border: none;
  border-radius: 8px; padding: 10px 20px;
  font-size: 13px; font-weight: 600; cursor: pointer;
  transition: background .15s; white-space: nowrap;
}
.btn-primary:hover { background: var(--accent2); }

/* Layout */
.two-col   { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.three-col { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 16px; }
.mt-16 { margin-top: 16px; }

/* Card */
.card { background: var(--white); border-radius: var(--r); padding: 20px 22px; box-shadow: var(--sh); }
.card.full-width { grid-column: 1/-1; }
.card-header {
  display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px;
}
.card-header h2 { font-size: 15px; font-weight: 700; margin: 0; }
.see-more { font-size: 12px; color: var(--accent); cursor: pointer; font-weight: 600; text-decoration: none; }
.see-more:hover { text-decoration: underline; }

/* Urgent list */
.urgent-list { list-style: none; max-height: 480px; overflow-y: scroll; overscroll-behavior: contain; -webkit-overflow-scrolling: touch; touch-action: pan-y; }
.urgent-item {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border);
}
.urgent-item:last-child { border-bottom: none; }
.urgent-body { flex: 1; min-width: 0; }
.urgent-id {
  font-size: 10px; font-weight: 700; color: var(--muted);
  background: #f0f4f8; padding: 1px 6px; border-radius: 4px;
  display: inline-block; margin-bottom: 3px;
}
.urgent-ten {
  font-size: 13px; font-weight: 500; line-height: 1.4;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.urgent-phong { font-size: 11px; color: var(--muted); margin-top: 2px; }
.urgent-right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex-shrink: 0; }
.date-badge { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 5px; white-space: nowrap; }
.date-badge.red    { background: #fff5f5; color: #c53030; }
.date-badge.orange { background: #fffaf0; color: #c05621; }
.date-badge.green  { background: #f0fff4; color: #276749; }
.nhac-badge { font-size: 10px; font-weight: 600; padding: 2px 7px; border-radius: 5px; background: #fde8f2; color: var(--pink2); }
.no-data { padding: 24px 0; text-align: center; color: var(--muted); font-size: 13px; }

/* Sources */
.sources-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(160px, 1fr)); gap: 12px; }
.source-card {
  background: var(--bg); border-radius: 10px; padding: 14px 16px;
  border: 1px solid var(--border);
  transition: transform .18s, box-shadow .18s, border-color .18s;
}
.source-card.clickable { cursor: pointer; }
.source-card.clickable:hover {
  transform: translateY(-3px);
  box-shadow: 0 8px 24px rgba(0,0,0,.12);
  border-color: var(--accent);
}
.source-name {
  font-size: 12px; font-weight: 600; line-height: 1.4; margin-bottom: 8px;
  display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden;
}
.source-count { font-size: 22px; font-weight: 800; color: var(--accent); }
.source-date  { font-size: 11px; color: var(--muted); margin-top: 2px; }
.source-pdf-icon { margin-top: 6px; font-size: 10px; font-weight: 600; color: var(--accent); }
.source-no-pdf  { margin-top: 6px; font-size: 10px; color: var(--muted); }

/* Filter bar */
.filter-bar { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
.filter-bar select, .filter-bar input {
  background: var(--white); border: 1px solid var(--border);
  border-radius: 8px; padding: 8px 14px; font-size: 13px; outline: none; transition: border .15s;
}
.filter-bar select:focus, .filter-bar input:focus { border-color: var(--accent); }
.filter-bar input { width: 200px; }

/* Nhom section headers in task view */
.nhom-section-header {
  display: flex; align-items: center; justify-content: space-between;
  padding: 14px 20px; margin: 24px 0 4px;
  background: var(--sidebar); border-radius: var(--r);
  color: #fff;
}
.nhom-section-header:first-child { margin-top: 0; }
.nhom-label { font-size: 15px; font-weight: 700; }

/* Task dept sections */
.dept-section { margin-bottom: 12px; }
.dept-section-header {
  display: flex; align-items: center; gap: 12px;
  padding: 12px 16px; background: var(--white);
  border-radius: var(--r) var(--r) 0 0;
  border-bottom: 2px solid var(--border);
  cursor: pointer; user-select: none;
}
.dept-section-header:hover { background: #f9f9f9; }
.dept-section-avatar { width: 34px; height: 34px; border-radius: 8px; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: #fff; flex-shrink: 0; }
.dept-section-name { font-size: 14px; font-weight: 700; flex: 1; }
.dept-badges { display: flex; gap: 6px; flex-wrap: wrap; }
.badge { font-size: 11px; font-weight: 600; padding: 2px 9px; border-radius: 5px; }
.badge-green  { background: #f0fff4; color: #276749; }
.badge-orange { background: #fffaf0; color: #c05621; }
.badge-red    { background: #fff5f5; color: #c53030; }
.badge-blue   { background: #ebf8ff; color: #2c5282; }
.badge-gray   { background: #f7fafc; color: #4a5568; }
.toggle-ic    { font-size: 12px; color: var(--muted); }

.task-table-wrap { background: var(--white); border-radius: 0 0 var(--r) var(--r); overflow-x: auto; box-shadow: var(--sh); }
.task-table-wrap.hidden { display: none; }
.task-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.task-table th {
  background: #f7fafc; padding: 10px 14px; text-align: left;
  font-weight: 600; color: var(--muted); font-size: 11px;
  text-transform: uppercase; letter-spacing: .04em;
  white-space: nowrap; border-bottom: 1px solid var(--border);
}
.task-table td { padding: 11px 14px; border-bottom: 1px solid var(--border); vertical-align: top; }
.task-table tr:last-child td { border-bottom: none; }
.task-table tr:hover td { background: #fafbfc; }
.task-id { font-size: 11px; font-weight: 700; color: var(--muted); white-space: nowrap; }
.task-ten { line-height: 1.45; max-width: 320px; }
.task-nhac { font-size: 10px; font-weight: 700; padding: 1px 5px; border-radius: 4px; background: #fef3c7; color: #92400e; margin-left: 5px; }
.status-pill { font-size: 11px; font-weight: 600; padding: 3px 10px; border-radius: 20px; white-space: nowrap; display: inline-block; }
.status-done      { background: #f0fff4; color: #276749; }
.status-active    { background: #ebf8ff; color: #2c5282; }
.status-late      { background: #fff5f5; color: #c53030; }
.status-recurring { background: #f0fdf4; color: #166534; }
.status-pending{ background: #fffbeb; color: #92400e; }
.nguon-cell { font-size: 11px; color: var(--muted); white-space: nowrap; max-width: 140px; overflow: hidden; text-overflow: ellipsis; }

/* Dept progress bars */
.dept-progress-row { display: flex; flex-direction: row; align-items: center; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--border); }
.dept-progress-row:last-child { border-bottom: none; }
.dp-name { font-size: 13px; font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 90px; max-width: 150px; flex-shrink: 0; }
.dp-bar-wrap { flex: 1; height: 10px; background: #dce8f5; border-radius: 5px; display: flex; overflow: hidden; }
.dp-bar-done   { background: var(--green); height: 100%; transition: width .5s; }
.dp-bar-active { background: var(--blue);  height: 100%; transition: width .5s; }
.dp-bar-late   { background: var(--red);   height: 100%; transition: width .5s; }
.dp-stats { display: flex; align-items: center; gap: 8px; flex-shrink: 0; }
.dp-stat { font-size: 12px; font-weight: 700; display: inline-flex; align-items: center; gap: 2px; }
.dp-num { min-width: 22px; text-align: right; display: inline-block; }
.dp-stat-done  { color: var(--green); }
.dp-stat-act   { color: var(--blue); }
.dp-stat-late  { color: var(--red); }
.dp-stat-total { color: var(--muted); font-weight: 500; font-size: 11px; }

.no-tasks-msg { text-align: center; padding: 40px 0; color: var(--muted); font-size: 14px; }
.mb-16 { margin-bottom: 16px; }

/* Search results */
.search-result-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.search-result-table th {
  background: #f7fafc; padding: 8px 12px; text-align: left;
  font-weight: 600; color: var(--muted); font-size: 11px; border-bottom: 1px solid var(--border);
}
.search-result-table td { padding: 9px 12px; border-bottom: 1px solid var(--border); }

/* ── Mobile overlay ── */
.mob-overlay {
  display: none; position: fixed; inset: 0;
  background: rgba(0,0,0,.45); z-index: 99;
}
.mob-overlay.open { display: block; }
.mob-hamburger {
  display: none; position: fixed; top: 12px; left: 12px; z-index: 200;
  width: 40px; height: 40px; border-radius: 10px;
  background: var(--sidebar); border: none; cursor: pointer;
  flex-direction: column; align-items: center; justify-content: center; gap: 5px;
}
.mob-hamburger span { display: block; width: 20px; height: 2px; background: #fff; border-radius: 2px; transition: transform .2s, opacity .2s; }

@media (max-width: 1100px) { .stats-grid { grid-template-columns: repeat(3, 1fr); } }
@media (max-width: 900px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
  .two-col, .three-col { grid-template-columns: 1fr; }
}
@media (max-width: 768px) {
  /* Sidebar: ẩn hoàn toàn, dùng hamburger drawer */
  .sidebar { position: fixed; left: -240px; top: 0; height: 100vh; width: 220px !important; z-index: 150; transition: left .25s ease; box-shadow: 4px 0 20px rgba(0,0,0,.25); }
  .sidebar.mob-open { left: 0; }
  .mob-hamburger { display: flex; }
  .view { padding: 56px 16px 32px; }
  /* Layout */
  .page-header { flex-direction: column; gap: 8px; }
  .page-header > div:last-child { width: 100%; }
  .search-box, .search-box input { width: 100%; }
  .filter-bar { flex-wrap: wrap; gap: 8px; }
  .filter-bar select, .filter-bar input { min-width: 140px; }
  .sources-grid { grid-template-columns: repeat(2, 1fr); }
  /* Table → card layout on mobile */
  .task-table-wrap { overflow-x: visible; }
  .task-table { min-width: 0; width: 100%; }
  .task-table thead { display: none; }
  .task-table tbody { display: block; padding: 6px 10px 10px; }
  .task-table tr { display: block; border: 1px solid var(--border); border-radius: 10px; margin-bottom: 8px; padding: 10px 12px; background: var(--white); }
  .task-table td { display: block; border: none; padding: 2px 0; }
  .col-hide-mobile { display: none; }
  .task-id { display: inline; margin-right: 6px; }
  .task-ten { display: inline; }
  .task-deadline { font-size: 12px; color: var(--muted); margin-top: 4px; }
  .task-deadline::before { content: 'Deadline: '; }
  .task-status { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 8px; }
  .task-status .btn-upd { flex: 1; min-width: 120px; text-align: center; }
  /* Dept sections */
  .dept-section-header { padding: 10px 12px; }
  .dept-badges { gap: 4px; }
  /* Dept progress bars — mobile: ẩn bar, chỉ hiện name + stats */
  .dp-bar-wrap { display: none; }
  .dp-stats { margin-left: auto; }
  .dp-stat { font-size: 13px; }
  .dp-num { min-width: 24px; }
  /* Charts — prevent overflow on mobile */
  canvas { max-width: 100%; display: block; }
  /* Review tab mobile */
  .rv-reporter { flex-direction: column; }
  .rv-reporter-actions { width: 100%; display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
  .btn-appr, .btn-rejt { width: 100%; padding: 12px; font-size: 14px; border-radius: 10px; text-align: center; }
  .review-stats { grid-template-columns: repeat(3,1fr); gap: 10px; }
  .rv-item { padding: 14px; }
  .rv-export-bar { flex-direction: column; }
  .rv-export-bar button { width: 100%; justify-content: center; }
  /* Modal */
  .modal-bx { width: calc(100vw - 20px); padding: 20px 16px; }
  .mactions { flex-direction: column-reverse; }
  .mactions button { width: 100%; }
  /* Font-size tối thiểu để đọc được trên mobile */
  .status-pill, .badge { font-size: 13px; }
  .urgent-phong, .task-nhac, .nhac-badge { font-size: 12px; }
}
@media (max-width: 480px) {
  .stats-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
  .stat-card { padding: 14px 12px; gap: 10px; }
  .stat-num { font-size: 22px; }
  .stat-icon { font-size: 20px; }
  .login-card { padding: 28px 16px 22px; }
  .review-stats { grid-template-columns: 1fr 1fr; }
}
@media (max-width: 380px) {
  .stat-icon { display: none; }
  .stats-grid { grid-template-columns: repeat(2, 1fr); }
}

/* ── Pending updates & update modal ── */
.pending-panel{background:#fffaf0;border:1px solid var(--orange);border-radius:var(--r);padding:16px 20px;margin-bottom:20px;}
.pending-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;font-size:14px;font-weight:700;color:#c05621;flex-wrap:wrap;gap:8px;}
.pending-item{display:flex;align-items:flex-start;gap:12px;padding:10px 0;border-bottom:1px solid #fdebc8;}
.pending-item:last-child{border-bottom:none;}
.pending-info{flex:1;min-width:0;font-size:12px;}
.pending-name{font-size:13px;font-weight:600;margin:2px 0;}
.pending-meta{color:var(--muted);margin-top:2px;}
.btn-appr{background:#f0fff4;border:1px solid var(--green);color:#276749;border-radius:6px;padding:7px 14px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;min-height:36px;}
.btn-rejt{background:#fff5f5;border:1px solid var(--red);color:#c53030;border-radius:6px;padding:7px 14px;font-size:13px;font-weight:600;cursor:pointer;white-space:nowrap;min-height:36px;}
.btn-upd{background:none;border:1px solid var(--pink);border-radius:6px;padding:7px 12px;font-size:13px;font-weight:600;cursor:pointer;color:var(--pink);transition:background-color .15s,color .15s,border-color .15s;margin-top:4px;display:inline-block;min-height:36px;}
.btn-upd:hover{background:var(--pink);color:#fff;}
.btn-sent{background:#f0fff4;border-color:#68d391;color:#276749;}
.btn-sent:hover{background:#dcfce7;}
.btn-exp{background:#48bb78;color:#fff;border:none;border-radius:7px;padding:6px 14px;font-size:12px;font-weight:600;cursor:pointer;white-space:nowrap;}
.modal-ov{position:fixed;inset:0;background:rgba(0,0,0,.45);z-index:8000;display:flex;align-items:center;justify-content:center;}
.modal-bx{background:#fff;border-radius:var(--r);padding:28px;width:440px;max-width:calc(100vw - 32px);box-shadow:0 20px 60px rgba(0,0,0,.3);}
.modal-ttl{font-size:16px;font-weight:700;margin-bottom:4px;}
.modal-sub{font-size:12px;color:var(--muted);margin-bottom:18px;line-height:1.5;}
.mfield{margin-bottom:13px;}
.mfield label{display:block;font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:5px;}
.mfield input,.mfield textarea,.mfield select{width:100%;padding:9px 12px;border:1.5px solid var(--border);border-radius:8px;font-size:13px;font-family:inherit;outline:none;transition:border .15s;resize:vertical;box-sizing:border-box;}
.mfield input:focus,.mfield textarea:focus,.mfield select:focus{border-color:var(--accent);}
.mfield select{background:#fff;cursor:pointer;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%23718096' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 12px center;padding-right:32px;}
.mactions{display:flex;gap:10px;margin-top:20px;justify-content:flex-end;}
.btn-cncl{background:var(--border);border:none;border-radius:7px;padding:9px 18px;font-size:13px;cursor:pointer;font-family:inherit;}
.msg-err{padding:10px 12px;border-radius:8px;font-size:13px;background:#fff5f5;color:#c53030;border:1.5px solid #fc8181;}
.msg-ok{padding:10px 12px;border-radius:8px;font-size:13px;background:#f0fff4;color:#276749;border:1.5px solid #68d391;}

/* ── Nav badge ── */
.nav-badge{display:inline-flex;align-items:center;justify-content:center;background:#f56565;color:#fff;font-size:10px;font-weight:700;border-radius:10px;min-width:18px;height:18px;padding:0 5px;margin-left:auto;flex-shrink:0;}

/* ── Review view ── */
/* Sticky bar (mobile review summary) */
.rv-sticky-bar{display:none;position:sticky;top:0;z-index:50;background:var(--white);border-bottom:1px solid var(--border);padding:10px 16px;gap:8px;flex-wrap:wrap;}
.rv-chip{display:inline-flex;align-items:center;gap:4px;padding:6px 12px;border-radius:999px;font-size:13px;font-weight:500;}
.rv-chip-pending{background:#fff3e0;color:#e65100;}
.rv-chip-approved{background:#e8f5e9;color:#2e7d32;}
.rv-chip-dept{background:#e3f2fd;color:#1565c0;}
.review-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;margin-bottom:24px;}
.rv-section{margin-bottom:28px;}
.rv-section-title{font-size:15px;font-weight:700;margin-bottom:14px;display:flex;align-items:center;gap:10px;padding-bottom:10px;border-bottom:2px solid var(--border);}
.rv-item{background:var(--white);border-radius:var(--r);padding:16px 18px;margin-bottom:10px;box-shadow:var(--sh);border-left:4px solid var(--border);}
.rv-item.pending-color{border-left-color:var(--orange);}
.rv-item.approved-color{border-left-color:var(--green);}
.rv-item-hdr{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;margin-bottom:10px;}
.rv-item-meta{font-size:11px;color:var(--muted);margin-top:3px;line-height:1.5;}
.rv-reporter{display:flex;align-items:flex-start;gap:10px;padding:10px 12px;border:1px solid var(--border);border-radius:8px;margin-top:8px;background:#f7fafc;flex-wrap:wrap;}
.rv-reporter-phong{font-size:11px;font-weight:700;color:var(--sidebar);background:#e2e8f0;padding:3px 9px;border-radius:5px;white-space:nowrap;flex-shrink:0;align-self:flex-start;}
.rv-reporter-body{flex:1;min-width:0;}
.rv-reporter-actions{display:flex;gap:6px;flex-shrink:0;align-self:flex-start;}
.rv-empty{text-align:center;padding:36px 0;color:var(--muted);font-size:14px;}
.rv-export-bar{display:flex;justify-content:flex-end;margin-top:16px;}
@media(max-width:900px){.review-stats{grid-template-columns:1fr 1fr;}}
@media(max-width:768px){
  .rv-sticky-bar{display:flex;}
  .review-stats{display:none;}
}
/* ── Nhật Ký ────────────────────────────────────────────────── */
.log-filterbar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px;align-items:center;}
.log-filterbar select,.log-filterbar input{padding:7px 10px;border:1px solid var(--border);border-radius:8px;font-size:13px;background:var(--white);color:var(--text);min-width:0;}
.log-filterbar input{flex:1;min-width:140px;}
.log-table-wrap{overflow-x:auto;border-radius:var(--r);box-shadow:var(--sh);background:var(--white);}
.log-table{width:100%;border-collapse:collapse;font-size:13px;}
.log-table th{background:var(--sidebar);color:#fff;padding:10px 12px;text-align:left;white-space:nowrap;font-weight:600;}
.log-table td{padding:9px 12px;border-bottom:1px solid var(--border);vertical-align:top;}
.log-table tr:last-child td{border-bottom:none;}
.log-table tr:hover td{background:#f0f5ff;}
.log-badge-user{display:inline-block;padding:2px 8px;border-radius:5px;font-size:11px;font-weight:700;background:#e8eaf6;color:#3949ab;}
.log-arrow{color:var(--muted);margin:0 4px;}
.log-status{display:inline-block;padding:2px 7px;border-radius:5px;font-size:11px;font-weight:600;}
.log-status.done{background:#e8f5e9;color:#2e7d32;}
.log-status.active{background:#e3f2fd;color:#1565c0;}
.log-status.late{background:#fff3e0;color:#e65100;}
.log-status.other{background:#f5f5f5;color:#555;}
.log-src{font-size:11px;color:var(--muted);}
.log-empty{text-align:center;padding:48px;color:var(--muted);font-size:14px;}
.log-count{font-size:12px;color:var(--muted);margin-bottom:10px;}
@media(max-width:768px){
  .log-table th:nth-child(3),.log-table td:nth-child(3),
  .log-table th:nth-child(5),.log-table td:nth-child(5),
  .log-table th:nth-child(8),.log-table td:nth-child(8){display:none;}
}
</style>
</head>
<body>
<script>window.__D = """ + data_json + """;window.__FB_CONFIG = """ + fb_cfg_json + """;</script>

<!-- ═══ LOGIN OVERLAY ═══ -->
<div id="login-overlay">
  <!-- Left hero panel -->
  <div class="login-hero">
    <div class="lh-wave"></div>
    <div class="lh-logo-ring">
      <img src="__LOGO_URI__" alt="Logo BVTD CS2">
    </div>
    <div class="lh-brand">
      <div class="lh-main">Bệnh Viện <em>Từ Dũ</em></div>
      <span class="lh-cs2">Cơ Sở 2</span>
      <div class="lh-desc">Hệ thống theo dõi tiến độ đầu việc — cập nhật theo thời gian thực</div>
      <div class="lh-stats" id="lh-stats-box">
        <div class="lh-stat"><div class="lh-sn" id="lh-total">—</div><div class="lh-sl">Đầu việc</div></div>
        <div class="lh-stat"><div class="lh-sn" id="lh-depts">—</div><div class="lh-sl">Phòng ban</div></div>
        <div class="lh-stat"><div class="lh-sn" id="lh-done">—</div><div class="lh-sl">Hoàn thành</div></div>
      </div>
    </div>
  </div>
  <!-- Right form panel -->
  <div class="login-panel">
    <div class="login-card">
      <div class="login-card-header">
        <div class="lc-title">Đăng nhập <span>hệ thống</span></div>
        <div class="lc-sub">Nhập thông tin tài khoản phòng ban của bạn</div>
      </div>
      <div class="login-sep"></div>
      <div class="login-field">
        <label>Tên đăng nhập</label>
        <div class="lf-wrap">
          <span class="fi">👤</span>
          <input id="login-user" type="text" placeholder="VD: HCQT, BGD, KHTH..."
            autocomplete="username" onkeydown="if(event.key==='Enter')doLogin()">
        </div>
      </div>
      <div class="login-field">
        <label>Mật khẩu</label>
        <div class="lf-wrap">
          <span class="fi">🔒</span>
          <input id="login-pass" type="password" placeholder="Nhập mật khẩu..."
            autocomplete="current-password" onkeydown="if(event.key==='Enter')doLogin()">
        </div>
      </div>
      <div class="login-remember">
        <input type="checkbox" id="login-remember">
        <label for="login-remember">Ghi nhớ đăng nhập</label>
      </div>
      <div id="login-err">Sai tên đăng nhập hoặc mật khẩu. Vui lòng thử lại.</div>
      <button class="login-btn" onclick="doLogin()">Đăng nhập →</button>
      <div class="login-hint">Liên hệ CNTT nếu quên mật khẩu</div>
    </div>
  </div>
</div>

<!-- ═══ APP BODY ═══ -->
<div id="app-body" style="display:none;flex-direction:row;min-height:100vh;">

<!-- Mobile hamburger + overlay -->
<button class="mob-hamburger" id="mob-ham" onclick="toggleSidebar()" aria-label="Mở menu">
  <span></span><span></span><span></span>
</button>
<div class="mob-overlay" id="mob-overlay" onclick="toggleSidebar()"></div>

<!-- Firebase warning banner (hidden by default) -->
<div id="fb-warn-banner" style="display:none;position:fixed;top:0;left:0;right:0;z-index:300;background:#fffaf0;border-bottom:2px solid #dd6b20;color:#7b341e;padding:10px 20px;font-size:13px;font-weight:600;text-align:center;">
  ⚠️ Firebase chưa cấu hình — báo cáo từ phòng ban sẽ không được đồng bộ theo thời gian thực.
</div>

<!-- Sidebar -->
<nav class="sidebar">
  <div class="sidebar-logo">
    <div style="display:flex;align-items:center;gap:10px;">
      <img src="__LOGO_URI__" alt="Logo BVTD CS2" style="width:40px;height:40px;object-fit:contain;border-radius:50%;background:#fff;padding:2px;flex-shrink:0;">
      <div>
        <div class="logo-name">BVTD CS2</div>
      </div>
    </div>
  </div>
  <div class="nav-section">
    <div class="nav-group-label">Chính</div>
    <div class="nav-item active" data-view="dashboard">
      <span class="ni">⊞</span><span>Tổng Quan</span>
    </div>
    <div class="nav-item" data-view="tasks">
      <span class="ni">✔</span><span>Đầu Việc</span>
    </div>
    <div class="nav-group-label" style="margin-top:16px;">Liên kết</div>
    <div class="nav-item" data-view="review" id="nav-review" style="display:none">
      <span class="ni">📋</span><span>Duyệt Cập Nhật</span>
      <span class="nav-badge" id="nav-review-badge" style="display:none">0</span>
    </div>
    <div class="nav-item" data-view="log" id="nav-log" style="display:none">
      <span class="ni">🕵</span><span>Nhật Ký</span>
    </div>
    <a class="nav-item" href="gantt.html" target="_blank" rel="noopener noreferrer">
      <span class="ni">📅</span><span>Biểu đồ Gantt</span>
    </a>
  </div>
  <div class="sidebar-footer">
    <div class="user-info">
      <span class="user-badge" id="user-badge">—</span>
      <button class="logout-btn" onclick="doLogout()" title="Đăng xuất">✕ Thoát</button>
    </div>
    <div class="sidebar-gen" id="gen-label"></div>
    <div class="sidebar-gen" id="ver-label" style="color:rgba(255,255,255,.35);font-size:10px;padding-top:0;"></div>
  </div>
</nav>

<!-- Main -->
<main class="main" style="flex:1;">

<!-- ═══ DASHBOARD ═══ -->
<div id="view-dashboard" class="view active">
  <header class="page-header">
    <div>
      <h1>Xin chào! 👋</h1>
      <p class="subtitle" id="today-label"></p>
    </div>
    <div style="display:flex;gap:10px;align-items:center;">
      <div class="search-box">
        <input type="text" id="dash-search" placeholder="Tìm kiếm đầu việc..." aria-label="Tìm kiếm đầu việc" oninput="_dbSearch(this.value)">
      </div>
      <button class="btn-primary" onclick="switchView('tasks')">Xem tất cả →</button>
    </div>
  </header>

  <!-- Stats (5 cards) -->
  <div class="stats-grid">
    <div class="stat-card stat-total">
      <div class="stat-icon">📋</div>
      <div><div class="stat-num" id="s-total">—</div><div class="stat-label">Tổng đầu việc</div></div>
    </div>
    <div class="stat-card stat-done">
      <div class="stat-icon">✅</div>
      <div><div class="stat-num" id="s-done">—</div><div class="stat-label">Hoàn thành</div></div>
    </div>
    <div class="stat-card stat-active">
      <div class="stat-icon">🔄</div>
      <div><div class="stat-num" id="s-active">—</div><div class="stat-label">Đang thực hiện</div></div>
    </div>
    <div class="stat-card stat-late">
      <div class="stat-icon">⚠️</div>
      <div><div class="stat-num" id="s-late">—</div><div class="stat-label">Trễ deadline</div></div>
    </div>
    <div class="stat-card stat-rate">
      <div class="stat-icon">📈</div>
      <div><div class="stat-num" id="s-rate">—%</div><div class="stat-label">% Hoàn thành</div></div>
    </div>
  </div>

  <!-- Search results -->
  <div id="dash-search-results" style="display:none;" class="card full-width mb-16">
    <div class="card-header">
      <h3>Kết quả tìm kiếm</h3>
      <span class="see-more" onclick="clearDashSearch()">✕ Đóng</span>
    </div>
    <div id="dash-search-list"></div>
  </div>

  <!-- Row 1: Urgent + Repeats alerts -->
  <div class="two-col">
    <div class="card">
      <div class="card-header">
        <h3>⚠️ Đầu Việc Trễ Hạn</h3>
        <span class="badge badge-red" id="urgent-count-badge">0</span>
      </div>
      <ul class="urgent-list" id="urgent-list"></ul>
    </div>
    <div class="card">
      <div class="card-header">
        <h3>🔁 Nhiệm Vụ Nhắc Lại Nhiều Lần</h3>
        <span id="repeats-count-badge" class="see-more" style="cursor:default;"></span>
      </div>
      <ul class="urgent-list" id="repeat-preview-list"></ul>
    </div>
  </div>

  <!-- Row 2: Dept progress (full width) -->
  <div class="card full-width mt-16">
    <div class="card-header">
      <h3>Tiến Độ Theo Phòng Ban</h3>
      <div style="display:flex;gap:16px;font-size:11px;color:var(--muted);">
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:var(--green);margin-right:4px;vertical-align:middle;"></span>Hoàn thành</span>
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:var(--blue);margin-right:4px;vertical-align:middle;"></span>Đang làm</span>
        <span><span style="display:inline-block;width:10px;height:10px;border-radius:2px;background:var(--red);margin-right:4px;vertical-align:middle;"></span>Trễ</span>
      </div>
    </div>
    <div id="dept-breakdown"></div>
  </div>

  <!-- Row 3: Charts -->
  <div class="two-col mt-16">
    <div class="card">
      <div class="card-header"><h2>Đầu Việc Theo Tháng</h2></div>
      <canvas id="monthly-chart" height="220"></canvas>
    </div>
    <div class="card">
      <div class="card-header"><h2>Phân Loại Nhóm</h2></div>
      <canvas id="nhom-chart" height="220"></canvas>
    </div>
  </div>

  <!-- Row 4: Meeting sources -->
  <div class="card full-width mt-16">
    <div class="card-header">
      <h3>Biên Bản / Họp Giao Ban</h3>
      <span style="font-size:12px;color:var(--muted);" id="src-count-label"></span>
    </div>
    <div class="sources-grid" id="sources-grid"></div>
  </div>
</div>

<!-- ═══ TASKS ═══ -->
<div id="view-tasks" class="view">
  <header class="page-header">
    <div>
      <h1>Danh Sách Đầu Việc</h1>
      <p class="subtitle" id="tasks-count-label">Tất cả đầu việc</p>
    </div>
    <div class="filter-bar">
      <select id="filter-nhom" onchange="filterTasks()">
        <option value="">Tất cả nhóm</option>
        <option value="hanh_chanh">🏢 Hành chính</option>
        <option value="chuyen_mon">🔬 Chuyên môn</option>
        <option value="quan_ly_khac">📋 Quản lý khác</option>
      </select>
      <select id="filter-status" onchange="filterTasks()">
        <option value="">Tất cả trạng thái</option>
        <option value="chua_xong">⏳ Chưa xong</option>
        <option value="da_hoan_thanh">✅ Hoàn thành</option>
        <option value="dang_thuc_hien">🔄 Đang thực hiện</option>
        <option value="tre_deadline">⚠️ Trễ deadline</option>
      </select>
      <select id="filter-dept" onchange="filterTasks()">
        <option value="">Tất cả phòng</option>
      </select>
      <select id="filter-bienban" onchange="filterTasks()">
        <option value="">Tất cả biên bản</option>
      </select>
      <input type="text" id="filter-search" placeholder="Tìm kiếm..." aria-label="Tìm kiếm đầu việc" oninput="_dbFilter()">
    </div>
  </header>
  <div id="tasks-by-nhom"></div>
</div>


<!-- ═══ REVIEW (BGĐ only) ═══ -->
<div id="view-review" class="view">
  <header class="page-header">
    <div>
      <h1>📋 Duyệt Cập Nhật</h1>
      <p class="subtitle" id="review-subtitle">Xem xét cập nhật tiến độ từ các phòng ban</p>
    </div>
  </header>

  <!-- Sticky summary bar (mobile-first) -->
  <div class="rv-sticky-bar" id="rv-sticky-bar">
    <span class="rv-chip rv-chip-pending">⏳ Chờ: <b id="rv-chip-pending">0</b></span>
    <span class="rv-chip rv-chip-approved">✅ Duyệt: <b id="rv-chip-approved">0</b></span>
    <span class="rv-chip rv-chip-dept">🏢 Phòng: <b id="rv-chip-dept">0</b></span>
  </div>

  <!-- KPI cards — hidden on mobile (sticky bar replaces) -->
  <div class="review-stats">
    <div class="stat-card" style="border-top:3px solid var(--orange);">
      <div class="stat-icon">⏳</div>
      <div><div class="stat-num" id="rv-pending-count" style="color:var(--orange)">0</div><div class="stat-label">Chờ duyệt</div></div>
    </div>
    <div class="stat-card" style="border-top:3px solid var(--green);">
      <div class="stat-icon">✅</div>
      <div><div class="stat-num" id="rv-approved-count" style="color:var(--green)">0</div><div class="stat-label">Đã duyệt</div></div>
    </div>
    <div class="stat-card" style="border-top:3px solid var(--blue);">
      <div class="stat-icon">🏢</div>
      <div><div class="stat-num" id="rv-depts-count" style="color:var(--blue)">0</div><div class="stat-label">Phòng báo cáo</div></div>
    </div>
  </div>

  <!-- Pending section -->
  <div class="rv-section">
    <div class="rv-section-title">
      ⏳ Chờ Duyệt
      <span class="badge badge-orange" id="rv-pending-badge">0</span>
    </div>
    <div id="rv-pending-list"></div>
  </div>

  <!-- Approved section -->
  <div class="rv-section">
    <div class="rv-section-title" style="display:flex;align-items:center;gap:8px;">
      ✅ Đã Duyệt
      <span class="badge badge-green" id="rv-approved-badge">0</span>
      <span style="font-size:12px;color:var(--muted);font-weight:400;">— sẵn sàng xuất JSON</span>
      <button onclick="showGHTokenSetup()" title="Cấu hình GitHub Token để gửi tự động"
        style="margin-left:auto;background:none;border:1px solid var(--border);border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer;color:var(--muted);display:flex;align-items:center;gap:4px;">
        ⚙ GitHub Token
      </button>
    </div>
    <div id="rv-approved-list"></div>
    <div class="rv-export-bar" id="rv-export-btn" style="display:none;gap:10px;">
      <button class="btn-primary" id="btn-gh-upload" onclick="uploadToGitHub()" style="flex:1;">
        📤 Gửi lên GitHub — tự động cập nhật
      </button>
      <button onclick="exportApproved()" title="Tải file thủ công (dự phòng)"
        style="background:#fff;border:2px solid var(--orange);border-radius:8px;padding:9px 16px;font-size:13px;font-weight:600;cursor:pointer;color:var(--orange);white-space:nowrap;display:flex;align-items:center;gap:6px;">
        ⬇ Tải file
      </button>
      <button onclick="showGHTokenSetup()" title="Cấu hình GitHub Token"
        style="background:#fff;border:2px solid var(--border);border-radius:8px;padding:9px 13px;font-size:20px;cursor:pointer;color:var(--muted);line-height:1;">
        ⚙
      </button>
    </div>
  </div>
</div>


<!-- ═══ NHẬT KÝ ═══ -->
<div id="view-log" class="view">
  <header class="page-header">
    <div>
      <h1>🕵 Nhật Ký Chỉnh Sửa</h1>
      <p class="subtitle">Lịch sử cập nhật trạng thái — ai chỉnh gì, khi nào</p>
    </div>
  </header>
  <div class="log-filterbar">
    <input id="log-search" type="search" placeholder="Tìm theo tên đầu việc hoặc ghi chú…" oninput="renderLog()">
    <select id="log-flt-user" onchange="renderLog()"><option value="">-- Tất cả người dùng --</option></select>
    <select id="log-flt-phong" onchange="renderLog()"><option value="">-- Tất cả phòng --</option></select>
    <select id="log-flt-tt" onchange="renderLog()">
      <option value="">-- Tất cả trạng thái mới --</option>
      <option value="da_hoan_thanh">✅ Hoàn thành</option>
      <option value="dang_thuc_hien">🔄 Đang làm</option>
      <option value="tre_deadline">⚠️ Trễ deadline</option>
    </select>
  </div>
  <div class="log-count" id="log-count"></div>
  <div class="log-table-wrap">
    <table class="log-table">
      <thead><tr>
        <th>Ngày</th>
        <th>Người dùng</th>
        <th>Phòng báo cáo</th>
        <th>Đầu việc</th>
        <th>Thay đổi trạng thái</th>
        <th>Ghi chú</th>
        <th>Nguồn</th>
        <th>Thiết bị / IP</th>
      </tr></thead>
      <tbody id="log-tbody"></tbody>
    </table>
    <div class="log-empty" id="log-empty" style="display:none">Không có bản ghi nào.</div>
  </div>
</div>


<!-- ═══ UPDATE MODAL ═══ -->
<div id="upd-modal" class="modal-ov" style="display:none" onclick="if(event.target===this)closeUpd()">
  <div class="modal-bx">
    <div class="modal-ttl">✏ Báo cáo tiến độ</div>
    <div class="modal-sub" id="upd-sub"></div>
    <div class="mfield">
      <label>Trạng thái</label>
      <select id="upd-tt">
        <option value="">-- Chọn trạng thái --</option>
        <option value="da_hoan_thanh">✅ Hoàn thành</option>
        <option value="dang_thuc_hien">🔄 Đang làm</option>
        <option value="tre_deadline">⚠️ Trễ Deadline</option>
      </select>
    </div>
    <div class="mfield" id="upd-ngay-wrap">
      <label>Ngày hoàn thành (bắt buộc nếu chọn "Hoàn thành")</label>
      <input type="date" id="upd-ngay">
    </div>
    <div class="mfield">
      <label>Ghi chú / Tình trạng</label>
      <textarea id="upd-note" rows="3" placeholder="VD: Đã hoàn thành... / Đang chờ... / Khó khăn vì..."></textarea>
    </div>
    <div id="upd-msg" style="display:none"></div>
    <div class="mactions">
      <button class="btn-cncl" onclick="closeUpd()">Hủy</button>
      <button class="btn-primary" onclick="submitUpd()">Gửi báo cáo →</button>
    </div>
  </div>
</div>


</main>
</div><!-- end app-body -->

<script>
const D = window.__D;

// ── Auth configuration ─────────────────────────────────────────────────────────
const PASS = 'bvtd@cs2';
// depts: null = xem tất cả; array = chỉ xem phòng ban trong list
const USERS = {
  'BGD':      null,
  'HCQT':     ['HCQT'],
  'KHTH':     ['KHTH'],
  'CNTT':     ['CNTT'],
  'KSNK':     ['KSNK'],
  'CSKH':     ['CSKH'],
  'CTXH':     ['CTXH'],
  'VTTBYT':   ['VTTBYT'],
  'XN':       ['XN'],
  'TCCB':     ['TCCB'],
  'TCKT':     ['TCKT'],
  'DD':       ['Điều dưỡng', 'Công Đoàn', 'CSKH', 'Đoàn Thanh Niên'],
  'GMHS':     ['GMHS'],
  'DUOC':     ['Dược'],
  'QLCL':     ['QLCL'],
  'CONGDOAN': ['Công Đoàn'],
  'DTN':      ['Đoàn Thanh Niên'],
  'KCC':      ['K.Cấp cứu'],
  'YHCT':     ['YHCT'],
  'PHCN':     ['K.PHCN'],
  'KNOI':     ['K.Nội'],
  'KNGOAI':   ['K.Ngoại'],
};

let AUTH = null;

/* Populate hero stats on login screen */
(function() {
  const tasks = (window.__D && window.__D.tasks) ? window.__D.tasks : [];
  const total = tasks.length;
  const depts = new Set(tasks.map(t => t.phong_chinh).filter(Boolean)).size;
  const done  = tasks.filter(t => t.trang_thai === 'da_hoan_thanh').length;
  const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
  set('lh-total', total || '—');
  set('lh-depts', depts || '—');
  set('lh-done',  done  || '—');
})();

function doLogin() {
  const user = (document.getElementById('login-user').value || '').trim().toUpperCase();
  const pass  = document.getElementById('login-pass').value || '';
  const errEl = document.getElementById('login-err');
  if (!(user in USERS) || pass !== PASS) {
    errEl.style.display = 'block';
    document.getElementById('login-pass').value = '';
    return;
  }
  errEl.style.display = 'none';
  AUTH = { user, depts: USERS[user] };
  const remember = document.getElementById('login-remember').checked;
  if (remember) {
    localStorage.setItem('bvtd_auth', JSON.stringify(AUTH));
    sessionStorage.removeItem('bvtd_auth');
  } else {
    sessionStorage.setItem('bvtd_auth', JSON.stringify(AUTH));
    localStorage.removeItem('bvtd_auth');
  }
  document.getElementById('login-overlay').style.display = 'none';
  document.getElementById('app-body').style.display = 'flex';
  document.getElementById('user-badge').textContent = AUTH.user;
  initApp();
  switchView('dashboard');
  startFbListener();
}

function doLogout() {
  sessionStorage.removeItem('bvtd_auth');
  localStorage.removeItem('bvtd_auth');
  AUTH = null;
  if (_monthlyChart) { try { _monthlyChart.destroy(); } catch(e) {} _monthlyChart = null; }
  if (_nhomChart)    { try { _nhomChart.destroy();    } catch(e) {} _nhomChart = null; }
  chartsInited = false; tasksRendered = false;
  window._myTasks = null; window._myStats = null;
  const deptFilter = document.getElementById('filter-dept');
  while (deptFilter.options.length > 1) deptFilter.remove(1);
  const bbFilter = document.getElementById('filter-bienban');
  while (bbFilter.options.length > 1) bbFilter.remove(1);
  document.getElementById('app-body').style.display = 'none';
  document.getElementById('login-overlay').style.display = 'flex';
  document.getElementById('login-user').value = '';
  document.getElementById('login-pass').value = '';
}

// ── Mobile sidebar toggle ───────────────────────────────────────────────────────
function toggleSidebar() {
  const sb = document.querySelector('.sidebar');
  const ov = document.getElementById('mob-overlay');
  sb.classList.toggle('mob-open');
  ov.classList.toggle('open');
}
// Đóng sidebar khi chọn nav item trên mobile
document.querySelectorAll('.nav-item').forEach(el => {
  el.addEventListener('click', () => {
    if (window.innerWidth <= 640) {
      document.querySelector('.sidebar').classList.remove('mob-open');
      document.getElementById('mob-overlay').classList.remove('open');
    }
  });
});

// ── Helpers ────────────────────────────────────────────────────────────────────
function fmtDate(s) {
  if (!s) return '—';
  const p = s.split('-');
  return p.length === 3 ? p[2]+'/'+p[1]+'/'+p[0] : s;
}

const AC = ['#4299e1','#48bb78','#ed8936','#9f7aea','#f56565','#38b2ac','#667eea','#fc8181','#68d391','#63b3ed','#b794f4','#fbb6ce'];
function avatarColor(name) {
  let h = 0;
  for (let c of name) h = (h * 31 + c.charCodeAt(0)) % AC.length;
  return AC[Math.abs(h) % AC.length];
}

function statusPill(tt, dk) {
  if (tt === 'da_hoan_thanh')  return '<span class="status-pill status-done">✅ Hoàn thành</span>';
  if (tt === 'dang_thuc_hien') {
    if (dk === '1') return '<span class="status-pill status-recurring">↻ Định kỳ</span>';
    return '<span class="status-pill status-active">🔄 Đang thực hiện</span>';
  }
  return '<span class="status-pill status-late">⚠️ Trễ deadline</span>';
}

function nhomLabel(n) {
  if (n === 'hanh_chanh')   return '🏢 Hành chính';
  if (n === 'chuyen_mon')   return '🔬 Chuyên môn';
  return '📋 Quản lý khác';
}

// ── Task filtering ─────────────────────────────────────────────────────────────
function getMyTasks() {
  if (!AUTH || !AUTH.depts) return D.tasks;
  return D.tasks.filter(t => {
    // Check phong_chinh (normalized in tasks_slim)
    if (AUTH.depts.some(d => t.phong === d)) return true;
    // Check phong_phoi_hop (raw, comma-separated)
    if (t.phoi_hop) {
      const parts = t.phoi_hop.split(', ').map(p => p.trim());
      if (parts.some(p => AUTH.depts.includes(p))) return true;
    }
    return false;
  });
}

// ── Stats computation from tasks ──────────────────────────────────────────────
function computeFromTasks(tasks) {
  const done   = tasks.filter(t => t.tt === 'da_hoan_thanh').length;
  const active = tasks.filter(t => t.tt === 'dang_thuc_hien').length;
  const late   = tasks.filter(t => t.tt === 'tre_deadline').length;
  const rate   = tasks.length ? Math.round(done / tasks.length * 100) : 0;

  // Dept breakdown
  const dm = {};
  tasks.forEach(t => {
    const d = t.phong || 'Khác';
    if (!dm[d]) dm[d] = {total:0,done:0,active:0,late:0};
    dm[d].total++;
    if (t.tt === 'da_hoan_thanh') dm[d].done++;
    else if (t.tt === 'dang_thuc_hien') dm[d].active++;
    else dm[d].late++;
  });
  const dept = Object.entries(dm).map(([k,v]) => ({name:k,...v})).sort((a,b) => b.total-a.total);

  // Monthly (last 8 months)
  const mm = {};
  tasks.forEach(t => {
    if (t.bat_dau && t.bat_dau.length >= 7) {
      const m = t.bat_dau.slice(0,7);
      mm[m] = (mm[m]||0) + 1;
    }
  });
  const months = Object.keys(mm).sort().slice(-8);

  // Nhom
  const nhom = {hanh_chanh:0, chuyen_mon:0, quan_ly_khac:0};
  tasks.forEach(t => { nhom[t.nhom||'quan_ly_khac']++; });

  // Urgent (late, sorted by deadline)
  const urgent = tasks.filter(t => t.tt === 'tre_deadline')
    .sort((a,b) => (a.ket_thuc||'9999').localeCompare(b.ket_thuc||'9999'));

  // Repeats (nhac >= 2)
  const repeats = tasks.filter(t => parseInt(t.nhac||'1') >= 2)
    .sort((a,b) => parseInt(b.nhac||'1') - parseInt(a.nhac||'1'));

  return {total:tasks.length, done, active, late, rate, dept,
          months, monthly_counts: months.map(m => mm[m]),
          nhom, urgent, repeats};
}

// ── App init (called after login) ─────────────────────────────────────────────
function initApp() {
  tasksRendered = false;
  const _tn = document.getElementById('tasks-by-nhom'); if (_tn) _tn.innerHTML = '';

  // Cảnh báo Firebase chưa cấu hình ngay khi mount
  if (!fbEnabled()) {
    const wb = document.getElementById('fb-warn-banner');
    if (wb) wb.style.display = 'block';
  }

  const tasks = getMyTasks();
  const st    = computeFromTasks(tasks);
  window._myTasks = tasks;
  window._myStats = st;

  // Static labels
  document.getElementById('today-label').textContent = D.today_vn || D.today;
  document.getElementById('gen-label').textContent   = 'Cập nhật: ' + D.generated;
  const _verEl = document.getElementById('ver-label');
  if (_verEl && D.version) _verEl.textContent = 'v' + D.version;

  // KPI cards
  document.getElementById('s-total').textContent   = st.total;
  document.getElementById('s-done').textContent    = st.done;
  document.getElementById('s-active').textContent  = st.active;
  document.getElementById('s-late').textContent    = st.late;
  document.getElementById('s-rate').textContent    = st.rate + '%';
  document.getElementById('urgent-count-badge').textContent = st.late;

  // Urgent list
  const urgentEl = document.getElementById('urgent-list');
  if (!st.urgent.length) {
    urgentEl.innerHTML = '<li class="no-data">Không có đầu việc trễ hạn 🎉</li>';
  } else {
    urgentEl.innerHTML = st.urgent.map(t => `
        <li class="urgent-item">
          <div class="urgent-body">
            <span class="urgent-id">${t.id}</span>
            <div class="urgent-ten">${t.ten}</div>
            <div class="urgent-phong">${t.phong}</div>
          </div>
          <div class="urgent-right">
            ${t.ket_thuc ? `<div class="date-badge red">${fmtDate(t.ket_thuc)}</div>` : ''}
            ${parseInt(t.nhac)>=2 ? `<div class="nhac-badge">🔁 ${t.nhac}x</div>` : ''}
          </div>
        </li>`).join('');
  }

  // Repeat preview (all items — tab removed, this is the only view)
  const repEl = document.getElementById('repeat-preview-list');
  const repBadge = document.getElementById('repeats-count-badge');
  if (!st.repeats.length) {
    repEl.innerHTML = '<li class="no-data">Không có nhiệm vụ nào nhắc lại.</li>';
    if (repBadge) repBadge.textContent = '';
  } else {
    if (repBadge) repBadge.textContent = st.repeats.length + ' nhiệm vụ';
    repEl.innerHTML = st.repeats.map(t => {
      const bbs = t.cac_bien_ban || [];
      const tipLines = ['🔁 Nhắc ' + t.nhac + ' lần qua các biên bản:']
        .concat(bbs.map(b => '  • ' + b));
      if (t.ket_thuc) tipLines.push('📅 Deadline: ' + fmtDate(t.ket_thuc));
      if (t.last_reminder) tipLines.push('⚠ Ngày HT không được trước: ' + fmtDate(t.last_reminder));
      const tip = tipLines.join('\\n').replace(/"/g, '&quot;');
      return `
        <li class="urgent-item">
          <div class="urgent-body">
            <span class="urgent-id">${t.id}</span>
            <div class="urgent-ten" title="${tip}" style="cursor:help;">${t.ten}</div>
            <div class="urgent-phong">${t.phong}</div>
          </div>
          <div class="urgent-right">
            <span class="nhac-badge">🔁 ${t.nhac}x nhắc</span>
            ${statusPill(t.tt, t.dk)}
          </div>
        </li>`;
    }).join('');
  }

  // Dept progress bars
  const deptEl = document.getElementById('dept-breakdown');
  deptEl.innerHTML = st.dept.map(d => {
    const dP = d.total ? Math.round(d.done/d.total*100) : 0;
    const aP = d.total ? Math.round(d.active/d.total*100) : 0;
    const lP = d.total ? Math.round(d.late/d.total*100) : 0;
    return `
      <div class="dept-progress-row">
        <div class="dp-name" title="${d.name}">${d.name}</div>
        <div class="dp-bar-wrap">
          <div class="dp-bar-done"   style="width:${dP}%"></div>
          <div class="dp-bar-active" style="width:${aP}%"></div>
          <div class="dp-bar-late"   style="width:${lP}%"></div>
        </div>
        <div class="dp-stats">
          <span class="dp-stat dp-stat-done">✅<span class="dp-num">${d.done}</span></span>
          <span class="dp-stat dp-stat-act">🔄<span class="dp-num">${d.active}</span></span>
          <span class="dp-stat dp-stat-late">⚠️<span class="dp-num">${d.late}</span></span>
          <span class="dp-stat dp-stat-total">/${d.total}</span>
        </div>
      </div>`;
  }).join('');

  // Sources grid (always full — shows all biên bản regardless of user)
  const srcEl = document.getElementById('sources-grid');
  const srcLabelEl = document.getElementById('src-count-label');
  if (!D.sources.length) {
    srcEl.innerHTML = '<p style="color:var(--muted);font-size:13px;">Chưa có dữ liệu.</p>';
  } else {
    const srcTotal = D.sources.reduce((s,x) => s+x.count, 0);
    if (srcLabelEl) srcLabelEl.textContent = D.sources.length + ' biên bản · ' + srcTotal + ' đầu việc';
    srcEl.innerHTML = D.sources.map(s => {
      const hasPdf = !!s.pdf;
      const pdfPath = hasPdf ? 'bien-ban-da-ky/' + encodeURIComponent(s.pdf) : '';
      const clickAttr = hasPdf ? `onclick="window.open('${pdfPath}','_blank')" title="Nhấn để xem biên bản PDF"` : '';
      const pdfIcon = hasPdf
        ? '<div class="source-pdf-icon">📄 Xem PDF</div>'
        : '<div class="source-no-pdf">Chưa có file</div>';
      return `
        <div class="source-card${hasPdf ? ' clickable' : ''}" ${clickAttr}>
          <div class="source-name">${s.name || ('Biên bản ' + fmtDate(s.date))}</div>
          <div class="source-count">${s.count} <span class="source-date">đầu việc</span></div>
          ${pdfIcon}
        </div>`;
    }).join('');
  }

  // BGĐ: show review nav + badge
  updateNavBadge();

  // Init charts
  initCharts(st);
}

// ── Charts ─────────────────────────────────────────────────────────────────────
let chartsInited = false;
let _monthlyChart = null, _nhomChart = null;

function initCharts(st) {
  if (typeof Chart === 'undefined') return;
  const mn = ['','T1','T2','T3','T4','T5','T6','T7','T8','T9','T10','T11','T12'];
  const monthLabels = st.months.map(m => { const [y,mo]=m.split('-'); return mn[parseInt(mo)]+'/'+y.slice(2); });

  if (chartsInited) {
    if (_monthlyChart) { _monthlyChart.data.labels = monthLabels; _monthlyChart.data.datasets[0].data = st.monthly_counts; _monthlyChart.update(); }
    if (_nhomChart)    { _nhomChart.data.datasets[0].data = [st.nhom.hanh_chanh||0, st.nhom.chuyen_mon||0, st.nhom.quan_ly_khac||0]; _nhomChart.update(); }
    return;
  }
  chartsInited = true;

  const mCtx = document.getElementById('monthly-chart').getContext('2d');
  _monthlyChart = new Chart(mCtx, {
    type: 'bar',
    data: { labels: monthLabels, datasets: [{ label:'Đầu việc mới', data:st.monthly_counts, backgroundColor:'#1A5CA8', borderRadius:7, borderSkipped:false }] },
    options: { responsive:true, plugins:{legend:{display:false}}, scales:{ y:{beginAtZero:true,grid:{color:'#f0f0f0'},ticks:{stepSize:20}}, x:{grid:{display:false}} } }
  });

  const nCtx = document.getElementById('nhom-chart').getContext('2d');
  _nhomChart = new Chart(nCtx, {
    type: 'doughnut',
    data: { labels:['Hành chính','Chuyên môn','Quản lý khác'], datasets:[{ data:[st.nhom.hanh_chanh||0,st.nhom.chuyen_mon||0,st.nhom.quan_ly_khac||0], backgroundColor:['#ed8936','#9f7aea','#4299e1'], borderWidth:3, borderColor:'#fff' }] },
    options: { responsive:true, plugins:{legend:{position:'bottom',labels:{padding:16,font:{size:12}}}} }
  });
}

// ── Tasks view (grouped by nhom → then dept) ───────────────────────────────────
let tasksRendered = false;

const NHOM_GROUPS = [
  { key: 'hanh_chanh',   label: '🏢 Hành Chính Quản Trị & VTTBYT' },
  { key: 'chuyen_mon',   label: '🔬 Chuyên Môn' },
  { key: 'quan_ly_khac', label: '📋 Quản Lý Khác' },
];

function buildTasksView(filtered) {
  const container = document.getElementById('tasks-by-nhom');
  container.innerHTML = '';

  if (!filtered.length) {
    container.innerHTML = '<div class="no-tasks-msg">Không tìm thấy đầu việc nào.</div>';
    document.getElementById('tasks-count-label').textContent = '0 đầu việc';
    return;
  }

  let totalDepts = new Set();
  const parts = [];
  const _pendingIds = new Set(fbPendingList().filter(p => p.user === AUTH.user).map(p => p.id));

  NHOM_GROUPS.forEach(nhomG => {
    const nhomTasks = filtered.filter(t => t.nhom === nhomG.key);
    if (!nhomTasks.length) return;

    const nhomDone   = nhomTasks.filter(t => t.tt === 'da_hoan_thanh').length;
    const nhomActive = nhomTasks.filter(t => t.tt === 'dang_thuc_hien').length;
    const nhomLate   = nhomTasks.filter(t => t.tt === 'tre_deadline').length;

    parts.push(`
      <div class="nhom-section-header">
        <span class="nhom-label">${nhomG.label}</span>
        <div class="dept-badges">
          ${nhomDone   ? `<span class="badge badge-green">${nhomDone} xong</span>` : ''}
          ${nhomActive ? `<span class="badge badge-blue">${nhomActive} đang</span>` : ''}
          ${nhomLate   ? `<span class="badge badge-red">${nhomLate} trễ</span>` : ''}
          <span class="badge" style="background:rgba(255,255,255,.15);color:#fff">${nhomTasks.length} task</span>
        </div>
      </div>`);

    const byDept = {};
    nhomTasks.forEach(t => {
      const d = t.phong || 'Khác';
      totalDepts.add(d);
      if (!byDept[d]) byDept[d] = [];
      byDept[d].push(t);
    });

    const depts = Object.keys(byDept).sort((a,b) => byDept[b].length - byDept[a].length);

    depts.forEach((dept, idx) => {
      const tasks  = byDept[dept];
      const done   = tasks.filter(t => t.tt === 'da_hoan_thanh').length;
      const active = tasks.filter(t => t.tt === 'dang_thuc_hien').length;
      const late   = tasks.filter(t => t.tt === 'tre_deadline').length;
      const uid    = 'ds_' + nhomG.key + '_' + idx;
      const color  = avatarColor(dept);
      const rows = tasks.map(t => {
        const nguonShort = t.nguon ? t.nguon.replace(/^Biên bản /, '') : '—';
        const canUpd = AUTH && (t.tt === 'tre_deadline' || t.tt === 'dang_thuc_hien' || (isBGD() && t.tt === 'da_hoan_thanh'));
        const updLabel = isBGD() ? '✏ Cập nhật' : '✏ Báo cáo';
        const alreadySent = !isBGD() && canUpd && _pendingIds.has(t.id);
        const updBtn = canUpd
          ? (alreadySent
              ? `<button class="btn-upd btn-sent" data-id="${t.id}" data-ten="${t.ten.replace(/"/g,'&quot;')}" data-phong="${t.phong}" data-phoi="${t.phoi_hop||''}" onclick="openUpd(this.dataset.id,this.dataset.ten,this.dataset.phong,this.dataset.phoi)">↺ Cập nhật lại</button>`
              : `<button class="btn-upd" data-id="${t.id}" data-ten="${t.ten.replace(/"/g,'&quot;')}" data-phong="${t.phong}" data-phoi="${t.phoi_hop||''}" onclick="openUpd(this.dataset.id,this.dataset.ten,this.dataset.phong,this.dataset.phoi)">${updLabel}</button>`)
          : '';
        return `<tr>
          <td class="task-id">${t.id}</td>
          <td class="task-ten">${t.ten}${parseInt(t.nhac)>=2?`<span class="task-nhac">🔁${t.nhac}x</span>`:''}</td>
          <td class="col-hide-mobile"><span style="font-size:11px;color:var(--muted)">${t.phoi_hop||'—'}</span></td>
          <td class="col-hide-mobile" style="white-space:nowrap;font-size:12px">${fmtDate(t.bat_dau)}</td>
          <td class="task-deadline" style="white-space:nowrap;font-size:12px">${t.ket_thuc?fmtDate(t.ket_thuc):'—'}</td>
          <td class="nguon-cell col-hide-mobile" title="${t.nguon}">${nguonShort}</td>
          <td class="task-status">${statusPill(t.tt, t.dk)}${updBtn}</td>
        </tr>`;
      }).join('');

      parts.push(`
        <div class="dept-section">
          <div class="dept-section-header" onclick="toggleDept('${uid}')">
            <div class="dept-section-avatar" style="background:${color}">${dept.slice(0,4)}</div>
            <div class="dept-section-name">${dept}</div>
            <div class="dept-badges">
              ${done   ? `<span class="badge badge-green">${done} xong</span>`  : ''}
              ${active ? `<span class="badge badge-blue">${active} đang</span>` : ''}
              ${late   ? `<span class="badge badge-red">${late} trễ</span>`     : ''}
              <span class="badge badge-gray">${tasks.length} task</span>
            </div>
            <span class="toggle-ic" id="ic-${uid}">▼</span>
          </div>
          <div class="task-table-wrap" id="${uid}">
            <table class="task-table">
              <thead><tr>
                <th>ID</th><th>Đầu việc</th><th class="col-hide-mobile">Phối hợp</th>
                <th class="col-hide-mobile">Bắt đầu</th><th>Deadline</th><th class="col-hide-mobile">Biên Bản</th><th>Trạng thái</th>
              </tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>`);
    });
  });

  container.innerHTML = parts.join('');

  document.getElementById('tasks-count-label').textContent =
    `${filtered.length} đầu việc · ${totalDepts.size} phòng ban`;
}

function toggleDept(uid) {
  const el   = document.getElementById(uid);
  const icon = document.getElementById('ic-' + uid);
  el.classList.toggle('hidden');
  if (icon) icon.textContent = el.classList.contains('hidden') ? '▶' : '▼';
}

function filterTasks() {
  const nhom     = document.getElementById('filter-nhom').value;
  const status   = document.getElementById('filter-status').value;
  const dept     = document.getElementById('filter-dept').value;
  const bienban  = document.getElementById('filter-bienban').value;
  const search   = (document.getElementById('filter-search').value || '').toLowerCase().trim();

  const base = window._myTasks || D.tasks;
  const filtered = base.filter(t => {
    if (nhom && t.nhom !== nhom) return false;
    if (status === 'chua_xong') { if (t.tt === 'da_hoan_thanh') return false; }
    else if (status && t.tt !== status) return false;
    if (dept    && t.phong !== dept)    return false;
    if (bienban && t.nguon !== bienban) return false;
    if (search && !t.ten.toLowerCase().includes(search) && !t.phong.toLowerCase().includes(search)) return false;
    return true;
  });
  buildTasksView(filtered);
}

function initTasksView() {
  if (tasksRendered) return;
  tasksRendered = true;

  const myTasks = window._myTasks || D.tasks;
  const deptFilter = document.getElementById('filter-dept');
  [...new Set(myTasks.map(t => t.phong || 'Khác'))].sort().forEach(d => {
    const o = document.createElement('option');
    o.value = d; o.textContent = d;
    deptFilter.appendChild(o);
  });
  const bbFilter = document.getElementById('filter-bienban');
  const bbSortKey = s => {
    const m = s.match(/(\\d{2})\\/(\\d{2})\\/(\\d{4})\\s*$/);
    if (!m) return 0;
    return parseInt(m[3]) * 10000 + parseInt(m[2]) * 100 + parseInt(m[1]);
  };
  [...new Set(myTasks.map(t => t.nguon || '').filter(Boolean))]
    .sort((a, b) => bbSortKey(b) - bbSortKey(a))
    .forEach(bb => {
      const o = document.createElement('option');
      o.value = bb; o.textContent = bb.replace(/^Biên bản /, '');
      bbFilter.appendChild(o);
    });
  // Default: chỉ hiện trễ + đang làm
  document.getElementById('filter-status').value = 'chua_xong';
  // Auto-select phòng khi user chỉ thuộc 1 phòng
  if (AUTH && AUTH.depts && AUTH.depts.length === 1) {
    deptFilter.value = AUTH.depts[0];
  }
  filterTasks();
}

// ── Debounce helpers ───────────────────────────────────────────────────────────
let _dbSearchT, _dbFilterT;
function _dbSearch(v) { clearTimeout(_dbSearchT); _dbSearchT = setTimeout(() => handleDashSearch(v), 200); }
function _dbFilter()  { clearTimeout(_dbFilterT); _dbFilterT = setTimeout(filterTasks, 200); }

// ── Dashboard search ───────────────────────────────────────────────────────────
function handleDashSearch(val) {
  const q = val.toLowerCase().trim();
  const resEl  = document.getElementById('dash-search-results');
  const listEl = document.getElementById('dash-search-list');
  if (!q) { resEl.style.display = 'none'; return; }

  const found = (window._myTasks || D.tasks).filter(t =>
    t.ten.toLowerCase().includes(q) || t.phong.toLowerCase().includes(q)
  ).slice(0, 20);

  resEl.style.display = 'block';
  if (!found.length) {
    listEl.innerHTML = '<p style="color:var(--muted);padding:12px 0">Không tìm thấy.</p>';
    return;
  }

  let html = '<table class="search-result-table"><thead><tr><th>ID</th><th>Đầu việc</th><th>Phòng</th><th>Deadline</th><th>Biên Bản</th><th>Trạng thái</th></tr></thead><tbody>';
  found.forEach(t => {
    const nguonShort = t.nguon ? t.nguon.replace(/^Biên bản /, '') : '—';
    html += `<tr>
      <td class="task-id">${t.id}</td>
      <td style="max-width:300px">${t.ten}</td>
      <td style="font-size:12px">${t.phong}</td>
      <td style="font-size:12px;white-space:nowrap">${fmtDate(t.ket_thuc)}</td>
      <td class="nguon-cell">${nguonShort}</td>
      <td>${statusPill(t.tt, t.dk)}</td>
    </tr>`;
  });
  html += '</tbody></table>';
  listEl.innerHTML = html;
}

function clearDashSearch() {
  document.getElementById('dash-search').value = '';
  document.getElementById('dash-search-results').style.display = 'none';
}

// ── Nhật Ký ────────────────────────────────────────────────────────────────────
let _logInited = false;

function _logStatusCss(tt) {
  if (tt === 'da_hoan_thanh') return 'done';
  if (tt === 'dang_thuc_hien') return 'active';
  if (tt === 'tre_deadline') return 'late';
  return 'other';
}
function _logStatusLabel(tt) {
  if (tt === 'da_hoan_thanh') return '✅ Hoàn thành';
  if (tt === 'dang_thuc_hien') return '🔄 Đang làm';
  if (tt === 'tre_deadline') return '⚠️ Trễ deadline';
  return tt || '—';
}

function initLogView() {
  if (!isBGD()) { switchView('dashboard'); return; }
  const allLog = (window.__D && window.__D.log) ? window.__D.log : [];
  // BGD sees all
  const myDepts = null;
  const accessible = myDepts
    ? allLog.filter(r => myDepts.includes(r.phong_bao_cao) || myDepts.includes(r.phong_chinh))
    : allLog;

  if (!_logInited) {
    // Populate user dropdown
    const users = [...new Set(accessible.map(r => r.user).filter(Boolean))].sort();
    const uSel = document.getElementById('log-flt-user');
    users.forEach(u => { const o = document.createElement('option'); o.value = u; o.textContent = u; uSel.appendChild(o); });

    // Populate phong dropdown
    const phongs = [...new Set(accessible.map(r => r.phong_bao_cao).filter(Boolean))].sort();
    const pSel = document.getElementById('log-flt-phong');
    phongs.forEach(p => { const o = document.createElement('option'); o.value = p; o.textContent = p; pSel.appendChild(o); });

    _logInited = true;
  }
  window._logData = accessible;
  renderLog();
}

function renderLog() {
  const rows = window._logData || [];
  const q = (document.getElementById('log-search')?.value || '').toLowerCase();
  const fUser = document.getElementById('log-flt-user')?.value || '';
  const fPhong = document.getElementById('log-flt-phong')?.value || '';
  const fTT = document.getElementById('log-flt-tt')?.value || '';

  const filtered = rows.filter(r => {
    if (fUser  && r.user !== fUser) return false;
    if (fPhong && r.phong_bao_cao !== fPhong) return false;
    if (fTT   && r.trang_thai_moi !== fTT) return false;
    if (q && !(
      (r.ten_dau_viec || '').toLowerCase().includes(q) ||
      (r.ghi_chu || '').toLowerCase().includes(q)
    )) return false;
    return true;
  });

  const tbody = document.getElementById('log-tbody');
  const empty = document.getElementById('log-empty');
  const countEl = document.getElementById('log-count');
  if (!tbody) return;

  countEl.textContent = filtered.length + ' bản ghi';

  if (!filtered.length) {
    tbody.innerHTML = '';
    empty.style.display = '';
    return;
  }
  empty.style.display = 'none';

  tbody.innerHTML = filtered.map(r => {
    const ttOld = r.trang_thai_cu ? `<span class="log-status ${_logStatusCss(r.trang_thai_cu)}">${_logStatusLabel(r.trang_thai_cu)}</span>` : '<span class="log-src">—</span>';
    const ttNew = r.trang_thai_moi ? `<span class="log-status ${_logStatusCss(r.trang_thai_moi)}">${_logStatusLabel(r.trang_thai_moi)}</span>` : '<span class="log-src">—</span>';
    const change = ttOld + '<span class="log-arrow">→</span>' + ttNew;
    const taskLabel = r.task_id ? `<span style="font-size:11px;color:var(--muted)">#${r.task_id}</span> ` : '';
    const nguonMap = {dashboard_auto:'auto', dashboard:'dashboard', check_chat:'check', apply_pending:'apply'};
    const nguon = nguonMap[r.nguon] || (r.nguon || '—');
    const mayVal = r.may || '';
    const ipVal  = r.ip  || '';
    const device = mayVal || ipVal
      ? `<span style="font-size:11px;display:block;color:var(--text)">${mayVal}</span><span style="font-size:11px;color:var(--muted)">${ipVal}</span>`
      : '<span class="log-src">—</span>';
    return `<tr>
      <td style="white-space:nowrap;font-size:12px">${r.ngay_cap_nhat || '—'}</td>
      <td><span class="log-badge-user">${r.user || '—'}</span></td>
      <td style="font-size:12px">${r.phong_bao_cao || '—'}</td>
      <td>${taskLabel}<span style="font-size:12px">${r.ten_dau_viec || '—'}</span></td>
      <td style="white-space:nowrap">${change}</td>
      <td style="font-size:12px;color:var(--muted)">${r.ghi_chu || ''}</td>
      <td class="log-src">${nguon}</td>
      <td style="min-width:120px">${device}</td>
    </tr>`;
  }).join('');
}

// ── View routing ───────────────────────────────────────────────────────────────
function switchView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item[data-view]').forEach(n => n.classList.remove('active'));
  const v = document.getElementById('view-' + name);
  if (v) v.classList.add('active');
  const n = document.querySelector(`[data-view="${name}"]`);
  if (n) n.classList.add('active');
  if (name === 'tasks')  initTasksView();
  if (name === 'review') renderReview();
  if (name === 'log')    initLogView();
}

document.querySelectorAll('[data-view]').forEach(el => {
  el.addEventListener('click', () => switchView(el.dataset.view));
});

// ── Firebase Realtime DB — pending updates (sync across devices) ───────────────
const FB_CFG = window.__FB_CONFIG || {};
const AK = 'bvtd_approved';
const TT_LABELS = {da_hoan_thanh:'✅ Hoàn thành', dang_thuc_hien:'🔄 Đang làm', tre_deadline:'⚠️ Trễ Deadline'};
let _updTask = null;
let _db = null;
let _fbPending = {};  // { "USER_taskId": entry } — synced by real-time listener

function isBGD() { return AUTH && AUTH.user === 'BGD'; }
function lsGet(k) { try { return JSON.parse(localStorage.getItem(k)||'[]'); } catch(e) { return []; } }
function lsSave(k, v) { localStorage.setItem(k, JSON.stringify(v)); }
function fbKey(user, id) { return user + '_' + id; }
function fbEnabled() { return !!(FB_CFG && FB_CFG.databaseURL); }
function normalizePending(e) {
  // Handle legacy migration format (task_id/task_ten) and missing at/user fields
  return {
    id:         e.id      || e.task_id  || '',
    ten:        e.ten     || e.task_ten || '',
    phong:      e.phong   || '',
    trang_thai: e.trang_thai || e.tt || '',
    ngay_ht:    e.ngay_ht || e.ngay_hoan_thanh || '',
    ghi_chu:    e.ghi_chu || '',
    user:       e.user    || e.phong   || '',
    user_phong: e.user_phong || e.phong || '',
    at:         e.at      || (e.timestamp ? new Date(e.timestamp).toISOString().slice(0,10) : ''),
    migrated:   e.migrated || false,
  };
}
function fbPendingList() { return Object.values(_fbPending).map(normalizePending); }

function fbInit() {
  if (_db) return true;
  if (!fbEnabled()) return false;
  try {
    if (!firebase.apps.length) firebase.initializeApp(FB_CFG);
    _db = firebase.database();
    return true;
  } catch(e) { console.warn('Firebase init error:', e); return false; }
}

function startFbListener() {
  if (!fbInit()) return;
  _db.ref('bvtd_pending').on('value', snap => {
    _fbPending = snap.val() || {};
    updateNavBadge();
    if (document.getElementById('view-review')?.classList.contains('active')) {
      renderPending();
      renderReview();
    }
  });
  migrateLocalStorage();
}

function showBanner(msg, isOk) {
  let b = document.getElementById('_toast-banner');
  if (!b) {
    b = document.createElement('div');
    b.id = '_toast-banner';
    b.style.cssText = 'position:fixed;bottom:20px;left:50%;transform:translateX(-50%);z-index:400;padding:12px 20px;border-radius:8px;font-size:13px;font-weight:600;box-shadow:0 4px 12px rgba(0,0,0,.15);max-width:90vw;text-align:center;transition:opacity .3s;';
    document.body.appendChild(b);
  }
  b.style.background = isOk ? '#f0fff4' : '#fff5f5';
  b.style.color = isOk ? '#276749' : '#c53030';
  b.style.border = isOk ? '1px solid #9ae6b4' : '1px solid #feb2b2';
  b.style.opacity = '1';
  b.textContent = msg;
  clearTimeout(b._t);
  b._t = setTimeout(() => { b.style.opacity = '0'; }, 3500);
}

function migrateLocalStorage() {
  const OLD_KEY = 'bvtd_pending';
  let old = [];
  try { old = JSON.parse(localStorage.getItem(OLD_KEY) || '[]'); } catch(e) {}
  if (!Array.isArray(old) || old.length === 0) return;
  const myPending = old.filter(e => e.phong === AUTH.user || (AUTH.depts && AUTH.depts.includes(e.phong)));
  if (myPending.length === 0) { localStorage.removeItem(OLD_KEY); return; }
  showBanner('🔄 Đang đồng bộ ' + myPending.length + ' báo cáo cũ lên Firebase…', true);
  let ok = 0;
  myPending.forEach(e => {
    const id    = e.id || e.task_id || '';
    const user  = e.user || e.phong || AUTH.user || '';
    const key   = fbKey(user, id) || (Date.now() + '_' + (e.phong || 'unknown'));
    const entry = {
      id,
      ten:        e.ten || e.task_ten || '',
      phong:      e.phong || '',
      trang_thai: e.trang_thai || e.tt || '',
      ngay_ht:    e.ngay_ht || e.ngay_hoan_thanh || e.ngay || '',
      ghi_chu:    e.ghi_chu || e.note || '',
      user,
      user_phong: e.user_phong || e.phong || '',
      at:         e.at || (e.timestamp ? new Date(e.timestamp).toISOString().slice(0,10) : new Date().toISOString().slice(0,10)),
      migrated:   true,
    };
    _db.ref('bvtd_pending/' + key).set(entry).then(() => ok++);
  });
  localStorage.removeItem(OLD_KEY);
  setTimeout(() => showBanner('✅ Đã đồng bộ ' + myPending.length + ' báo cáo lên Firebase thành công!', true), 1000);
}

function fmtDateInput(el) {
  let v = el.value.replace(/[^\\d]/g, '');
  if (v.length > 2) v = v.slice(0,2) + '/' + v.slice(2);
  if (v.length > 5) v = v.slice(0,5) + '/' + v.slice(5,9);
  el.value = v;
}

function openUpd(id, ten, phong, phoi) {
  _updTask = {id, ten, phong, phoi: phoi || ''};
  document.getElementById('upd-sub').textContent = id + ' — ' + ten + ' (' + phong + ')';
  document.getElementById('upd-tt').value = '';
  document.getElementById('upd-ngay').value = new Date().toISOString().slice(0, 10);
  document.getElementById('upd-note').value = '';
  document.getElementById('upd-ngay-wrap').style.display = '';
  document.getElementById('upd-msg').style.display = 'none';
  document.getElementById('upd-modal').style.display = 'flex';
}
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('upd-tt').addEventListener('change', function() {
    const wrap = document.getElementById('upd-ngay-wrap');
    wrap.style.display = this.value === 'dang_thuc_hien' ? 'none' : '';
    if (this.value === 'dang_thuc_hien') document.getElementById('upd-ngay').value = '';
  });
});
function closeUpd() { document.getElementById('upd-modal').style.display = 'none'; }
function showUpdMsg(msg, isErr) {
  const el = document.getElementById('upd-msg');
  el.textContent = msg;
  el.className = isErr ? 'msg-err' : 'msg-ok';
  el.style.display = 'block';
}

// ── Device / IP capture ────────────────────────────────────────────────────────
function _getDeviceInfo() {
  const ua = navigator.userAgent;
  let os = 'Unknown';
  if (/Windows NT/.test(ua))        os = 'Windows';
  else if (/Mac OS X/.test(ua))     os = 'Mac';
  else if (/Android/.test(ua))      os = 'Android';
  else if (/iPhone|iPad/.test(ua))  os = 'iOS';
  else if (/Linux/.test(ua))        os = 'Linux';
  let br = 'Unknown';
  if (/Edg\\//.test(ua))            br = 'Edge';
  else if (/Chrome\\//.test(ua))    br = 'Chrome';
  else if (/Firefox\\//.test(ua))   br = 'Firefox';
  else if (/Safari\\//.test(ua))    br = 'Safari';
  return os + ' / ' + br;
}

function _getLocalIP() {
  return new Promise(resolve => {
    try {
      const pc = new RTCPeerConnection({iceServers: []});
      pc.createDataChannel('');
      pc.createOffer().then(o => pc.setLocalDescription(o)).catch(() => resolve('—'));
      const found = new Set();
      pc.onicecandidate = e => {
        if (!e.candidate) { pc.close(); resolve(found.size ? [...found].join(', ') : '—'); return; }
        const m = /(\\d{1,3}(?:\\.\\d{1,3}){3})/.exec(e.candidate.candidate);
        if (m && !m[1].startsWith('127.') && !m[1].startsWith('0.')) found.add(m[1]);
      };
      setTimeout(() => { try { pc.close(); } catch(_){} resolve(found.size ? [...found].join(', ') : '—'); }, 1500);
    } catch(_) { resolve('—'); }
  });
}

async function submitUpd() {
  if (!_updTask) return;
  const tt = document.getElementById('upd-tt').value;
  let ngayRaw = document.getElementById('upd-ngay').value.trim();
  const note = document.getElementById('upd-note').value.trim();
  if (!tt) { showUpdMsg('Vui lòng chọn trạng thái.', true); return; }
  if (tt === 'da_hoan_thanh' && !ngayRaw) { showUpdMsg('Vui lòng nhập ngày hoàn thành.', true); return; }
  let ngay = '';
  if (ngayRaw) {
    if (/^\\d{4}-\\d{2}-\\d{2}$/.test(ngayRaw)) {
      ngay = ngayRaw;
    } else {
      showUpdMsg('Ngày không hợp lệ. Vui lòng chọn ngày từ lịch.', true); return;
    }
    // Kiểm tra ngày HT >= ngày nhắc cuối (task nhắc >= 2 lần)
    const _tr = (window._myTasks || D.tasks).find(t => t.id === _updTask.id);
    if (_tr && parseInt(_tr.nhac || '1') >= 2 && _tr.last_reminder && ngay < _tr.last_reminder) {
      showUpdMsg('❌ Ngày hoàn thành không hợp lệ! Nhiệm vụ này đã bị nhắc ' + _tr.nhac + ' lần — lần nhắc cuối: ' + fmtDate(_tr.last_reminder) + '. Ngày hoàn thành phải từ ' + fmtDate(_tr.last_reminder) + ' trở đi.', true);
      return;
    }
  }
  // Kiểm tra user báo cáo là phòng chính hay chỉ phối hợp (BGD depts=null → xem tất cả)
  const isPhongChinh = !AUTH.depts || AUTH.depts.some(d => d === _updTask.phong);
  const isPhongPhoi = !isPhongChinh && _updTask.phoi && AUTH.depts && AUTH.depts.some(d =>
    _updTask.phoi.split(', ').map(p => p.trim()).includes(d)
  );
  let finalNote = note || '';
  if (isPhongPhoi) {
    const flag = `⚠️ Báo cáo từ phòng phối hợp (${AUTH.user}) — cần kiểm tra lại với phòng chính (${_updTask.phong})`;
    finalNote = finalNote ? flag + ' | ' + finalNote : flag;
  }
  const userPhong = AUTH.depts ? AUTH.depts.join(', ') : AUTH.user;
  const [localIP] = await Promise.all([_getLocalIP()]);
  const entry = {id:_updTask.id, ten:_updTask.ten, phong:_updTask.phong,
                 trang_thai:tt, ngay_ht:ngay, ghi_chu:finalNote, user:AUTH.user,
                 user_phong:userPhong,
                 may:_getDeviceInfo(), ip:localIP,
                 at:new Date().toISOString().slice(0,10)};
  if (isBGD()) {
    // BGĐ → thẳng vào approved queue, xuất JSON rồi chạy /check
    const appr = lsGet(AK);
    const idx = appr.findIndex(a => a.id === _updTask.id);
    if (idx >= 0) appr[idx] = entry; else appr.push(entry);
    lsSave(AK, appr);
    showUpdMsg('✓ Đã lưu. Nhấn "Xuất JSON" trong panel bên dưới để áp dụng vào database.', false);
    setTimeout(() => { closeUpd(); renderPending(); }, 1200);
  } else {
    // Phòng ban → Firebase pending (real-time, hiển thị ngay trên BGĐ dashboard)
    if (!fbEnabled()) {
      showUpdMsg('❌ Firebase chưa cấu hình — liên hệ CNTT để kích hoạt đồng bộ báo cáo.', true);
      return;
    }
    if (!fbInit()) {
      showUpdMsg('❌ Không thể kết nối Firebase. Kiểm tra internet và thử lại.', true);
      return;
    }
    const key = fbKey(AUTH.user, _updTask.id);
    const _btn = document.querySelector(`button.btn-upd[data-id="${_updTask.id}"]`);
    _db.ref('bvtd_pending/' + key).set(entry)
      .then(() => {
        _fbPending[key] = entry;
        if (_btn) {
          _btn.textContent = '↺ Cập nhật lại';
          _btn.classList.add('btn-sent');
          const pill = _btn.closest('td') && _btn.closest('td').querySelector('.status-pill');
          if (pill) {
            const lb = tt === 'da_hoan_thanh' ? 'Hoàn thành' : tt === 'dang_thuc_hien' ? 'Đang làm' : 'Trễ deadline';
            pill.textContent = '⏳ ' + lb + ' — chờ duyệt';
            pill.className = 'status-pill status-pending';
          }
        }
        showUpdMsg('✓ Đã gửi báo cáo. BGĐ sẽ thấy ngay trên dashboard.', false);
        setTimeout(closeUpd, 1500);
      })
      .catch(e => showUpdMsg('❌ Lỗi gửi: ' + e.message, true));
  }
}

// ── Review view (BGĐ only) ────────────────────────────────────────────────────
function renderReview() {
  if (!isBGD()) return;
  const approved = lsGet(AK);
  const doneKeys = new Set(approved.map(a => a.id + '|' + a.user));
  const pending  = fbPendingList().filter(p => !doneKeys.has(p.id + '|' + p.user));
  const depts    = new Set(pending.map(p => p.user));

  // KPI cards + sticky chips
  document.getElementById('rv-pending-count').textContent  = pending.length;
  document.getElementById('rv-approved-count').textContent = approved.length;
  document.getElementById('rv-depts-count').textContent    = depts.size;
  document.getElementById('rv-pending-badge').textContent  = pending.length;
  document.getElementById('rv-approved-badge').textContent = approved.length;
  document.getElementById('rv-chip-pending').textContent   = pending.length;
  document.getElementById('rv-chip-approved').textContent  = approved.length;
  document.getElementById('rv-chip-dept').textContent      = depts.size;
  document.getElementById('review-subtitle').textContent   =
    pending.length
      ? pending.length + ' cập nhật đang chờ từ ' + depts.size + ' phòng ban'
      : 'Không có cập nhật nào đang chờ duyệt';

  // Pending list
  const pendEl = document.getElementById('rv-pending-list');
  if (!pending.length) {
    pendEl.innerHTML = '<div class="rv-empty">🎉 Không có cập nhật nào đang chờ duyệt</div>';
  } else {
    const grouped = {};
    pending.forEach(p => { if (!grouped[p.id]) grouped[p.id] = []; grouped[p.id].push(p); });
    pendEl.innerHTML = Object.values(grouped).map(grp => {
      const first = grp[0];
      const task  = D.tasks.find(t => t.id === first.id);
      const curTT = task ? statusPill(task.tt, task.dk) : '';
      const taskMeta = task ? [
        task.ket_thuc ? `⏰ Deadline: <b>${fmtDate(task.ket_thuc)}</b>` : `<span style="color:var(--muted)">Không có deadline</span>`,
        task.bat_dau  ? `📅 Giao: ${fmtDate(task.bat_dau)}` : '',
        task.phoi_hop ? `🤝 Phối hợp: ${task.phoi_hop}` : '',
        task.nguon    ? `📄 ${task.nguon}` : '',
      ].filter(Boolean).join(' &ensp;·&ensp; ') : '';
      const reporters = grp.map(p => `
        <div class="rv-reporter">
          <span class="rv-reporter-phong">${p.user_phong || p.user}</span>
          <div class="rv-reporter-body">
            <div style="font-size:13px;font-weight:600;">${TT_LABELS[p.trang_thai] || p.trang_thai || '—'}</div>
            ${p.ngay_ht ? `<div class="rv-item-meta">📅 Ngày hoàn thành: <b>${p.ngay_ht}</b></div>` : ''}
            ${p.ghi_chu ? `<div class="rv-item-meta">📝 ${p.ghi_chu}</div>` : ''}
            <div class="rv-item-meta" style="margin-top:4px;">Báo cáo ngày ${p.at}</div>
          </div>
          <div class="rv-reporter-actions">
            <button class="btn-appr" onclick="approveUpd('${p.id}','${p.user}')">✓ Duyệt</button>
            <button class="btn-rejt"  onclick="rejectUpd('${p.id}','${p.user}')">✕ Từ chối</button>
          </div>
        </div>`).join('');
      return `
        <div class="rv-item pending-color">
          <div class="rv-item-hdr">
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                <span class="task-id">${first.id}</span>
                <span style="font-size:14px;font-weight:700;">${first.ten}</span>
              </div>
              <div class="rv-item-meta" style="margin-top:6px;">
                Phòng chính: <b>${first.phong}</b>&ensp;|&ensp;Trạng thái hiện tại: ${curTT}
              </div>
              ${taskMeta ? `<div class="rv-item-meta" style="margin-top:4px;">${taskMeta}</div>` : ''}
            </div>
            ${grp.length > 1 ? `<span class="badge badge-orange">${grp.length} phòng</span>` : ''}
          </div>
          ${reporters}
        </div>`;
    }).join('');
  }

  // Approved list
  const apprEl = document.getElementById('rv-approved-list');
  const expBtn = document.getElementById('rv-export-btn');
  if (!approved.length) {
    apprEl.innerHTML = '<div class="rv-empty" style="padding:20px 0;">Chưa có mục nào được duyệt.</div>';
    if (expBtn) expBtn.style.display = 'none';
  } else {
    apprEl.innerHTML = approved.map(a => `
      <div class="rv-item approved-color">
        <div class="rv-item-hdr">
          <div style="flex:1;min-width:0;">
            <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
              <span class="task-id">${a.id}</span>
              <span style="font-size:14px;font-weight:700;">${a.ten}</span>
            </div>
            <div class="rv-item-meta" style="margin-top:4px;">
              Phòng: <b>${a.user_phong || a.user}</b> &ensp;·&ensp; Phòng chính: ${a.phong} &ensp;·&ensp; ngày ${a.at}
            </div>
            ${TT_LABELS[a.trang_thai] ? `<div class="rv-item-meta" style="margin-top:4px;">${TT_LABELS[a.trang_thai]}</div>` : ''}
            ${a.ngay_ht ? `<div class="rv-item-meta">📅 Ngày hoàn thành: <b>${a.ngay_ht}</b></div>` : ''}
            ${a.ghi_chu ? `<div class="rv-item-meta">📝 ${a.ghi_chu}</div>` : ''}
          </div>
          <button class="btn-rejt" style="flex-shrink:0;align-self:flex-start;" onclick="removeApproved('${a.id}')">✕ Bỏ</button>
        </div>
      </div>`).join('');
    if (expBtn) expBtn.style.display = '';
  }

  updateNavBadge();
}

function updateNavBadge() {
  const navEl = document.getElementById('nav-review');
  const badge = document.getElementById('nav-review-badge');
  const navLog = document.getElementById('nav-log');
  if (!isBGD()) {
    if (navEl)  { navEl.style.display  = 'none'; navEl.setAttribute('aria-hidden','true');  }
    if (navLog) { navLog.style.display = 'none'; navLog.setAttribute('aria-hidden','true'); }
    return;
  }
  if (navEl)  { navEl.style.display  = 'flex'; navEl.removeAttribute('aria-hidden');  }
  if (navLog) { navLog.style.display = 'flex'; navLog.removeAttribute('aria-hidden'); }
  const approved  = lsGet(AK);
  const doneKeys  = new Set(approved.map(a => a.id + '|' + a.user));
  const count     = fbPendingList().filter(p => !doneKeys.has(p.id + '|' + p.user)).length;
  if (badge) {
    badge.textContent   = count;
    badge.style.display = count > 0 ? 'inline-flex' : 'none';
  }
}

function renderPending() {
  const panel = document.getElementById('pending-panel');
  if (!panel || !isBGD()) { if (panel) panel.innerHTML = ''; return; }
  const approvedItems = lsGet(AK);
  const doneKeys2 = new Set(approvedItems.map(a => a.id + '|' + a.user));
  const pendingItems = fbPendingList().filter(p => !doneKeys2.has(p.id + '|' + p.user));
  if (!pendingItems.length && !approvedItems.length) { panel.innerHTML = ''; return; }

  let h = '<div class="pending-panel">';

  if (pendingItems.length) {
    h += `<div class="pending-hdr" style="margin-bottom:8px;display:flex;justify-content:space-between;align-items:center;">
      <span>⏳ Chờ duyệt — ${pendingItems.length} cập nhật từ phòng ban</span>
      ${pendingItems.length > 2 ? `<button class="btn-appr" onclick="approveAll()" style="font-size:12px;padding:5px 12px;">✅ Duyệt tất cả</button>` : ''}
    </div>`;
    // Group theo task ID
    const grouped = {};
    pendingItems.forEach(p => { if (!grouped[p.id]) grouped[p.id] = []; grouped[p.id].push(p); });
    Object.values(grouped).forEach(grp => {
      const first = grp[0];
      const multiPhong = grp.length > 1;
      h += `<div class="pending-item" style="${multiPhong?'border-left:3px solid #f6ad55;':''}">
        <div class="pending-info" style="width:100%;">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px;">
            <span class="task-id">${first.id}</span>
            <div class="pending-name" style="margin:0;">${first.ten}</div>
            <span style="font-size:11px;color:#718096;margin-left:auto;">Phòng chính: <b>${first.phong}</b></span>
          </div>
          ${grp.map((p,i) => `
          <div style="border:1px solid #e2e8f0;border-radius:6px;padding:8px 10px;margin-bottom:${i<grp.length-1?'6px':'0'};background:${i%2===0?'#f7fafc':'#fff'};">
            <div style="display:flex;justify-content:space-between;align-items:center;">
              <span style="font-size:12px;font-weight:700;color:#2d3748;">📤 ${p.user_phong||p.user}</span>
              <span style="font-size:11px;color:#a0aec0;">ngày ${p.at}</span>
            </div>
            ${p.trang_thai?`<div class="pending-meta" style="margin-top:4px;">${TT_LABELS[p.trang_thai]||p.trang_thai}</div>`:''}
            ${p.ngay_ht?`<div class="pending-meta" style="margin-top:2px;">📅 Ngày HT: ${p.ngay_ht}</div>`:''}
            ${p.ghi_chu?`<div class="pending-meta" style="margin-top:2px;">📝 ${p.ghi_chu}</div>`:''}
            <div style="display:flex;gap:6px;margin-top:6px;">
              <button class="btn-appr" onclick="approveUpd('${p.id}','${p.user}')">✓ Duyệt</button>
              <button class="btn-rejt" onclick="rejectUpd('${p.id}','${p.user}')">✕ Từ chối</button>
            </div>
          </div>`).join('')}
        </div>
      </div>`;
    });
  }

  if (approvedItems.length) {
    if (pendingItems.length) h += '<div style="height:1px;background:var(--border);margin:12px 0;"></div>';
    h += `<div style="font-size:13px;font-weight:700;color:#276749;margin-bottom:8px;">✅ Đã duyệt / BGĐ cập nhật trực tiếp — ${approvedItems.length} mục</div>`;
    approvedItems.forEach(a => {
      h += `<div class="pending-item" style="border-color:#c6f6d5;">
        <div class="pending-info">
          <span class="task-id">${a.id}</span>
          <div class="pending-name">${a.ten}</div>
          <div class="pending-meta">${a.phong} · ${a.user} ngày ${a.at}</div>
          ${a.trang_thai?`<div class="pending-meta">${TT_LABELS[a.trang_thai]||a.trang_thai}</div>`:''}
          ${a.ngay_ht?`<div class="pending-meta">📅 Ngày HT: ${a.ngay_ht}</div>`:''}
          ${a.ghi_chu?`<div class="pending-meta">📝 ${a.ghi_chu}</div>`:''}
        </div>
        <button class="btn-rejt" style="flex-shrink:0;margin-top:4px;" onclick="removeApproved('${a.id}')">✕</button>
      </div>`;
    });
  }

  h += `<div style="margin-top:14px;display:flex;justify-content:flex-end;">
    <button class="btn-exp" onclick="exportApproved()">⬇ Xuất JSON để chạy /check (${approvedItems.length} mục)</button>
  </div>`;

  panel.innerHTML = h + '</div>';
}

// ── GitHub Auto-Upload (BGĐ) ──────────────────────────────────────────────────
const GH_TOKEN_KEY = 'bvtd_gh_token';
const GH_REPO      = 'dragonhuynh/bvtd-progress';
const GH_PATH      = 'data/pending_updates.json';

function showGHTokenSetup() {
  const cur = localStorage.getItem(GH_TOKEN_KEY) || '';
  const tok = prompt(
    'Nhập GitHub Personal Access Token\\n\\n' +
    'Cách tạo token:\\n' +
    '1. Vào github.com → Settings → Developer settings\\n' +
    '2. Personal access tokens → Fine-grained tokens → Generate new\\n' +
    '3. Repository: dragonhuynh/bvtd-progress\\n' +
    '4. Permissions: Contents → Read and write\\n\\n' +
    'Token hiện tại: ' + (cur ? cur.slice(0,8)+'...' : '(chưa có)'),
    cur
  );
  if (tok !== null) {
    localStorage.setItem(GH_TOKEN_KEY, tok.trim());
    alert(tok.trim() ? '✓ Đã lưu token.' : '✓ Đã xóa token.');
  }
}

async function uploadToGitHub() {
  const approved = lsGet(AK);
  if (!approved.length) { alert('Chưa có cập nhật nào được duyệt.'); return; }

  let token = localStorage.getItem(GH_TOKEN_KEY) || '';
  if (!token) {
    token = (prompt('Nhập GitHub Personal Access Token\\n(Chỉ cần nhập 1 lần — lưu vào bộ nhớ):') || '').trim();
    if (!token) return;
    localStorage.setItem(GH_TOKEN_KEY, token);
  }

  const btn = document.getElementById('btn-gh-upload');
  const BTN_LABEL = '📤 Gửi lên GitHub — tự động cập nhật';
  if (btn) { btn.textContent = '⏳ Đang gửi...'; btn.disabled = true; }

  const apiUrl = `https://api.github.com/repos/${GH_REPO}/contents/${GH_PATH}`;
  const headers = {
    'Authorization': `Bearer ${token}`,
    'Accept': 'application/vnd.github.v3+json',
    'Content-Type': 'application/json',
  };

  try {
    // Lấy SHA nếu file đã tồn tại (cần cho PUT)
    let sha = '';
    const chk = await fetch(apiUrl, { headers });
    if (chk.ok) sha = (await chk.json()).sha || '';

    // Upload
    const payload = JSON.stringify(approved, null, 2);
    const content  = btoa(unescape(encodeURIComponent(payload)));
    const body = {
      message: `dashboard: ${approved.length} cập nhật BGĐ duyệt ngày ${new Date().toLocaleDateString('vi-VN')}`,
      content,
      ...(sha ? { sha } : {}),
    };

    const resp = await fetch(apiUrl, { method: 'PUT', headers, body: JSON.stringify(body) });

    if (resp.ok) {
      lsSave(AK, []);
      renderReview();
      updateNavBadge();
      if (btn) { btn.textContent = '✓ Đã gửi!'; btn.disabled = false; }
      alert(
        '✓ Đã gửi lên GitHub thành công!\\n\\n' +
        'GitHub Actions sẽ tự động:\\n' +
        '  1. Cập nhật tasks.csv\\n' +
        '  2. Sinh lại dashboard HTML\\n' +
        '  3. Deploy lên trang web\\n\\n' +
        'Tải lại trang sau ~1–2 phút để thấy kết quả.'
      );
    } else {
      const err = await resp.json().catch(() => ({}));
      if (btn) { btn.textContent = BTN_LABEL; btn.disabled = false; }
      if (resp.status === 401) {
        localStorage.removeItem(GH_TOKEN_KEY);
        alert('❌ Token không hợp lệ hoặc hết hạn. Nhấn ⚙ để nhập lại.');
      } else if (resp.status === 403) {
        alert('❌ Token thiếu quyền. Cần quyền "Contents: Read and write" cho repo bvtd-progress.');
      } else {
        alert(`❌ Lỗi ${resp.status}: ${err.message || 'Không rõ nguyên nhân'}`);
      }
    }
  } catch(e) {
    if (btn) { btn.textContent = BTN_LABEL; btn.disabled = false; }
    alert('❌ Lỗi kết nối: ' + e.message + '\\nKiểm tra kết nối internet.');
  }
}

function removeApproved(id) {
  lsSave(AK, lsGet(AK).filter(a => a.id !== id));
  renderPending(); renderReview();
}

function _resolveFbKey(id, user) {
  const direct = fbKey(user, id);
  if (_fbPending[direct]) return direct;
  // Fallback: tìm theo field id (data migrate cũ có key format khác)
  const found = Object.entries(_fbPending).find(([k,v]) => String(v.id||v.task_id||'') === String(id));
  return found ? found[0] : direct;
}

function approveUpd(id, user) {
  const key = _resolveFbKey(id, user);
  const item = _fbPending[key];
  if (!item) { alert('Không tìm thấy mục này trong danh sách chờ.'); return; }
  if (fbInit()) _db.ref('bvtd_pending/' + key).remove();
  delete _fbPending[key];
  const norm = normalizePending(item);
  const appr = lsGet(AK);
  const idx = appr.findIndex(a => String(a.id) === String(id));
  if (idx >= 0) appr[idx] = norm; else appr.push(norm);
  lsSave(AK, appr);
  renderPending(); renderReview();
}

function approveAll() {
  const approvedItems = lsGet(AK);
  const doneKeys2 = new Set(approvedItems.map(a => a.id + '|' + a.user));
  const pendingItems = fbPendingList().filter(p => !doneKeys2.has(p.id + '|' + p.user));
  pendingItems.forEach(p => approveUpd(p.id, p.user));
}

function rejectUpd(id, user) {
  const key = _resolveFbKey(id, user);
  if (fbInit()) _db.ref('bvtd_pending/' + key).remove();
  delete _fbPending[key];
  renderPending(); renderReview();
}

function exportApproved() {
  const appr = lsGet(AK);
  if (!appr.length) { alert('Chưa có cập nhật nào được duyệt.'); return; }
  const blob = new Blob([JSON.stringify(appr, null, 2)], {type:'application/json'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'pending_updates.json';
  a.click();
  lsSave(AK, []);
  renderPending(); renderReview();
  alert('✓ Đã tải file cập nhật về máy.\\nĐặt file pending_updates.json vào thư mục data/ rồi chạy /check để áp dụng.');
}

// ── Boot ───────────────────────────────────────────────────────────────────────
// DOMContentLoaded fires after ALL defer scripts (Chart.js, Firebase) — guaranteed available.
document.addEventListener('DOMContentLoaded', function() {
  const savedAuth = sessionStorage.getItem('bvtd_auth') || localStorage.getItem('bvtd_auth');
  if (savedAuth) {
    let parsedAuth = null;
    try { parsedAuth = JSON.parse(savedAuth); }
    catch(e) { localStorage.removeItem('bvtd_auth'); sessionStorage.removeItem('bvtd_auth'); }
    if (parsedAuth && parsedAuth.user && parsedAuth.user in USERS) {
      AUTH = parsedAuth;
      document.getElementById('login-overlay').style.display = 'none';
      document.getElementById('app-body').style.display = 'flex';
      document.getElementById('user-badge').textContent = AUTH.user;
      initApp();
      switchView('dashboard');
      startFbListener();
    }
  }
});
</script>
</body>
</html>""".replace("__LOGO_URI__", logo_uri)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    tasks = load_tasks()
    if not tasks:
        print("Khong co du lieu trong tasks.csv")
        return

    data = compute(tasks)
    data["log"] = load_update_log()

    html_out = build_html(data)
    for fname in ("dashboard.html", "tien_do.html"):
        (ROOT / fname).write_text(html_out, encoding="utf-8")
    print(f"dashboard.html + tien_do.html da tao ({data['total']} tasks, {len(data['dept'])} phong ban, {len(data['repeats'])} nhac lai)")


if __name__ == "__main__":
    main()
