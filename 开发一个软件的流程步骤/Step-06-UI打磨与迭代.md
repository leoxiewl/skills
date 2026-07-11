---
完整创建时间: 2026-06-20T15:30:00
编辑分类: human+llm
tags:
  - my-skills
  - 软件开发
  - SOP
  - indie-dev
---

# Step 06 — UI 打磨与迭代

> [!abstract]
> 功能跑通之后，界面往往"能用但不好看"。这一步把 UI 从"可以用"推到"想用"。关键是用截图和参考图来驱动，而不是用文字描述。

## 核心方法

1. 跑起来，截图，发给 AI："这里有问题，具体是 X"
2. 找一张参考图（或描述想要的风格），一起发给 AI
3. AI 出修改方案，你来审查
4. 改完再截图，对比前后

> [!tip]
> **截图 > 文字描述。** "顶部有空隙"不如截图加红圈直观。AI 看到截图能更快定位问题。

---

## UI 迭代的典型问题类型

| 类型 | 描述 | 处理方式 |
|---|---|---|
| 结构问题 | 有空隙、边框多余、对不齐 | 截图 + 标注，让 AI 找坐标/padding 错误 |
| 视觉问题 | 颜色土、字体丑、对比度低 | 发参考图 + 描述期望风格 |
| 交互问题 | 点击没反应、动画卡顿 | 描述操作步骤 + 期望行为 vs 实际行为 |
| 层级问题 | 被遮挡、z-order 错误 | 描述哪个元素挡住了哪个 |

---

## FocusBar UI 迭代过程（实战案例）

### 第一版："能用，但太丑"

初版只有功能，样式全用默认：
- 标准白色背景窗口
- 双层边框
- 无视觉层次

**用户反馈**（给 AI 的指令）：
> 1. 整体风格太丑，要现代简约
> 2. 弹窗有双层框，去掉
> 3. 弹出的框跟上边框有空隙，填满
> 4. 要有悬浮玻璃效果，像 iOS 最新版那种
> 5. 加一个齿轮设置按钮

### 改进方向

**玻璃效果**用 `NSVisualEffectView`（SwiftUI 包装成 `NSViewRepresentable`）：

```swift
struct GlassMaterial: NSViewRepresentable {
    func makeNSView(context: Context) -> NSVisualEffectView {
        let v = NSVisualEffectView()
        v.material = .sidebar        // sidebar 比 hudWindow 更通透
        v.blendingMode = .behindWindow
        v.state = .active
        return v
    }
}
```

**面板形状**：顶部直角（贴合刘海），底部圆角：

```swift
struct PanelShape: Shape {
    let radius: CGFloat = 14
    func path(in rect: CGRect) -> Path {
        var p = Path()
        p.move(to: CGPoint(x: rect.minX, y: rect.minY))      // 左上：直角
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.minY))   // 右上：直角
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - radius))
        p.addQuadCurve(to: CGPoint(x: rect.maxX - radius, y: rect.maxY),
                       control: CGPoint(x: rect.maxX, y: rect.maxY))
        p.addLine(to: CGPoint(x: rect.minX + radius, y: rect.maxY))
        p.addQuadCurve(to: CGPoint(x: rect.minX, y: rect.maxY - radius),
                       control: CGPoint(x: rect.minX, y: rect.maxY))
        p.closeSubpath()
        return p
    }
}
```

**颜色系统**：集中定义 Design Token，不要散落在各处：

```swift
private enum DS {
    static let blue   = Color(red: 0.28, green: 0.62, blue: 1.00)  // 本周 #47A0FF
    static let amber  = Color(red: 1.00, green: 0.72, blue: 0.20)  // 今日 #FFB833
    static let coral  = Color(red: 1.00, green: 0.36, blue: 0.36)  // 正在做 #FF5C5C
    static let topGrad = Color(red: 0.12, green: 0.35, blue: 0.82) // 渐变 #1F59D1
}
```

### 第二版："好看，但不够显眼"

**用户反馈**：
> 面板不够显眼，参考这张蓝色截图，加一些亮色

**解决**：在玻璃底层叠加蓝色渐变色带（顶部浓 → 底部淡）：

```swift
LinearGradient(
    stops: [
        .init(color: DS.topGrad.opacity(0.28), location: 0.0),
        .init(color: DS.topGrad.opacity(0.08), location: 0.45),
        .init(color: .clear, location: 1.0)
    ],
    startPoint: .top, endPoint: .bottom
)
```

**教训**：参考图是最高效的沟通方式。"参考这张截图的配色"比"我要蓝色渐变"精确得多。

---

## UI 层叠结构（供参考）

```
ZStack
  ├── GlassMaterial (NSVisualEffectView，最底层模糊背景)
  ├── LinearGradient (蓝色色带，叠在模糊上方)
  ├── HStack (内容：左栏 Top3 + 右栏正在做)
  └── HStack (操作按钮：pin + 齿轮，bottomTrailing)
```

顶部亮边用 `.overlay(alignment: .top)` 单独加，不影响 clip 范围。

---

## 收敛原则

> [!warning]
> UI 迭代很容易无限循环。设定"够用"的标准，达到后就停下来发布，而不是等到"完美"。

**FocusBar 的收敛标准**：
- 玻璃效果：✅
- 颜色区分三个功能区：✅
- 无多余边框和空隙：✅
- 按钮能用、位置合理：✅

达到这些就算 v1.0，后续再迭代。

---

## 产出物

- 截图对比（before/after）
- Design Token 文件（颜色、字号集中管理）
- 更新后的 README 截图

---

*关联：[[开发一个软件的流程]] · [[Step-05-编写代码与调试]] · [[Step-07-打包发布]]*
