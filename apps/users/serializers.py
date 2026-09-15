"""
=============================================================================
 apps/users/serializers.py
=============================================================================
"""

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import User


class MeSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "role", "is_staff", "is_superuser",
        ]
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    """Gestion des comptes (Jalon 6, admin uniquement) — lecture et
    modification (rôle, coordonnées, actif/inactif). Le mot de passe n'est
    jamais lu ni modifié via ce serializer : à la création (voir
    CreerUserSerializer) ou via /auth/password/reset/ ensuite."""

    class Meta:
        model = User
        fields = [
            "id", "username", "email", "first_name", "last_name",
            "role", "is_active", "date_joined",
        ]
        read_only_fields = ["id", "date_joined"]


class CreerUserSerializer(serializers.ModelSerializer):
    """
    Création d'un compte (Jalon 6, admin uniquement).
    Données attendues :
      {
        "username": "magasinier2",
        "password": "MotDePasseInitial123!",
        "role": "MAGASINIER",
        "email": "" (optionnel),
        "first_name": "" (optionnel),
        "last_name": "" (optionnel)
      }
    """

    password = serializers.CharField(
        write_only=True, style={"input_type": "password"},
        help_text="Mot de passe initial — le compte pourra le changer via « mot de passe oublié ».",
    )

    class Meta:
        model = User
        fields = ["username", "password", "email", "first_name", "last_name", "role"]


class LoginSerializer(serializers.Serializer):
    """
    Connexion.
    Données attendues :
      {
        "username": "admin",
        "password": "admin1234"
      }
    """

    username = serializers.CharField(help_text="Nom d'utilisateur.")
    password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        help_text="Mot de passe du compte.",
    )


class LogoutSerializer(serializers.Serializer):
    """
    Déconnexion.
    Données attendues :
      {
        "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
      }
    """

    refresh = serializers.CharField(help_text="Refresh token à révoquer.")


class DemandeReinitialisationSerializer(serializers.Serializer):
    """
    Demande d'un code de réinitialisation par e-mail.
    Données attendues :
      {
        "email": "user@example.com"
      }
    """

    email = serializers.EmailField(help_text="E-mail du compte à réinitialiser.")


class ConfirmationReinitialisationSerializer(serializers.Serializer):
    """
    Confirmation du nouveau mot de passe avec le code reçu par e-mail.
    Données attendues :
      {
        "email": "user@example.com",
        "code": "123456",
        "new_password": "NouveauMotDePasse123!",
        "confirm_password": "NouveauMotDePasse123!"
      }
    """

    email = serializers.EmailField(help_text="E-mail du compte.")
    code = serializers.CharField(
        min_length=6, max_length=6,
        help_text="Code à 6 chiffres reçu par e-mail (valable 15 minutes, usage unique).",
    )
    new_password = serializers.CharField(
        write_only=True, min_length=8,
        style={"input_type": "password"},
        help_text="Nouveau mot de passe (min. 8 caractères).",
    )
    confirm_password = serializers.CharField(
        write_only=True,
        style={"input_type": "password"},
        help_text="Confirmation du nouveau mot de passe.",
    )

    def validate_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Le code doit contenir uniquement des chiffres.")
        return value

    def validate(self, data):
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError(
                {"confirm_password": "Les mots de passe ne correspondent pas."}
            )
        try:
            validate_password(data["new_password"])
        except DjangoValidationError as exc:
            raise serializers.ValidationError({"new_password": list(exc.messages)}) from exc
        return data
