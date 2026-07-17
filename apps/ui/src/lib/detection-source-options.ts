/** Canonical detection sources (mirrors engine/detect/detection_signal_types.py). */
export const DETECTION_SOURCE_OPTIONS = [
  { id: "zoom", label: "Zoom (desktop)" },
  { id: "teams", label: "Microsoft Teams" },
  { id: "browser_meet", label: "Google Meet (browser)" },
  { id: "browser_zoom", label: "Zoom (browser)" },
  { id: "browser_teams", label: "Teams (browser)" },
  { id: "browser_webex", label: "Webex" },
  { id: "browser_whereby", label: "Whereby (browser)" },
  { id: "slack", label: "Slack" },
  { id: "discord", label: "Discord" },
  { id: "skype", label: "Skype" },
  { id: "adhoc_loopback", label: "Any app with sustained audio" },
] as const;

/** Short human labels for the detection toast headline. */
export const MEETING_SOURCE_TOAST_LABELS: Readonly<Record<string, string>> = {
  zoom: "Zoom",
  teams: "Microsoft Teams",
  browser_meet: "Google Meet",
  browser_zoom: "Zoom",
  browser_teams: "Microsoft Teams",
  browser_webex: "Webex",
  browser_whereby: "Whereby",
  slack: "Slack",
  discord: "Discord",
  skype: "Skype",
  adhoc_loopback: "A call",
};

export function meetingSourceToastLabel(source: string): string {
  return MEETING_SOURCE_TOAST_LABELS[source] ?? "A meeting";
}

export const AUTOSTOP_SILENCE_OPTIONS = [
  { value: 0, label: "Off" },
  { value: 30, label: "30 seconds" },
  { value: 60, label: "60 seconds" },
  { value: 120, label: "2 minutes" },
] as const;
