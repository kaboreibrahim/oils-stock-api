"""
=============================================================================
 apps/receptions/services.py
 Règles métier des réceptions. Aucun accès direct à l'ORM ici : tout passe
 par ReceptionRepository / LigneReceptionRepository (ce domaine),
 FournisseurRepository (apps.fournisseurs, pour la création à la volée en
 reprise) et UniteStockRepository / MouvementStockService (apps.stock, pour
 créer les unités et écrire le journal des mouvements).
=============================================================================
"""

import logging
from datetime import datetime, time

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.common.models import HistoriqueAction
from apps.common.services import HistoriqueActionService
from apps.fournisseurs.repositories import FournisseurRepository
from apps.notifications.services import NotificationService
from apps.stock.models import StatutStock, TypeMouvement
from apps.stock.repositories import UniteStockRepository
from apps.stock.services import MouvementStockService

from .extraction import OcrIndisponible, detecter_plage, extraire_pdf
from .models import (
    LigneReception,
    NatureReception,
    Reception,
    SourceLigneReception,
    StatutLigneReception,
    StatutReception,
)
from .repositories import LigneReceptionRepository, ReceptionRepository

logger = logging.getLogger("apps.receptions")

# Filet de sécurité contre une plage saisie par erreur (ex. bornes inversées
# en unités au lieu de milliers) — largement au-dessus d'un lot réel (le plus
# gros exemple connu, Ebont, fait 131 unités).
TAILLE_MAX_PLAGE = 2000

# Filet de sécurité contre une collision de référence concurrente (bascule
# d'année, tout premier enregistrement, ou deux tentatives de rejeu
# idempotent simultanées — voir _generer_reference()).
NB_TENTATIVES_REFERENCE = 3


class ReceptionService:
    def __init__(
        self,
        repo: ReceptionRepository | None = None,
        lignes: LigneReceptionRepository | None = None,
        fournisseurs: FournisseurRepository | None = None,
        unites: UniteStockRepository | None = None,
        mouvements: MouvementStockService | None = None,
        historique: HistoriqueActionService | None = None,
        notifications: NotificationService | None = None,
    ):
        self.repo = repo or ReceptionRepository()
        self.lignes = lignes or LigneReceptionRepository()
        self.fournisseurs = fournisseurs or FournisseurRepository()
        self.unites = unites or UniteStockRepository()
        self.mouvements = mouvements or MouvementStockService()
        self.historique = historique or HistoriqueActionService()
        self.notifications = notifications or NotificationService()

    # ── Lecture ──────────────────────────────────────────────────────────

    def lister(self):
        return self.repo.get_all()

    def obtenir(self, reception_id) -> Reception:
        reception = self.repo.get_by_id(reception_id)
        if reception is None:
            raise Reception.DoesNotExist("Réception introuvable.")
        return reception

    def lister_lignes(self, reception: Reception):
        return self.lignes.get_all_for_reception(reception)

    # ── En-tête ──────────────────────────────────────────────────────────

    def creer(self, donnees: dict, utilisateur) -> Reception:
        donnees = dict(donnees)
        nature = donnees.get("nature")

        if nature == NatureReception.REPRISE:
            # §09 du dossier de conception : la reprise (mise en service) est
            # réservée à l'administrateur, à la différence de l'arrivage/la
            # saisie courante (magasinier + admin).
            if not getattr(utilisateur, "est_admin", False):
                raise PermissionDenied("La reprise de l'existant est réservée aux administrateurs.")
            donnees["fournisseur"] = None
        elif not donnees.get("fournisseur"):
            raise ValidationError("Le fournisseur est obligatoire pour un arrivage ou une saisie.")

        if nature == NatureReception.ARRIVAGE and not donnees.get("fichier"):
            raise ValidationError("Le fichier PDF est obligatoire pour un arrivage.")
        if nature != NatureReception.ARRIVAGE:
            donnees.pop("fichier", None)

        reception = None
        for _ in range(NB_TENTATIVES_REFERENCE):
            try:
                with transaction.atomic():  # savepoint — isole une collision de référence concurrente
                    reference = self._generer_reference()
                    reception = self.repo.create(
                        reference=reference,
                        cree_par=utilisateur if getattr(utilisateur, "is_authenticated", False) else None,
                        **donnees,
                    )
                break
            except IntegrityError:
                reception = None
                continue
        if reception is None:
            raise ValidationError("Impossible de générer une référence de réception unique — veuillez réessayer.")
        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.CREATION, app="receptions",
            objet_type="Reception", objet_id=reception.id, resume=f"Création de la réception {reception.reference}",
        )
        logger.info("Réception créée : %s (%s)", reception.reference, nature)
        return reception

    def modifier(self, reception: Reception, donnees: dict, utilisateur) -> Reception:
        self._verifier_brouillon(reception, "modifier l'en-tête")
        reception = self.repo.update(reception, **donnees)
        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.MODIFICATION, app="receptions",
            objet_type="Reception", objet_id=reception.id, resume=f"Modification de la réception {reception.reference}",
        )
        return reception

    def supprimer(self, reception: Reception, utilisateur) -> None:
        self._verifier_brouillon(reception, "supprimer")
        reference = reception.reference
        self.repo.delete(reception)
        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.SUPPRESSION, app="receptions",
            objet_type="Reception", objet_id=reception.id, resume=f"Suppression de la réception {reference}",
        )

    # ── Lignes ───────────────────────────────────────────────────────────

    def ajouter_ligne(
        self, reception: Reception, *, numero_serie: str, type_article: str, utilisateur,
        fournisseur_id=None, fournisseur_code=None,
    ) -> LigneReception:
        self._verifier_brouillon(reception, "ajouter une unité")
        numero_serie = (numero_serie or "").strip()
        if not numero_serie:
            raise ValidationError("Le numéro de série est obligatoire.")

        ligne_fournisseur, effectif = self._resoudre_fournisseur_ligne(
            reception, fournisseur_id, fournisseur_code, utilisateur,
        )
        statut_ligne = self._statut_pour(reception, effectif, numero_serie)
        source = (
            SourceLigneReception.REPRISE if reception.nature == NatureReception.REPRISE
            else SourceLigneReception.MANUEL
        )

        ligne = self.lignes.create(
            reception=reception, numero_serie=numero_serie, fournisseur=ligne_fournisseur,
            type_article=type_article, statut_ligne=statut_ligne, source=source,
        )
        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.MODIFICATION, app="receptions",
            objet_type="Reception", objet_id=reception.id,
            resume=f"Ajout de {numero_serie} à la réception {reception.reference}",
        )
        return ligne

    def ajouter_plage(
        self, reception: Reception, *, prefixe: str, debut: int, fin: int, largeur: int | None,
        type_article: str, utilisateur, fournisseur_id=None, fournisseur_code=None,
    ) -> list[LigneReception]:
        self._verifier_brouillon(reception, "générer une plage")
        prefixe = (prefixe or "").strip()
        if debut is None or fin is None:
            raise ValidationError("Le numéro de début et le numéro de fin sont obligatoires.")
        if fin < debut:
            raise ValidationError("Le numéro de fin doit être supérieur ou égal au numéro de début.")
        total = fin - debut + 1
        if total > TAILLE_MAX_PLAGE:
            raise ValidationError(f"Plage trop large ({total} numéros, maximum {TAILLE_MAX_PLAGE}).")

        ligne_fournisseur, effectif = self._resoudre_fournisseur_ligne(
            reception, fournisseur_id, fournisseur_code, utilisateur,
        )
        largeur = largeur or len(str(fin))
        source = SourceLigneReception.PLAGE

        a_creer = [
            LigneReception(
                reception=reception, numero_serie=f"{prefixe}{str(i).zfill(largeur)}",
                fournisseur=ligne_fournisseur, type_article=type_article,
                statut_ligne=self._statut_pour(reception, effectif, f"{prefixe}{str(i).zfill(largeur)}"),
                source=source,
            )
            for i in range(debut, fin + 1)
        ]
        lignes = self.lignes.create_many(a_creer)
        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.MODIFICATION, app="receptions",
            objet_type="Reception", objet_id=reception.id,
            resume=f"Génération d'une plage de {total} unité(s) sur la réception {reception.reference}",
        )
        return lignes

    def retirer_ligne(self, reception: Reception, ligne_id, utilisateur) -> None:
        self._verifier_brouillon(reception, "retirer une unité")
        ligne = self.lignes.get_by_id(reception, ligne_id)
        if ligne is None:
            raise LigneReception.DoesNotExist("Ligne de réception introuvable.")
        numero_serie = ligne.numero_serie
        self.lignes.delete(ligne)
        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.MODIFICATION, app="receptions",
            objet_type="Reception", objet_id=reception.id,
            resume=f"Retrait de {numero_serie} de la réception {reception.reference}",
        )

    def extraire(self, reception: Reception, utilisateur, *, type_article: str | None = None) -> dict:
        """(Re)lance l'extraction sur le PDF de la réception — §05 du dossier
        de conception. Ne touche qu'aux lignes déjà issues d'une extraction
        précédente (source=EXTRACTION) : les lignes ajoutées/corrigées à la
        main par l'utilisateur ne sont jamais effacées par un nouveau passage."""
        self._verifier_brouillon(reception, "extraire")
        if reception.nature != NatureReception.ARRIVAGE:
            raise ValidationError("L'extraction n'est disponible que pour un arrivage.")
        if not reception.fichier:
            raise ValidationError("Aucun fichier n'est associé à cette réception.")
        if reception.fournisseur_id is None:
            raise ValidationError("Cette réception n'a pas de fournisseur d'en-tête.")

        fournisseur = reception.fournisseur
        type_final = type_article or fournisseur.type_article_defaut
        if not type_final:
            raise ValidationError(
                "Le type d'article est obligatoire (aucun type par défaut sur ce fournisseur)."
            )

        mode = fournisseur.mode_extraction or "TEXTE"
        try:
            resultat = extraire_pdf(reception.fichier, mode, fournisseur.regex_numero_serie)
        except OcrIndisponible as exc:
            raise ValidationError(str(exc))

        # Ré-extraction : ne supprime que les lignes jamais retouchées par un humain.
        (
            self.lignes.get_all_for_reception(reception)
            .filter(source=SourceLigneReception.EXTRACTION)
            .delete()
        )

        # Générique (pas de profil) ou OCR (page scannée) : confiance moindre,
        # revue manuelle systématique — le doublon reste prioritaire sur ce statut.
        a_verifier_par_defaut = resultat.generique or resultat.ocr_utilise
        a_creer = []
        for numero in resultat.numeros:
            statut = self._statut_pour(reception, fournisseur, numero)
            if statut == StatutLigneReception.OK and a_verifier_par_defaut:
                statut = StatutLigneReception.A_VERIFIER
            a_creer.append(LigneReception(
                reception=reception, numero_serie=numero, fournisseur=None,
                type_article=type_final, statut_ligne=statut, source=SourceLigneReception.EXTRACTION,
            ))
        lignes = self.lignes.create_many(a_creer)

        if resultat.quantite_detectee and not reception.quantite_annoncee:
            reception = self.repo.update(reception, quantite_annoncee=resultat.quantite_detectee)

        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.MODIFICATION, app="receptions",
            objet_type="Reception", objet_id=reception.id,
            resume=f"Extraction sur la réception {reception.reference} ({len(lignes)} numéro(s) détecté(s))",
        )
        logger.info(
            "Extraction : %s — %s numéro(s), profil %s",
            reception.reference, len(lignes), "générique" if resultat.generique else fournisseur.code,
        )
        return {
            "reception": reception,
            "lignes": lignes,
            "plage_detectee": detecter_plage(resultat.numeros),
            "generique": resultat.generique,
            "ocr_utilise": resultat.ocr_utilise,
        }

    # ── Cycle de vie ─────────────────────────────────────────────────────

    def valider(self, reception: Reception, utilisateur) -> Reception:
        self._verifier_brouillon(reception, "valider")
        lignes = list(self.lignes.get_all_for_reception(reception))
        if not lignes:
            raise ValidationError("Impossible de valider une réception sans aucune unité.")
        problematiques = [l for l in lignes if l.statut_ligne != StatutLigneReception.OK]
        if problematiques:
            raise ValidationError(
                f"{len(problematiques)} ligne(s) à corriger avant validation (doublon ou format "
                "invalide) — retirez-les ou corrigez-les d'abord."
            )

        commentaire = (
            "Reprise de l'ancien système" if reception.nature == NatureReception.REPRISE
            else f"Réception {reception.reference}"
        )
        date_mouvement = timezone.make_aware(datetime.combine(reception.date_reception, time.min))

        with transaction.atomic():
            for ligne in lignes:
                fournisseur = ligne.fournisseur or reception.fournisseur
                try:
                    with transaction.atomic():  # savepoint — isole une éventuelle collision de numéro
                        unite = self.unites.create(
                            numero_serie=ligne.numero_serie, type_article=ligne.type_article,
                            fournisseur=fournisseur, statut=StatutStock.EN_STOCK,
                            reception=reception, date_entree=reception.date_reception,
                        )
                except IntegrityError:
                    raise ValidationError(
                        f"L'unité {ligne.numero_serie} ({fournisseur.code}) existe déjà en stock — "
                        "quelqu'un d'autre l'a probablement ajoutée entre-temps."
                    )
                self.mouvements.enregistrer(
                    unite_stock=unite, type_mouvement=TypeMouvement.ENTREE,
                    utilisateur=utilisateur, reception=reception,
                    commentaire=commentaire, date_mouvement=date_mouvement,
                )

            reception = self.repo.update(
                reception, statut=StatutReception.VALIDEE,
                valide_par=utilisateur if getattr(utilisateur, "is_authenticated", False) else None,
                valide_le=timezone.now(),
            )

        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.VALIDATION, app="receptions",
            objet_type="Reception", objet_id=reception.id,
            resume=f"Validation de la réception {reception.reference} ({len(lignes)} unité(s))",
        )
        # Une réception ne fait qu'ajouter du stock — pas de check de seuil.
        self.notifications.notifier_reception_validee(reception=reception, nombre=len(lignes))
        logger.info("Réception validée : %s (%s unités)", reception.reference, len(lignes))
        return reception

    def annuler(self, reception: Reception, motif: str, utilisateur) -> Reception:
        if reception.statut != StatutReception.VALIDEE:
            raise ValidationError("Seule une réception validée peut être annulée.")
        motif = (motif or "").strip()
        if not motif:
            raise ValidationError("Le motif d'annulation est obligatoire.")

        unites = list(self.unites.get_all().filter(reception=reception))
        deja_sorties = [u for u in unites if u.statut != StatutStock.EN_STOCK]
        if deja_sorties:
            numeros = ", ".join(u.numero_serie for u in deja_sorties[:5])
            suffixe = "…" if len(deja_sorties) > 5 else ""
            raise ValidationError(
                f"Impossible d'annuler : {len(deja_sorties)} unité(s) de cette réception ne sont "
                f"plus en stock (déjà sorties) — {numeros}{suffixe}."
            )

        with transaction.atomic():
            for unite in unites:
                unite.delete()  # suppression logique — l'unité n'aurait pas dû exister
                self.mouvements.enregistrer(
                    unite_stock=unite, type_mouvement=TypeMouvement.ANNULATION_ENTREE,
                    utilisateur=utilisateur, reception=reception, commentaire=motif,
                )
            reception = self.repo.update(
                reception, statut=StatutReception.ANNULEE, motif_annulation=motif,
                annule_par=utilisateur if getattr(utilisateur, "is_authenticated", False) else None,
                annule_le=timezone.now(),
            )

        self.historique.enregistrer(
            utilisateur=utilisateur, action=HistoriqueAction.Action.ANNULATION, app="receptions",
            objet_type="Reception", objet_id=reception.id,
            resume=f"Annulation de la réception {reception.reference} — {motif}",
        )
        logger.info("Réception annulée : %s", reception.reference)
        return reception

    # ── Utilitaires ──────────────────────────────────────────────────────

    def _resoudre_fournisseur_ligne(self, reception, fournisseur_id, fournisseur_code, utilisateur):
        """Renvoie (fournisseur_a_stocker_sur_la_ligne, fournisseur_effectif).

        Reprise : chaque ligne porte son propre fournisseur (obligatoire,
        résolu par id ou créé à la volée par code — §05 du dossier de
        conception). Arrivage/saisie : le fournisseur vient de l'en-tête, la
        ligne ne stocke rien (cohérent avec le modèle documenté).
        """
        if reception.nature != NatureReception.REPRISE:
            if reception.fournisseur_id is None:
                raise ValidationError("Cette réception n'a pas de fournisseur d'en-tête.")
            return None, reception.fournisseur

        if fournisseur_id:
            fournisseur = self.fournisseurs.get_by_id(fournisseur_id)
            if fournisseur is None:
                raise ValidationError("Fournisseur introuvable.")
            return fournisseur, fournisseur

        code = (fournisseur_code or "").strip().upper()
        if not code:
            raise ValidationError(
                "Le fournisseur est obligatoire pour une ligne de reprise "
                "(sélectionnez-en un existant ou saisissez un nouveau code)."
            )
        fournisseur = self.fournisseurs.get_by_code(code)
        if fournisseur is None:
            fournisseur = self.fournisseurs.create(code=code, nom=code)
            self.historique.enregistrer(
                utilisateur=utilisateur, action=HistoriqueAction.Action.CREATION, app="fournisseurs",
                objet_type="Fournisseur", objet_id=fournisseur.id,
                resume=f"Création du fournisseur {code} (à la volée depuis une reprise)",
            )
            logger.info("Fournisseur créé à la volée depuis une reprise : %s", code)
        return fournisseur, fournisseur

    def _statut_pour(self, reception: Reception, fournisseur, numero_serie: str) -> str:
        if fournisseur is not None and self.unites.get_by_numero_serie(fournisseur, numero_serie) is not None:
            return StatutLigneReception.DOUBLON
        qs = self.lignes.get_all_for_reception(reception).filter(numero_serie=numero_serie)
        if reception.nature == NatureReception.REPRISE:
            qs = qs.filter(fournisseur=fournisseur)
        if qs.exists():
            return StatutLigneReception.DOUBLON
        return StatutLigneReception.OK

    def _verifier_brouillon(self, reception: Reception, action: str) -> None:
        if reception.statut != StatutReception.BROUILLON:
            raise ValidationError(f"Impossible de {action} : la réception n'est plus au statut brouillon.")

    def _generer_reference(self) -> str:
        annee = timezone.now().year
        prefixe = f"REC-{annee}-"
        dernier = self.repo.get_dernier_numero(prefixe)
        dernier_num = int(dernier.reference.rsplit("-", 1)[-1]) if dernier else 0
        return f"{prefixe}{dernier_num + 1:04d}"
