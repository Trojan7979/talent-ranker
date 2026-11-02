import { useState } from "react";

export type Proposal = {
  object_id: string; file_name: string; name: string | null; email: string | null;
  candidate_id: string | null; suggestion: "existing" | "new" | "review";
  analysis_error: string | null; job_title: string | null; web_url: string;
};

export type Decision = {
  object_id: string; action: "existing" | "new" | "skip";
  candidate_id: string; name: string; email: string; job_title: string;
};

type Props = {
  review: Proposal[];
  decisions: Record<string, Decision>;
  update: (objectId: string, change: Partial<Decision>) => void;
  busy: boolean;
  canApprove: boolean;
  approve: () => void;
  selectFirst: (count: number) => void;
};

export function SourceProposalReview({ review, decisions, update, busy, canApprove, approve, selectFirst }: Props) {
  const [limit, setLimit] = useState(20);
  if (!review.length) return null;
  const selected = review.filter((item) => decisions[item.object_id]
    && decisions[item.object_id].action !== "skip").length;
  return <>
    <p>Confirm each suggestion. Files with unresolved identity or extraction issues are skipped by default.</p>
    <div className="source-bulk-selection">
      <label>Resumes to index
        <input type="number" min={1} max={review.length} value={limit}
          onChange={(event) => setLimit(Number(event.target.value))} disabled={busy} />
      </label>
      <button type="button" disabled={busy || !Number.isInteger(limit) || limit < 1 || limit > review.length}
        onClick={() => selectFirst(limit)}>Select first {limit || "N"}</button>
      <p>{selected} selected of {review.length}. Selection follows the displayed file order. Files needing review stay skipped, so the selected count may be lower than N.</p>
    </div>
    <div className="source-file-list">{review.map((item) => {
      const decision = decisions[item.object_id];
      return <div className="source-file" key={item.object_id}>
        <strong>{item.file_name}</strong>
        {item.web_url && <a href={item.web_url} target="_blank" rel="noopener noreferrer">Open source</a>}
        <span>{item.suggestion === "existing" ? `Existing: ${item.candidate_id}`
          : item.suggestion === "new" ? "New candidate" : "Needs review"}</span>
        {item.analysis_error && <span className="error">{item.analysis_error}</span>}
        {decision && <>
          <select aria-label={`Action for ${item.file_name}`} value={decision.action}
            onChange={(event) => update(item.object_id, { action: event.target.value as Decision["action"] })}>
            <option value="skip">Skip</option>
            <option value="existing">Use existing candidate</option>
            {item.suggestion === "new" && <option value="new">Create new candidate ID</option>}
          </select>
          {decision.action === "existing" && <input aria-label={`Candidate ID for ${item.file_name}`}
            placeholder="CAND_0001" value={decision.candidate_id}
            onChange={(event) => update(item.object_id, { candidate_id: event.target.value })} />}
          {decision.action !== "skip" && <>
            <input aria-label={`Name for ${item.file_name}`} placeholder="Candidate name"
              value={decision.name} onChange={(event) => update(item.object_id, { name: event.target.value })} />
            <input aria-label={`Email for ${item.file_name}`} placeholder="Email (optional)"
              value={decision.email} onChange={(event) => update(item.object_id, { email: event.target.value })} />
            <input aria-label={`Job title for ${item.file_name}`} placeholder="Job title (optional)"
              maxLength={120} value={decision.job_title}
              onChange={(event) => update(item.object_id, { job_title: event.target.value })} />
          </>}
        </>}
      </div>;
    })}</div>
    <button type="button" disabled={busy || !canApprove} onClick={approve}>Confirm and index {selected} resumes</button>
  </>;
}

