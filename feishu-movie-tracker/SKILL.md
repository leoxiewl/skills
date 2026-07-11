---
name: feishu-movie-tracker
description: 管理个人观影记录（新增/查询/更新/统计），写入飞书多维表格「个人观影记录库」。当用户说"新增观影""记一部电影""添加剧集""观影记录""查观影"等时触发。
---

# 飞书观影记录 Skill

通过 Claude Code 对话管理个人观影记录，写入飞书多维表格「个人观影记录库」。工具：`lark-cli` 操作 Bitable。

> **核心能力**：自然语言解析 → 结构化字段 → 写入飞书多维表格。支持新增、查询、更新、统计观影记录。

---

## 目标表格

`https://linfenggo.feishu.cn/wiki/DUGUwKxa8iF8QUkWuclcZLPznDg`

- **base_token**: `MGFMbMX1Pasf79sxkO2ciXxFnQb`
- **table_id**: `tbl8b5bhTFamIYxj`

### 字段映射

| 字段名 | field_id | 类型 | 说明 |
|--------|----------|------|------|
| 标题 | fldW7Ertu2 | text | 影视名称（必填） |
| 类型 | fldm53iuP5 | select | 电影/剧集 |
| 状态 | fldhz4FUgo | select | 想看/在看/已看/弃剧 |
| 发布年份 | fldWndJvGo | number | 上映/首播年份 |
| 开始观看日期 | fldmLGtltm | datetime | 开始观看日期 |
| 类别/题材 | fldta9Vss4 | select | 爱情/悬疑/科幻/喜剧/动作/剧情/恐怖/纪录片/动画/历史 |
| 工作室 | fldmBV7DVa | select | 皮克斯/迪士尼/吉卜力/梦工厂/照明娱乐/索尼动画/华纳动画/蓝天工作室/其他 |
| 导演 | fldkvGSqJ1 | select | 导演名（多选） |
| 主演 | fldSJNo3ez | select | 主演名（多选） |
| 豆瓣评分 | fld0X2QYbF | number | 豆瓣评分（1-10） |
| 个人评分 | fldoEW1Gaw | number | 个人评分（1-10） |
| 推荐理由/短评 | fldbpIqOUo | text | 推荐理由或短评 |
| 豆瓣链接 | fldykg8MJj | text | 豆瓣电影链接 |
| 个人标签 | fldjouyxfl | select | 个人标签（多选） |
| 封面图 | fld57LBjqT | attachment | 海报/封面图 |
| 创建时间 | fldydQ9hkt | created_at | 自动记录 |
| 修改时间 | flddfsCCxZ | updated_at | 自动记录 |

---

## Step 1 — 解析用户意图

Claude Code 从用户自然语言中提取以下信息：

### 新增观影记录

用户可能说：
- "新增观影《奥本海默》"
- "记一部电影《盗梦空间》豆瓣9.3分"
- "添加剧集《三体》2023年国产科幻剧"
- "看了《凡人修仙传》给8分"

**提取规则**：

| 字段 | 解析规则 | 默认值 |
|------|----------|--------|
| 标题 | 影视名称（去掉书名号《》也可以） | 必填 |
| 类型 | "电影"→电影, "电视剧/剧集/剧"→剧集, "动漫/动画"→剧集 | 电影 |
| 状态 | "想看"→想看, "在看/正在看"→在看, "看了/已看/看完"→已看, "弃了/弃剧"→弃剧 | 想看 |
| 发布年份 | 提取年份数字 | 空 |
| 开始观看日期 | "X月X日开始"/"从X号看" → 解析日期；"今天看"→今天 | 空 |
| 类别/题材 | 从描述推断：科幻/悬疑/爱情/喜剧/动作/剧情/恐怖/纪录片/动画/历史 | 空 |
| 工作室 | 从产地推断：好莱坞→其他, 国产→其他, 日本→其他, 吉卜力→吉卜力, 皮克斯→皮克斯 | 其他 |
| 个人评分 | "给X分"/"评分X"/"X星" → 数字（1-10） | 空 |
| 推荐理由/短评 | 用户额外说明 | 空 |

### 查询观影记录

- "查观影" / "我的观影记录" → 列出所有记录
- "想看的电影" / "待看列表" → 状态=想看
- "已看的" / "看过的" → 状态=已看
- "2023年看的" / "今年看的" → 按开始观看日期年份筛选
- "科幻片" / "悬疑剧" → 按类别/题材筛选
- "电影" / "剧集" → 按类型筛选

### 更新观影记录

- "《奥本海默》看完了" → 状态改为已看
- "《三体》给9分" → 更新个人评分
- "《纸牌屋》弃了" → 状态改为弃剧
- "《琅琊榜》短评：很好看" → 更新推荐理由/短评

### 统计观影数据

- "观影统计" / "今年看了多少" → 年度观影数量统计
- "观影类型分布" → 按类别/题材统计
- "观影状态分布" → 按状态统计

---

## Step 2 — 运行脚本

脚本路径：`_my/my-skills/feishu-movie-tracker/scripts/movie.py`（相对 vault 根目录）

### 新增观影记录

```bash
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py add \
  --title "奥本海默" \
  --type "电影" \
  --status "想看" \
  --year 2023 \
  --category "剧情" \
  --studio "其他" \
  --rating 8.5

# 预览模式（不写入飞书）
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py add ... --dry-run
```

### 查询观影记录

```bash
# 列出所有记录
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py list

# 按状态筛选
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py list --status "想看"

# 按年份筛选（开始观看日期）
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py list --year 2023

# 按类型筛选
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py list --type "电影"

# 按类别筛选
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py list --category "科幻"
```

### 更新观影记录

```bash
# 更新状态
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py update \
  --title "奥本海默" \
  --status "已看"

# 更新评分
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py update \
  --title "三体" \
  --rating 9

# 更新短评
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py update \
  --title "琅琊榜" \
  --note "古装权谋神作"
```

### 统计观影数据

```bash
# 年度观影统计
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py stats --by-year

# 类型分布
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py stats --by-type

# 类别分布
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py stats --by-category

# 状态分布
python3 _my/my-skills/feishu-movie-tracker/scripts/movie.py stats --by-status
```

---

## 异常处理

| 情况 | 处理 |
|------|------|
| 必填字段缺失（标题） | 提示用户补充，终止 |
| lark-cli 写入失败 | 打印错误详情，exit 1 |
| 查询无结果 | 打印"无匹配记录" |
| 更新时找不到记录 | 打印"未找到名为 X 的记录"，exit 1 |
| 日期解析失败 | 提示用户用 YYYY-MM-DD 格式 |
