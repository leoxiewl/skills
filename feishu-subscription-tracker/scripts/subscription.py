#!/usr/bin/env python3
"""
飞书订阅管理脚本 — 新增/查询/更新订阅记录
用法:
  python3 subscription.py add --name "X" --type "月付订阅" --amount 20 --currency "USD" --cny-amount 145 [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--auto-renew] [--category X] [--payment X] [--note X] [--continue-sub X] [--dry-run]
  python3 subscription.py list [--expiring-within N] [--type X]
  python3 subscription.py update --name "X" [--amount N] [--currency X] [--cny-amount N] [--end YYYY-MM-DD] [--note X] [--dry-run]
依赖: lark-cli 已登录
"""

import json
import subprocess
import sys
import argparse
from datetime import datetime, timezone, timedelta

LARK_CLI = "/Users/leo/.local/bin/lark-cli"
BASE_TOKEN = "GIbpbyT74aqJFpsSoUvcRhlQnXe"
TABLE_ID = "tblgd8eOC8d3GvvR"

TZ_CST = timezone(timedelta(hours=8))

# 当前字段 ID 映射（2026-06-27 同步自飞书表格）
FIELD_IDS = {
    "名称": "fldbEgOw7p",          # text
    "订阅类型": "fldd2tcEVx",      # select: 月付订阅/年付订阅/一次性买断/一次性购买
    "分类": "fldZAyjNKF",          # select: AI 工具/效率工具/娱乐会员/云服务
    "金额": "fldrM3aC6c",          # number
    "币种": "fldKGgUeAa",          # select: USD/CNY
    "折算人民币": "fldcxTKirZ",    # number（手动输入）
    "开始时间": "fldG3MfmaN",      # datetime
    "结束时间": "fldaKJ6U5w",      # datetime
    "自动续费": "fld1dtpaTY",      # checkbox
    "付款方式": "fldppT9kRl",      # select: 信用卡/支付宝/微信/PayPal/Apple Pay/其他
    "备注": "fldlPCjgZo",          # text
    "是否继续订阅": "fldsdkRDYX",  # select: 是/否/待定
    "月均成本": "fldSOOVuM8",      # formula（自动计算）
    "剩余天数": "fldx4TN2G6",      # formula（自动计算）
    "年份": "fldDU5OUsv",          # formula（自动计算）
    "创建时间": "fldiCXYNra",      # created_at
    "修改时间": "fldaWofRiX",      # updated_at
}

# 可写入的手动字段 ID（add/update 用）
WRITABLE_FIELDS = {
    "名称": "fldbEgOw7p",
    "订阅类型": "fldd2tcEVx",
    "分类": "fldZAyjNKF",
    "金额": "fldrM3aC6c",
    "币种": "fldKGgUeAa",
    "折算人民币": "fldcxTKirZ",
    "开始时间": "fldG3MfmaN",
    "结束时间": "fldaKJ6U5w",
    "自动续费": "fld1dtpaTY",
    "付款方式": "fldppT9kRl",
    "备注": "fldlPCjgZo",
    "是否继续订阅": "fldsdkRDYX",
}

# select 字段（写入时需要用数组格式）
SELECT_FIELDS = {"订阅类型", "分类", "币种", "付款方式", "是否继续订阅"}


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


def calc_end_date(start_str, sub_type):
    """根据订阅类型推算默认结束日期"""
    start_dt = datetime.strptime(start_str, "%Y-%m-%d")
    if sub_type == "月付订阅":
        end_dt = start_dt + timedelta(days=30)
    elif sub_type == "年付订阅":
        try:
            end_dt = start_dt.replace(year=start_dt.year + 1)
        except ValueError:
            end_dt = start_dt.replace(year=start_dt.year + 1, day=28)
    else:
        return None
    return end_dt.strftime("%Y-%m-%d")


def fetch_all_records():
    """获取表中所有记录，返回 (fields, rows, record_ids)"""
    data = run_lark([
        "base", "+record-list",
        "--base-token", BASE_TOKEN,
        "--table-id", TABLE_ID,
        "--format", "json",
        "--limit", "500",
    ])
    if not data.get("ok"):
        print(f"查询记录失败: {data}", file=sys.stderr)
        return [], [], []

    inner = data.get("data") or {}
    return inner.get("fields") or [], inner.get("data") or [], inner.get("record_id_list") or []


def find_record_by_name(name):
    """按名称查找记录，返回 (record_id, field_values_dict) 或 (None, None)"""
    fields, rows, record_ids = fetch_all_records()
    if not fields:
        return None, None

    try:
        name_idx = fields.index("名称")
    except ValueError:
        return None, None

    for rid, row in zip(record_ids, rows):
        val = row[name_idx] if name_idx < len(row) else None
        if val == name:
            record = {}
            for i, f in enumerate(fields):
                record[f] = row[i] if i < len(row) else None
            return rid, record
    return None, None


# ── add 命令 ──────────────────────────────────────────────────────────────────

def cmd_add(args):
    name = args.name
    sub_type = args.type or "月付订阅"
    amount = args.amount
    currency = args.currency or "CNY"
    cny_amount = args.cny_amount
    start_str = args.start or datetime.now(TZ_CST).strftime("%Y-%m-%d")
    end_str = args.end
    auto_renew = args.auto_renew
    category = args.category or ""
    payment = args.payment or ""
    note = args.note or ""
    continue_sub = args.continue_sub or ""
    dry_run = args.dry_run

    # 参数校验
    if not name:
        print("❌ 名称不能为空", file=sys.stderr)
        sys.exit(1)
    if amount is None:
        print("❌ 金额不能为空", file=sys.stderr)
        sys.exit(1)

    # 自动续费默认值
    if auto_renew is None:
        auto_renew = sub_type in ("月付订阅", "年付订阅")

    # 自动推算结束日期
    if not end_str and sub_type in ("月付订阅", "年付订阅"):
        end_str = calc_end_date(start_str, sub_type)

    # 格式化日期
    start_display = f"{start_str} 00:00:00"
    end_display = f"{end_str} 00:00:00" if end_str else None

    # 打印预览
    end_show = end_str or "无（永久）"
    renew_show = "是" if auto_renew else "否"
    print(f"📝 新增订阅{'  [dry-run]' if dry_run else ''}")
    print(f"  名称:       {name}")
    print(f"  订阅类型:   {sub_type}")
    print(f"  金额:       {amount} {currency}")
    if cny_amount is not None:
        print(f"  折算人民币: {cny_amount}")
    print(f"  开始时间:   {start_str}")
    print(f"  结束时间:   {end_show}")
    print(f"  自动续费:   {renew_show}")
    if category:
        print(f"  分类:       {category}")
    if payment:
        print(f"  付款方式:   {payment}")
    if continue_sub:
        print(f"  是否继续:   {continue_sub}")
    if note:
        print(f"  备注:       {note}")

    # 构建 payload
    fields_dict = {
        "名称": name,
        "订阅类型": sub_type,
        "金额": amount,
        "币种": currency,
        "开始时间": start_display,
        "自动续费": auto_renew,
    }
    if cny_amount is not None:
        fields_dict["折算人民币"] = cny_amount
    if category:
        fields_dict["分类"] = category
    if end_display:
        fields_dict["结束时间"] = end_display
    if payment:
        fields_dict["付款方式"] = payment
    if note:
        fields_dict["备注"] = note
    if continue_sub:
        fields_dict["是否继续订阅"] = continue_sub

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
    expiring_within = args.expiring_within
    filter_type = args.type

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
    now = datetime.now(TZ_CST)

    for rid, row in zip(record_ids, rows):
        record = {}
        for f, i in idx.items():
            record[f] = row[i] if i < len(row) else None

        # 类型筛选
        if filter_type and _val(record, "订阅类型") != filter_type:
            continue

        # 即将到期筛选
        if expiring_within:
            sub_type = _val(record, "订阅类型") or ""
            if sub_type == "一次性买断":
                continue
            end_val = record.get("结束时间")
            if not end_val:
                continue
            try:
                if isinstance(end_val, (int, float)):
                    end_dt = datetime.fromtimestamp(end_val / 1000, tz=TZ_CST)
                elif isinstance(end_val, str):
                    end_dt = datetime.strptime(end_val[:10], "%Y-%m-%d").replace(tzinfo=TZ_CST)
                else:
                    continue
                days_left = (end_dt - now).days
                if days_left > expiring_within or days_left < 0:
                    continue
                record["_days_left"] = days_left
            except (OSError, ValueError):
                continue

        matched.append(record)

    if not matched:
        print("无匹配订阅")
        return

    # 打印结果
    print(f"📋 共 {len(matched)} 条订阅\n")

    if expiring_within:
        matched.sort(key=lambda r: r.get("_days_left", 999))

    for r in matched:
        name = _val(r, "名称") or "?"
        sub_type = _val(r, "订阅类型") or "?"
        amount = r.get("金额", "?")
        currency = _val(r, "币种") or "?"
        cny = r.get("折算人民币")
        start = r.get("开始时间", "")
        end = r.get("结束时间", "")

        start_display = _format_date(start)
        end_display = _format_date(end) if end else "永久"
        cny_display = f"  ¥{cny}" if cny else ""
        days_info = ""
        if "_days_left" in r:
            days_info = f"  ⏰ 剩余 {r['_days_left']} 天"

        print(f"  {name}  |  {amount} {currency}{cny_display}  |  {sub_type}  |  {start_display} → {end_display}{days_info}")


# ── update 命令 ───────────────────────────────────────────────────────────────

def cmd_update(args):
    name = args.name
    dry_run = args.dry_run

    if not name:
        print("❌ 请指定要更新的订阅名称", file=sys.stderr)
        sys.exit(1)

    # 查找记录
    rid, record = find_record_by_name(name)
    if not rid:
        print(f"❌ 未找到名为「{name}」的订阅", file=sys.stderr)
        sys.exit(1)

    # 构建更新字段
    fields_dict = {}

    if args.amount is not None:
        fields_dict["金额"] = args.amount
    if args.currency:
        fields_dict["币种"] = args.currency
    if args.cny_amount is not None:
        fields_dict["折算人民币"] = args.cny_amount
    if args.end:
        fields_dict["结束时间"] = f"{args.end} 00:00:00"
    if args.note is not None:
        fields_dict["备注"] = args.note
    if args.auto_renew is not None:
        fields_dict["自动续费"] = args.auto_renew
    if args.category:
        fields_dict["分类"] = args.category
    if args.payment:
        fields_dict["付款方式"] = args.payment
    if args.type:
        fields_dict["订阅类型"] = args.type
    if args.continue_sub:
        fields_dict["是否继续订阅"] = args.continue_sub

    if not fields_dict:
        print("❌ 没有指定要更新的字段", file=sys.stderr)
        sys.exit(1)

    payload = _build_payload(fields_dict)

    # 打印预览
    print(f"✏️ 更新订阅「{name}」{'  [dry-run]' if dry_run else ''}")
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


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="飞书订阅管理")
    subparsers = parser.add_subparsers(dest="command")

    # add
    add_parser = subparsers.add_parser("add", help="新增订阅")
    add_parser.add_argument("--name", required=True, help="订阅名称")
    add_parser.add_argument("--type", default="月付订阅", help="订阅类型: 月付订阅/年付订阅/一次性买断/一次性购买")
    add_parser.add_argument("--amount", type=float, required=True, help="金额")
    add_parser.add_argument("--currency", default="CNY", help="币种: USD/CNY")
    add_parser.add_argument("--cny-amount", type=float, help="折算人民币金额（手动输入，因汇率浮动自行计算）")
    add_parser.add_argument("--start", help="开始日期 YYYY-MM-DD")
    add_parser.add_argument("--end", help="结束日期 YYYY-MM-DD")
    add_parser.add_argument("--auto-renew", action="store_true", default=None, help="自动续费")
    add_parser.add_argument("--no-auto-renew", action="store_false", dest="auto_renew", help="不自动续费")
    add_parser.add_argument("--category", default="", help="分类: AI 工具/效率工具/娱乐会员/云服务")
    add_parser.add_argument("--payment", default="", help="付款方式: 信用卡/支付宝/微信/PayPal/Apple Pay/其他")
    add_parser.add_argument("--continue-sub", default="", help="是否继续订阅: 是/否/待定")
    add_parser.add_argument("--note", default="", help="备注")
    add_parser.add_argument("--dry-run", action="store_true", help="预览，不写入")

    # list
    list_parser = subparsers.add_parser("list", help="查询订阅")
    list_parser.add_argument("--expiring-within", type=int, help="N天内到期")
    list_parser.add_argument("--type", help="按订阅类型筛选")

    # update
    update_parser = subparsers.add_parser("update", help="更新订阅")
    update_parser.add_argument("--name", required=True, help="订阅名称")
    update_parser.add_argument("--type", help="订阅类型")
    update_parser.add_argument("--amount", type=float, help="金额")
    update_parser.add_argument("--currency", help="币种")
    update_parser.add_argument("--cny-amount", type=float, help="折算人民币金额")
    update_parser.add_argument("--end", help="结束日期 YYYY-MM-DD")
    update_parser.add_argument("--auto-renew", action="store_true", default=None, help="自动续费")
    update_parser.add_argument("--no-auto-renew", action="store_false", dest="auto_renew", help="不自动续费")
    update_parser.add_argument("--category", help="分类")
    update_parser.add_argument("--payment", help="付款方式")
    update_parser.add_argument("--continue-sub", help="是否继续订阅: 是/否/待定")
    update_parser.add_argument("--note", help="备注")
    update_parser.add_argument("--dry-run", action="store_true", help="预览，不写入")

    args = parser.parse_args()

    if args.command == "add":
        cmd_add(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "update":
        cmd_update(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
