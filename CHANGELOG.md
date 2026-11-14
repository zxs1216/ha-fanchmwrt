# Changelog

## v3.0.1 — 补齐 HACS 合规资源

### 新增

- 添加 `custom_components/fanchmwrt/brand/icon.png`（256×256）

### 修复

- HACS 发布规范要求集成必须提供品牌图标资源，缺失会导致仓库被判为不合规、无法在 HACS 内安装

## v3.0.0 — 品牌重构与平台裁剪

> 定位：从「上游精简分支」转为自主维护的 FanchmWrt 集成。

### 变更

- 集成 domain：`openwrt` → `fanchmwrt`
- 集成名称：`OpenWrt` → `FanchmWrt`
- 版本号：`2.5.5` → `3.0.0`
- 代码目录：`custom_components/openwrt/` → `custom_components/fanchmwrt/`
- 运行时模块引用（`sys.modules["custom_components.openwrt.*"]`）同步改名
- `manifest.json`：codeowners→`@zxs1216`，documentation/issue_tracker/loggers 指向新仓库
- `hacs.json`：发布包名 `openwrt.zip` → `fanchmwrt.zip`

### 移除

- 平台：`device_tracker`、`light`、`number`、`update`、`event`、`image`（以及 `device_trackers/` 目录）
- 仓库内上游站点文档 `docs/`、`mkdocs.yml`、`personal/`，减少噪声

### 保留

- 平台：`binary_sensor`、`button`、`sensor`、`switch`
- 系统监控、网络接口、服务监控、防火墙诊断等既有能力

### 中文

- 合并上一版 `ha-openwrt-minimal` 的 `zh-Hans.json`，保留与上游键路径匹配的 95 条
- 覆盖率 95/507（约 19%），未覆盖键回退英文

### 升级注意

- **domain 变更**：旧 `openwrt` 条目需先删除，再添加 `fanchmwrt`
- 路由器侧需具备 `uhttpd-mod-ubus` / `rpcd-mod-file`，并建议新建只读账号

### 已知限制

- OpenClash 独立设备与节点控制尚未实现，排期 v3.1
- VPN / SQM / Batman / GPS / ModemManager 内部模块未删除，仅不再暴露平台入口
