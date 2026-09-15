"""
=============================================================================
 apps/users/test_password_reset_api.py
 Flux : demande de code par e-mail (réponse générique), confirmation avec
 code + nouveau mot de passe, expiration, usage unique, limite de tentatives,
 révocation des sessions existantes après réinitialisation.

 Django bascule automatiquement l'EMAIL_BACKEND sur un backend en mémoire
 pendant les tests (jamais le vrai SMTP) — les e-mails envoyés sont
 consultables dans django.core.mail.outbox.
=============================================================================
"""

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import PasswordResetCode

User = get_user_model()


class PasswordResetApiTests(APITestCase):
    def setUp(self):
        # Le throttling DRF vit dans le cache Django, pas dans la base — il
        # survit d'un test à l'autre si on ne le vide pas explicitement.
        cache.clear()
        self.user = User.objects.create_user(
            username="test_reset", email="reset@example.com", password="AncienMotDePasse123!",
        )

    def _demander(self, email="reset@example.com"):
        return self.client.post("/api/v1/auth/password/reset/", {"email": email})

    def _dernier_code_en_clair(self) -> str:
        """Récupère le code depuis l'e-mail envoyé (le seul endroit où il est en clair)."""
        corps = mail.outbox[-1].body
        return next(mot for mot in corps.split() if mot.isdigit() and len(mot) == 6)

    def test_demande_envoie_un_email_avec_un_code_a_6_chiffres(self):
        response = self._demander()
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["reset@example.com"])
        code = self._dernier_code_en_clair()
        self.assertEqual(len(code), 6)
        self.assertTrue(PasswordResetCode.objects.filter(utilisateur=self.user).exists())

    def test_demande_pour_email_inconnu_renvoie_la_meme_reponse_generique(self):
        response_connu = self._demander("reset@example.com")
        response_inconnu = self._demander("personne@example.com")
        self.assertEqual(response_connu.status_code, response_inconnu.status_code)
        self.assertEqual(response_connu.data, response_inconnu.data)
        # aucun e-mail envoyé pour le compte inexistant
        self.assertEqual(len(mail.outbox), 1)

    def test_confirmation_reussie_change_le_mot_de_passe(self):
        self._demander()
        code = self._dernier_code_en_clair()
        response = self.client.post(
            "/api/v1/auth/password/reset/confirm/",
            {
                "email": "reset@example.com",
                "code": code,
                "new_password": "NouveauMotDePasse123!",
                "confirm_password": "NouveauMotDePasse123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("NouveauMotDePasse123!"))

        connexion = self.client.post(
            "/api/v1/auth/token/",
            {"username": "test_reset", "password": "NouveauMotDePasse123!"},
        )
        self.assertEqual(connexion.status_code, status.HTTP_200_OK)

    def test_code_deja_utilise_est_rejete(self):
        self._demander()
        code = self._dernier_code_en_clair()
        payload = {
            "email": "reset@example.com",
            "code": code,
            "new_password": "NouveauMotDePasse123!",
            "confirm_password": "NouveauMotDePasse123!",
        }
        premiere = self.client.post("/api/v1/auth/password/reset/confirm/", payload)
        self.assertEqual(premiere.status_code, status.HTTP_200_OK)

        rejeu = self.client.post("/api/v1/auth/password/reset/confirm/", payload)
        self.assertEqual(rejeu.status_code, status.HTTP_400_BAD_REQUEST)

    def test_code_incorrect_est_rejete(self):
        self._demander()
        response = self.client.post(
            "/api/v1/auth/password/reset/confirm/",
            {
                "email": "reset@example.com",
                "code": "000000",
                "new_password": "NouveauMotDePasse123!",
                "confirm_password": "NouveauMotDePasse123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_code_expire_est_rejete(self):
        self._demander()
        entree = PasswordResetCode.objects.get(utilisateur=self.user)
        entree.date_expiration = timezone.now() - timezone.timedelta(seconds=1)
        entree.save()
        code = self._dernier_code_en_clair()

        response = self.client.post(
            "/api/v1/auth/password/reset/confirm/",
            {
                "email": "reset@example.com",
                "code": code,
                "new_password": "NouveauMotDePasse123!",
                "confirm_password": "NouveauMotDePasse123!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_mots_de_passe_differents_sont_rejetes(self):
        self._demander()
        code = self._dernier_code_en_clair()
        response = self.client.post(
            "/api/v1/auth/password/reset/confirm/",
            {
                "email": "reset@example.com",
                "code": code,
                "new_password": "NouveauMotDePasse123!",
                "confirm_password": "AutreChose456!",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cinq_tentatives_invalident_le_code_meme_correct_ensuite(self):
        self._demander()
        code = self._dernier_code_en_clair()
        mauvaise_requete = {
            "email": "reset@example.com",
            "code": "000000",
            "new_password": "NouveauMotDePasse123!",
            "confirm_password": "NouveauMotDePasse123!",
        }
        for _ in range(5):
            self.client.post("/api/v1/auth/password/reset/confirm/", mauvaise_requete)

        bonne_requete = dict(mauvaise_requete, code=code)
        response = self.client.post("/api/v1/auth/password/reset/confirm/", bonne_requete)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reinitialisation_revoque_les_sessions_existantes(self):
        connexion = self.client.post(
            "/api/v1/auth/token/",
            {"username": "test_reset", "password": "AncienMotDePasse123!"},
        )
        refresh = connexion.data["refresh"]
        self.assertEqual(OutstandingToken.objects.filter(user=self.user).count(), 1)

        self._demander()
        code = self._dernier_code_en_clair()
        self.client.post(
            "/api/v1/auth/password/reset/confirm/",
            {
                "email": "reset@example.com",
                "code": code,
                "new_password": "NouveauMotDePasse123!",
                "confirm_password": "NouveauMotDePasse123!",
            },
        )

        # le refresh obtenu avant la réinitialisation ne doit plus fonctionner
        rejeu = self.client.post("/api/v1/auth/token/refresh/", {"refresh": refresh})
        self.assertEqual(rejeu.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertTrue(BlacklistedToken.objects.filter(token__user=self.user).exists())
