from decimal import Decimal
from .models import Product, Customer, Order, OrderItem, UserSession, Rider
from .messages import send_text, send_reply_buttons, send_list_menu
from django.conf import settings

def get_or_create_customer(phone):
    cust, _ = Customer.objects.get_or_create(phone=phone)
    return cust

def get_session(phone):
    sess, _ = UserSession.objects.get_or_create(phone=phone)
    return sess

def calculate_totals(cart):
    total = Decimal('0')
    for pid, qty in cart.items():
        try:
            product = Product.objects.get(id=pid)
            total += product.price * Decimal(str(qty))
        except:
            pass
    delivery = Decimal('50') if total < Decimal('500') else Decimal('0')
    grand = total + delivery
    return total, delivery, grand

def format_cart(cart):
    lines = ["आपका कार्ट:"]
    total = Decimal('0')
    for pid, qty in cart.items():
        try:
            p = Product.objects.get(id=pid)
            amt = p.price * Decimal(str(qty))
            total += amt
            lines.append(f"• {p.name} - {qty} @ ₹{p.price} = ₹{amt}")
        except:
            lines.append(f"• आइटम {pid} - {qty} (हटा दिया गया)")
    delivery = Decimal('50') if total < Decimal('500') else Decimal('0')
    grand = total + delivery
    lines.append("")
    lines.append(f"आइटम टोटल: ₹{total}")
    lines.append(f"डिलीवरी चार्ज: ₹{delivery}" + (" (₹500 से कम पर)" if delivery else " (फ्री!)"))
    lines.append(f"ग्रैंड टोटल: ₹{grand}")
    return "\n".join(lines), total, delivery, grand

def get_menu_categories():
    products = Product.objects.filter(active=True).order_by('category', 'name')
    cats = {}
    for p in products:
        cat = p.category or "अन्य"
        cats.setdefault(cat, []).append(p)
    return cats