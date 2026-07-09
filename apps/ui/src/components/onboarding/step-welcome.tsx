import { motion } from "framer-motion";
import { OmniButton } from "../button";
import { OmniMark } from "../omni-mark";

const PRIVACY_TRUTHS: readonly string[] = [
  "No bot joins your calls.",
  "Audio is captured on this machine only.",
  "Recordings stay on this device as MP3.",
];

export function StepWelcome({ onBegin }: { readonly onBegin: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center text-center">
      <span className="omni-aperture" aria-hidden="true" style={{ width: 80, height: 80, display: "inline-flex", alignItems: "center", justifyContent: "center" }}>
        <OmniMark size={80} />
      </span>
      <h1
        className="mt-[var(--space-6)] mb-0 font-[family-name:var(--font-display)] font-semibold text-[var(--ink)]"
        style={{
          fontSize: "var(--text-title-size)",
          lineHeight: "var(--text-title-lh)",
          letterSpacing: "var(--text-title-ls)",
        }}
      >
        Welcome to Omni Steroid
      </h1>
      <p
        className="mt-[var(--space-3)] mb-0 text-[var(--grey-600)]"
        style={{ fontSize: "var(--text-body-size)", maxWidth: 380 }}
      >
        Meeting intelligence that runs entirely on your device.
      </p>

      {/* Privacy truths block, left-aligned, centered container */}
      <div className="mt-[var(--space-6)] mb-0 flex justify-center w-full">
        <motion.ul
          className="flex list-none flex-col gap-[var(--space-2)] p-0 m-0 text-left"
          variants={{
            visible: { transition: { staggerChildren: 0.08 } }
          }}
          initial="hidden"
          animate="visible"
        >
          {PRIVACY_TRUTHS.map((truth) => (
            <motion.li
              key={truth}
              variants={{
                hidden: { opacity: 0, y: 4 },
                visible: { opacity: 1, y: 0 }
              }}
              transition={{ duration: 0.2, ease: [0, 0, 0.2, 1] }} // --dur-panel is 200ms
              className="flex items-center gap-[var(--space-2)] text-[var(--ink-secondary)]"
              style={{ fontSize: "var(--text-body-size)" }}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
                style={{ color: "var(--success)" }}
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
              <span>{truth}</span>
            </motion.li>
          ))}
        </motion.ul>
      </div>

      <OmniButton
        variant="primary"
        onClick={onBegin}
        className="mt-[var(--space-8)]"
        style={{ fontSize: 14 }}
      >
        Get started
      </OmniButton>
    </div>
  );
}
