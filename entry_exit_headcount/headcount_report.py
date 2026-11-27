# ============================================================
# FILE: entry_exit_headcount/headcount_report.py
# PURPOSE: Generates daily and monthly headcount reports from
#          the HeadcountEvent records stored in the database.
# USE CASE: Entry/Exit Headcount (Use Case 2)
#
# HOW IT WORKS:
#   - get_daily_report(): sums IN/OUT events for one calendar day.
#   - get_monthly_report(): sums per-day for a full month with running
#     "currently inside" count carried forward day to day.
#   - opening_count: number of people who were already inside at the
#     start of the reporting period (passed from API query param).
#
# DEBUG TIPS:
#   - Report shows zeros but events exist in DB?
#       → Check gate_name matches exactly (default: "Plant Entrance Gate 3").
#       → Check event_timestamp timezone: DB stores UTC, report uses UTC range.
#   - Report date mismatch by 1 day?
#       → event_timestamp is stored as UTC. Local timezone offset can shift
#          events to a different calendar day. Check server timezone.
#   - closing_count going negative?
#       → opening_count incorrect, or IN/OUT events unbalanced. Check DB directly:
#          SELECT direction, COUNT(*) FROM headcount_events GROUP BY direction;
#   - SQLAlchemy query errors?
#       → Confirm HeadcountEvent table exists: run main.py once to create tables.
#
# DEPENDENCIES:
#   - shared/models.py    → HeadcountEvent (SQLAlchemy model)
#   - SQLAlchemy session  → passed in __init__(db)
# ============================================================

from datetime import date, datetime, time, timedelta
from sqlalchemy import func
from shared.models import HeadcountEvent


class HeadcountReport:
    """
    Generates daily and monthly headcount reports from stored crossing events.

    Usage:
        report = HeadcountReport(db)
        daily = report.get_daily_report()
        monthly = report.get_monthly_report(year=2026, month=11)
    """

    def __init__(self, db):
        self.db = db

    def get_daily_report(self, report_date=None, gate_name="Gate 3", opening_count=0):
        """
        Generate total IN/OUT and closing count for one day.

        Args:
            report_date   (date): Day to report. Defaults to today.
            gate_name     (str):  Gate identifier (must match DB records).
            opening_count (int):  People inside at day start.

        Returns:
            dict: {gate_name, report_date, opening_count, total_in, total_out, closing_count}

        DEBUG: total_in/out are 0 → check gate_name matches exactly what
               was saved during events (see camera_manager's gate_name setting).
        """
        if report_date is None:
            report_date = date.today()
        start_time = datetime.combine(report_date, time.min)
        end_time = start_time + timedelta(days=1)

        results = (
            self.db.query(HeadcountEvent.direction, func.count(HeadcountEvent.id).label("total"))
            .filter(
                HeadcountEvent.gate_name == gate_name,
                HeadcountEvent.event_timestamp >= start_time,
                HeadcountEvent.event_timestamp < end_time,
            )
            .group_by(HeadcountEvent.direction)
            .all()
        )

        total_in = 0
        total_out = 0
        for direction, total in results:
            if direction == "IN":
                total_in = total
            elif direction == "OUT":
                total_out = total

        return {
            "gate_name": gate_name,
            "report_date": report_date.isoformat(),
            "opening_count": opening_count,
            "total_in": total_in,
            "total_out": total_out,
            "closing_count": opening_count + total_in - total_out,
        }

    def get_monthly_report(self, year=None, month=None, gate_name="Gate 3", opening_count=0):
        """
        Generate a monthly report with per-day breakdowns.
        Running count is carried forward so each day's opening = previous day's closing.

        Returns:
            dict: {gate_name, year, month, opening_count, total_in, total_out,
                   closing_count, daily_reports: [...]}

        DEBUG: Per-day totals wrong → query DB directly:
               SELECT DATE(event_timestamp), direction, COUNT(*) FROM headcount_events
               WHERE gate_name='...' GROUP BY 1, 2;
        """
        today = date.today()
        year = year or today.year
        month = month or today.month

        if month < 1 or month > 12:
            raise ValueError("Month must be between 1 and 12")

        first_day = date(year, month, 1)
        next_month = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        start_time = datetime.combine(first_day, time.min)
        end_time = datetime.combine(next_month, time.min)

        results = (
            self.db.query(
                func.date(HeadcountEvent.event_timestamp).label("event_date"),
                HeadcountEvent.direction,
                func.count(HeadcountEvent.id).label("total"),
            )
            .filter(
                HeadcountEvent.gate_name == gate_name,
                HeadcountEvent.event_timestamp >= start_time,
                HeadcountEvent.event_timestamp < end_time,
            )
            .group_by(func.date(HeadcountEvent.event_timestamp), HeadcountEvent.direction)
            .order_by(func.date(HeadcountEvent.event_timestamp))
            .all()
        )

        daily_data = {}
        for event_date, direction, total in results:
            if event_date not in daily_data:
                daily_data[event_date] = {"total_in": 0, "total_out": 0}
            if direction == "IN":
                daily_data[event_date]["total_in"] = total
            elif direction == "OUT":
                daily_data[event_date]["total_out"] = total

        daily_reports = []
        monthly_in = 0
        monthly_out = 0
        running_count = opening_count
        current_day = first_day

        while current_day < next_month:
            day_key = current_day.isoformat()
            day_data = daily_data.get(day_key, {"total_in": 0, "total_out": 0})
            total_in = day_data["total_in"]
            total_out = day_data["total_out"]
            day_opening = running_count
            running_count = max(0, running_count + total_in - total_out)
            daily_reports.append({
                "report_date": day_key,
                "opening_count": day_opening,
                "total_in": total_in,
                "total_out": total_out,
                "closing_count": running_count,
            })
            monthly_in += total_in
            monthly_out += total_out
            current_day += timedelta(days=1)

        return {
            "gate_name": gate_name,
            "year": year,
            "month": month,
            "opening_count": opening_count,
            "total_in": monthly_in,
            "total_out": monthly_out,
            "closing_count": running_count,
            "daily_reports": daily_reports,
        }
