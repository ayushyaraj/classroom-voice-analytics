import { useEffect, useRef, useState } from "react";
import { getNewSegments, getProgress } from "../api.js";
import styles from "./Processing.module.css";

const STAGE_LABELS = {
  queued: "Waiting in queue",
  preprocessing: "Converting and cleaning audio",
  transcribing: "Transcribing",
  analyzing: "Attributing speakers and computing metrics",
  done: "Done",
  failed: "Failed",
};

function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m} min ${s} s` : `${s} s`;
}

// Polls progress every 2 s and streams in newly transcribed segments so a
// long job is never a blank spinner.
export default function Processing({ jobId, onDone, onReset }) {
  const [progress, setProgress] = useState(null);
  const [segments, setSegments] = useState([]);
  const [error, setError] = useState(null);
  const lastId = useRef(0);
  const tailRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const p = await getProgress(jobId);
        if (cancelled) return;
        setProgress(p);
        if (p.segment_count > lastId.current) {
          const fresh = await getNewSegments(jobId, lastId.current);
          if (cancelled || fresh.segments.length === 0) return;
          lastId.current = fresh.segments[fresh.segments.length - 1].id;
          setSegments((prev) => [...prev, ...fresh.segments].slice(-200));
        }
        if (p.status === "done") {
          clearInterval(timer);
          onDone();
        }
        if (p.status === "failed") clearInterval(timer);
      } catch (err) {
        if (!cancelled) setError(err.message);
        clearInterval(timer);
      }
    }, 2000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [jobId, onDone]);

  useEffect(() => {
    tailRef.current?.scrollIntoView({ block: "end" });
  }, [segments]);

  if (error) {
    return (
      <div className={styles.panel}>
        <p className={styles.error}>{error}</p>
        <button className={styles.back} onClick={onReset}>
          Back to upload
        </button>
      </div>
    );
  }
  if (!progress) return <p>Loading job.</p>;

  const failed = progress.status === "failed";
  const percent = Math.round((progress.progress || 0) * 100);

  return (
    <div className={styles.panel}>
      <div className={styles.statusRow}>
        <strong>{STAGE_LABELS[progress.status] || progress.status}</strong>
        <span className={styles.elapsed}>
          elapsed {formatElapsed(progress.elapsed_seconds)}
        </span>
      </div>

      {!failed && (
        <>
          <div className={styles.barTrack}>
            <div className={styles.barFill} style={{ width: `${percent}%` }} />
          </div>
          <p className={styles.percent}>
            {progress.status === "transcribing"
              ? `${percent}% of audio transcribed, ${progress.segment_count} segments so far`
              : "Progress applies to the transcription stage."}
          </p>
        </>
      )}

      {progress.language_notice && (
        <p className={styles.notice}>{progress.language_notice}</p>
      )}

      {failed && (
        <>
          <p className={styles.error}>
            {progress.error} (stage: {progress.error_stage})
          </p>
          <button className={styles.back} onClick={onReset}>
            Back to upload
          </button>
        </>
      )}

      {segments.length > 0 && !failed && (
        <div className={styles.partial}>
          <h3 className={styles.partialTitle}>Partial transcript</h3>
          <div className={styles.partialScroll}>
            {segments.map((s) => (
              <p key={s.id} className={styles.partialLine}>
                <span className={styles.time}>
                  {new Date(s.start * 1000).toISOString().substring(11, 19)}
                </span>
                {s.text}
              </p>
            ))}
            <div ref={tailRef} />
          </div>
        </div>
      )}
    </div>
  );
}
