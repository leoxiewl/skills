---
完整创建时间: 2026-06-20T15:30:00
编辑分类: human+llm
tags:
  - my-skills
  - 软件开发
  - SOP
  - indie-dev
  - distribution
---

# Step 07 — 打包发布 DMG（macOS）

> [!abstract]
> macOS App 发布有两条路：未签名（免费，用户需手动绕过 Gatekeeper）或签名+公证（$99/年，双击直接安装）。开源早期版本走未签名即可，发布到 GitHub Releases。

---

## 两条路的对比

| | 未签名 | 签名 + 公证 |
|---|---|---|
| 费用 | 免费 | Apple Developer $99/年 |
| 用户体验 | 首次需右键→打开 或 终端命令 | 双击直接安装，无警告 |
| 沙箱限制 | 无限制 | 部分 API 受限（如全局鼠标监听） |
| 适用场景 | 开源/早期版本 | 正式发布/App Store |

> [!note]
> 需要 `NSEvent.addGlobalMonitorForEvents` 等 API 的 App 无法上 App Store，因为必须关闭沙箱。未签名 DMG 是唯一选择（除非走 Developer ID 公证）。

---

## 完整流程（未签名版本）

### 前置条件

```bash
brew install xcodegen     # 项目文件生成
brew install create-dmg   # DMG 制作工具
brew install gh           # GitHub CLI（发布用）
gh auth login             # 登录 GitHub
```

### Step 1 — 生成 Xcode 项目

```bash
xcodegen generate
```

### Step 2 — 打包 Release Archive

```bash
xcodebuild archive \
  -project FocusBar.xcodeproj \
  -scheme FocusBar \
  -configuration Release \
  -archivePath /tmp/FocusBar.xcarchive \
  CODE_SIGN_IDENTITY="" \
  CODE_SIGNING_REQUIRED=NO \
  CODE_SIGNING_ALLOWED=NO
```

### Step 3 — 从 Archive 提取 .app

```bash
cp -R /tmp/FocusBar.xcarchive/Products/Applications/FocusBar.app /tmp/FocusBar.app
```

### Step 4 — 制作 DMG

```bash
mkdir -p /tmp/dmg_staging
cp -R /tmp/FocusBar.app /tmp/dmg_staging/

create-dmg \
  --volname "FocusBar" \
  --window-pos 200 120 \
  --window-size 560 320 \
  --icon-size 100 \
  --icon "FocusBar.app" 140 160 \
  --hide-extension "FocusBar.app" \
  --app-drop-link 420 160 \
  --no-internet-enable \
  "/tmp/FocusBar-v1.0.0.dmg" \
  "/tmp/dmg_staging/"
```

**DMG 命名规范**：`AppName-vX.Y.Z.dmg`，版本号必须带。

### Step 5 — 发布到 GitHub Releases

```bash
gh release create v1.0.0 /tmp/FocusBar-v1.0.0.dmg \
  --repo username/FocusBar \
  --title "FocusBar v1.0.0" \
  --notes "Release notes..."
```

---

## 如果要更新 DMG 资产

```bash
# 删除旧文件
gh release delete-asset v1.0.0 "FocusBar.dmg" --repo username/FocusBar --yes

# 上传新文件
gh release upload v1.0.0 /tmp/FocusBar-v1.0.0.dmg --repo username/FocusBar
```

---

## README 中必须写清楚的内容

因为 App 未签名，README 里**必须**说明首次打开方式，否则用户会以为软件坏了：

```markdown
> **首次启动：** macOS 会拦截未签名的 App。
> 请右键点击 FocusBar.app → 打开，或在终端执行：
> ```bash
> xattr -dr com.apple.quarantine /Applications/FocusBar.app
> ```
```

---

## 版本号规范

遵循语义化版本 `vMAJOR.MINOR.PATCH`：

| 类型 | 示例 | 触发条件 |
|---|---|---|
| PATCH | v1.0.1 | Bug 修复 |
| MINOR | v1.1.0 | 新功能，向下兼容 |
| MAJOR | v2.0.0 | 破坏性变更 |

Git tag 与 GitHub Release 版本号保持一致。

---

## 后续：签名 + 公证（正式版）

当需要更好用户体验时，升级为签名版：

1. 申请 Apple Developer 账号
2. 创建 Developer ID Application 证书
3. 签名：`codesign --deep --force --sign "Developer ID Application: ..." FocusBar.app`
4. 公证：`xcrun notarytool submit FocusBar.dmg --apple-id ... --team-id ... --password ...`
5. 钉上公证印章：`xcrun stapler staple FocusBar.dmg`

---

## 产出物

- `AppName-vX.Y.Z.dmg`（带版本号）
- GitHub Release（含 Release Notes）
- 更新后的 README（含首次打开说明）

---

*关联：[[开发一个软件的流程]] · [[Step-06-UI打磨与迭代]]*
