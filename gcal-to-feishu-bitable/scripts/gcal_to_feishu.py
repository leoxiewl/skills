#!/usr/bin/env python3
"""
将 Google Calendar 当天事件同步到飞书多维表格
用法: python3 gcal_to_feishu.py [--date YYYY-MM-DD] [--dry-run]
依赖: gws CLI 已认证 (gws auth login); lark-cli 已登录
"""

import json
import os
import subprocess
import sys
import argparse
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

LARK_CLI = "/Users/leo/.local/bin/lark-cli"
BASE_TOKEN = "Wz3nbxbm6a9z3osshfgcfPgvnkb"
TABLE_ID = "tblTWirrJcB4xeH1"

SKIP_CALENDARS = ["月相", "中国节假日"]

TZ_CST = timezone(timedelta(hours=8))

FIELDS = ["日程标题", "日期", "开始时间", "结束时间", "角色分类", "日历来源", "备注"]

# gws 与代理有已知冲突，调用时清除代理环境变量
GWS_ENV = {**os.environ, "HTTP_PROXY": "", "HTTPS_PROXY": "", "http_proxy": "", "https_proxy": ""}


# ── gws helpers ──────────────────────────────────────────────────────────────

def _parse_gws_json(raw_stdout):
    """从 gws 输出中提取 JSON（跳过 keyring 提示行等非 JSON 前缀）。"""
    lines = raw_stdout.strip().split("\n")
    json_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("{"):
            json_start = i
            break
    json_str = "\n".join(lines[json_start:])
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        items = []
        for line in lines[json_start:]:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        if items:
            return {"items": items} if len(items) > 1 else items[0]
        return None


def _run_gws_auth_login():
    """运行 gws auth login，自动检测 stdout 中的 OAuth URL 并用浏览器打开。
    返回 True 表示成功，False 表示失败。
    """
    import webbrowser
    import re

    print("⚠️  gws Token 已失效，正在启动重新认证流程...")
    print("浏览器会自动打开 Google 授权页面，完成授权后回到终端继续。")
    print()

    proc = subprocess.Popen(
        ["gws", "auth", "login"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=GWS_ENV
    )
    url_opened = False
    try:
        while True:
            line = proc.stdout.readline()
            if not line:
                if proc.poll() is not None:
                    break
                continue
            print(line, end='')
            if not url_opened:
                match = re.search(r'(https://\S+)', line)
                if match:
                    url = match.group(1)
                    print(f"\n🌐 自动打开浏览器进行 Google OAuth 授权...\n")
                    webbrowser.open(url)
                    url_opened = True
    except KeyboardInterrupt:
        proc.kill()
        return False

    try:
        proc.wait(timeout=300)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        print("⚠️  gws auth login 超时（300s），但可能已完成授权", file=sys.stderr)

    return proc.returncode == 0


def try_get_calendars_with_auth():
    """获取日历列表，认证失败时自动引导重新登录并重试。
    返回日历列表 [(name, id), ...]，失败时返回 None。
    """
    # 第一次尝试
    calendars = get_calendar_list()
    if calendars:
        return calendars

    # 失败 → 可能是认证问题，尝试重新登录
    print("\n获取日历列表失败，尝试重新认证 gws...\n")
    if not _run_gws_auth_login():
        print("❌ gws auth login 失败，请手动运行：gws auth login", file=sys.stderr)
        return None

    # 重试
    print("✅ 认证完成，重新获取日历列表...")
    calendars = get_calendar_list()
    if calendars:
        return calendars

    print("❌ 重新认证后仍无法获取日历列表，请检查网络或手动运行 gws auth status", file=sys.stderr)
    return None


def run_gws(args):
    cmd = ["gws"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, env=GWS_ENV)
    if result.returncode != 0:
        print(f"gws 命令失败: {' '.join(cmd)}", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return None
    return _parse_gws_json(result.stdout)


def get_calendar_list():
    data = run_gws(["calendar", "calendarList", "list", "--page-all"])
    if not data or "items" not in data:
        print("无法获取日历列表", file=sys.stderr)
        return []
    return [(item["summary"], item["id"]) for item in data["items"] if item.get("summary") and item.get("id")]


def get_events_for_day(cal_id, date_str):
    params = json.dumps({
        "calendarId": cal_id,
        "timeMin": f"{date_str}T00:00:00+08:00",
        "timeMax": f"{date_str}T23:59:59+08:00",
        "singleEvents": True,
        "orderBy": "startTime",
    })
    data = run_gws(["calendar", "events", "list", "--params", params])
    return data.get("items", []) if data else []


def parse_dt_to_ms(dt_str):
    """ISO 8601 字符串 → Unix 毫秒 (CST)"""
    if dt_str.endswith("Z"):
        dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
    else:
        dt = datetime.fromisoformat(dt_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ_CST)
    return int(dt.timestamp() * 1000)


# ── lark-cli helpers ──────────────────────────────────────────────────────────

ROLE_FIELD_ID = "flddoPhPRm"

def run_lark(args, timeout=60):
    cmd = [LARK_CLI] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "raw": result.stdout, "stderr": result.stderr}


def ensure_select_options(needed_names, dry_run):
    """确保 角色分类 select 字段包含所有 needed_names，缺失的自动追加。"""
    # 获取当前字段定义
    data = run_lark([
        "base", "+field-get",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--field-id", ROLE_FIELD_ID,
    ])
    if not data.get("ok"):
        print(f"无法获取角色分类字段定义: {data}", file=sys.stderr)
        return False

    field_def = data.get("data") or {}
    current_options = field_def.get("options") or []
    existing_names = {opt["name"] for opt in current_options}

    missing = [n for n in needed_names if n not in existing_names]
    if not missing:
        return True

    print(f"追加新角色分类 option: {missing}")
    if dry_run:
        print("[dry-run] 跳过 +field-update")
        return True

    new_options = list(current_options) + [{"name": n} for n in missing]
    new_field_def = {
        "name": field_def.get("name", "角色分类"),
        "type": "select",
        "multiple": field_def.get("multiple", False),
        "options": new_options,
    }
    result = run_lark([
        "base", "+field-update",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--field-id", ROLE_FIELD_ID,
        "--json", json.dumps(new_field_def, ensure_ascii=False),
        "--yes",
    ])
    if not result.get("ok"):
        print(f"更新角色分类字段失败: {result}", file=sys.stderr)
        return False
    return True


def get_existing_record_ids(date_str):
    """返回表中 日期 字段属于 date_str 当天的所有 record_id。
    API 返回格式: data.data = rows[], data.fields = column names[], data.record_id_list = ids[]
    日期字段值为 'YYYY-MM-DD HH:MM:SS' 字符串。
    """
    data = run_lark([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--format", "json",
        "--limit", "200",
    ])
    if not data.get("ok"):
        return []

    inner = data.get("data") or {}
    fields = inner.get("fields") or []
    rows = inner.get("data") or []
    record_ids = inner.get("record_id_list") or []

    try:
        date_idx = fields.index("日期")
    except ValueError:
        return []

    ids = []
    for rid, row in zip(record_ids, rows):
        date_val = row[date_idx] if date_idx < len(row) else None
        # 日期值格式: "2026-06-27 08:00:00"，取前10位比较
        if isinstance(date_val, str) and date_val[:10] == date_str:
            ids.append(rid)
    return ids


def delete_records(record_ids):
    if not record_ids:
        return
    args = ["base", "+record-delete", "--base-token", BASE_TOKEN, "--table-id", TABLE_ID, "--yes"]
    for rid in record_ids:
        args += ["--record-id", rid]
    result = run_lark(args)
    if not result.get("ok"):
        print(f"删除记录失败: {result}", file=sys.stderr)


def batch_create_records(rows, dry_run):
    payload = {"fields": FIELDS, "rows": rows}
    payload_str = json.dumps(payload, ensure_ascii=False)
    if dry_run:
        print("\n[dry-run] +record-batch-create payload:")
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return True
    result = run_lark([
        "base", "+record-batch-create",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--json", payload_str,
    ])
    if not result.get("ok"):
        print(f"写入失败: {result}", file=sys.stderr)
        return False
    return True


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="同步 Google Calendar 到飞书多维表格")
    parser.add_argument("--date", default=datetime.now(TZ_CST).strftime("%Y-%m-%d"), help="目标日期 YYYY-MM-DD")
    parser.add_argument("--dry-run", action="store_true", help="只打印，不写入")
    args = parser.parse_args()

    date_str = args.date
    dry_run = args.dry_run

    # 当天零点 Unix ms (CST)
    day_start_dt = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=TZ_CST)
    day_start_ms = int(day_start_dt.timestamp() * 1000)

    print(f"目标日期: {date_str}{'  [dry-run]' if dry_run else ''}")

    # 1. 获取日历列表（认证失败时自动引导重新登录并重试）
    calendars = try_get_calendars_with_auth()
    if not calendars:
        sys.exit(1)
    targets = [(name, cid) for name, cid in calendars if name not in SKIP_CALENDARS]
    if not targets:
        print("没有可查询的日历（全部被过滤）。", file=sys.stderr)
        sys.exit(1)
    print(f"查询 {len(targets)} 个日历...")

    # 2. 并发拉取事件
    all_events = []  # [(cal_name, event), ...]
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        futures = {pool.submit(get_events_for_day, cid, date_str): name for name, cid in targets}
        for future in as_completed(futures):
            cal_name = futures[future]
            events = future.result()
            for ev in events:
                all_events.append((cal_name, ev))

    # 当天边界 ms
    day_end_ms = day_start_ms + 24 * 3600 * 1000  # 次日 00:00

    # 3. 过滤全天事件，组装 rows；跨天事件截断到当天 00:00~24:00
    rows = []
    for cal_name, ev in all_events:
        start_obj = ev.get("start", {})
        end_obj = ev.get("end", {})
        if "date" in start_obj:
            continue  # 全天事件跳过
        start_str = start_obj.get("dateTime")
        end_str = end_obj.get("dateTime")
        if not start_str or not end_str:
            continue

        title = ev.get("summary") or "(无标题)"
        description = ev.get("description") or ""
        raw_start_ms = parse_dt_to_ms(start_str)
        raw_end_ms = parse_dt_to_ms(end_str)

        # 截断到当天边界
        start_ms = max(raw_start_ms, day_start_ms)
        end_ms = min(raw_end_ms, day_end_ms)
        if end_ms <= start_ms:
            continue

        cross_day = raw_start_ms < day_start_ms or raw_end_ms > day_end_ms
        row = [title, day_start_ms, start_ms, end_ms, cal_name, "Google Calendar", description]
        rows.append(row)
        start_time = "00:00" if start_ms == day_start_ms and raw_start_ms < day_start_ms else datetime.fromtimestamp(start_ms / 1000, tz=TZ_CST).strftime("%H:%M")
        end_time = "24:00" if end_ms == day_end_ms else datetime.fromtimestamp(end_ms / 1000, tz=TZ_CST).strftime("%H:%M")
        suffix = " [跨天截断]" if cross_day else ""
        print(f"  {start_time}~{end_time}  [{cal_name}]  {title}{suffix}")

    if not rows:
        print("当天无有效事件（含时间的），无需写入。")
        return

    print(f"\n共 {len(rows)} 条有效事件")

    # 4. 确保 角色分类 字段包含所有日历名称 option
    needed_cal_names = list({row[4] for row in rows})  # index 4 = 角色分类
    if not ensure_select_options(needed_cal_names, dry_run):
        sys.exit(1)

    # 5. 去重：删除当天已有记录
    if not dry_run:
        existing_ids = get_existing_record_ids(date_str)
        if existing_ids:
            print(f"删除已有 {len(existing_ids)} 条旧记录...")
            delete_records(existing_ids)

    # 6. 分批写入（每批 ≤ 500）
    batch_size = 500
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        ok = batch_create_records(batch, dry_run)
        if not ok:
            sys.exit(1)

    if not dry_run:
        print(f"✅ 已写入 {len(rows)} 条记录到飞书多维表格")


if __name__ == "__main__":
    main()
