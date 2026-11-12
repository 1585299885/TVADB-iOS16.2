# TVADB — iOS 16.2 兼容版

基于上游 [wy164519317/tvadb](https://github.com/wy164519317/tvadb)（MIT）改造，**从源码层面**移除 iOS 17 依赖，使编译产物可以在 iOS 16.2 + TrollStore 上真正启动，而不是靠改二进制头绕过。

## 为什么原版在 iOS 16.2 上闪退

上游用 Xcode 26 / iOS 26 SDK 编译，`IPHONEOS_DEPLOYMENT_TARGET = 17.0`。源码里用了 4 类 iOS 17 才有的 SwiftUI API：

| API | 处数 | iOS 16.2 的状况 |
| --- | --- | --- |
| `ContentUnavailableView` | 7 | 类型不存在 |
| `.sensoryFeedback` | 5 | 不存在 |
| `.contentMargins` | 1 | 不存在 |
| `.safeAreaPadding` | 4 | 不存在 |
| `.onChange(of:) { old, new in }` | 8 | iOS 16 只有单参数 `(newValue)` 签名 |
| `.topBarTrailing` / `.topBarLeading` | 8 | iOS 16 对应 `.navigationBarTrailing` / `.navigationBarLeading` |

这些会生成 **15 个强绑定到 `SwiftUI.framework` 的 iOS 17 符号**（见 `LC_DYLD_CHAINED_FIXUPS`）。iOS 16.2 的 SwiftUI 里没有它们，`dyld` 启动时解析符号直接抛 `Symbol not found` 并杀掉进程 —— 这就是"安装成功却秒退"的根因。只改 `MinimumOSVersion` / `minos`、或把符号改成弱绑定，都解决不了：启动路径 `RootView` 就会访问空元数据。

## 本版本做了什么

| 改动 | 说明 |
| --- | --- |
| `IPHONEOS_DEPLOYMENT_TARGET` | `17.0` → **`16.2`**（Debug / Release 两处） |
| `TVADBContentUnavailableView` | 追加在 `iosadb/UI/DesignSystem.swift`，纯 iOS 15/16 API 实现的空状态视图，替换全部 `ContentUnavailableView`（含 `.search(text:)`） |
| `.sensoryFeedback` | 删除 5 处触感反馈 modifier（iOS 16 无等价实现，去掉不影响功能） |
| `.contentMargins` / `.safeAreaPadding` | 分别删除 / 换成 `.padding`，保持布局可用 |
| `.onChange` | 双参数闭包改为 iOS 16 的单参数签名；`RemoteControlView` 中需要旧值的一处改用 `@State` 保存上一次值 |
| toolbar placement | `.topBarTrailing/Leading` → `.navigationBarTrailing/Leading` |
| `scripts/patch-ios16.py` | 编译后把 Mach-O 的 `LC_BUILD_VERSION.minos` **和 `sdk`** 都固定为 `16.2.0`，并把 `Info.plist` 的 `MinimumOSVersion` 设为 `16.2`（`sdk` 不降，dyld 仍可能按新 SDK 启用旧系统没有的行为） |
| `scripts/check-symbols.py` | 编译后扫描 dyld import 表，**若残留任何强绑定的 iOS 17 符号就让构建失败**，避免产出装上去仍闪退的包 |

`LC_BUILD_VERSION.sdk` 的降级是必要的：即使部署目标设成 16.2，用新 SDK 编译出的二进制仍记录 SDK 26.x，旧系统上的 dyld 会按它判断运行时行为。

## 怎么拿到 IPA

### 方式 A：GitHub Actions（不需要 Mac，不需要开发者账号）

1. 在 GitHub 新建仓库，把本目录**所有文件**（包括隐藏的 `.github/`）push 上去，公开仓库的 Actions 免费。
2. push 即自动触发 `Build TVADB IPA for iOS 16.2`；也可在 **Actions** 页手动 `Run workflow`。
3. 跑完在该次运行的 **Artifacts** 下载 `TVADB-iOS16.2-unsigned`，解压得到 `TVADB-iOS16.2-unsigned.ipa`。
4. IPA 传到 iPhone → 分享 / 打开方式选 **TrollStore** → Install。

> 步骤 `Verify no iOS 17 SwiftUI symbols remain` 会通过才上传成品；若失败，把日志发回来即可继续修。

### 方式 B：有 Mac

```bash
cd TVADB-iOS16.2
bash scripts/build-ios16-ipa.sh
```

产物在 `dist/TVADB-iOS16.2-unsigned.ipa`。

## 安装注意

- 先在 TrollStore 的 **Apps** 里删除旧版 TVADB 再安装，避免旧二进制 / 图标缓存残留。
- IPA 是**未签名**的（上游脚本 `CODE_SIGNING_ALLOWED=NO`），TrollStore 会自行签发；不要用 AltStore / 描述文件方式装。
- 首次连接会请求「本地网络」权限，请允许，否则扫描不到车机 / 电视。
- ADB 无线调试：传统 `adb tcpip 5555` 直连可用；Android 11+ 的无线配对（SPAKE2/TLS）上游已实现，行为与官方版一致。

## 文件说明

```
iosadb/                     已改造的 Swift 源码（29 个文件）
iosadb.xcodeproj/           Xcode 工程，部署目标 16.2
Vendor/adb-prebuilt/        arm64 真机 ADB 静态库（38 MB，构建脚本自动解压）
scripts/build-unsigned-ipa.sh    上游原版构建脚本
scripts/patch-ios16.py           部署目标强制降级
scripts/check-symbols.py         iOS 17 符号残留检查
scripts/build-ios16-ipa.sh       本机一键构建
.github/workflows/build-ipa.yml  macOS 云端一键构建
```

上游的模拟器静态库（39 MB）和 README 截图已从本包中移除以减小体积，不影响真机编译。
