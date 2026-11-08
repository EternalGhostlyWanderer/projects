import { Outlet } from "react-router";

import { Header } from "./Header";
import { PageContainer } from "./PageContainer";
import { Sidebar } from "./Sidebar";

export function AppShell() {
  return (
    <div className="min-h-screen bg-[linear-gradient(135deg,#f5f8fb_0%,#eef3f7_100%)] text-[#11151b]">
      <div className="flex min-h-screen">
        <Sidebar />
        <div className="min-w-0 flex-1">
          <Header />
          <main>
            <PageContainer>
              <Outlet />
            </PageContainer>
          </main>
        </div>
      </div>
    </div>
  );
}
