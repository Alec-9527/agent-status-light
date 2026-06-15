# 🚦 Hermes Tower Light — AI 物理状态灯

> **你的 Hermes Agent 在做什么？看一眼灯就知道。**
>
> 🔴 红灯闪烁 = 需要你审批 &nbsp;|&nbsp; 🟡 黄灯常亮 = 正在工作 &nbsp;|&nbsp; 🟢 绿灯 = 任务完成

把 Hermes Agent 的运行状态投射到桌面的三色 USB 串口塔灯上，让 AI 的工作进度一目了然。

---

## 开箱即用

```bash
git clone https://github.com/Alec-9527/hermes-tower-light.git
cd hermes-tower-light
# 修改 hermes_lamp.py 里的串口和命令（见下方），然后：
python3 hermes_lamp.py --daemon
```

---

## 适配你的灯

不同厂家的 USB 串口灯协议不同，但原理一样。**只需改两处：**

### 1. 串口路径

```python
# hermes_lamp.py 第 69-79 行，改成你灯对应的设备名
patterns = [
    "/dev/cu.usbserial-*",   # CH341 芯片
    "/dev/cu.wchusbserial*",  # CH340 芯片
    "/dev/cu.SLAB_USBtoUART*", # CP210x 芯片
    "/dev/cu.usbmodem*",       # 通用
]
```

或者直接设置环境变量：
```bash
export HERMES_LAMP_PORT=/dev/cu.usbserial-1130
```

### 2. 灯控命令

我用的灯协议是 `帧头 + 地址 + 操作码 + 校验和`，每个颜色一个地址，操作码 01=常亮、02=闪烁：

```python
COMMANDS = {
    #   地址  操作码      含义
    "off":          bytes.fromhex("A0 00 00 A0"),   # 全灭
    "yellow":       bytes.fromhex("A0 01 01 A2"),   # 🟡 黄灯常亮（工作中）
    "yellow_flash": bytes.fromhex("A0 01 02 A3"),   # 🟡 黄灯闪烁
    "green":        bytes.fromhex("A0 02 01 A3"),   # 🟢 绿灯常亮（完成）
    "green_flash":  bytes.fromhex("A0 02 02 A4"),   # 🟢 绿灯闪烁
    "red":          bytes.fromhex("A0 03 01 A4"),   # 🔴 红灯常亮
    "red_flash":    bytes.fromhex("A0 03 02 A5"),   # 🔴 红灯闪烁（等审批）
}
```

**地址编码：** `00`=全灭 `01`=黄 `02`=绿 `03`=红 `04`=蜂鸣器  
**操作码：** `00`=灭 `01`=常亮 `02`=闪烁  

> 💡 如果你用的是其他协议（Modbus、HTTP、GPIO 等），把 `send_frame()` 函数换成你自己的控制逻辑，外层接口不用动。

---

## 接入 Hermes

### 方式一：Hook 直调（推荐，审批弹窗前亮灯）

在 `~/.hermes/config.yaml` 加入 shell hooks：

```yaml
hooks:
  pre_llm_call:
  - command: /你的路径/hermes_lamp.py
    timeout: 3
  pre_tool_call:
  - command: /你的路径/hermes_lamp.py
    timeout: 3
  pre_approval_request:
  - command: /你的路径/hermes_lamp.py
    timeout: 3
  post_approval_response:
  - command: /你的路径/hermes_lamp.py
    timeout: 3
  transform_llm_output:
  - command: /你的路径/hermes_lamp.py
    timeout: 3
  on_session_start:
  - command: /你的路径/hermes_lamp.py
    timeout: 3
  on_session_end:
  - command: /你的路径/hermes_lamp.py
    timeout: 3
```

### 方式二：日志监控（兜底）

如果 hook 不够可靠，启动后台上报监控进程：

```bash
# 手动启动
python3 hermes_lamp_log_monitor.py &

# 或者设为 macOS LaunchAgent 开机自启
cp com.hermes.lamp-log-monitor.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.hermes.lamp-log-monitor.plist
```

---

## 灯色含义

| 场景 | 灯色 | 触发时机 |
|------|:---:|------|
| AI 正在思考 / 调用工具 | 🟡 黄 | `pre_llm_call`、`pre_tool_call` |
| 等待你审批命令 | 🔴 红灯闪烁 | `pre_approval_request` |
| 审批完成，继续干活 | 🟡 黄 | `post_approval_response` |
| 任务完成 | 🟢 绿闪 5s → 常亮 15s → 灭 | `transform_llm_output` |
| 会话结束 | 🟢 同上 | `on_session_end` |

闪烁和常亮的时长可在 `hermes_lamp.py` 顶部修改：
```python
DONE_FLASH_SECONDS = 5.0   # 完成闪烁秒数
DONE_STEADY_SECONDS = 25.0  # 完成常亮秒数
```

---

## 硬件

| 型号 | 芯片 | 接口 | 购买关键词 |
|------|------|------|-----------|
| 虹明机电 USB 串口报警灯 | CH341 | USB-A | "USB 串口报警灯 三色" |
| 通用 CH340 三色灯 | CH340 | USB-A | "CH340 USB 三色指示灯" |

淘宝/1688 搜 "USB 三色报警灯" 约 ¥15-30。

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `hermes_lamp.py` | 核心：daemon + 串口控制 + Hermes hook 适配 |
| `hermes_lamp_log_monitor.py` | 兜底：监控 agent.log 驱动灯 |
| `com.hermes.lamp-log-monitor.plist` | macOS LaunchAgent 配置 |

---

## License

MIT — 随便改，随便用。
