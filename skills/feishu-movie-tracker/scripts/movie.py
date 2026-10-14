#!/usr/bin/env python3
"""
飞书观影记录管理脚本 — 新增/查询/更新/统计观影记录
用法:
  python3 movie.py add --title "X" --type "电影" --status "想看" [--year N] [--category X] [--studio X] [--rating N] [--note X] [--dry-run]
  python3 movie.py list [--status X] [--year N] [--type X] [--category X]
  python3 movie.py update --title "X" [--status X] [--rating N] [--note X] [--dry-run]
  python3 movie.py stats [--by-year] [--by-type] [--by-category] [--by-status]
依赖: lark-cli 已登录
"""

import json
import subprocess
import sys
import argparse
from datetime import datetime, timezone, timedelta
from collections import Counter

LARK_CLI = "/Users/leo/.local/bin/lark-cli"
BASE_TOKEN = "MGFMbMX1Pasf79sxkO2ciXxFnQb"
TABLE_ID = "tbl8b5bhTFamIYxj"

TZ_CST = timezone(timedelta(hours=8))

# 字段 ID 映射
FIELD_IDS = {
    "标题": "fldW7Ertu2",          # text（必填）
    "类型": "fldm53iuP5",          # select: 电影/剧集
    "状态": "fldhz4FUgo",          # select: 想看/在看/已看/弃剧
    "发布年份": "fldWndJvGo",      # number
    "开始观看日期": "fldmLGtltm",  # datetime
    "类别/题材": "fldta9Vss4",     # select: 爱情/悬疑/科幻/喜剧/动作/剧情/恐怖/纪录片/动画/历史
    "工作室": "fldmBV7DVa",        # select: 皮克斯/迪士尼/吉卜力/梦工厂/照明娱乐/索尼动画/华纳动画/蓝天工作室/其他
    "导演": "fldkvGSqJ1",          # select（多选）
    "主演": "fldSJNo3ez",          # select（多选）
    "豆瓣评分": "fld0X2QYbF",      # number
    "个人评分": "fldoEW1Gaw",      # number
    "推荐理由/短评": "fldbpIqOUo", # text
    "豆瓣链接": "fldykg8MJj",      # text
    "个人标签": "fldjouyxfl",      # select（多选）
    "封面图": "fld57LBjqT",        # attachment
    "创建时间": "fldydQ9hkt",      # created_at
    "修改时间": "flddfsCCxZ",      # updated_at
}

# 可写入的手动字段 ID（add/update 用）
WRITABLE_FIELDS = {
    "标题": "fldW7Ertu2",
    "类型": "fldm53iuP5",
    "状态": "fldhz4FUgo",
    "发布年份": "fldWndJvGo",
    "开始观看日期": "fldmLGtltm",
    "类别/题材": "fldta9Vss4",
    "工作室": "fldmBV7DVa",
    "导演": "fldkvGSqJ1",
    "主演": "fldSJNo3ez",
    "豆瓣评分": "fld0X2QYbF",
    "个人评分": "fldoEW1Gaw",
    "推荐理由/短评": "fldbpIqOUo",
    "豆瓣链接": "fldykg8MJj",
    "个人标签": "fldjouyxfl",
}

# select 字段（写入时需要用数组格式）
SELECT_FIELDS = {"类型", "状态", "类别/题材", "工作室", "导演", "主演", "个人标签"}


# ── lark-cli helpers ──────────────────────────────────────────────────────────

def run_lark(args, timeout=60):
    cmd = [LARK_CLI] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        pass
    try:
        return json.loads(result.stderr)
    except json.JSONDecodeError:
        pass
    return {"ok": False, "raw": result.stdout, "stderr": result.stderr}


def _val(record, field_name):
    """取字段值，如果是数组则取第一个元素"""
    v = record.get(field_name)
    if isinstance(v, list) and len(v) == 1:
        return v[0]
    return v


def _format_date(val):
    """格式化日期值（毫秒时间戳或字符串）"""
    if not val:
        return ""
    try:
        if isinstance(val, (int, float)):
            dt = datetime.fromtimestamp(val / 1000, tz=TZ_CST)
            return dt.strftime("%Y-%m-%d")
        return str(val)[:10]
    except (OSError, ValueError):
        return str(val)[:10]


def _build_payload(fields_dict):
    """构建 +record-upsert payload，select 字段自动用数组格式"""
    payload = {}
    for name, value in fields_dict.items():
        if value is None:
            continue
        fid = WRITABLE_FIELDS.get(name)
        if not fid:
            continue
        if name in SELECT_FIELDS and not isinstance(value, list):
            payload[fid] = [value]
        else:
            payload[fid] = value
    return payload


def fetch_all_records():
    """获取表中所有记录，返回 (fields, rows, record_ids)"""
    data = run_lark([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--format", "json",
        "--limit", "200",
    ])
    if not data.get("ok"):
        print(f"查询记录失败: {data}", file=sys.stderr)
        return [], [], []

    inner = data.get("data") or {}
    return inner.get("fields") or [], inner.get("data") or [], inner.get("record_id_list") or []


def find_record_by_name(name):
    """按标题查找记录，返回 (record_id, field_values_dict) 或 (None, None)"""
    fields, rows, record_ids = fetch_all_records()
    if not fields:
        return None, None

    try:
        title_idx = fields.index("标题")
    except ValueError:
        return None, None

    for rid, row in zip(record_ids, rows):
        val = row[title_idx] if title_idx < len(row) else None
        if val == name:
            record = {}
            for i, f in enumerate(fields):
                record[f] = row[i] if i < len(row) else None
            return rid, record
    return None, None


# ── add 命令 ──────────────────────────────────────────────────────────────────

def cmd_add(args):
    title = args.title
    media_type = args.type or "电影"
    status = args.status or "想看"
    year = args.year
    category = args.category or ""
    studio = args.studio or "其他"
    rating = args.rating
    note = args.note or ""
    watch_date = args.watch_date
    dry_run = args.dry_run

    # 参数校验
    if not title:
        print("❌ 标题不能为空", file=sys.stderr)
        sys.exit(1)

    # 打印预览
    print(f"🎬 新增观影记录{'  [dry-run]' if dry_run else ''}")
    print(f"  标题:       {title}")
    print(f"  类型:       {media_type}")
    print(f"  状态:       {status}")
    if year:
        print(f"  发布年份:   {year}")
    if category:
        print(f"  类别/题材:  {category}")
    if studio:
        print(f"  工作室:     {studio}")
    if rating is not None:
        print(f"  个人评分:   {rating}")
    if watch_date:
        print(f"  开始观看:   {watch_date}")
    if note:
        print(f"  短评:       {note}")

    # 构建 payload
    fields_dict = {
        "标题": title,
        "类型": media_type,
        "状态": status,
    }
    if year:
        fields_dict["发布年份"] = year
    if category:
        fields_dict["类别/题材"] = category
    if studio:
        fields_dict["工作室"] = studio
    if rating is not None:
        fields_dict["个人评分"] = rating
    if note:
        fields_dict["推荐理由/短评"] = note
    if watch_date:
        fields_dict["开始观看日期"] = f"{watch_date} 00:00:00"

    payload = _build_payload(fields_dict)

    if dry_run:
        print(f"\n[dry-run] 跳过写入飞书")
        print(f"  payload: {json.dumps(payload, ensure_ascii=False, indent=2)}")
        return

    payload_str = json.dumps(payload, ensure_ascii=False)
    result = run_lark([
        "base", "+record-upsert",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--json", payload_str,
    ])
    if not result.get("ok"):
        print(f"❌ 写入失败: {result}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ 已写入飞书多维表格")


# ── list 命令 ─────────────────────────────────────────────────────────────────

def cmd_list(args):
    filter_status = args.status
    filter_year = args.year
    filter_type = args.type
    filter_category = args.category

    fields, rows, record_ids = fetch_all_records()
    if not fields:
        print("表中暂无记录")
        return

    # 建立字段索引
    idx = {}
    for i, f in enumerate(fields):
        idx[f] = i

    # 筛选
    matched = []

    for rid, row in zip(record_ids, rows):
        record = {}
        for f, i in idx.items():
            record[f] = row[i] if i < len(row) else None

        # 状态筛选
        if filter_status and _val(record, "状态") != filter_status:
            continue

        # 类型筛选
        if filter_type and _val(record, "类型") != filter_type:
            continue

        # 类别筛选
        if filter_category and _val(record, "类别/题材") != filter_category:
            continue

        # 年份筛选（按开始观看日期）
        if filter_year:
            watch_date = record.get("开始观看日期")
            if watch_date:
                try:
                    if isinstance(watch_date, (int, float)):
                        dt = datetime.fromtimestamp(watch_date / 1000, tz=TZ_CST)
                        year = dt.year
                    elif isinstance(watch_date, str):
                        year = int(watch_date[:4])
                    else:
                        continue
                    if year != filter_year:
                        continue
                except (OSError, ValueError):
                    continue
            else:
                continue

        matched.append(record)

    if not matched:
        print("无匹配记录")
        return

    # 打印结果
    print(f"🎬 共 {len(matched)} 条记录\n")

    for r in matched:
        title = _val(r, "标题") or "?"
        media_type = _val(r, "类型") or "?"
        status = _val(r, "状态") or "?"
        year = r.get("发布年份") or ""
        category = _val(r, "类别/题材") or ""
        rating = r.get("个人评分") or ""

        year_str = f" ({year})" if year else ""
        category_str = f" [{category}]" if category else ""
        rating_str = f" ⭐{rating}" if rating else ""

        print(f"  {title}{year_str}{category_str}  |  {media_type}  |  {status}{rating_str}")


# ── update 命令 ───────────────────────────────────────────────────────────────

def cmd_update(args):
    title = args.title
    dry_run = args.dry_run

    if not title:
        print("❌ 请指定要更新的记录标题", file=sys.stderr)
        sys.exit(1)

    # 查找记录
    rid, record = find_record_by_name(title)
    if not rid:
        print(f"❌ 未找到名为「{title}」的记录", file=sys.stderr)
        sys.exit(1)

    # 构建更新字段
    fields_dict = {}

    if args.status:
        fields_dict["状态"] = args.status
    if args.type:
        fields_dict["类型"] = args.type
    if args.rating is not None:
        fields_dict["个人评分"] = args.rating
    if args.note is not None:
        fields_dict["推荐理由/短评"] = args.note
    if args.category:
        fields_dict["类别/题材"] = args.category
    if args.studio:
        fields_dict["工作室"] = args.studio
    if args.year is not None:
        fields_dict["发布年份"] = args.year
    if args.watch_date:
        fields_dict["开始观看日期"] = f"{args.watch_date} 00:00:00"

    if not fields_dict:
        print("❌ 没有指定要更新的字段", file=sys.stderr)
        sys.exit(1)

    payload = _build_payload(fields_dict)

    # 打印预览
    print(f"✏️ 更新「{title}」{'  [dry-run]' if dry_run else ''}")
    for k, v in fields_dict.items():
        print(f"  {k}: {v}")

    if dry_run:
        print("\n[dry-run] 跳过写入飞书")
        return

    payload_str = json.dumps(payload, ensure_ascii=False)
    result = run_lark([
        "base", "+record-upsert",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--record-id", rid,
        "--json", payload_str,
    ])
    if not result.get("ok"):
        print(f"❌ 更新失败: {result}", file=sys.stderr)
        sys.exit(1)

    print(f"✅ 已更新飞书多维表格")


# ── stats 命令 ────────────────────────────────────────────────────────────────

def cmd_stats(args):
    by_year = args.by_year
    by_type = args.by_type
    by_category = args.by_category
    by_status = args.by_status

    # 默认显示年度统计
    if not (by_year or by_type or by_category or by_status):
        by_year = True

    fields, rows, record_ids = fetch_all_records()
    if not fields:
        print("表中暂无记录")
        return

    # 建立字段索引
    idx = {}
    for i, f in enumerate(fields):
        idx[f] = i

    # 提取所有记录
    all_records = []
    for rid, row in zip(record_ids, rows):
        record = {}
        for f, i in idx.items():
            record[f] = row[i] if i < len(row) else None
        all_records.append(record)

    print("📊 观影数据统计\n")
    print(f"总记录数: {len(all_records)}\n")

    # 按年份统计（开始观看日期）
    if by_year:
        print("=== 年度观影统计 ===")
        year_counter = Counter()
        for r in all_records:
            watch_date = r.get("开始观看日期")
            if watch_date:
                try:
                    if isinstance(watch_date, (int, float)):
                        dt = datetime.fromtimestamp(watch_date / 1000, tz=TZ_CST)
                        year = dt.year
                    elif isinstance(watch_date, str):
                        year = int(watch_date[:4])
                    else:
                        continue
                    year_counter[year] += 1
                except (OSError, ValueError):
                    continue

        if year_counter:
            for year in sorted(year_counter.keys(), reverse=True):
                count = year_counter[year]
                bar = "█" * min(count, 20)
                print(f"  {year}: {bar} {count}")
        else:
            print("  暂无观看日期数据")
        print()

    # 按类型统计
    if by_type:
        print("=== 类型分布 ===")
        type_counter = Counter()
        for r in all_records:
            media_type = _val(r, "类型")
            if media_type:
                type_counter[media_type] += 1

        for t, count in type_counter.most_common():
            bar = "█" * min(count, 20)
            print(f"  {t}: {bar} {count}")
        print()

    # 按类别统计
    if by_category:
        print("=== 类别/题材分布 ===")
        category_counter = Counter()
        for r in all_records:
            category = _val(r, "类别/题材")
            if category:
                category_counter[category] += 1

        for c, count in category_counter.most_common():
            bar = "█" * min(count, 20)
            print(f"  {c}: {bar} {count}")
        print()

    # 按状态统计
    if by_status:
        print("=== 状态分布 ===")
        status_counter = Counter()
        for r in all_records:
            status = _val(r, "状态")
            if status:
                status_counter[status] += 1

        for s, count in status_counter.most_common():
            bar = "█" * min(count, 20)
            print(f"  {s}: {bar} {count}")
        print()


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="飞书观影记录管理")
    subparsers = parser.add_subparsers(dest="command")

    # add
    add_parser = subparsers.add_parser("add", help="新增观影记录")
    add_parser.add_argument("--title", required=True, help="影视标题")
    add_parser.add_argument("--type", default="电影", help="类型: 电影/剧集")
    add_parser.add_argument("--status", default="想看", help="状态: 想看/在看/已看/弃剧")
    add_parser.add_argument("--year", type=int, help="发布年份")
    add_parser.add_argument("--category", help="类别/题材: 爱情/悬疑/科幻/喜剧/动作/剧情/恐怖/纪录片/动画/历史")
    add_parser.add_argument("--studio", default="其他", help="工作室")
    add_parser.add_argument("--rating", type=float, help="个人评分 (1-10)")
    add_parser.add_argument("--watch-date", help="开始观看日期 YYYY-MM-DD")
    add_parser.add_argument("--note", help="推荐理由/短评")
    add_parser.add_argument("--dry-run", action="store_true", help="预览，不写入")

    # list
    list_parser = subparsers.add_parser("list", help="查询观影记录")
    list_parser.add_argument("--status", help="按状态筛选: 想看/在看/已看/弃剧")
    list_parser.add_argument("--year", type=int, help="按年份筛选（开始观看日期）")
    list_parser.add_argument("--type", help="按类型筛选: 电影/剧集")
    list_parser.add_argument("--category", help="按类别筛选")

    # update
    update_parser = subparsers.add_parser("update", help="更新观影记录")
    update_parser.add_argument("--title", required=True, help="影视标题")
    update_parser.add_argument("--status", help="状态: 想看/在看/已看/弃剧")
    update_parser.add_argument("--type", help="类型: 电影/剧集")
    update_parser.add_argument("--rating", type=float, help="个人评分 (1-10)")
    update_parser.add_argument("--category", help="类别/题材")
    update_parser.add_argument("--studio", help="工作室")
    update_parser.add_argument("--year", type=int, help="发布年份")
    update_parser.add_argument("--watch-date", help="开始观看日期 YYYY-MM-DD")
    update_parser.add_argument("--note", help="推荐理由/短评")
    update_parser.add_argument("--dry-run", action="store_true", help="预览，不写入")

    # stats
    stats_parser = subparsers.add_parser("stats", help="统计观影数据")
    stats_parser.add_argument("--by-year", action="store_true", help="按年份统计")
    stats_parser.add_argument("--by-type", action="store_true", help="按类型统计")
    stats_parser.add_argument("--by-category", action="store_true", help="按类别统计")
    stats_parser.add_argument("--by-status", action="store_true", help="按状态统计")

    args = parser.parse_args()

    if args.command == "add":
        cmd_add(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "stats":
        cmd_stats(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
