"""Random public identifiers (Q3a, O6): what responses use instead of primary keys."""

import secrets

_ALPHABET = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford base32, lowercase
PUBLIC_ID_LENGTH = 16


def new_public_id() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(PUBLIC_ID_LENGTH))
