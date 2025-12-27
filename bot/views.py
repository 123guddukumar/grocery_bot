import json
import requests
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from .models import *
from .utils import *
from .messages import *

@csrf_exempt
def webhook(request):
    if request.method == 'GET':
        # Verification
        mode = request.GET.get('hub.mode')
        token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        if mode == 'subscribe' and token == settings.VERIFY_TOKEN:
            # return JsonResponse({'hub.challenge': challenge})
            return HttpResponse(challenge, status=200)
        return JsonResponse({'error': 'Forbidden'}, status=403)

    elif request.method == 'POST':
        try:
            body = json.loads(request.body)
            if body.get('object') != 'whatsapp_business_account':
                return JsonResponse({'status': 'ignored'})

            for entry in body.get('entry', []):
                for change in entry.get('changes', []):
                    value = change.get('value', {})
                    if 'messages' in value:
                        for msg in value['messages']:
                            process_incoming_message(msg, value.get('contacts', [{}])[0])
        except Exception as e:
            print("Error:", e)
        return JsonResponse({'status': 'ok'})

def process_incoming_message(msg, contact):
    from_phone = msg['from']
    msg_type = msg.get('type')

    profile_name = contact.get('profile', {}).get('name', '')

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

    # Owner / Rider commands
    if from_phone == settings.OWNER_PHONE:
        handle_owner_command(from_phone, text)
        return
    if from_phone in settings.RIDER_PHONES:
        handle_rider_command(from_phone, text)
        return

    # Customer flow
    session = get_session(from_phone)
    state = session.state

    if text in ['hi', 'hello', 'हाय', 'नमस्ते'] or state == 'start':
        welcome_message(from_phone)
        session.state = 'menu'
        session.save()

    elif state == 'menu':
        if text == '1':
            send_list_menu(from_phone, get_menu_categories())
            session.state = 'adding_to_cart'
            session.save()
        elif text == '2':
            check_order_status(from_phone)
        elif text == '3':
            send_text(from_phone, "हेल्प: बस नंबर टाइप करें। उदाहरण:\n1 2kg → 2kg आइटम नंबर 1\n'कार्ट' देखने के लिए\n'कन्फर्म' ऑर्डर के लिए")

    elif state == 'adding_to_cart':
        if text == 'कार्ट':
            show_cart(from_phone)
        elif text == 'कन्फर्म':
            confirm_order_start(from_phone)
        else:
            add_to_cart(from_phone, text)

    elif state == 'collecting_name':
        handle_name_input(from_phone, text.title())
    elif state == 'collecting_address':
        handle_address_input(from_phone, text)
    else:
        welcome_message(from_phone)

def welcome_message(to):
    body = "नमस्ते! 👋 हमारी ग्रॉसरी दुकान में आपका स्वागत है।\n\nक्या करें?"
    buttons = [
        {"id": "1", "title": "ग्रॉसरी मेनू"},
        {"id": "2", "title": "ऑर्डर स्टेटस"},
        {"id": "3", "title": "हेल्प"}
    ]
    send_reply_buttons(to, body, buttons)

def add_to_cart(phone, text):
    session = get_session(phone)
    try:
        parts = text.split()
        item_id = int(parts[0])
        quantity = parts[1] if len(parts) > 1 else "1kg"
        quantity = quantity.replace('kg', '').strip()
        qty = Decimal(quantity)

        product = Product.objects.get(id=item_id, active=True)
        session.cart[str(item_id)] = float(qty)
        session.save()

        send_text(phone, f"✅ {product.name} - {qty}kg कार्ट में जोड़ा गया!\n\nऔर जोड़ें या 'कार्ट' टाइप करें।")
    except:
        send_text(phone, "गलत इनपुट 😕\nउदाहरण: 1 2kg\nया 'कार्ट' देखने के लिए")

def show_cart(phone):
    session = get_session(phone)
    if not session.cart:
        send_text(phone, "कार्ट खाली है। मेनू से आइटम चुनें।")
        return

    cart_text, item_total, delivery, grand = format_cart(session.cart)
    cart_text += "\n\nकन्फर्म करने के लिए 'कन्फर्म' टाइप करें"
    send_text(phone, cart_text)
    session.state = 'adding_to_cart'
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