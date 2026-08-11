import { useEffect, useRef, useState } from "react";
import { getDemoId, uploadJob } from "../api.js";
import styles from "./UploadForm.module.css";

const LANGUAGES = [
  { value: "mr", label: "Marathi (default)" },
  { value: "hi", label: "Hindi" },
  { value: "en", label: "English" },
  { value: "auto", label: "Auto detect" },
];

const MODEL_SIZES = [
  { value: "groq", label: "Fast cloud, Groq (needs API key, fastest)" },
  // { value: "medium", label: "medium local (best accuracy, slowest)" },
  // { value: "small", label: "small local" },
  // { value: "base", label: "base local" },
  // { value: "tiny", label: "tiny local (fast, rough)" },
];

export default function UploadForm({ onCreated }) {
  const [audio, setAudio] = useState(null);
  const [sidecar, setSidecar] = useState(null);
  const [photo, setPhoto] = useState(null);
  const [language, setLanguage] = useState("mr");
  const [modelSize, setModelSize] = useState("groq");
  const [studentCount, setStudentCount] = useState("");
  const [dragOver, setDragOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [demoId, setDemoId] = useState(null);
  const audioInput = useRef(null);

  useEffect(() => {
    getDemoId()
      .then((r) => setDemoId(r.job_id))
      .catch(() => {});
  }, []);

  function acceptFiles(fileList) {
    for (const file of fileList) {
      const name = file.name.toLowerCase();
      if (name.endsWith(".json")) setSidecar(file);
      else if (/\.(jpe?g|png)$/.test(name)) setPhoto(file);
      else setAudio(file);
    }
  }

  function onDrop(event) {
    event.preventDefault();
    setDragOver(false);
    acceptFiles(event.dataTransfer.files);
  }

  async function submit(event) {
    event.preventDefault();
    if (!audio) {
      setError("Choose an audio file first.");
      return;
    }
    setBusy(true);
    setError(null);
    const form = new FormData();
    form.append("audio", audio);
    if (sidecar) form.append("sidecar", sidecar);
    if (photo) form.append("photo", photo);
    form.append("language", language);
    form.append("model_size", modelSize);
    if (studentCount !== "") form.append("student_count", studentCount);
    try {
      const result = await uploadJob(form);
      onCreated(result.job_id);
    } catch (err) {
      setError(err.message);
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={submit}>
      <div
        className={dragOver ? styles.dropzoneActive : styles.dropzone}
        onDragOver={(e) => {
          e.preventDefault();
          setDragOver(true);
        }}
        onDragLeave={() => setDragOver(false)}
        onDrop={onDrop}
        onClick={() => audioInput.current.click()}
      >
        <p className={styles.dropTitle}>
          Drop the classroom recording here, or click to browse
        </p>
        <p className={styles.dropHint}>
          Optional: drop the sidecar JSON and classroom photo alongside it.
          Up to 500 MB.
        </p>
        <input
          ref={audioInput}
          type="file"
          hidden
          multiple
          onChange={(e) => acceptFiles(e.target.files)}
        />
        <ul className={styles.fileList}>
          <li>Audio: {audio ? audio.name : "none"}</li>
          <li>Metadata JSON: {sidecar ? sidecar.name : "none"}</li>
          <li>Photo: {photo ? photo.name : "none"}</li>
        </ul>
      </div>

      <div className={styles.fields}>
        <label className={styles.field}>
          Language
          <select value={language} onChange={(e) => setLanguage(e.target.value)}>
            {LANGUAGES.map((l) => (
              <option key={l.value} value={l.value}>
                {l.label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          Model size
          <select value={modelSize} onChange={(e) => setModelSize(e.target.value)}>
            {MODEL_SIZES.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.field}>
          Student count (pre-filled from JSON when present)
          <input
            type="number"
            min="1"
            value={studentCount}
            onChange={(e) => setStudentCount(e.target.value)}
            placeholder="e.g. 22"
          />
        </label>
      </div>

      <p className={styles.warning}>
        A one hour recording takes several minutes to process on this
        hardware. The page shows real progress and the transcript streams in
        as it is produced.
      </p>

      {error && <p className={styles.error}>{error}</p>}

      <div className={styles.actions}>
        <button className={styles.submit} type="submit" disabled={busy}>
          {busy ? "Uploading" : "Upload and analyze"}
        </button>
        {demoId && (
          <a className={styles.demoLink} href={`#job=${demoId}`}>
            View a pre-computed sample result
          </a>
        )}
      </div>
    </form>
  );
}
