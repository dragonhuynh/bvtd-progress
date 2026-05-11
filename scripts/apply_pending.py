"""
Auto-apply pending_updates.json vào tasks.csv (không tương tác).
Được gọi bởi GitHub Actions khi BGĐ upload file lên repo.
"""
import sys
import json
import csv
import subprocess
from pathlib import Path
from datetime import datetime, date

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

TASKS_CSV     = ROOT / "data" / "tasks.csv"
PENDING_FILE  = ROOT / "data" / "pending_updates.json"
LOG_CSV       = ROOT / "data" / "update_log.csv"
VERSIONS_JSON = ROOT / "data" / "report_versions.json"
INDEX_JSON    = ROOT / "data" / "tasks_index.json"

LOG_HEADERS = [
    "ngay_cap_nhat", "task_id", "ten_dau_viec", "phong_chinh",
    "phong_bao_cao", "user", "trang_thai_cu", "trang_thai_moi",
    "ngay_hoan_thanh", "ghi_chu", "nguon",
]


def _load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _save_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def _rebuild_index(tasks: list[dict]) -> None:
    if not tasks:
        return
    nums = [int(t["id"]) for t in tasks if str(t.get("id", "")).isdigit()]
    index = {
        "next_id_num": max(nums) + 1 if nums else 1,
        "total": len(tasks),
        "titles": [t.get("ten_dau_viec", "") for t in tasks],
        "updated": str(date.today()),
    }
    INDEX_JSON.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_log(rows: list[dict]) -> None:
    write_header = not LOG_CSV.exists()
    with LOG_CSV.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_HEADERS)
        if write_header:
            w.writeheader()
        w.writerows(rows)


def _bump_version() -> str:
    data = {"version": "0.0", "history": []}
    if VERSIONS_JSON.exists():
        try:
            data = json.loads(VERSIONS_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    major, minor = data.get("version", "0.0").split(".")
    new_ver = f"{major}.{int(minor) + 1}"
    data["version"] = new_ver
    entry = {
        "version": new_ver,
        "ngay": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "loai": "check",
        "thay_doi": ["auto-apply từ dashboard"],
    }
    hist = data.get("history", [])
    hist.insert(0, entry)
    data["history"] = hist[:50]
    VERSIONS_JSON.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return new_ver


def main() -> None:
    if not PENDING_FILE.exists():
        print("Không có pending_updates.json — bỏ qua.")
        return

    try:
        pending = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"[LỖI] Không đọc được pending_updates.json: {e}")
        sys.exit(1)

    if not pending:
        print("pending_updates.json rỗng — xóa file.")
        PENDING_FILE.unlink()
        return

    tasks = _load_csv(TASKS_CSV)
    task_map = {str(t["id"]): t for t in tasks}

    today = str(date.today())
    log_rows: list[dict] = []
    changes = 0

    print(f"{'='*55}")
    print(f"📱 AUTO-APPLY — {len(pending)} cập nhật từ dashboard")
    print(f"{'='*55}")

    for p in pending:
        tid = str(p.get("id", ""))
        task = task_map.get(tid)
        if not task:
            print(f"  ⚠ Không tìm thấy task id={tid!r}")
            continue

        old_tt = task["trang_thai"]
        new_tt = p.get("trang_thai") or old_tt

        task["trang_thai"] = new_tt
        if new_tt == "da_hoan_thanh" and p.get("ngay_ht"):
            task["ket_thuc"] = p["ngay_ht"]
        if p.get("ghi_chu"):
            task["ghi_chu"] = p["ghi_chu"]

        log_rows.append({
            "ngay_cap_nhat":   today,
            "task_id":         task["id"],
            "ten_dau_viec":    task["ten_dau_viec"],
            "phong_chinh":     task["phong_chinh"],
            "phong_bao_cao":   p.get("user_phong", p.get("phong", "")),
            "user":            p.get("user", ""),
            "trang_thai_cu":   old_tt,
            "trang_thai_moi":  new_tt,
            "ngay_hoan_thanh": p.get("ngay_ht", ""),
            "ghi_chu":         p.get("ghi_chu", ""),
            "nguon":           "dashboard_auto",
        })
        changes += 1
        phong = p.get("user_phong") or p.get("user", "")
        print(f"  ✓ [{task['id']}] {task['ten_dau_viec'][:50]} → {new_tt} (từ {phong})")

    # Ghi CSV + log
    _save_csv(TASKS_CSV, tasks)
    _rebuild_index(tasks)
    if log_rows:
        _append_log(log_rows)

    # Xóa pending file
    PENDING_FILE.unlink()

    ver = _bump_version()
    print(f"\n✓ Áp dụng {changes}/{len(pending)} cập nhật. Phiên bản: v{ver}")

    # Sinh lại dashboard HTML
    print("\n▶ Sinh lại dashboard HTML...")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "generate_dashboard.py")],
        capture_output=True, text=True, cwd=str(ROOT),
    )
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print(f"[WARN] generate_dashboard.py lỗi:\n{result.stderr[:500]}")
    else:
        print("✓ tien_do.html đã cập nhật.")


if __name__ == "__main__":
    main()
