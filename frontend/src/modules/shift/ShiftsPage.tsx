import { useSearchParams } from "react-router";
import type { Employee, ScheduleDay } from "../../api/types";
import { useAuth } from "../../auth/AuthProvider";
import { usePermissions } from "../../auth/usePermissions";
import { addDays, formatDay, parseLocal, toLocalDate, weekStart } from "../../forms/time";
import { Drawer } from "../../shell/Drawer";
import { PageHead } from "../../shell/PageHead";
import { useDepartments, useEmployees } from "../org/queries";
import { toEmployeeSubjects } from "../org/timeline";
import { DayPanel } from "./DayPanel";
import { cellText } from "./format";
import { sourceLabels } from "./labels";
import { useSchedule } from "./queries";
import { RosterPanel } from "./RosterPanel";

export function ShiftsPage() {
  const [params, setParams] = useSearchParams();
  const { can } = usePermissions();
  const { user } = useAuth();
  const weekParam = params.get("week");
  const parsedWeek = weekParam ? parseLocal(weekParam) : new Date();
  // 網址參數可能被亂改，日期無效就退回本週，避免送出 NaN 的查詢
  const start = weekStart(Number.isNaN(parsedWeek.getTime()) ? new Date() : parsedWeek);
  const days = Array.from({ length: 7 }, (_, index) => toLocalDate(addDays(start, index)));
  const { data: employeeData } = useEmployees();
  const { data: departmentData } = useDepartments();
  const schedule = useSchedule(days[0], days[6]);
  const employees = employeeData ?? [];
  const subjects = toEmployeeSubjects(employees, departmentData ?? []);
  const byKey = new Map((schedule.data ?? []).map((day) => [`${day.employeeId}:${day.day}`, day]));
  const employeeById = new Map(employees.map((item) => [item.id, item]));
  // 只決定顯示；後端會再檢查是不是人資或直屬主管
  const canEdit = (employee: Employee) => can("shift.manage") || (user?.employeeId != null && employee.managerId === user.employeeId);

  const setPanel = (panel: Record<string, string>) => setParams((current) => {
    const next = new URLSearchParams(current);
    ["cell", "roster"].forEach((key) => next.delete(key));
    Object.entries(panel).forEach(([key, value]) => next.set(key, value));
    return next;
  });
  const goToWeek = (date: Date) => setParams({ week: toLocalDate(weekStart(date)) });

  const cellParam = params.get("cell");
  const [cellEmployeeId, cellDay] = cellParam ? cellParam.split(":") : [null, null];
  const selectedDay: ScheduleDay | undefined = cellParam ? byKey.get(`${cellEmployeeId}:${cellDay}`) : undefined;
  const rosterEmployee = params.get("roster") ? employeeById.get(Number(params.get("roster"))) : undefined;
  const cellEmployee = selectedDay ? employeeById.get(selectedDay.employeeId) : undefined;
  const open = Boolean((selectedDay && cellEmployee) || rosterEmployee);
  const title = rosterEmployee ? `${rosterEmployee.name}的週班表` : cellEmployee && selectedDay ? `${cellEmployee.name} ${formatDay(selectedDay.day)}` : "";

  const groups: { name: string; subjects: typeof subjects }[] = [];
  for (const subject of subjects) {
    const last = groups[groups.length - 1];
    if (last && last.name === subject.group) last.subjects.push(subject); else groups.push({ name: subject.group, subjects: [subject] });
  }

  return (
    <div className="inner">
      <PageHead headline="Shifts" />
      <div className="weekBar">
        <button className="secondary" type="button" onClick={() => goToWeek(addDays(start, -7))}>上一週</button>
        <button className="secondary" type="button" onClick={() => goToWeek(new Date())}>本週</button>
        <button className="secondary" type="button" onClick={() => goToWeek(addDays(start, 7))}>下一週</button>
        <span className="range">{formatDay(days[0])} – {formatDay(days[6])}</span>
      </div>
      {schedule.isError && <div className="formError" role="alert">班表載入失敗</div>}
      <div className="tableWrap">
        <table className="shiftGrid">
          <thead>
            <tr><th>員工</th>{days.map((day) => <th key={day}>{formatDay(day)}</th>)}</tr>
          </thead>
          <tbody>
            {groups.map((group) => [
              <tr key={`group-${group.name}`} className="shiftGroup"><td colSpan={8}>{group.name}</td></tr>,
              ...group.subjects.map((subject) => (
                <tr key={subject.id} aria-label={subject.label}>
                  <th scope="row"><button className="textLink" type="button" onClick={() => setPanel({ roster: String(subject.id) })}>{subject.label}</button></th>
                  {days.map((day) => {
                    const resolved = byKey.get(`${subject.id}:${day}`);
                    if (!resolved) return <td key={day} />;
                    return (
                      <td key={day}>
                        <button
                          type="button"
                          aria-label={`${subject.label} ${formatDay(day)} ${cellText(resolved)}，${sourceLabels[resolved.source]}`}
                          className={`shiftCell shiftSource-${resolved.source}${resolved.source === "override" ? " shiftOverride" : ""}`}
                          onClick={() => setPanel({ cell: `${subject.id}:${day}` })}
                        >
                          {cellText(resolved)}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              )),
            ])}
          </tbody>
        </table>
      </div>
      <Drawer open={open} title={title} onClose={() => setPanel({})}>
        {selectedDay && cellEmployee && <DayPanel day={selectedDay} employee={cellEmployee} canEdit={canEdit(cellEmployee)} onDone={() => setPanel({})} />}
        {rosterEmployee && <RosterPanel key={rosterEmployee.id} employee={rosterEmployee} canEdit={canEdit(rosterEmployee)} />}
      </Drawer>
    </div>
  );
}
