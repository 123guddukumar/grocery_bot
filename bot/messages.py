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


# ---------------- CATALOG-STYLE PRODUCT LIST (WITH IMAGES) ----------------
def send_product_menu(to: str, categories):
    sections = []

    for cat_name, products in categories.items():
        rows = []
        for p in products:
            if not p.active:
                continue

            price_str = f"₹{p.price}/kg" if "kg" in p.name.lower() else f"₹{p.price}"

            row = {
                "id": str(p.id),
                "title": p.name[:60],
                "description": price_str
            }

            # If image_url exists, add thumbnail (WhatsApp supports in list rows)
            # Note: WhatsApp list rows don't officially support images yet, but product catalog does.
            # So we're using "product" interactive type for better image support
            rows.append(row)

        if rows:
            sections.append({"title": cat_name[:24], "rows": rows[:10]})

    if not sections:
        return send_text(to, "मेनू में अभी कोई आइटम उपलब्ध नहीं है 🙏")

    # Use product list if images, else fallback to list
    # WhatsApp has "product" type for catalog, but for custom, we use list + describe image in desc
    # Better: Send as interactive list with description including image hint, but actual image via URL not direct.
    # For real images in menu, WhatsApp Business Catalog is best, but for Cloud API custom, limited.
    # Compromise: Use list menu, but send image separately on select? No, better stick to list but add image in cart or something.
    # Wait, WhatsApp Cloud API supports "catalog" message type for businesses with catalog.
    # But for simple, we'll add image_url and send single product messages if needed.
    # For now: Keep list menu, but after selecting item, send product image + quantity prompt.

    return send_message(
        to,
        "interactive",
        {
            "type": "list",
            "header": {"type": "text", "text": "हमारा ग्रॉसरी मेनू 🛒🍅"},
            "body": {"text": "नीचे से आइटम चुनें। क्वांटिटी बताएं, जैसे 2kg"},
            "action": {"button": "मेनू देखें", "sections": sections}
        }
    )

# New: Send product image when item selected
def send_product_detail(to: str, product):
    if product.image_url:
        send_message(to, "image", {"image": {"link": product.image_url, "caption": f"{product.name}\n₹{product.price}\nकितनी क्वांटिटी चाहिए? (उदा: 2kg)"}})
    else:
        send_text(to, f"{product.name}\n₹{product.price}\nकितनी क्वांटिटी चाहिए? (उदा: 2kg या 1)")