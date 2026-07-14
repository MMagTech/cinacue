import { useEffect, useState } from "react";
import PublicPage from "./pages/PublicPage";
import AdminApp from "./pages/AdminApp";

// Minimal path-based routing — no router dependency. Anything under /admin
// renders the admin app; everything else renders the public channel page.
export default function App() {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  if (path.startsWith("/admin")) return <AdminApp />;
  return <PublicPage />;
}
