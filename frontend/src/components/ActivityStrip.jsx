import styles from "./ActivityStrip.module.css";

// Horizontal strip, one column per minute. Column height is fixed; the fill
// shows the teacher/student split of speech in that minute.
export default function ActivityStrip({ timeline }) {
  if (!timeline.length) return <p className={styles.empty}>No timeline.</p>;
  return (
    <div className={styles.strip}>
      {timeline.map((row) => {
        const total = row.teacher_seconds + row.student_seconds;
        const tPct = total > 0 ? (row.teacher_seconds / total) * 100 : 0;
        const sPct = total > 0 ? (row.student_seconds / total) * 100 : 0;
        // opacity reflects how much speech happened that minute vs a full 60 s
        const activity = Math.min(total / 60, 1);
        return (
          <div
            key={row.minute}
            className={styles.col}
            title={`Minute ${row.minute}: teacher ${row.teacher_seconds}s, student ${row.student_seconds}s`}
          >
            <div className={styles.bar} style={{ opacity: 0.25 + 0.75 * activity }}>
              <div className={styles.teacher} style={{ height: `${tPct}%` }} />
              <div className={styles.student} style={{ height: `${sPct}%` }} />
            </div>
            {row.minute % 5 === 0 && (
              <span className={styles.tick}>{row.minute}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
