// 線條圖示：直角、不填色，跟整體的方正風格一致；用 currentColor，反白時會跟著變色
const iconPaths = {
  home: '<path d="M3 11l9-8 9 8"/><path d="M5 10v10h14V10"/>',
  events: '<rect x="3" y="5" width="18" height="16"/><path d="M3 10h18M8 3v4M16 3v4"/>',
  timeline: '<path d="M3 6h9M7 12h11M3 18h7"/><path d="M14 4v4M20 10v4M12 16v4"/>',
  calendar: '<rect x="3" y="5" width="18" height="16"/><path d="M3 10h18M8 3v4M16 3v4M8 14h2M14 14h2M8 17h2"/>',
  shift: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7v5l3.5 2"/>',
  leave: '<path d="M4 20h16M12 20V9"/><path d="M12 9c-4 0-7 2-8 5 3-1 6-1 8-5zM12 9c4 0 7 2 8 5-3-1-6-1-8-5z"/><path d="M12 9c0-3 1-5 3-6"/>',
  resources: '<path d="M3 7l9-4 9 4-9 4-9-4z"/><path d="M3 7v10l9 4 9-4V7M12 11v10"/>',
  people: '<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20c0-3.6 2.9-6 6.5-6s6.5 2.4 6.5 6"/><circle cx="17" cy="9" r="2.5"/><path d="M17 14c2.6 0 4.5 1.8 4.5 5"/>',
  building: '<path d="M4 21V4h10v17M14 9h6v12M2 21h20M8 8h2M8 12h2M8 16h2"/>',
  key: '<circle cx="8" cy="12" r="4"/><path d="M12 12h9M18 12v4M21 12v3"/>',
  log: '<path d="M5 3h14v18H5z"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  close: '<path d="M5 5l14 14M19 5L5 19"/>',
  chat: '<path d="M4 5h16v11H9l-5 4V5z"/>',
  arrowUp: '<path d="M12 20V5M5 12l7-7 7 7"/>',
  chevron: '<path d="M9 5l7 7-7 7"/>',
};

export type IconName = keyof typeof iconPaths;

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return (
    <svg
      className="ico" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.6" strokeLinecap="square" strokeLinejoin="miter" aria-hidden="true"
      // 路徑是這個檔案裡寫死的常數，不是使用者輸入
      dangerouslySetInnerHTML={{ __html: iconPaths[name] }}
    />
  );
}
