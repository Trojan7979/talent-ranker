import { useEffect, useState } from "react";
import { screeningApi } from "./screeningApi";

type Props = { campaignId: string; recruiterToken: string };

export function GmailConnection({ campaignId, recruiterToken }: Props) {
  const [status, setStatus] = useState<{ backend: string; sender_email: string | null; connected: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let active = true;
    screeningApi.gmailStatus(recruiterToken).then((value) => {
      if (active) setStatus(value);
    }).catch((cause: unknown) => {
      if (active) setError(cause instanceof Error ? cause.message : "Could not check sender.");
    });
    return () => { active = false; };
  }, [recruiterToken]);

  async function connect() {
    setBusy(true);
    try {
      const response = await screeningApi.connectGmail(campaignId, recruiterToken);
      window.location.assign(response.authorization_url);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start Gmail connection.");
      setBusy(false);
    }
  }

  return <section className="screening-panel" aria-label="Invitation sender">
    <h2>Invitation sender</h2>
    {error && <p className="error" role="alert">{error}</p>}
    {!status && !error && <p>Checking sender connection…</p>}
    {status?.backend !== "gmail_api" && status &&
      <p>Configured backend: {status.backend}. Gmail connection is available when Gmail API is selected.</p>}
    {status?.backend === "gmail_api" && <>
      <p>Sender: <strong>{status.sender_email ?? "Not configured"}</strong></p>
      <p role="status">{status.connected ? "Gmail authorization is saved." : "Gmail needs a one-time connection before live delivery."}</p>
      {!status.connected && <button type="button" disabled={busy} onClick={connect}>Connect Gmail</button>}
      {status.connected && <button type="button" className="secondary-button" disabled={busy}
        onClick={() => screeningApi.gmailStatus(recruiterToken).then(setStatus).catch((cause: unknown) => setError(String(cause)))}>
        Refresh sender status</button>}
      <p className="hint">Google asks the sender to approve Gmail send access and identity confirmation. You will return here and re-enter recruiter access.</p>
    </>}
  </section>;
}
