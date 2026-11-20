import { useState, type FormEvent } from "react";
import { ApiError, apiSend } from "../api/client";
import { useAuth } from "../auth/AuthProvider";
import { Drawer } from "./Drawer";

export function ChangePasswordDrawer({ open, onClose }: { open: boolean; onClose(): void }) {
  const { signOutWithNotice } = useAuth();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (pending) return;
    if (next !== again) {
      setError("兩次輸入的新密碼不一樣");
      return;
    }
    setPending(true);
    setError(null);
    try {
      await apiSend("POST", "/api/auth/password", { currentPassword: current, newPassword: next });
      // 後端改密碼後會刪掉所有 session（包含這一個），所以要回登入頁
      signOutWithNotice("密碼已更新，請用新密碼登入");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "更新失敗，請再試一次");
      setPending(false);
    }
  }

  return (
    <Drawer open={open} title="改密碼" onClose={onClose}>
      <form className="form" onSubmit={submit}>
        <div className="field"><label htmlFor="pwCurrent">目前密碼</label><input id="pwCurrent" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} /></div>
        <div className="field"><label htmlFor="pwNext">新密碼</label><input id="pwNext" type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} /></div>
        <div className="field"><label htmlFor="pwAgain">再輸入一次新密碼</label><input id="pwAgain" type="password" autoComplete="new-password" value={again} onChange={(e) => setAgain(e.target.value)} /></div>
        {error && <div className="formError" role="alert">{error}</div>}
        <div className="formActions"><button className="primary" type="submit" disabled={pending}>更新密碼</button></div>
      </form>
    </Drawer>
  );
}
