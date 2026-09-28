"""Password hashing, token generation, and the password policy.

Argon2id with library defaults: the parameters are deliberately not tuned here,
because a hand-picked `time_cost` that is wrong for the machine it deploys to is
worse than the library's considered default.
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# The same object the app uses everywhere, so a hash written by one code path
# verifies in another. Raising `rehash_needs` is a future migration, not a
# v1 concern.
_hasher = PasswordHasher()

# A token is 32 bytes of `secrets.token_urlsafe`, roughly 256 bits. At that
# entropy a fast hash is the right choice for storage: a slow one protects
# nothing an attacker holding the hash could not already do, and would only slow
# redemption.
TOKEN_ENTROPY_BYTES = 32

# A username shorter than this is too short to make a meaningful password
# check, and would reject innocuous passwords containing "a" or "jo".
MIN_USERNAME_IN_PASSWORD_CHECK = 3

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 200

# Long enough to exclude the credential-stuffing staples. No composition rules:
# length is what actually helps, and rules that force `Passw0rd!` make things
# worse by pushing people towards predictable substitutions.
COMMON_PASSWORDS = frozenset(
    {
        "passwordpassword",
        "123456789012",
        "qwertyuiop12",
        "letmeinplease",
        "iloveyou1234",
        "administrator",
        "bmtrackeradmin",
        "correcthorseb",
    }
)


def hash_password(password: str) -> str:
    """Return an argon2id hash of a password.

    Args:
        password: The plaintext password.

    Returns:
        The encoded hash, which embeds its own parameters.

    """
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Return whether a password matches a stored hash.

    A malformed or missing hash returns False rather than raising, because this
    is called on the sign-in path where a corrupt row must fail the login, not
    the request.

    Args:
        password: The plaintext password to check.
        password_hash: The stored hash.

    Returns:
        Whether they match.

    """
    if not password_hash:
        return False
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    """Return whether a hash was made with weaker parameters than current.

    Args:
        password_hash: The stored hash.

    Returns:
        Whether the password should be re-hashed on next successful sign-in.

    """
    if not password_hash:
        return True
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


def generate_token() -> str:
    """Return a fresh, cryptographically random token.

    Returns:
        A URL-safe token with 256 bits of entropy.

    """
    return secrets.token_urlsafe(TOKEN_ENTROPY_BYTES)


def hash_token(raw_token: str) -> str:
    """Return the stored form of a token.

    Only the hash is persisted, so a database dump yields nothing that can be
    redeemed.

    Args:
        raw_token: The token as generated and handed to the user.

    Returns:
        A hex SHA-256 digest.

    """
    return hashlib.sha256(raw_token.encode()).hexdigest()


def tokens_match(raw_token: str, stored_hash: str) -> bool:
    """Return whether a presented token matches a stored hash.

    Compares in constant time so that a mismatch does not leak, through timing,
    how much of the digest was correct.

    Args:
        raw_token: The token from the request.
        stored_hash: The digest on file.

    Returns:
        Whether they match.

    """
    return secrets.compare_digest(hash_token(raw_token), stored_hash)


def check_password_policy(password: str, username: str) -> None:
    """Raise `ValueError` if a password is unacceptable.

    Args:
        password: The candidate password.
        username: The account it belongs to, checked against the password so
            that "cal1234" is not acceptable for user "cal".

    Raises:
        ValueError: If the password is too short, too long, obviously common, or
            contains the username.

    """
    if len(password) < MIN_PASSWORD_LENGTH:
        msg = f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
        raise ValueError(msg)
    if len(password) > MAX_PASSWORD_LENGTH:
        msg = f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
        raise ValueError(msg)

    lowered = password.lower()
    if lowered in COMMON_PASSWORDS:
        msg = "That password is far too common."
        raise ValueError(msg)
    if (
        username
        and len(username) >= MIN_USERNAME_IN_PASSWORD_CHECK
        and username.lower() in lowered
    ):
        msg = "The password must not contain your username."
        raise ValueError(msg)
