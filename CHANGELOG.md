# Changelog

## v3.0.4 — 修复启动报错

### 修复

- `NameError: name 'ap_info' is not defined`（`coordinator/device_registry.py`）
- 原因：v3.0.3 删除 radio / SSID 注册块时，连带移除了 `ap_info` 与 `radio_info` 的定义，但后续 `active_identifiers` 计算与孤儿设备清理仍引用这两个变量
- 处理：在精简模式下将两者定义为空字典，保持下游逻辑不变且不再生成任何 AP / radio 标识

### 校验

- `compileall` 通过
- 逐个比对被删块内定义的 16 个局部变量，确认全部已重新定义、为循环变量或仅存在于注释

## v3.0.3 — 旁路由精简：只保留路由器主设备

### 移除的设备条目

- 2 × Wireless Radio（2.4 GHz / 5 GHz）
- 2 × Wireless SSID（SSID FanchmWrt 2.4 GHz / 5 GHz）
- 6 × 客户端 MAC 设备（78:df:72:9f:25:bd 等）

### 移除的实体

- 上述 10 个辅助设备下的全部实体（每个客户端 6 个、每个 radio 1 个、每个 SSID 6 个）
- 引用非路由器设备的带宽 / 设备诊断 / 无线 / WPS 等实体，注册前统一过滤

### 实现

- 新增 `helpers/compact.py`：按 device identifier 过滤实体，并在 setup 时清理注册表里的历史辅助设备
- `sensor.py` / `switch.py` / `button.py` / `binary_sensor.py`：注册前调用过滤
- `coordinator/device_registry.py`：不再注册 Wireless Radio / Wireless SSID 设备
- `__init__.py`：set up 时删除除路由器主设备外的所有设备（连带其实体）

### 保留

- `JCG Q30 PRO` 一个设备条目，及其系统、网络、存储、服务类实体

## v3.0.2 — 修正 HACS 安装路径

### 修复

- 移除 `hacs.json` 中的 `zip_release` / `filename`
- 原因：HACS 会把 zip 整包解压到 `config/custom_components/<domain>/`，而包内已含 `custom_components/<domain>/` 前缀，导致安装后出现 `custom_components/fanchmwrt/custom_components/fanchmwrt/` 的双层嵌套，HA 无法识别该集成
- 改为标准源码安装路径后，HACS 会正确复制 `custom_components/fanchmwrt`

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
