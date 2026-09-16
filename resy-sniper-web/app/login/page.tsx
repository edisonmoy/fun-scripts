"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

function LoginForm() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const router = useRouter();
  const searchParams = useSearchParams();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    const res = await fetch("/api/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    setLoading(false);
    if (!res.ok) {
      setError("Wrong password.");
      return;
    }
    router.push(searchParams.get("next") || "/");
    router.refresh();
  }

  return (
    <form className="login-form card" onSubmit={handleSubmit}>
      <h1>Resy sniper</h1>
      <p className="subtitle">Enter the password to manage targets.</p>
      <input
        type="password"
        placeholder="Password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        autoFocus
      />
      {error && <div className="status-message error">{error}</div>}
      <button type="submit" className="primary" disabled={loading || !password}>
        {loading ? "Checking..." : "Enter"}
      </button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main>
      <Suspense fallback={null}>
        <LoginForm />
      </Suspense>
    </main>
  );
}
