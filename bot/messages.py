from django.conf import settings
import requests
import json

BASE_URL = f"https://graph.facebook.com/v20.0/{settings.PHONE_NUMBER_ID}"

def send_message(to: str, msg_type: str, data: dict):
    url = f"{BASE_URL}/messages"
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": msg_type,
        **data
    }
    requests.post(url, headers=headers, json=payload)

def send_text(to: str, text: str):
    send_message(to, "text", {"body": text})

def send_reply_buttons(to: str, body: str, buttons: list):
    btns = [{"type": "reply", "reply": {"id": b['id'], "title": b['title']}} for b in buttons]
    send_message(to, "interactive", {
        "type": "button",
        "body": {"text": body},
        "action": {"buttons": btns}
    })

def send_list_menu(to: str, categories):
    sections = []
    for cat_name, products in categories.items():
        rows = []
        for p in products:
            if p.active:
                desc = f"₹{p.price}/kg" if 'kg' in p.name.lower() else f"₹{p.price}"
                rows.append({
                    "id": str(p.id),
                    "title": f"{p.name[:60]}",
                    "description": desc
                })
        if rows:
            sections.append({"title": cat_name, "rows": rows[:10]})  # max 10 per section

    if not sections:
        send_text(to, "मेनू में अभी कुछ नहीं है। जल्द जोड़ा जाएगा।")
        return

    send_message(to, "interactive", {
        "type": "list",
        "header": {"type": "text", "text": "हमारा ग्रॉसरी मेनू 🍎🥦"},
        "body": {"text": "नीचे से आइटम चुनें।\nक्वांटिटी के साथ नंबर टाइप करें, जैसे: *1 2kg*"},
        "action": {
            "button": "मेनू देखें",
            "sections": sections
        }
    })