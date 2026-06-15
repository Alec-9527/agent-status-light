# 🚦 Agent Status Light

> **Know what your Hermes Agent is doing — at a glance.**
>
> 🔴 Red = waiting on you · 🟡 Yellow = working · 🟢 Green = done

<br>

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/Alec-9527/agent-status-light/main/setup.sh | bash
```

Restart Hermes. That's it.

> Requirements: a USB 3-color tower light (CH341 chip, ~$3 on AliExpress) and [Hermes Agent](https://github.com/NousResearch/hermes-agent) installed.

<br>

## What the light tells you

| Hermes is... | Light | Meaning |
|-------------|:-----:|--------|
| Asking for command approval | 🔴 flashing | Waiting for you |
| Asking a clarifying question | 🔴 flashing | Waiting for you |
| Running tools / thinking | 🟡 solid | Working |
| Turn finished | 🟢 flash → solid → off | Done |

<br>

## Different lamp?

Edit `lamp_config.json` with your lamp's protocol:

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

Each command is whatever hex string your lamp expects. Re-run `./setup.sh`.

> Modbus, HTTP, GPIO? Replace `send_frame()` in `hermes_lamp.py` — the rest stays the same.

<br>

## Manual install

```bash
git clone https://github.com/Alec-9527/agent-status-light.git
cd agent-status-light
./setup.sh
```

`setup.sh` handles: detect serial port → test the light → start daemon → configure Hermes hooks → patch approval/clarify source.

<br>

## Hardware

Search: **"USB 3-color alarm light"**, CH341 chip. ~$3 on AliExpress / 1688.

<br>

MIT
