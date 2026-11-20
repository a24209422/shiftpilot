import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router";
import { apiGet } from "../api/client";
import type { Booking, CalendarDay } from "../api/types";
import { usePermissions } from "../auth/usePermissions";
import { addDays, formatRange, formatTime, parseLocal, toLocalDate, toLocalString, weekStart } from "../forms/time";

const weekdayNames = ["一", "二", "三", "四", "五", "六", "日"];
const pad = (value: number) => String(value).padStart(2, "0");
// 小框太長會蓋住半個月曆，多的只顯示筆數
const popoverLimit = 6;

// 首頁的本月月曆：假日、補班日來自行事曆，每天顯示有幾筆排程；點某一天跳到排程頁的那一週
export function MonthCalendar() {
  const { can } = usePermissions();
  const navigate = useNavigate();
  const [month, setMonth] = useState(() => {
    const now = new Date();
    return new Date(now.getFullYear(), now.getMonth(), 1);
  });

  const monthEnd = new Date(month.getFullYear(), month.getMonth() + 1, 0);
  // 格子從第一週的週一排到最後一週的週日，前後會露出上、下個月的幾天
  const gridStart = weekStart(month);
  const gridEnd = addDays(weekStart(monthEnd), 7);
  const cells: Date[] = [];
  for (let day = gridStart; day < gridEnd; day = addDays(day, 1)) cells.push(day);

  const { data: days } = useQuery({
    queryKey: ["calendarDays", "month", toLocalDate(month)],
    queryFn: () => apiGet<CalendarDay[]>("/api/org/calendarDays", { from: toLocalDate(month), to: toLocalDate(monthEnd) }),
    enabled: can("org.read"),
  });
  const { data: bookings } = useQuery({
    // 放在 ["bookings", …] 底下：新增、修改、取消排程時的 invalidate 會一起更新月曆
    queryKey: ["bookings", "month", toLocalString(gridStart)],
    queryFn: () => apiGet<Booking[]>("/api/booking/bookings", { from: toLocalString(gridStart), to: toLocalString(gridEnd) }),
    enabled: can("booking.read"),
  });

  const today = toLocalDate(new Date());
  const dayInfo = (date: string) => (days ?? []).find((item) => item.day === date);
  // 跨日的排程在經過的每一天都要算到
  const bookingsOn = (day: Date) => {
    const next = addDays(day, 1);
    return (bookings ?? [])
      .filter((item) => parseLocal(item.startAt) < next && parseLocal(item.endAt) > day)
      .sort((a, b) => a.startAt.localeCompare(b.startAt));
  };
  // 同一天內只寫時間；跨日的寫出完整日期，才看得出是從哪天延續過來的
  const timeLabel = (item: Booking) => (
    item.startAt.slice(0, 10) === item.endAt.slice(0, 10) ? `${formatTime(item.startAt)}–${formatTime(item.endAt)}` : formatRange(item.startAt, item.endAt)
  );
  const shiftMonth = (offset: number) => setMonth(new Date(month.getFullYear(), month.getMonth() + offset, 1));

  return (
    <section className="monthBlock">
      <div className="monthHead">
        <h2 className="sectionTitle big">Calendar <small>{month.getFullYear()} / {month.getMonth() + 1}</small></h2>
        <div className="weekBar">
          <button className="secondary" type="button" onClick={() => shiftMonth(-1)}>上個月</button>
          <button className="secondary" type="button" onClick={() => { const now = new Date(); setMonth(new Date(now.getFullYear(), now.getMonth(), 1)); }}>本月</button>
          <button className="secondary" type="button" onClick={() => shiftMonth(1)}>下個月</button>
          {/* 行事曆頁不在導覽列，這是維護假日、補班日的入口 */}
          {can("org.manage") && <button className="secondary" type="button" onClick={() => navigate("/calendar")}>管理假日</button>}
        </div>
      </div>
      <div className="monthGrid">
        {weekdayNames.map((name) => <div className="monthWeekday" key={name}>{name}</div>)}
        {cells.map((day) => {
          const date = toLocalDate(day);
          const info = dayInfo(date);
          const dayBookings = bookingsOn(day);
          const count = dayBookings.length;
          const classes = [
            "monthCell",
            day.getMonth() !== month.getMonth() ? "outside" : "",
            date === today ? "today" : "",
            day.getDay() === 0 || day.getDay() === 6 ? "weekend" : "",
            info?.kind === "holiday" ? "holiday" : "",
            count > 0 ? "busy" : "",
            // 週六、週日在月曆最右邊，小框往左開才不會超出畫面
            day.getDay() === 0 || day.getDay() === 6 ? "popLeft" : "",
          ].filter(Boolean).join(" ");
          return (
            <button
              type="button" key={date} data-day={date} className={classes}
              onClick={() => navigate(`/bookings?week=${toLocalDate(weekStart(day))}`)}
              aria-label={`${day.getMonth() + 1} 月 ${day.getDate()} 日，${count} 筆排程${info ? `，${info.name}` : ""}`}
            >
              <span className="dayNo">{day.getDate() === 1 ? `${day.getMonth() + 1}/1` : pad(day.getDate())}</span>
              {info && <span className={`tag ${info.kind === "holiday" ? "ok" : "warn"}`}>{info.name}</span>}
              {count > 0 && <span className="dayCount">{count} 筆</span>}
              {count > 0 && (
                <span className="dayPopover" aria-hidden="true">
                  {dayBookings.slice(0, popoverLimit).map((item) => (
                    <span className="popItem" key={item.id}>
                      <span className="popTime">{timeLabel(item)}</span>
                      <span className="popTitle">{item.title}</span>
                      {item.resources.length > 0 && <span className="popMeta">{item.resources.map((resource) => resource.name).join("、")}</span>}
                    </span>
                  ))}
                  {count > popoverLimit && <span className="popMeta">還有 {count - popoverLimit} 筆</span>}
                </span>
              )}
            </button>
          );
        })}
      </div>
    </section>
  );
}
