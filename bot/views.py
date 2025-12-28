import json
import requests
import google.generativeai as genai
from decimal import Decimal
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import *
from .utils import *
from .messages import *

VERIFY_TOKEN = "grocery_bot_verify_123"

# Configure Gemini
genai.configure(api_key=settings.GEMINI_API_KEY)
gemini_model = genai.GenerativeModel('gemini-1.5-flash')


@csrf_exempt
def webhook(request):
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")
        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("Webhook verified")
            return HttpResponse(challenge)
        return HttpResponse("Forbidden", status=403)

    if request.method == "POST":
        data = json.loads(request.body)
        print("INCOMING:", json.dumps(data, indent=2))

        try:
            entry = data["entry"][0]["changes"][0]["value"]

            if "statuses" in entry:
                return JsonResponse({"ok": True})

            if "messages" not in entry:
                return JsonResponse({"ok": True})

            msg = entry["messages"][0]
            from_phone = msg["from"]
            msg_type = msg.get("type")

            contact = entry.get("contacts", [{}])[0]
            process_incoming_message(msg, contact)

        except Exception as e:
            print("ERROR:", e)

        return JsonResponse({"ok": True})


def process_incoming_message(msg, contact):
    from_phone = msg['from']
    msg_type = msg.get('type')

    session = get_session(from_phone)

    # Handle Voice Note
    if msg_type == "audio":
        audio_id = msg["audio"]["id"]
        handle_voice_order(from_phone, audio_id)
        return

    # Handle Text or Button
    text = ""
    if msg_type == "text":
        text = msg["text"]["body"].strip().lower()
    elif msg_type == "interactive":
        interactive = msg["interactive"]
        if interactive["type"] == "button_reply":
            text = interactive["button_reply"]["id"].lower()
        elif interactive["type"] == "list_reply":
            text = interactive["list_reply"]["id"].lower()

    # Owner / Rider
    if from_phone == settings.OWNER_PHONE:
        handle_owner_command(from_phone, text)
        return
    if from_phone in settings.RIDER_PHONES:
        handle_rider_command(from_phone, text)
        return

    state = session.state

    # Welcome
    if text in ['hi', 'hello', 'हाय', 'नमस्ते', 'start'] or state == 'start':
        welcome_message(from_phone)
        session.state = 'menu'
        session.save()
        return

    # Trigger Voice by text command
    if 'voice' in text or 'वॉइस' in text or text == '4':
        start_voice_order(from_phone)
        return

    # Main Menu
    if state == 'menu':
        if text == '1':
            send_list_menu(from_phone, get_menu_categories())
            session.state = 'selecting_item'
        elif text == '2':
            check_order_status(from_phone)
        elif text == '3':
            send_text(from_phone, "हेल्प: मेनू से चुनें या 'वॉइस' टाइप करके बोलकर ऑर्डर करें।")
        session.save()
        return

    # Normal Menu Flow
    if state == 'selecting_item':
        handle_menu_item_selection(from_phone, text)
        return
    if state == 'awaiting_quantity':
        add_to_cart_with_quantity(from_phone, text)
        return
    if state == 'adding_to_cart':
        if text == 'add_more':
            send_list_menu(from_phone, get_menu_categories())
            session.state = 'selecting_item'
        elif text == 'view_cart':
            show_cart(from_phone)
        session.save()
        return
    if state == 'viewing_cart':
        if text == 'confirm_order':
            confirm_order_start(from_phone)
        elif text == 'back_to_menu':
            send_list_menu(from_phone, get_menu_categories())
            session.state = 'selecting_item'
        session.save()
        return

    # Voice Flow
    if state == 'voice_order':
        handle_voice_text_input(from_phone, text.upper())  # Case insensitive
        return
    if state == 'voice_confirm':
        if text == 'yes_confirm':
            confirm_voice_cart(from_phone)
        elif text == 'no_edit':
            start_voice_order(from_phone, edit=True)
        session.save()
        return

    # Personal Info
    if state == 'collecting_name':
        handle_name_input(from_phone, text.title())
        return
    if state == 'collecting_address':
        handle_address_input(from_phone, text)
        return

    # Fallback
    welcome_message(from_phone)
    session.state = 'menu'
    session.save()


# ==================== VOICE ORDER ====================

def start_voice_order(to, edit=False):
    msg = "फिर से बताएं क्या चाहिए?" if edit else "बताएं क्या-क्या चाहिए?\n\nवॉइस मैसेज भेजें या टाइप करें।\nउदाहरण: 5kg चावल, 2 किलो टमाटर, 1 पैकेट नमक"
    send_text(to, msg)
    session = get_session(to)
    session.state = 'voice_order'
    session.temp_data = {"voice_items": []}
    session.save()


def handle_voice_order(phone, audio_id):
    # Download audio
    url = f"https://graph.facebook.com/v22.0/{audio_id}"
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}
    resp = requests.get(url, headers=headers)
    audio_url = resp.json().get("url")

    audio_resp = requests.get(audio_url, headers=headers)
    with open("/tmp/audio.ogg", "wb") as f:
        f.write(audio_resp.content)

    # Transcribe with Gemini
    sample_file = genai.upload_file(path="/tmp/audio.ogg", display_name="order")
    response = gemini_model.generate_content(
        [sample_file, "\n\n", "इस वॉइस मैसेज में ग्रॉसरी ऑर्डर है। क्या-क्या मांगा है? सिर्फ टेक्स्ट लौटाओ।"]
    )
    transcribed_text = response.text.strip()

    genai.delete_file(sample_file.name)

    send_text(phone, f"आपने कहा: {transcribed_text}\n\nप्रोसेस कर रहा हूँ...")
    handle_voice_text_input(phone, transcribed_text)


def handle_voice_text_input(phone, text):
    session = get_session(phone)

    # Get all product names for context
    products = Product.objects.filter(active=True)
    product_list = "\n".join([f"- {p.name} (₹{p.price})" for p in products])

    prompt = f"""
आप एक ग्रॉसरी बॉट हैं। यूजर ने ये कहा: "{text}"

उपलब्ध आइटम्स:
{product_list}

इसमें से हर आइटम को quantity के साथ निकालो।
फॉर्मेट: JSON array of objects
[
  {{"name": "exact_product_name_from_list", "quantity": "2kg" or "1" or "500g"}}
]

अगर आइटम मैच नहीं करता तो skip करो।
अगर थोड़ा गलत spelling है लेकिन मतलब साफ है तो closest match करो।
उदाहरण:
- "tamatr" → टमाटर
- "sona mansuri" → सोना मसूरी चावल
- "dal" → अरहर दाल (अगर सिर्फ एक दाल है)

सिर्फ JSON लौटाओ, कुछ और नहीं।
"""

    try:
        response = gemini_model.generate_content(prompt)
        items = json.loads(response.text)
    except Exception as e:
        send_text(phone, "समझ नहीं पाया। कृपया दोबारा बोलें या टाइप करें।")
        return

    added = []
    not_found = []
    for item in items:
        try:
            product = None
            name_lower = item["name"].lower()
            for p in products:
                if name_lower in p.name.lower() or p.name.lower() in name_lower:
                    product = p
                    break
            if product:
                qty = item["quantity"].replace("किलो", "kg").replace("किग्रा", "kg")
                qty_num = qty.replace("kg", "").replace("g", "").strip() or "1"
                session.cart[str(product.id)] = float(qty_num)
                added.append(f"• {product.name} - {qty}")
            else:
                not_found.append(item["name"])
        except:
            not_found.append(item["name"])

    session.save()

    msg = "आपका ऑर्डर समझ लिया!\n\n"
    if added:
        msg += "जोड़े गए आइटम:\n" + "\n".join(added) + "\n\n"
    if not_found:
        suggestions = []
        for nf in not_found:
            # Simple suggestion
            matches = [p.name for p in products if nf.lower() in p.name.lower()][:2]
            if matches:
                suggestions.append(f"{nf} → शायद {', '.join(matches)}?")
        if suggestions:
            msg += "ये आइटम नहीं मिले:\n" + "\n".join([f"- {nf}" for nf in not_found]) + "\n\nसुझाव:\n" + "\n".join(suggestions) + "\n\n"
        else:
            msg += "ये आइटम उपलब्ध नहीं हैं:\n" + "\n".join([f"- {nf}" for nf in not_found]) + "\n\n"

    cart_text, _, _, grand = format_cart(session.cart)
    msg += cart_text

    buttons = [
        {"id": "yes_confirm", "title": "हाँ, कन्फर्म करें"},
        {"id": "no_edit", "title": "बदलाव करें"}
    ]
    send_reply_buttons(phone, msg, buttons)

    session.state = 'voice_confirm'
    session.save()


def confirm_voice_cart(phone):
    session = get_session(phone)
    show_cart(phone)  # reuse normal cart view
    session.state = 'viewing_cart'
    session.save()


# ==================== WELCOME FIX (3 BUTTONS) ====================

def welcome_message(to):
    body = "नमस्ते! स्वागत है हमारी ग्रॉसरी दुकान में 🛒\n\nक्या करें?\n\n'वॉइस' टाइप करके बोलकर ऑर्डर कर सकते हैं।"
    buttons = [
        {"id": "1", "title": "मेनू देखें"},
        {"id": "2", "title": "ऑर्डर स्टेटस"},
        {"id": "3", "title": "हेल्प"}
    ]
    send_reply_buttons(to, body, buttons)


# ==================== NORMAL MENU FLOW ====================

def handle_menu_item_selection(phone, text):
    try:
        product = Product.objects.get(id=int(text), active=True)
        send_product_detail(phone, product)
        session = get_session(phone)
        session.temp_data = {"awaiting_quantity_for": int(text)}
        session.state = 'awaiting_quantity'
        session.save()
    except:
        send_text(phone, "गलत चुनाव। कृपया मेनू से दोबारा चुनें।")
        welcome_message(phone)




def send_product_detail(to, product):
    caption = f"{product.name}\n₹{product.price} per kg\n\nकितनी क्वांटिटी चाहिए?\nउदाहरण: 2kg या 1"
    if product.image_url:
        send_message(to, "image", {"image": {"link": product.image_url, "caption": caption}})
    else:
        send_text(to, caption)


def add_to_cart_with_quantity(phone, quantity_text):
    session = get_session(phone)
    product_id = session.temp_data.get("awaiting_quantity_for")
    if not product_id:
        send_text(phone, "कुछ गड़बड़ हुई। कृपया दोबारा मेनू से शुरू करें।")
        welcome_message(phone)
        return

    try:
        qty_str = quantity_text.strip().lower().replace('kg', '').replace('किग्रा', '').strip()
        qty = Decimal(qty_str or "1")

        product = Product.objects.get(id=product_id, active=True)
        session.cart[str(product_id)] = float(qty)
        session.save()

        body = f"{product.name} - {qty}kg कार्ट में जोड़ा गया!"
        buttons = [
            {"id": "add_more", "title": "और जोड़ें"},
            {"id": "view_cart", "title": "कार्ट देखें"}
        ]
        send_reply_buttons(phone, body, buttons)

        session.state = 'adding_to_cart'
        session.temp_data = {}
        session.save()

    except:
        send_text(phone, "गलत क्वांटिटी। उदाहरण: 2kg या 1.5")


def show_cart(phone):
    session = get_session(phone)
    if not session.cart:
        send_text(phone, "कार्ट खाली है। मेनू से आइटम चुनें।")
        welcome_message(phone)
        session.state = 'menu'
        session.save()
        return

    cart_text, item_total, delivery, grand = format_cart(session.cart)

    buttons = [
        {"id": "confirm_order", "title": "ऑर्डर कन्फर्म करें"},
        {"id": "back_to_menu", "title": "मेनू में वापस"}
    ]
    send_reply_buttons(phone, cart_text, buttons)

    session.state = 'viewing_cart'
    session.save()


def confirm_order_start(phone):
    session = get_session(phone)
    if not session.cart:
        send_text(phone, "कार्ट खाली है!")
        return

    _, _, _, grand = format_cart(session.cart)
    send_text(phone, f"ऑर्डर कन्फर्म करने जा रहे हैं। कुल: ₹{grand}\n\nअपना नाम बताएं:")
    session.state = 'collecting_name'
    session.save()

def handle_name_input(phone, name):
    customer = get_or_create_customer(phone)
    customer.name = name
    customer.save()
    send_text(phone, f"धन्यवाद {name}! अब अपना पूरा एड्रेस बताएं:")
    session = get_session(phone)
    session.state = 'collecting_address'
    session.save()

def handle_address_input(phone, address):
    customer = Customer.objects.get(phone=phone)
    customer.address = address
    customer.save()

    session = get_session(phone)
    cart = session.cart
    item_total, delivery, grand_total = calculate_totals(cart)

    order = Order.objects.create(
        customer=customer,
        item_total=item_total,
        delivery_charge=delivery,
        grand_total=grand_total,
        status='PLACED'
    )
    for pid, qty in cart.items():
        try:
            p = Product.objects.get(id=pid)
            OrderItem.objects.create(
                order=order,
                product=p,
                quantity=qty,
                price=p.price
            )
        except:
            pass

    session.current_order = order
    session.cart = {}
    session.state = 'menu'
    session.save()

    # Notify customer
    send_text(phone, f"🎉 ऑर्डर #{order.id} सफलतापूर्वक प्लेस हो गया!\nकुल: ₹{grand_total}\n\nस्टेटस अपडेट मिलते रहेंगे।")

    # Notify owner
    notify_owner_new_order(order)

def handle_location(phone, lat, lng):
    session = get_session(phone)
    if session.current_order:
        order = session.current_order
        order.location_lat = lat
        order.location_lng = lng
        order.save()
        send_text(phone, "लोकेशन मिल गई! धन्यवाद।")

def notify_owner_new_order(order):
    map_link = f"https://maps.google.com/?q={order.location_lat or ''},{order.location_lng or ''}" if order.location_lat else "लोकेशन नहीं दी गई"
    items = "\n".join([f"- {oi.product.name} {oi.quantity}kg @ ₹{oi.price} = ₹{oi.price * oi.quantity}" for oi in order.items.all()])
    text = f"""नया ऑर्डर! #{order.id}
नाम: {order.customer.name}
मोबाइल: {order.customer.phone}
एड्रेस: {order.customer.address}
मैप: {map_link}

आइटम्स:
{items}

टोटल: ₹{order.item_total} | डिलीवरी: ₹{order.delivery_charge} | ग्रैंड: ₹{order.grand_total}

एक्सेप्ट करने के लिए 'OK' रिप्लाई करें।"""
    send_text(settings.OWNER_PHONE, text)

def handle_owner_command(phone, text):
    if text == 'ok':
        orders = Order.objects.filter(status='PLACED').order_by('-created_at')
        if orders:
            order = orders[0]
            order.status = 'ACCEPTED'
            order.save()
            send_text(order.customer.phone, f"✅ आपका ऑर्डर #{order.id} एक्सेप्ट हो गया! जल्द डिलीवरी होगी।")
            send_text(settings.OWNER_PHONE, "ऑर्डर एक्सेप्ट हो गया। अब राइडर असाइन करें।")
            # Auto assign first rider (simple MVP)
            if settings.RIDER_PHONES:
                rider_phone = settings.RIDER_PHONES[0]
                rider, _ = Rider.objects.get_or_create(phone=rider_phone, defaults={'name': 'Rider'})
                order.rider = rider
                order.status = 'RIDER_ASSIGNED'
                order.save()
                notify_rider(order)
        else:
            send_text(phone, "कोई पेंडिंग ऑर्डर नहीं है।")

def notify_rider(order):
    map_link = f"https://maps.google.com/?q={order.location_lat or ''},{order.location_lng or ''}" if order.location_lat else ""
    text = f"""नई डिलीवरी!
पिकअप: दुकान (बेतिया/मोतिहारी)
कस्टमर: {order.customer.name} - {order.customer.phone}
एड्रेस: {order.customer.address}
मैप: {map_link}

COD अमाउंट: ₹{order.grand_total}

पिकअप कन्फर्म करें: 'READY' टाइप करें
डिलीवर करने पर: 'DELIVERED' टाइप करें"""
    send_text(order.rider.phone, text)
    send_text(settings.OWNER_PHONE, "राइडर को मैसेज भेज दिया गया।")

def handle_rider_command(phone, text):
    rider = Rider.objects.get(phone=phone)
    orders = Order.objects.filter(rider=rider, status__in=['RIDER_ASSIGNED', 'OUT_FOR_DELIVERY'])
    if not orders:
        return
    order = orders.latest('created_at')

    if text == 'ready':
        order.status = 'OUT_FOR_DELIVERY'
        order.save()
        send_text(settings.OWNER_PHONE, f"राइडर पिकअप करके निकल गया है - ऑर्डर #{order.id}")
        send_text(order.customer.phone, f"🚚 आपका ऑर्डर #{order.id} आउट फॉर डिलीवरी है!")

    elif text == 'delivered':
        order.status = 'DELIVERED'
        order.save()
        send_text(order.customer.phone, f"🎉 आपका ऑर्डर #{order.id} डिलीवर हो गया! धन्यवाद 🙏")
        send_text(settings.OWNER_PHONE, f"ऑर्डर #{order.id} डिलीवर हो गया। COD: ₹{order.grand_total}")

def check_order_status(phone):
    customer = Customer.objects.filter(phone=phone).first()
    if not customer:
        send_text(phone, "आपका कोई ऑर्डर नहीं मिला।")
        return
    orders = Order.objects.filter(customer=customer).order_by('-created_at')[:5]
    if not orders:
        send_text(phone, "कोई ऑर्डर नहीं मिला।")
        return
    msg = "आपके हाल के ऑर्डर:\n\n"
    for o in orders:
        status_hi = {
            'PLACED': 'प्लेस किया गया',
            'ACCEPTED': 'एक्सेप्ट',
            'RIDER_ASSIGNED': 'राइडर असाइन',
            'OUT_FOR_DELIVERY': 'डिलीवरी पर',
            'DELIVERED': 'डिलीवर'
        }.get(o.status, o.status)
        msg += f"#{o.id} - ₹{o.grand_total} - {status_hi}\n"
    send_text(phone, msg)