//! Translate the persisted push-to-talk hotkey into a global-shortcut
//! accelerator string.
//!
//! Where it sits in the pipeline: the Settings UI records a real key
//! combination and persists it (engine setting `push_to_talk_hotkey`) as an
//! ordered list of tokens — modifiers first, then the key — e.g. `["F9"]`,
//! `["Ctrl","Shift","K"]`, `["Alt","Space"]`. The shell binds the hold key
//! with `tauri-plugin-global-shortcut`, whose `Shortcut`/`HotKey` parser
//! wants a `+`-joined accelerator of modifier names and W3C `Code` values
//! (`Control+Shift+KeyK`, `F9`, `Alt+Space`). This module is that one, pure
//! translation.
//!
//! Invariant: the function is TOTAL and fail-safe. An empty/blank list — a
//! corrupt or unset setting — falls back to the default hold key, so a bad
//! setting can never leave the accelerator string itself unbindable. (An
//! individually malformed token is passed through and rejected later by the
//! plugin's parser, which the caller handles non-fatally — a hotkey miss
//! must never crash the app.)

/// The default push-to-talk hold key when no valid combination is configured.
/// One well-documented constant — every registration path funnels through it.
pub const DEFAULT_DICTATION_HOLD_KEY: &str = "F9";

/// Map one recorded token to its global-shortcut spelling.
///
/// - Modifier names (case-insensitively) normalise to the canonical form the
///   parser accepts (`Control`/`Shift`/`Alt`/`Super`).
/// - A bare ASCII letter/digit becomes its W3C `Code` (`KeyK`, `Digit1`) —
///   the parser matches on physical code, not on the character.
/// - Anything else (function keys, `Space`, `ArrowUp`, `Enter`, …) is already
///   a valid `Code` name and passes straight through.
fn token_to_accelerator(token: &str) -> String {
    let trimmed = token.trim();
    match trimmed.to_ascii_lowercase().as_str() {
        "ctrl" | "control" => return "Control".to_string(),
        "shift" => return "Shift".to_string(),
        "alt" | "option" => return "Alt".to_string(),
        "meta" | "super" | "cmd" | "command" | "win" => return "Super".to_string(),
        _ => {}
    }
    let mut chars = trimmed.chars();
    if let (Some(only), None) = (chars.next(), chars.clone().next()) {
        // Exactly one character: spell it as a physical Code.
        if only.is_ascii_alphabetic() {
            return format!("Key{}", only.to_ascii_uppercase());
        }
        if only.is_ascii_digit() {
            return format!("Digit{only}");
        }
    }
    trimmed.to_string()
}

/// Build a global-shortcut accelerator from the persisted key list.
///
/// Blank tokens are dropped; an empty result falls back to
/// [`DEFAULT_DICTATION_HOLD_KEY`] so the returned string is always non-empty.
pub fn accelerator_from_keys(keys: &[String]) -> String {
    let parts: Vec<String> = keys
        .iter()
        .filter(|token| !token.trim().is_empty())
        .map(|token| token_to_accelerator(token))
        .collect();
    if parts.is_empty() {
        return DEFAULT_DICTATION_HOLD_KEY.to_string();
    }
    parts.join("+")
}

#[cfg(test)]
mod tests {
    use super::*;

    fn keys(tokens: &[&str]) -> Vec<String> {
        tokens.iter().map(|t| (*t).to_string()).collect()
    }

    #[test]
    fn empty_list_falls_back_to_default_f9() {
        assert_eq!(accelerator_from_keys(&[]), "F9");
        assert_eq!(DEFAULT_DICTATION_HOLD_KEY, "F9");
    }

    #[test]
    fn blank_and_whitespace_only_tokens_fall_back_to_default() {
        // A setting of only blanks is as good as unset — fail safe to default.
        assert_eq!(accelerator_from_keys(&keys(&["", "   ", "\t"])), "F9");
    }

    #[test]
    fn bare_function_key_passes_through_unchanged() {
        assert_eq!(accelerator_from_keys(&keys(&["F9"])), "F9");
        assert_eq!(accelerator_from_keys(&keys(&["F13"])), "F13");
    }

    #[test]
    fn single_letter_becomes_physical_key_code() {
        // The plugin matches physical Code, so "K" must become "KeyK".
        assert_eq!(accelerator_from_keys(&keys(&["k"])), "KeyK");
        assert_eq!(accelerator_from_keys(&keys(&["Z"])), "KeyZ");
    }

    #[test]
    fn single_digit_becomes_digit_code() {
        assert_eq!(accelerator_from_keys(&keys(&["1"])), "Digit1");
    }

    #[test]
    fn modifiers_normalise_and_order_is_preserved() {
        assert_eq!(
            accelerator_from_keys(&keys(&["Ctrl", "Shift", "K"])),
            "Control+Shift+KeyK"
        );
        assert_eq!(accelerator_from_keys(&keys(&["Alt", "Space"])), "Alt+Space");
        // Case-insensitive modifier spelling still normalises.
        assert_eq!(
            accelerator_from_keys(&keys(&["CONTROL", "a"])),
            "Control+KeyA"
        );
    }

    #[test]
    fn meta_family_maps_to_super() {
        for token in ["Meta", "Super", "Cmd", "Command", "Win"] {
            assert_eq!(accelerator_from_keys(&keys(&[token, "K"])), "Super+KeyK");
        }
    }

    #[test]
    fn tokens_are_trimmed_before_use() {
        assert_eq!(
            accelerator_from_keys(&keys(&[" Ctrl ", " k "])),
            "Control+KeyK"
        );
    }

    #[test]
    fn named_keys_pass_through_as_codes() {
        assert_eq!(accelerator_from_keys(&keys(&["ArrowUp"])), "ArrowUp");
        assert_eq!(
            accelerator_from_keys(&keys(&["Ctrl", "Enter"])),
            "Control+Enter"
        );
    }

    #[test]
    fn output_is_always_non_empty() {
        // Property-ish sweep: whatever the input, the result never collapses
        // to an empty accelerator (registration always has a target).
        let samples: &[&[&str]] = &[
            &[],
            &[""],
            &["   "],
            &["F9"],
            &["Ctrl", "Shift", "Alt", "K"],
            &["\t", "F10"],
        ];
        for sample in samples {
            assert!(!accelerator_from_keys(&keys(sample)).is_empty());
        }
    }
}
