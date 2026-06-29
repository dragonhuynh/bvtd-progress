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

from tracker import (
    load_tasks, save_tasks, bump_version, append_update_log,
    save_directive_fields, classify_nhom, detect_dinh_ky,
)


def _norm_phoi(v) -> str:
    """phong_phoi_hop dùng '|' (pipe). Chấp nhận list hoặc chuỗi."""
    if isinstance(v, list):
        return "|".join(str(x).strip() for x in v if str(x).strip())
    return str(v or "").strip()


def _next_id_num(tasks: list[dict]) -> int:
    nums = [int(t["id"]) for t in tasks if str(t.get("id", "")).isdigit()]
    return (max(nums) + 1) if nums else 1

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
    new_count = 0
    next_num = _next_id_num(tasks)

    print(f"{'='*55}")
    print(f"📱 AUTO-APPLY — {len(pending)} cập nhật từ dashboard")
    print(f"{'='*55}")

    for p in pending:
        # ── Đầu việc MỚI (tạo tay từ tab Tạo Task) ─────────────────────────────
        if p.get("new_task"):
            ten = (p.get("ten") or "").strip()
            phong = (p.get("phong") or "").strip()
            if not ten or not phong:
                print(f"  ⚠ Bỏ qua đầu việc mới thiếu tên/phòng: {p.get('id')!r}")
                continue
            new_id = str(next_num)
            next_num += 1
            is_dk = "1" if (str(p.get("dinh_ky", "")) == "1" or detect_dinh_ky(ten)) else "0"
            row = {
                "id": new_id,
                "ten_dau_viec": ten,
                "nhom": classify_nhom(ten, phong),
                "phong_chinh": phong,
                "phong_phoi_hop": _norm_phoi(p.get("phoi_hop")),
                "bat_dau": (p.get("bat_dau") or today),
                "ket_thuc": (p.get("deadline") or ""),
                "trang_thai": (p.get("trang_thai") or "dang_thuc_hien"),
                "so_lan_nhac": "1",
                "ghi_chu": (p.get("ghi_chu") or ""),
                "nguon_van_ban": (p.get("nguon") or ""),
                "dinh_ky": is_dk,
            }
            tasks.append(row)
            task_map[new_id] = row
            new_count += 1
            log_rows.append({
                "ngay_cap_nhat":   today,
                "task_id":         new_id,
                "ten_dau_viec":    ten,
                "phong_chinh":     phong,
                "phong_bao_cao":   p.get("user_phong", p.get("user", "")),
                "user":            p.get("user", ""),
                "trang_thai_cu":   "",
                "trang_thai_moi":  row["trang_thai"],
                "ngay_hoan_thanh": "",
                "ghi_chu":         f"[Tạo mới] {row['ghi_chu']}".strip(),
                "nguon":           "dashboard_new_task",
                "may":             p.get("may", ""),
                "ip":              p.get("ip", ""),
            })
            print(f"  ➕ [{new_id}] {ten[:50]} ({phong}) — từ {p.get('user_phong') or p.get('user','')}")
            continue

        tid = str(p.get("id", ""))
        task = task_map.get(tid)
        if not task:
            print(f"  ⚠ Không tìm thấy task id={tid!r}")
            continue

        old_tt = task["trang_thai"]
        note_in = (p.get("ghi_chu") or "").strip()
        # Nhận diện chỉ đạo theo cờ HOẶC theo tiền tố tên (phòng khi cờ chi_dao
        # bị rớt giữa pipeline → vẫn prepend, KHÔNG ghi đè mất ghi chú cũ)
        is_directive = bool(p.get("chi_dao")) or ("PHẠM THANH HẢI" in note_in.upper())
        if is_directive:
            # Chỉ đạo (BS Thanh Hải / PGĐ): KHÔNG đổi trạng thái — chèn ghi chú lên đầu
            new_tt = old_tt
            if note_in:
                old_note = (task.get("ghi_chu") or "").strip()
                task["ghi_chu"] = f"{note_in} | {old_note}" if old_note else note_in
            save_directive_fields(task, p, today)
        else:
            new_tt = p.get("trang_thai") or old_tt
            task["trang_thai"] = new_tt
            if new_tt == "da_hoan_thanh" and p.get("ngay_ht"):
                task["ket_thuc"] = p["ngay_ht"]
            if note_in:
                task["ghi_chu"] = note_in

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
            "may":             p.get("may", ""),
            "ip":              p.get("ip", ""),
        })
        changes += 1
        phong = p.get("user_phong") or p.get("user", "")
        print(f"  ✓ [{task['id']}] {task['ten_dau_viec'][:50]} → {new_tt} (từ {phong})")

    save_tasks(tasks)
    if log_rows:
        append_update_log(log_rows)

    PENDING_FILE.unlink()

    if new_count:
        ver = bump_version("parse", [f"thêm {new_count} đầu việc mới từ dashboard"])
    else:
        ver = bump_version("check", ["auto-apply từ dashboard"])
    print(f"\n✓ Áp dụng {changes}/{len(pending)} cập nhật + {new_count} đầu việc mới. Phiên bản: v{ver}")

    print("\n▶ Sinh lại dashboard HTML...")
    import generate_dashboard
    generate_dashboard.main()
    print("✓ tien_do.html đã cập nhật.")


if __name__ == "__main__":
    main()
