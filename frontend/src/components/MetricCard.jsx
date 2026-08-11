import { useState } from "react";
import styles from "./MetricCard.module.css";

// One engagement metric, click to expand its formula and interpretation.
export default function MetricCard({ def, value, band }) {
  const [open, setOpen] = useState(false);
  const shown = typeof value === "number" ? value.toFixed(2) : "n/a";
  return (
    <div className={styles.card}>
      <button
        className={styles.head}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className={styles.label}>{def.label}</span>
        <span className={styles.value}>{shown}</span>
      </button>
      <div className={styles.band}>{band}</div>
      {open && (
        <div className={styles.detail}>
          <p>
            <strong>Formula:</strong> {def.formula}
          </p>
          <p>{def.explanation}</p>
          <p className={styles.bands}>
            <strong>Bands:</strong> {def.bands}
          </p>
        </div>
      )}
      <button className={styles.toggle} onClick={() => setOpen((v) => !v)}>
        {open ? "Hide detail" : "Show formula"}
      </button>
    </div>
  );
}
