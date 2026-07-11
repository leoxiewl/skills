#!/usr/bin/env python3
"""
日历总结计算脚本
用法: python3 calendar_summary.py --date YYYY-MM-DD
依赖: gws CLI 已安装且已认证 (gws auth login)

功能:
1. 调用 gws 获取所有日历列表
2. 逐日历查询当天事件
3. 计算每个事件时长 (跨日截断, 全天计0h)
4. 按角色合并汇总
5. 输出 Markdown 表格 (追加到日记末尾的格式)
"""

import json
import os
import subprocess
import sys
import argparse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed


# ============================================================
# 日历角色映射 (依据日历规则)
# ============================================================
ROLE_MAP = {
    "🏃🏻\u200d♂️运动": ("🌿 健康", "运动"),
    "💤睡眠": ("🌿 健康", "睡眠"),
    "🧭 Founder": ("🧭 Founder", "Founder"),
    "职业工作": ("💼 职业工作", "职业工作"),
    "生活": ("🌍 生活", "生活"),
    "娱乐": ("🌍 生活", "娱乐"),
    "🤝 伴侣": ("🤝 关系", "伴侣"),
    "🤝 朋友": ("🤝 关系", "朋友"),
    "🤝 下一代": ("🤝 关系", "下一代"),
    "🤝 origin 家庭": ("🤝 关系", "origin 家庭"),
    "CEO(Sys)": ("🧠 系统", "CEO(Sys)"),
    "投资": ("💰 投资", "投资"),
}

# 跳过的系统日历 (不参与统计)
SKIP_CALENDARS = ["月相", "中国节假日"]

# 信号灯阈值
SIGNAL_THRESHOLDS = {
    "🌿 健康": lambda h: "✅" if h >= 7 else ("🟡" if h >= 5 else "⚠️"),
    "🧭 Founder": lambda h: "✅" if h >= 1 else ("🟡" if h > 0 else "🔴"),
    "💼 职业工作": lambda h: "✅" if h >= 4 else ("🟡" if h >= 2 else "⚠️"),
    "🤝 关系": lambda h: "✅" if h >= 1 else "🔴 归零",
    "🌍 生活": lambda h: "—",
    "🧠 系统": lambda h: "—",
    "💰 投资": lambda h: "—",
}

# 角色显示顺序
ROLE_ORDER = ["💼 职业工作", "🌿 健康", "🌍 生活", "🧠 系统", "🧭 Founder", "🤝 关系", "💰 投资"]


def run_gws(args):
    """执行 gws 命令并返回 JSON 结果"""
    cmd = ["gws"] + args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(f"GWS 命令失败: {' '.join(cmd)}", file=sys.stderr)
        print(f"stderr: {result.stderr}", file=sys.stderr)
        return None
    # 去掉 keyring 提示行
    lines = result.stdout.strip().split("\n")
    json_start = 0
    for i, line in enumerate(lines):
        if line.strip().startswith("{"):
            json_start = i
            break
    json_str = "\n".join(lines[json_start:])
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        # 可能是 NDJSON (--page-all)
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


def get_calendar_list():
    """获取所有日历列表, 返回 [(summary, id), ...]"""
    data = run_gws(["calendar", "calendarList", "list", "--page-all"])
    if not data or "items" not in data:
        print("无法获取日历列表", file=sys.stderr)
        return []
    calendars = []
    for item in data["items"]:
        summary = item.get("summary", "")
        cal_id = item.get("id", "")
        if summary and cal_id:
            calendars.append((summary, cal_id))
    return calendars


def get_events_for_day(cal_id, date_str):
    """查询指定日历在指定日期的事件"""
    time_min = f"{date_str}T00:00:00+08:00"
    time_max = f"{date_str}T23:59:59+08:00"
    params = json.dumps({
        "calendarId": cal_id,
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": True,
        "orderBy": "startTime"
    })
    data = run_gws(["calendar", "events", "list", "--params", params])
    if not data:
        return []
    return data.get("items", [])


def warm_discovery():
    """discovery 预热: 在并行查询前先串行调一次 gws, 触发 calendar v3
    discovery doc 缓存构建。calendarList.list 与 events.list 共用同一份
    discovery, 因此一次调用即可。预热后并行线程命中缓存, 不再各自重复拉取。
    返回获取到的日历列表 (复用结果, 避免二次请求)。
    """
    return get_calendar_list()


def process_one_calendar(cal_name, cal_id, date_str, day_start, day_end):
    """查询并计算单个日历当天的事件 (供线程池调用)"""
    events = get_events_for_day(cal_id, date_str)
    total_hours = 0.0
    event_list = []
    for ev in events:
        hours, is_all_day, is_cross_day, c_start, c_end = calculate_event_hours(
            ev, day_start, day_end
        )
        total_hours += hours
        event_list.append({
            "summary": ev.get("summary", "(无标题)"),
            "hours": hours,
            "all_day": is_all_day,
            "cross_day": is_cross_day,
            "start": c_start,
            "end": c_end,
        })
    return cal_name, {
        "count": len(events),
        "hours": round(total_hours, 2),
        "events": event_list,
    }


def parse_datetime(dt_str):
    """解析 ISO 8601 时间字符串, 返回 naive datetime"""
    # 处理 +08:00 时区
    if "+" in dt_str and ":" == dt_str[-3:-2]:
        dt_str = dt_str[:-6]
    elif "Z" in dt_str:
        dt_str = dt_str.replace("Z", "")
    return datetime.strptime(dt_str, "%Y-%m-%dT%H:%M:%S")


def calculate_event_hours(event, day_start, day_end):
    """计算事件在目标日期范围内的时长 (小时)
    返回 (hours, is_all_day, is_cross_day, clamped_start, clamped_end)
    全天/无效事件的 clamped_start/clamped_end 为 None
    """
    start_obj = event.get("start", {})
    end_obj = event.get("end", {})

    # 全天事件 (start.date 而非 start.dateTime)
    if "date" in start_obj:
        return 0.0, True, False, None, None

    start_str = start_obj.get("dateTime")
    end_str = end_obj.get("dateTime")
    if not start_str or not end_str:
        return 0.0, True, False, None, None

    start = parse_datetime(start_str)
    end = parse_datetime(end_str)

    # 跨日截断
    is_cross_day = start < day_start or end > day_end
    start = max(start, day_start)
    end = min(end, day_end)

    if end <= start:
        return 0.0, False, is_cross_day, None, None

    hours = (end - start).total_seconds() / 3600
    return round(hours, 2), False, is_cross_day, start, end


def build_event_detail(calendar_data, day_start, day_end):
    """生成"全部事件明细"表: 按开始时间排序的完整时间线,
    事件之间的空白时段作为"无日历记录"单独列出。返回 Markdown 行列表。
    """
    timed = []      # 有起止时间的事件
    all_day = []    # 全天事件 (计 0h)
    for cal_name, data in calendar_data.items():
        for ev in data["events"]:
            if ev["all_day"] or ev.get("start") is None:
                all_day.append((cal_name, ev))
            else:
                timed.append((cal_name, ev))
    timed.sort(key=lambda x: x[1]["start"])

    def fmt(dt):
        return "24:00" if dt == day_end else dt.strftime("%H:%M")

    md = []
    md.append("### 全部事件明细\n")
    md.append("| 时间段 | 日历 | 总时长 | 占 24h | 笔记 |")
    md.append("|---|---|--:|--:|---|")

    if not timed:
        # 整天无定时事件
        gap_h = round((day_end - day_start).total_seconds() / 3600, 2)
        md.append(f"| 00:00~24:00 | *(无日历记录)* | {gap_h:.2f}h | 100% | 当天无日历事件记录 |")
    else:
        covered = day_start  # 已被事件覆盖到的时间指针
        for cal_name, ev in timed:
            s, e = ev["start"], ev["end"]
            # 事件前的空白时段
            if s > covered:
                gap_h = round((s - covered).total_seconds() / 3600, 2)
                gap_pct = round(gap_h / 24 * 100)
                md.append(f"| {fmt(covered)}~{fmt(s)} | *(无日历记录)* | {gap_h:.2f}h | {gap_pct}% | |")
            # 笔记: 事件名 + 跨日/重叠标记
            notes = []
            name = ev.get("summary", "")
            if name and name != "(无标题)":
                notes.append(name)
            if ev.get("cross_day"):
                notes.append("[跨日截断]")
            if s < covered:
                notes.append("[时间重叠]")
            note = "；".join(notes)
            pct = round(ev["hours"] / 24 * 100)
            md.append(f"| {fmt(s)}~{fmt(e)} | {cal_name} | {ev['hours']:.2f}h | {pct}% | {note} |")
            if e > covered:
                covered = e
        # 末尾空白时段
        if covered < day_end:
            gap_h = round((day_end - covered).total_seconds() / 3600, 2)
            gap_pct = round(gap_h / 24 * 100)
            md.append(f"| {fmt(covered)}~24:00 | *(无日历记录)* | {gap_h:.2f}h | {gap_pct}% | |")

    # 全天事件单独罗列
    if all_day:
        md.append("")
        items = "、".join(
            f"{ev.get('summary', '(无标题)')}（{cal_name}）" for cal_name, ev in all_day
        )
        md.append(f"**全天事件（计 0h）**：{items}")

    return md


def generate_summary(date_str):
    """主函数: 生成日历总结"""
    day_start = datetime.strptime(date_str, "%Y-%m-%d")
    day_end = day_start + timedelta(days=1)

    # Step 1: discovery 预热 + 获取日历列表 (一次调用同时完成)
    print(f"正在预热 discovery 并获取日历列表...", file=sys.stderr)
    calendars = warm_discovery()
    if not calendars:
        print("未获取到任何日历, 请检查 gws 认证状态", file=sys.stderr)
        return None

    print(f"共 {len(calendars)} 个日历", file=sys.stderr)

    # Step 2: 并行查询事件 & 计算 (discovery 已预热, 线程命中缓存)
    # 总耗时 ≈ 最慢的那个日历, 而非所有日历求和
    targets = [(name, cid) for name, cid in calendars if name not in SKIP_CALENDARS]
    calendar_data = {}  # {cal_name: {"count": N, "hours": float, "events": [...]}}

    if targets:
        with ThreadPoolExecutor(max_workers=len(targets)) as executor:
            futures = {
                executor.submit(
                    process_one_calendar, name, cid, date_str, day_start, day_end
                ): name
                for name, cid in targets
            }
            for future in as_completed(futures):
                cal_name, data = future.result()
                calendar_data[cal_name] = data
                print(f"  完成: {cal_name}", file=sys.stderr)

    # Step 3: 按角色合并
    role_data = {}  # {role: {"hours": float, "calendars": [cal_names]}}
    for cal_name, data in calendar_data.items():
        if cal_name in ROLE_MAP:
            role, _ = ROLE_MAP[cal_name]
            if role not in role_data:
                role_data[role] = {"hours": 0.0, "calendars": []}
            role_data[role]["hours"] += data["hours"]
            role_data[role]["calendars"].append(cal_name)

    # 四舍五入角色时长
    for role in role_data:
        role_data[role]["hours"] = round(role_data[role]["hours"], 2)

    # Step 4: 生成 Markdown
    total_recorded = round(sum(d["hours"] for d in calendar_data.values()), 2)
    total_pct = round(total_recorded / 24 * 100)
    unrecorded = round(24 - total_recorded, 2)
    unrecorded_pct = round(unrecorded / 24 * 100)

    md = []
    md.append("## 📊 日历时间数据\n")
    md.append("### 日历级别明细\n")
    md.append("| 日历 | 事件数 | 总时长 | 占 24h |")
    md.append("|---|--:|--:|--:|")

    # 按时长降序
    sorted_cals = sorted(calendar_data.items(), key=lambda x: x[1]["hours"], reverse=True)
    for cal_name, data in sorted_cals:
        hours = data["hours"]
        pct = round(hours / 24 * 100)
        md.append(f"| {cal_name} | {data['count']} | {hours:.2f}h | {pct}% |")

    md.append(f"| **合计** |  | **{total_recorded:.2f}h** | **{total_pct}%** |")

    md.append("")
    md.append("### 角色级别汇总\n")
    md.append("| 角色类别 | 总时长 | 占 24h | 信号 |")
    md.append("|---|--:|--:|---|")

    for role in ROLE_ORDER:
        if role in role_data:
            hours = role_data[role]["hours"]
            pct = round(hours / 24 * 100)
            signal_fn = SIGNAL_THRESHOLDS.get(role, lambda h: "—")
            signal = signal_fn(hours)
            md.append(f"| {role} | {hours:.2f}h | {pct}% | {signal} |")

    md.append(f"| **已记录** | **{total_recorded:.2f}h** | **{total_pct}%** | |")
    md.append(f"| **未记录** | **{unrecorded:.2f}h** | **{unrecorded_pct}%** | |")

    md.append("")
    md.append("### 红线检查\n")

    # 关系检查
    rel_hours = role_data.get("🤝 关系", {}).get("hours", 0)
    if rel_hours == 0:
        md.append("- [ ] 🤝 关系：🔴 所有关系角色归零")
    elif rel_hours < 1:
        md.append(f"- [ ] 🤝 关系：⚠️ 投入偏低（{rel_hours:.1f}h）")
    else:
        md.append(f"- [x] 🤝 关系：✅ 有投入（{rel_hours:.1f}h）")

    # 运动检查
    exercise_hours = calendar_data.get("🏃🏻\u200d♂️运动", {}).get("hours", 0)
    if exercise_hours == 0:
        md.append("- [ ] 🏃 运动：🔴 无运动记录")
    elif exercise_hours < 0.5:
        md.append(f"- [ ] 🏃 运动：⚠️ 运动不足（{exercise_hours:.1f}h），无力量训练")
    else:
        md.append(f"- [x] 🏃 运动：✅ 有运动（{exercise_hours:.1f}h）")

    # 睡眠检查
    sleep_hours = calendar_data.get("💤睡眠", {}).get("hours", 0)
    if sleep_hours >= 7:
        md.append(f"- [x] 😴 睡眠：✅ 睡眠充足（{sleep_hours:.1f}h）")
    elif sleep_hours >= 6:
        md.append(f"- [ ] 😴 睡眠：🟡 略不足（{sleep_hours:.1f}h）")
    else:
        md.append(f"- [ ] 😴 睡眠：⚠️ 严重不足（{sleep_hours:.1f}h）")

    # Founder 检查
    founder_hours = calendar_data.get("🧭 Founder", {}).get("hours", 0)
    if founder_hours >= 1:
        md.append(f"- [x] 🧭 Founder：✅ 核心战役有推进（{founder_hours:.1f}h）")
    elif founder_hours > 0:
        md.append(f"- [ ] 🧭 Founder：🟡 投入偏低（{founder_hours:.1f}h）")
    else:
        md.append("- [ ] 🧭 Founder：🔴 今日无投入")

    # 全部事件明细 (完整时间线)
    md.append("")
    md.extend(build_event_detail(calendar_data, day_start, day_end))

    return "\n".join(md)


def find_diary_file(date_str):
    """定位日记文件路径
    格式: 个人OS/02_Reviews/YYYY/YYYY-MM/YYYY-Www/YYYY-MM-DD-周X.md
    """
    import os

    WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    weekday_name = WEEKDAY_NAMES[dt.weekday()]

    # 计算 ISO 周号
    iso_year, iso_week, _ = dt.isocalendar()
    week_str = f"{iso_year}-W{iso_week:02d}"

    year = dt.strftime("%Y")
    month = dt.strftime("%Y-%m")

    # 在仓库中搜索日记文件
    # 优先搜索精确路径
    base_dir = os.environ.get("GIT_WIKI_ROOT", "")
    if not base_dir:
        # 尝试从当前工作目录推断
        cwd = os.getcwd()
        if "_my" in cwd or "git-local-wiki" in cwd:
            # 向上找到仓库根目录
            parts = cwd.split("/")
            for i, p in enumerate(parts):
                if p == "git-local-wiki":
                    base_dir = "/".join(parts[:i+1])
                    break

    if not base_dir:
        base_dir = os.path.expanduser("~/linfeng/mydata/git-local-wiki")

    exact_path = os.path.join(
        base_dir, "个人OS", "02_Reviews", year, month, week_str,
        f"{date_str}-{weekday_name}.md"
    )

    if os.path.exists(exact_path):
        return exact_path

    # 如果精确路径不存在, 在周目录下搜索日期匹配的文件
    week_dir = os.path.join(base_dir, "个人OS", "02_Reviews", year, month, week_str)
    if os.path.isdir(week_dir):
        for f in os.listdir(week_dir):
            if f.startswith(date_str) and f.endswith(".md"):
                return os.path.join(week_dir, f)

    return None


def write_to_diary(diary_path, markdown_content):
    """将日历总结追加到日记文件末尾
    如果已有 📊 日历时间数据 区域, 替换旧数据
    """
    with open(diary_path, "r", encoding="utf-8") as f:
        content = f.read()

    # 检查是否已有日历时间数据区域
    marker = "## 📊 日历时间数据"
    if marker in content:
        # 替换旧数据: 从 marker 开始到下一个 ## 或文件末尾
        start_idx = content.index(marker)
        # 找下一个 ## 标题 (非子标题 ###)
        rest = content[start_idx:]
        next_section_idx = None
        for i in range(len(rest)):
            if i > 0 and rest[i:i+3] == "\n##" and rest[i+3] != "#":
                next_section_idx = i
                break

        if next_section_idx:
            old_section = rest[:next_section_idx]
            new_content = content[:start_idx] + markdown_content + "\n" + content[start_idx + len(old_section):]
        else:
            # marker 之后直到文件末尾都是旧数据
            new_content = content[:start_idx] + markdown_content

        with open(diary_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"已替换旧数据: {diary_path}", file=sys.stderr)
    else:
        # 追加到文件末尾 (在最后一个 ## 相关 区域之前, 或直接末尾)
        # 找 "## 相关" 区域
        related_marker = "\n## 相关"
        if related_marker in content:
            related_idx = content.index(related_marker)
            new_content = content[:related_idx] + "\n" + markdown_content + content[related_idx:]
        else:
            new_content = content.rstrip() + "\n\n" + markdown_content

        with open(diary_path, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"已追加数据: {diary_path}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="日历总结计算脚本")
    parser.add_argument("--date", required=True, help="目标日期 YYYY-MM-DD")
    parser.add_argument("--write", action="store_true", help="将结果写入日记文件 (否则只输出到 stdout)")
    args = parser.parse_args()

    # 验证日期格式
    try:
        datetime.strptime(args.date, "%Y-%m-%d")
    except ValueError:
        print(f"日期格式错误: {args.date}, 应为 YYYY-MM-DD", file=sys.stderr)
        sys.exit(1)

    result = generate_summary(args.date)
    if not result:
        print("生成总结失败", file=sys.stderr)
        sys.exit(1)

    if args.write:
        diary_path = find_diary_file(args.date)
        if diary_path:
            write_to_diary(diary_path, result)
            print(f"日记文件: {diary_path}", file=sys.stderr)
        else:
            print(f"未找到日记文件, 仅输出到 stdout", file=sys.stderr)
            print(result)
    else:
        print(result)


if __name__ == "__main__":
    main()
