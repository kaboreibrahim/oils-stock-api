"""
=============================================================================
 apps/users/services.py
 Connexion + réinitialisation de mot de passe par code à 6 chiffres envoyé
 par e-mail. Aucun accès direct à l'ORM ici : tout passe par UserRepository /
 PasswordResetCodeRepository (ou l'API publique de Django/simplejwt, qui fait
 elle-même sa propre validation).
=============================================================================
"""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.hashers import check_password, make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.models import HistoriqueAction
from apps.common.services import HistoriqueActionService

from .models import User
from .repositories import PasswordResetCodeRepository, UserRepository

logger = logging.getLogger("apps.users")

CODE_TTL = timedelta(minutes=15)  # la limite de tentatives (5) vit sur PasswordResetCode.est_utilisable


class AuthService:
    """Connexion. La logique métier tient en une règle : un message générique,
    quelle que soit la cause de l'échec (mauvais mot de passe, compte inconnu,
    supprimé ou désactivé) — pour ne jamais révéler l'existence d'un compte."""

    def connecter(self, username: str, password: str) -> dict:
        utilisateur = authenticate(username=username, password=password)
        if utilisateur is None:
            raise ValidationError("Identifiants incorrects.")

        refresh = RefreshToken.for_user(utilisateur)
        return {"access": str(refresh.access_token), "refresh": str(refresh)}


class PasswordResetService:
    def __init__(
        self,
        user_repo: UserRepository | None = None,
        code_repo: PasswordResetCodeRepository | None = None,
        historique: HistoriqueActionService | None = None,
    ):
        self.user_repo = user_repo or UserRepository()
        self.code_repo = code_repo or PasswordResetCodeRepository()
        self.historique = historique or HistoriqueActionService()

    def demander(self, email: str) -> None:
        """Envoie un code par e-mail si un compte actif correspond.

        Ne lève jamais d'erreur et ne révèle jamais si l'e-mail existe — la
        vue renvoie toujours la même réponse générique, que le compte existe
        ou non (évite l'énumération de comptes).
        """
        utilisateur = self.user_repo.get_by_email(email)
        if utilisateur is None or not utilisateur.email:
            logger.info("Demande de réinitialisation pour un e-mail inconnu : %s", email)
            return

        code = f"{secrets.randbelow(1_000_000):06d}"
        self.code_repo.create(
            utilisateur=utilisateur,
            code_hache=make_password(code),
            date_expiration=timezone.now() + CODE_TTL,
        )
        self._envoyer_email(utilisateur, code)
        logger.info("Code de réinitialisation envoyé à %s", utilisateur.username)

    def confirmer(self, email: str, code: str, nouveau_mot_de_passe: str) -> None:
        utilisateur = self.user_repo.get_by_email(email)
        if utilisateur is None:
            raise ValidationError("Code invalide ou expiré.")

        entree = self.code_repo.get_dernier_code_valide(utilisateur)
        if entree is None or not entree.est_utilisable:
            raise ValidationError("Code invalide ou expiré.")

        if not check_password(code, entree.code_hache):
            entree.tentatives += 1
            self.code_repo.save(entree)
            raise ValidationError("Code invalide ou expiré.")

        try:
            validate_password(nouveau_mot_de_passe, user=utilisateur)
        except ValidationError as exc:
            raise ValidationError({"new_password": list(exc.messages)}) from exc

        utilisateur.set_password(nouveau_mot_de_passe)
        utilisateur.save(update_fields=["password"])

        entree.utilise_le = timezone.now()
        self.code_repo.save(entree)

        self._revoquer_toutes_les_sessions(utilisateur)

        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.MODIFICATION, app="users",
            objet_type="User", objet_id=utilisateur.id,
            resume="Mot de passe réinitialisé par code e-mail",
        )
        logger.info("Mot de passe réinitialisé pour %s", utilisateur.username)

    @staticmethod
    def _envoyer_email(utilisateur: User, code: str) -> None:
        sujet = "Réinitialisation de votre mot de passe — Oils of Africa Stock"
        message = (
            f"Bonjour {utilisateur.username},\n\n"
            f"Voici votre code de réinitialisation : {code}\n\n"
            "Ce code est valable 15 minutes et à usage unique.\n"
            "Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail."
        )
        try:
            send_mail(
                sujet, message,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
                recipient_list=[utilisateur.email],
                fail_silently=False,
            )
        except Exception:
            # Un échec d'envoi ne doit jamais remonter jusqu'au client — la
            # réponse reste générique. On journalise pour l'exploitation.
            logger.exception("Échec d'envoi du code de réinitialisation à %s", utilisateur.email)

    @staticmethod
    def _revoquer_toutes_les_sessions(utilisateur: User) -> None:
        """Blackliste tous les refresh tokens en circulation — un mot de passe
        changé (volontairement ou après compromission) invalide les sessions
        existantes."""
        from rest_framework_simplejwt.token_blacklist.models import (
            BlacklistedToken,
            OutstandingToken,
        )

        for token in OutstandingToken.objects.filter(user=utilisateur):
            BlacklistedToken.objects.get_or_create(token=token)


class UserService:
    """Gestion des comptes (Jalon 6, §09 « Gérer utilisateurs & rôles »,
    réservée à l'admin — voir apps.users.permissions/views). Le mot de passe
    ne se change jamais ici après la création : seulement via
    PasswordResetService (code par e-mail), pour ne pas dupliquer sa logique
    de validation."""

    def __init__(
        self,
        repo: UserRepository | None = None,
        historique: HistoriqueActionService | None = None,
    ):
        self.repo = repo or UserRepository()
        self.historique = historique or HistoriqueActionService()

    def lister(self):
        return self.repo.get_all()

    def obtenir(self, user_id) -> User:
        utilisateur = self.repo.get_by_id(user_id)
        if utilisateur is None:
            raise User.DoesNotExist("Utilisateur introuvable.")
        return utilisateur

    def creer(self, donnees: dict, createur) -> User:
        donnees = dict(donnees)
        username = donnees.pop("username")
        password = donnees.pop("password")
        if self.repo.get_by_username(username):
            raise ValidationError(f"Le nom d'utilisateur « {username} » existe déjà.")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise ValidationError({"password": list(exc.messages)}) from exc

        utilisateur = self.repo.create(username=username, password=password, **donnees)
        self.historique.enregistrer(
            utilisateur=createur, action=HistoriqueAction.Action.CREATION, app="users",
            objet_type="User", objet_id=utilisateur.id,
            resume=f"Création du compte {utilisateur.username} ({utilisateur.role})",
        )
        logger.info("Compte créé : %s (%s)", utilisateur.username, utilisateur.role)
        return utilisateur

    def modifier(self, utilisateur: User, donnees: dict, modificateur) -> User:
        donnees = dict(donnees)
        quitte_le_role_admin = "role" in donnees and donnees["role"] != User.Role.ADMIN
        va_etre_desactive = donnees.get("is_active") is False
        perd_ses_privileges = utilisateur.est_admin and (quitte_le_role_admin or va_etre_desactive)

        if utilisateur.pk == modificateur.pk and perd_ses_privileges:
            raise ValidationError("Vous ne pouvez pas retirer votre propre rôle admin ni vous désactiver vous-même.")
        if perd_ses_privileges and self.repo.compter_admins_actifs(exclure_id=utilisateur.pk) == 0:
            raise ValidationError("Impossible de retirer le dernier compte administrateur actif.")

        utilisateur = self.repo.update(utilisateur, **donnees)
        self.historique.enregistrer(
            utilisateur=modificateur, action=HistoriqueAction.Action.MODIFICATION, app="users",
            objet_type="User", objet_id=utilisateur.id,
            resume=f"Modification du compte {utilisateur.username}",
        )
        return utilisateur

    def supprimer(self, utilisateur: User, suppresseur) -> None:
        if utilisateur.pk == suppresseur.pk:
            raise ValidationError("Vous ne pouvez pas supprimer votre propre compte.")
        if utilisateur.est_admin and self.repo.compter_admins_actifs(exclure_id=utilisateur.pk) == 0:
            raise ValidationError("Impossible de supprimer le dernier compte administrateur actif.")

        username = utilisateur.username
        self.repo.delete(utilisateur)
        self.historique.enregistrer(
            utilisateur=suppresseur, action=HistoriqueAction.Action.SUPPRESSION, app="users",
            objet_type="User", objet_id=utilisateur.id,
            resume=f"Suppression du compte {username}",
        )
