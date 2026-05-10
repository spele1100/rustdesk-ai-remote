# Competitive Research: AI Computer-Use / Remote Desktop Agents

Research conducted: 2026-04-13

---

## 1. Open Computer Use (Coasty AI)

- **Repo:** https://github.com/coasty-ai/open-computer-use
- **License:** Apache 2.0
- **Language:** TypeScript (Next.js frontend) + Python (FastAPI backend)
- **Stars:** Notable (claims 82% OSWorld — state of the art)

### Architecture
- **Frontend:** Next.js 15 + React 19 chat UI
- **Backend:** FastAPI multi-agent executor (Planner, Browser, Terminal, Desktop agents)
- **VM:** Docker container running Ubuntu 22.04 + XFCE desktop, Chrome, VNC :5900
- **Screen capture:** VNC-based for Docker VM; Puppeteer for browser; native APIs for desktop
- **Input injection:** Selenium (browser), xdotool/Win32/CoreGraphics (desktop)
- **Also has Electron desktop app** — runs agent commands locally via native automation

### Supported Platforms
- Docker VM (Linux desktop) — primary
- Electron app: Windows (Win32/PowerShell), macOS (CoreGraphics/osascript), Linux (xdotool)

### Vision Models
- Multi-provider: OpenAI, Anthropic, Google, Azure, xAI, Mistral, Perplexity, OpenRouter
- User selects model via UI

### Remote Control
- **Docker VM only** — agent controls a containerized desktop
- Electron app does **local control** only
- No true remote control of a separate physical machine over network

### Key Limitations
- Requires Supabase account for auth/storage
- Complex stack (Next.js + FastAPI + Docker + Supabase + Stripe)
- Docker-only VM approach limits use cases (can't control existing machines remotely)
- Electron app is local-only

### What We Could Reuse
- Multi-agent architecture (Planner → specialized agents)
- Action protocol design
- Model-agnostic provider abstraction

---

## 2. CUA (trycua/cua)

- **Repo:** https://github.com/trycua/cua
- **License:** MIT
- **Language:** Python (SDK), includes Lume (Swift/Rust for macOS VMs)
- **Stars:** Major project in the space

### Architecture
- **Sandbox SDK:** Unified API for controlling VMs/containers (Linux, macOS, Windows, Android)
- **cua-computer-server:** Driver inside sandbox for UI interactions + code execution
- **cuabot:** CLI tool — runs coding agents in sandboxes (supports Claude Code, OpenClaw, etc.)
- **Lume:** macOS/Linux VM management using Apple Virtualization.Framework on Apple Silicon
- **cua-bench:** Benchmarking framework (OSWorld, ScreenSpot, Windows Arena)

### Screen Capture & Input
- `sb.screenshot()` — screenshot API
- `sb.mouse.click()`, `sb.keyboard.type()`, `sb.mobile.gesture()` — unified input API
- Runs inside VMs/containers, not on bare metal remotely

### Supported Platforms
- Linux (container + VM), macOS (VM via Apple VZ), Windows (VM), Android (emulator)
- Cloud (cua.ai) or local (QEMU)

### Vision Models
- Model-agnostic — provides sandbox infrastructure, you bring your own agent/model
- cua-agent SDK for building agents

### Remote Control
- **Cloud sandbox** — agent connects to remote VMs via cua.ai cloud
- **Local QEMU** — agent controls local VMs
- NOT designed to control an existing physical machine over network — it provisions fresh VMs

### Key Limitations
- Focus on sandboxed/isolated environments, not controlling real user machines
- Heavy infrastructure (QEMU/VMs)
- macOS VMs require Apple Silicon host

### What We Could Reuse
- Sandbox API design (screenshot, mouse, keyboard abstractions)
- Benchmark framework for testing our agent
- cuabot integration — could potentially run our agent inside their sandbox

---

## 3. TankWork (AgentTankOS)

- **Repo:** https://github.com/AgentTankOS/tankwork
- **License:** MIT
- **Language:** Python
- **Version:** v0.5.0-alpha

### Architecture
- **Desktop agent framework** with voice + text control
- Uses **Claude 3.5 Sonnet** for computer use (via Anthropic API)
- **Voice:** ElevenLabs TTS for narration, voice intent recognition
- **Screen:** Computer vision via Claude's computer use beta
- **Input:** Native desktop automation (macOS-centric)
- Features agent personas (crypto analyst, narrative specialist, etc.)

### Supported Platforms
- **macOS only** (Apple Silicon recommended) — primary
- Windows: "Coming soon"
- No Linux support mentioned

### Vision Models
- Claude 3.5 Sonnet (computer use beta)
- Gemini for analysis
- GPT-4o for narrative processing

### Remote Control
- **Local only** — controls the machine it runs on
- No network/remote capability

### Key Limitations
- macOS only currently
- Alpha quality (v0.5.0)
- Crypto/trading focused personas (niche)
- Local-only, no remote control
- Heavy API dependency (ElevenLabs, Anthropic, OpenAI, Google)

### What We Could Reuse
- Voice command architecture (nice UX pattern)
- Agent persona/skill routing concept
- Minimal dependency approach (Python-only)

---

## 4. UI-TARS (ByteDance)

- **Repo:** https://github.com/bytedance/UI-TARS
- **License:** Apache 2.0 (model weights), MIT-like for code
- **Language:** Python, model in PyTorch
- **Latest:** UI-TARS-2 (Sept 2025) — "All In One" agent model

### Architecture
- **Vision-Language Model** purpose-built for GUI interaction
- Input: screenshot → Output: structured actions (click, type, drag, etc.)
- Uses **absolute coordinates** for grounding
- Supports thought-before-action reasoning (CoT)
- **UI-TARS-desktop:** Desktop application version (separate repo)
- **Midscene.js:** Web automation variant

### Performance
- OSWorld: 42.5% (vs OpenAI CUA 36.4%, Claude 3.7 28%)
- ScreenSpot-Pro: 61.6% (vs CUA 23.4%, Claude 27.7%)
- Exceptional at game tasks (near 100% on Poki benchmarks)

### Supported Platforms
- Desktop: Windows, Linux, macOS (via prompt templates)
- Mobile: Android
- Model runs anywhere (self-hosted or cloud)

### Remote Control
- Model itself is not a remote control tool — it's a **vision model**
- Needs to be paired with an execution layer (like UI-TARS-desktop or custom code)
- Could be used as the vision brain for any remote control system

### Key Limitations
- 7B parameter model — needs GPU for real-time inference
- Model-only, not a complete agent system
- Desktop app is separate and basic
- No built-in remote/network capability

### What We Could Reuse
- **The model itself** — could use UI-TARS as our vision backbone
- Coordinate-based action format is clean and well-designed
- Desktop/mobile prompt templates are reusable
- Action parser library (`pip install ui-tars`) converts model output to pyautogui commands

---

## 5. AgentSea (Surfkit)

- **Website:** https://www.agentsea.ai/
- **GitHub:** https://github.com/agentsea
- **License:** MIT
- **Language:** Python

### Architecture
- **Surfkit:** "Kubernetes for agents" — orchestration layer
- **ToolFuse:** Library for building agent tools
- **Virtual Desktop Device:** Agent-controlled desktop via mouse/keyboard commands
- Agents: Surfpizza, SurfSlicer — multimodal GUI surfers
- UNIX philosophy: small composable tools

### Virtual Desktop
- Full remote desktop that agents control by sending mouse clicks, key commands
- "Like remote desktop but with an agent in charge"
- Can run local, Docker, or cloud (GCP/Amazon)

### Supported Platforms
- Cross-platform (Python-based)
- Cloud deployment supported

### Vision Models
- Model-agnostic ("hot-swappable brains")

### Remote Control
- **Has virtual desktop concept** — closest to our use case
- Agent controls a desktop environment remotely
- But focused on **provisioned desktops**, not connecting to existing machines

### Key Limitations
- Early stage, relatively small community
- Documentation appears limited
- Focus on cloud-provisioned desktops, not controlling user's actual machine
- Website is more marketing than technical docs

### What We Could Reuse
- Virtual desktop device abstraction
- ToolFuse tool-building pattern
- Agent orchestration concepts (Surfkit)

---

## 6. Astropad Workbench

- **Website:** https://astropad.com/product/workbench/
- **Launched:** April 8, 2026
- **Pricing:** Free (20 min/day) or $10/month, $50/year
- **Type:** Proprietary remote desktop app

### Architecture
- **Remote desktop for monitoring AI agents** (not for AI to control)
- Built on Astropad's LIQUID display protocol (low-latency, Retina quality)
- **macOS host** → **iPhone/iPad client**
- Voice control via Apple's voice model (dictate commands to AI agent)
- Device chooser for multiple Macs

### Supported Platforms
- **Host:** macOS 15+ only
- **Client:** iPad, iPhone (iOS 26+)
- Windows/Linux support planned

### Vision Models
- None built-in — it's a monitoring/observation tool for humans

### Remote Control
- **Human controls remotely** via iPad/iPhone
- Purpose: check on AI agents, approve dialogs, restart stuck tasks
- NOT for AI agents to control machines — it's for humans to supervise AI

### Key Limitations
- macOS only (host)
- Proprietary/closed source
- Expensive ($10/mo)
- For human monitoring, not AI control
- iPhone client still being refined

### What We Could Reuse
- **Product insight:** "AI agent monitoring" is a real need — our tool could include a human supervision layer
- Voice command UX pattern
- Low-latency streaming is important for agent monitoring

---

## 7. Bytebot (Bonus Discovery)

- **Repo:** https://github.com/bytebot-ai/bytebot
- **Self-hosted** AI desktop agent
- Containerized Linux desktop environment
- Agent boots a fresh sandboxed computer for each task
- Similar to Coasty but more focused on self-hosting
- No remote control of existing machines

---

## Comparison Matrix

| Project | Remote Control | Existing Machine | Self-Hosted | Open Source | Platforms |
|---------|---------------|-----------------|-------------|-------------|-----------|
| Open Computer Use | Docker VM only | ❌ | ✅ | Apache 2.0 | Win/Mac/Lin (Docker) |
| CUA | Cloud VM | ❌ | ✅ | MIT | Win/Mac/Lin/Android |
| TankWork | Local only | ❌ (same machine) | ✅ | MIT | macOS only |
| UI-TARS | Model only | Needs execution layer | ✅ | Apache 2.0 | Any (model) |
| AgentSea | Virtual desktop | ❌ (provisioned) | ✅ | MIT | Cross-platform |
| Astropad Workbench | Human monitoring | ✅ (macOS) | ❌ | Proprietary | macOS only |
| **Our Project** | **✅ Any machine** | **✅** | **✅** | **GPL-3.0** | **Win/Mac/Lin** |

---

## What's Missing — The Gap We Fill

### No project does: "AI controls YOUR existing machine remotely over the network"

Every existing solution falls into one of these categories:

1. **Sandbox/VM approach** (Open Computer Use, CUA, Bytebot, AgentSea) — Agent controls a fresh VM/container. Can't interact with your actual desktop, installed apps, logged-in sessions, or local files.

2. **Local-only** (TankWork) — Agent runs on and controls the same machine. No network separation.

3. **Model-only** (UI-TARS) — Just the vision model. Needs execution infrastructure built around it.

4. **Human monitoring** (Astropad Workbench) — For humans to watch AI agents, not for AI to control machines.

### Our unique value proposition:

**An AI agent that remotely controls an existing physical/virtual machine over the network, using vision + input injection, as easily as a human would via remote desktop.**

Key differentiators:
- **Controls YOUR machine** — not a sandbox, not a fresh VM. Your apps, your login sessions, your files.
- **Lightweight agent** — runs on target machine, streams screen + accepts commands. No Docker/VM overhead.
- **Network-native** — agent on VPS controls target behind NAT via RustDesk-style relay. Works anywhere.
- **Self-hosted** — no cloud subscription, no third-party services required.
- **Model-agnostic** — use any vision model (UI-TARS, Claude, GLM, GPT-4V).
- **Can integrate UI-TARS** as the vision backbone for best-in-class GUI understanding.

This is the intersection nobody has built yet: **lightweight remote control + AI vision + existing machine + self-hosted**.
