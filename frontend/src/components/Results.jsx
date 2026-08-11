import { useEffect, useState } from "react";
import { downloadUrl, flipLabels, getJob, photoUrl } from "../api.js";
import MetricCard from "./MetricCard.jsx";
import ActivityStrip from "./ActivityStrip.jsx";
import TranscriptList from "./TranscriptList.jsx";
import styles from "./Results.module.css";

function fmtDate(value) {
  if (!value) return null;
  return value;
}

function SessionHeader({ job, metadata, hasPhoto }) {
  const d = metadata?.data || {};
  const place = [d.school_name, d.village, d.district, d.state]
    .filter(Boolean)
    .join(", ");
  const rows = [
    ["Teacher", d.teacher_name],
    ["Class", d.class_or_grade],
    ["Subject or activity", d.subject || d.activity_type],
    ["Recorded", fmtDate(d.recorded_at)],
    ["Location", place || null],
    [
      "GPS",
      d.latitude != null && d.longitude != null
        ? `${d.latitude.toFixed(5)}, ${d.longitude.toFixed(5)}`
        : null,
    ],
    ["Students on record", d.student_count],
  ].filter(([, v]) => v != null && v !== "");

  return (
    <div className={styles.sessionHeader}>
      <div className={styles.sessionFacts}>
        <h2 className={styles.sessionTitle}>Session details</h2>
        <table className={styles.factTable}>
          <tbody>
            {rows.map(([k, v]) => (
              <tr key={k}>
                <th>{k}</th>
                <td>{v}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {metadata?.warnings?.length > 0 && (
          <ul className={styles.metaWarnings}>
            {metadata.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        )}
      </div>
      {hasPhoto && (
        <figure className={styles.photoFigure}>
          <img
            className={styles.photo}
            src={photoUrl(job.id)}
            alt="Classroom photo supplied with the recording"
          />
          <figcaption className={styles.photoCaption}>
            Supplied as context only. No image analysis is run on it.
          </figcaption>
        </figure>
      )}
    </div>
  );
}

const METRIC_DEFS = [
  {
    key: "teacher_dominance_ratio",
    band: "teacher_dominance_band",
    label: "Teacher Dominance Ratio",
    formula: "teacher talk seconds / total speech seconds",
    explanation:
      "Of all the time anyone spoke, how much was the teacher. Silence is ignored, so a quiet written-work class is not misread as teacher dominated.",
    bands: "Above 0.85 lecture heavy, 0.60 to 0.85 balanced, below 0.60 student led.",
  },
  {
    key: "student_participation_indicator",
    band: "student_participation_band",
    label: "Student Participation Indicator",
    formula:
      "(student responses / max(teacher questions, 1)) times (student talk / total speech), clamped 0 to 1",
    explanation:
      "Combines whether questions get answered with how much airtime students actually get, so choral one word replies do not score like students explaining reasoning.",
    bands: "Below 0.20 low, 0.20 to 0.50 moderate, above 0.50 high.",
  },
  {
    key: "interaction_density",
    band: "interaction_density_band",
    label: "Interaction Density",
    formula: "question and response turn pairs / duration in minutes",
    explanation:
      "How often a genuine back and forth happened per minute, so a short and a long recording compare fairly.",
    bands: "Below 1 low dialogue, 1 to 3 active, above 3 highly interactive.",
  },
];

export default function Results({ jobId, onReset }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [segments, setSegments] = useState([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getJob(jobId)
      .then((d) => {
        setData(d);
        setMetrics(d.metrics);
        setSegments(d.segments);
      })
      .catch((e) => setError(e.message));
  }, [jobId]);

  async function onFlip(segmentId, speaker) {
    setSegments((prev) =>
      prev.map((s) =>
        s.id === segmentId
          ? { ...s, speaker, speaker_source: "manual", speaker_confidence: 1 }
          : s
      )
    );
    setSaving(true);
    try {
      const res = await flipLabels(jobId, [{ segment_id: segmentId, speaker }]);
      setMetrics(res.metrics);
    } catch (e) {
      setError(e.message);
    } finally {
      setSaving(false);
    }
  }

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
  if (!data || !metrics) return <p>Loading results.</p>;

  const job = data.job;
  const talkTotal = metrics.total_speech_seconds || 1;
  const teacherPct = metrics.teacher_talk_percent || 0;
  const studentPct = metrics.student_talk_percent || 0;

  return (
    <div className={styles.wrap}>
      <div className={styles.topBar}>
        <button className={styles.back} onClick={onReset}>
          New analysis
        </button>
        <div className={styles.downloads}>
          <a href={downloadUrl(jobId, "transcript.txt")}>Transcript .txt</a>
          <a href={downloadUrl(jobId, "report.csv")}>Report .csv</a>
          <a href={downloadUrl(jobId, "")}>Full JSON</a>
        </div>
      </div>

      <SessionHeader job={job} metadata={data.metadata} hasPhoto={data.has_photo} />

      {job.language_notice && (
        <p className={styles.notice}>{job.language_notice}</p>
      )}
      {job.warnings?.length > 0 && (
        <ul className={styles.jobWarnings}>
          {job.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}

      <section className={styles.section}>
        <h2 className={styles.h2}>Summary</h2>
        <p className={styles.summary}>{metrics.summary}</p>
      </section>

      <section className={styles.section}>
        <h2 className={styles.h2}>Engagement metrics</h2>
        <div className={styles.cards}>
          {METRIC_DEFS.map((def) => (
            <MetricCard
              key={def.key}
              def={def}
              value={metrics[def.key]}
              band={metrics[def.band]}
            />
          ))}
        </div>
      </section>

      <section className={styles.section}>
        <h2 className={styles.h2}>Analysis</h2>
        <div className={styles.talkBar}>
          <div
            className={styles.talkTeacher}
            style={{ width: `${teacherPct}%` }}
            title={`Teacher ${teacherPct}%`}
          >
            {teacherPct >= 8 ? `Teacher ${teacherPct}%` : ""}
          </div>
          <div
            className={styles.talkStudent}
            style={{ width: `${studentPct}%` }}
            title={`Students ${studentPct}%`}
          >
            {studentPct >= 8 ? `Students ${studentPct}%` : ""}
          </div>
        </div>

        <table className={styles.countTable}>
          <tbody>
            <tr>
              <th>Teacher talk</th>
              <td>{metrics.teacher_talk_seconds} s</td>
              <th>Student talk</th>
              <td>{metrics.student_talk_seconds} s</td>
            </tr>
            <tr>
              <th>Teacher questions</th>
              <td>{metrics.teacher_question_count}</td>
              <th>Student responses</th>
              <td>{metrics.student_response_count}</td>
            </tr>
            <tr>
              <th>Question-response pairs</th>
              <td>{metrics.qa_pair_count}</td>
              <th>Per student talk</th>
              <td>
                {metrics.per_student_talk_seconds != null
                  ? `${metrics.per_student_talk_seconds} s`
                  : "n/a"}
              </td>
            </tr>
            <tr>
              <th>Short pauses (1.5 to 5 s)</th>
              <td>{metrics.short_pause_seconds} s</td>
              <th>Long dead air (over 5 s)</th>
              <td>{metrics.long_pause_seconds} s</td>
            </tr>
          </tbody>
        </table>

        <h3 className={styles.h3}>Minute by minute activity</h3>
        <ActivityStrip timeline={metrics.timeline || []} />
        <p className={styles.legend}>
          <span className={styles.swatchTeacher} /> Teacher
          <span className={styles.swatchStudent} /> Student
        </p>
      </section>

      <section className={styles.section}>
        <h2 className={styles.h2}>
          Transcript{" "}
          <span className={styles.saveHint}>
            {saving ? "saving label" : "labels are editable, metrics recompute"}
          </span>
        </h2>
        <TranscriptList segments={segments} onFlip={onFlip} />
      </section>
    </div>
  );
}
