"""Tests for password strength estimation."""

from ls_compressor.core.passwords import (
    PasswordStrength,
    password_entropy_bits,
    password_strength,
)


def test_empty_and_short_passwords_are_weak() -> None:
    """Empty and very short passwords never pass the weak band."""
    assert password_strength("") is PasswordStrength.WEAK
    assert password_strength("abc") is PasswordStrength.WEAK
    assert password_entropy_bits("") == 0.0


def test_common_passwords_are_always_weak() -> None:
    """Well-known passwords are rejected regardless of length."""
    assert password_strength("password") is PasswordStrength.WEAK
    assert password_strength("12345678") is PasswordStrength.WEAK
    assert password_strength("qwerty") is PasswordStrength.WEAK


def test_obvious_patterns_are_weak() -> None:
    """Runs and repeats do not earn entropy credit."""
    assert password_strength("aaaaaaaa") is PasswordStrength.WEAK
    assert password_strength("abcdefgh") is PasswordStrength.WEAK
    assert password_strength("87654321") is PasswordStrength.WEAK


def test_strength_bands_follow_entropy() -> None:
    """Longer mixed passwords climb the strength bands."""
    weak = password_strength("abc1")
    fair = password_strength("Somewhat1")
    good = password_strength("Much-better-9")
    strong = password_strength("Tr0ub4dor&3-Ext#mely-L0ng-P@ssphr@se")

    assert weak is PasswordStrength.WEAK
    assert fair in {PasswordStrength.FAIR, PasswordStrength.GOOD}
    assert good in {PasswordStrength.GOOD, PasswordStrength.STRONG}
    assert strong is PasswordStrength.STRONG
    assert password_entropy_bits("Tr0ub4dor&3") > password_entropy_bits("abc1")


def test_strength_display_names() -> None:
    """Every band has a user-facing label."""
    assert PasswordStrength.WEAK.display_name == "Weak"
    assert PasswordStrength.STRONG.display_name == "Strong"
