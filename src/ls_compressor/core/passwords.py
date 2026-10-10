"""Local password strength estimation for the GUI meter."""

import math
import re
from enum import StrEnum
from itertools import pairwise

_COMMON_PASSWORDS = {
    "password",
    "123456",
    "12345678",
    "qwerty",
    "letmein",
    "admin",
    "welcome",
    "iloveyou",
    "monkey",
    "dragon",
}


class PasswordStrength(StrEnum):
    """Qualitative password strength bands shown by the meter."""

    WEAK = "weak"
    FAIR = "fair"
    GOOD = "good"
    STRONG = "strong"

    @property
    def display_name(self) -> str:
        """Return the human-readable band name."""
        return {
            self.WEAK: "Weak",
            self.FAIR: "Fair",
            self.GOOD: "Good",
            self.STRONG: "Strong",
        }[self]


def _charset_pool(password: str) -> int:
    """Estimate the character pool size a password draws from."""
    pool = 0
    if any(c.islower() for c in password):
        pool += 26
    if any(c.isupper() for c in password):
        pool += 26
    if any(c.isdigit() for c in password):
        pool += 10
    if any(not c.isalnum() for c in password):
        pool += 33
    return max(pool, 1)


def _has_obvious_pattern(password: str) -> bool:
    """Return True for runs, repeats, or keyboard sequences."""
    lowered = password.lower()
    if lowered in _COMMON_PASSWORDS:
        return True
    if re.fullmatch(r"(.)\1{3,}", lowered):
        return True
    digits = [ord(c) for c in lowered]
    sequential = all(b - a == 1 for a, b in pairwise(digits))
    reverse = all(a - b == 1 for a, b in pairwise(digits))
    return sequential or reverse


def password_entropy_bits(password: str) -> float:
    """Estimate password entropy in bits from length and charset pool."""
    if not password:
        return 0.0
    return len(password) * math.log2(_charset_pool(password))


def password_strength(password: str) -> PasswordStrength:
    """Classify a password into a strength band.

    Bands follow entropy thresholds with a hard cap for obvious patterns:
    <40 bits weak, <60 fair, <80 good, otherwise strong.
    """
    if not password or len(password) < 4:
        return PasswordStrength.WEAK
    entropy = password_entropy_bits(password)
    if _has_obvious_pattern(password):
        return PasswordStrength.WEAK
    if entropy < 40:
        return PasswordStrength.WEAK
    if entropy < 60:
        return PasswordStrength.FAIR
    if entropy < 80:
        return PasswordStrength.GOOD
    return PasswordStrength.STRONG
