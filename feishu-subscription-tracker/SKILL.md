---
name: feishu-subscription-tracker
description: 管理个人订阅记录（新增/查询/更新/取消），写入飞书多维表格「个人订阅管理」。当用户说"新增订阅""记一笔订阅""添加订阅""订阅管理""查订阅"等时触发。
---

# 飞书订阅管理 Skill

通过 `lark-cli` 操作飞书多维表格「个人订阅管理」，管理订阅记录。

---

## 目标表格

- **base_token**: `GIbpbyT74aqJFpsSoUvcRhlQnXe`
- **table_id**: `tblgd8eOC8d3GvvR`（订阅记录）

---

## 记录结构（两层）

| 层级 | 作用 | 必填字段 | 禁止字段 |
|------|------|----------|----------|
| **父记录** | 产品目录节点，无金额数据 | `产品名称` | 其余全部留空 |
| **子记录** | 月粒度花费，含金额 | `父记录`、`产品名称`、`开始时间`、`折算人民币`、`订阅类型`、`分类` | — |

> 仪表盘"月度花费趋势"读全表按月份分组、求和折算人民币。父记录无金额，自然不参与统计。

---

## 关键字段

| 字段名 | field_id | 类型 | 说明 |
|--------|----------|------|------|
| 产品名称 | fld8s2j8JQ | multiselect | 父记录和子记录都填 |
| 父记录 | fldR6Z8HxO | link (self) | 子记录填，指向父记录 record_id |
| 开始时间 | fldG3MfmaN | datetime | 子记录填，精确到订阅周期日（驱动月份公式字段，TEXT 取 YYYY/MM） |
| 结束时间 | fldaKJ6U5w | datetime | 子记录填，= 下一个周期日（即该条记录的到期点） |
| 折算人民币 | fldcxTKirZ | number | 子记录填，该月金额（见计算规则） |
| 订阅类型 | fldd2tcEVx | select | 子记录填：月付订阅/年付订阅/一次性购买/一次性买断 |
| 分类 | fldZAyjNKF | select | 子记录填：AI 工具/效率工具/娱乐会员/内容工具/生活工具/Token |
| 月份 | fldCC9cVbM | formula(只读) | 自动计算 TEXT(开始时间,"YYYY/MM") |

---

## 月度金额计算规则

| 订阅类型 | 子记录数量 | 折算人民币（每条） |
|----------|------------|-------------------|
| 月付订阅 | 从开始月到结束月，每月 1 条 | = 每月实付金额 |
| 年付订阅 | 从开始月起 12 个月，共 12 条 | = 年费总额 ÷ 12 |
| 一次性购买 | 仅开始月 1 条 | = 总金额 |
| 一次性买断 | 仅开始月 1 条 | = 总金额 |

---

## 新增订阅流程

### Step 1 — 解析用户信息

从用户描述中提取：

| 信息 | 解析 |
|------|------|
| 产品名称 | 订阅产品名 |
| 订阅类型 | "月付/按月"→月付订阅，"年付/按年"→年付订阅，"买断/永久"→一次性买断，"一次性"→一次性购买 |
| 折算人民币 | 年费/月费总额（人民币） |
| 开始月 | 开始时间的年月；若给的是到期日，反推：开始月 = 到期日 - 1年（年付）或 - N月（月付） |
| 结束月 | 到期日对应月份（月付/年付需要） |
| 分类 | 从产品名推断或用户指定 |

**日期推算规则**：
- 精确推算每条子记录的开始和结束时间，不要用月份 1 日代替
- 年付：到期日 - 1 年 = 订阅开始日；每月子记录 = [N月订阅日, (N+1)月订阅日)
- 月付：按实际订阅周期日逐月推算
- 示例："微信读书年付 168，2026-10-08 到期" →
  - 开始日 2025-10-08，12 条子记录：
    - 2025-10-08 ~ 2025-11-08 / 2025-11-08 ~ 2025-12-08 / … / 2026-09-08 ~ 2026-10-08
  - 每条 折算人民币 = 168 ÷ 12 = 14

### Step 2 — 检查是否已有同产品父记录

```bash
lark-cli base +record-list --base-token GIbpbyT74aqJFpsSoUvcRhlQnXe \
  --table-id tblgd8eOC8d3GvvR --as user
```

- 若已有该产品父记录（产品名称匹配、无折算人民币）→ 直接用该 record_id
- 若没有 → 创建新父记录

### Step 3 — 创建父记录（如需）

```bash
lark-cli base +record-batch-create \
  --base-token GIbpbyT74aqJFpsSoUvcRhlQnXe \
  --table-id tblgd8eOC8d3GvvR \
  --json '{"fields":["fld8s2j8JQ"],"rows":[[["产品名称"]]]}' --as user
```

记录返回的 `record_id_list[0]` 作为父记录 ID。

### Step 4 — 创建月度子记录

```bash
lark-cli base +record-batch-create \
  --base-token GIbpbyT74aqJFpsSoUvcRhlQnXe \
  --table-id tblgd8eOC8d3GvvR \
  --json '{
    "fields": ["fldR6Z8HxO","fld8s2j8JQ","fldG3MfmaN","fldcxTKirZ","fldd2tcEVx","fldZAyjNKF"],
    "rows": [
      [[{"id":"<父记录ID>"}], ["产品名称"], "YYYY-MM-01 00:00:00", 金额, "订阅类型", "分类"],
      ...
    ]
  }' --as user
```

> **关键格式**：`父记录`（link 字段）在 rows 里必须用 `[{"id":"..."}]`（数组包裹），不能是裸对象 `{"id":"..."}`。

---

## 查询订阅

```bash
# 列出所有记录
lark-cli base +record-list --base-token GIbpbyT74aqJFpsSoUvcRhlQnXe \
  --table-id tblgd8eOC8d3GvvR --as user

# 按产品名称搜索
lark-cli base +record-search --base-token GIbpbyT74aqJFpsSoUvcRhlQnXe \
  --table-id tblgd8eOC8d3GvvR \
  --filter '{"conjunction":"and","conditions":[{"field_name":"产品名称","operator":"contains","value":"ChatGPT"}]}' \
  --as user
```

---

## 异常处理

| 情况 | 处理 |
|------|------|
| 产品名不在 `产品名称` 选项中 | 直接写入，平台自动新增选项 |
| link 字段格式错误 | rows 里父记录必须是 `[{"id":"..."}]` 数组形式 |
| 年付到期日不确定开始月 | 向用户确认，或用"到期日 - 12 个月"推算 |
| 已有同产品父记录 | 复用已有父记录，不重复创建 |
