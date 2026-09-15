"""
=============================================================================
 apps/fournisseurs/test_fournisseur_api.py
 Flux : lecture ouverte à tous les rôles, écriture réservée à l'admin,
 unicité de code, suppression logique.
=============================================================================
"""

from datetime import date

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from apps.stock.models import StatutStock, TypeArticle, UniteStock

from .models import Fournisseur

User = get_user_model()


class FournisseurApiTests(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="test_admin", password="x", role=User.Role.ADMIN)
        self.magasinier = User.objects.create_user(username="test_mag", password="x", role=User.Role.MAGASINIER)
        self.lecteur = User.objects.create_user(username="test_lec", password="x", role=User.Role.LECTURE)
        self.fournisseur = Fournisseur.objects.create(code="EBONT", nom="Ebont")

    def _connecte(self, user):
        self.client.force_authenticate(user=user)

    def test_lecture_ouverte_a_tous_les_roles(self):
        for user in (self.admin, self.magasinier, self.lecteur):
            self._connecte(user)
            response = self.client.get("/api/v1/fournisseurs/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, user.username)

    def test_lecture_refusee_sans_authentification(self):
        response = self.client.get("/api/v1/fournisseurs/")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_creation_reservee_a_admin(self):
        payload = {"code": "DHL", "nom": "DHL"}
        for user in (self.lecteur, self.magasinier):
            self._connecte(user)
            response = self.client.post("/api/v1/fournisseurs/", payload)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, user.username)

        self._connecte(self.admin)
        response = self.client.post("/api/v1/fournisseurs/", payload)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["code"], "DHL")

    def test_code_normalise_en_majuscules(self):
        self._connecte(self.admin)
        response = self.client.post("/api/v1/fournisseurs/", {"code": "laf", "nom": "LAF"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["code"], "LAF")

    def test_code_deja_utilise_est_rejete(self):
        self._connecte(self.admin)
        response = self.client.post("/api/v1/fournisseurs/", {"code": "ebont", "nom": "Doublon"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_suppression_est_logique(self):
        self._connecte(self.admin)
        response = self.client.delete(f"/api/v1/fournisseurs/{self.fournisseur.pk}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertFalse(Fournisseur.objects.filter(pk=self.fournisseur.pk).exists())
        self.assertTrue(Fournisseur.all_objects.filter(pk=self.fournisseur.pk).exists())

    def test_suppression_reservee_a_admin(self):
        self._connecte(self.magasinier)
        response = self.client.delete(f"/api/v1/fournisseurs/{self.fournisseur.pk}/")
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_code_dun_fournisseur_supprime_reste_bloque_proprement(self):
        """Bug réel rencontré en testant l'écran de détail (Jalon 5+) : `code`
        est unique au niveau base sur TOUTES les lignes (supprimées incluses),
        mais l'ancienne vérification ne regardait que les lignes actives
        (`objects`) — recréer avec le même code après une suppression logique
        levait une IntegrityError brute (500) au lieu d'un 400 propre."""
        self._connecte(self.admin)
        self.client.delete(f"/api/v1/fournisseurs/{self.fournisseur.pk}/")
        response = self.client.post("/api/v1/fournisseurs/", {"code": "EBONT", "nom": "Rebond"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_meme_cle_idempotence_ne_cree_qu_un_fournisseur(self):
        """Phase 2 PWA — écriture hors-ligne : un rejeu (même Idempotency-Key)
        après une coupure réseau ne doit jamais créer un doublon."""
        self._connecte(self.admin)
        payload = {"code": "IDEMF", "nom": "Fournisseur idempotent"}
        r1 = self.client.post("/api/v1/fournisseurs/", payload, HTTP_IDEMPOTENCY_KEY="cle-fourn-1")
        r2 = self.client.post("/api/v1/fournisseurs/", payload, HTTP_IDEMPOTENCY_KEY="cle-fourn-1")
        self.assertEqual(r1.status_code, status.HTTP_201_CREATED, r1.data)
        self.assertEqual(r2.status_code, status.HTTP_201_CREATED, r2.data)
        self.assertEqual(r1.data["id"], r2.data["id"])
        self.assertEqual(Fournisseur.objects.filter(code="IDEMF").count(), 1)

    def test_meme_cle_idempotence_sur_modification_ne_reapplique_pas(self):
        self._connecte(self.admin)
        payload = {"pays": "Vietnam"}
        r1 = self.client.patch(f"/api/v1/fournisseurs/{self.fournisseur.pk}/", payload, HTTP_IDEMPOTENCY_KEY="cle-fourn-patch-1")
        r2 = self.client.patch(f"/api/v1/fournisseurs/{self.fournisseur.pk}/", payload, HTTP_IDEMPOTENCY_KEY="cle-fourn-patch-1")
        self.assertEqual(r1.status_code, status.HTTP_200_OK, r1.data)
        self.assertEqual(r2.status_code, status.HTTP_200_OK, r2.data)
        self.assertEqual(r1.data, r2.data)


class FournisseurRepartitionParTypeApiTests(APITestCase):
    """Compteurs nb_flexitanks/nb_heating_pads — répartition par type affichée
    sur la liste des fournisseurs (pas seulement la fiche détail)."""

    def setUp(self):
        self.lecteur = User.objects.create_user(username="test_lec2", password="x", role=User.Role.LECTURE)
        self.dhl = Fournisseur.objects.create(code="DHL", nom="DHL")
        UniteStock.objects.create(numero_serie="F1", type_article=TypeArticle.FLEXITANK, fournisseur=self.dhl, date_entree=date.today())
        UniteStock.objects.create(numero_serie="F2", type_article=TypeArticle.FLEXITANK, fournisseur=self.dhl, date_entree=date.today())
        UniteStock.objects.create(numero_serie="H1", type_article=TypeArticle.HEATING_PAD, fournisseur=self.dhl, date_entree=date.today())
        self.client.force_authenticate(user=self.lecteur)

    def test_liste_expose_la_repartition_par_type(self):
        response = self.client.get("/api/v1/fournisseurs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        resultat = next(f for f in response.data["results"] if f["code"] == "DHL")
        self.assertEqual(resultat["nb_flexitanks"], 2)
        self.assertEqual(resultat["nb_heating_pads"], 1)

    def test_detail_expose_aussi_la_repartition_par_type(self):
        response = self.client.get(f"/api/v1/fournisseurs/{self.dhl.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["nb_flexitanks"], 2)
        self.assertEqual(response.data["nb_heating_pads"], 1)

    def test_repartition_ne_compte_que_les_unites_en_stock(self):
        """Une unité SORTIE ne doit plus compter — la répartition sert de base
        à l'alerte de seuil de réapprovisionnement (unités actuellement
        disponibles), pas à un total historique."""
        UniteStock.objects.create(
            numero_serie="F3", type_article=TypeArticle.FLEXITANK, fournisseur=self.dhl,
            date_entree=date.today(), statut=StatutStock.SORTIE,
        )
        response = self.client.get(f"/api/v1/fournisseurs/{self.dhl.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["nb_flexitanks"], 2)  # toujours 2, pas 3

    def test_repartition_ne_compte_pas_les_unites_supprimees(self):
        """Bug réel : la relation inverse `unites_stock` passe par le manager
        de base, qui n'applique pas le filtre de suppression logique — une
        unité supprimée (mais encore statut=EN_STOCK en base) gonflait le
        compteur (DHL affichait 20 heating pads au lieu de 3)."""
        unite = UniteStock.objects.create(
            numero_serie="H_SUPPR", type_article=TypeArticle.HEATING_PAD, fournisseur=self.dhl,
            date_entree=date.today(), statut=StatutStock.EN_STOCK,
        )
        unite.delete()  # suppression logique — deleted_at renseigné, statut inchangé
        response = self.client.get(f"/api/v1/fournisseurs/{self.dhl.pk}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["nb_heating_pads"], 1)  # l'unité supprimée ne compte pas


class FournisseurSeuilReapproApiTests(APITestCase):
    """Seuil de réapprovisionnement par type (Flexitank/Heating pad) —
    précisable à la création ou modification d'un fournisseur."""

    def setUp(self):
        self.admin = User.objects.create_user(username="test_admin2", password="x", role=User.Role.ADMIN)
        self.client.force_authenticate(user=self.admin)

    def test_creation_avec_seuils(self):
        response = self.client.post(
            "/api/v1/fournisseurs/",
            {"code": "SEUIL1", "nom": "Seuil Un", "seuil_reappro_flexitank": 5, "seuil_reappro_heating_pad": 10},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["seuil_reappro_flexitank"], 5)
        self.assertEqual(response.data["seuil_reappro_heating_pad"], 10)

    def test_seuils_absents_par_defaut(self):
        response = self.client.post("/api/v1/fournisseurs/", {"code": "SEUIL2", "nom": "Seuil Deux"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNone(response.data["seuil_reappro_flexitank"])
        self.assertIsNone(response.data["seuil_reappro_heating_pad"])

    def test_seuil_negatif_est_rejete(self):
        response = self.client.post(
            "/api/v1/fournisseurs/", {"code": "SEUIL3", "nom": "Seuil Trois", "seuil_reappro_flexitank": -1},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_modification_du_seuil(self):
        fournisseur = Fournisseur.objects.create(code="SEUIL4", nom="Seuil Quatre")
        response = self.client.patch(f"/api/v1/fournisseurs/{fournisseur.pk}/", {"seuil_reappro_heating_pad": 3})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["seuil_reappro_heating_pad"], 3)
        self.assertIsNone(response.data["seuil_reappro_flexitank"])


class FournisseurReapproDynamiqueApiTests(APITestCase):
    """Champs du réapprovisionnement dynamique (délai, stock de sécurité,
    coût unitaire) — utilisés par apps.dashboard, précisables comme les
    seuils manuels à la création ou modification d'un fournisseur."""

    def setUp(self):
        self.admin = User.objects.create_user(username="test_admin3", password="x", role=User.Role.ADMIN)
        self.client.force_authenticate(user=self.admin)

    def test_creation_avec_les_cinq_champs(self):
        response = self.client.post(
            "/api/v1/fournisseurs/",
            {
                "code": "DYN1", "nom": "Dynamique Un",
                "delai_livraison_jours": 30,
                "stock_securite_flexitank": 2, "stock_securite_heating_pad": 4,
                "cout_unitaire_flexitank": "12.50", "cout_unitaire_heating_pad": "8.00",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["delai_livraison_jours"], 30)
        self.assertEqual(response.data["stock_securite_flexitank"], 2)
        self.assertEqual(response.data["stock_securite_heating_pad"], 4)
        self.assertEqual(response.data["cout_unitaire_flexitank"], "12.50")
        self.assertEqual(response.data["cout_unitaire_heating_pad"], "8.00")

    def test_champs_absents_par_defaut(self):
        response = self.client.post("/api/v1/fournisseurs/", {"code": "DYN2", "nom": "Dynamique Deux"})
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        for champ in (
            "delai_livraison_jours", "stock_securite_flexitank", "stock_securite_heating_pad",
            "cout_unitaire_flexitank", "cout_unitaire_heating_pad",
        ):
            self.assertIsNone(response.data[champ])

    def test_modification_des_champs(self):
        fournisseur = Fournisseur.objects.create(code="DYN3", nom="Dynamique Trois")
        response = self.client.patch(
            f"/api/v1/fournisseurs/{fournisseur.pk}/",
            {"delai_livraison_jours": 45, "cout_unitaire_flexitank": "15.00"},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["delai_livraison_jours"], 45)
        self.assertEqual(response.data["cout_unitaire_flexitank"], "15.00")

    def test_cout_negatif_est_rejete(self):
        response = self.client.post(
            "/api/v1/fournisseurs/", {"code": "DYN4", "nom": "Dynamique Quatre", "cout_unitaire_flexitank": "-1.00"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
