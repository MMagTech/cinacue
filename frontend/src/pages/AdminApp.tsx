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
      <div className="login-wrap">
        <span className="wordmark">CINA<b>CUE</b></span>
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
    <div className="admin">
      <div className="admin-top">
        <span className="wordmark">CINA<b>CUE</b> <span className="sub">· Admin</span></span>
        <nav className="nav">
          {tabs.map(([key, label]) => (
            <button
              key={key}
              className={tab === key ? "on" : ""}
              onClick={() => setTab(key)}
            >
              {label}
            </button>
          ))}
        </nav>
        <span className="spacer" />
        <button className="btn ghost btn-sm" onClick={doLogout}>Log Out</button>
      </div>

      <div className="admin-body">
        {tab === "dashboard" && <DashboardPage />}
        {tab === "schedule" && <SchedulePage />}
        {tab === "encoding" && <EncodingPage />}
      </div>
    </div>
  );
}
