"""CLI de gestión del license server: claves, clientes y licencias."""

import argparse
import datetime as _dt
import json
import os
import sys

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from sqlalchemy import create_engine

from . import db as license_db
from .signing import sign_claims

_PRIVATE_KEY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "private_key.pem")
_PUBLIC_KEY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "licensing", "novus_public.pem")


def _engine():
    path = os.environ.get("NOVUS_LICENSE_DB", os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "novus_license.db"))
    return create_engine(f"sqlite:///{path}")


def _to_epoch(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        pass
    text_value = value.strip()
    if len(text_value) == 10:
        dt = _dt.datetime.strptime(text_value, "%Y-%m-%d")
    else:
        dt = _dt.datetime.fromisoformat(text_value)
    return int(dt.replace(tzinfo=_dt.timezone.utc).timestamp())


def _parse_modules(items):
    modules = {}
    for item in items or []:
        if "=" in item:
            name, _, raw = item.partition("=")
            modules[name.strip()] = raw.strip().lower() in ("1", "true", "yes", "on")
        else:
            modules[item.strip()] = True
    return modules


def _parse_limits(items):
    limits = {}
    for item in items or []:
        name, _, value = item.partition("=")
        limits[name.strip()] = int(value)
    return limits


def cmd_keygen():
    if os.path.exists(_PRIVATE_KEY_PATH):
        print(f"[error] ya existe {_PRIVATE_KEY_PATH}; bórralo para regenerar")
        return 1
    private_key = ed25519.Ed25519PrivateKey.generate()
    priv_pem = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption())
    pub_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    os.makedirs(os.path.dirname(_PRIVATE_KEY_PATH), exist_ok=True)
    os.makedirs(os.path.dirname(_PUBLIC_KEY_PATH), exist_ok=True)
    with open(_PRIVATE_KEY_PATH, "wb") as fh:
        fh.write(priv_pem)
    os.chmod(_PRIVATE_KEY_PATH, 0o600)
    with open(_PUBLIC_KEY_PATH, "wb") as fh:
        fh.write(pub_pem)
    print(f"[ok] clave privada -> {_PRIVATE_KEY_PATH}")
    print(f"[ok] clave pública  -> {_PUBLIC_KEY_PATH}")
    return 0


def cmd_customer_add(args):
    engine = _engine()
    license_db.init_db(engine)
    secret = os.environ.get("NOVUS_LICENSE_SERVER_SECRET", "")
    try:
        license_db.create_customer(engine, args.id, args.name,
                                   license_db.hash_api_key(secret, args.api_key))
    except Exception as exc:
        print(f"[error] no se pudo crear el cliente: {exc}")
        return 1
    print(f"[ok] cliente '{args.id}' creado")
    return 0


def cmd_customer_list(_args):
    engine = _engine()
    license_db.init_db(engine)
    for c in license_db.list_customers(engine):
        print(f"#{c.id} {c.customer_id}  {c.name}  [{c.status}]  {c.created_at}")
    return 0


def cmd_customer_disable(args):
    license_db.set_customer_status(_engine(), args.id, "disabled")
    print(f"[ok] cliente '{args.id}' deshabilitado")
    return 0


def cmd_license_issue(args):
    engine = _engine()
    license_db.init_db(engine)
    if license_db.get_customer(engine, args.customer) is None:
        print(f"[error] cliente '{args.customer}' no existe")
        return 1
    valid_from = _to_epoch(args.valid_from) if args.valid_from else int(
        _dt.datetime.now(_dt.timezone.utc).timestamp())
    try:
        license_db.issue_license(engine, args.customer, args.license_id,
                                 valid_from, _to_epoch(args.valid_until),
                                 args.grace_days, _parse_modules(args.modules),
                                 _parse_limits(args.limit))
    except Exception as exc:
        print(f"[error] no se pudo emitir la licencia: {exc}")
        return 1
    lic = license_db.get_license_by_id(engine, args.license_id)
    now = int(_dt.datetime.now(_dt.timezone.utc).timestamp())
    claims = {
        "customer_id": lic["customer_id"],
        "license_id": lic["license_id"],
        "status": lic["status"],
        "valid_from": lic["valid_from"],
        "valid_until": lic["valid_until"],
        "offline_until": lic["offline_until"],
        "modules": lic["modules"],
        "limits": lic["limits"],
        "iat": now,
        "exp": lic["offline_until"],
    }
    with open(_PRIVATE_KEY_PATH, "rb") as fh:
        private_key_pem = fh.read()
    token = sign_claims(claims, private_key_pem)
    print(f"[ok] licencia '{args.license_id}' emitida para '{args.customer}'")
    print(f"JWT:\n{token}")
    return 0


def cmd_license_renew(args):
    engine = _engine()
    if license_db.get_license_by_id(engine, args.license_id) is None:
        print(f"[error] licencia '{args.license_id}' no existe")
        return 1
    valid_from = _to_epoch(args.valid_from) if args.valid_from else int(
        _dt.datetime.now(_dt.timezone.utc).timestamp())
    license_db.renew_license(engine, args.license_id, valid_from,
                             _to_epoch(args.valid_until), args.grace_days)
    print(f"[ok] licencia '{args.license_id}' renovada")
    return 0


def cmd_license_suspend(args):
    license_db.set_license_status(_engine(), args.license_id, "suspended", "suspended")
    print(f"[ok] licencia '{args.license_id}' suspendida")
    return 0


def cmd_license_revoke(args):
    license_db.set_license_status(_engine(), args.license_id, "revoked", "revoked")
    print(f"[ok] licencia '{args.license_id}' revocada")
    return 0


def cmd_license_show(args):
    lic = license_db.get_license_by_id(_engine(), args.license_id)
    if lic is None:
        print(f"[error] licencia '{args.license_id}' no existe")
        return 1
    print(json.dumps(lic, indent=2, sort_keys=True))
    return 0


def cmd_license_list(args):
    for lic in license_db.list_licenses(_engine(), getattr(args, "customer", None)):
        print(f"{lic['license_id']}  {lic['customer_id']}  [{lic['status']}]  "
              f"valida={lic['valid_until']}")
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(prog="license-server")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("keygen", help="Genera el par de claves ed25519")

    c = sub.add_parser("customer", help="Gestiona clientes")
    csub = c.add_subparsers(dest="customer_action", required=True)
    ca = csub.add_parser("add")
    ca.add_argument("--id", required=True)
    ca.add_argument("--name", required=True)
    ca.add_argument("--api-key", required=True)
    csub.add_parser("list")
    cd = csub.add_parser("disable")
    cd.add_argument("--id", required=True)

    l = sub.add_parser("license", help="Gestiona licencias")
    lsub = l.add_subparsers(dest="license_action", required=True)
    li = lsub.add_parser("issue")
    li.add_argument("--customer", required=True)
    li.add_argument("--license-id", required=True)
    li.add_argument("--valid-until", required=True)
    li.add_argument("--valid-from", default=None)
    li.add_argument("--grace-days", type=int, default=7)
    li.add_argument("--modules", nargs="*", default=[])
    li.add_argument("--limit", nargs="*", default=[])
    lr = lsub.add_parser("renew")
    lr.add_argument("--license-id", required=True)
    lr.add_argument("--valid-until", required=True)
    lr.add_argument("--valid-from", default=None)
    lr.add_argument("--grace-days", type=int, default=7)
    for action_name in ("suspend", "revoke"):
        p = lsub.add_parser(action_name)
        p.add_argument("--license-id", required=True)
    ls = lsub.add_parser("show")
    ls.add_argument("--license-id", required=True)
    ll = lsub.add_parser("list")
    ll.add_argument("--customer", default=None)

    args = parser.parse_args(argv)
    if args.command == "keygen":
        return cmd_keygen()
    if args.command == "customer":
        if args.customer_action == "add":
            return cmd_customer_add(args)
        if args.customer_action == "list":
            return cmd_customer_list(args)
        if args.customer_action == "disable":
            return cmd_customer_disable(args)
    if args.command == "license":
        if args.license_action == "issue":
            return cmd_license_issue(args)
        if args.license_action == "renew":
            return cmd_license_renew(args)
        if args.license_action == "suspend":
            return cmd_license_suspend(args)
        if args.license_action == "revoke":
            return cmd_license_revoke(args)
        if args.license_action == "show":
            return cmd_license_show(args)
        if args.license_action == "list":
            return cmd_license_list(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
