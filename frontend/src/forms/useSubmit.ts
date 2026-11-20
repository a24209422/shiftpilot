import { useQueryClient, type QueryKey } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { ApiError } from "../api/client";

// 後端的欄位錯誤有兩種寫法：details.fields[].loc（請求格式錯）與 details.field（規則檢查）
function fieldErrorsOf(error: ApiError | null): Record<string, string> {
  const result: Record<string, string> = {};
  const details = error?.details as { fields?: { loc: (string | number)[]; message: string }[]; field?: string } | null;
  for (const item of details?.fields ?? []) {
    const name = item.loc[item.loc.length - 1];
    if (typeof name === "string") result[name] = item.message;
  }
  if (details?.field && error) result[details.field] = error.message;
  return result;
}

interface Options<T> {
  onSuccess(result: T): void;
  invalidate?: QueryKey[];
}

export function useSubmit<T>(action: () => Promise<T>, { onSuccess, invalidate = [] }: Options<T>) {
  const queryClient = useQueryClient();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);
  // 用 ref 擋重複送出：state 要等下一次 render 才更新，連點兩下會兩次都通過
  const busy = useRef(false);

  async function submit() {
    if (busy.current) return;
    busy.current = true;
    setPending(true);
    setError(null);
    try {
      const result = await action();
      // 等列表重新讀完再回呼，呼叫端關面板時畫面已經是新資料
      await Promise.all(invalidate.map((key) => queryClient.invalidateQueries({ queryKey: key }).catch(() => {})));
      onSuccess(result);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught : new ApiError(0, "UNKNOWN", "送出失敗，請再試一次"));
    } finally {
      busy.current = false;
      setPending(false);
    }
  }

  return { submit, pending, error, fieldErrors: fieldErrorsOf(error) };
}
