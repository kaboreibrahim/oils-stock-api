"""
=============================================================================
 apps/users/repositories.py
 Seul point d'accès à User.objects / PasswordResetCode.objects en dehors de
 l'authentification JWT elle-même (qui reste gérée par simplejwt/Django).
=============================================================================
"""

from .models import PasswordResetCode, User


class UserRepository:
    @staticmethod
    def get_all():
        return User.objects.all().order_by("username")

    @staticmethod
    def get_by_id(user_id):
        return User.objects.filter(pk=user_id).first()

    @staticmethod
    def get_by_username(username: str):
        # `all_objects`, pas `objects` : `username` est unique au niveau base
        # sur TOUTES les lignes (supprimées incluses — suppression logique,
        # voir SoftDeleteModel). Ne vérifier que les comptes actifs laisserait
        # passer un nom déjà pris par un compte supprimé et ferait échouer la
        # création avec une IntegrityError brute (500) — même bug que celui
        # rencontré et corrigé sur fournisseurs/clients, évité ici d'emblée.
        return User.all_objects.filter(username=username).first()

    @staticmethod
    def get_by_email(email: str):
        return User.objects.filter(email__iexact=email).first()

    @staticmethod
    def create(*, username: str, password: str, **extra_fields) -> User:
        return User.objects.create_user(username=username, password=password, **extra_fields)

    @staticmethod
    def update(utilisateur: User, **data) -> User:
        for champ, valeur in data.items():
            setattr(utilisateur, champ, valeur)
        utilisateur.save()
        return utilisateur

    @staticmethod
    def delete(utilisateur: User) -> None:
        utilisateur.delete()  # suppression logique (SoftDeleteModel)

    @staticmethod
    def lister_actifs():
        # `User.objects` exclut déjà les comptes supprimés (SoftDeleteModel) mais
        # PAS les comptes désactivés — d'où le filtre `is_active` explicite.
        return User.objects.filter(is_active=True)

    @staticmethod
    def compter_admins_actifs(exclure_id=None):
        queryset = User.objects.filter(role=User.Role.ADMIN, is_active=True)
        if exclure_id is not None:
            queryset = queryset.exclude(pk=exclure_id)
        return queryset.count()


class PasswordResetCodeRepository:
    @staticmethod
    def create(**data) -> PasswordResetCode:
        return PasswordResetCode.objects.create(**data)

    @staticmethod
    def get_dernier_code_valide(utilisateur) -> PasswordResetCode | None:
        return (
            PasswordResetCode.objects
            .filter(utilisateur=utilisateur, utilise_le__isnull=True)
            .order_by("-created_at")
            .first()
        )

    @staticmethod
    def save(code: PasswordResetCode) -> PasswordResetCode:
        code.save()
        return code
