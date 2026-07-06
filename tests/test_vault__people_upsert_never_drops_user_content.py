"""People upsert: insert-only merge — user content is never dropped or edited.

Covers: card creation shape, missing-key insertion, user-set values never
overwritten (even when empty), byte-exact preservation of user body text,
wikilink append-once idempotency, aliased-link detection, cards without
frontmatter, unterminated frontmatter failing closed, and files missing a
trailing newline.
"""

from pathlib import Path

import pytest

from engine.vault.frontmatter_codec import parse_frontmatter
from engine.vault.people_contact_writer import upsert_person_note
from engine.vault.vault_errors import FrontmatterFormatError


def test_new_card_has_frontmatter_heading_and_meeting_links(tmp_path: Path) -> None:
    path = upsert_person_note(
        tmp_path,
        name="Alice O'Hara",
        phone="+44 7700 900123",
        email="alice@example.com",
        company="Acme Ltd",
        meeting_note_stems=["2026-07-06 Weekly Sync"],
    )
    assert path == tmp_path / "People" / "Alice O'Hara.md"
    text = path.read_text(encoding="utf-8")
    fields, body = parse_frontmatter(text)
    assert fields == {
        "phone": "+44 7700 900123",
        "email": "alice@example.com",
        "company": "Acme Ltd",
    }
    assert "# Alice O'Hara" in body
    assert "## Meetings" in body
    assert "- [[2026-07-06 Weekly Sync]]" in body


def test_none_fields_are_omitted_from_new_cards(tmp_path: Path) -> None:
    path = upsert_person_note(tmp_path, name="Bob")
    fields, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    assert fields == {}


def test_upsert_inserts_missing_keys_only(tmp_path: Path) -> None:
    upsert_person_note(tmp_path, name="Carol", email="c@example.com")
    path = upsert_person_note(
        tmp_path, name="Carol", email="DIFFERENT@example.com", company="NewCo"
    )
    fields, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
    assert fields["email"] == "c@example.com"  # existing value wins, never overwritten
    assert fields["company"] == "NewCo"  # missing key inserted


def test_user_blanked_field_is_respected_not_refilled(tmp_path: Path) -> None:
    """A key the user set to empty is still THEIR decision — never overwritten."""
    card = tmp_path / "People" / "Dave.md"
    card.parent.mkdir(parents=True)
    card.write_text("---\nphone:\n---\n\n# Dave\n", encoding="utf-8")
    upsert_person_note(tmp_path, name="Dave", phone="+1 555 0100")
    text = card.read_text(encoding="utf-8")
    assert "+1 555 0100" not in text
    assert "phone:\n" in text


def test_upsert_preserves_user_body_bytes_exactly(tmp_path: Path) -> None:
    card = tmp_path / "People" / "Erin.md"
    card.parent.mkdir(parents=True)
    user_body = (
        "\n# Erin\n\nUser paragraph with 评审 🚀 and trailing spaces   \n"
        "\tindented user line\n\n## Meetings\n\n- [[2026-01-01 Kickoff]]\n"
    )
    card.write_text(f"---\nemail: e@example.com\n---{user_body}", encoding="utf-8")
    upsert_person_note(
        tmp_path,
        name="Erin",
        company="Acme",
        meeting_note_stems=["2026-07-06 Weekly Sync"],
    )
    text = card.read_text(encoding="utf-8")
    # Every user-authored body line survives verbatim.
    for line in user_body.split("\n"):
        assert line in text.split("\n")
    assert "company: Acme" in text
    assert "- [[2026-07-06 Weekly Sync]]" in text


def test_new_link_lands_after_last_existing_link_under_meetings(tmp_path: Path) -> None:
    card = tmp_path / "People" / "Frank.md"
    card.parent.mkdir(parents=True)
    card.write_text(
        "# Frank\n\n## Meetings\n\n- [[Old A]]\n- [[Old B]]\n\nUser afterword.\n",
        encoding="utf-8",
    )
    upsert_person_note(tmp_path, name="Frank", meeting_note_stems=["New C"])
    lines = card.read_text(encoding="utf-8").split("\n")
    assert lines.index("- [[New C]]") == lines.index("- [[Old B]]") + 1
    assert lines.index("- [[New C]]") < lines.index("User afterword.")


def test_upsert_is_idempotent_second_identical_call_changes_nothing(tmp_path: Path) -> None:
    upsert_person_note(
        tmp_path, name="Grace", email="g@example.com", meeting_note_stems=["Sync"]
    )
    path = tmp_path / "People" / "Grace.md"
    once = path.read_bytes()
    upsert_person_note(
        tmp_path, name="Grace", email="g@example.com", meeting_note_stems=["Sync"]
    )
    assert path.read_bytes() == once


def test_aliased_existing_link_counts_as_present(tmp_path: Path) -> None:
    card = tmp_path / "People" / "Heidi.md"
    card.parent.mkdir(parents=True)
    card.write_text("# Heidi\n\n## Meetings\n\n- [[Sync|the sync]]\n", encoding="utf-8")
    upsert_person_note(tmp_path, name="Heidi", meeting_note_stems=["Sync"])
    text = card.read_text(encoding="utf-8")
    assert text.count("[[Sync") == 1  # not appended again


def test_card_without_frontmatter_gets_block_prepended_user_bytes_intact(
    tmp_path: Path,
) -> None:
    card = tmp_path / "People" / "Ivan.md"
    card.parent.mkdir(parents=True)
    user_text = "# Ivan\nUser wrote this without frontmatter.\n"
    card.write_text(user_text, encoding="utf-8")
    upsert_person_note(tmp_path, name="Ivan", email="i@example.com")
    text = card.read_text(encoding="utf-8")
    assert text.startswith("---\nemail: i@example.com\n---\n")
    assert user_text in text


def test_unterminated_frontmatter_fails_closed_file_untouched(tmp_path: Path) -> None:
    card = tmp_path / "People" / "Judy.md"
    card.parent.mkdir(parents=True)
    original = "---\nphone: 123\nnever closed\n"
    card.write_text(original, encoding="utf-8")
    with pytest.raises(FrontmatterFormatError):
        upsert_person_note(tmp_path, name="Judy", email="j@example.com")
    assert card.read_text(encoding="utf-8") == original


def test_missing_trailing_newline_is_completed_before_link_append(tmp_path: Path) -> None:
    card = tmp_path / "People" / "Ken.md"
    card.parent.mkdir(parents=True)
    card.write_bytes(b"# Ken\nlast user line without newline")
    upsert_person_note(tmp_path, name="Ken", meeting_note_stems=["Sync"])
    text = card.read_text(encoding="utf-8")
    # The user's text was completed, never spliced into.
    assert "last user line without newline\n" in text
    assert "- [[Sync]]" in text


def test_bom_prefixed_card_keeps_its_bom_and_frontmatter_detection(tmp_path: Path) -> None:
    card = tmp_path / "People" / "Lena.md"
    card.parent.mkdir(parents=True)
    # write_bytes: exact LF bytes (write_text would CRLF-translate on Windows).
    card.write_bytes(b"\xef\xbb\xbf---\nphone: 1\n---\n\n# Lena\n")
    upsert_person_note(tmp_path, name="Lena", company="Acme")
    raw = card.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf---\n")  # BOM preserved byte-for-byte
    text = raw.decode("utf-8")
    assert "company: Acme" in text
    assert text.count("---") == 2  # merged into the existing block, not a new one


def test_person_name_is_sanitized_for_windows(tmp_path: Path) -> None:
    path = upsert_person_note(tmp_path, name='Dr. "Q": <Lead/Arch>')
    assert path.name == "Dr. Q Lead Arch.md"
    assert path.exists()
