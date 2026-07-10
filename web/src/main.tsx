import React from "react";
import ReactDOM from "react-dom/client";
import "./styles.css";

function App() {
  return (
    <main>
      <h1>AgentHub</h1>
      <p>The local control plane is ready. Goal execution UI arrives in Milestone 6.</p>
    </main>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
