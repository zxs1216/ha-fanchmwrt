# FanchmWrt

自用的 Home Assistant OpenWrt 集成，聚焦软路由（旁路由）监控。由 [FaserF/ha-openwrt](https://github.com/FaserF/ha-openwrt) 裁剪重构而来，按 MIT 协议保留原始版权。

- **当前版本**：4.1.0
- **domain**：`fanchmwrt`
- **最低 HA 版本**：2025.2.0

---

## 与上游的关系

本项目基于上游 `v2.5.5`（MIT）。裁掉与本机场景无关的模块，重整品牌与目录，后续独立演进，不再跟随上游。

原始版权归 FaserF 所有，修改部分版权归 zxs1216，详见 `LICENSE`。

## v3.0.0 做了什么

**变更**

- 集成域名 `openwrt` → `fanchmwrt`，名称改为 FanchmWrt，版本 `2.5.5` → `3.0.0`
- 所有 `sys.modules` 运行时引用同步改名，避免模块补丁失效
- 仓库地址、issue 跟踪、日志器名称指向本仓库
- `hacs.json` 的发布包名改为 `fanchmwrt.zip`

**移除的平台**

| 平台 | 原因 |
|---|---|
| `device_tracker` | 不做「谁在家」追踪，保留在线设备数统计即可 |
| `light` | 路由器 LED 控制与本机无关 |
| `number` | WiFi 功率等数值滑块不需要 |
| `update` / `image` | 固件更新与在线刷机不在监控范围 |
| `event` | 依附于设备跟踪的新设备事件 |

保留 `binary_sensor`、`button`、`sensor`、`switch` 四个平台。

**中文**

继承并合并了上一版 `ha-openwrt-minimal` 的简体中文翻译，目前覆盖 `strings.json` 中 95/507 个键（约 19%），未覆盖部分由 HA 自动回退英文。完整翻译排在 v3.1。

## v4.0.0 两个主条目

| 主条目 | 控制 | 传感器 | 诊断 | 「访问」 |
|---|---|---|---|---|
| 路由器 | 重启 | 系统 / 内存 / 存储 / 运行时间（d.h.m）/ **实时下载·上传** / 在线客户端 | 外网连通、网关延迟、DNS 解析耗时 | LuCI 状态概览 |
| OpenClash | 5 个分流组节点选择、刷新 DNS 缓存 | 当前节点、实时与累计流量、代理累计流量、**剩余流量 / 总流量 / 已用流量 / 使用率**、活动连接数 | 运行状态、DNS 解析健康、规则数、内核版本、代理模式 | OpenClash 运行状态页 |

- OpenClash 数据来自路由器 mihomo API（默认 `9090`），在「主要设置」里填 API 密钥与端口。
- 订阅剩余流量来自订阅响应头 `subscription-userinfo`，由集成经 ubus `file.read` 读取
  `/etc/config/openclash` 中的订阅地址后低频（约 10 分钟）获取，不下载订阅内容。
- 启动时自动清除旧 `openwrt` 集成与历史精简留下的**全部禁用实体**，设备页不再出现「+N 个已禁用实体」。
- 侧边栏控制仪表盘已按使用反馈移除；HA 设备页原生按钮不支持实体级二次确认弹窗。

## 尚未包含

- **深度模块清理**：VPN / SQM / Batman / GPS / ModemManager 等内部代码仍保留但界面不暴露，避免在无可运行 HA 环境下删出 ImportError

## 安装

### 方式一：HACS / Marketplace

1. 打开 HACS（或新版 Marketplace）→ 自定义仓库
2. 添加 `https://github.com/zxs1216/ha-fanchmwrt`，类型选 `Integration`
3. 搜索 `FanchmWrt` 安装并重启 Home Assistant

### 方式二：手动

下载 Release 的源码包，把其中的 `custom_components/fanchmwrt` 整个目录放入 HA 配置目录，重启。

## 路由器侧准备

需要 ubus 访问能力：

```sh
# 确认依赖（OpenWrt 25.12 通常已自带）
apk list --installed | grep -E 'uhttpd-mod-ubus|rpcd-mod-file|rpcd-mod-iwinfo|jsonfilter'
```

建议为 HA 建一个只读专用账号，而不是直接用 root：

```sh
uci add rpcd login
uci set rpcd.@login[-1].username='homeassistant'
uci set rpcd.@login[-1].password="$(uhttpd -m '你的密码')"
uci add_list rpcd.@login[-1].read='*'
uci commit rpcd
/etc/init.d/rpcd restart
```

## 升级注意

**domain 已从 `openwrt` 改为 `fanchmwrt`**，旧的集成条目不会被自动接管。升级步骤：

1. 在 HA 中删除旧的 `openwrt` 条目
2. 安装本集成
3. 重新添加集成并填写路由器地址与凭据

## 许可

MIT。见 `LICENSE`。
