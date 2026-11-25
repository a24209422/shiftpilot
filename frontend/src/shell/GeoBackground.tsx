import { useLayoutEffect, useRef } from "react";

// 主內容區的背景浮水印：目前頁面的標題一字一行、斜放在左上。
// 只是裝飾，所以不進無障礙樹，螢幕閱讀器不會把標題多念一次

const tilt = (16 * Math.PI) / 180;
const maxSize = 380;
// 量字寬用的基準字級：offsetWidth 不受 rotate 影響，量一次再等比例換算就好
const probeSize = 100;

function fit(el: HTMLDivElement) {
  const area = el.parentElement;
  if (!area) return;
  el.style.fontSize = `${probeSize}px`;
  const widest = Math.max(...Array.from(el.children, (child) => (child as HTMLElement).offsetWidth));
  const block = el.offsetHeight;
  const width = area.clientWidth;
  const height = area.clientHeight;
  // jsdom 沒有版面、量出來都是 0，這時保留 CSS 的預設字級
  if (!widest || !block || !width || !height) {
    el.style.removeProperty("font-size");
    return;
  }
  // 盡量貼左上角：只留一點邊，斜體字頭才不會被左緣切掉
  const left = width * 0.005;
  // 寬、高都要塞得下，每個字才看得到：寬看最長那行斜放後的水平跨度；
  // 高看字尾升起的那一截加上整疊字斜放後的高度，像首頁標題三行疊起來最容易超出底部
  const byWidth = (width * 0.94 - left) / (widest * Math.cos(tilt));
  const byHeight = (height * 0.96) / (widest * Math.sin(tilt) + block * Math.cos(tilt));
  // 短標題也不放大超過原本的上限
  const size = Math.min(maxSize, Math.min(byWidth, byHeight) * probeSize);
  const lineWidth = (widest / probeSize) * size;
  el.style.fontSize = `${size}px`;
  el.style.left = `${left}px`;
  // 往右上斜的那一截會升高，起點跟著往下移同樣的高度，字尾才不會被主內容區頂端切掉
  el.style.top = `${lineWidth * Math.sin(tilt)}px`;
}

export function GeoBackground({ title }: { title: string | null }) {
  const ref = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const el = ref.current;
    const area = el?.parentElement;
    if (!el || !area) return;
    const refit = () => fit(el);
    refit();
    // 聊天面板拉寬、導覽列收合都會改變主內容區寬度，光聽 window resize 抓不到
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", refit);
      return () => window.removeEventListener("resize", refit);
    }
    const observer = new ResizeObserver(refit);
    observer.observe(area);
    return () => observer.disconnect();
  }, [title]);

  if (!title) return null;
  return (
    <div ref={ref} className="bgWatermark" aria-hidden="true">
      {title.split(/\s+/).map((word, i) => <span key={i}>{word}</span>)}
    </div>
  );
}
