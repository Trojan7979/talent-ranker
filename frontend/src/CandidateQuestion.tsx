import type { Answers } from "./screeningApi";
import { StartDateField } from "./StartDateField";

export type Prompt = { kind: "qualification"; id: string; text: string } | {
  kind: "interest" | "availability" | "notice_period" | "salary";
};

type AnswerStatus = "answered" | "unsure" | "prefer_not_to_answer";

function qualificationQuestion(text: string): string {
  const subject = text.trim().replace(/[.!?]+$/, "");
  const experience = subject.match(/^Experience\s+(.+)$/i);
  if (experience) return `Have you had experience ${experience[1]}?`;
  const understanding = subject.match(/^Strong understanding of\s+(.+)$/i);
  if (understanding) return `Would you say you have a strong understanding of ${understanding[1]}?`;
  return `Have you used ${subject} in a role or project?`;
}

export function CandidateQuestion({ prompt, answers, onChange }: {
  prompt: Prompt; answers: Answers; onChange: (answers: Answers) => void;
}) {
  if (prompt.kind === "qualification") {
    const current = answers.qualifications.find((item) => item.requirement_id === prompt.id);
    return <label>{qualificationQuestion(prompt.text)}
      <select value={current?.confirmation ?? ""} onChange={(event) => {
        const remaining = answers.qualifications.filter((item) => item.requirement_id !== prompt.id);
        const confirmation = event.target.value as "yes" | "no" | "unsure" | "";
        onChange({ ...answers, qualifications: confirmation
          ? [...remaining, { requirement_id: prompt.id, confirmation }] : remaining });
      }}>
        <option value="">Skip for now</option><option value="yes">Yes, I have</option>
        <option value="no">Not yet</option><option value="unsure">I'm not sure</option>
      </select>
    </label>;
  }
  if (prompt.kind === "interest") {
    return <label>Would you like to continue with this role?
      <select value={answers.interest ?? ""} onChange={(event) => onChange({ ...answers,
        interest: event.target.value as Answers["interest"] || undefined })}>
        <option value="">Skip for now</option><option value="interested">Yes, I'd like to continue</option>
        <option value="not_interested">No, thank you</option>
        <option value="needs_details">I'd like more details first</option>
        <option value="unsure">I'm not sure yet</option>
      </select>
    </label>;
  }
  if (prompt.kind === "availability") {
    const current = answers.availability;
    return <div className="question-fields">
      <label>If this role is a fit, when could you start?
        <select value={current?.status ?? ""} onChange={(event) => {
          const status = event.target.value as AnswerStatus | "";
          onChange({ ...answers, availability: status ? { status } : undefined });
        }}>
          <option value="">Skip for now</option><option value="answered">I can give a date</option>
          <option value="unsure">I'm not sure yet</option>
          <option value="prefer_not_to_answer">I'd rather discuss this</option>
        </select>
      </label>
      {current?.status === "answered" && <StartDateField value={current.earliest_start_date}
        onChange={(date) => onChange({ ...answers, availability: {
          status: "answered", earliest_start_date: date,
        } })} />}
    </div>;
  }
  if (prompt.kind === "notice_period") {
    const current = answers.notice_period;
    return <div className="question-fields">
      <label>How much notice would you need before starting?
        <select value={current?.status ?? ""} onChange={(event) => {
          const status = event.target.value as AnswerStatus | "";
          onChange({ ...answers, notice_period: status ? { status } : undefined });
        }}>
          <option value="">Skip for now</option><option value="answered">I can give the number of days</option>
          <option value="unsure">I'm not sure yet</option>
          <option value="prefer_not_to_answer">I'd rather discuss this</option>
        </select>
      </label>
      {current?.status === "answered" && <label>Days of notice (enter 0 if you can start now)
        <input type="number" min="0" max="365" value={current.days ?? ""} onChange={(event) =>
          onChange({ ...answers, notice_period: { status: "answered",
            days: event.target.value === "" ? undefined : Number(event.target.value) } })} />
      </label>}
    </div>;
  }
  const current = answers.salary;
  const salary = current?.status === "answered" ? current : { status: "answered" as const };
  return <div className="question-fields">
    <label>What compensation range would you expect for this role?
      <select value={current?.status ?? ""} onChange={(event) => {
        const status = event.target.value as AnswerStatus | "";
        onChange({ ...answers, salary: status ? { status } : undefined });
      }}>
        <option value="">Skip for now</option><option value="answered">I can share a range</option>
        <option value="unsure">I'm not sure yet</option>
        <option value="prefer_not_to_answer">I'd rather discuss this</option>
      </select>
    </label>
    {current?.status === "answered" && <>
      <div className="field-row">
        <label>Minimum amount<input type="number" min="0" value={current.minimum ?? ""}
          onChange={(event) => onChange({ ...answers, salary: { ...salary,
            minimum: event.target.value === "" ? undefined : Number(event.target.value) } })} /></label>
        <label>Maximum amount<input type="number" min="0" value={current.maximum ?? ""}
          onChange={(event) => onChange({ ...answers, salary: { ...salary,
            maximum: event.target.value === "" ? undefined : Number(event.target.value) } })} /></label>
      </div>
      <div className="field-row">
        <label>Currency (3-letter code)<input maxLength={3} placeholder="INR" value={current.currency ?? ""}
          onChange={(event) => onChange({ ...answers, salary: { ...salary,
            currency: event.target.value.toUpperCase() } })} /></label>
        <label>Pay period<select value={current.period ?? ""} onChange={(event) =>
          onChange({ ...answers, salary: { ...salary,
            period: event.target.value as "hour" | "month" | "year" } })}>
          <option value="">Choose</option><option value="hour">Hour</option>
          <option value="month">Month</option><option value="year">Year</option>
        </select></label>
      </div>
      <label className="inline-check"><input type="checkbox" checked={current.negotiable ?? false}
        onChange={(event) => onChange({ ...answers, salary: { ...salary, negotiable: event.target.checked } })} />Negotiable</label>
    </>}
  </div>;
}
