import { NavLink } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { roleLabels } from "../auth/roles";
import type { PageRegistration } from "../modules/registry";
import { Icon } from "./icons";

const pad = (value: number) => String(value).padStart(2, "0");
const dayNames = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];

const navClass = ({ isActive }: { isActive: boolean }) => `navItem${isActive ? " active" : ""}`;

export function Sidebar({ pages, onChangePassword }: { pages: PageRegistration[]; onChangePassword(): void }) {
  const { user, logout } = useAuth();
  const now = new Date();
  const stamp = `${now.getFullYear()}.${pad(now.getMonth() + 1)}.${pad(now.getDate())} ${dayNames[now.getDay()]}`;
  return (
    <nav className="sidebar">
      <div className="brand">Shift<br />Pilot</div>
      <div className="brandNote">{stamp}</div>
      <NavLink to="/" end className={navClass}><Icon name="home" size={18} /><span className="navLabel">首頁</span></NavLink>
      {pages.map((page) => (
        <NavLink key={page.key} to={page.path} className={navClass}>
          <Icon name={page.icon} size={18} /><span className="navLabel">{page.name}</span>
        </NavLink>
      ))}
      <div className="sidebarFoot">
        {user && <span>{user.employeeName ?? user.email}・{roleLabels[user.role]}</span>}
        <button className="ghostBtn" type="button" onClick={onChangePassword}>改密碼</button>
        <button className="ghostBtn" type="button" onClick={() => { void logout(); }}>登出</button>
      </div>
    </nav>
  );
}
