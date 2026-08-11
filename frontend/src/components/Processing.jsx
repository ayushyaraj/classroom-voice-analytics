import { useEffect, useRef, useState } from "react";
import { getEvents, getNewSegments, getProgress } from "../api.js";
import styles from "./Processing.module.css";

const STAGE_LABELS = {
  queued: "Waiting in queue",
  preprocessing: "Preparing audio",
  transcribing: "Transcribing",
  analyzing: "Analyzing",
  done: "Done",
  failed: "Failed",
};

function formatElapsed(seconds) {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return m > 0 ? `${m} min ${s} s` : `${s} s`;
}

function clockTime(ts) {
  return new Date(ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

// Polls progress, the activity feed, and newly transcribed segments every
// second, so from upload to finish the user always sees something moving:
// the step-by-step activity log, a real percentage, and the transcript
// streaming in as chunks land.
export default function Processing({ jobId, onDone, onReset }) {
  const [progress, setProgress] = useState(null);
  const [events, setEvents] = useState([]);
  const [segments, setSegments] = useState([]);
  const [error, setError] = useState(null);
  const lastSeg = useRef(0);
  const lastEvent = useRef(0);
  const feedRef = useRef(null);
  const transcriptRef = useRef(null);

  useEffect(() => {
    let cancelled = false;
    const timer = setInterval(async () => {
      try {
        const p = await getProgress(jobId);
        if (cancelled) return;
        setProgress(p);

        const fresh = await getEvents(jobId, lastEvent.current);
        if (!cancelled && fresh.events.length) {
          lastEvent.current = fresh.events[fresh.events.length - 1].id;
          setEvents((prev) => [...prev, ...fresh.events].slice(-100));
        }

        if (p.segment_count > lastSeg.current) {
          const segs = await getNewSegments(jobId, lastSeg.current);
          if (!cancelled && segs.segments.length) {
            lastSeg.current = segs.segments[segs.segments.length - 1].id;
            setSegments((prev) => [...prev, ...segs.segments].slice(-200));
          }
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
    }, 1000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [jobId, onDone]);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight });
  }, [events]);
  useEffect(() => {
    transcriptRef.current?.scrollTo({ top: transcriptRef.current.scrollHeight });
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
  const stageLabel = STAGE_LABELS[progress.status] || progress.status;

  return (
    <div className={styles.panel}>
      <div className={styles.statusRow}>
        <strong>
          {!failed && <span className={styles.spinner} aria-hidden />}
          {stageLabel}
        </strong>
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
            {percent}% of this stage
            {progress.segment_count > 0
              ? `, ${progress.segment_count} lines transcribed`
              : ""}
          </p>
        </>
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

      {!failed && (
        <div className={styles.grid}>
          <div className={styles.column}>
            <h3 className={styles.columnTitle}>Activity</h3>
            <div className={styles.feed} ref={feedRef}>
              {events.length === 0 && (
                <p className={styles.feedEmpty}>Starting up...</p>
              )}
              {events.map((e) => (
                <div key={e.id} className={styles.feedLine}>
                  <span className={styles.feedTime}>{clockTime(e.ts)}</span>
                  <span>{e.message}</span>
                </div>
              ))}
            </div>
          </div>

          <div className={styles.column}>
            <h3 className={styles.columnTitle}>Transcript so far</h3>
            <div className={styles.feed} ref={transcriptRef}>
              {segments.length === 0 && (
                <p className={styles.feedEmpty}>
                  Text appears here as each part is transcribed.
                </p>
              )}
              {segments.map((s) => (
                <p key={s.id} className={styles.partialLine}>
                  <span className={styles.feedTime}>
                    {new Date(s.start * 1000).toISOString().substring(11, 19)}
                  </span>
                  {s.text}
                </p>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
