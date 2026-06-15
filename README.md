# 🚦 Hermes Status Light

> **Your AI agent, physically present on your desk.**
>
> 🔴 Red = needs you · 🟡 Yellow = working · 🟢 Green = done

A $3 USB tower light that mirrors your [Hermes Agent](https://github.com/NousResearch/hermes-agent) in real time — approval dialogs, tool calls, task completion, all visible at a glance without looking at the screen.

<br>

## Why this project?

**One command.** Not "edit config, compile, wire GPIO pins." Just `curl | bash`, restart Hermes, done.

**$3 hardware.** A mass-produced industrial alarm light off AliExpress. No 3D printing, no soldering, no Raspberry Pi. USB plug-and-play.

**Physical presence.** Your AI is no longer a black terminal window. It has a light on your desk. You know it's waiting for you from across the room.

<br>

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Alec-9527/agent-status-light/main/setup.sh | bash
```

Restart Hermes. That's it.

<br>

## What the light means

| Hermes is... | Light | 
|-------------|:-----:|
| Asking for command approval | 🔴 flashing |
| Asking a clarifying question | 🔴 flashing |
| Running tools / thinking | 🟡 solid |
| Turn finished | 🟢 flash → solid → off |

<br>

## Different lamp?

Edit `lamp_config.json` with your lamp's serial commands:

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

Re-run `./setup.sh`. Also works with Modbus, HTTP, GPIO — replace `send_frame()` and keep everything else.

<br>

## Hardware

Search "USB 3-color alarm light" (CH341 chip). ~$3 on AliExpress.

<br>

MIT
