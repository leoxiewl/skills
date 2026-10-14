---
name: gcal-to-feishu-bitable
description: 将 Google Calendar 指定日期的有效事件（含起止时间）同步写入飞书多维表格「个人时间输入与可视化管理系统」。当用户说"同步日历到飞书""日历写飞书""同步到多维表格""gcal sync feishu"等时触发。
---

# 日历同步飞书 Skill

将 Google Calendar 当天（或指定日期）所有含起止时间的事件写入飞书多维表格。工具：`gws` 读取日历 + `lark-cli` 写入 Bitable。

> **边界**：全天事件（无具体时间）跳过不写；重复运行会先清除当天旧记录再重写，保持幂等。

---

## 目标表格

`https://linfenggo.feishu.cn/wiki/QAptwowC5iOjJPkEGpuclkM1nee?table=tblTWirrJcB4xeH1&view=vewk2HamvJ`

写入字段：

| 字段 | 来源 |
|---|---|
| 日程标题 | Google Calendar 事件标题 |
| 日期 | 目标日期 00:00 (CST) |
| 开始时间 | 事件开始时间 |
| 结束时间 | 事件结束时间 |
| 角色分类 | 日历名称（直接写入，自动创建 option） |
| 日历来源 | 固定 "Google Calendar" |
| 备注 | Google Calendar 事件备注 (description) |

---

## Step 1 — 确认目标日期 & 检查认证

用户可以说"今天""昨天""2026-06-27"——换算为绝对日期。

```bash
gws auth status
```

- `auth_method: none` → 提示运行 `gws auth login`，**终止**
- 认证正常 → 继续

---

## Step 2 — 运行脚本

脚本路径：`_my/my-skills/gcal-to-feishu-bitable/scripts/gcal_to_feishu.py`（相对 vault 根目录）

```bash
# 预览：打印事件列表，不写入飞书
python3 _my/my-skills/gcal-to-feishu-bitable/scripts/gcal_to_feishu.py --date YYYY-MM-DD --dry-run

# 写入飞书多维表格
python3 _my/my-skills/gcal-to-feishu-bitable/scripts/gcal_to_feishu.py --date YYYY-MM-DD
```

`--date` 默认为今天，可省略。

脚本自动完成：
1. 并发拉取所有日历的当天事件
2. 过滤全天事件和系统日历（月相、中国节假日）
3. 删除飞书表中当天已有的旧记录
4. 批量写入新记录（每批 ≤ 500 条）
5. 打印写入摘要

---

## 异常处理

| 情况 | 处理 |
|---|---|
| gws 认证失败 | 提示 `gws auth login`，终止 |
| 当天无含时间的事件 | 打印"无有效事件"，不写入 |
| lark-cli 写入失败 | 打印错误详情，exit 1 |
| 全天事件 | 跳过，不写入 |
