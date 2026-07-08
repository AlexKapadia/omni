/** Canonical detection sources (mirrors engine/detect/detection_signal_types.py). */
export const DETECTION_SOURCE_OPTIONS = [
  { id: "zoom", label: "Zoom (desktop)" },
  { id: "teams", label: "Microsoft Teams" },
  { id: "browser_meet", label: "Google Meet (browser)" },
  { id: "browser_zoom", label: "Zoom (browser)" },
  { id: "browser_teams", label: "Teams (browser)" },
  { id: "browser_webex", label: "Webex (browser)" },
  { id: "browser_whereby", label: "Whereby (browser)" },
  { id: "slack", label: "Slack" },
  { id: "discord", label: "Discord" },
  { id: "adhoc_loopback", label: "Any app with sustained audio" },
] as const;

export const AUTOSTOP_SILENCE_OPTIONS = [
  { value: 0, label: "Off" },
  { value: 30, label: "30 seconds" },
  { value: 60, label: "60 seconds" },
  { value: 120, label: "2 minutes" },
] as const;
