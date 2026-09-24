import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { CandidateQuestion } from "./CandidateQuestion";
import type { Prompt } from "./CandidateQuestion";
import { screeningApi } from "./screeningApi";
import type { Answers, Invite } from "./screeningApi";

function promptsFor(invite: Invite): Prompt[] {
  const questions = invite.questions;
  return [
    ...questions.must_haves.map((item) => ({ kind: "qualification" as const, ...item })),
    ...(questions.require_interest ? [{ kind: "interest" as const }] : []),
    ...(questions.require_availability ? [{ kind: "availability" as const }] : []),
    ...(questions.require_notice_period ? [{ kind: "notice_period" as const }] : []),
    ...(questions.require_salary ? [{ kind: "salary" as const }] : []),
  ];
}

function validAnswer(prompt: Prompt, answers: Answers): boolean {
  if (prompt.kind === "availability") {
    return answers.availability?.status !== "answered" || Boolean(answers.availability.earliest_start_date);
  }
  if (prompt.kind === "notice_period") {
    return answers.notice_period?.status !== "answered" || answers.notice_period.days !== undefined;
  }
  if (prompt.kind === "salary" && answers.salary?.status === "answered") {
    const pay = answers.salary;
    return pay.minimum !== undefined && pay.maximum !== undefined && pay.minimum <= pay.maximum
      && /^[A-Z]{3}$/.test(pay.currency ?? "") && Boolean(pay.period);
  }
  return true;
}

export function CandidatePage() {
  const { token } = useParams();
  const [invite, setInvite] = useState<Invite | null>(null);
  const [answers, setAnswers] = useState<Answers>({ qualifications: [] });
  const [step, setStep] = useState(-1);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [finished, setFinished] = useState(false);
  const [declined, setDeclined] = useState(false);

  useEffect(() => {
    if (!token) return;
    let active = true;
    screeningApi.getInvite(token).then(async (loaded) => {
      if (loaded.status === "sent") {
        try { loaded = await screeningApi.event(token, "opened"); } catch { /* Start remains available. */ }
      }
      if (active) {
        setInvite(loaded);
        if (loaded.status === "completed") setFinished(true);
        if (loaded.status === "declined") setDeclined(true);
      }
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Link unavailable.");
    });
    return () => { active = false; };
  }, [token]);

  async function start() {
    if (!token || !invite) return;
    setBusy(true);
    try {
      if (invite.status !== "started") setInvite(await screeningApi.event(token, "started"));
      setStep(0);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start.");
    } finally { setBusy(false); }
  }

  async function decline() {
    if (!token || !window.confirm("Decline this screening invitation?")) return;
    setBusy(true);
    try {
      setInvite(await screeningApi.event(token, "decline"));
      setDeclined(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not decline.");
    } finally { setBusy(false); }
  }

  async function submit() {
    if (!token) return;
    setBusy(true);
    try {
      await screeningApi.complete(token, answers);
      setFinished(true);
      setError(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Submission failed.");
    } finally { setBusy(false); }
  }

  const prompts = invite ? promptsFor(invite) : [];
  const current = prompts[step];
  return (
    <main className="candidate-page">
      <div className="candidate-shell">
        <p className="eyebrow">Candidate screening</p>
        {error && <p className="error" role="alert">{error}</p>}
        {!invite && !error && <p role="status">Loading invitation…</p>}
        {invite && <>
          <h1>{invite.job_id}</h1>
          <p className="hint">Link expires {new Date(invite.expires_at).toLocaleString()}</p>
          {finished ? <section className="screening-panel"><h2>Thank you</h2><p>Your screening responses were submitted.</p></section>
            : declined ? <section className="screening-panel"><h2>Invitation declined</h2><p>Your response was recorded.</p></section>
              : step === -1 ? <section className="screening-panel">
                <h2>Welcome</h2><p>Confirm your qualifications, interest, availability, notice period, and expected compensation. You may leave an answer unresolved.</p>
                <div className="wizard-actions">
                  <button type="button" disabled={busy} onClick={start}>Start screening</button>
                  <button type="button" className="secondary-button" disabled={busy} onClick={decline}>Decline</button>
                </div>
              </section> : <section className="screening-panel">
                {current ? <>
                  <p className="eyebrow">Question {step + 1} of {prompts.length}</p>
                  <CandidateQuestion prompt={current} answers={answers} onChange={setAnswers} />
                  {!validAnswer(current, answers) && <p className="error">Complete the selected answer or choose Unsure.</p>}
                </> : <>
                  <h2>Review and submit</h2>
                  <p>You answered {answers.qualifications.length} of {invite.questions.must_haves.length} qualifications.</p>
                  <ul>
                    <li>Interest: {answers.interest ?? "Not answered"}</li>
                    <li>Availability: {answers.availability?.earliest_start_date ?? answers.availability?.status ?? "Not answered"}</li>
                    <li>Notice: {answers.notice_period?.days !== undefined ? `${answers.notice_period.days} days` : answers.notice_period?.status ?? "Not answered"}</li>
                    <li>Expected pay: {answers.salary?.status === "answered"
                      ? `${answers.salary.minimum}–${answers.salary.maximum} ${answers.salary.currency}/${answers.salary.period}`
                      : answers.salary?.status ?? "Not answered"}</li>
                  </ul>
                </>}
                <div className="wizard-actions">
                  <button type="button" className="secondary-button" disabled={busy} onClick={() => setStep((value) => value - 1)}>Back</button>
                  {current ? <button type="button" disabled={busy || !validAnswer(current, answers)} onClick={() => setStep((value) => value + 1)}>Continue</button>
                    : <button type="button" disabled={busy} onClick={submit}>Submit screening</button>}
                </div>
              </section>}
        </>}
      </div>
    </main>
  );
}
