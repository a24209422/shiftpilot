import { useState } from "react";
import { NavLink } from "react-router";
import { useAuth } from "../auth/AuthProvider";
import { roleLabels } from "../auth/roles";
import type { PageRegistration } from "../modules/registry";
import { Icon } from "./icons";

const pad = (value: number) => String(value).padStart(2, "0");
const dayNames = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"];
const collapsedKey = "shiftpilot.sidebarCollapsed";

const navClass = ({ isActive }: { isActive: boolean }) => `navItem${isActive ? " active" : ""}`;

// 瀏覽器停用網站資料時 localStorage 會丟例外；記不住收合狀態不該讓整個導覽列壞掉
function readCollapsed(): boolean {
  try {
    return localStorage.getItem(collapsedKey) === "1";
  } catch {
    return false;
  }
}

function writeCollapsed(value: boolean) {
  try {
    if (value) localStorage.setItem(collapsedKey, "1");
    else localStorage.removeItem(collapsedKey);
  } catch {
    // 記不住就算了，這次的畫面照樣切換
  }
}

export function Sidebar({ pages, onChangePassword }: { pages: PageRegistration[]; onChangePassword(): void }) {
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const now = new Date();
  const stamp = `${now.getFullYear()}.${pad(now.getMonth() + 1)}.${pad(now.getDate())} ${dayNames[now.getDay()]}`;
  const toggle = () => {
    writeCollapsed(!collapsed);
    setCollapsed(!collapsed);
  };
  // 收起時文字只在視覺上隱藏（螢幕報讀仍讀得到），滑鼠提示靠 title；展開時文字就在畫面上，不另外加
  const named = (name: string) => (collapsed ? { title: name } : {});
  return (
    <nav className={`sidebar${collapsed ? " collapsed" : ""}`}>
      <div className="sidebarHead">
        <div className="brand"><span className="brandFull">Shift<br />Pilot</span><span className="brandShort">SP</span></div>
        <button
          className="sidebarToggle" type="button" onClick={toggle}
          aria-label={collapsed ? "展開導覽列" : "收合導覽列"} title={collapsed ? "展開導覽列" : "收合導覽列"} aria-expanded={!collapsed}
        >
          <Icon name="panelLeft" size={18} />
        </button>
        <div className="brandNote">{stamp}</div>
      </div>
      {/* 只有這段會捲動：頁面一多，標題與登出仍固定在上下 */}
      <div className="sidebarNav">
        <NavLink to="/" end className={navClass} {...named("首頁")}><Icon name="home" size={18} /><span className="navLabel">首頁</span></NavLink>
        {/* end：/leave/admin 這類子頁面的開頭跟母頁面一樣，不加的話兩個會同時亮 */}
        {pages.map((page) => (
          <NavLink key={page.key} to={page.path} end className={navClass} {...named(page.name)}>
            <Icon name={page.icon} size={18} /><span className="navLabel">{page.name}</span>
          </NavLink>
        ))}
      </div>
      <div className="sidebarFoot">
        {user && <span className="sidebarUser">{user.employeeName ?? user.email}・{roleLabels[user.role]}</span>}
        <button className="ghostBtn" type="button" onClick={onChangePassword} {...named("改密碼")}>
          <Icon name="key" size={16} /><span className="navLabel">改密碼</span>
        </button>
        <button className="ghostBtn" type="button" onClick={() => { void logout(); }} {...named("登出")}>
          <Icon name="logout" size={16} /><span className="navLabel">登出</span>
        </button>
      </div>
    </nav>
  );
}
