"""
Command-line tool for the server owner to manage accounts (there is no e-mail password reset).

    python manage_users.py list
    python manage_users.py reset-password someone@example.com        (asks for the new password)
    python manage_users.py disable someone@example.com               (cannot sign in; data is kept)
    python manage_users.py enable someone@example.com
    python manage_users.py signout-all someone@example.com           (ends all of their sessions)

It works on the database named in backend/.env (DATABASE_URL), so run it from the backend folder on the same
machine as the server (or against the same DATABASE_URL).
"""
import getpass
import sys

import auth
import models
from database import SessionLocal


def _user(db, email: str) -> models.User:
    user = db.query(models.User).filter(models.User.email == (email or "").strip().lower()).first()
    if user is None:
        raise SystemExit(f"No account with the e-mail {email!r}. Use 'list' to see the accounts.")
    return user


def list_users(db) -> None:
    rows = db.query(models.User).order_by(models.User.id).all()
    if not rows:
        print("No accounts yet.")
        return
    owner = auth.owner_user_id(db)
    for u in rows:
        flags = [f for f, on in (("owner", u.id == owner), ("disabled", not u.is_active), ("telegram", bool(u.telegram_chat_id))) if on]
        last = u.last_login_at.strftime("%Y-%m-%d %H:%M") if u.last_login_at else "never"
        print(f"{u.id:>3}  {u.email:<36} {u.name or '':<22} last sign-in: {last:<17} {' '.join(flags)}")


def reset_password(db, email: str, new_password: str = None) -> None:
    user = _user(db, email)
    if new_password is None:
        new_password = getpass.getpass("New password: ")
        if new_password != getpass.getpass("Repeat it: "):
            raise SystemExit("The two passwords differ. Nothing was changed.")
    try:
        auth.validate_password(new_password)
    except Exception as exc:
        raise SystemExit(getattr(exc, "detail", str(exc)))
    user.password_hash = auth.hash_password(new_password)
    user.token_version = int(user.token_version or 0) + 1      # signs the user out everywhere
    db.commit()
    print(f"Password changed for {user.email}. Their old sessions no longer work.")


def set_active(db, email: str, active: bool) -> None:
    user = _user(db, email)
    user.is_active = active
    if not active:
        user.token_version = int(user.token_version or 0) + 1
    db.commit()
    print(f"{user.email} is now {'enabled' if active else 'disabled'}.")


def sign_out_all(db, email: str) -> None:
    user = _user(db, email)
    user.token_version = int(user.token_version or 0) + 1
    db.commit()
    print(f"All sessions of {user.email} were ended.")


def main(argv: list) -> int:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    command, args = argv[0], argv[1:]
    db = SessionLocal()
    try:
        if command == "list":
            list_users(db)
        elif command == "reset-password" and len(args) == 1:
            reset_password(db, args[0])
        elif command in ("disable", "enable") and len(args) == 1:
            set_active(db, args[0], command == "enable")
        elif command == "signout-all" and len(args) == 1:
            sign_out_all(db, args[0])
        else:
            print(__doc__)
            return 2
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
