# Changelog

## v4.1.1 — 修复订阅流量 unknown 与「访问」链接未生效

- **订阅流量 unknown**：增加经路由器 SSH 执行 curl 的兜底路径（与 OpenClash LuCI 页面同源），
  覆盖 HA 主机直连订阅地址受限的情况；启动初期在 1/3/6/10 次轮询重试，之后约 10 分钟刷新；
  失败原因改为 WARNING 日志便于定位。
- **「访问」链接未更新**：`async_get_or_create()` 不会覆盖已存在设备的 `configuration_url`，
  改为 `async_update_device()` 显式更新，确保从 metacubexd 代理面板切到 OpenClash 运行状态页。
- 部署说明：本次 Marketplace 受 GitHub 匿名 API 限流，改用等效的手动整包部署；
  限流解除后在 Marketplace 点一次更新即可对齐版本记录。

## v4.1.0 — 实时流量、订阅剩余流量与「访问」重定向

**按使用反馈调整**

1. **移除侧边栏仪表盘**：删除 HA 中的「FanchmWrt 控制」视图及仓库内
   `dashboards/fanchmwrt.yaml`。代价：计划书中的「控制块二次确认弹窗」暂无载体——
   HA 设备页原生按钮不支持实体级确认，如需该能力需另做紧凑卡片。
2. **路由器条目增加实时流量**：新增「实时下载 / 实时上传」（kB/s），
   从已启用的非虚拟接口中取最大 `rx_rate` / `tx_rate`，避免 br-lan 与物理口重复累加。
3. **OpenClash 条目增加订阅剩余流量**：新增「剩余流量 / 套餐总流量 / 已用流量 / 流量使用率」。
   数据来源为订阅响应头 `subscription-userinfo`（本项目实测 total=1000 GB、剩余 790.2 GB，
   与 OpenClash 状态页一致）。集成经 ubus `file.read` 读取 `/etc/config/openclash`
   定位当前订阅地址，约 10 分钟刷新一次，只取响应头并立即关闭连接，不下载订阅内容。
4. **「访问」不再跳代理面板**：OpenClash 设备的 `configuration_url` 由
   `:9090/ui/metacubexd/` 改为 `http://<host>/cgi-bin/luci/admin/services/openclash`
   （即包含运行状态、订阅流量、运行数据、IP 检查的那张页面）。
   主要数据同时已实体化到设备页，无需打开外部页面即可查看。

**限制说明**：HA 设备页的「访问」本质只能打开一个链接，无法把第三方网页画面内嵌进设备页；
LuCI 另有登录态与 iframe 限制。因此采用「链接指向状态页 + 主要数据实体化」的组合。

## v4.0.3 — 补齐计划书中的「存储」传感器

v4.0.2 已把实体精简到 34 个且 0 禁用，但清理掉默认禁用的细分存储实体后，
路由器传感器块缺少计划书明确列出的「存储」。本版新增 2 个精简汇总传感器
（基于主 coordinator，优先 `/overlay`、回退 `/`）：

- `存储使用率`（%）
- `可用存储空间`（MB）

不再恢复 22 个按挂载点拆分的细分存储实体，保持设备页精简。最终 36 个实体、0 禁用。

## v4.0.2 — 让历史禁用实体的清理真正落地

v4.0.1 的 `filter_v4_entities()` 已生效（服务类实体不再创建，状态机中已消失），
但注册表里 216 条僵尸项仍在设备页显示为「已禁用实体」。原因：清理函数直接遍历
`entity_registry.entities.values()`，在 HA 2026 中该直接迭代行为不稳定；
而保留类实体（存储 / 速率 / 日志）重新注册时又复用了旧的
`disabled_by=integration` 状态，无法自动解禁。

**修复**

- `purge_legacy_entities()` 改用官方 `er.async_entries_for_config_entry()` 遍历，
  并且对「禁用项」与「服务控制类僵尸项」一律 `async_remove`，让保留实体以启用状态重建。
- 平台注册后的兜底清理改为延迟 4 秒的后台任务，覆盖异步注册完成的实体。

## v4.0.1 — 彻底消除「+N 个已禁用实体」

**真因定位**：v4.0.0 上线后实测，设备页的禁用实体并非只来自旧条目，
而是集成自己每次启动都会成批注册 **216 个 `entity_registry_enabled_default=False`**
的实体（72 个服务状态、72 个服务启停按钮、36 个服务开关，以及默认禁用的
存储 / 接口速率 / 系统日志 / 进程排行等传感器）。

**修复**

- 新增 `filter_v4_entities()`，四个平台统一在注册前过滤：
  - 丢弃服务状态 / `restart_*` / `stop_*` / `start_*` / `service_*` 控制实体（计划书三大块不需要）；
  - 把存储、接口速率、连接跟踪、系统日志、进程排行、内存明细、负载等
    **强制改为默认启用**，保留在传感器块中，不再折叠成「已禁用实体」。
- 平台注册**之后**再跑一次 `purge_legacy_entities()`，兜底删除历史遗留的禁用实体；
  启动前那次仍保留。
- 设备遍历改用 `dr.async_entries_for_config_entry()`，消除 HA 的
  `device_registry.devices` 弃用告警。
- 修正 `strings.json` / `en.json` / `zh-Hans.json` 中 10 处遗留多步流程文案的占位符，
  消除启动时 `homeassistant.helpers.translation` 的 ERROR 日志。

**效果**：设备页不再出现「+N 个已禁用实体」，计划书要求的三大块实体全部正常显示。

## v4.0.0 — 按计划书大版本更新：两个主条目 + 彻底清理禁用实体

**版本定位**：从「单设备精简版」升级为计划书定义的双主条目结构，完全剥离上游更新链。

### 新增：两个主条目

| 主条目 | 分区 | 内容 | 左侧「访问」 |
|---|---|---|---|
| 路由器（FanchmWrt） | 控制 | 重启路由器 | LuCI 状态概览 `/cgi-bin/luci/admin/status/overview` |
| | 传感器 | 系统 / 内存 / 存储 / **运行时间（d.h.m）** / 流量 / 在线客户端 | |
| | 诊断 | 外网连通、网关延迟、DNS 解析耗时、原有系统诊断项 | |
| OpenClash | 代理 | 5 个分流组节点选择（🚀 节点选择 / 🎯 Gemini / TikTok / Discord / X）、刷新 DNS 缓存 | metacubexd 代理面板 `:9090/ui/metacubexd/` |
| | 运行状态 | 当前节点、OpenClash 运行、DNS 解析健康、活动连接数、规则数、内核版本、代理模式 | |
| | 流量 | 实时上/下行、累计上/下行、**代理累计流量**、DNS 解析延迟 | |

- 数据源：新增 `openclash/api.py`（mihomo RESTful，`/proxies`、`/traffic` SSE 首行、`/connections`、`/rules`、`/configs`、`/version`、节点切换、Fake-IP 缓存刷新）与 `openclash/coordinator.py`（15 秒轮询，失败仅降级不阻断集成加载）。
- DNS 解析健康 / 外网连通 / 网关延迟由标准库 UDP/TCP 探测实现，无新增 pip 依赖。
- 「主要设置」新增 OpenClash API 密钥与端口（中文），密钥写入 HA 配置后可自动生成带密钥的面板直达链接。

### 修复：历史禁用实体

- 新增 `purge_legacy_entities()`：启动时删除旧 `openwrt` 集成残留的全部实体（含 `config_entry` / `user` 禁用项）、本条目下任何被禁用的实体，以及旧 `openwrt` 域设备。设备页不再出现「+N 个已禁用实体」。
- 本次上线前已直接清理 HA 上残留的旧 `openwrt` 条目及其 33 个禁用实体。

### 变更

- 运行时间由 TIMESTAMP 改为 `Xd Yh Zm` 字符串，归入传感器块。
- `PLATFORMS` 增加 `select`；`router_identifier_set()` 同时放行 OpenClash 设备，避免被辅助设备清理逻辑误删。
- 版本 `3.1.1` → `4.0.0`。

### 已知限制

- HA 设备页的按钮/开关**不会**弹出二次确认（核心不支持实体级确认）。控制项的确认弹窗在随包 `dashboards/fanchmwrt.yaml` 中实现，导入后从仪表盘操作即可。

## v3.1.1 — 修复「添加集成」500 错误

**现象**：v3.1.0 点开 FanchmWrt 添加集成时，前端提示
「无法加载配置向导：500 Internal Server Error Server got itself in trouble」。

**根因**：v3.1.0 把登录改为单步表单时，`flows/discovery.py` 漏导入 7 个常量：
`CONF_USERNAME`、`CONF_PASSWORD`、`CONF_USE_SSL`、`CONF_VERIFY_SSL`、
`CONF_PORT`、`CONF_UBUS_PATH`、`DEFAULT_UBUS_PATH`。
`async_step_user()` / `_quick_setup_schema()` 一执行就抛
`NameError: name 'CONF_USERNAME' is not defined`，配置流初始化失败 → HTTP 500。

**修复**

- 补齐上述 7 个常量导入；全包 pyflakes（F821）扫描与 `compileall` 均通过，无其它未定义名。
- `_test_connection()` 预先初始化 `client = None` 并保护 `finally` 中的 `disconnect()`，
  避免创建客户端即失败时抛 `UnboundLocalError`，导致提交表单时再次 500。

**范围**：仅修复配置向导，未新增或恢复任何实体、设备、选项。

## v3.1.0 — 旁路由深度精简、单步登录与完整中文

### 实体精简（旁路由场景）

**移除的实体类别**

- 按钮：Start/Cancel WPS、Create Backup、WoL、Kick、AdBlock/Ban-IP 等
- 开关：WPS、无线 Radio、防火墙、访问控制、SQM、VPN、LED、AdBlock/Simple AdBlock/Ban-IP
- 二元传感器：WPS 状态、Batman Mesh、MWAN 在线、VPN/WireGuard/Tailscale 状态
- 传感器：公网 IP、无线客户端数、邻居设备、Swap、DHCP 租约数、
  WireGuard/Tailscale/OpenVPN 流量、MWAN 指标、QModem、Batman Mesh、
  LLDP 邻居、NLBWmon、SNORT、MQTT 在线检测状态

**保留**：CPU / 内存 / 负载 / 温度 / 运行时间 / 存储（含 overlay）/ 连接跟踪数 /
已连接客户端数 / 系统日志 / 进程排行 / 接口速率与地址 / 接口连接状态 / 服务开关 / 重启按钮

**历史实体清理**：新增 `purge_removed_entities()`，启动时按 unique_id 片段
自动删除注册表中遗留的已移除类别实体（约 29 类模式）。

### 登录精简

- 原多步流程（连接方式选择 → 主机 → 凭据 → 权限确认 → 软件包 → 追踪选择…）
  合并为**单步表单**：主机地址 / 用户名 / 密码
- 连接方式固定 ubus，端口与路径取默认值；验证通过后直接创建条目
- 默认选项预设为旁路由场景（设备跟踪关、服务监控开、VPN/SQM/LED/防火墙关）

### 选项精简

- 配置选项收敛为 6 项主要设置：轮询间隔、DHCP 软件、服务开关、
  防火墙开关、VPN 传感器、负载传感器
- 移除固件更新 / 备份 / GPS / MQTT / 追踪等十余项与旁路由无关的选项

### 品牌

- 全部 UI 字符串中的 "OpenWrt" 替换为 "FanchmWrt"（配置向导、选项页、错误提示、Issues 文案）
- 新图标：蓝底白色路由器造型（机身 + 双天线 + 指示灯 + 网口），256×256

### 中文

- `zh-Hans.json` 覆盖 strings.json 全部 **493/493** 键（100%），
  包括配置向导、选项、实体名称、错误提示、Issues、服务字段

### 已知限制

- OpenClash 独立设备与节点控制仍在计划中（v3.2）
- VPN / SQM / Batman 等内部模块代码保留（未创建实体），待后续版本清理

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
