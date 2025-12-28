from django.conf import settings
import requests
import json

# ---------------- CONFIG ----------------
GRAPH_VERSION = "v22.0"  # Stable
BASE_URL = f"https://graph.facebook.com/{GRAPH_VERSION}/{settings.PHONE_NUMBER_ID}"

HEADERS = {
    "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
    "Content-Type": "application/json"
}


# ---------------- CORE SEND FUNCTION ----------------
def send_message(to: str, msg_type: str, data: dict):
    url = f"{BASE_URL}/messages"

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": msg_type,
        **data
    }

    # 🔥 DEBUG LOGS (VERY IMPORTANT)
    print("\n📤 SENDING MESSAGE")
    print("➡️ TO:", to)
    print("➡️ TYPE:", msg_type)
    print("📦 PAYLOAD:", json.dumps(payload, indent=2))

    response = requests.post(url, headers=HEADERS, json=payload)

    print("📨 META STATUS:", response.status_code)
    print("📨 META RESPONSE:", response.text)

    return response


# ---------------- TEXT MESSAGE ----------------
def send_text(to: str, text: str):
    return send_message(
        to,
        "text",
        {
            "text": {
                "body": text
            }
        }
    )


# ---------------- REPLY BUTTONS ----------------
def send_reply_buttons(to: str, body: str, buttons: list):
    btns = [
        {
            "type": "reply",
            "reply": {
                "id": b["id"],
                "title": b["title"][:20]  # WhatsApp limit
            }
        }
        for b in buttons
    ]

    return send_message(
        to,
        "interactive",
        {
            "interactive": {
                "type": "button",
                "body": {"text": body},
                "action": {"buttons": btns}
            }
        }
    )


# ---------------- LIST MENU ----------------
def send_list_menu(to: str, categories):
    sections = []

    for cat_name, products in categories.items():
        rows = []

        for p in products:
            if not p.active:
                continue

            desc = f"₹{p.price}/kg" if "kg" in p.name.lower() else f"₹{p.price}"

            rows.append({
                "id": str(p.id),
                "title": p.name[:24],       # WhatsApp limit
                "description": desc[:72]
            })

        if rows:
            sections.append({
                "title": cat_name[:24],
                "rows": rows[:10]           # Max 10 rows
            })

    if not sections:
        return send_text(to, "मेनू में अभी कोई आइटम उपलब्ध नहीं है 🙏")

    return send_message(
        to,
        "interactive",
        {
            "interactive": {
                "type": "list",
                "header": {
                    "type": "text",
                    "text": "हमारा ग्रॉसरी मेनू 🛒"
                },
                "body": {
                    "text": "नीचे से आइटम चुनें।\nउदाहरण: *1 2kg*"
                },
                "action": {
                    "button": "मेनू देखें",
                    "sections": sections
                }
            }
        }
    )
