import { useRef, useState } from "react";
import styles from "./TranscriptList.module.css";

// Fixed height virtualization. A 67 minute transcript is thousands of rows;
// rendering them all freezes the DOM, so only the visible slice (plus an
// overscan buffer) is mounted, positioned by absolute offset inside a spacer
// sized to the full list. Rows are clamped to ROW_HEIGHT so offsets stay exact.
const ROW_HEIGHT = 68; // px, must match .row height in the CSS
const OVERSCAN = 6; // rows above and below the viewport, hides scroll seams
const VIEWPORT = 520; // px scroll container height

function ts(seconds) {
  const s = Math.floor(seconds);
  return new Date(s * 1000).toISOString().substring(11, 19);
}

export default function TranscriptList({ segments, onFlip }) {
  const [scrollTop, setScrollTop] = useState(0);
  const ref = useRef(null);

  if (!segments.length) {
    return <p className={styles.empty}>No transcript segments.</p>;
  }

  const total = segments.length * ROW_HEIGHT;
  const first = Math.max(0, Math.floor(scrollTop / ROW_HEIGHT) - OVERSCAN);
  const visibleCount = Math.ceil(VIEWPORT / ROW_HEIGHT) + OVERSCAN * 2;
  const last = Math.min(segments.length, first + visibleCount);
  const slice = segments.slice(first, last);

  return (
    <div
      className={styles.viewport}
      style={{ height: VIEWPORT }}
      ref={ref}
      onScroll={(e) => setScrollTop(e.currentTarget.scrollTop)}
    >
      <div style={{ height: total, position: "relative" }}>
        {slice.map((s, i) => {
          const index = first + i;
          const teacher = s.speaker === "TEACHER";
          return (
            <div
              key={s.id}
              className={styles.row}
              style={{
                position: "absolute",
                top: index * ROW_HEIGHT,
                height: ROW_HEIGHT,
              }}
            >
              <div className={styles.meta}>
                <span className={styles.time}>
                  {ts(s.start)}
                </span>
                <select
                  className={teacher ? styles.tagTeacher : styles.tagStudent}
                  value={s.speaker || "TEACHER"}
                  onChange={(e) => onFlip(s.id, e.target.value)}
                >
                  <option value="TEACHER">TEACHER</option>
                  <option value="STUDENT">STUDENT</option>
                </select>
                <span className={styles.conf}>
                  {s.speaker_confidence != null
                    ? `${Math.round(s.speaker_confidence * 100)}%`
                    : ""}
                  {s.speaker_source === "manual" ? " edited" : ""}
                </span>
                {s.is_question ? <span className={styles.q}>Q</span> : null}
              </div>
              <div className={styles.text}>{s.text}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
