
from django.urls import path

from routes.views import plan_route

urlpatterns = [
    path("plan-route/", plan_route, name="plan-route"),
]
