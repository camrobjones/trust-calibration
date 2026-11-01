"""
URL configuration for trust project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.urls import path

from conversation import views

urlpatterns = [
    path("survey/", views.survey),
    path("save_survey_results/", views.save_survey_results),
    path("conversation_instructions/", views.conversation_instructions),
    path("conversation/", views.conversation, name="conversation"),
    path("waiting_room/", views.waiting_room, name="waiting_room"),
    path("send_message/", views.send_message),
    path("get_messages/", views.get_messages),
    path("send_verdict/", views.send_verdict),
    path("waiting_room_timeout/", views.waiting_room_timeout),
    path("exit_survey/<int:ppt_id>/", views.exit_survey, name="exit_survey"),
    path("save_exit_survey_results/", views.save_exit_survey_results),
    path("download_data/<str:model>/", views.download_data),
]
