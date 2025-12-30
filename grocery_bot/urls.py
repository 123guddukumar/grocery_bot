from django.contrib import admin
from django.urls import path
from bot import views

urlpatterns = [
    path('admin/', admin.site.urls),
    path('webhook/', views.webhook, name='webhook'),
    path("menu/", views.web_menu, name="web_menu"),
    path("api/web-order/", views.web_order),
    path("api/add-to-cart/", views.web_add_to_cart),


]