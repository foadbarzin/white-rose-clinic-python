"""Command-line administration (secure, one-time bootstrap; never an API).

Usage (from the repository root)::

    $env:PYTHONPATH = "backend"
    python -m app.cli bootstrap-owner --username owner --generate-password --confirm
    python -m app.cli status

The bootstrap is intentionally manual: it refuses to run when any active user
already exists, it never uses a default password, and the generated password is
printed exactly once (the account must change it at first login).
"""

from __future__ import annotations

import argparse
import secrets
import string
import sys

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.exceptions import WrcError
from app.core.permissions import PERMISSION_CODES
from app.core.security import hash_password, validate_password_strength
from app.database.models.identity import User
from app.database.models.rbac import Role, RolePermission, UserRole
from app.database.session import session_scope
from app.services.audit import AuditService

PASSWORD_ALPHABET = string.ascii_letters + string.digits + "!@#$%^&*-_=+"
SYSTEM_ROLE_CODE = "owner"


def _generate_password(length: int = 20) -> str:
    rng = secrets.SystemRandom()
    while True:
        candidate = "".join(rng.choice(PASSWORD_ALPHABET) for _ in range(length))
        if (
            any(char.islower() for char in candidate)
            and any(char.isupper() for char in candidate)
            and any(char.isdigit() for char in candidate)
            and any(char in "!@#$%^&*-_=+" for char in candidate)
        ):
            return candidate


def _ensure_owner_role(session) -> Role:
    role = session.scalar(select(Role).where(Role.code == SYSTEM_ROLE_CODE))
    if role is None:
        role = Role(
            code=SYSTEM_ROLE_CODE,
            name="مالک سیستم",
            description="نقش سیستمی با تمام مجوزها؛ فقط از طریق Bootstrap امن ساخته می‌شود.",
            is_system=True,
            is_active=True,
            legacy_role="admin",
        )
        session.add(role)
        session.flush()
    existing = set(
        session.scalars(
            select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
        )
    )
    for code in sorted(PERMISSION_CODES - existing):
        session.add(RolePermission(role_id=role.id, permission_code=code))
    session.flush()
    return role


def bootstrap_owner(
    username: str,
    password: str,
    display_name: str,
    *,
    generated: bool,
) -> dict[str, object]:
    settings = get_settings()
    username = (username or "").strip().lower()
    if len(username) < 3:
        raise SystemExit("نام کاربری باید حداقل ۳ نویسه باشد.")
    validate_password_strength(password, username=username)

    with session_scope() as session:
        active_users = int(
            session.scalar(
                select(func.count())
                .select_from(User)
                .where(User.is_deleted.is_(False), User.is_active.is_(True))
            )
            or 0
        )
        if active_users:
            raise SystemExit(
                "Bootstrap مسدود شد: کاربر فعال در سیستم وجود دارد. "
                "برای مدیریت از حساب مالک موجود استفاده کنید."
            )
        if session.scalar(select(func.count()).select_from(User).where(User.username == username)):
            raise SystemExit("نام کاربری تکراری است.")

        role = _ensure_owner_role(session)
        hashed = hash_password(
            password,
            pepper=settings.secret_key,
            memory_kib=settings.argon2_memory_kib,
            time_cost=settings.argon2_time_cost,
            parallelism=settings.argon2_parallelism,
        )
        user = User(
            username=username,
            password_hash=hashed.encoded,
            password_algo=hashed.algo,
            password_params=hashed.params,
            display_name=(display_name or "مالک سیستم").strip()[:120],
            role="admin",
            is_active=True,
            must_change_password=True,
            failed_attempts=0,
        )
        session.add(user)
        session.flush()
        session.add(UserRole(user_id=user.id, role_id=role.id))
        AuditService.log(
            session,
            action="auth.bootstrap_owner",
            entity="users",
            entity_id=user.id,
            actor_username="bootstrap",
            details={
                "username": user.username,
                "role": role.code,
                "generated_password": bool(generated),
            },
        )
        session.flush()
        return {
            "username": user.username,
            "user_id": str(user.id),
            "role": role.code,
            "password_generated": generated,
        }


def _status() -> dict[str, object]:
    with session_scope() as session:
        users = int(session.scalar(select(func.count()).select_from(User)) or 0)
        active = int(
            session.scalar(
                select(func.count()).select_from(User).where(User.is_active.is_(True))
            )
            or 0
        )
        roles = int(session.scalar(select(func.count()).select_from(Role)) or 0)
        return {"users": users, "active_users": active, "roles": roles}


def _read_password(args: argparse.Namespace) -> tuple[str, bool]:
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
        if not password:
            raise SystemExit("رمز از stdin خالی است.")
        return password, False
    if args.generate_password:
        return _generate_password(), True
    raise SystemExit("یکی از --generate-password یا --password-stdin الزامی است.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="wrc-admin", description="White Rose Clinic admin CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    boot = sub.add_parser("bootstrap-owner", help="create the first owner account (one-time)")
    boot.add_argument("--username", default="owner")
    boot.add_argument("--display-name", default="مالک سیستم")
    boot.add_argument("--generate-password", action="store_true")
    boot.add_argument("--password-stdin", action="store_true")
    boot.add_argument("--confirm", action="store_true", help="required explicit confirmation")

    sub.add_parser("status", help="show non-sensitive counts")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "status":
            data = _status()
            print(
                f"users={data['users']} active_users={data['active_users']} roles={data['roles']}"
            )
            return 0

        if args.command == "bootstrap-owner":
            if not args.confirm:
                raise SystemExit(
                    "برای Bootstrap، پرچم --confirm الزامی است (اقدام صریح مالک سیستم)."
                )
            password, generated = _read_password(args)
            result = bootstrap_owner(
                args.username, password, args.display_name, generated=generated
            )
            print("Bootstrap انجام شد.")
            print(f"نام کاربری: {result['username']}")
            print(f"نقش: {result['role']}")
            if generated:
                print("رمز یک‌بارمصرف (فقط همین یک بار نمایش داده می‌شود):")
                print(password)
            print("در اولین ورود، تغییر رمز الزامی است.")
            return 0
    except WrcError as exc:
        print(f"خطا: {exc.message} ({exc.code})", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

