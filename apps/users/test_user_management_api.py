"""
=============================================================================
 apps/users/test_user_management_api.py
 Flux : CRUD des comptes (Jalon 6, réservé à l'admin), unicité du nom
 d'utilisateur (y compris après suppression logique), garde-fous sur le
 dernier compte admin actif et sur son propre compte.
=============================================================================
"""

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

User = get_user_model()


class UserManagementApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="test_admin", password="x", role=User.Role.ADMIN)
        self.magasinier = User.objects.create_user(username="test_mag", password="x", role=User.Role.MAGASINIER)
        self.lecteur = User.objects.create_user(username="test_lec", password="x", role=User.Role.LECTURE)

    def _connecte(self, user):
        self.client.force_authenticate(user=user)

    def test_reservee_a_admin(self):
        for user in (self.magasinier, self.lecteur):
            self._connecte(user)
            response = self.client.get("/api/v1/users/")
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, user.username)

    def test_lecture_sans_authentification_refusee(self):
        response = self.client.get("/api/v1/users/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_liste_ouverte_a_admin(self):
        self._connecte(self.admin)
        response = self.client.get("/api/v1/users/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["count"], 3)

    def test_creation(self):
        self._connecte(self.admin)
        response = self.client.post(
            "/api/v1/users/",
            {"username": "nouveau", "password": "MotDePasseInitial123!", "role": "MAGASINIER"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["role"], "MAGASINIER")
        self.assertNotIn("password", response.data)

        nouveau = User.objects.get(username="nouveau")
        self.assertTrue(nouveau.check_password("MotDePasseInitial123!"))

    def test_creation_mot_de_passe_trop_faible_est_rejetee(self):
        self._connecte(self.admin)
        response = self.client.post(
            "/api/v1/users/", {"username": "faible", "password": "123", "role": "LECTURE"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(User.objects.filter(username="faible").exists())

    def test_nom_utilisateur_deja_pris_est_rejete(self):
        self._connecte(self.admin)
        response = self.client.post(
            "/api/v1/users/", {"username": "test_mag", "password": "MotDePasseInitial123!", "role": "LECTURE"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_nom_utilisateur_reutilise_apres_suppression_logique_est_rejete(self):
        """Même bug que celui rencontré et corrigé sur fournisseurs/clients (Jalon 6+) :
        `username` est unique en base sur toutes les lignes, supprimées incluses."""
        self._connecte(self.admin)
        self.client.delete(f"/api/v1/users/{self.magasinier.pk}/")
        response = self.client.post(
            "/api/v1/users/", {"username": "test_mag", "password": "MotDePasseInitial123!", "role": "LECTURE"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_modification_du_role(self):
        self._connecte(self.admin)
        response = self.client.patch(f"/api/v1/users/{self.lecteur.pk}/", {"role": "MAGASINIER"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.lecteur.refresh_from_db()
        self.assertEqual(self.lecteur.role, User.Role.MAGASINIER)

    def test_desactivation(self):
        self._connecte(self.admin)
        response = self.client.patch(f"/api/v1/users/{self.magasinier.pk}/", {"is_active": False})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.magasinier.refresh_from_db()
        self.assertFalse(self.magasinier.is_active)

    def test_suppression_est_logique(self):
        self._connecte(self.admin)
        response = self.client.delete(f"/api/v1/users/{self.lecteur.pk}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(User.objects.filter(pk=self.lecteur.pk).exists())
        self.assertTrue(User.all_objects.filter(pk=self.lecteur.pk).exists())

    def test_ne_peut_pas_supprimer_son_propre_compte(self):
        self._connecte(self.admin)
        response = self.client.delete(f"/api/v1/users/{self.admin.pk}/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(User.objects.filter(pk=self.admin.pk).exists())

    def test_ne_peut_pas_retirer_son_propre_role_admin(self):
        autre_admin = User.objects.create_user(username="test_admin2", password="x", role=User.Role.ADMIN)
        self._connecte(self.admin)
        response = self.client.patch(f"/api/v1/users/{self.admin.pk}/", {"role": "LECTURE"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.Role.ADMIN)
        # l'autre admin n'est pas concerné, juste créé pour prouver que ce
        # n'est pas la garde "dernier admin" qui a bloqué ici
        self.assertTrue(autre_admin.est_admin)

    def test_ne_peut_pas_retirer_le_dernier_admin_actif(self):
        """Vérifié au niveau du service, pas via l'API : la garde « dernier
        admin » est distincte de la garde « pas son propre rôle » (déjà
        testée ci-dessus) — avec un seul admin en base (self.admin, posé par
        setUp), il n'existe justement aucun AUTRE admin qui pourrait passer
        la permission IsAdmin de l'API pour déclencher ce cas précis."""
        from django.core.exceptions import ValidationError

        from apps.users.services import UserService

        service = UserService()
        with self.assertRaises(ValidationError):
            service.modifier(self.admin, {"role": User.Role.LECTURE}, self.magasinier)
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.role, User.Role.ADMIN)

    def test_peut_retirer_un_admin_si_un_autre_reste(self):
        second_admin = User.objects.create_user(username="test_admin3", password="x", role=User.Role.ADMIN)
        self._connecte(second_admin)
        response = self.client.patch(f"/api/v1/users/{self.admin.pk}/", {"role": "LECTURE"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_recherche_et_filtre_par_role(self):
        self._connecte(self.admin)
        response = self.client.get("/api/v1/users/?role=MAGASINIER")
        self.assertEqual(response.data["count"], 1)
        response = self.client.get("/api/v1/users/?search=test_lec")
        self.assertEqual(response.data["count"], 1)
