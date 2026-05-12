"""
Auto-apply pending_updates.json vào tasks.csv (không tương tác).
Được gọi bởi GitHub Actions khi BGĐ upload file lên repo.
"""
import sys
import json
import logging
from pathlib import Path
from datetime import date

logging.basicConfig(stream=sys.stderr, level=logging.WARNING, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from tracker import load_tasks, save_tasks, bump_version, append_update_log

PENDING_FILE = ROOT / "data" / "pending_updates.json"


def main() -> None:
    if not PENDING_FILE.exists():
        print("Không có pending_updates.json — bỏ qua.")
        return

    try:
        pending = json.loads(PENDING_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        log.error("Không đọc được pending_updates.json: %s", e)
        sys.exit(1)

    if not pending:
        print("pending_updates.json rỗng — xóa file.")
        PENDING_FILE.unlink()
        return

    tasks = load_tasks()
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

    save_tasks(tasks)
    if log_rows:
        append_update_log(log_rows)

    PENDING_FILE.unlink()

    ver = bump_version("check", ["auto-apply từ dashboard"])
    print(f"\n✓ Áp dụng {changes}/{len(pending)} cập nhật. Phiên bản: v{ver}")

    print("\n▶ Sinh lại dashboard HTML...")
    import generate_dashboard
    generate_dashboard.main()
    print("✓ tien_do.html đã cập nhật.")


if __name__ == "__main__":
    main()
