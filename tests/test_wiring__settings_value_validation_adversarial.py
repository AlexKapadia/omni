"""Adversarial unit tests for per-key settings validation + normalisation.

Every branch of ``validate_settings_values`` and its private helpers is
exercised with boundary-exact inputs (on / just-over / just-under each
threshold) and the EXACT refusal is asserted: the ``SettingsValueError``
type, its ``.key``, and a substring of its plain-voice ``.reason``. Accept
paths assert the normalised output map, so a wrong normalisation fails the
test. All filesystem probes use ``tmp_path`` (synthetic only).
"""

from pathlib import Path

import pytest

from engine.storage.app_settings_repository import (
    SETTING_ACTIVE_TEMPLATE,
    SETTING_CUSTOM_TEMPLATES,
    SETTING_DISCLOSURE_REMINDER,
    SETTING_INSTANT_EXECUTE_WHITELIST,
    SETTING_KEEP_AUDIO,
    SETTING_KILL_SWITCH,
    SETTING_ONBOARDING_COMPLETE,
    SETTING_PUSH_TO_TALK_HOTKEY,
    SETTING_VAULT_DIR,
)
from engine.wiring.settings_value_validation import (
    CREATE_VAULT_DIR_FLAG,
    SettingsValueError,
    validate_settings_values,
)


def _refused(values: dict[str, object]) -> SettingsValueError:
    """Assert the batch is refused; return the raised error for inspection."""
    with pytest.raises(SettingsValueError) as excinfo:
        validate_settings_values(values)
    return excinfo.value


# ----------------------------------------------------------------- booleans
def test_bool_setting_rejects_int_one_with_exact_reason() -> None:
    err = _refused({SETTING_KEEP_AUDIO: 1})  # truthy but NOT a JSON bool
    assert err.key == SETTING_KEEP_AUDIO
    assert err.reason == "value must be true or false"


def test_bool_setting_rejects_string_true() -> None:
    assert _refused({SETTING_DISCLOSURE_REMINDER: "true"}).key == SETTING_DISCLOSURE_REMINDER


def test_bool_setting_rejects_int_zero() -> None:
    assert _refused({SETTING_KILL_SWITCH: 0}).reason == "value must be true or false"


def test_bool_settings_accept_real_booleans_and_normalise_unchanged() -> None:
    out = validate_settings_values(
        {
            SETTING_KEEP_AUDIO: True,
            SETTING_DISCLOSURE_REMINDER: False,
            SETTING_KILL_SWITCH: True,
            SETTING_ONBOARDING_COMPLETE: False,
        }
    )
    assert out == {
        SETTING_KEEP_AUDIO: True,
        SETTING_DISCLOSURE_REMINDER: False,
        SETTING_KILL_SWITCH: True,
        SETTING_ONBOARDING_COMPLETE: False,
    }


# ---------------------------------------------------------------- vault_dir
def test_vault_dir_rejects_non_string() -> None:
    err = _refused({SETTING_VAULT_DIR: 123})
    assert err.key == SETTING_VAULT_DIR
    assert err.reason == "value must be a folder path"


def test_vault_dir_rejects_blank_string() -> None:
    assert _refused({SETTING_VAULT_DIR: "   "}).reason == "value must be a folder path"


def test_vault_dir_rejects_path_over_500_chars() -> None:
    # Length is checked before absoluteness — 501 chars trips it regardless.
    err = _refused({SETTING_VAULT_DIR: "a" * 501})
    assert err.reason == "path is too long"


def test_vault_dir_rejects_relative_path() -> None:
    err = _refused({SETTING_VAULT_DIR: "relative/notes"})
    assert err.reason == "path must be absolute"


def test_vault_dir_missing_without_create_flag_is_refused(tmp_path: Path) -> None:
    missing = tmp_path / "no-such-vault"
    err = _refused({SETTING_VAULT_DIR: str(missing)})
    assert err.reason == "folder does not exist"


def test_vault_dir_existing_writable_returns_normalised_path(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    out = validate_settings_values({SETTING_VAULT_DIR: str(vault)})
    assert out[SETTING_VAULT_DIR] == str(vault)


def test_vault_dir_create_flag_makes_the_folder_and_returns_it(tmp_path: Path) -> None:
    fresh = tmp_path / "fresh-vault"
    out = validate_settings_values(
        {SETTING_VAULT_DIR: str(fresh), CREATE_VAULT_DIR_FLAG: True}
    )
    assert out[SETTING_VAULT_DIR] == str(fresh)
    assert fresh.is_dir()  # the companion flag actually created it
    assert CREATE_VAULT_DIR_FLAG not in out  # companion flag never persisted


def test_vault_dir_create_flag_mkdir_failure_is_refused(tmp_path: Path) -> None:
    # Parent is a FILE, so mkdir(parents=True) cannot create the child dir.
    blocker = tmp_path / "blocker"
    blocker.write_text("i am a file", encoding="utf-8")
    target = blocker / "child-vault"
    err = _refused({SETTING_VAULT_DIR: str(target), CREATE_VAULT_DIR_FLAG: True})
    assert err.key == SETTING_VAULT_DIR
    assert err.reason.startswith("could not create the folder")


def test_vault_dir_non_writable_is_refused(tmp_path: Path) -> None:
    # The write probe collides with an EXISTING directory of the same name,
    # so writing the probe file raises OSError -> fail closed.
    vault = tmp_path / "readonly-vault"
    vault.mkdir()
    (vault / ".omni-write-probe").mkdir()
    err = _refused({SETTING_VAULT_DIR: str(vault)})
    assert err.key == SETTING_VAULT_DIR
    assert err.reason.startswith("folder is not writable")


# ------------------------------------------------------------------- hotkey
def test_hotkey_rejects_non_string() -> None:
    err = _refused({SETTING_PUSH_TO_TALK_HOTKEY: 5})
    assert err.key == SETTING_PUSH_TO_TALK_HOTKEY
    assert err.reason == "value must be a key combination string"


def test_hotkey_rejects_empty_after_trim() -> None:
    assert _refused({SETTING_PUSH_TO_TALK_HOTKEY: "   "}).reason == "value must be 1-64 characters"


def test_hotkey_accepts_single_char_boundary() -> None:
    out = validate_settings_values({SETTING_PUSH_TO_TALK_HOTKEY: "a"})
    assert out[SETTING_PUSH_TO_TALK_HOTKEY] == "a"


def test_hotkey_accepts_64_char_boundary() -> None:
    out = validate_settings_values({SETTING_PUSH_TO_TALK_HOTKEY: "a" * 64})
    assert out[SETTING_PUSH_TO_TALK_HOTKEY] == "a" * 64


def test_hotkey_rejects_65_char_boundary() -> None:
    err = _refused({SETTING_PUSH_TO_TALK_HOTKEY: "a" * 65})
    assert err.reason == "value must be 1-64 characters"


def test_hotkey_rejects_control_character() -> None:
    err = _refused({SETTING_PUSH_TO_TALK_HOTKEY: "a\x01"})
    assert err.reason == "control characters are not allowed"


# ---------------------------------------------------------------- whitelist
def test_whitelist_rejects_non_list() -> None:
    err = _refused({SETTING_INSTANT_EXECUTE_WHITELIST: "create_event"})
    assert err.key == SETTING_INSTANT_EXECUTE_WHITELIST
    assert err.reason == "value must be a list of intent types"


def test_whitelist_rejects_unknown_intent_with_repr_in_reason() -> None:
    err = _refused({SETTING_INSTANT_EXECUTE_WHITELIST: ["create_event", "launch_missiles"]})
    assert err.reason == "unknown intent type: 'launch_missiles'"


def test_whitelist_rejects_non_string_item() -> None:
    assert (
        _refused({SETTING_INSTANT_EXECUTE_WHITELIST: ["create_event", 5]}).reason
        == "unknown intent type: 5"
    )


def test_whitelist_dedupes_and_sorts() -> None:
    out = validate_settings_values(
        {
            SETTING_INSTANT_EXECUTE_WHITELIST: [
                "upsert_contact",
                "create_event",
                "create_event",
                "draft_email",
            ]
        }
    )
    assert out[SETTING_INSTANT_EXECUTE_WHITELIST] == [
        "create_event",
        "draft_email",
        "upsert_contact",
    ]


# ----------------------------------------------------------- active_template
def test_active_template_rejects_non_string() -> None:
    err = _refused({SETTING_ACTIVE_TEMPLATE: 7})
    assert err.key == SETTING_ACTIVE_TEMPLATE
    assert err.reason == "value must be a template id"


def test_active_template_rejects_empty() -> None:
    assert _refused({SETTING_ACTIVE_TEMPLATE: ""}).reason == "value must be a template id"


def test_active_template_rejects_uppercase() -> None:
    assert (
        _refused({SETTING_ACTIVE_TEMPLATE: "General"}).reason
        == "template ids are lowercase snake_case"
    )


def test_active_template_rejects_non_snake_with_space() -> None:
    assert (
        _refused({SETTING_ACTIVE_TEMPLATE: "a b"}).reason
        == "template ids are lowercase snake_case"
    )


def test_active_template_accepts_64_char_boundary() -> None:
    out = validate_settings_values({SETTING_ACTIVE_TEMPLATE: "a" * 64})
    assert out[SETTING_ACTIVE_TEMPLATE] == "a" * 64


def test_active_template_rejects_65_char_boundary() -> None:
    assert (
        _refused({SETTING_ACTIVE_TEMPLATE: "a" * 65}).reason
        == "template ids are lowercase snake_case"
    )


def test_active_template_accepts_valid_snake_case() -> None:
    out = validate_settings_values({SETTING_ACTIVE_TEMPLATE: "one_on_one"})
    assert out[SETTING_ACTIVE_TEMPLATE] == "one_on_one"


# --------------------------------------------------------- custom_templates
def _one_valid_template() -> dict[str, object]:
    return {
        "template_id": "my_notes",
        "display_name": "My Notes",
        "sections": [{"title": "Recap", "guidance": "Summarize the meeting."}],
        "tone_rules": "Be terse.",
    }


def test_custom_templates_rejects_non_list() -> None:
    err = _refused({SETTING_CUSTOM_TEMPLATES: {"template_id": "x"}})
    assert err.key == SETTING_CUSTOM_TEMPLATES
    assert err.reason == "value must be a list of templates"


def test_custom_templates_rejects_more_than_20() -> None:
    err = _refused({SETTING_CUSTOM_TEMPLATES: [_one_valid_template()] * 21})
    assert err.reason == "at most 20 custom templates"


def test_custom_templates_rejects_non_dict_entry() -> None:
    assert (
        _refused({SETTING_CUSTOM_TEMPLATES: ["not-a-dict"]}).reason
        == "each template must be an object"
    )


def test_custom_templates_rejects_missing_sections_list() -> None:
    assert (
        _refused({SETTING_CUSTOM_TEMPLATES: [{"template_id": "x"}]}).reason
        == "each template needs a sections list"
    )


def test_custom_templates_rejects_non_dict_section() -> None:
    entry: dict[str, object] = {
        "template_id": "my_notes",
        "display_name": "My Notes",
        "sections": ["not-a-section-object"],
        "tone_rules": "",
    }
    assert (
        _refused({SETTING_CUSTOM_TEMPLATES: [entry]}).reason == "every section must be an object"
    )


def test_custom_templates_surfaces_build_validation_error() -> None:
    bad = _one_valid_template()
    bad["template_id"] = "Bad-Id"  # not lowercase snake_case
    err = _refused({SETTING_CUSTOM_TEMPLATES: [bad]})
    assert err.key == SETTING_CUSTOM_TEMPLATES
    assert "lowercase snake_case" in err.reason


def test_custom_templates_rejects_duplicate_ids() -> None:
    err = _refused({SETTING_CUSTOM_TEMPLATES: [_one_valid_template(), _one_valid_template()]})
    assert err.reason == "duplicate template id 'my_notes'"


def test_custom_templates_accepts_and_normalises_stripped_shape() -> None:
    entry: dict[str, object] = {
        "template_id": "my_notes",
        "display_name": "  My Notes  ",
        "sections": [{"title": "  Recap  ", "guidance": "  Summarize.  "}],
        "tone_rules": "  Be terse.  ",
    }
    out = validate_settings_values({SETTING_CUSTOM_TEMPLATES: [entry]})
    assert out[SETTING_CUSTOM_TEMPLATES] == [
        {
            "template_id": "my_notes",
            "display_name": "My Notes",
            "sections": [{"title": "Recap", "guidance": "Summarize."}],
            "tone_rules": "Be terse.",
        }
    ]


# ------------------------------------------------------------ batch-level
def test_create_vault_dir_flag_must_be_bool() -> None:
    err = _refused({CREATE_VAULT_DIR_FLAG: "yes"})
    assert err.key == CREATE_VAULT_DIR_FLAG
    assert err.reason == "value must be true or false"


def test_unknown_settings_key_is_refused() -> None:
    err = _refused({"totally_unknown": 1})
    assert err.key == "totally_unknown"
    assert err.reason == "unknown settings key"


def test_empty_batch_is_refused() -> None:
    err = _refused({})
    assert err.key == "values"
    assert err.reason == "no persistable settings in the update"


def test_only_companion_flag_yields_no_persistable_settings() -> None:
    err = _refused({CREATE_VAULT_DIR_FLAG: True})
    assert err.key == "values"
    assert err.reason == "no persistable settings in the update"
