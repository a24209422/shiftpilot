import { useEffect, useRef } from "react";

// 主內容區的背景浮水印：右上、左下各一個二十邊晶格，再往中央空白延伸幾條細線。
// 只是裝飾，所以畫在 canvas 上、不進無障礙樹；畫不出來（例如測試環境沒有 canvas）就什麼都不顯示

interface Medallion { x: number; y: number; r: number }
interface Point { x: number; y: number }

// 二十邊形的頂點從 π/20 起算，讓上下各有一條水平邊，晶格看起來比較穩
const sides = 20;
const baseRotation = Math.PI / sides;

function vertices(cx: number, cy: number, r: number, n: number, rotation: number): Point[] {
  return Array.from({ length: n }, (_, i) => {
    const angle = rotation + (i / n) * Math.PI * 2;
    return { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) };
  });
}

function drawChords(ctx: CanvasRenderingContext2D, points: Point[], step: number, lineWidth: number, alpha: number) {
  ctx.save();
  ctx.beginPath();
  ctx.lineWidth = lineWidth;
  ctx.globalAlpha *= alpha;
  points.forEach((point, i) => {
    const target = points[(i + step) % points.length];
    ctx.moveTo(point.x, point.y);
    ctx.lineTo(target.x, target.y);
  });
  ctx.stroke();
  ctx.restore();
}

function strokeCircle(ctx: CanvasRenderingContext2D, x: number, y: number, r: number, lineWidth: number, alpha: number) {
  ctx.beginPath();
  ctx.lineWidth = lineWidth;
  ctx.globalAlpha = alpha;
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.stroke();
}

function drawLattice(ctx: CanvasRenderingContext2D, { x, y, r }: Medallion) {
  ctx.save();
  const points = vertices(x, y, r, sides, baseRotation);
  drawChords(ctx, points, 1, 2.0, 1);
  drawChords(ctx, points, 3, 1.15, 0.8);
  drawChords(ctx, points, 5, 1.35, 0.9);
  drawChords(ctx, points, 7, 1.0, 0.72);
  drawChords(ctx, points, 2, 0.75, 0.6);
  drawChords(ctx, points, 4, 0.8, 0.65);

  // 中央的天文儀：同心環加兩個偏心環，外圈一圈刻度
  const core = r * 0.32;
  strokeCircle(ctx, x, y, core, 1.0, 0.85);
  strokeCircle(ctx, x + core * 0.16, y - core * 0.12, core * 0.65, 0.7, 0.7);
  strokeCircle(ctx, x - core * 0.16, y + core * 0.12, core * 0.45, 0.65, 0.65);
  ctx.beginPath();
  ctx.lineWidth = 0.55;
  ctx.globalAlpha = 0.6;
  for (let i = 0; i < 12; i++) {
    const angle = (i / 12) * Math.PI * 2;
    ctx.moveTo(x + core * 0.78 * Math.cos(angle), y + core * 0.78 * Math.sin(angle));
    ctx.lineTo(x + core * Math.cos(angle), y + core * Math.sin(angle));
  }
  ctx.stroke();
  ctx.restore();
}

type RayCap = "node" | "square" | "satellite";

function drawExtensions(ctx: CanvasRenderingContext2D, top: Medallion, bottom: Medallion, width: number, height: number) {
  ctx.save();
  // 射線對齊頂點角度，看起來才像是從晶格本身長出來的
  const vertexAngle = (k: number) => baseRotation + k * (Math.PI * 2) / sides;
  const along = (m: Medallion, angle: number, factor: number): Point => ({
    x: m.x + m.r * factor * Math.cos(angle), y: m.y + m.r * factor * Math.sin(angle),
  });

  const orbits = (m: Medallion, from: number, to: number) => {
    ctx.beginPath();
    ctx.lineWidth = 1.1;
    ctx.globalAlpha = 0.85;
    ctx.arc(m.x, m.y, m.r * 1.14, from, to);
    ctx.stroke();
    ctx.beginPath();
    ctx.lineWidth = 1.0;
    ctx.globalAlpha = 0.75;
    ctx.setLineDash([4, 7]);
    ctx.arc(m.x, m.y, m.r * 1.32, from + 0.06, to - 0.06);
    ctx.stroke();
    ctx.setLineDash([]);
  };

  const satellite = (center: Point, r: number, rotation: number) => {
    const points = vertices(center.x, center.y, r, 10, rotation);
    drawChords(ctx, points, 1, 1.2, 0.95);
    drawChords(ctx, points, 3, 0.9, 0.85);
  };

  const rays = (m: Medallion, list: [number, number, RayCap][]) => {
    for (const [k, length, cap] of list) {
      const angle = vertexAngle(k);
      const start = along(m, angle, 1);
      const end = along(m, angle, length);
      ctx.beginPath();
      ctx.lineWidth = 1.1;
      ctx.globalAlpha = 0.85;
      ctx.moveTo(start.x, start.y);
      ctx.lineTo(end.x, end.y);
      // 射線穿過內圈軌道的地方加一道刻度
      const cross = along(m, angle, 1.14);
      const nx = -Math.sin(angle) * 5;
      const ny = Math.cos(angle) * 5;
      ctx.moveTo(cross.x - nx, cross.y - ny);
      ctx.lineTo(cross.x + nx, cross.y + ny);
      ctx.stroke();
      ctx.globalAlpha = 0.95;
      if (cap === "node") {
        ctx.beginPath();
        ctx.arc(end.x, end.y, 5, 0, Math.PI * 2);
        ctx.stroke();
      } else if (cap === "square") {
        ctx.strokeRect(end.x - 5.5, end.y - 5.5, 11, 11);
      } else {
        satellite(along(m, angle, length + 0.06), Math.max(22, m.r * 0.08), angle);
      }
    }
  };

  // 軌道與射線只畫朝向畫面中央的那一側，另一側本來就在畫面外
  orbits(top, Math.PI * 0.5, Math.PI * 1.08);
  rays(top, [[5, 1.24, "square"], [7, 1.42, "node"], [8, 1.28, "satellite"], [10, 1.2, "node"]]);
  orbits(bottom, -Math.PI * 0.5, -Math.PI * 0.02);
  rays(bottom, [[-1, 1.45, "node"], [-2, 1.22, "square"], [-3, 1.55, "satellite"], [-4, 1.3, "node"]]);

  // 十字記號用比例定位，縮放視窗時跟著版面走，不會亂跳
  ctx.lineWidth = 1.0;
  ctx.globalAlpha = 0.8;
  ctx.beginPath();
  for (const [fx, fy] of [[0.44, 0.42], [0.58, 0.64], [0.34, 0.6], [0.66, 0.36], [0.5, 0.84]]) {
    const x = width * fx;
    const y = height * fy;
    ctx.moveTo(x - 7, y);
    ctx.lineTo(x + 7, y);
    ctx.moveTo(x, y - 7);
    ctx.lineTo(x, y + 7);
  }
  ctx.stroke();
  ctx.restore();
}

function render(canvas: HTMLCanvasElement) {
  // 先看尺寸再拿 context：jsdom 沒有版面、寬高都是 0，這樣測試時就不會去碰它沒實作的 getContext
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (!width || !height) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  // 高解析螢幕要放大畫布才不會糊，但超過 2 倍看不出差別，只是浪費記憶體
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);

  // 墨色跟著主題的褐灰色走，之後改色票不用回來改這裡
  const ink = getComputedStyle(canvas).getPropertyValue("--base-300").trim() || "#6e6150";
  ctx.strokeStyle = ink;
  ctx.fillStyle = ink;
  ctx.lineCap = "square";
  ctx.lineJoin = "miter";

  const minSide = Math.min(width, height);
  const topRadius = Math.max(300, Math.min(580, minSide * 0.64));
  const top = { x: width - topRadius * 0.6, y: topRadius * 0.5, r: topRadius };
  const bottomRadius = Math.max(230, Math.min(400, minSide * 0.45));
  const bottom = { x: -bottomRadius * 0.08, y: height + bottomRadius * 0.08, r: bottomRadius };
  drawLattice(ctx, top);
  drawLattice(ctx, bottom);
  drawExtensions(ctx, top, bottom, width, height);
}

export function GeoBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const redraw = () => render(canvas);
    redraw();
    // 聊天面板拉寬、導覽列收合都會改變主內容區大小，光聽 window resize 抓不到
    if (typeof ResizeObserver === "undefined") {
      window.addEventListener("resize", redraw);
      return () => window.removeEventListener("resize", redraw);
    }
    const observer = new ResizeObserver(redraw);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  return <canvas ref={canvasRef} className="geoCanvas" aria-hidden="true" />;
}
