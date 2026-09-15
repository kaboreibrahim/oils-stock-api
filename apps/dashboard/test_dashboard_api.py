"""
=============================================================================
 apps/dashboard/test_dashboard_api.py
 Un fichier, une classe par rapport (même convention que le reste du
 projet) — fixtures réelles (UniteStock/MouvementStock), pas de mock.
=============================================================================
"""

import datetime
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from apps.fournisseurs.models import Fournisseur
from apps.stock.models import MouvementStock, StatutStock, TypeArticle, TypeMouvement, UniteStock

User = get_user_model()


def _il_y_a(jours: int) -> "datetime.datetime":
    return timezone.now() - timedelta(days=jours)


def _mois_moins(offset: int) -> tuple[int, int]:
    """(année, mois) `offset` mois avant aujourd'hui — jour fixé à 15 pour
    éviter tout souci de fin de mois."""
    aujourdhui = date.today()
    m, annee = aujourdhui.month - offset, aujourdhui.year
    while m <= 0:
        m += 12
        annee -= 1
    return annee, m


def _mouvement_le_mois(offset: int, *, unite, type_mouvement=TypeMouvement.SORTIE) -> MouvementStock:
    annee, mois = _mois_moins(offset)
    dt = timezone.make_aware(datetime.datetime(annee, mois, 15, 12, 0))
    return MouvementStock.objects.create(unite_stock=unite, type_mouvement=type_mouvement, date_mouvement=dt)


class DashboardApiTestsBase(APITestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username="dash_admin", password="x", role=User.Role.ADMIN)
        self.magasinier = User.objects.create_user(username="dash_mag", password="x", role=User.Role.MAGASINIER)
        self.lecteur = User.objects.create_user(username="dash_lec", password="x", role=User.Role.LECTURE)
        self.client.force_authenticate(user=self.admin)

    def _creer_unite(self, fournisseur, type_article=TypeArticle.FLEXITANK, *, jours_entree=0, statut=StatutStock.EN_STOCK, numero_serie=None):
        return UniteStock.objects.create(
            numero_serie=numero_serie or f"SN-{UniteStock.objects.count() + 1}",
            type_article=type_article, fournisseur=fournisseur, statut=statut,
            date_entree=date.today() - timedelta(days=jours_entree),
        )


class StockDormantApiTests(DashboardApiTestsBase):
    def setUp(self):
        super().setUp()
        self.fournisseur = Fournisseur.objects.create(code="DORM1", nom="Dormant Un")

    def test_lecture_ouverte_a_tous_les_roles(self):
        for user in (self.admin, self.magasinier, self.lecteur):
            self.client.force_authenticate(user=user)
            response = self.client.get("/api/v1/dashboard/stock-dormant/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, user.username)

    def test_unite_ancienne_sans_sortie_est_incluse_via_date_entree(self):
        unite = self._creer_unite(self.fournisseur, jours_entree=200)
        response = self.client.get("/api/v1/dashboard/stock-dormant/?seuil_jours=90")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        resultat = next(r for r in response.data["results"] if r["id"] == str(unite.id))
        self.assertEqual(resultat["source_date"], "ENTREE")
        self.assertEqual(resultat["date_reference"], (date.today() - timedelta(days=200)).isoformat())
        self.assertGreaterEqual(resultat["jours_ecoules"], 200)

    def test_unite_avec_sortie_recente_est_exclue(self):
        unite = self._creer_unite(self.fournisseur, jours_entree=200)
        MouvementStock.objects.create(unite_stock=unite, type_mouvement=TypeMouvement.SORTIE, date_mouvement=_il_y_a(5))
        response = self.client.get("/api/v1/dashboard/stock-dormant/?seuil_jours=90")
        ids = [r["id"] for r in response.data["results"]]
        self.assertNotIn(str(unite.id), ids)

    def test_unite_avec_derniere_sortie_ancienne_est_incluse_via_derniere_sortie(self):
        unite = self._creer_unite(self.fournisseur, jours_entree=200)
        MouvementStock.objects.create(unite_stock=unite, type_mouvement=TypeMouvement.SORTIE, date_mouvement=_il_y_a(150))
        response = self.client.get("/api/v1/dashboard/stock-dormant/?seuil_jours=90")
        resultat = next(r for r in response.data["results"] if r["id"] == str(unite.id))
        self.assertEqual(resultat["source_date"], "DERNIERE_SORTIE")
        self.assertEqual(resultat["date_reference"], (date.today() - timedelta(days=150)).isoformat())

    def test_unite_recente_est_exclue(self):
        unite = self._creer_unite(self.fournisseur, jours_entree=10)
        response = self.client.get("/api/v1/dashboard/stock-dormant/?seuil_jours=90")
        ids = [r["id"] for r in response.data["results"]]
        self.assertNotIn(str(unite.id), ids)

    def test_valeur_immobilisee_null_si_cout_non_configure(self):
        unite = self._creer_unite(self.fournisseur, type_article=TypeArticle.HEATING_PAD, jours_entree=200)
        response = self.client.get("/api/v1/dashboard/stock-dormant/?seuil_jours=90")
        resultat = next(r for r in response.data["results"] if r["id"] == str(unite.id))
        self.assertIsNone(resultat["valeur_immobilisee"])

    def test_valeur_immobilisee_calculee_si_cout_configure(self):
        self.fournisseur.cout_unitaire_flexitank = "12.50"
        self.fournisseur.save()
        unite = self._creer_unite(self.fournisseur, type_article=TypeArticle.FLEXITANK, jours_entree=200)
        response = self.client.get("/api/v1/dashboard/stock-dormant/?seuil_jours=90")
        resultat = next(r for r in response.data["results"] if r["id"] == str(unite.id))
        self.assertEqual(resultat["valeur_immobilisee"], "12.50")

    def test_seuil_jours_non_numerique_est_rejete(self):
        response = self.client.get("/api/v1/dashboard/stock-dormant/?seuil_jours=abc")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_seuil_jours_negatif_est_rejete(self):
        response = self.client.get("/api/v1/dashboard/stock-dormant/?seuil_jours=-5")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class SeuilsReapproApiTests(DashboardApiTestsBase):
    def test_lecture_ouverte_a_tous_les_roles(self):
        for user in (self.admin, self.magasinier, self.lecteur):
            self.client.force_authenticate(user=user)
            response = self.client.get("/api/v1/dashboard/seuils-reappro/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, user.username)

    def test_seuil_manuel_prioritaire_meme_avec_delai_et_historique(self):
        fournisseur = Fournisseur.objects.create(
            code="SR1", nom="SR Un", seuil_reappro_flexitank=5,
            delai_livraison_jours=30, stock_securite_flexitank=99,
        )
        unite = self._creer_unite(fournisseur, TypeArticle.FLEXITANK)
        MouvementStock.objects.create(unite_stock=unite, type_mouvement=TypeMouvement.SORTIE, date_mouvement=_il_y_a(10))
        response = self.client.get("/api/v1/dashboard/seuils-reappro/")
        ligne = next(
            r for r in response.data if r["fournisseur"]["code"] == "SR1" and r["type_article"] == "FLEXITANK"
        )
        self.assertEqual(ligne["seuil"], 5)
        self.assertEqual(ligne["source_seuil"], "MANUEL")

    def test_seuil_calcule_quand_delai_et_historique_disponibles(self):
        fournisseur = Fournisseur.objects.create(
            code="SR2", nom="SR Deux", delai_livraison_jours=30, stock_securite_flexitank=4,
        )
        unite = self._creer_unite(fournisseur, TypeArticle.FLEXITANK)
        # Sortie ancienne (hors fenêtre de 90j) : historique présent, mais
        # consommation récente nulle -> seuil = stock_securite seul.
        MouvementStock.objects.create(unite_stock=unite, type_mouvement=TypeMouvement.SORTIE, date_mouvement=_il_y_a(200))
        response = self.client.get("/api/v1/dashboard/seuils-reappro/")
        ligne = next(
            r for r in response.data if r["fournisseur"]["code"] == "SR2" and r["type_article"] == "FLEXITANK"
        )
        self.assertEqual(ligne["seuil"], 4)
        self.assertEqual(ligne["source_seuil"], "CALCULE")

    def test_pas_de_seuil_si_delai_absent(self):
        fournisseur = Fournisseur.objects.create(code="SR3", nom="SR Trois")
        unite = self._creer_unite(fournisseur, TypeArticle.FLEXITANK)
        MouvementStock.objects.create(unite_stock=unite, type_mouvement=TypeMouvement.SORTIE, date_mouvement=_il_y_a(10))
        response = self.client.get("/api/v1/dashboard/seuils-reappro/")
        ligne = next(
            r for r in response.data if r["fournisseur"]["code"] == "SR3" and r["type_article"] == "FLEXITANK"
        )
        self.assertIsNone(ligne["seuil"])
        self.assertIsNone(ligne["source_seuil"])
        self.assertFalse(ligne["en_alerte"])

    def test_pas_de_seuil_si_aucun_historique_de_sortie(self):
        fournisseur = Fournisseur.objects.create(code="SR4", nom="SR Quatre", delai_livraison_jours=15)
        self._creer_unite(fournisseur, TypeArticle.FLEXITANK)  # jamais sortie
        response = self.client.get("/api/v1/dashboard/seuils-reappro/")
        ligne = next(
            r for r in response.data if r["fournisseur"]["code"] == "SR4" and r["type_article"] == "FLEXITANK"
        )
        self.assertIsNone(ligne["seuil"])

    def test_en_alerte_quand_stock_actuel_sous_le_seuil(self):
        fournisseur = Fournisseur.objects.create(code="SR5", nom="SR Cinq", seuil_reappro_flexitank=3)
        self._creer_unite(fournisseur, TypeArticle.FLEXITANK)  # 1 unité en stock <= seuil 3
        response = self.client.get("/api/v1/dashboard/seuils-reappro/")
        ligne = next(
            r for r in response.data if r["fournisseur"]["code"] == "SR5" and r["type_article"] == "FLEXITANK"
        )
        self.assertTrue(ligne["en_alerte"])


class SortiesMensuellesApiTests(DashboardApiTestsBase):
    def test_lecture_ouverte_a_tous_les_roles(self):
        for user in (self.admin, self.magasinier, self.lecteur):
            self.client.force_authenticate(user=user)
            response = self.client.get("/api/v1/dashboard/sorties-mensuelles/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, user.username)

    def test_repartition_par_mois_et_moyenne_mobile(self):
        fournisseur = Fournisseur.objects.create(code="SM1", nom="SM Un")
        unite = self._creer_unite(fournisseur, TypeArticle.FLEXITANK)
        unite_hp = self._creer_unite(fournisseur, TypeArticle.HEATING_PAD)

        # Mois courant : 3 sorties Flexitank, 1 Heating pad.
        for _ in range(3):
            _mouvement_le_mois(0, unite=unite)
        _mouvement_le_mois(0, unite=unite_hp)
        # Mois -1 : 1 sortie Flexitank.
        _mouvement_le_mois(1, unite=unite)
        # Mois -2 : 2 sorties Flexitank.
        for _ in range(2):
            _mouvement_le_mois(2, unite=unite)

        response = self.client.get("/api/v1/dashboard/sorties-mensuelles/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.data
        self.assertEqual(len(data["mois"]), 12)
        self.assertEqual(data["flexitank"][-1], 3)
        self.assertEqual(data["flexitank"][-2], 1)
        self.assertEqual(data["flexitank"][-3], 2)
        self.assertEqual(data["heating_pad"][-1], 1)

        # Moyenne mobile : null sur les 2 premiers points de la série, puis calculée.
        self.assertIsNone(data["flexitank_moyenne_mobile"][0])
        self.assertIsNone(data["flexitank_moyenne_mobile"][1])
        self.assertAlmostEqual(data["flexitank_moyenne_mobile"][-1], (2 + 1 + 3) / 3)
        self.assertAlmostEqual(data["heating_pad_moyenne_mobile"][-1], (0 + 0 + 1) / 3)


class PrevisionsApiTests(DashboardApiTestsBase):
    def test_lecture_ouverte_a_tous_les_roles(self):
        for user in (self.admin, self.magasinier, self.lecteur):
            self.client.force_authenticate(user=user)
            response = self.client.get("/api/v1/dashboard/previsions/")
            self.assertEqual(response.status_code, status.HTTP_200_OK, user.username)

    def test_pas_de_projection_sans_consommation_recente(self):
        fournisseur = Fournisseur.objects.create(code="PR1", nom="PR Un", seuil_reappro_flexitank=5)
        self._creer_unite(fournisseur, TypeArticle.FLEXITANK)  # aucune sortie du tout
        response = self.client.get("/api/v1/dashboard/previsions/")
        ligne = next(
            r for r in response.data if r["fournisseur"]["code"] == "PR1" and r["type_article"] == "FLEXITANK"
        )
        self.assertIsNone(ligne["jours_avant_rupture"])
        self.assertIsNone(ligne["date_commande_recommandee"])

    def test_commande_recommandee_aujourdhui_si_deja_sous_le_seuil(self):
        fournisseur = Fournisseur.objects.create(code="PR2", nom="PR Deux", seuil_reappro_flexitank=5)
        unites = [self._creer_unite(fournisseur, TypeArticle.FLEXITANK) for _ in range(2)]  # stock 2 <= seuil 5
        # Une sortie récente pour avoir une consommation > 0 (une 3e unité, déjà sortie).
        unite_sortie = self._creer_unite(fournisseur, TypeArticle.FLEXITANK, statut=StatutStock.SORTIE)
        MouvementStock.objects.create(unite_stock=unite_sortie, type_mouvement=TypeMouvement.SORTIE, date_mouvement=_il_y_a(10))

        response = self.client.get("/api/v1/dashboard/previsions/")
        ligne = next(
            r for r in response.data if r["fournisseur"]["code"] == "PR2" and r["type_article"] == "FLEXITANK"
        )
        self.assertTrue(ligne["en_alerte"])
        self.assertIsNotNone(ligne["jours_avant_rupture"])
        self.assertEqual(ligne["date_commande_recommandee"], date.today().isoformat())

    def test_tri_ascendant_par_jours_avant_rupture_nulls_en_dernier(self):
        sans_conso = Fournisseur.objects.create(code="PR3", nom="PR Trois", seuil_reappro_flexitank=5)
        self._creer_unite(sans_conso, TypeArticle.FLEXITANK)  # jamais sortie -> jours_avant_rupture=None

        avec_conso = Fournisseur.objects.create(code="PR4", nom="PR Quatre", seuil_reappro_flexitank=1)
        unite = self._creer_unite(avec_conso, TypeArticle.FLEXITANK)
        MouvementStock.objects.create(unite_stock=unite, type_mouvement=TypeMouvement.SORTIE, date_mouvement=_il_y_a(10))

        response = self.client.get("/api/v1/dashboard/previsions/")
        jours = [r["jours_avant_rupture"] for r in response.data]
        # Toutes les valeurs non nulles doivent être triées avant tous les None.
        premiere_position_nulle = next((i for i, j in enumerate(jours) if j is None), len(jours))
        self.assertTrue(all(j is not None for j in jours[:premiere_position_nulle]))
        non_nulles = [j for j in jours if j is not None]
        self.assertEqual(non_nulles, sorted(non_nulles))
