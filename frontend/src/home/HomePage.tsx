import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router";
import { apiGet } from "../api/client";
import type { BookingSummary } from "../api/types";
import { usePermissions } from "../auth/usePermissions";
import { formatRange, formatTime, toLocalDate } from "../forms/time";
import { navPages, type ModuleRegistration } from "../modules/registry";
import { Icon } from "../shell/icons";
import { PageHead } from "../shell/PageHead";
import { MonthCalendar } from "./MonthCalendar";

const pad = (value: number) => String(value).padStart(2, "0");

export function HomePage({ registrations }: { registrations: ModuleRegistration[] }) {
  const { can } = usePermissions();
  const navigate = useNavigate();
  const canSee = can("booking.read");
  const { data: summary } = useQuery({ queryKey: ["summary"], queryFn: () => apiGet<BookingSummary>("/api/booking/summary"), enabled: canSee });
  const pages = navPages(registrations, can);

  const now = new Date();
  const today = toLocalDate(now);
  const stamp = `'${String(now.getFullYear()).slice(2)}  ${pad(now.getMonth() + 1)}  ${pad(now.getDate())}  ${pad(now.getHours())}:${pad(now.getMinutes())}`;

  const todayBookings = summary?.todayBookings ?? [];
  const next = summary?.nextBooking ?? null;
  const rooms = (summary?.resourceStatus ?? []).filter((item) => item.kind === "room");
  const busyRooms = rooms.filter((item) => item.currentBooking).length;
  const nextIsToday = next !== null && next.startAt.slice(0, 10) === today;

  const stats = summary ? [
    { label: "今天的排程", value: String(todayBookings.length), note: nextIsToday ? `下一場 ${formatTime(next!.startAt)}` : "今天沒有下一場了" },
    { label: "會議室使用中", value: `${busyRooms}/${rooms.length}`, note: "此刻" },
    { label: "接下來的排程", value: String(summary.bookingCount), note: "還沒結束的已確認排程" },
    { label: "資源", value: String(summary.resourceCount), note: "可以預約" },
  ] : [];

  return (
    <div className="inner">
      <PageHead
        headline="Ask, don’t dig."
        action={can("booking.write") && (
          <button className="primary" type="button" onClick={() => navigate("/bookings?new=1")}><Icon name="plus" size={16} />新增排程</button>
        )}
      />

      {summary && (
        <section className="stats">
          {stats.map((stat) => (
            <div className="stat" key={stat.label}>
              <div className="statLabel">{stat.label}</div>
              <div className="statValue">{stat.value}</div>
              <div className="statNote">{stat.note}</div>
            </div>
          ))}
        </section>
      )}

      <section className="modulesBlock">
        <h2 className="sectionTitle big">All modules</h2>
        <div className="launcher">
          {pages.map((page, index) => (
            <button className="tile" type="button" key={page.key} onClick={() => navigate(page.path)}>
              <span className="tileTop"><span className="tileNo">No.{pad(index + 1)}</span><span>↗</span></span>
              <span className="tileIcon"><Icon name={page.icon} size={34} /></span>
              <span className="tileName">{page.en}</span>
              <span className="tileZh">{page.name}</span>
            </button>
          ))}
        </div>
      </section>

      {summary && (
        <>
          <section className="split">
            <article className="feature">
              <div className="photo"><div className="photoInner" /><span className="stamp">{stamp}</span></div>
              <div className="featureBody">
                <h3>Next up</h3>
                {next ? (
                  <>
                    <p className="featureTitle">{next.title}</p>
                    <p className="featureMeta">{formatRange(next.startAt, next.endAt)} ／ {next.resources.map((item) => item.name).join("、") || "沒有指定資源"}</p>
                  </>
                ) : (
                  <>
                    <p className="featureTitle">沒有接下來的排程</p>
                    <p className="featureMeta">&nbsp;</p>
                  </>
                )}
                <button className="textLink" type="button" onClick={() => navigate("/bookings")}>View all events →</button>
              </div>
            </article>
            <div className="panel">
              <h2 className="sectionTitle">Rooms right now</h2>
              {rooms.map((room) => (
                <div className="roomRow" key={room.resourceId}>
                  <div>
                    <div className="roomName">{room.name}</div>
                    <div className="roomNote">{room.currentBooking ? room.currentBooking.title : "目前沒有排程"}</div>
                  </div>
                  <span className={`tag ${room.currentBooking ? "warn" : "ok"}`}>{room.currentBooking ? "使用中" : "空著"}</span>
                </div>
              ))}
              {rooms.length === 0 && <div className="empty">沒有會議室</div>}
            </div>
          </section>

          <section className="panel">
            <h2 className="sectionTitle big">On the run sheet <small>({todayBookings.length})</small></h2>
            {todayBookings.length === 0 ? <div className="empty">今天沒有排程</div> : (
              <div className="tableWrap">
                <table>
                  <thead><tr><th>時間</th><th>標題</th><th>資源</th></tr></thead>
                  <tbody>
                    {todayBookings.map((item) => (
                      <tr key={item.id} onClick={() => navigate(`/bookings?id=${item.id}`)}>
                        <td className="mono">{formatTime(item.startAt)}–{formatTime(item.endAt)}</td>
                        <td>{item.title}</td>
                        <td>{item.resources.map((resource) => resource.name).join("、") || "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
      <MonthCalendar />
    </div>
  );
}
