"""
=============================================================================
 apps/users/test_auth_api.py
 Flux : connexion JWT, renouvellement, utilisateur courant, déconnexion
 (liste noire), blocage d'un compte supprimé.
=============================================================================
"""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class AuthApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="test_admin", password="motdepasse123", role=User.Role.ADMIN,
        )

    def test_connexion_reussie_retourne_les_deux_jetons(self):
        response = self.client.post(
            "/api/v1/auth/token/",
            {"username": "test_admin", "password": "motdepasse123"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)
        self.assertIn("refresh", response.data)

    def test_connexion_mot_de_passe_incorrect(self):
        response = self.client.post(
            "/api/v1/auth/token/",
            {"username": "test_admin", "password": "mauvais"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["detail"], "Identifiants incorrects.")

    def test_connexion_utilisateur_inconnu_meme_message_que_mot_de_passe_incorrect(self):
        """Le message ne doit jamais permettre de deviner si le compte existe."""
        response = self.client.post(
            "/api/v1/auth/token/",
            {"username": "n-existe-pas", "password": "peu-importe"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(response.data["detail"], "Identifiants incorrects.")

    def test_renouvellement_du_jeton(self):
        tokens = self.client.post(
            "/api/v1/auth/token/",
            {"username": "test_admin", "password": "motdepasse123"},
        ).data
        response = self.client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("access", response.data)

    def test_utilisateur_courant_renvoie_le_role(self):
        tokens = self.client.post(
            "/api/v1/auth/token/",
            {"username": "test_admin", "password": "motdepasse123"},
        ).data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")
        response = self.client.get("/api/v1/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["role"], "ADMIN")

    def test_utilisateur_courant_sans_jeton_est_refuse(self):
        response = self.client.get("/api/v1/auth/me/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_compte_supprime_ne_peut_plus_se_connecter(self):
        self.user.delete()  # suppression logique
        response = self.client.post(
            "/api/v1/auth/token/",
            {"username": "test_admin", "password": "motdepasse123"},
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_compte_restaure_peut_de_nouveau_se_connecter(self):
        self.user.delete()
        self.user.refresh_from_db()
        self.user.restore()
        response = self.client.post(
            "/api/v1/auth/token/",
            {"username": "test_admin", "password": "motdepasse123"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_deconnexion_revoque_le_refresh_token(self):
        tokens = self.client.post(
            "/api/v1/auth/token/",
            {"username": "test_admin", "password": "motdepasse123"},
        ).data
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {tokens['access']}")

        response = self.client.post("/api/v1/auth/logout/", {"refresh": tokens["refresh"]})
        self.assertEqual(response.status_code, status.HTTP_205_RESET_CONTENT)

        # le refresh révoqué ne peut plus servir à obtenir un nouvel access token
        self.client.credentials()  # retire le Bearer, pas nécessaire pour /token/refresh/
        replay = self.client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(replay.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_deconnexion_sans_authentification_est_refusee(self):
        response = self.client.post("/api/v1/auth/logout/", {"refresh": "peu-importe"})
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_renouvellement_blackliste_automatiquement_l_ancien_refresh(self):
        """BLACKLIST_AFTER_ROTATION : un refresh déjà échangé ne peut pas être rejoué."""
        tokens = self.client.post(
            "/api/v1/auth/token/",
            {"username": "test_admin", "password": "motdepasse123"},
        ).data
        first_refresh = self.client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(first_refresh.status_code, status.HTTP_200_OK)

        replay = self.client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
        self.assertEqual(replay.status_code, status.HTTP_401_UNAUTHORIZED)
