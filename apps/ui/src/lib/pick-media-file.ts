/**
 * Native file picker for importing audio/video into the Library.
 */
export async function pickMediaFile(): Promise<string | null> {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({
    multiple: false,
    title: "Import audio or video",
    filters: [
      {
        name: "Media",
        extensions: ["mp3", "mp4", "m4a", "wav", "webm", "mkv", "mov", "aac", "flac", "ogg"],
      },
    ],
  });
  if (selected === null) return null;
  return typeof selected === "string" ? selected : null;
}
