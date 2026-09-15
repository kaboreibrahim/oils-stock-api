"""
=============================================================================
 apps/receptions/serializers.py
=============================================================================
"""

from rest_framework import serializers

from apps.stock.models import TypeArticle

from .models import LigneReception, Reception


class LigneReceptionSerializer(serializers.ModelSerializer):
    fournisseur_code = serializers.CharField(source="fournisseur.code", read_only=True, default=None)

    class Meta:
        model = LigneReception
        fields = [
            "id", "numero_serie", "fournisseur", "fournisseur_code",
            "type_article", "statut_ligne", "source", "ajoute_le",
        ]
        read_only_fields = fields


class ReceptionSerializer(serializers.ModelSerializer):
    fournisseur_code = serializers.CharField(source="fournisseur.code", read_only=True, default=None)
    nb_lignes = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Reception
        fields = [
            "id", "reference", "nature", "fournisseur", "fournisseur_code", "reference_fournisseur",
            "fichier", "date_reception", "statut", "quantite_annoncee", "nb_lignes",
            "valide_le", "annule_le", "motif_annulation", "notes", "created_at", "updated_at",
        ]
        read_only_fields = [
            "id", "reference", "statut", "nb_lignes", "valide_le", "annule_le",
            "motif_annulation", "created_at", "updated_at",
        ]


class ReceptionDetailSerializer(ReceptionSerializer):
    lignes = LigneReceptionSerializer(many=True, read_only=True)

    class Meta(ReceptionSerializer.Meta):
        fields = ReceptionSerializer.Meta.fields + ["lignes"]


class AjouterLigneReceptionSerializer(serializers.Serializer):
    """Contrat JSON : `{"numero_serie": "...", "type_article": "FLEXITANK"|"HEATING_PAD",
    "fournisseur": "<uuid>"?, "fournisseur_code": "..."?}`.
    `fournisseur`/`fournisseur_code` ne servent qu'en reprise (créé à la volée si le code
    est inconnu) — ignorés pour un arrivage/une saisie, où le fournisseur vient de l'en-tête."""

    numero_serie = serializers.CharField(max_length=100)
    type_article = serializers.ChoiceField(choices=TypeArticle.choices)
    fournisseur = serializers.UUIDField(required=False, allow_null=True)
    fournisseur_code = serializers.CharField(max_length=20, required=False, allow_blank=True)


class AjouterPlageReceptionSerializer(serializers.Serializer):
    """Contrat JSON :
    `{"prefixe": "24E3231260424A", "debut": 1, "fin": 131, "largeur": 3?,
    "type_article": "FLEXITANK", "fournisseur": "<uuid>"?, "fournisseur_code": "..."?}`.
    Génère une ligne par numéro `prefixe + n` (zéro-préfixé sur `largeur` chiffres,
    déduite de `fin` si omise)."""

    prefixe = serializers.CharField(max_length=80, allow_blank=True)
    debut = serializers.IntegerField(min_value=0)
    fin = serializers.IntegerField(min_value=0)
    largeur = serializers.IntegerField(required=False, allow_null=True, min_value=1, max_value=10)
    type_article = serializers.ChoiceField(choices=TypeArticle.choices)
    fournisseur = serializers.UUIDField(required=False, allow_null=True)
    fournisseur_code = serializers.CharField(max_length=20, required=False, allow_blank=True)


class AnnulerReceptionSerializer(serializers.Serializer):
    """Contrat JSON : `{"motif": "..."}`."""

    motif = serializers.CharField(max_length=255)


class ExtraireSerializer(serializers.Serializer):
    """Contrat JSON : `{"type_article": "FLEXITANK"|"HEATING_PAD"}` — optionnel
    si le fournisseur a un `type_article_defaut` sur son profil d'extraction."""

    type_article = serializers.ChoiceField(choices=TypeArticle.choices, required=False)


class PlageDetecteeSerializer(serializers.Serializer):
    """Indice de plage repéré dans les numéros extraits — voir
    apps.receptions.extraction.detecter_plage. Purement informatif : ne crée
    rien, l'utilisateur complète via POST .../lignes/plage/ s'il le souhaite."""

    prefixe = serializers.CharField()
    debut = serializers.IntegerField()
    fin = serializers.IntegerField()
    largeur = serializers.IntegerField()
    complet = serializers.BooleanField()
    nb_trouves = serializers.IntegerField()
    nb_attendus = serializers.IntegerField()


class ExtractionResultatSerializer(serializers.Serializer):
    """Réponse de `POST /receptions/{id}/extraire/`."""

    lignes = LigneReceptionSerializer(many=True)
    plage_detectee = PlageDetecteeSerializer(allow_null=True)
    generique = serializers.BooleanField()
    ocr_utilise = serializers.BooleanField()
