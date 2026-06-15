# 🚦 Agent Status Light — 给你的 Hermes Agent 装一盏状态灯

> **AI 在干嘛？看一眼灯就知道。**
>
> 🔴 红闪 = 等你审批 · 🟡 黄亮 = 干活中 · 🟢 绿亮 = 搞定了

[Hermes Agent](https://github.com/NousResearch/hermes-agent) 是 Nous Research 开源的 AI 编程助手。这个项目把它的运行状态投射到桌面的 USB 串口三色塔灯上——审批弹窗、工具调用、任务完成，灯色一目了然。

---

## 三步安装

```bash
git clone https://github.com/Alec-9527/agent-status-light.git
cd agent-status-light
# 1. 编辑 lamp_config.json，把命令换成你灯的协议（不改也能跑，默认是 CH341 塔灯协议）
# 2. 运行安装脚本
./setup.sh
# 3. 重启 Hermes
```

**就这么简单。** `setup.sh` 自动完成：检测串口 → 测试灯 → 启动 daemon → 添加 Hermes hooks → patch 审批/询问源码。

---

## 适配你的灯 —— 只改一个文件

不管什么品牌的 USB 串口灯，核心都是一个**地址+操作码**的组合。编辑 `lamp_config.json`：

```json
{
    "serial_port": "/dev/cu.usbserial-1130",
    "commands": {
        "off":          "A0 00 00 A0",
        "yellow":       "A0 01 01 A2",
        "yellow_flash": "A0 01 02 A3",
        "green":        "A0 02 01 A3",
        "green_flash":  "A0 02 02 A4",
        "red":          "A0 03 01 A4",
        "red_flash":    "A0 03 02 A5"
    },
    "done_flash_seconds": 5,
    "done_steady_seconds": 25
}
```

**命令编码：** 每个命令是一个 hex 字符串，格式取决于你的灯：
- 我的灯：`A0` + 地址 + 操作码 + 校验和
- 地址：`00`=全灭 `01`=黄 `02`=绿 `03`=红
- 操作码：`00`=灭 `01`=常亮 `02`=闪烁

> 💡 Modbus、HTTP、GPIO 等协议？把 `send_frame()` 换成你的逻辑，`lamp_config.json` 里填对应的命令字符串。

---

## 灯色含义

| 场景 | 灯色 | 触发时机 |
|------|:---:|------|
| AI 正在思考 / 调用工具 | 🟡 黄 | `pre_llm_call`、`pre_tool_call` |
| 等待你审批命令 | 🔴 红闪 | 审批弹窗前 |
| 询问你问题（clarify） | 🔴 红闪 | 选择弹窗前 |
| 审批完成 / 回答完毕 | 🟡 黄 | 恢复工作 |
| 任务完成 | 🟢 绿闪 → 常亮 → 灭 | `transform_llm_output` |

---

## 硬件

| 型号 | 芯片 | 价格 | 关键词 |
|------|------|------|--------|
| 虹明机电 USB 串口报警灯 | CH341 | ¥15-30 | "USB 三色报警灯" |

---

## 文件说明

| 文件 | 作用 |
|------|------|
| `hermes_lamp.py` | 核心：daemon + 串口控制 + Hermes hook 适配 |
| `lamp_config.json` | **你只需要改这个**——灯的串口命令和参数 |
| `setup.sh` | 一键安装：检测串口、测试灯、patch Hermes、添加 hooks |
| `patches/` | Hermes 源码 patch 参考（setup.sh 自动处理） |

---

## License

MIT
