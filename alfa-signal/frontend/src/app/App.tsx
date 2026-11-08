import { useState } from "react";

import { DEMO_AUTH, readSession, saveSession, type DemoSession } from "@/features/insights/session";
import { LoginPage } from "@/pages/LoginPage";

import { AppProviders } from "./providers";
import { AppRouter } from "./router";

export default function App() {
  const [session, setSession] = useState<DemoSession | null>(readSession);

  if (DEMO_AUTH && !session) {
    return (
      <LoginPage
        onLogin={(value) => {
          saveSession(value);
          setSession(value);
        }}
      />
    );
  }
  return (
    <AppProviders>
      <AppRouter />
    </AppProviders>
  );
}
