import { useCallback, useEffect, useState } from "react";
import UploadForm from "./components/UploadForm.jsx";
import Processing from "./components/Processing.jsx";
import Results from "./components/Results.jsx";
import styles from "./App.module.css";

// Views: upload -> processing -> results. A #job=<id> hash deep-links
// straight into an existing job, which is how the demo result is opened.
export default function App() {
  const [jobId, setJobId] = useState(() => {
    const match = window.location.hash.match(/#job=([a-f0-9]+)/);
    return match ? match[1] : null;
  });
  const [finished, setFinished] = useState(false);

  const openJob = useCallback((id) => {
    window.location.hash = `job=${id}`;
    setFinished(false);
    setJobId(id);
  }, []);

  const reset = useCallback(() => {
    window.location.hash = "";
    setJobId(null);
    setFinished(false);
  }, []);

  useEffect(() => {
    const onHashChange = () => {
      const match = window.location.hash.match(/#job=([a-f0-9]+)/);
      setJobId(match ? match[1] : null);
      if (!match) setFinished(false);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <h1 className={styles.title} onClick={reset}>
          Classroom Voice Analytics
        </h1>
        <p className={styles.subtitle}>
          Teacher and student talk analysis for recorded lessons. Speaker
          labels are heuristic, not diarization.
        </p>
      </header>
      {jobId === null && <UploadForm onCreated={openJob} />}
      {jobId !== null && !finished && (
        <Processing jobId={jobId} onDone={() => setFinished(true)} onReset={reset} />
      )}
      {jobId !== null && finished && <Results jobId={jobId} onReset={reset} />}
    </div>
  );
}
