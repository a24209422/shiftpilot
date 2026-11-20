import { useCallback } from "react";
import { useSearchParams } from "react-router";

type Mode = "view" | "edit" | "new";

// 新增表單的帶入值（時間軸點空檔時帶來的）也算面板的一部分，關掉面板就要一起清掉
const panelKeys = ["id", "edit", "new", "resourceId", "startAt", "endAt"];

// 詳情面板的狀態放在網址：?id=3（看）、?id=3&edit=1（編輯）、?new=1（新增），重新整理不會丟
export function useDrawerParams() {
  const [params, setParams] = useSearchParams();
  const id = params.get("id");
  const mode: Mode | null = params.get("new") ? "new" : id ? (params.get("edit") ? "edit" : "view") : null;

  // 其他查詢參數（例如 week）要保留，只動面板自己的三個
  const replacePanel = useCallback((panel: Record<string, string>) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      panelKeys.forEach((key) => next.delete(key));
      Object.entries(panel).forEach(([key, value]) => next.set(key, value));
      return next;
    });
  }, [setParams]);

  return {
    selectedId: id,
    mode,
    openView: (target: string) => replacePanel({ id: target }),
    openEdit: (target: string) => replacePanel({ id: target, edit: "1" }),
    openNew: () => replacePanel({ new: "1" }),
    close: useCallback(() => replacePanel({}), [replacePanel]),
  };
}
