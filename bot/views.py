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
gemini_model = genai.GenerativeModel('gemini-1.5-flash')  # Fast & good for Hindi

@csrf_exempt
def webhook(request):
    if request.method == "GET":
        mode = request.GET.get("hub.mode")
        token = request.GET.get("hub.verify_token")
        challenge = request.GET.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            print("Webhook verified")
            return HttpResponse(challenge)
        return HttpResponse("Verification failed", status=403)

    if request.method == "POST":
        data = json.loads(request.body)
        print("INCOMING DATA:", json.dumps(data, indent=2))

        try:
            entry = data["entry"][0]
            change = entry["changes"][0]
            value = change["value"]

            if "statuses" in value:
                return JsonResponse({"status": "status ignored"})

            contacts = value.get("contacts", [])
            contact = contacts[0] if contacts else {}

            if "messages" in value:
                msg = value["messages"][0]
                print("FROM:", msg.get("from"))
                print("TYPE:", msg.get("type"))

                process_incoming_message(msg, contact)

        except Exception as e:
            print("ERROR:", str(e))

        return JsonResponse({"status": "ok"})


def process_incoming_message(msg, contact):
    
    from_phone = msg['from']
    msg_type = msg.get('type')

    session = get_session(from_phone)
    # 🔥 GLOBAL RESET COMMAND (ALWAYS WORKS)
    if msg_type == 'text':
        raw_text = msg['text']['body'].strip().lower()
        if raw_text in ['hi', 'hello', 'start', 'menu', 'हाय', 'नमस्ते']:
            session.state = 'menu'
            session.cart = {}
            session.temp_data = {}
            session.save()
            welcome_message(from_phone)
            return


    # Handle audio (voice note)
    if msg_type == 'audio':
        print("🎤 VOICE MESSAGE RECEIVED")
        media_id = msg['audio']['id']
        handle_voice_order(from_phone, media_id)
        return

    # Text or interactive
    if msg_type == 'text':
        text = msg['text']['body'].strip().lower()
    elif msg_type == 'interactive':
        if msg['interactive']['type'] == 'button_reply':
            text = msg['interactive']['button_reply']['id']
        elif msg['interactive']['type'] == 'list_reply':
            text = msg['interactive']['list_reply']['id']
        else:
            text = ""
    elif msg_type == 'location':
        lat = msg['location']['latitude']
        lng = msg['location']['longitude']
        handle_location(from_phone, lat, lng)
        return
    else:
        text = ""

    # Owner / Rider
    if from_phone == settings.OWNER_PHONE:
        handle_owner_command(from_phone, text)
        return
    if from_phone in settings.RIDER_PHONES:
        handle_rider_command(from_phone, text)
        return

    state = session.state

    # Start / Welcome
    if text in ['hi', 'hello', 'हाय', 'नमस्ते'] or state == 'start':
        welcome_message(from_phone)
        session.state = 'menu'
        session.save()
        return

    # Main Menu
    if state == 'menu':
        if text == '1':
            send_list_menu(from_phone, get_menu_categories())
            session.state = 'selecting_item'
            session.save()
        elif text == '2':
            check_order_status(from_phone)
        elif text == '3':
            send_text(from_phone, "हेल्प: मेनू से चुनें या वॉइस से बोलें।")
        elif text == 'voice_order':
            start_voice_order(from_phone)
        return

    # Voice/Text order flow
    if state == 'voice_order_waiting':
        if msg_type == 'text' and text in ['hi', 'menu', 'cancel', 'रद्द']:
            session.state = 'menu'
            session.save()
            welcome_message(from_phone)
            return
        process_voice_text_order(from_phone, msg['text']['body'])
        return


    # Normal menu flow (existing)
    if state == 'selecting_item':
        try:
            product = Product.objects.get(id=int(text), active=True)
            send_product_detail(from_phone, product)
            session.temp_data = {"awaiting_quantity_for": int(text)}
            session.state = 'awaiting_quantity'
            session.save()
        except:
            send_text(from_phone, "गलत चुनाव। दोबारा मेनू से चुनें।")
        return

    if state == 'awaiting_quantity':
        add_to_cart_with_quantity(from_phone, text)
        return

    if state == 'adding_to_cart':
        if text == 'add_more':
            send_list_menu(from_phone, get_menu_categories())
            session.state = 'selecting_item'
            session.save()
        elif text == 'view_cart':
            show_cart(from_phone)
        return

    if state == 'viewing_cart':
        if text == 'confirm_order':
            confirm_order_start(from_phone)
        elif text == 'back_to_menu':
            send_list_menu(from_phone, get_menu_categories())
            session.state = 'selecting_item'
            session.save()
        return

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


# ---------------- VOICE ORDER FUNCTIONS ----------------

def welcome_message(to):
    try:
        body = "नमस्ते! 👋 हमारी ग्रॉसरी दुकान में स्वागत है।\n\nक्या करना चाहते हैं?"
        buttons = [
            {"id": "1", "title": "ग्रॉसरी मेनू"},
            {"id": "voice_order", "title": "वॉइस ऑर्डर 🎤"},
            {"id": "2", "title": "ऑर्डर स्टेटस"}
        ]
        send_reply_buttons(to, body, buttons)
    except Exception as e:
        send_text(to, "नमस्ते! '1' = मेनू | '2' = स्टेटस | 'voice' = वॉइस ऑर्डर")

def start_voice_order(phone):
    send_text(phone, "बताएं क्या क्या चाहिए?\nवॉइस मैसेज भेजें या टाइप करें।\nउदाहरण: 5kg चावल, 2kg टमाटर, 1 पैकेट नमक")
    session = get_session(phone)
    session.state = 'voice_order_waiting'
    session.save()


def handle_voice_order(phone, media_id):
    # Download audio
    url = f"https://graph.facebook.com/v20.0/{media_id}"
    headers = {"Authorization": f"Bearer {settings.WHATSAPP_TOKEN}"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        send_text(phone, "वॉइस मैसेज प्रोसेस करने में दिक्कत हुई। टाइप करके बताएं।")
        return

    audio_url = response.json()['url']
    audio_response = requests.get(audio_url, headers=headers)
    if audio_response.status_code != 200:
        send_text(phone, "ऑडियो डाउनलोड नहीं हुआ। फिर कोशिश करें।")
        return

    # Upload to Gemini (as bytes)
    audio_file = genai.upload_file(audio_response.content, mime_type="audio/ogg")
    
    send_text(phone, "आपका वॉइस ऑर्डर प्रोसेस हो रहा है... थोड़ा इंतज़ार करें ⏳")
    
    # Call Gemini
    prompt = """
    ये ग्रॉसरी ऑर्डर है हिंदी/हिंग्लिश में। हर आइटम को निकालो: product name और quantity.
    उपलब्ध प्रोडक्ट्स: {products}
    
    आउटपुट सिर्फ JSON:
    [
      {{"name": "मिलान किया गया प्रोडक्ट नेम", "quantity": "2kg", "original": "tamatr 2kg"}},
      ...
    ]
    अगर कोई आइटम मैच न करे तो null quantity रखो।
    """.format(products=", ".join([p.name for p in Product.objects.filter(active=True)]))
    
    response = gemini_model.generate_content([audio_file, prompt])
    try:
        parsed = json.loads(response.text)
        process_parsed_items(phone, parsed)
    except:
        send_text(phone, "वॉइस समझ नहीं आया। उदाहरण: '5 किलो चावल, 2 किलो टमाटर' बोलकर भेजें।")


def process_voice_text_order(phone, text):
    products_list = ", ".join([p.name for p in Product.objects.filter(active=True)])
    prompt = f"""
    ये ग्रॉसरी ऑर्डर है: "{text}"
    उपलब्ध आइटम्स: {products_list}
    
    हर आइटम निकालो और closest match करो (typos handle करो जैसे tamatr → टमाटर)
    
    JSON में लौटाओ:
    [
      {{"matched_product": "टमाटर", "quantity": "2kg", "original": "tamatr 2kg"}},
      {{"matched_product": null, "quantity": null, "original": "xyz"}}
    ]
    """
    
    response = gemini_model.generate_content(prompt)
    try:
        parsed = json.loads(response.text)
        process_parsed_items(phone, parsed)
    except Exception as e:
        send_text(phone, f"समझ नहीं आया 😕\nउदाहरण: 5kg चावल, 2kg टमाटर, 1 पैकेट नमक")


def process_parsed_items(phone, items):
    session = get_session(phone)
    added = []
    not_found = []
    suggestions = []

    for item in items:
        if item.get('matched_product'):
            try:
                product = Product.objects.get(name__iexact=item['matched_product'], active=True)
                qty_str = item['quantity'].lower().replace('kg', '').replace('किलो', '').strip() or '1'
                qty = Decimal(qty_str)
                session.cart[str(product.id)] = float(qty)
                added.append(f"✅ {product.name} - {qty}kg")
            except:
                not_found.append(item['original'])
        else:
            not_found.append(item['original'])
            # Suggest similar
            similar = Product.objects.filter(name__icontains=item['original'].split()[0], active=True)[:2]
            if similar:
                suggestions.append(f"क्या मतलब था: {', '.join([p.name for p in similar])}?")

    session.save()

    msg = "आपका ऑर्डर समझ लिया:\n\n" + "\n".join(added)
    if not_found:
        msg += "\n\nये आइटम नहीं मिले: " + ", ".join(not_found)
        if suggestions:
            msg += "\n\n" + "\n".join(suggestions)

    if added:
        buttons = [
            {"id": "add_more", "title": "और जोड़ें"},
            {"id": "view_cart", "title": "कार्ट देखें"}
        ]
        send_reply_buttons(phone, msg, buttons)
        session.state = 'adding_to_cart'
    else:
        send_text(phone, msg + "\n\nदोबारा बताएं या मेनू से चुनें।")
        welcome_message(phone)
        session.state = 'menu'

    session.save()


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