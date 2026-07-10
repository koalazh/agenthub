import React, { FormEvent, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";

const API = "http://127.0.0.1:8787";

type GoalSummary = {
  id: string;
  title: string;
  status: string;
};

type GoalDetail = {
  goal: GoalSummary & { contract: { objective: string; acceptance_criteria: string[] } };
  current_harness_version: { version: number } | null;
  step_executions: Array<{ step_id: string; kind: string; status: string; agent_id: string | null }>;
  artifacts: Array<{ id: string; kind: string; size_bytes: number }>;
  approvals: Array<{ id: string; type: string; status: string }>;
};

function App() {
  const [goals, setGoals] = useState<GoalSummary[]>([]);
  const [selected, setSelected] = useState<GoalDetail | null>(null);
  const [objective, setObjective] = useState("");
  const [projectRoot, setProjectRoot] = useState("");

  async function loadGoals() {
    const response = await fetch(`${API}/api/goals`);
    if (response.ok) setGoals(await response.json());
  }

  async function selectGoal(goalId: string) {
    const response = await fetch(`${API}/api/goals/${goalId}`);
    if (response.ok) setSelected(await response.json());
  }

  useEffect(() => {
    void loadGoals();
  }, []);

  useEffect(() => {
    if (!selected) return;
    const events = new EventSource(`${API}/api/goals/${selected.goal.id}/events`);
    events.onmessage = () => void selectGoal(selected.goal.id);
    const refresh = () => void selectGoal(selected.goal.id);
    events.addEventListener("goal.completed", refresh);
    events.addEventListener("goal.failed", refresh);
    events.addEventListener("artifact.published", refresh);
    events.addEventListener("step.completed", refresh);
    events.addEventListener("gate.completed", refresh);
    events.addEventListener("review.completed", refresh);
    events.addEventListener("approval.requested", refresh);
    return () => events.close();
  }, [selected?.goal.id]);

  async function createGoal(event: FormEvent) {
    event.preventDefault();
    const response = await fetch(`${API}/api/goals`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        objective,
        project_root: projectRoot,
        acceptance_criteria: ["Required checks pass"],
        required_evidence: ["Test output", "Independent review"],
      }),
    });
    if (!response.ok) return;
    const created = await response.json();
    setObjective("");
    await loadGoals();
    await selectGoal(created.goal_id);
  }

  return (
    <div className="shell">
      <aside>
        <h1>AgentHub</h1>
        <form onSubmit={createGoal}>
          <textarea
            aria-label="Goal objective"
            placeholder="Describe a software Goal"
            value={objective}
            onChange={(event) => setObjective(event.target.value)}
            required
          />
          <input
            aria-label="Project root"
            placeholder="/absolute/path/to/repo"
            value={projectRoot}
            onChange={(event) => setProjectRoot(event.target.value)}
            required
          />
          <button type="submit">Create Goal</button>
        </form>
        <nav>
          {goals.map((goal) => (
            <button className="goal" key={goal.id} onClick={() => void selectGoal(goal.id)}>
              <span>{goal.title}</span><small>{goal.status}</small>
            </button>
          ))}
        </nav>
      </aside>
      <main>
        {!selected ? (
          <div className="empty">Select a Goal to inspect its execution.</div>
        ) : (
          <>
            <header>
              <div><p>Goal</p><h2>{selected.goal.title}</h2></div>
              <div className="badges">
                <span>{selected.goal.status}</span>
                <span>Harness v{selected.current_harness_version?.version ?? "—"}</span>
              </div>
            </header>
            <section><h3>Objective</h3><p>{selected.goal.contract.objective}</p></section>
            <section>
              <h3>Task Board</h3>
              <div className="task-grid">
                {selected.step_executions.map((step) => (
                  <article key={step.step_id}>
                    <small>{step.kind}</small><strong>{step.step_id}</strong>
                    <span>{step.status}</span><code>{step.agent_id ?? "unbound"}</code>
                  </article>
                ))}
              </div>
            </section>
            <div className="columns">
              <section><h3>Artifacts</h3>{selected.artifacts.map((item) => <p key={item.id}>{item.kind} · {item.size_bytes} B</p>)}</section>
              <section><h3>Approvals</h3>{selected.approvals.map((item) => <p key={item.id}>{item.type} · {item.status}</p>)}</section>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
