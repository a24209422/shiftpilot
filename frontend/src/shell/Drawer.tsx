import { createContext, useContext, useEffect, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { Icon } from "./icons";

// 詳情面板蓋在主內容上，不隨內容捲動，所以由外殼提供一個固定的掛載位置
export const DrawerHostContext = createContext<HTMLElement | null>(null);

interface DrawerProps {
  open: boolean;
  title: string;
  onClose(): void;
  children: ReactNode;
  footer?: ReactNode;
}

export function Drawer({ open, title, onClose, children, footer }: DrawerProps) {
  const host = useContext(DrawerHostContext);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!host) return null;
  return createPortal(
    <aside className={`drawer${open ? " open" : ""}`} aria-label="詳情" aria-hidden={!open}>
      {open && (
        <>
          <div className="drawerHead">
            <h2>{title}</h2>
            <button className="iconBtn" type="button" onClick={onClose} aria-label="關閉"><Icon name="close" size={16} /></button>
          </div>
          <div className="drawerBody">{children}</div>
          {footer && <div className="drawerFoot">{footer}</div>}
        </>
      )}
    </aside>,
    host,
  );
}
