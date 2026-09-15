from django.contrib import admin

from .models import Client


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("code", "nom", "pays", "actif")
    list_filter = ("actif",)
    search_fields = ("code", "nom")
    ordering = ("nom",)
