"""
=============================================================================
 apps/fournisseurs/serializers.py
 Validation de FORMAT + sérialisation uniquement. Les règles métier (unicité
 réelle, normalisation du code) vivent dans FournisseurService — l'unicité
 déclarée ici (via `unique=True` sur le modèle) n'est qu'un confort de
 validation immédiate, pas la source de vérité.
=============================================================================
"""

from rest_framework import serializers

from .models import Fournisseur


class FournisseurSerializer(serializers.ModelSerializer):
    a_un_profil_extraction = serializers.BooleanField(read_only=True)
    # Annotations de FournisseurRepository.get_all() — un fournisseur obtenu
    # autrement (queryset non annoté) n'a pas ces attributs : sans default,
    # DRF ferait planter la sérialisation.
    nb_flexitanks = serializers.IntegerField(read_only=True, default=0)
    nb_heating_pads = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Fournisseur
        fields = [
            "id", "code", "nom", "pays", "contact_nom", "contact_email",
            "contact_tel", "actif", "notes", "a_un_profil_extraction",
            "nb_flexitanks", "nb_heating_pads",
            "seuil_reappro_flexitank", "seuil_reappro_heating_pad",
            "delai_livraison_jours", "stock_securite_flexitank", "stock_securite_heating_pad",
            "cout_unitaire_flexitank", "cout_unitaire_heating_pad",
            "created_at", "updated_at",
        ]
        # Le profil d'extraction (mode_extraction, regex_numero_serie,
        # type_article_defaut) n'est ni lu ni écrit ici — voir
        # ProfilExtractionSerializer / GET·PUT /fournisseurs/{id}/profil-extraction/.
        read_only_fields = ["id", "created_at", "updated_at"]


class ProfilExtractionSerializer(serializers.ModelSerializer):
    """`GET·PUT /fournisseurs/{id}/profil-extraction/` — §07 du dossier de
    conception. Vide (`regex_numero_serie=""`) = pas de profil, extraction
    générique en amont (voir apps.receptions.extraction)."""

    class Meta:
        model = Fournisseur
        fields = ["mode_extraction", "regex_numero_serie", "type_article_defaut"]
