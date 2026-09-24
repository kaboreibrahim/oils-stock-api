"""
=============================================================================
 apps/clients/permissions.py
 Lecture pour tous ; écriture pour magasinier et administrateur (§09).
 Logique partagée avec d'autres apps -> apps/common/permissions.py.
=============================================================================
"""

from apps.common.permissions import IsMagasinierOrReadOnly
from apps.common.service_auth import IsEmpotageService

__all__ = ["IsMagasinierOrReadOnly", "IsEmpotageService"]
