---
完整创建时间: 2026-06-20T15:30:00
编辑分类: human+llm
tags:
  - my-skills
  - 软件开发
  - SOP
  - indie-dev
---

# Step 05 — 编写代码与调试

> [!abstract]
> 有了实现方案，就可以让 AI 逐模块写代码。不要一次让 AI 写完所有文件——按阶段推进，每个阶段能独立运行验收。

## 核心节奏

```
实现方案中的一个阶段
  → 让 AI 写这个阶段的代码
  → 编译，看报错
  → 把报错贴给 AI，让它修
  → 运行，截图验收
  → 进入下一阶段
```

> [!tip]
> 每个阶段结束时拍一张截图，记录"当时的样子"。调试过程很容易忘记走过的弯路。

---

## AI 协作写代码的要点

### 给 AI 的上下文要完整

每次让 AI 写/改代码，需要提供：
1. 当前要实现的是哪个阶段
2. 相关文件的**完整内容**（不要只贴片段）
3. 报错信息的**完整文本**（不要截图，要文字）
4. 期望的行为是什么

### 报错处理原则

- 编译报错：直接把报错信息贴给 AI，通常一次就能修
- 运行时表现不对：截图 + 描述"我期望X，实际看到Y"
- 不要自己猜原因——先把现象告诉 AI，让 AI 分析

> [!warning]
> 不确定的地方不要让 AI 猜。应该先搜索验证（查文档、看已有代码），或者直接问清楚再写代码。

---

## FocusBar 编写过程中踩的坑（实战）

### 坑 1：TextField 无法输入

**现象**：面板展开后，点击 TextField，键盘输入没反应。

**根本原因**：`NSPanel` + `.nonactivatingPanel` 让面板永远不成为 key window，系统不会把键盘事件路由到它。

**解决方案**：子类化 `NSPanel`，重写 `sendEvent`：

```swift
private final class FocusPanel: NSPanel {
    override var canBecomeKey: Bool { true }
    override func sendEvent(_ event: NSEvent) {
        if event.type == .leftMouseDown, !isKeyWindow {
            makeKeyAndOrderFront(nil)
            NSApp.activate(ignoringOtherApps: false)
        }
        super.sendEvent(event)
    }
}
```

**教训**：`nonactivatingPanel` 解决"不抢焦点"，但副作用是无法输入。两者需要手动平衡。

---

### 坑 2：面板顶部有空隙

**现象**：面板展开后，顶部与刘海屏之间有一段空白。

**根本原因**：panelRect 的 Y 坐标计算错误。macOS 坐标系 Y 轴从下往上，容易搞反。

**解决方案**：

```swift
// ❌ 错误：多加了 menuBarH，导致面板位置偏下
let y = screen.frame.maxY - menuBarH - panelContentHeight

// ✅ 正确：从 notch 底边直接向下延伸
let notchBottomY = notchRect(for: screen).minY
let y = notchBottomY - panelContentHeight
```

**教训**：涉及窗口坐标，务必在注释里写清楚"Y 轴方向"，否则很容易再犯。

---

### 坑 3：macOS 版本兼容

项目目标 macOS 13，以下 API 都需要注意：

| API | 最低版本 | 替代方案 |
|---|---|---|
| `@Observable` 宏 | macOS 14 | `ObservableObject` + `@Published` |
| `.onChange(of:) { old, new in }` | macOS 14 | `.onChange(of:) { new in }` |
| `.strikethrough(color: .tertiary)` | — | `.tertiary` 不是 Color，去掉 color 参数 |

**教训**：用 AI 写代码时，每次都要提醒"目标是 macOS 13"，否则 AI 默认会用最新 API。

---

### 坑 4：类型命名冲突

```swift
// ❌ 与 Swift.Task 并发类型冲突，编译器报错
struct Task { ... }

// ✅ 加前缀区分
struct FocusTask { ... }
```

**教训**：自定义类型命名尽量加项目前缀，避免与标准库或框架冲突。

---

## 调试工具

| 工具 | 用途 |
|---|---|
| `xcodebuild build` | 命令行编译，快速看报错 |
| Xcode Console | 看 `print()` 输出和运行时日志 |
| 截图 + 描述 | 告诉 AI 界面问题 |
| `po variable` (LLDB) | 在断点处打印对象 |

---

## 产出物

- 可运行的各阶段代码
- 每个阶段的截图（用于记录进度和 README 素材）
- 踩坑记录（写进这份文档）

---

*关联：[[开发一个软件的流程]] · [[Step-04-技术实现方案]] · [[Step-06-UI打磨与迭代]]*
