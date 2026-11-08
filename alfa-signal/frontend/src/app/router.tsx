import { BrowserRouter, Link, Route, Routes } from "react-router";

import { AppShell } from "@/components/layout/AppShell";
import { DashboardPage } from "@/pages/DashboardPage";
import { InsightDetailsPage } from "@/pages/InsightDetailsPage";
import { InsightsPage } from "@/pages/InsightsPage";

function NotFoundPage() {
  return (
    <section className="grid min-h-[60vh] place-items-center text-center">
      <div>
        <p className="text-sm font-semibold text-[#ef3124]">Ошибка 404</p>
        <h1 className="mt-2 text-3xl font-semibold tracking-tight">Страница не найдена</h1>
        <p className="mt-3 text-muted-foreground">Вернитесь на главную страницу Альфа-Бизнеса.</p>
        <Link
          to="/"
          className="mt-6 inline-flex h-10 items-center rounded-xl bg-[#171719] px-4 text-sm font-medium text-white transition hover:bg-black/80"
        >
          Вернуться на главную
        </Link>
      </div>
    </section>
  );
}

export function AppRouter() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<AppShell />}>
          <Route index element={<DashboardPage />} />
          <Route path="insights" element={<InsightsPage />} />
          <Route path="insights/:insightId" element={<InsightDetailsPage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
