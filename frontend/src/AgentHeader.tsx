export function AgentHeader() {
  return <header className="agent-header">
    <div className="agent-identity">
      <span className="agent-mark" aria-hidden="true">✦</span>
      <div><h1>Recruitment Agent</h1><p>Dedicated agent workspace</p></div>
    </div>
    <span className="agent-availability"><i />Available</span>
  </header>;
}
