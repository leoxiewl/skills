---
完整创建时间: 2026-06-20T15:30:00
编辑分类: human+llm
tags:
  - my-skills
  - 软件开发
  - SOP
  - indie-dev
---

# Step 04 — 写技术实现方案

> [!abstract]
> 设计文档确认后，不要直接写代码。先让 AI 出一份技术实现方案，把所有关键决策提前拍板——避免写到一半发现架构走不通。

## 核心方法

1. 把设计文档喂给 AI，说"现在出技术实现方案"
2. AI 列出分阶段实现顺序 + 关键技术决策
3. 你来审查每个决策，确认或纠正
4. 方案确认后存到项目目录（`implementation-plan.md`）

> [!important]
> 实现方案 ≠ 代码。它是一份**决策清单**：用什么技术、为什么、踩过什么坑、分几个阶段做。

---

## 实现方案应该包含什么

| 模块 | 内容 |
|---|---|
| 分阶段实现顺序 | 每个阶段独立可验收，从核心向外扩展 |
| 关键技术决策表 | 问题 → 决策 → 理由，三列对齐 |
| 关键 API 速查 | 不常见但重要的 API，写在方案里随时查 |
| 数据流图 | 各层之间怎么通信 |
| 常见陷阱 | 这个领域已知的坑，提前记录 |

---

## FocusBar 的技术决策（实战案例）

### 平台选型

| 问题 | 决策 | 理由 |
|---|---|---|
| Observable 方案 | `ObservableObject` + `@Published` | macOS 13 不支持 `@Observable` 宏（需 macOS 14+）|
| 窗口类型 | `NSPanel` + `.nonactivatingPanel` | 防止面板展开时抢走当前 App 的焦点 |
| 鼠标追踪 | `NSEvent.addGlobalMonitorForEvents` | 无需 Accessibility 权限，MVP 够用 |
| 动画方案 | `NSAnimationContext` + `NSWindow.animator()` | SwiftUI `withAnimation` 无法控制窗口 frame |
| 窗口层级 | `.statusBar.rawValue + 1` | 浮在 menu bar 上方，全屏 App 下也可见 |
| 类型命名 | `FocusTask`（非 `Task`） | 避免与 Swift.Task 并发类型冲突 |
| 沙箱 | 关闭 | 沙箱会阻断 `NSEvent.addGlobalMonitorForEvents` |
| 项目管理 | xcodegen + `project.yml` | `.xcodeproj` 不进 git，避免冲突 |

### xcodegen 的价值

```yaml
# project.yml 示例
name: FocusBar
options:
  deploymentTarget:
    macOS: "13.0"
targets:
  FocusBar:
    type: application
    platform: macOS
    sources: FocusBar/
```

- 用 YAML 描述项目结构，`xcodegen generate` 生成 `.xcodeproj`
- `.xcodeproj` 加入 `.gitignore`，团队协作无冲突
- 重新生成一条命令，不会有"Xcode 版本不兼容"的问题

### 关键 API 速查（macOS 特有）

```swift
// 窗口层级：浮在 menu bar 上方
window.level = NSWindow.Level(rawValue: NSWindow.Level.statusBar.rawValue + 1)

// 全屏 App 下也保持可见
window.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]

// 全局鼠标监听（需关闭沙箱）
NSEvent.addGlobalMonitorForEvents(matching: [.mouseMoved]) { event in ... }

// 300ms 可取消防抖（鼠标离开后延迟收起）
let item = DispatchWorkItem { self.collapsePanel() }
DispatchQueue.main.asyncAfter(deadline: .now() + 0.3, execute: item)

// 玻璃效果
let view = NSVisualEffectView()
view.material = .sidebar
view.blendingMode = .behindWindow
view.state = .active
```

### 数据流结构

```
AppDelegate
  ├─ MarkdownStore (ObservableObject)       ← 数据层
  ├─ NotchWindow (透明占位，level=statusBar+1)
  └─ PanelController
       ├─ FocusPanel (NSPanel subclass)
       │    └─ NSHostingView → PanelView (SwiftUI)
       └─ 全局鼠标监听 → handleMouseMoved()
```

### 常见陷阱

| 陷阱 | 原因 | 解决方案 |
|---|---|---|
| TextField 无法输入 | `NSPanel` + `.nonactivatingPanel` 永远不成为 key window | 子类化 `NSPanel`，重写 `sendEvent` 在 `leftMouseDown` 时调用 `makeKeyAndOrderFront` |
| 面板展开时抢焦点 | `makeKeyAndOrderFront` 被自动调用 | 用 `.nonactivatingPanel`，只在用户主动点击时才激活 |
| 全局鼠标监听不触发 | 只注册了 global 或 local 其中一种 | 必须同时注册 `addGlobalMonitorForEvents` + `addLocalMonitorForEvents` |
| `@Observable` 报错 | 该宏需要 macOS 14+ | 改用 `ObservableObject` + `@Published` |
| 面板顶部有空隙 | panelRect 计算错误，Y 轴从下往上 | 用 `notchRect.minY` 作为面板顶边，不要加 menuBarH |
| `.onChange(of:)` 两参数报错 | 双参数形式需要 macOS 14+ | 用单参数形式 `.onChange(of: x) { newVal in }` |

---

## 产出物

- `implementation-plan.md`：存于项目根目录
- 这份文档是 AI 写代码的"说明书"，每次让 AI 实现某个模块，先把对应部分贴给它

---

*关联：[[开发一个软件的流程]] · [[Step-03-写设计文档]] · [[Step-05-编写代码与调试]]*
