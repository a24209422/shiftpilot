import { useEffect, useState } from "react";
import { apiSend } from "../../api/client";
import type { User } from "../../api/types";
import { roleLabels } from "../../auth/roles";
import { TextField } from "../../forms/fields";
import { FormError } from "../../forms/FormError";
import { formatDay, formatTime, parseLocal } from "../../forms/time";
import { useSubmit } from "../../forms/useSubmit";
import { DataTable, type Column } from "../../shell/DataTable";
import { DetailList } from "../../shell/DetailList";
import { Drawer } from "../../shell/Drawer";
import { Icon } from "../../shell/icons";
import { PageHead } from "../../shell/PageHead";
import { useToast } from "../../shell/Toast";
import { useDrawerParams } from "../../shell/useDrawerParams";
import { useUsers } from "./queries";
import { UserForm } from "./UserForm";

const isLocked = (user: User) => user.lockedUntil !== null && parseLocal(user.lockedUntil) > new Date();
const stateText = (user: User) => (!user.isActive ? "已停用" : isLocked(user) ? "鎖定中" : "啟用");
const StateTag = ({ user }: { user: User }) => (
  <span className={`tag ${!user.isActive ? "mute" : isLocked(user) ? "bad" : "ok"}`}>{stateText(user)}</span>
);
const lastLogin = (user: User) => (user.lastLoginAt ? `${formatDay(user.lastLoginAt)} ${formatTime(user.lastLoginAt)}` : "從未");

const columns: Column<User>[] = [
  { label: "Email", render: (row) => row.email, text: (row) => row.email },
  { label: "角色", render: (row) => roleLabels[row.role], text: (row) => roleLabels[row.role] },
  { label: "連結員工", render: (row) => row.employeeName ?? "—", text: (row) => row.employeeName ?? "" },
  { label: "最後登入", render: lastLogin, text: lastLogin },
  { label: "狀態", render: (row) => <StateTag user={row} />, text: stateText },
];

function UserActions({ user, onEdit }: { user: User; onEdit(): void }) {
  const toast = useToast();
  const [resetting, setResetting] = useState(false);
  const [next, setNext] = useState("");
  const [again, setAgain] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const reset = useSubmit(
    () => apiSend("POST", `/api/core/users/${user.id}/password`, { newPassword: next }),
    { onSuccess: () => { toast("已重設密碼"); setResetting(false); setNext(""); setAgain(""); } },
  );

  function confirm() {
    if (next !== again) { setLocalError("兩次輸入的新密碼不一樣"); return; }
    if (next.length < 8 || next.length > 128) { setLocalError("密碼要 8 到 128 字元"); return; }
    setLocalError(null);
    void reset.submit();
  }

  if (resetting) {
    return (
      <div className="form" style={{ width: "100%" }}>
        <TextField label="新密碼" type="password" value={next} onChange={setNext} />
        <TextField label="再輸入一次新密碼" type="password" value={again} onChange={setAgain} />
        {localError && <div className="formError" role="alert">{localError}</div>}
        <FormError error={reset.error} />
        <div className="formActions">
          <button className="danger" type="button" disabled={reset.pending} onClick={confirm}>確定重設</button>
          <button className="secondary" type="button" onClick={() => setResetting(false)}>先不要</button>
        </div>
      </div>
    );
  }
  return (
    <>
      <button className="primary" type="button" onClick={onEdit}>編輯</button>
      <button className="danger" type="button" onClick={() => setResetting(true)}>重設密碼</button>
    </>
  );
}

export function UsersPage() {
  const { data, isSuccess } = useUsers();
  const drawer = useDrawerParams();
  const users = data ?? [];
  const selected = users.find((item) => String(item.id) === drawer.selectedId) ?? null;

  useEffect(() => {
    if (isSuccess && (drawer.mode === "view" || drawer.mode === "edit") && !selected) drawer.close();
  }, [isSuccess, drawer.mode, selected]); // eslint-disable-line react-hooks/exhaustive-deps

  const open = drawer.mode === "new" || (drawer.mode !== null && selected !== null);

  return (
    <div className="inner">
      <PageHead
        headline="Accounts"
        action={<button className="primary" type="button" onClick={drawer.openNew}><Icon name="plus" size={16} />新增帳號</button>}
      />
      <DataTable
        columns={columns} rows={users} rowKey={(row) => String(row.id)} selectedKey={drawer.selectedId}
        onSelect={(row) => drawer.openView(String(row.id))} filterPlaceholder="篩選帳號…"
      />
      <Drawer
        open={open} title={drawer.mode === "new" ? "新增帳號" : selected?.email ?? ""} onClose={drawer.close}
        footer={drawer.mode === "view" && selected ? <UserActions key={selected.id} user={selected} onEdit={() => drawer.openEdit(String(selected.id))} /> : undefined}
      >
        {drawer.mode === "new" && <UserForm onDone={drawer.close} />}
        {drawer.mode === "edit" && selected && <UserForm key={selected.id} user={selected} onDone={() => drawer.openView(String(selected.id))} />}
        {drawer.mode === "view" && selected && (
          <DetailList
            items={[
              ["Email", selected.email], ["角色", roleLabels[selected.role]], ["連結員工", selected.employeeName ?? "—"],
              ["最後登入", lastLogin(selected)], ["狀態", <StateTag key="s" user={selected} />],
              ["建立時間", `${formatDay(selected.createdAt)} ${formatTime(selected.createdAt)}`],
            ]}
          />
        )}
      </Drawer>
    </div>
  );
}
