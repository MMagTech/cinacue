import { useEffect, useState } from "react";
import { whoami, logout } from "../api";
import AdminLogin from "./AdminLogin";
import DashboardPage from "./DashboardPage";
import SchedulePage from "./SchedulePage";
import EncodingPage from "./EncodingPage";

type Tab = "dashboard" | "schedule" | "encoding";

export default function AdminApp() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [tab, setTab] = useState<Tab>("dashboard");

  useEffect(() => {
    whoami()
      .then((r) => setAuthed(r.authenticated))
      .catch(() => setAuthed(false));
  }, []);

  if (authed === null) {
    return (
      <div className="container">
        <div className="brand">Movie Channel — Admin</div>
      </div>
    );
  }

  if (!authed) {
    return <AdminLogin onSuccess={() => setAuthed(true)} />;
  }

  const doLogout = async () => {
    try {
      await logout();
    } catch {
      /* ignore */
    }
    setAuthed(false);
  };

  const tabs: [Tab, string][] = [
    ["dashboard", "Dashboard"],
    ["schedule", "Schedule"],
    ["encoding", "Encoding"],
  ];

  return (
    <div className="container">
      <div className="topbar">
        <div className="brand">Movie Channel — Admin</div>
        <button className="btn secondary" onClick={doLogout}>
          Log out
        </button>
      </div>

      <div className="tabs">
        {tabs.map(([key, label]) => (
          <button
            key={key}
            className={`tab ${tab === key ? "active" : ""}`}
            onClick={() => setTab(key)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "dashboard" && <DashboardPage />}
      {tab === "schedule" && <SchedulePage />}
      {tab === "encoding" && <EncodingPage />}
    </div>
  );
}
