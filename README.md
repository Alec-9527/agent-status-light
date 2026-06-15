# 🚦 Agent Status Light

> **Hermes Agent 在干嘛？看一眼桌面的灯就知道。**
>
> 🔴 红灯 = 等你审批 · 🟡 黄灯 = 干活中 · 🟢 绿灯 = 任务完成

<br>

## 安装

```bash
curl -fsSL https://raw.githubusercontent.com/Alec-9527/agent-status-light/main/setup.sh | bash
```

重启 Hermes。**搞定。**

> 前提：你有一盏 USB 三色报警灯（CH341 芯片，淘宝 ¥15-30），并且已经装了 [Hermes Agent](https://github.com/NousResearch/hermes-agent)。

<br>

## 效果

| 你看到 | 灯亮了 | 含义 |
|--------|:-----:|------|
| Hermes 弹出审批框 | 🔴 红闪 | 等你确认 |
| Hermes 问你要选项 | 🔴 红闪 | 等你选择 |
| Hermes 在跑命令 | 🟡 黄亮 | 工作中 |
| 任务完成 | 🟢 绿闪 → 常亮 → 灭 | 搞定了 |

<br>

## 灯的品牌不一样？

编辑 `lamp_config.json`，把命令换成你灯的协议：

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
    }
}
```

每个命令的格式取决于你的灯协议。然后重新运行 `./setup.sh`。

> Modbus、HTTP、GPIO 等协议：把 `hermes_lamp.py` 中的 `send_frame()` 函数换成你的控制逻辑。

<br>

## 手动安装

```bash
git clone https://github.com/Alec-9527/agent-status-light.git
cd agent-status-light
./setup.sh
```

`setup.sh` 做了什么：检测串口 → 测试灯 → 启动 daemon → 配置 Hermes hooks → patch 审批源码。

<br>

## 硬件

关键词：**"USB 三色报警灯"**，芯片 CH341，淘宝/1688 ¥15-30。

<br>

MIT
