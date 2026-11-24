import { useLocation } from "react-router";

const storageKey = "shiftpilot.dev";

// demo 用的是建置好的前端，不能靠 import.meta.env.DEV；用網址開關，記在瀏覽器裡，換頁也不會掉
export function useDevMode(): boolean {
  const { search } = useLocation();
  const value = new URLSearchParams(search).get("dev");
  if (value === "1") {
    localStorage.setItem(storageKey, "1");
    return true;
  }
  if (value === "0") {
    localStorage.removeItem(storageKey);
    return false;
  }
  return localStorage.getItem(storageKey) === "1";
}
