import { useState } from "react";
import { Outlet } from "react-router";
import { usePermissions } from "../auth/usePermissions";
import type { ModuleRegistration } from "../modules/registry";
import { navPages } from "../modules/registry";
import { ChangePasswordDrawer } from "./ChangePasswordForm";
import { DrawerHostContext } from "./Drawer";
import { GeoBackground } from "./GeoBackground";
import { PageTitleContext } from "./PageHead";
import { SidePanel } from "./SidePanel";
import { Sidebar } from "./Sidebar";
import { ToastProvider } from "./Toast";

export function Shell({ registrations }: { registrations: ModuleRegistration[] }) {
  const { can, isLoading } = usePermissions();
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  const [pageTitle, setPageTitle] = useState<string | null>(null);
  return (
    <ToastProvider>
      <PageTitleContext.Provider value={setPageTitle}>
        <DrawerHostContext.Provider value={host}>
          <div className="app">
            <Sidebar pages={navPages(registrations, can)} onChangePassword={() => setPasswordOpen(true)} />
            <div className="main">
              <div className="body" ref={setHost}>
                <GeoBackground title={pageTitle} />
                <main className="content">{isLoading ? <div className="empty">載入中…</div> : <Outlet />}</main>
              </div>
            </div>
            {/* 問答面板：外殼先放上，功能之後再接 */}
            <SidePanel />
          </div>
          <ChangePasswordDrawer open={passwordOpen} onClose={() => setPasswordOpen(false)} />
        </DrawerHostContext.Provider>
      </PageTitleContext.Provider>
    </ToastProvider>
  );
}
