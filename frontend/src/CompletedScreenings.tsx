import type { ReviewPage } from "./screeningApi";
import { summaryText } from "./summaryText";

const outcomes = {
  proceed_to_interview: "Ready for interview",
  needs_recruiter_review: "Needs recruiter review",
  do_not_proceed: "Do not proceed",
};

type Props = {
  results: ReviewPage | null;
  selected: Set<string>;
  busy: boolean;
  lastUpdated: Date | null;
  labels: Record<string, string>;
  onSelectAll: () => void;
  onToggle: (candidateId: string) => void;
  onExport: (candidateIds: string[]) => void;
};

export function CompletedScreenings({ results, selected, busy, lastUpdated, labels,
  onSelectAll, onToggle, onExport }: Props) {
  return <section className="screening-panel">
    <h2>Completed screenings</h2>
    <p className="hint">Refreshes every 10 seconds while this tab is visible. {lastUpdated && `Last checked ${lastUpdated.toLocaleTimeString()}.`}</p>
    {results && <p>{results.counts.needs_recruiter_review} need review · {results.counts.proceed_to_interview} ready for interview · {results.counts.do_not_proceed} do not proceed</p>}
    {results && results.items.length > 0 && <div className="selection-toolbar">
      <button type="button" className="secondary-button" onClick={onSelectAll}>Select loaded results</button>
      <strong>{selected.size} selected</strong>
      <button type="button" disabled={busy || selected.size === 0} onClick={() => onExport([...selected])}>Export selected XLSX</button>
    </div>}
    <div className="shortlist-grid">
      {results?.items.map((item) => <article className="result-card" key={item.id}>
        <label className="candidate-select"><input type="checkbox" checked={selected.has(item.candidate_id)}
          onChange={() => onToggle(item.candidate_id)} />Select {item.candidate_id}</label>
        <div><h3>{item.candidate_id}</h3><strong>{outcomes[item.outcome]}</strong></div>
        <p>Candidate reported: {summaryText(item.confirmed, "reported", labels).join("; ") || "None"}</p>
        <p>No answer: {summaryText(item.missing, "missing", labels).join("; ") || "None"}</p>
        <p>Recruiter follow-up: {summaryText(item.needs_verification, "followUp", labels).join("; ") || "None"}</p>
        <button type="button" className="secondary-button" disabled={busy}
          onClick={() => onExport([item.candidate_id])}>Export this result</button>
      </article>)}
    </div>
    {results?.items.length === 0 && <p>No completed screenings yet.</p>}
    <p className="hint">These answers are self-reported. Profile details without a structured source are blank in the workbook.</p>
  </section>;
}
