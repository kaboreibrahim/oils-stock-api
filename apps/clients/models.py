"""
=============================================================================
 apps/clients/models.py
=============================================================================
"""

from django.db import models

from apps.common.models import BaseModel


class Client(BaseModel):
    """Client destinataire d'une sortie de stock."""

    code = models.CharField("code", max_length=20, unique=True)
    nom = models.CharField("nom", max_length=200)
    contact_nom = models.CharField("contact", max_length=200, blank=True)
    contact_email = models.EmailField("e-mail", blank=True)
    contact_tel = models.CharField("téléphone", max_length=50, blank=True)
    adresse = models.CharField("adresse", max_length=255, blank=True)
    pays = models.CharField("pays", max_length=100, blank=True)
    actif = models.BooleanField("actif", default=True)
    notes = models.TextField("notes", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["nom"]
        verbose_name = "client"
        verbose_name_plural = "clients"

    def __str__(self) -> str:
        return f"{self.nom} ({self.code})"
