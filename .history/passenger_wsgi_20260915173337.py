"""
Point d'entrée attendu par Passenger sur un hébergement mutualisé cPanel
(fonctionnalité « Setup Python App »). cPanel génère un fichier du même nom
par défaut lors de la création de l'app Python — celui-ci le remplace pour
pointer vers la vraie application WSGI Django (core/wsgi.py), inchangée.

Ne pas renommer ce fichier ni le déplacer : Passenger cherche `passenger_wsgi.py`
à la racine du dossier de l'application configuré dans cPanel.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

from core.wsgi import application  # noqa: E402 (import après sys.path/env, nécessaire ici)
