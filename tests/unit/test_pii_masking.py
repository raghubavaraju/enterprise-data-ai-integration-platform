"""Masking must be irreversible, entitlement-driven, and still leave the record usable."""
from __future__ import annotations

import pytest

from common.pii import (
    apply_profile_masking,
    mask_birth_date,
    mask_email,
    mask_full_name,
    mask_phone,
    pseudonymise,
    redact_for_ai,
)


class TestFieldMasking:
    def test_email_keeps_only_the_first_character_and_the_domain(self):
        masked = mask_email("sofia.chen@example.com")
        assert masked.startswith("s")
        assert masked.endswith("@example.com")
        assert "sofia.chen" not in masked
        assert "ofia" not in masked

    def test_phone_keeps_only_the_last_four_digits(self):
        assert mask_phone("+1-402-555-1005") == "***-***-1005"
        assert "402" not in mask_phone("+1-402-555-1005")

    def test_birth_date_is_generalised_to_year(self):
        # A full date of birth is a quasi-identifier: with a postcode it
        # re-identifies most people. The year alone does not.
        assert mask_birth_date("1960-04-17") == "1960-**-**"

    def test_full_name_keeps_the_given_name(self):
        # Masking the whole name makes the record unusable to an agent, which is
        # how masking ends up switched off. Keeping the given name is the
        # compromise that survives contact with operations.
        masked = mask_full_name("Sofia Chen")
        assert masked.startswith("Sofia ")
        assert "Chen" not in masked

    def test_single_word_name_is_left_alone(self):
        assert mask_full_name("Prince") == "Prince"

    @pytest.mark.parametrize("value", [None, ""])
    def test_maskers_tolerate_missing_values(self, value):
        assert mask_email(value) == value
        assert mask_phone(value) == value
        assert mask_full_name(value) == value


class TestProfileMasking:
    PROFILE = {"fullName": "Sofia Chen", "email": "sofia.chen@example.com",
               "phone": "+1-402-555-1005", "birthDate": "1960-04-17",
               "segment": "PREMIUM", "tenureDays": 629}

    def test_entitled_caller_sees_the_real_values(self):
        assert apply_profile_masking(self.PROFILE, allowed=True) == self.PROFILE

    def test_unentitled_caller_sees_nothing_identifying(self):
        masked = apply_profile_masking(self.PROFILE, allowed=False)
        blob = str(masked)
        assert "sofia.chen@example.com" not in blob
        assert "Chen" not in blob
        assert "1005" in blob          # last four digits are intentionally kept
        assert masked["_masked"] is True

    def test_non_identifying_fields_survive_masking(self):
        # Masking that destroys the useful part of the record gets turned off.
        masked = apply_profile_masking(self.PROFILE, allowed=False)
        assert masked["segment"] == "PREMIUM"
        assert masked["tenureDays"] == 629

    def test_masking_does_not_invent_fields_that_were_absent(self):
        # Emitting a masked placeholder for a field the response never carried
        # tells the client the field exists, which is itself a disclosure.
        masked = apply_profile_masking({"segment": "PREMIUM"}, allowed=False)
        assert "email" not in masked
        assert masked["_maskedFields"] == []


class TestAiRedaction:
    def test_direct_identifiers_are_stripped_before_leaving_the_boundary(self):
        text = ("Contact me on sofia.chen@example.com or +1-402-555-1005, "
                "card 4111 1111 1111 1111.")
        clean = redact_for_ai(text)
        assert "sofia.chen@example.com" not in clean
        assert "402" not in clean
        assert "4111" not in clean
        assert "[EMAIL_REDACTED]" in clean
        assert "[CARD_REDACTED]" in clean

    def test_ordinary_text_is_left_intact(self):
        text = "The parcel arrived two days late and the carton was crushed."
        assert redact_for_ai(text) == text


class TestPseudonymisation:
    def test_is_stable_and_non_reversible(self):
        a, b = pseudonymise("CRM-100005"), pseudonymise("CRM-100005")
        assert a == b, "the same input must always map to the same pseudonym"
        assert "CRM-100005" not in a
        assert pseudonymise("CRM-100006") != a
