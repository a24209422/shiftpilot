import { useQueries, useQuery } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { usePermissions } from "../auth/usePermissions";
import { addDays, formatDay, formatRange, toLocalDate, toLocalString } from "../forms/time";
import type { ModuleRegistration } from "../modules/registry";
import { PageHead } from "../shell/PageHead";
import { Tabs } from "../shell/Tabs";
import { axisFor, clipToDay, groupSubjects, halfDayGroups, minuteLabel, minuteToLocal, parseDay, percentOf, slotFor, slotStep, type Axis } from "./layout";
import type { TimelineSource, TimelineView } from "./types";

// 現在時間線要跟著走，一分鐘更新一次就夠
function useNow() {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 60_000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

// 長條顏色的數量，對應 global.css 的 .tlTone0 到 .tlTone4
const toneCount = 5;

const placeStyle = (axis: Axis, startMinute: number, endMinute: number) => ({
  left: `${percentOf(axis, startMinute)}%`,
  width: `${percentOf(axis, endMinute) - percentOf(axis, startMinute)}%`,
});

export function TimelinePage({ registrations }: { registrations: ModuleRegistration[] }) {
  const { can } = usePermissions();
  const [params, setParams] = useSearchParams();
  const views = registrations.flatMap((registration) => registration.timelineViews ?? []).filter((view) => can(view.requires));
  const view = views.find((item) => item.key === params.get("view")) ?? views[0];
  if (!view) return <div className="empty">沒有可以看的時間軸</div>;
  const sources = registrations
    .flatMap((registration) => registration.timelineSources ?? [])
    .filter((source) => source.subjectType === view.subjectType && can(source.requires));
  const create = view.createLink && view.createRequires && can(view.createRequires) ? view.createLink : undefined;
  // 換檢視時保留日期，只換 view
  const selectView = (key: string) => setParams((current) => {
    const next = new URLSearchParams(current);
    next.set("view", key);
    return next;
  });
  const tabs = views.length > 1 ? <Tabs tabs={views.map((item) => ({ key: item.key, label: item.name }))} value={view.key} onChange={selectView} /> : null;
  return <TimelineBoard key={view.key} view={view} sources={sources} create={create} tabs={tabs} />;
}

function TimelineBoard({ view, sources, create, tabs }: {
  view: TimelineView; sources: TimelineSource[]; create?: (subjectId: number, startAt: string, endAt: string) => string; tabs: ReactNode;
}) {
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const now = useNow();
  const day = parseDay(params.get("date"), now);
  const from = toLocalString(day);
  const to = toLocalString(addDays(day, 1));

  const subjects = useQuery(view.subjects());
  const results = useQueries({ queries: sources.map((source) => source.items(from, to)) });
  // 一個來源失敗不能默默少畫：其他照畫，但要說出哪個來源沒載到
  const failed = sources.filter((_, index) => results[index]?.isError).map((source) => source.name);

  const rows = subjects.data ?? [];
  const rowIds = new Set(rows.map((subject) => subject.id));
  const placed = results
    .flatMap((result) => result.data ?? [])
    .flatMap((item) => {
      const span = clipToDay(day, item);
      // 不屬於任何一列的項目（例如停用資源上的排程）不畫
      return span && rowIds.has(item.subjectId) ? [{ item, span }] : [];
    });
  const axis = axisFor(placed.map((entry) => entry.span));
  const cells: number[] = [];
  for (let minute = axis.startMinute; minute < axis.endMinute; minute += slotStep) cells.push(minute);
  const hours: number[] = [];
  for (let minute = axis.startMinute; minute < axis.endMinute; minute += 60) hours.push(minute);
  const nowMinute = now.getHours() * 60 + now.getMinutes();
  const showNow = toLocalDate(day) === toLocalDate(now) && nowMinute >= axis.startMinute && nowMinute <= axis.endMinute;
  const goTo = (date: Date) => setParams((current) => {
    const next = new URLSearchParams(current);
    next.set("date", toLocalDate(date));
    return next;
  });

  return (
    <div className="inner">
      <PageHead headline="Timeline" />
      {tabs}
      <div className="weekBar">
        <button className="secondary" type="button" onClick={() => goTo(addDays(day, -1))}>前一天</button>
        <button className="secondary" type="button" onClick={() => goTo(now)}>今天</button>
        <button className="secondary" type="button" onClick={() => goTo(addDays(day, 1))}>後一天</button>
        <span className="range">{formatDay(from)}</span>
      </div>
      {failed.length > 0 && <div className="formError" role="alert">{failed.join("、")}載入失敗</div>}
      {subjects.isError && <div className="formError" role="alert">{view.name}載入失敗</div>}
      {subjects.isSuccess && rows.length === 0 && <div className="empty">{view.emptyText}</div>}
      {rows.length > 0 && (
        <div className="timeline">
          <div className="tlHead">
            <div className="tlHeadName">{view.name}</div>
            <div className="tlHeadTrack">
              <div className="tlHalves">
                {halfDayGroups(axis).map((half) => (
                  <span key={half.label} className="tlHalf" style={placeStyle(axis, half.startMinute, half.endMinute)}>{half.label}</span>
                ))}
              </div>
              <div className="tlHours">
                {hours.map((minute) => (
                  <span key={minute} className="tlHour" style={placeStyle(axis, minute, minute + 60)}>{minuteLabel(minute)}</span>
                ))}
              </div>
            </div>
          </div>
          {groupSubjects(rows).map((group) => (
            <div key={group.name} className="tlGroup">
              <div className="tlGroupName">{group.name}</div>
              {group.subjects.map((subject) => {
                const row = placed.filter((entry) => entry.item.subjectId === subject.id);
                const spans = row.map((entry) => entry.span);
                // 跟範本一樣每一列一個顏色；用列在整張圖的順序輪流，換日期也不會變色
                const tone = rows.indexOf(subject) % toneCount;
                return (
                  <div key={subject.id} className={`tlRow tlTone${tone}`}>
                    <div className="tlName"><span>{subject.label}</span></div>
                    <div className="tlTrack">
                      {hours.map((minute, index) => index % 2 === 1 && (
                        <div key={minute} className="tlStripe" style={placeStyle(axis, minute, minute + 60)} />
                      ))}
                      {create && cells.map((cell) => {
                        const slot = slotFor(cell, spans);
                        if (!slot) return null;
                        return (
                          <button
                            key={cell} type="button" className="tlCell" style={placeStyle(axis, cell, cell + slotStep)}
                            aria-label={`${subject.label} ${minuteLabel(cell)} 新增排程`}
                            onClick={() => navigate(create(subject.id, minuteToLocal(day, slot.startMinute), minuteToLocal(day, slot.endMinute)))}
                          />
                        );
                      })}
                      {row.map(({ item, span }) => {
                        const className = `${item.kind === "block" ? "tlBlock" : "tlBar"}${item.muted ? " tlMuted" : ""}`;
                        const style = placeStyle(axis, span.startMinute, span.endMinute);
                        const title = `${item.label} ${formatRange(item.startAt, item.endAt)}`;
                        const text = `${item.label}${span.crossesDay ? "（跨日）" : ""}`;
                        return item.link ? (
                          <button key={item.key} type="button" className={className} style={style} title={title} onClick={() => navigate(item.link!)}>{text}</button>
                        ) : (
                          <div key={item.key} className={className} style={style} title={title}>{text}</div>
                        );
                      })}
                      {showNow && <div className="tlNow" data-testid="nowLine" style={{ left: `${percentOf(axis, nowMinute)}%` }} />}
                    </div>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
