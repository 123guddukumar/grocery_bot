from django.contrib import admin
from django.urls import path, re_path
from bot import views

urlpatterns = [
    path('admin/', admin.site.urls),
    re_path(r'^webhook/?$', views.webhook, name='webhook'),
    re_path(r'^menu/?$', views.web_menu, name='web_menu'),
    path("api/web-order/", views.web_order),
    path("api/add-to-cart/", views.web_add_to_cart),
]