"""
=============================================================================
 apps/common/tests.py
=============================================================================
"""

from django.contrib.auth import get_user_model
from django.test import RequestFactory, TestCase

from .idempotence import executer_avec_idempotence
from .models import HistoriqueAction, IdempotencyRecord
from .services import HistoriqueActionService

User = get_user_model()


class HistoriqueActionServiceTests(TestCase):
    def setUp(self):
        self.utilisateur = User.objects.create_user(username="test_audit", password="x")
        self.service = HistoriqueActionService()

    def test_enregistrer_cree_une_ligne_historique(self):
        entree = self.service.enregistrer(
            utilisateur=self.utilisateur,
            action=HistoriqueAction.Action.CREATION,
            app="fournisseurs",
            objet_type="Fournisseur",
            objet_id="123",
            resume="Création du fournisseur TEST",
        )
        self.assertEqual(HistoriqueAction.objects.count(), 1)
        self.assertEqual(entree.utilisateur, self.utilisateur)
        self.assertEqual(entree.app, "fournisseurs")

    def test_enregistrer_sans_utilisateur_authentifie_ne_leve_pas_erreur(self):
        from django.contrib.auth.models import AnonymousUser

        entree = self.service.enregistrer(
            utilisateur=AnonymousUser(),
            action=HistoriqueAction.Action.CREATION,
            app="fournisseurs",
            objet_type="Fournisseur",
            objet_id="123",
        )
        self.assertIsNone(entree.utilisateur)


class ExecuterAvecIdempotenceTests(TestCase):
    def setUp(self):
        self.utilisateur = User.objects.create_user(username="test_idem_unit", password="x")
        self.factory = RequestFactory()

    def _requete(self, methode="POST", chemin="/api/v1/sorties/"):
        requete = getattr(self.factory, methode.lower())(chemin)
        requete.user = self.utilisateur
        return requete

    def test_sans_cle_executer_est_appele_a_chaque_fois(self):
        requete = self._requete()
        compteur = {"n": 0}

        def executer():
            compteur["n"] += 1
            return 201, {"n": compteur["n"]}

        executer_avec_idempotence(requete, None, executer)
        executer_avec_idempotence(requete, None, executer)
        self.assertEqual(compteur["n"], 2)
        self.assertEqual(IdempotencyRecord.objects.count(), 0)

    def test_avec_cle_le_rejeu_ne_reexecute_pas(self):
        requete = self._requete()
        compteur = {"n": 0}

        def executer():
            compteur["n"] += 1
            return 201, {"n": compteur["n"]}

        statut1, corps1 = executer_avec_idempotence(requete, "cle-unitaire-1", executer)
        statut2, corps2 = executer_avec_idempotence(requete, "cle-unitaire-1", executer)

        self.assertEqual(compteur["n"], 1)  # executer() n'a tourné qu'une fois
        self.assertEqual((statut1, corps1), (statut2, corps2))
        self.assertEqual(IdempotencyRecord.objects.count(), 1)

    def test_meme_cle_chemin_different_leve_validation_error(self):
        from django.core.exceptions import ValidationError

        requete1 = self._requete(chemin="/api/v1/sorties/")
        requete2 = self._requete(chemin="/api/v1/clients/")
        executer_avec_idempotence(requete1, "cle-partagee-unit", lambda: (201, {}))
        with self.assertRaises(ValidationError):
            executer_avec_idempotence(requete2, "cle-partagee-unit", lambda: (201, {}))
