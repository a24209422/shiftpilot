import { createContext, useContext, useEffect } from "react";
import type { ReactNode } from "react";

// 背景浮水印畫在 Shell 不捲動的那一層，拿不到各頁的標題，所以由 PageHead 把標題往上交。
// 預設是什麼都不做：單獨測試頁面時沒有 Shell，PageHead 照樣能用
export const PageTitleContext = createContext<(title: string | null) => void>(() => {});

export function PageHead({ headline, action }: { headline: string; action?: ReactNode }) {
  const setPageTitle = useContext(PageTitleContext);
  useEffect(() => {
    setPageTitle(headline);
    // 離開頁面就清掉，下一頁沒有標題時不會留著上一頁的浮水印
    return () => setPageTitle(null);
  }, [headline, setPageTitle]);
  return (
    <header className="pageHead">
      <div>
        <h1 className="headline">{headline}</h1>
      </div>
      {action}
    </header>
  );
}
