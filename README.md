# 🚦 Agent Status Light — 给你的 Hermes Agent 装一盏状态灯

> **AI 在干嘛？看一眼灯就知道。**
>
> 🔴 红闪 = 等你审批 · 🟡 黄亮 = 干活中 · 🟢 绿亮 = 搞定了

[Hermes Agent](https://github.com/NousResearch/hermes-agent) 是 Nous Research 开源的 AI 编程助手。这个项目把它的运行状态投射到桌面的 USB 串口三色塔灯上——审批弹窗、工具调用、任务完成，灯色一目了然。

---

## 插上就用

```bash
git clone https://github.com/Alec-9527/agent-status-light.git
cd agent-status-light
# 只改一处：把你灯的串口命令填进去（见下方）
python3 hermes_lamp.py --daemon
```

---

## 适配你的灯 —— 只需要改命令

不管什么品牌的 USB 串口灯，核心都是一个**地址+操作码**的组合。我的灯协议如下，你换成自己灯的即可：

```python
COMMANDS = {
    #  地址 操作码 → 含义
    "off":          b"\xA0\x00\x00\xA0",   # 00 00 = 全灭
    "yellow":       b"\xA0\x01\x01\xA2",   # 01 01 = 黄灯常亮
    "yellow_flash": b"\xA0\x01\x02\xA3",   # 01 02 = 黄灯闪烁
    "green":        b"\xA0\x02\x01\xA3",   # 02 01 = 绿灯常亮
    "green_flash":  b"\xA0\x02\x02\xA4",   # 02 02 = 绿灯闪烁
    "red":          b"\xA0\x03\x01\xA4",   # 03 01 = 红灯常亮
    "red_flash":    b"\xA0\x03\x02\xA5",   # 03 02 = 红灯闪烁
}
```

> **地址编码：** `00`=全灭 `01`=黄 `02`=绿 `03`=红  
> **操作码：** `00`=灭 `01`=常亮 `02`=闪烁  
> 
> 💡 如果你用的是 Modbus、HTTP、GPIO 等协议，把 `send_frame()` 换成你的控制逻辑就行，外壳不动。

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
