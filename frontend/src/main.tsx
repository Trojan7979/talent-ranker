import React, { ChangeEvent, FormEvent, useState } from "react";
import { createRoot } from "react-dom/client";
import { CandidateScore, rankCandidates } from "./api";
import "./styles.css";

function App() {
  const [jobId, setJobId] = useState("senior-ai-engineer");
  const [jobDescription, setJobDescription] = useState("");
  const [topK, setTopK] = useState(2);
  const [results, setResults] = useState<CandidateScore[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  async function loadJobDescriptionFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    if (files.length === 0) {
      return;
    }
    setError(null);
    try {
      const parts = await Promise.all(
        files.map(async (file) => {
          const content = (await file.text()).trim();
          return files.length > 1 ? `JD part: ${file.name}\n${content}` : content;
        }),
      );
      setJobDescription(parts.join("\n\n"));
    } catch {
      setError("Could not read the selected JD file.");
    }
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setIsLoading(true);
    setError(null);
    try {
      const response = await rankCandidates(jobId, jobDescription, topK);
      setResults(response.results);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Ranking failed");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="workspace">
      <section className="query-panel">
        <h1>Talent Ranker</h1>
        <form onSubmit={submit}>
          <label>
            Job ID
            <input value={jobId} onChange={(event) => setJobId(event.target.value)} />
          </label>
          <label>
            Number of candidates
            <input
              type="number"
              min={1}
              max={1000}
              value={topK}
              onChange={(event) => setTopK(Number(event.target.value))}
            />
          </label>
          <label>
            Load JD files
            <input
              type="file"
              accept=".txt,.md,text/plain,text/markdown"
              multiple
              onChange={loadJobDescriptionFiles}
            />
            <span className="hint">Select one or more TXT/Markdown parts.</span>
          </label>
          <label>
            Job description preview
            <textarea
              value={jobDescription}
              onChange={(event) => setJobDescription(event.target.value)}
              rows={12}
            />
          </label>
          <button disabled={isLoading || jobDescription.length < 20 || topK < 1 || topK > 1000}>
            {isLoading ? "Ranking..." : "Rank candidates"}
          </button>
        </form>
        {error && <p className="error">{error}</p>}
      </section>
      <section className="results-panel">
        {results.map((candidate) => (
          <article key={candidate.candidate_id} className="result-card">
            <div>
              <span>#{candidate.rank}</span>
              <h2>{candidate.candidate_id}</h2>
            </div>
            <strong>{Math.round(candidate.score * 100)}%</strong>
            <p>{candidate.reasoning}</p>
          </article>
        ))}
      </section>
    </main>
  );
}

createRoot(document.getElementById("root") as HTMLElement).render(<App />);
