import { useState } from "react";
import { Outlet } from "react-router";
import { usePermissions } from "../auth/usePermissions";
import type { ModuleRegistration } from "../modules/registry";
import { visiblePages } from "../modules/registry";
import { ChangePasswordDrawer } from "./ChangePasswordForm";
import { DrawerHostContext } from "./Drawer";
import { Sidebar } from "./Sidebar";
import { ToastProvider } from "./Toast";

export function Shell({ registrations }: { registrations: ModuleRegistration[] }) {
  const { can, isLoading } = usePermissions();
  const [host, setHost] = useState<HTMLDivElement | null>(null);
  const [passwordOpen, setPasswordOpen] = useState(false);
  return (
    <ToastProvider>
      <DrawerHostContext.Provider value={host}>
        <div className="app">
          <Sidebar pages={visiblePages(registrations, can)} onChangePassword={() => setPasswordOpen(true)} />
          <div className="main">
            <div className="body" ref={setHost}>
              <main className="content">{isLoading ? <div className="empty">載入中…</div> : <Outlet />}</main>
            </div>
          </div>
          {/* 右側面板的位置：問答做好之後掛在這裡 */}
          <aside className="sidePanelSlot" />
        </div>
        <ChangePasswordDrawer open={passwordOpen} onClose={() => setPasswordOpen(false)} />
      </DrawerHostContext.Provider>
    </ToastProvider>
  );
}
