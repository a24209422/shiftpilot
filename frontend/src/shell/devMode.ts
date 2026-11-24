import { useLocation } from "react-router";

const storageKey = "shiftpilot.dev";

// demo 用的是建置好的前端，不能靠 import.meta.env.DEV；用網址開關，記在瀏覽器裡，換頁也不會掉
export function useDevMode(): boolean {
  const { search } = useLocation();
  const value = new URLSearchParams(search).get("dev");
  if (value === "1") {
    safely(() => localStorage.setItem(storageKey, "1"));
    return true;
  }
  if (value === "0") {
    safely(() => localStorage.removeItem(storageKey));
    return false;
  }
  return safely(() => localStorage.getItem(storageKey)) === "1";
}

// 瀏覽器停用網站資料時 localStorage 會丟例外；開發者模式只是方便，不能因此讓面板壞掉
function safely<T>(action: () => T): T | null {
  try {
    return action();
  } catch {
    return null;
  }
}
