# Oils of Africa Stock — API

Backend de l'application de gestion de stock (flexitanks & heating pads).
Django 5.2 LTS + Django REST Framework + PostgreSQL, architecture en couches
Service / Repository (version pragmatique de la Clean Architecture).

Dossier de conception : voir l'artefact « Stock Oils of Africa ».

## Architecture

```
core/                  configuration du projet UNIQUEMENT — aucune logique métier
  settings.py
  urls.py               racine des routes, monte chaque app sous /api/v1/...
  swagger.py             réglages drf-spectacular
  wsgi.py / asgi.py

apps/                  toutes les apps métier, une par domaine
  common/               socle partagé : id UUID, suppression logique, audit générique
  users/                 authentification JWT, utilisateur applicatif (rôle)
  fournisseurs/
  clients/
  stock/                 unités de stock (UniteStock) + journal des mouvements (MouvementStock)
  sorties/                bons de sortie (Sortie, LigneSortie), cycle brouillon/validée/annulée, PDF
  retours/                enregistrement d'un retour — pas de modèle, compose apps.stock
  receptions/             entrées de stock (Reception, LigneReception) — saisie manuelle, plage, reprise
```

Chaque app métier suit le même découpage en couches :

| Fichier            | Couche            | Responsabilité                                              |
|---------------------|--------------------|---------------------------------------------------------------|
| `models.py`         | Domaine            | Champs, `Meta`, `__str__` — pas de logique métier              |
| `repositories.py`   | Accès aux données  | Seul fichier à toucher `.objects` — `get_all`, `get_by_id`, `create`, `update`, `delete` |
| `services.py`       | Métier             | Règles métier, lève `ValidationError` (message en français), journalise dans `HistoriqueAction` |
| `serializers.py`    | Présentation       | Validation de format + sérialisation uniquement                |
| `permissions.py`    | Autorisation       | Réexporte/compose les permissions de `apps.common.permissions` |
| `views.py`          | Contrôleur         | `GenericViewSet` fin — valide, délègue au service, traduit les erreurs en HTTP |
| `urls.py`           | Routage            | `SimpleRouter` local, monté par `core/urls.py`                  |
| `test_*.py`         | Tests              | Un fichier par flux d'API                                       |

Flux d'une requête, toujours dans ce sens :
`HTTP → View → Serializer (format) → Service (métier) → Repository (ORM) → Model`

Nouvelle app métier (Jalon 2+) → même squelette, ajoutée à `INSTALLED_APPS`
(`apps.<domaine>`) et montée dans `core/urls.py`.

## Prérequis

- Python 3.13
- PostgreSQL 17 en local (port 5432)

## Installation

```bash
py -3.13 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
cp .env.example .env          # puis adapter SECRET_KEY et DB_*
```

### Base de données

Créer le rôle et la base (via psql en superutilisateur) :

```sql
CREATE ROLE oils_stock WITH LOGIN PASSWORD 'motdepasse';
CREATE DATABASE oils_stock OWNER oils_stock;
```

Reporter les identifiants dans `DB_NAME`/`DB_USER`/`DB_PASSWORD` (et
`DB_HOST`/`DB_PORT` si différents des défauts `127.0.0.1`/`5432`) du fichier
`.env`.

## Lancer

```bash
.venv/Scripts/python.exe manage.py migrate
.venv/Scripts/python.exe manage.py createsuperuser
.venv/Scripts/python.exe manage.py runserver
```

- Admin : http://127.0.0.1:8000/admin/
- Santé : http://127.0.0.1:8000/api/health/ (non versionnée)

## Tests

```bash
.venv/Scripts/python.exe manage.py test
```

Un fichier de tests par flux (`apps/<domaine>/test_<flux>_api.py`) : authentification
(connexion, refresh, logout, rotation, compte supprimé), mot de passe oublié (code,
expiration, usage unique, tentatives, révocation des sessions), CRUD + permissions
par rôle, contrainte d'unicité `(fournisseur, numero_serie)`, cycle de vie d'une sortie
(lignes, validation, annulation, mouvements écrits, bon de sortie PDF), retour d'une
unité sortie, cycle de vie d'une réception (saisie, plage, doublons, validation, reprise
avec création de fournisseur à la volée, annulation), extraction PDF (profil fournisseur,
détection générique, doublons, re-extraction, plage détectée, bout en bout jusqu'à la
validation — PDF de test générés à la volée avec reportlab, vrai moteur pdfplumber
exercé, pas de mock), OCR (page scannée + dégradation propre sans Tesseract, et avec
le vrai binaire quand il est installé), lookup et scan mobile (résolution par
numéro/code, photo OCRisée), régression code unique après suppression logique,
exports CSV (respect des filtres), gestion des comptes (garde-fous dernier
admin/propre compte), annulation réservée admin.
**141 tests**, tous verts (les tests OCR se dégradent en `skip` plutôt qu'en échec
sur une machine sans le binaire Tesseract installé — voir Jalon 5 plus bas).

Le vrai SMTP (`EMAIL_HOST_PASSWORD` etc.) n'est **jamais** utilisé pendant `manage.py test` —
Django bascule automatiquement sur un backend en mémoire ; les e-mails envoyés sont
consultables dans `django.core.mail.outbox`.

## Déploiement (hébergement mutualisé cPanel)

Ciblé pour un hébergement mutualisé sans accès root (« Setup Python App » de
cPanel + Passenger) — pas de Docker/Gunicorn possible sur ce type d'hôte.

**Moteur de base de données différent entre dev et prod** — le dev reste sur
PostgreSQL (`psycopg`, comme depuis le début du projet) ; la production
utilise **MySQL**, seul moteur disponible sur cet hébergement mutualisé.
`DB_ENGINE` (`.env`, `postgresql` par défaut) sélectionne le moteur sans
dupliquer `core/settings.py` — mettre `DB_ENGINE=mysql` (+ `DB_PORT=3306`)
en production. Driver MySQL : **PyMySQL** (`requirements.txt`), pas
`mysqlclient` — pur Python, donc pas de compilation nécessaire sur un hôte
sans compilateur C ni accès root. `core/__init__.py` installe le shim
`pymysql.install_as_MySQLdb()` (chargé avant toute config Django, obligatoire
pour que le backend `django.db.backends.mysql` fonctionne avec PyMySQL). En
MySQL, `OPTIONS` impose `utf8mb4` (accents/emoji corrects) et le mode strict
(`STRICT_TRANS_TABLES`) — sans lui, MySQL tronque silencieusement une valeur
trop longue au lieu de lever une erreur de validation claire.

- **`passenger_wsgi.py`** (racine du dépôt) — remplace le stub que cPanel
  génère par défaut à la création de l'app Python ; pointe simplement vers
  `core.wsgi.application`, inchangé sinon.
- **`.env.production`** (jamais committé, dans `.gitignore`) — gabarit prêt à
  copier vers `.env` **sur le serveur uniquement** ; ne jamais écraser le
  `.env` local de dev avec, sous peine de faire pointer le dev sur la vraie
  base de production.
- **Base de données en champs séparés** (`DB_NAME`/`DB_USER`/`DB_PASSWORD`/
  `DB_HOST`/`DB_PORT`, `core/settings.py`) plutôt qu'une seule `DATABASE_URL` —
  un mot de passe d'hébergement mutualisé contient souvent des caractères
  spéciaux d'URL (`@ { } * , =` ...) qui exigeraient un pourcent-encodage
  fragile dans une chaîne de connexion ; en champ séparé, django-environ le
  lit tel quel, sans transformation ni risque d'erreur d'encodage.
- **`DEBUG=False` active automatiquement** `SECURE_SSL_REDIRECT`,
  `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE` (`core/settings.py`) — suppose
  un certificat SSL déjà valide sur le domaine (AutoSSL/Let's Encrypt), sinon
  boucle de redirection.
- **`CSRF_TRUSTED_ORIGINS`** (nouvelle variable `.env`, liste vide par défaut
  en dev) — doit contenir le domaine de l'API lui-même en production
  (`https://...`), sinon la connexion à `/admin/` échoue en 403 (authentification
  par session, contrairement à l'API qui n'en a pas besoin — JWT sans cookie).
- **WhiteNoise** (`whitenoise.middleware.WhiteNoiseMiddleware`, juste après
  `SecurityMiddleware`) sert les statiques (admin, Swagger UI) directement
  depuis l'app WSGI — `DEBUG=False` désactive le service natif de
  `django.contrib.staticfiles`, et un hébergement mutualisé n'offre pas
  toujours un moyen simple de mapper `/static/` côté Apache. Nécessite
  `manage.py collectstatic` après chaque déploiement (`STORAGES["staticfiles"]`
  = `CompressedManifestStaticFilesStorage`, noms de fichiers hachés + gzip/brotli).
- **Fichiers médias (PDF d'arrivage) : rien à configurer côté serveur** — le
  mapping `/media/...` de `core/urls.py` n'est actif qu'en `DEBUG` (commodité
  de dev) ; l'application elle-même ne l'utilise jamais, le seul point d'accès
  réel est `GET /api/v1/receptions/{id}/fichier/`, qui lit le fichier sur
  disque et le renvoie via `FileResponse` (décision du Jalon 4, pour éviter
  tout souci CORS sur une URL média brute).

**Étapes sur le serveur** (une fois l'app Python créée dans cPanel, le dépôt
déployé/uploadé, et `.env.production` copié vers `.env`) :

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
# puis redémarrer l'app Python depuis cPanel (touch tmp/restart.txt ou bouton "Restart")
```

**Reste à faire côté hébergeur, hors de portée depuis cet environnement** :
créer l'app Python dans cPanel (version Python, dossier racine = ce dépôt),
vérifier que le certificat SSL du domaine de l'API est bien actif avant
d'activer `SECURE_SSL_REDIRECT`, et mettre à jour `NEXT_PUBLIC_API_URL` côté
frontend pour pointer vers `https://oils-stock-api.communaute-tepo.com`.

## Authentification — détails

- **Connexion** (`LoginView` + `LoginSerializer` + `AuthService.connecter`) : classe et serializer propres au projet (n'utilise plus directement les vues simplejwt) — **un seul message**, `"Identifiants incorrects."`, quelle que soit la cause (mauvais mot de passe, compte inconnu, supprimé ou désactivé). Tous les messages d'erreur/succès sont formulés côté backend, jamais laissés aux textes par défaut d'une librairie.
- JWT via `rest_framework_simplejwt` : access 30 min, refresh 7 jours.
- **Rotation + liste noire** : `ROTATE_REFRESH_TOKENS` et `BLACKLIST_AFTER_ROTATION` activés — un refresh déjà échangé contre un nouvel access ne peut pas être rejoué. App `rest_framework_simplejwt.token_blacklist` requise (déjà dans `INSTALLED_APPS`).
- **`POST /api/v1/auth/logout/`** révoque explicitement le refresh token fourni (déconnexion « vraie », pas seulement un oubli côté client).
- Limite connue : un `access` token déjà émis reste valable jusqu'à expiration naturelle (pas de révocation immédiate des access tokens, seulement des refresh).

### Mot de passe oublié

```
POST /api/v1/auth/password/reset/          {email} -> 200 générique (n'indique jamais si le compte existe)
POST /api/v1/auth/password/reset/confirm/  {email, code, new_password, confirm_password} -> 200
```

- Code à **6 chiffres**, envoyé par e-mail (`EMAIL_*` dans `.env`), haché en base (jamais stocké en clair), valable **15 minutes**, **usage unique**, invalidé après **5 tentatives** incorrectes.
- Rate-limit par IP (`DEFAULT_THROTTLE_RATES`) : 5 demandes/heure, 10 confirmations/heure — la confirmation est la cible d'un brute-force du code, la demande celle d'un spam d'e-mails.
- Au succès : **toutes les sessions existantes du compte sont révoquées** (tous ses refresh tokens blacklistés) — cohérent avec le logout, réutilise `token_blacklist`.
- Sans configuration SMTP (`.env` vide), `EMAIL_BACKEND` retombe sur la console — aucun compte e-mail requis pour développer.

## Sorties & retours — détails (Jalon 2)

- **`Sortie`** — en-tête client (référentiel) / projet (texte libre, autocomplété) / TRD (texte libre) / date. Naît `BROUILLON`, référence auto-générée (`SOR-2026-0001`, sous `transaction.atomic()` + `select_for_update()` pour éviter les collisions).
- **`LigneSortie`** — une unité par ligne. Ajout par numéro de série : refusé si l'unité n'existe pas, n'est pas `EN_STOCK`, ou si le numéro est ambigu entre plusieurs fournisseurs (le client précise alors `fournisseur`). Suppression réelle (pas de suppression logique) tant que la sortie est `BROUILLON` — une ligne retirée avant validation n'a jamais représenté un mouvement de stock.
- **Validation** (`POST /sorties/{id}/valider/`) — toutes les unités passent `EN_STOCK` → `SORTIE`, reçoivent `date_sortie` (celle de la Sortie), un `MouvementStock` de type `SORTIE` est écrit pour chacune. Refusé si la sortie n'a aucune ligne.
- **Annulation** (`POST /sorties/{id}/annuler/`, motif obligatoire) — uniquement depuis `VALIDEE`. Toutes les unités reviennent `EN_STOCK`, un `MouvementStock` `ANNULATION_SORTIE` par unité. Rien n'est supprimé.
- **Retour** (`POST /api/v1/retours/`) — **pas de modèle dédié** (neuf tables au total dans le dossier de conception, pas de table `Retour`) : une ou plusieurs unités `SORTIE` reviennent `EN_STOCK`, `MouvementStock` `RETOUR` par unité (garde le lien vers la sortie d'origine via son champ `sortie`). La sortie d'origine, elle, reste `VALIDEE` — seules les unités rentrent. Résolution du numéro de série identique à l'ajout de ligne (refus si ambigu/inconnu/pas actuellement sorti).
- **`MouvementStock`** (`apps/stock/models.py`) — journal d'audit immuable : `type_mouvement` (`ENTREE · SORTIE · RETOUR · ANNULATION_ENTREE · ANNULATION_SORTIE` — les deux premiers arrivent avec `apps.receptions`, Jalon 3/4), `date_mouvement` (date **métier** de l'évènement, distincte de `created_at` — un retour peut être signalé après coup avec sa vraie date). Jamais modifié ni supprimé, lecture seule même dans l'admin. Écrit uniquement via `MouvementStockService.enregistrer(...)`.
- **Bon de sortie** (`GET /sorties/{id}/bon-de-sortie.pdf/` — **avec le `/` final**, ajouté par le routeur DRF) — PDF généré à la volée avec `reportlab` (pur Python, pas de moteur HTML→PDF système à installer), disponible uniquement une fois la sortie `VALIDEE`. En-tête avec le logo Oils of Africa (`apps/sorties/assets/oils-of-africa-logo.png`, copié depuis le frontend — `LOGO_PATH.exists()` vérifié avant insertion : un déploiement incomplet ne fait pas planter le PDF, il part juste sans logo) à côté du titre ; pied de page avec un bloc « Validation » (nom du Gestionnaire de Stock, date, encadré vide pour signer à la main sur l'exemplaire imprimé) — demandé après coup.
- Filtres sortie : `client`, `statut`, `date_debut`/`date_fin` (`apps/sorties/filters.py`, `django_filters.FilterSet` — les autres apps utilisent `filterset_fields` simple, insuffisant pour une plage de dates) · recherche : `reference`, `projet`, `trd`.
- `GET /api/v1/projets/?q=` — autocomplétion du champ libre `projet` (libellés distincts déjà utilisés).
- Seul endroit du projet avec une route réellement imbriquée (`/sorties/{id}/lignes/{ligneId}/`, suppression) : ne rentre pas dans un `SimpleRouter`/`@action`, vue dédiée (`LigneSortieDetailView`) montée à la main dans `apps/sorties/urls.py`.

## Réceptions — détails (Jalon 3)

- **`Reception`** — trois natures (`ARRIVAGE`, `SAISIE`, `REPRISE`). `fournisseur` obligatoire en en-tête pour arrivage/saisie, toujours nul pour une reprise (chaque ligne porte le sien — §04 du dossier de conception). Naît `BROUILLON`, référence auto-générée (`REC-2026-0001`, même mécanique anti-collision que `Sortie`). Le champ `fichier` (PDF, `ARRIVAGE` uniquement) est arrivé avec le Jalon 4 — voir plus bas.
- **Permissions** : créer/valider/annuler une `SAISIE` ou un `ARRIVAGE` → magasinier + admin, comme les sorties. Créer une **`REPRISE`** → **admin uniquement** (§09 du dossier de conception, mise en service) — appliqué dans `ReceptionService.creer` via `django.core.exceptions.PermissionDenied` (auto-traduite en 403 par DRF, pas besoin d'une permission DRF dédiée qui inspecterait le corps de la requête).
- **`LigneReception`** — ajout à l'unité ou par plage (`prefixe` + `debut` + `fin`, zéro-préfixé sur `largeur` chiffres déduite de `fin` si omise — génère `prefixe + "001"` à `prefixe + "131"` pour l'exemple Ebont du dossier de conception). Statut `OK`/`DOUBLON` calculé à l'ajout : doublon si déjà en stock **ou** déjà présent sur cette même réception (n'empêche pas l'ajout, juste la validation). `A_VERIFIER` est utilisé depuis le Jalon 4 (extraction générique, voir plus bas) ; `FORMAT_INVALIDE` reste réservé à l'OCR (Jalon 5), inutilisé pour l'instant. Suppression réelle tant que `BROUILLON` (même raisonnement que `LigneSortie`).
- **Reprise — fournisseur à la volée** : chaque ligne accepte `fournisseur` (UUID existant) ou `fournisseur_code` (texte) ; si le code ne correspond à aucun fournisseur, il est **créé automatiquement** (`nom` = `code`, `actif=True`), avec une entrée `HistoriqueAction` dédiée — cohérent avec « l'ancien système n'a aucun export » du dossier de conception.
- **Validation** (`POST /receptions/{id}/valider/`) — refusée si une ligne n'est pas `OK` (message indiquant combien) : plus simple et plus sûr que promouvoir seulement les lignes `OK` en silence. Chaque ligne devient une `UniteStock` `EN_STOCK` (`fournisseur` = celui de la ligne s'il existe, sinon celui de l'en-tête) + un `MouvementStock` `ENTREE`, commenté `"Reprise de l'ancien système"` en reprise ou `"Réception {référence}"` sinon. `date_entree` = `date_reception` (date de reprise pour une reprise, comme documenté). Une collision de numéro de série au moment précis de la validation (course avec une autre réception) est rattrapée via une transaction imbriquée (savepoint) et renvoyée en 400 explicite plutôt qu'en 500.
- **Annulation** (`POST /receptions/{id}/annuler/`, motif obligatoire) — uniquement depuis `VALIDEE`. **Refusée** si l'une des unités créées par cette réception n'est plus `EN_STOCK` (déjà sortie) — contrairement à l'annulation d'une sortie, qui ne fait que faire revenir des unités déjà existantes, annuler une réception **retire des unités qui n'auraient jamais dû exister** : elles sont mises en suppression logique (`UniteStock.delete()`), pas juste changées de statut. Un `MouvementStock` `ANNULATION_ENTREE` par unité garde la trace.
- Contrôle de comptage (`quantite_annoncee` vs nombre de lignes) : **signalé, jamais bloquant** — affiché côté frontend, pas vérifié par l'API (une correction légitime en cours de revue peut créer un écart temporaire).
- Filtres réception : `nature`, `statut`, `fournisseur`, `date_debut`/`date_fin` (`apps/receptions/filters.py`, même approche que `apps/sorties/filters.py`) · recherche : `reference`, `reference_fournisseur`.
- `/api/v1/unites/` et `/api/v1/mouvements/` acceptent maintenant aussi le filtre `reception`.

## Extraction des documents — détails (Jalon 4)

- **Profil d'extraction** (`GET·PUT /fournisseurs/{id}/profil-extraction/`) — trois champs directement sur `Fournisseur` (pas de modèle séparé, relation 1:1 naturelle) : `mode_extraction` (`TABLEAU`/`GRILLE`/`TEXTE`, vide = générique), `regex_numero_serie`, `type_article_defaut`. Lecture ouverte à tous, écriture réservée à l'**ADMIN** (§09 du dossier de conception) — même permission que le CRUD fournisseur, pas de logique supplémentaire nécessaire.
- **`apps/receptions/extraction.py`** — moteur pur (aucun accès ORM), `pdfplumber` sans OCR (Jalon 5) :
  - `extraire_pdf(fichier, mode, regex)` — mode `TABLEAU` : essaie `page.extract_tables()`, retient la colonne dont le plus de cellules matchent le motif (ignore la 1ʳᵉ ligne, en-tête probable), retombe sur un balayage du texte brut si aucune table n'est concluante. Modes `GRILLE`/`TEXTE` et fournisseur sans profil : balayage du texte brut directement (`page.extract_text()` + regex).
  - Sans `regex_numero_serie` (fournisseur sans profil) : motif générique large (jetons alphanumériques 5-24 caractères) — fiabilité assumée par le statut `A_VERIFIER` systématique en aval, pas par la précision du motif (§05 : « détection générique, revue manuelle »).
  - `detecter_plage(numeros)` — repère un préfixe commun + compteur numérique de largeur constante (regex `^((?:.*\D)?)(\d+)$` : le préfixe peut lui-même contenir des chiffres, ex. `24E3231260424A` avant `001` — piège rencontré et corrigé, une première version supposait un préfixe sans aucun chiffre). Renvoie `debut`/`fin`/`complet`/`nb_trouves`/`nb_attendus` — purement informatif, ne crée rien ; le frontend propose de compléter via `/lignes/plage/` (déjà là depuis le Jalon 3) si `complet=False`.
  - Quantité annoncée auto-détectée (`\d+\s*(?:SETS?|UNITÉS?|PCS|PIECES?)`, ex. « 131 SETS ») — ne remplace jamais une valeur déjà saisie par l'utilisateur.
- **`ReceptionService.extraire`** (`POST /receptions/{id}/extraire/`) — uniquement pour un `ARRIVAGE` `BROUILLON` avec fichier. Type d'article : paramètre optionnel, sinon `type_article_defaut` du fournisseur, sinon 400. Une ligne extraite avec un profil connu part `OK` (sous réserve du doublon habituel) ; sans profil, systématiquement `A_VERIFIER`. **Ré-extraction** ("(Re)lance") : supprime uniquement les lignes `source=EXTRACTION` de la réception avant de recréer — les lignes ajoutées/corrigées à la main (`MANUEL`/`PLAGE`) sont toujours intactes.
- **`Reception.fichier`** — `FileField` (PDF uniquement, 20 Mo max, deux validateurs : `FileExtensionValidator` + taille). `MEDIA_ROOT`/`MEDIA_URL` ajoutés à `core/settings.py`, servis par Django lui-même seulement en `DEBUG` (`core/urls.py`) — sans authentification à ce niveau (réseau local). **Le frontend ne consomme jamais cette URL brute** : il passe par `GET /receptions/{id}/fichier/` (nouvel `@action`, `FileResponse`, même pattern que le bon de sortie du Jalon 2) — sert deux buts à la fois : cohérence de l'authentification JWT, et surtout évite un **blocage CORS réel rencontré en testant** (le frontend et l'API ne sont pas sur le même hôte dès qu'un tunnel s'interpose ; la personnalisation CORS de `django-cors-headers` ne s'appliquait pas de la même façon à `/media/` qu'à `/api/v1/`).
- Création d'un `ARRIVAGE` : `POST /receptions/` accepte désormais du **multipart** (fichier + champs) en plus du JSON déjà utilisé pour `SAISIE`/`REPRISE` — aucune configuration supplémentaire nécessaire, les `DEFAULT_PARSER_CLASSES` de DRF acceptent déjà les deux nativement.

## OCR & scan mobile — détails (Jalon 5)

- **`apps/common/ocr.py`** — primitive OCR partagée (`OcrIndisponible`, `ocriser_image(image)` via `pytesseract`). Vit dans `apps.common` plutôt que dans `apps.receptions` ou `apps.stock` : les deux en ont besoin (page de PDF scannée pour l'un, photo prise au téléphone pour l'autre) et `apps.receptions` dépend déjà de `apps.stock` — la loger dans l'un des deux aurait créé un cycle.
- **Extraction PDF, repli OCR** (`apps/receptions/extraction.py`) — une page dont `extract_text()` renvoie moins de 10 caractères est considérée scannée : elle est rendue en image (`page.to_image(resolution=300)`) puis passée à `ocriser_image`. `ResultatExtraction.ocr_utilise` (bool) l'indique ; une ligne extraite d'une page OCRisée part systématiquement `A_VERIFIER` (même logique de confiance moindre que le mode générique sans profil). **Écart assumé avec le dossier de conception** : celui-ci nommait `ocrmypdf` ; `pytesseract` + le rendu de page déjà fourni par `pdfplumber` suffisent puisque le besoin réel est d'extraire du texte, pas de produire un nouveau PDF recherchable — évite les dépendances système lourdes d'`ocrmypdf` (Ghostscript, qpdf).
- **`GET /api/v1/unites/lookup/?q=`** — résout `code_interne` **ou** `numero_serie` exact, renvoie toujours une **liste** (vide si rien, plusieurs si le numéro est partagé entre fournisseurs — l'appelant désambiguïse).
- **`POST /api/v1/unites/scanner/`** — OCR d'une photo envoyée en multipart (`image`) : extrait des jetons candidats (motif large `[A-Z0-9]{5,24}`, 15 max), renvoie chacun avec les unités qu'il résout, triés résolus-d'abord. Image validée par `PIL.Image.open()` + `.load()` (décodage forcé immédiat) — erreurs illisibles renvoyées en 400, jamais un 500.
- **Tesseract** (binaire système, pas fourni par `pytesseract`) doit être installé séparément sur la machine (`choco install tesseract` sous Windows, en shell **administrateur**). Sans lui, `ocriser_image` lève `OcrIndisponible`, traduite en 400 avec un message explicite ("saisie manuelle en attendant") — l'extraction texte normale et la résolution manuelle (`lookup`) fonctionnent sans Tesseract ; seule la reconnaissance sur une page scannée/une photo en a besoin. **Piège rencontré après l'install** : `choco install` met à jour le PATH machine, mais un processus déjà démarré (ex. `runserver` lancé avant) garde son PATH en mémoire jusqu'à son propre redémarrage — `shutil.which("tesseract")` échouait donc juste après l'installation, alors même que le binaire était bien présent. `_resoudre_binaire_tesseract()` (`apps/common/ocr.py`) retente en plus les emplacements d'installation Chocolatey standard (`C:\Program Files\Tesseract-OCR\tesseract.exe`) avant d'abandonner, sans dépendre du PATH.
- **HTTPS local** (`runserver_plus`, fourni par `django-extensions` + `Werkzeug`, ajoutés à `INSTALLED_APPS` uniquement quand `DEBUG=True`) — nécessaire car `getUserMedia` (caméra, écran `/scan` du frontend) exige un contexte sécurisé dès qu'on accède depuis autre chose que `localhost`/`127.0.0.1` (un téléphone sur le réseau local, typiquement). Réutilise le **même certificat** que celui généré côté frontend par `next dev --experimental-https` (mkcert, voir le README frontend) plutôt que d'en générer un second :
  ```bash
  .venv/Scripts/python.exe manage.py runserver_plus 0.0.0.0:8000 \
    --cert-file ../oils-stock-web/certificates/localhost.pem \
    --key-file ../oils-stock-web/certificates/localhost-key.pem
  ```
  Générer d'abord le certificat côté frontend (une fois) avant cette commande — voir le README frontend pour l'ordre exact et pourquoi `NEXT_PUBLIC_API_URL` doit alors pointer vers `https://<ip-lan>:8000` (une page servie en HTTPS ne peut pas appeler une API en HTTP simple — *mixed content*, bloqué par le navigateur).
- **Tests** : `unittest.skipUnless(_resoudre_binaire_tesseract(), ...)` (même résolution que l'appli, pas juste `shutil.which`) pour les assertions qui exigent le vrai binaire — permet de développer/exécuter la suite sur une machine sans Tesseract sans faux rouge, plus un test toujours actif qui mocke `pytesseract.TesseractNotFoundError` pour vérifier la dégradation propre. Fixtures : PDF/PNG de synthèse (texte dessiné avec Pillow, PDF assemblé avec `reportlab` en pure image — aucune couche texte réelle) pour exercer le vrai moteur, jamais un mock du moteur lui-même. **Vérifié avec le vrai Tesseract installé** : les 4 tests jusque-là `skip` passent réellement (OCR d'un PDF scanné synthétique, détection de doublon, scan mobile résolu, jeton inconnu) — plus un vrai document scanné (bordereau Ebont réel) extrait avec succès en conditions réelles (voir la mémoire de session pour le détail).

## Fournisseurs & clients — fiches complètes

Le CRUD (`fournisseurs`/`clients`) existait déjà côté API depuis le Jalon 1 — cette
étape n'a ajouté aucune route, uniquement les écrans frontend qui en manquaient
(création, édition, détail avec petites stats). Un vrai bug a toutefois été trouvé
en les construisant :

- **`code` réutilisé après suppression logique → 500** — `code` (`Fournisseur`,
  `Client`) est déclaré `unique=True` sur le modèle, donc unique au niveau de la
  base sur **toutes** les lignes, supprimées incluses (la suppression est
  logique, `deleted_at`, voir `apps.common.models.SoftDeleteModel`). Mais
  `FournisseurRepository.get_by_code`/`ClientRepository.get_by_code`
  interrogeaient `objects` (lignes actives seulement) — un code déjà pris par
  une ligne supprimée passait donc cette vérification, puis la création
  plantait sur l'`IntegrityError` brute de la base (500), au lieu du message
  de validation français habituel. **Corrigé** : ces deux méthodes interrogent
  maintenant `all_objects`. Conséquence assumée : un code, une fois utilisé,
  reste bloqué même après suppression du fournisseur/client qui le portait —
  cohérent avec ce que la contrainte de la base impose déjà réellement.
  Deux tests de régression ajoutés (`test_code_dun_fournisseur_supprime_reste_bloque_proprement`,
  `test_code_dun_client_supprime_reste_bloque_proprement`).

## Jalon 6 — Pilotage & mise en production (en cours)

D'après §10 du dossier de conception : « Tableau de bord, statistiques, exports,
permissions fines, Docker Compose + Caddy, sauvegardes automatiques. » Volet
applicatif construit en premier (décision utilisateur) — exports CSV et gestion
des comptes ; le volet déploiement (Docker/Caddy/sauvegardes) n'est pas encore
démarré.

- **Annulation réservée à l'admin** — §09 du dossier de conception laissait la
  question ouverte (note *) : annuler une sortie/réception **déjà validée**
  (donc déjà répercutée sur le stock réel) est une opération sensible,
  tranchée en faveur de l'admin seul (au lieu de magasinier + admin comme le
  reste de l'écriture). `SortieViewSet`/`ReceptionViewSet.get_permissions()`
  renvoie `[IsAdmin()]` uniquement pour l'action `annuler`, `super()` pour
  toutes les autres — pas un changement de `permission_classes` global, qui
  aurait aussi bloqué créer/valider pour le magasinier. `IsAdmin` existait
  déjà dans `apps.common.permissions` (prévue « pour la gestion des
  utilisateurs », jamais utilisée avant) et est maintenant réexportée par
  `apps.sorties.permissions`/`apps.receptions.permissions`.
- **Exports CSV** (`apps/common/exports.py`, `exporter_csv(queryset, colonnes,
  prefixe_fichier)`) — ouverts à **tous les rôles** (§09), un `@action GET
  .../export/` par ViewSet en lecture (`unites`, `mouvements`, `sorties`,
  `receptions`). Réutilise `self.filter_queryset(self.get_queryset())` :
  respecte exactement les mêmes filtres/recherche que `list()`, mais exporte
  **toutes** les lignes correspondantes (pas de pagination). Séparateur `;`
  (pas `,`) et BOM UTF-8 en tête — sans ça Excel en français n'affiche ni les
  accents ni les colonnes correctement. Colonnes en clair via
  `get_FOO_display()` des champs `TextChoices` (`type_article`, `statut`,
  `nature`...), pas les valeurs brutes de l'enum.
- **Gestion des comptes** (`GET/POST/PATCH/DELETE /api/v1/users/`, entièrement
  réservé à l'**ADMIN**) — `apps/users/` avait déjà `UserRepository` et
  `IsAdmin` posés en prévision (commentaires « Jalon 6 » déjà présents dans le
  code depuis le Jalon 1). Ajouté : `UserService` (CRUD complet),
  `UserSerializer`/`CreerUserSerializer`, `UserViewSet`. Le mot de passe ne se
  change **jamais** après la création — uniquement via `/auth/password/reset/`
  (déjà existant), pour ne pas dupliquer sa logique de validation.
  - **Garde-fous** (`UserService.modifier`/`supprimer`) : impossible de
    retirer son **propre** rôle admin ou de se désactiver soi-même ;
    impossible de retirer/désactiver/supprimer le **dernier** compte admin
    actif (`UserRepository.compter_admins_actifs`) ; impossible de supprimer
    son propre compte.
  - **Même bug qu'avec fournisseurs/clients, évité d'emblée cette fois** :
    `username` est unique en base sur toutes les lignes (supprimées
    incluses) — `UserRepository.get_by_username` interroge `all_objects`
    dès le départ, pas `objects`, pour ne pas reproduire l'`IntegrityError`
    brute déjà rencontrée et corrigée sur `Fournisseur`/`Client`.
  - `apps/users/urls.py` restructuré : les routes d'auth (`token/`, `logout/`,
    `me/`, `password/reset/...`) posent maintenant leur préfixe `auth/`
    elles-mêmes (au lieu que `core/urls.py` le fasse via `path("auth/",
    include(...))`), pour pouvoir aussi monter le routeur `users/` dans le
    même fichier — même pattern que `apps.sorties.urls`
    (`sorties/` + `projets/` dans un seul fichier). Aucune URL existante n'a
    changé.
- **`apps/stock/repositories.py`** (déjà) annote `nb_unites`/`nb_lignes` sur
  les querysets de `Sortie`/`Reception` — réutilisé tel quel dans les exports
  (`s.nb_unites`) plutôt que de recompter avec `.count()` par ligne (évite un
  N+1 sur un export potentiellement long).
- **Fiche fournisseur enrichie** (demandé après coup) — répartition Flexitank/
  Heating pad (comptages `/unites/?fournisseur=&type_article=`, déjà possible
  avec les filtres existants) et 5 dernières transactions du fournisseur.
  Ce dernier point manquait un filtre : `MouvementStockViewSet.filterset_fields`
  ne permettait de filtrer que sur des champs directs (`unite_stock`,
  `type_mouvement`, `sortie`, `reception`), pas sur le fournisseur de l'unité
  (relation indirecte). Ajouté `"unite_stock__fournisseur"` à la liste — la
  syntaxe `champ__relation` de django-filter marche directement dans
  `filterset_fields` sans FilterSet dédié, aucun autre changement nécessaire.
- **Répartition Flexitank/Heating pad aussi sur la liste `/fournisseurs`**
  (demandé après coup, une fois la fiche détail ci-dessus livrée) —
  `FournisseurRepository.get_all()` annote `nb_flexitanks`/`nb_heating_pads`
  via `Count("unites_stock", filter=Q(unites_stock__type_article=...),
  distinct=True)`, même pattern que `nb_unites`/`nb_lignes` sur
  Sortie/Reception. `get_by_id()` passe désormais par `get_all()` (au lieu de
  `Fournisseur.objects` directement) pour que la fiche détail garde elle
  aussi les compteurs annotés — mêmes deux champs, un seul calcul. Exposés
  côté `FournisseurSerializer` en `IntegerField(read_only=True, default=0)` —
  le `default` évite un plantage de sérialisation si jamais un fournisseur
  est un jour obtenu par un chemin qui ne passe pas par `get_all()`.
- **Seuil de réapprovisionnement par type, par fournisseur** (demandé après
  coup) — deux champs réels (pas annotés) sur `Fournisseur` :
  `seuil_reappro_flexitank`/`seuil_reappro_heating_pad`
  (`PositiveIntegerField`, `null=True` = pas d'alerte configurée pour ce
  type). Question posée à l'utilisateur pour lever l'ambiguïté de « seuil à
  ne pas dépasser » (plafond de capacité vs seuil bas de réappro) → **seuil
  bas** retenu : une alerte se déclenche quand le nombre d'unités **en
  stock** de ce type, pour ce fournisseur, descend à ce niveau ou en
  dessous. Conséquence directe : `nb_flexitanks`/`nb_heating_pads` (ci-dessus)
  ne comptent plus le total historique mais uniquement les unités
  `EN_STOCK` — le chiffre affiché et celui comparé au seuil doivent être le
  même nombre, sinon une alerte à côté d'un total qui ne bouge jamais serait
  incompréhensible. Migration `0003_fournisseur_seuil_reappro_flexitank_and_more`.
- **Bon de sortie enrichi** (demandé après coup) — logo Oils of Africa en
  en-tête (`apps/sorties/pdf.py::_entete`, image copiée depuis le frontend
  vers `apps/sorties/assets/`, insérée seulement si `LOGO_PATH.exists()` —
  jamais de 500 si le fichier venait à manquer) et bloc de signature
  « Validation » en pied de bon (`_bloc_signature`) : nom du **Gestionnaire
  de Stock**, date, encadré vide assez grand pour signer à la main sur
  l'exemplaire imprimé.
- **Tableau de bord analytique** (`apps/dashboard/`, demandé après coup) —
  première vraie surface d'agrégation du projet (`TruncMonth`,
  `Subquery`/`OuterRef`, `values().annotate()`). `DashboardViewSet`
  (`GenericViewSet`, 4 `@action` GET, ouvert à tous les rôles) →
  `DashboardService` (toutes les formules) → `DashboardRepository` (seul
  accès ORM, réutilise `FournisseurRepository.get_all()` pour ne pas
  recompter « le stock actuel »). Endpoints :
  `GET /api/v1/dashboard/stock-dormant/?seuil_jours=90` (unités EN_STOCK dont
  la dernière activité — dernière sortie, ou date d'entrée à défaut — dépasse
  X jours ; `valeur_immobilisee` = `null` si le fournisseur n'a pas de coût
  configuré, **jamais inventée**), `.../seuils-reappro/` (seuil effectif par
  fournisseur/type : manuel prioritaire, sinon
  `ceil(conso_moy_jour × delai_livraison_jours + stock_securite)` si le délai
  et un historique de sortie existent ; `conso_moy_jour` sur fenêtre glissante
  de **90 jours**), `.../sorties-mensuelles/` (12 mois, une série par type +
  moyenne mobile 3 mois, `null` sur les 2 premiers points),
  `.../previsions/` (jours avant rupture = `stock/conso`, date de commande
  recommandée, trié par urgence, nulls en dernier). 5 nouveaux champs
  nullables sur `Fournisseur` (migrations `0004`+`0005`) :
  `delai_livraison_jours`, `stock_securite_flexitank`/`_heating_pad`,
  `cout_unitaire_flexitank`/`_heating_pad` (`Decimal36` + `MinValueValidator(0)`).
- **Bug soft-delete corrigé** dans `FournisseurRepository.get_all()` — la
  relation inverse `unites_stock` passe par le manager de base de
  `UniteStock`, qui **n'applique pas** le filtre de suppression logique
  (`SoftDeleteModel`) : `nb_flexitanks`/`nb_heating_pads` comptaient les
  unités supprimées encore marquées `statut=EN_STOCK` (un fournisseur
  affichait 20 heating pads au lieu de 3). Corrigé en ajoutant
  `unites_stock__deleted_at__isnull=True` au filtre des deux `Count`.
- **Notifications web push + in-app** (`apps/notifications/`, demandé après
  coup) — modèles `Notification` (une ligne par destinataire, l'état lu est
  par utilisateur) et `PushSubscription` (un abonnement par appareil), calqués
  sur `HistoriqueAction` (`UUIDModel`, repo `@staticmethod`) **avec** la couche
  API. `NotificationService` crée les notifs in-app (`bulk_create`) puis tente
  un envoi web push (`pywebpush`, clés VAPID) — un échec d'envoi (timeout,
  410…) n'interrompt **jamais** la validation ; un endpoint mort (404/410)
  est supprimé. Déclenché **uniquement** à la validation d'une sortie
  (`MOUVEMENT_SORTIE` + détection de franchissement de seuil / passage à zéro
  en comparant l'état capturé *avant* le bloc atomic) ou d'une réception
  (`MOUVEMENT_ENTREE` seul — une entrée ne fait qu'ajouter du stock). Le seuil
  « effectif » vient de `DashboardService.seuil_effectif`. Tous les
  utilisateurs actifs sont destinataires (auteur inclus). Endpoints :
  `GET /api/v1/notifications/` (filtre `?lu=`), `.../non-lus/`,
  `POST .../{id}/marquer-lu/`, `.../marquer-tout-lu/`,
  `GET .../cle-vapid-publique/`, `POST·DELETE .../abonnements/`. Envoi
  **synchrone** dans la requête (pas de file d'attente dans ce projet) —
  point d'évolution : `transaction.on_commit` + worker.
- **117 → 194 tests** : annulation réservée admin (2 nouveaux + 6 adaptés),
  exports (4), gestion des comptes (15), filtre mouvements par fournisseur
  (1), répartition par type liste + détail (2), seuils de réappro manuels
  (5), bon de sortie enrichi (1), champs de réappro dynamique / coût
  fournisseur (4), régression soft-delete sur le comptage (1),
  `apps/dashboard` (21), et `apps/notifications` (19 : notif par utilisateur
  actif, franchissement de seuil / passage à zéro, épuisé prioritaire,
  réception sans alerte, API lecture scopée, abonnements, envoi push mocké —
  410 supprime l'abonnement, exception n'interrompt pas la validation, clé
  vide saute l'envoi). Tous verts.
- **Répartition par type sur le bon de sortie** (demandé après coup) —
  `apps/sorties/pdf.py::_tableau_repartition()` : tableau séparé (Type |
  Quantité sortie, + ligne Total) inséré entre les infos générales et le
  détail unité par unité, calculé via `collections.Counter` sur les lignes
  (un type à zéro n'est pas affiché). 194 → 195 tests (le nouveau ouvre le
  PDF généré avec `pdfplumber` et vérifie le texte extrait, pas seulement la
  taille du fichier).
- **Idempotence + écriture hors-ligne (Phase 2 frontend, demandé après coup)**
  — `apps/common/models.py::IdempotencyRecord` (`UUIDModel` seul, pas
  `SoftDeleteModel` — lignes immuables, unicité stricte voulue sur
  `(utilisateur, cle)`) + `apps/common/idempotence.py::executer_avec_idempotence(request, cle, executer)`,
  appelée explicitement en tête de 9 méthodes de vue (`SortieViewSet.create`/
  `.lignes`/`LigneSortieDetailView.delete`, mêmes trois pour `receptions` +
  `.plage`, `ClientViewSet`/`FournisseurViewSet.create`/`.update`) — pas de
  mixin ni de `dispatch()` surchargé, cohérent avec le style « tout est
  explicite » du projet. `request.headers.get("Idempotency-Key")` (insensible
  à la casse nativement, pas besoin de `META["HTTP_..."]`) ; sans clé fournie,
  comportement inchangé (passthrough). `CORS_ALLOW_HEADERS` étendu avec
  `"idempotency-key"` — sans ça, échec CORS silencieux invisible en test
  `APITestCase` (qui contourne le CORS), visible seulement dans un vrai
  navigateur.
  - **Règle d'ordre critique** : toute validation (`serializer.is_valid(raise_exception=True)`
    compris) doit s'exécuter **dans** le closure `executer()` passé à
    `executer_avec_idempotence()`, jamais avant — un rejeu qui revalide contre
    l'état déjà muté par le premier appel échoue sinon à tort (ex.
    `UniqueValidator` sur un `code` déjà créé). Bug réel rencontré et corrigé
    pendant l'implémentation : `ClientViewSet`/`FournisseurViewSet.create`
    validaient le serializer *avant* l'appel à `executer_avec_idempotence`,
    donc un rejeu avec la même clé recevait un 400 "code déjà utilisé" au
    lieu de la réponse 201 mise en cache.
  - **`IdempotencyRecord.corps` doit utiliser `DjangoJSONEncoder`** (pas
    l'encodeur JSON par défaut de `JSONField`) : `PrimaryKeyRelatedField.to_representation()`
    renvoie un `uuid.UUID` brut, que seul l'encodeur JSON *de rendu HTTP* de
    DRF sait sérialiser — sans l'encodeur explicite, `TypeError: Object of
    type UUID is not JSON serializable` plante **dans** la transaction, ce
    qui annule tout (y compris la ligne métier déjà créée par `executer()`).
  - **`_generer_reference()` durci** (`apps/sorties/services.py`,
    `apps/receptions/services.py`) — `SortieRepository.get_dernier_numero()`/
    `ReceptionRepository.get_dernier_numero()` avec `select_for_update()` ne
    protège que les lignes déjà existantes pour ce préfixe d'année : zéro
    protection à la bascule d'année, à la toute première ligne, ou entre deux
    rejeux idempotents concurrents — deux transactions calculent alors toutes
    deux `0001` et la seconde lève un `IntegrityError` brut, non intercepté.
    Boucle de retry (`NB_TENTATIVES_REFERENCE = 3`) autour d'un
    `transaction.atomic()` imbriqué (savepoint, isolé de la transaction
    ambiante de l'idempotence) dans `creer()`.
  - 195 → **209 tests** : `apps/common/test_idempotence_api.py` (5, via
    l'endpoint Sortie réel — dédoublonnage, non-régression sans clé, rejet
    cross-chemin, scindage par utilisateur), `ExecuterAvecIdempotenceTests`
    (3, unitaires), retry sur collision de référence (2, sorties + réceptions),
    idempotence création/modification (4, clients + fournisseurs).

## Conventions

- **Identifiants** : tous les modèles métier ont une clé primaire **UUID** (`apps.common.models.UUIDModel`), pas d'entier auto-incrémenté.
- **Suppression** : tous les modèles métier héritent de `apps.common.models.SoftDeleteModel` (via `BaseModel`) — `objects` (défaut, admin inclus) ne renvoie que les lignes actives ; `all_objects` renvoie tout, supprimé inclus ; `.delete()` renseigne `deleted_at` (`hard=True` pour une vraie suppression) ; `.restore()` annule la suppression. `apps.users.User` a sa propre composition de manager (voir `apps/users/models.py`) pour ne pas casser `createsuperuser`.
- **Audit** : tout service métier journalise ses actions via `apps.common.services.HistoriqueActionService.enregistrer(...)` — consultable en lecture seule dans l'admin (« Historique des actions »).
- **Vues** : chaque endpoint isolé (connexion, refresh, `/me/`) a sa propre classe dans `apps/users/views.py`, décorée `@extend_schema`. Un `GenericViewSet` complet est décoré une fois avec `@extend_schema_view(list=..., create=..., ...)`.
- **Versionnement** : toutes les routes métier sont sous `/api/v1/`. `/api/health/` et la documentation (`/api/schema/`, `/api/docs/...`) restent non versionnées.
- **Français** : code, noms de variables, messages d'erreur et docstrings en français.

### API disponible

```
POST /api/v1/auth/token/          {username, password} -> {access, refresh}
POST /api/v1/auth/token/refresh/  {refresh} -> {access, refresh}
POST /api/v1/auth/logout/         {refresh} -> 205, refresh mis sur liste noire
GET  /api/v1/auth/me/             utilisateur courant + rôle

GET/POST/PATCH/DELETE /api/v1/users/           lecture/écriture: admin uniquement (Jalon 6) — gestion des comptes et rôles

GET/POST/PATCH/DELETE /api/v1/fournisseurs/                       lecture: tous · écriture: admin
GET/PUT                /api/v1/fournisseurs/{id}/profil-extraction/  lecture: tous · écriture: admin
GET/POST/PATCH/DELETE /api/v1/clients/        lecture: tous · écriture: magasinier + admin
GET                    /api/v1/unites/        lecture: tous — écriture via sorties/retours/réceptions, filtres type/statut/fournisseur/sortie/reception
GET                    /api/v1/unites/lookup/?q=   résout code_interne ou numero_serie exact -> liste (vide/1/plusieurs)
POST                   /api/v1/unites/scanner/     OCR d'une photo (multipart "image") -> jetons détectés + unités résolues
GET                    /api/v1/unites/export/      export CSV — mêmes filtres que la liste, toutes les lignes (pas de pagination)
GET                    /api/v1/mouvements/    lecture: tous — journal d'audit du stock, filtres unite_stock/type_mouvement/sortie/reception/unite_stock__fournisseur
GET                    /api/v1/mouvements/export/  export CSV — idem

GET/POST              /api/v1/sorties/                          lecture: tous · écriture: magasinier + admin
GET/PATCH/DELETE       /api/v1/sorties/{id}/                     PATCH/DELETE uniquement si BROUILLON
GET/POST               /api/v1/sorties/{id}/lignes/
DELETE                  /api/v1/sorties/{id}/lignes/{ligneId}/
POST                   /api/v1/sorties/{id}/valider/
POST                   /api/v1/sorties/{id}/annuler/              motif obligatoire, réservé admin (Jalon 6)
GET                    /api/v1/sorties/{id}/bon-de-sortie.pdf/    disponible une fois VALIDEE
GET                    /api/v1/sorties/export/                    export CSV — mêmes filtres que la liste
GET                    /api/v1/projets/?q=                        autocomplétion du champ libre "projet"
POST                   /api/v1/retours/                           lecture: — · écriture: magasinier + admin

GET/POST              /api/v1/receptions/                          lecture: tous · écriture: magasinier + admin (REPRISE : admin seul ; ARRIVAGE : multipart avec fichier)
GET/PATCH/DELETE       /api/v1/receptions/{id}/                     PATCH/DELETE uniquement si BROUILLON
GET/POST               /api/v1/receptions/{id}/lignes/
DELETE                  /api/v1/receptions/{id}/lignes/{ligneId}/
POST                   /api/v1/receptions/{id}/lignes/plage/        génère une série de lignes (préfixe + début + fin)
POST                   /api/v1/receptions/{id}/extraire/            (re)lance l'extraction du PDF — ARRIVAGE BROUILLON uniquement
GET                    /api/v1/receptions/{id}/fichier/             sert le PDF via l'API (pas l'URL média brute)
POST                   /api/v1/receptions/{id}/valider/
POST                   /api/v1/receptions/{id}/annuler/             motif obligatoire, refusé si une unité est déjà sortie, réservé admin (Jalon 6)
GET                    /api/v1/receptions/export/                   export CSV — mêmes filtres que la liste
```
Filtres/recherche disponibles (`?search=`, `?ordering=`, champs de `filterset_fields` par vue) via django-filter.

### Documentation interactive

- Swagger UI : http://127.0.0.1:8000/api/docs/swagger/
- Redoc : http://127.0.0.1:8000/api/docs/redoc/
- Schéma OpenAPI brut : http://127.0.0.1:8000/api/schema/

Ouverts sans authentification (ce sont des descriptions de l'API, pas des données). Dans Swagger UI, bouton **Authorize** → coller `<access_token>` (récupéré via `/api/v1/auth/token/`) pour tester les endpoints protégés directement depuis la page.

### Comptes de dev

| username | password | rôle |
|---|---|---|
| admin | admin1234 | ADMIN |
| magasinier1 | magasinier1234 | MAGASINIER |
| lecteur1 | lecteur1234 | LECTURE |

### Données de dev

Fournisseurs `EBONT`, `DHL`, `LAF` déjà créés (seed manuel, pas encore de fixture).

## Avancement

**Jalon 1 — socle**

- [x] 1a — squelette Django + DRF, réglages via `.env`, `User` personnalisé (rôle), admin, `/api/health/`
- [x] 1b — modèles `Fournisseur`, `Client`, `UniteStock` + admin
- [x] id UUID + suppression logique sur tous les modèles
- [x] 1c — authentification JWT + `/me/` + permissions par rôle
- [x] 1d — projet frontend Next.js (`../oils-stock-web`, connexion, navigation)
- [x] Documentation API — Swagger UI + Redoc (drf-spectacular)
- [x] Architecture en couches Service/Repository, apps sous `apps/`, `/api/v1/`, tests automatisés
- [x] Logout réel (liste noire) + mot de passe oublié par code e-mail

**Jalon 2 — sorties & retours**

- [x] `Sortie` / `LigneSortie` (`apps/sorties/`) — CRUD, cycle brouillon → validée → annulée
- [x] `MouvementStock` (`apps/stock/`) — journal d'audit du stock, immuable
- [x] Retour d'une unité sortie (`apps/retours/`) — sans modèle dédié, compose `apps.stock`
- [x] Bon de sortie en PDF (`reportlab`)
- [x] Autocomplétion des projets, filtres client/statut/période sur les sorties
- [x] Écrans Next.js : liste, création, détail (validation/annulation/PDF), enregistrement d'un retour

**Jalon 3 — entrées manuelles & reprise**

- [x] `Reception` / `LigneReception` (`apps/receptions/`) — CRUD, cycle brouillon → validée → annulée
- [x] Saisie manuelle à l'unité et par plage, détection de doublon (déjà en stock ou déjà sur la réception)
- [x] Reprise de l'existant — réservée à l'admin, fournisseur créé à la volée par code si inconnu
- [x] Validation → `UniteStock` + `MouvementStock` `ENTREE` ; annulation → suppression logique, refusée si une unité est déjà sortie
- [x] Écrans Next.js : liste, nouvelle réception (saisie), reprise, détail/revue (lignes, plage, validation, annulation)
- [x] Tableau de bord : panneau « Mouvements de stock » et activité récente incluent désormais les réceptions

**Jalon 4 — extraction des documents**

- [x] Profil d'extraction par fournisseur (`mode_extraction`, `regex_numero_serie`, `type_article_defaut`)
- [x] Moteur d'extraction PDF (`pdfplumber`, sans OCR) — modes tableau/grille/texte, détection générique en repli
- [x] Détection de plage (préfixe + suffixe numérique), quantité annoncée auto-détectée
- [x] Upload du PDF d'arrivage (multipart), (ré)extraction sans perdre les corrections manuelles
- [x] Écrans Next.js : mode « Arrivage (PDF) » à la création, revue à deux volets (PDF + tableau) sur la fiche, réglage du profil d'extraction depuis la liste des fournisseurs

**Jalon 5 — OCR & scan mobile**

- [x] OCR en repli sur l'extraction PDF (page sans couche texte) — `apps/common/ocr.py`, `pytesseract`
- [x] `GET /unites/lookup/?q=` (résolution code interne/numéro de série) et `POST /unites/scanner/` (OCR d'une photo)
- [x] Écran `/scan` (Next.js) — caméra plein écran, résolution du numéro, mode « ajout à la sortie en cours »
- [x] HTTPS local — `runserver_plus` côté API, `next dev --experimental-https` côté frontend, même certificat mkcert réutilisé
- [x] Tesseract installé sur la machine de dev — 117 tests, tous verts, plus de `skip`
- [x] Vérification bout en bout de la reconnaissance OCR réelle — vrai bordereau Ebont scanné, extrait avec succès (48 numéros lus par OCR, doublons/A_VERIFIER corrects)

**Fournisseurs & clients — fiches complètes**

- [x] Création (`POST`, déjà supporté par l'API) branchée côté frontend — `/fournisseurs/nouveau`, `/clients/nouveau`
- [x] Fiche détail éditable (`PATCH`, déjà supporté) — `/fournisseurs/[id]`, `/clients/[id]`, petites stats réelles
- [x] Bug trouvé et corrigé : code réutilisé après suppression logique plantait en 500 — voir plus haut

**Jalon 6 — Pilotage & mise en production (volet applicatif)**

- [x] Annulation d'une sortie/réception validée réservée à l'admin (§09, note * du dossier de conception, tranchée)
- [x] Exports CSV (`unites`, `mouvements`, `sorties`, `receptions`), ouverts à tous les rôles, respectent les filtres
- [x] Gestion des comptes (`/api/v1/users/`, admin uniquement) — CRUD, rôles, actif/inactif, garde-fous dernier admin/propre compte
- [x] Écran `/parametres` (Next.js) — liste + création + édition inline (rôle, statut), plus un placeholder
- [x] Fiche fournisseur enrichie — répartition Flexitank/Heating pad, 5 dernières transactions (`GET /mouvements/?unite_stock__fournisseur=`, nouveau filtre)
- [x] Répartition Flexitank/Heating pad sur le bon de sortie PDF (tableau séparé, `_tableau_repartition()`)
- [x] Idempotence backend (`Idempotency-Key`, `IdempotencyRecord`) pour l'écriture hors-ligne du frontend (Phase 2) — 9 points d'application, `_generer_reference()` durci contre les collisions concurrentes
- [ ] Tableau de bord/statistiques enrichis (le tableau de bord existant depuis le Jalon 1 couvre déjà l'essentiel — pas retouché)
- [ ] Docker Compose + Caddy + sauvegardes automatiques (volet déploiement — pas commencé)
