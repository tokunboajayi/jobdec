# iMessage Migration & Integration Guide for Job Deck

This guide provides a comprehensive technical roadmap for bridging or migrating Job Deck from Telegram to Apple iMessage.

---

## 1. Executive Summary & Protocol Differences

| Feature | Telegram Bot Platform | Apple iMessage Protocol | Feasibility on iMessage |
| :--- | :--- | :--- | :--- |
| **API Availability** | Official open public Bot API & Webhooks | Proprietary, end-to-end encrypted (no official open bot API) | Requires macOS Bridge (BlueBubbles / AppleScript) |
| **Two-Way Text Commands** | `/status`, `run`, `stop`, `turbo`, `prep` | Text replies via SMS/iMessage | ✅ **100% Supported** |
| **Push Notifications & Alerts** | Instant push notifications | Native iOS blue-bubble notifications | ✅ **100% Supported** |
| **Direct Links & Documents** | Clickable HTML links & PDF attachments | Clickable links, rich iMessage previews & PDF attachments | ✅ **100% Supported** |
| **Voice Memo Commands** | Transcribes voice notes via Google Speech | Voice audio clips sent as attachments | ✅ **Supported** (with audio conversion) |
| **Interactive Inline Buttons** | Clickable touch buttons below messages | **Not supported** (Apple limits interactive buttons to Messages for Business) | ⚠️ Text replies required (e.g., text `run` or `1`) |
| **In-Place Message Editing** | Dynamic HUD edits in-place every 4s without spam | **Not supported** by Apple (new message sent for each tick) | ❌ Would create continuous chat notification clutter |
| **Pinned Top Banner** | Persistent pinned status banner in chat | **Not supported** by iMessage | ❌ Not available |

### Recommendation: Dual-Channel Architecture
The optimal setup is a **Hybrid Hub**:
1. **Telegram**: Retained as the **Full Graphical Command Center** (dynamic in-place HUD, interactive buttons, live screen cam, pinned status banner).
2. **iMessage**: Configured as the **Personal VIP Pager & Direct Alert Channel** (for instant blue-bubble alerts when you advance to an interview, get an offer, or receive a critical recruiter deadline, with one-tap Gmail links).

---

## 2. Technical Migration Paths for iMessage

### Method A: BlueBubbles REST API Bridge (Recommended)
[BlueBubbles](https://bluebubbles.app/) is a free, open-source server that runs on any macOS device (Mac Mini, MacBook, or macOS VM/cloud VPS). It exposes a private REST API and webhooks for sending and receiving iMessages.

1. **Install BlueBubbles Server** on a Mac or macOS VM:
   - Download from [bluebubbles.app](https://bluebubbles.app/).
   - Follow the setup wizard to link your Apple ID.
2. **Configure Job Deck `.env`**:
   ```ini
   IMESSAGE_ENABLED=true
   IMESSAGE_SERVER_URL=http://your-mac-ip:1234
   IMESSAGE_PASSWORD=your_bluebubbles_password
   IMESSAGE_TARGET_HANDLE=+1404XXXXXXX
   ```
3. Job Deck's `agents/imessage_bridge.py` will automatically route interview stage advancements, formal offers, and recruiter alerts to your iPhone via iMessage.

### Method B: Native macOS AppleScript
If Job Deck is executed directly on a Mac:
- `agents/imessage_bridge.py` automatically detects `sys.platform == "darwin"` and invokes `osascript` to send native iMessages via the macOS Messages app with zero third-party software.

### Method C: SendBlue / Twilio Cloud Gateway
If you do not have a dedicated macOS device running 24/7:
- Use SendBlue (iMessage API as a Service) or Twilio to forward high-priority recruiter alerts to your phone number as iMessage/SMS.

---

## 3. How Commands Work on iMessage

When using iMessage, instead of tapping inline buttons, you simply reply with intuitive short words:
- `status`: Returns milestone progress, verified counts, and runner state.
- `run` or `start`: Launches 3 parallel headless workers.
- `turbo`: Launches maximum dynamic workers based on hardware.
- `stop` or `pause`: Pauses the runner immediately.
- `prep Company`: Generates and returns an Interview Battlecard.
- `optimize`: Trims memory, lowers process priority, and kills zombie browsers.
- Paste any job URL: Immediately auto-applies on the spot.
